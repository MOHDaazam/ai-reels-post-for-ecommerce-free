"""Lazy, testable adapter around the official Kaggle Python API."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings, settings

UNKNOWN_STATUS = "unknown"
UNPOLLABLE = {UNKNOWN_STATUS, "not_found"}
READY_DATASET_STATES = {"ready", "active", "complete", "completed"}


class CredentialState(str, Enum):
    missing = "missing"
    present = "present"
    invalid = "invalid"


@dataclass(frozen=True)
class CredentialStatus:
    state: CredentialState
    source: str | None
    username_hint: str | None
    detail: str


@dataclass(frozen=True)
class BootstrapResult:
    username: str
    dataset_ref: str
    kernel_ref: str


@dataclass(frozen=True)
class Submission:
    kernel_ref: str
    dataset_version: str


@dataclass(frozen=True)
class KernelState:
    status: str
    failure_message: str = ""


class KaggleClient(Protocol):
    def credential_status(self, validate: bool = False) -> CredentialStatus: ...

    def bootstrap(self) -> BootstrapResult: ...

    def submit_job(self, job_id: str, job_dir: Path) -> Submission: ...

    def poll(self, kernel_ref: str) -> KernelState: ...

    def download_outputs(self, kernel_ref: str, dest: Path) -> list[Path]: ...


class KaggleApiAdapter(Protocol):
    """Small surface that tests can replace without importing Kaggle."""

    def authenticate(self) -> str: ...

    def validate_identity(self, username: str) -> None: ...

    def dataset_exists(self, dataset_ref: str) -> bool | None: ...

    def kernel_exists(self, kernel_ref: str) -> bool | None: ...

    def dataset_status(self, dataset_ref: str) -> str | None: ...

    def create_dataset(self, folder: Path) -> Any: ...

    def version_dataset(self, folder: Path, notes: str) -> Any: ...

    def kernel_status(self, kernel_ref: str) -> KernelState: ...

    def push_kernel(self, folder: Path) -> Any: ...

    def download_kernel_outputs(self, kernel_ref: str, dest: Path) -> list[Path]: ...


class OfficialKaggleApiAdapter:
    """Official client wrapper. Import and authentication happen only on use."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or settings
        self._api: Any | None = None

    def _client(self) -> Any:
        if self._api is None:
            # Kaggle 2.x introspects KAGGLE_API_TOKEN and populates the
            # authenticated username. Legacy username/key and kaggle.json
            # credentials remain supported by the official client.
            if self.settings.kaggle_username:
                os.environ["KAGGLE_USERNAME"] = self.settings.kaggle_username
            if self.settings.kaggle_api_token:
                os.environ["KAGGLE_API_TOKEN"] = self.settings.kaggle_api_token
            if self.settings.kaggle_json_path.is_file():
                os.environ["KAGGLE_CONFIG_DIR"] = str(
                    self.settings.kaggle_json_path.parent
                )
            try:
                from kaggle.api.kaggle_api_extended import KaggleApi
            except ImportError as exc:
                raise RuntimeError(
                    "The official 'kaggle' package is not installed. Run pip install -e ."
                ) from exc
            api = KaggleApi()
            try:
                api.authenticate()
            except SystemExit as exc:
                raise RuntimeError(
                    "Kaggle authentication is not configured or was rejected."
                ) from exc
            self._api = api
        return self._api

    def authenticate(self) -> str:
        api = self._client()
        username = api.get_config_value(api.CONFIG_NAME_USER)
        if not username:
            raise RuntimeError("Kaggle authenticated but did not return a username.")
        return str(username)

    def validate_identity(self, username: str) -> None:
        # authenticate() only loads credentials. This cheap API request verifies
        # that Kaggle accepts them.
        self._client().kernels_list(user=username, page_size=1)

    def dataset_exists(self, dataset_ref: str) -> bool | None:
        # Kaggle answers GetDatasetStatus with 403 for datasets it will not
        # reveal, so listing owned datasets is the only dependable probe.
        try:
            owned = self._client().dataset_list(mine=True) or []
        except Exception:
            return None
        return any(_same_ref(getattr(item, "ref", ""), dataset_ref) for item in owned)

    def kernel_exists(self, kernel_ref: str) -> bool | None:
        try:
            owned = self._client().kernels_list(mine=True, page_size=100) or []
        except Exception:
            return None
        return any(_same_ref(getattr(item, "ref", ""), kernel_ref) for item in owned)

    def dataset_status(self, dataset_ref: str) -> str | None:
        api = self._client()
        method = getattr(api, "dataset_status", None)
        if method is None:
            return None
        try:
            return _status_name(method(dataset_ref))
        except Exception as exc:  # Kaggle exposes several generated exception types
            if _is_not_found(exc):
                return "not_found"
            if _is_permission_error(exc):
                return UNKNOWN_STATUS
            raise

    def create_dataset(self, folder: Path) -> Any:
        return self._client().dataset_create_new(
            str(folder), public=False, quiet=True, convert_to_csv=False
        )

    def version_dataset(self, folder: Path, notes: str) -> Any:
        return self._client().dataset_create_version(
            str(folder), notes, quiet=True, convert_to_csv=False
        )

    def kernel_status(self, kernel_ref: str) -> KernelState:
        try:
            response = self._client().kernels_status(kernel_ref)
        except Exception as exc:
            if _is_not_found(exc):
                return KernelState("not_found")
            if _is_permission_error(exc):
                return KernelState(UNKNOWN_STATUS)
            raise
        return KernelState(
            status=_status_name(getattr(response, "status", response)),
            failure_message=str(
                getattr(response, "failure_message", None)
                or getattr(response, "failureMessage", None)
                or ""
            ),
        )

    def push_kernel(self, folder: Path) -> Any:
        return self._client().kernels_push(str(folder))

    def download_kernel_outputs(self, kernel_ref: str, dest: Path) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        result = self._client().kernels_output(
            kernel_ref, path=str(dest), force=True, quiet=True
        )
        files = result[0] if isinstance(result, tuple) else result
        return [Path(path) for path in (files or [])]


