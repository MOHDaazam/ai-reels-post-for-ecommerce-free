from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine
from app.kaggle.client import (
    CredentialProbe,
    CredentialState,
    CredentialStatus,
    KaggleClient,
)
from app.localtime import isoformat as local_iso


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    ok: bool
    detail: str
    level: str  # ok | warn | error | pending


@dataclass(frozen=True)
class HealthReport:
    ready: bool
    checks: list[Check]
    credentials: CredentialStatus
    generated_at: str


class HealthService:
    def __init__(
        self,
        probe: CredentialProbe | None = None,
        client: KaggleClient | None = None,
    ) -> None:
        self.client = client
        self.probe = probe or CredentialProbe()

    def report(self) -> HealthReport:
        creds = (
            self.client.credential_status()
            if self.client is not None
            else self.probe.credential_status()
        )
        checks = [
            self._app(),
            self._sqlite(),
            self._data_dir(),
            self._credentials(creds),
            Check(
                key="orchestration",
                label="Kaggle orchestration",
                ok=settings.kaggle_runner_dir.joinpath("run.py").is_file(),
                detail=(
                    "Private dataset/kernel worker is wired and serialized."
                    if settings.kaggle_runner_dir.joinpath("run.py").is_file()
                    else f"Runner template missing: {settings.kaggle_runner_dir / 'run.py'}"
                ),
                level=(
                    "ok"
                    if settings.kaggle_runner_dir.joinpath("run.py").is_file()
                    else "error"
                ),
            ),
            Check(
                key="gpu_runner",
                label="GPU runner",
                ok=settings.kaggle_runner_dir.joinpath("run.py").is_file(),
                detail=(
                    "Bundled FLUX still and LTX image-to-video runner targets Kaggle T4."
                    if settings.kaggle_runner_dir.joinpath("run.py").is_file()
                    else "GPU runner is missing."
                ),
                level=(
                    "ok"
                    if settings.kaggle_runner_dir.joinpath("run.py").is_file()
                    else "error"
                ),
            ),
        ]
        blocking = [c for c in checks if c.level == "error"]
        return HealthReport(
            ready=not blocking,
            checks=checks,
            credentials=creds,
            generated_at=local_iso(),
        )

    def _app(self) -> Check:
        return Check(
            key="app",
            label="Studio app",
            ok=True,
            detail=f"{settings.app_name} bound for localhost use.",
            level="ok",
        )

    def _sqlite(self) -> Check:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                inspect(engine).get_table_names()
            return Check(
                key="sqlite",
                label="SQLite",
                ok=True,
                detail=f"Database ready at {settings.db_path}.",
                level="ok",
            )
        except Exception as exc:  # noqa: BLE001
            return Check(
                key="sqlite",
                label="SQLite",
                ok=False,
                detail=f"Database check failed: {exc}",
                level="error",
            )

    def _data_dir(self) -> Check:
        try:
            settings.jobs_dir.mkdir(parents=True, exist_ok=True)
            probe = settings.jobs_dir / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return Check(
                key="storage",
                label="Job storage",
                ok=True,
                detail=f"Writable jobs directory: {settings.jobs_dir}",
                level="ok",
            )
        except OSError as exc:
            return Check(
                key="storage",
                label="Job storage",
                ok=False,
                detail=f"Cannot write job files: {exc}",
                level="error",
            )

    def _credentials(self, creds: CredentialStatus) -> Check:
        if creds.state is CredentialState.present:
            hint = f" Username: {creds.username_hint}." if creds.username_hint else ""
            return Check(
                key="kaggle_auth",
                label="Kaggle credentials",
                ok=True,
                detail=creds.detail + hint,
                level="ok",
            )
        if creds.state is CredentialState.invalid:
            return Check(
                key="kaggle_auth",
                label="Kaggle credentials",
                ok=False,
                detail=creds.detail,
                level="error",
            )
        return Check(
            key="kaggle_auth",
            label="Kaggle credentials",
            ok=False,
            detail=creds.detail + " Jobs can still be queued locally.",
            level="warn",
        )
