"""Serialized Kaggle job worker with restart recovery."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import select

from app.config import Settings, settings
from app.database import get_session
from app.estimates import estimate
from app.jobs import _job_payload
from app.kaggle.client import UNPOLLABLE, KaggleClient, KaggleService
from app.localtime import stamp as local_stamp
from app.models import Job, JobStatus
from app.outputs import build_campaign_zip, persist_kaggle_outputs
from app.storage import JobStorage


class JobOrchestrator(Protocol):
    async def process(self, job: Job) -> None:
        """Claim a queued job, run it remotely, persist outputs and terminal status."""


class KaggleOrchestrator:
    ACTIVE = {
        JobStatus.submitting.value,
        JobStatus.running.value,
        JobStatus.cancel_requested.value,
    }

    def __init__(
        self,
        client: KaggleClient | None = None,
        storage: JobStorage | None = None,
        cfg: Settings | None = None,
    ) -> None:
        self.client = client or KaggleService()
        self.storage = storage or JobStorage()
        self.settings = cfg or settings

    async def process(self, job: Job) -> None:
        job_id = job.id
        try:
            current = self._get(job_id)
            if current is None:
                return
            if current.status == JobStatus.queued.value:
                self._update(
                    job_id,
                    status=JobStatus.submitting.value,
                    started_at=current.started_at or _now(),
                    error_message=None,
                )
                self._log(job_id, "Submitting private dataset version to Kaggle.")
                submission = await asyncio.to_thread(
                    self.client.submit_job, job_id, self.storage.job_dir(job_id)
                )
                refreshed = self._get(job_id)
                next_status = (
                    JobStatus.cancel_requested.value
                    if refreshed is not None
                    and refreshed.status == JobStatus.cancel_requested.value
                    else JobStatus.running.value
                )
                self._update(
                    job_id,
                    status=next_status,
                    kaggle_kernel_ref=submission.kernel_ref,
                    kaggle_dataset_version=submission.dataset_version,
                )
                self._log(
                    job_id,
                    f"Kaggle kernel started: {submission.kernel_ref} "
                    f"(dataset version {submission.dataset_version}).",
                )
                self._log_estimate(job_id)
            await self._monitor(job_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep the worker alive for the next queued job
            self._fail(job_id, exc)

    async def _monitor(self, job_id: str) -> None:
        delay = max(1.0, self.settings.kaggle_poll_initial_seconds)
        last_remote_status: str | None = None
        unreadable_since: float | None = None
        resubmitted = False
        while True:
            job = self._get(job_id)
            if job is None or job.status not in self.ACTIVE:
                return
            if not job.kaggle_kernel_ref:
                # A process can die before submit_job returns. Re-submit the
                # same fixed dataset/kernel resources; Kaggle versions them.
                if job.status in {
                    JobStatus.submitting.value,
                    JobStatus.cancel_requested.value,
                }:
                    self._log(job_id, "Recovering an interrupted submission.")
                    submission = await asyncio.to_thread(
                        self.client.submit_job, job_id, self.storage.job_dir(job_id)
                    )
                    self._update(
                        job_id,
                        status=(
                            JobStatus.cancel_requested.value
                            if job.status == JobStatus.cancel_requested.value
                            else JobStatus.running.value
                        ),
                        kaggle_kernel_ref=submission.kernel_ref,
                        kaggle_dataset_version=submission.dataset_version,
                    )
                    continue
                raise RuntimeError("Active job has no Kaggle kernel reference.")

            state = await asyncio.to_thread(self.client.poll, job.kaggle_kernel_ref)
            remote = state.status.lower()
            if remote != last_remote_status:
                self._log(job_id, f"Kaggle kernel status: {remote}.")
                last_remote_status = remote
            if remote in {"complete", "completed"}:
                await self._complete(job_id, job.kaggle_kernel_ref)
                return
            if remote in {"error", "failed", "canceled", "cancelled"}:
                remote_detail = await self._capture_remote_log(job_id, job.kaggle_kernel_ref)
                detail = (
                    remote_detail
                    or state.failure_message
                    or f"Kaggle kernel ended with status {remote}."
                )
                raise RuntimeError(detail)
            if (
                remote == "not_found"
                and job.status == JobStatus.submitting.value
                and not resubmitted
            ):
                # Recovery from a crash before kernels_push reached Kaggle.
                resubmitted = True
                submission = await asyncio.to_thread(
                    self.client.submit_job, job_id, self.storage.job_dir(job_id)
                )
                self._update(
                    job_id,
                    status=JobStatus.running.value,
                    kaggle_kernel_ref=submission.kernel_ref,
                    kaggle_dataset_version=submission.dataset_version,
                )
                continue
            if remote in UNPOLLABLE:
                now = time.monotonic()
                unreadable_since = unreadable_since or now
                if now - unreadable_since >= self.settings.kaggle_unknown_status_timeout_seconds:
                    raise RuntimeError(
                        "Kaggle stopped reporting a readable status for "
                        f"{job.kaggle_kernel_ref}. Open the kernel on Kaggle to see "
                        "whether it is still running, then retry this job."
                    )
            else:
                unreadable_since = None
                if remote not in {"queued", "running"}:
                    self._log(job_id, f"Waiting on unrecognized Kaggle status '{remote}'.")
            await asyncio.sleep(delay)
            delay = min(delay * 1.6, self.settings.kaggle_poll_max_seconds)

    async def _capture_remote_log(self, job_id: str, kernel_ref: str) -> str | None:
        """A failed kernel is only diagnosable from Kaggle's own log."""
        destination = self.storage.job_dir(job_id) / "kaggle_failure"
        try:
            await asyncio.to_thread(self.client.download_outputs, kernel_ref, destination)
        except Exception as exc:
            self._log(job_id, f"Could not download the Kaggle failure log: {exc}")
            return None
        logs = [
            path
            for path in destination.rglob("*.log")
            if path.is_file() and not path.is_symlink()
        ]
        if not logs:
            self._log(job_id, "Kaggle returned no log for the failed run.")
        for path in logs:
            try:
                self._log(
                    job_id,
                    f"Kaggle failure log ({path.name}):\n"
                    f"{path.read_text(encoding='utf-8', errors='replace')}",
                )
            except OSError as exc:
                self._log(job_id, f"Could not read {path.name}: {exc}")
        return self._remote_error(destination)

    def _remote_error(self, destination: Path) -> str | None:
        """The runner records the real cause in its manifest before re-raising."""
        for path in sorted(destination.rglob("manifest.json")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, str) and error.strip():
                    return error.strip()[:2000]
        return None

    async def _complete(self, job_id: str, kernel_ref: str) -> None:
        download_dir = self.storage.job_dir(job_id) / "kaggle_output"
        files = await asyncio.to_thread(
            self.client.download_outputs, kernel_ref, download_dir
        )
        log_files = [
            path
            for path in download_dir.rglob("*.log")
            if path.is_file() and not path.is_symlink()
        ]
        for log_file in log_files:
            try:
                text = log_file.read_text(encoding="utf-8", errors="replace")
                self._log(job_id, f"Kaggle log:\n{text}")
            except OSError:
                pass
        metadata = await asyncio.to_thread(
            persist_kaggle_outputs,
            download_dir,
            files,
            self.storage.output_dir(job_id),
        )
        metadata["campaign_zip_filename"] = "campaign.zip"
        archive = await asyncio.to_thread(
            build_campaign_zip,
            self.storage.output_dir(job_id),
            metadata,
            job_id=job_id,
        )
        destination = self.storage.output_mp4(job_id)
        self._update(
            job_id,
            status=JobStatus.completed.value,
            output_filename=destination.name,
            output_manifest_json=json.dumps(metadata, ensure_ascii=False),
            error_message=None,
            finished_at=_now(),
        )
        for warning in metadata.get("warnings") or []:
            self._log(job_id, f"Runner warning: {warning}")
        self._log(
            job_id,
            f"Downloaded {len(metadata['outputs'])} reel(s) and built {archive.name}; "
            "job completed.",
        )

    def _get(self, job_id: str) -> Job | None:
        session = get_session()
        try:
            return session.get(Job, job_id)
        finally:
            session.close()

    def _update(self, job_id: str, **values: object) -> None:
        session = get_session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                return
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = _now()
            session.commit()
            session.refresh(job)
            self.storage.write_job_json(job_id, _job_payload(job))
        finally:
            session.close()

    def _fail(self, job_id: str, exc: Exception) -> None:
        message = str(exc).strip()[:2000] or exc.__class__.__name__
        self._update(
            job_id,
            status=JobStatus.failed.value,
            error_message=message,
            finished_at=_now(),
        )
        self._log(job_id, f"Job failed: {message}")

    def _log_estimate(self, job_id: str) -> None:
        """Re-anchor the estimate once Kaggle actually starts the run."""
        session = get_session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                return
            prediction = estimate(session, job, started_at=_now())
            self._log(job_id, prediction.describe())
        finally:
            session.close()

    def _log(self, job_id: str, message: str) -> None:
        self.storage.append_log(job_id, f"[{_timestamp()}] {message}")


class JobWorker:
    def __init__(
        self,
        orchestrator: JobOrchestrator | None = None,
        storage: JobStorage | None = None,
        poll_seconds: float = 2.0,
    ) -> None:
        self.orchestrator = orchestrator or KaggleOrchestrator()
        self.storage = storage or JobStorage()
        self.poll_seconds = poll_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            job = self._next_queued()
            if job is not None:
                await self.orchestrator.process(job)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    def _next_queued(self) -> Job | None:
        session = get_session()
        try:
            active = (
                select(Job)
                .where(
                    Job.status.in_(
                        [
                            JobStatus.submitting.value,
                            JobStatus.running.value,
                            JobStatus.cancel_requested.value,
                        ]
                    )
                )
                .order_by(Job.created_at.asc())
                .limit(1)
            )
            recover = session.scalars(active).first()
            if recover is not None:
                return recover
            stmt = (
                select(Job)
                .where(Job.status == JobStatus.queued.value)
                .order_by(Job.created_at.asc())
                .limit(1)
            )
            return session.scalars(stmt).first()
        finally:
            session.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return local_stamp()