class CredentialProbe:
    """Inspect local credential files/env without importing Kaggle."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or settings

    def credential_status(self) -> CredentialStatus:
        api_token = (self.settings.kaggle_api_token or "").strip()
        legacy_key = (os.getenv("KAGGLE_KEY") or "").strip()
        token = api_token or legacy_key
        user = (self.settings.kaggle_username or "").strip()
        if token:
            hint = user or None
            variable = "KAGGLE_API_TOKEN" if api_token else "KAGGLE_KEY"
            return CredentialStatus(
                state=CredentialState.present,
                source="environment",
                username_hint=hint,
                detail=f"{variable} is set. Token value is never shown in the UI.",
            )
        path = self.settings.kaggle_json_path
        if path.is_file():
            hint = user or None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    hint = str(payload.get("username") or hint or "") or None
                    if payload.get("key") or payload.get("api_token"):
                        return CredentialStatus(
                            state=CredentialState.present,
                            source="project credential file"
                            if path != Path.home() / ".kaggle" / "kaggle.json"
                            else "kaggle.json",
                            username_hint=hint,
                            detail="Found a local Kaggle credential file. Secret contents are never shown.",
                        )
                return CredentialStatus(
                    state=CredentialState.invalid,
                    source="kaggle.json",
                    username_hint=hint,
                    detail="The Kaggle credential file does not contain a token or key.",
                )
            except (OSError, json.JSONDecodeError):
                return CredentialStatus(
                    state=CredentialState.invalid,
                    source="kaggle.json",
                    username_hint=None,
                    detail="The Kaggle credential file could not be read as JSON.",
                )
        return CredentialStatus(
            state=CredentialState.missing,
            source=None,
            username_hint=None,
            detail="No KAGGLE_API_TOKEN, KAGGLE_KEY, or ~/.kaggle/kaggle.json found.",
        )


class KaggleService:
    """Stages the one-dataset/one-kernel workflow used by the worker."""

    def __init__(
        self,
        cfg: Settings | None = None,
        adapter: KaggleApiAdapter | None = None,
        probe: CredentialProbe | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.settings = cfg or settings
        self.adapter = adapter or OfficialKaggleApiAdapter(self.settings)
        self.probe = probe or CredentialProbe(self.settings)
        self._sleep = sleep
        self._username: str | None = None
        self._validated_status: CredentialStatus | None = None

    def credential_status(self, validate: bool = False) -> CredentialStatus:
        local = self.probe.credential_status()
        if not validate or local.state is not CredentialState.present:
            return self._validated_status or local
        try:
            username = self.adapter.authenticate()
            self.adapter.validate_identity(username)
            self._username = username
            self._validated_status = CredentialStatus(
                CredentialState.present,
                local.source,
                username,
                "Credentials were accepted by the Kaggle API.",
            )
        except Exception as exc:
            self._validated_status = CredentialStatus(
                CredentialState.invalid,
                local.source,
                local.username_hint,
                "Kaggle rejected or could not validate credentials: "
                f"{_safe_error(exc, self.settings.kaggle_api_token)}",
            )
        return self._validated_status

    def bootstrap(self) -> BootstrapResult:
        username = self._require_username()
        dataset_ref = f"{username}/{self.settings.kaggle_dataset_slug}"
        kernel_ref = f"{username}/{self.settings.kaggle_kernel_slug}"
        self._require_runner()

        if self._dataset_present(dataset_ref) is not True:
            self._create_dataset(dataset_ref)
        self._wait_for_dataset(dataset_ref)

        # A kernel is created by a push, which also starts a run. Bootstrap it
        # once with a no-op payload; later jobs reuse the same private slug.
        if self._kernel_present(kernel_ref) is not True:
            with tempfile.TemporaryDirectory(prefix="video-studio-kernel-") as raw:
                self._stage_kernel(Path(raw), kernel_ref, dataset_ref)
                _assert_response(self.adapter.push_kernel(Path(raw)), "kernel bootstrap")
            self._wait_for_bootstrap_kernel(kernel_ref)
        return BootstrapResult(username, dataset_ref, kernel_ref)

    def _create_dataset(self, dataset_ref: str) -> None:
        with tempfile.TemporaryDirectory(prefix="video-studio-bootstrap-") as raw:
            folder = Path(raw)
            self._write_dataset_metadata(folder, dataset_ref)
            (folder / "job.json").write_text(
                json.dumps({"id": "bootstrap", "bootstrap": True}, indent=2),
                encoding="utf-8",
            )
            try:
                _assert_response(self.adapter.create_dataset(folder), "dataset creation")
            except Exception as exc:
                if _is_conflict(exc):
                    return
                raise RuntimeError(self._creation_hint(dataset_ref, exc)) from exc

    def _creation_hint(self, dataset_ref: str, exc: Exception) -> str:
        detail = _safe_error(exc, self.settings.kaggle_api_token)
        message = f"Could not create the private dataset {dataset_ref}: {detail}"
        if _is_permission_error(exc):
            message += (
                " Kaggle returns this when the account cannot create datasets yet. "
                "Verify your phone number on Kaggle, accept the API terms, and make "
                "sure the API token belongs to this account."
            )
        return message

    def _dataset_present(self, dataset_ref: str) -> bool | None:
        exists = self._probe(self.adapter, "dataset_exists", dataset_ref)
        if exists is not None:
            return exists
        status = self._dataset_status(dataset_ref)
        if status == "not_found":
            return False
        if status is None or status == UNKNOWN_STATUS:
            return None
        return True

    def _kernel_present(self, kernel_ref: str) -> bool | None:
        exists = self._probe(self.adapter, "kernel_exists", kernel_ref)
        if exists is not None:
            return exists
        status = self._kernel_status(kernel_ref).status
        if status == "not_found":
            return False
        if status == UNKNOWN_STATUS:
            return None
        return True

    def _dataset_status(self, dataset_ref: str) -> str | None:
        """Status reads are advisory: Kaggle denies them for some accounts."""
        try:
            return self.adapter.dataset_status(dataset_ref)
        except Exception as exc:
            if _is_permission_error(exc) or _is_not_found(exc):
                return UNKNOWN_STATUS
            raise

    def _kernel_status(self, kernel_ref: str) -> KernelState:
        try:
            return self.adapter.kernel_status(kernel_ref)
        except Exception as exc:
            if _is_permission_error(exc) or _is_not_found(exc):
                return KernelState(UNKNOWN_STATUS)
            raise

    @staticmethod
    def _probe(adapter: Any, name: str, ref: str) -> bool | None:
        method = getattr(adapter, name, None)
        if method is None:
            return None
        try:
            return method(ref)
        except Exception:
            return None

    def submit_job(self, job_id: str, job_dir: Path) -> Submission:
        resources = self.bootstrap()
        with tempfile.TemporaryDirectory(prefix=f"video-studio-job-{job_id}-") as raw:
            dataset_dir = Path(raw)
            self._write_dataset_metadata(dataset_dir, resources.dataset_ref)
            shutil.copy2(job_dir / "job.json", dataset_dir / "job.json")
            for upload in (job_dir / "input").glob("*"):
                if upload.is_file():
                    shutil.copy2(upload, dataset_dir / upload.name)
            response = _assert_response(
                self.adapter.version_dataset(
                    dataset_dir, f"Video Studio job {job_id}"
                ),
                "dataset version creation",
            )
            version = _response_version(response)
        self._wait_for_dataset(resources.dataset_ref)
        with tempfile.TemporaryDirectory(prefix=f"video-studio-kernel-{job_id}-") as raw:
            kernel_dir = Path(raw)
            self._stage_kernel(kernel_dir, resources.kernel_ref, resources.dataset_ref)
            _assert_response(self.adapter.push_kernel(kernel_dir), "kernel submission")
        return Submission(resources.kernel_ref, version)

    def poll(self, kernel_ref: str) -> KernelState:
        return self.adapter.kernel_status(kernel_ref)

    def download_outputs(self, kernel_ref: str, dest: Path) -> list[Path]:
        return self.adapter.download_kernel_outputs(kernel_ref, dest)

    def _require_username(self) -> str:
        if self._username:
            return self._username
        status = self.credential_status(validate=True)
        if status.state is not CredentialState.present or not status.username_hint:
            raise RuntimeError(status.detail)
        return status.username_hint

    def _require_runner(self) -> Path:
        run_file = self.settings.kaggle_runner_dir / "run.py"
        if not run_file.is_file():
            raise RuntimeError(f"Kaggle runner is missing: {run_file}")
        for name in (
            "dataset-metadata.template.json",
            "kernel-metadata.template.json",
        ):
            if not self.settings.kaggle_runner_dir.joinpath(name).is_file():
                raise RuntimeError(
                    f"Kaggle runner metadata template is missing: "
                    f"{self.settings.kaggle_runner_dir / name}"
                )
        return run_file

    def _write_dataset_metadata(self, folder: Path, dataset_ref: str) -> None:
        payload = self._read_template("dataset-metadata.template.json")
        payload["id"] = dataset_ref
        (folder / "dataset-metadata.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _stage_kernel(self, folder: Path, kernel_ref: str, dataset_ref: str) -> None:
        shutil.copy2(self._require_runner(), folder / "run.py")
        payload = self._read_template("kernel-metadata.template.json")
        payload["id"] = kernel_ref
        slug = kernel_ref.split("/")[-1]
        if _slugify(str(payload.get("title", ""))) != slug:
            # Kaggle warns and behaves unpredictably when the title does not
            # resolve to the kernel slug.
            payload["title"] = slug.replace("-", " ").title()
        payload["dataset_sources"] = [dataset_ref]
        (folder / "kernel-metadata.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _read_template(self, name: str) -> dict[str, Any]:
        path = self.settings.kaggle_runner_dir / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid Kaggle runner template: {path}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Kaggle runner template must contain an object: {path}")
        return payload

    def _wait_for_dataset(self, dataset_ref: str) -> None:
        deadline = time.monotonic() + self.settings.kaggle_dataset_ready_timeout_seconds
        delay = max(1.0, self.settings.kaggle_poll_initial_seconds)
        while True:
            status = self._dataset_status(dataset_ref)
            if status is None or status in READY_DATASET_STATES or status in UNPOLLABLE:
                # Some accounts cannot read dataset status at all; the version
                # call that follows reports any real problem.
                return
            if status in {"error", "failed", "invalid"}:
                raise RuntimeError(f"Kaggle dataset entered status '{status}'.")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for Kaggle dataset readiness ({status})."
                )
            self._sleep(delay)
            delay = min(delay * 1.6, self.settings.kaggle_poll_max_seconds)

    def _wait_for_bootstrap_kernel(self, kernel_ref: str) -> None:
        deadline = time.monotonic() + self.settings.kaggle_dataset_ready_timeout_seconds
        unverifiable_deadline = time.monotonic() + self.settings.kaggle_poll_max_seconds
        delay = max(1.0, self.settings.kaggle_poll_initial_seconds)
        while True:
            state = self._kernel_status(kernel_ref)
            if state.status in {"complete", "completed"}:
                return
            if state.status in {"error", "failed", "canceled", "cancelled"}:
                raise RuntimeError(
                    state.failure_message
                    or f"Kaggle bootstrap kernel entered status '{state.status}'."
                )
            if state.status in UNPOLLABLE and time.monotonic() >= unverifiable_deadline:
                # The push succeeded but this account cannot read kernel status.
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for Kaggle bootstrap kernel ({state.status})."
                )
            self._sleep(delay)
            delay = min(delay * 1.6, self.settings.kaggle_poll_max_seconds)


def _status_name(value: Any) -> str:
    name = getattr(value, "name", value)
    return str(name).lower().split(".")[-1]


def _response_version(response: Any) -> str:
    for name in ("version_number", "versionNumber", "ref"):
        value = getattr(response, name, None)
        if value is not None:
            return str(value)
    return datetime_version()


def _assert_response(response: Any, operation: str) -> Any:
    error = getattr(response, "error", None)
    status = _status_name(getattr(response, "status", "ok"))
    if error or status in {"error", "failed", "invalid"}:
        raise RuntimeError(f"Kaggle {operation} failed: {error or status}")
    return response


def datetime_version() -> str:
    return str(int(time.time()))


def _slugify(title: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")


def _same_ref(candidate: object, ref: str) -> bool:
    return str(candidate or "").strip().lower() == ref.strip().lower()


def _http_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    for value in (
        getattr(response, "status_code", None),
        getattr(exc, "status", None),
        getattr(exc, "status_code", None),
    ):
        if isinstance(value, int):
            return value
    return None


def _is_not_found(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        _http_status(exc) == 404
        or "404" in text
        or "not found" in text
        or "notfound" in text
    )


def _is_permission_error(exc: Exception) -> bool:
    """Kaggle reports invisible or missing resources as permission failures."""
    text = str(exc).lower()
    return (
        _http_status(exc) == 403
        or "403" in text
        or "forbidden" in text
        or "was denied" in text
        or "cannot access" in text
    )


def _is_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return _http_status(exc) == 409 or "already exists" in text or "already in use" in text


def _safe_error(exc: Exception, *configured_secrets: str | None) -> str:
    text = str(exc).strip().replace("\n", " ")
    file_secrets: list[str] = []
    try:
        payload = json.loads(settings.kaggle_json_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            file_secrets = [
                str(value)
                for key, value in payload.items()
                if key in {"key", "api_token"} and value
            ]
    except (OSError, json.JSONDecodeError):
        pass
    for secret in (
        *configured_secrets,
        *file_secrets,
        settings.kaggle_api_token,
        os.getenv("KAGGLE_API_TOKEN"),
        os.getenv("KAGGLE_KEY"),
    ):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:500] or exc.__class__.__name__
