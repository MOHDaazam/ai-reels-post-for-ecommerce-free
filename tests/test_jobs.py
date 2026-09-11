from __future__ import annotations

from collections.abc import Generator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.jobs import CreateJobInput, JobService
from app.models import Base, Job, JobStatus
from app.storage import JobStorage
from app.validation import ValidationError


@pytest.fixture
def job_context(tmp_path: Path) -> Generator[tuple[Session, JobService, JobStorage]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    storage = JobStorage(
        Settings(
            root_dir=tmp_path,
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'studio.db'}",
        )
    )
    yield session, JobService(storage), storage
    session.close()
    engine.dispose()


def image_upload() -> UploadFile:
    return UploadFile(
        filename="product.png", file=BytesIO(b"\x89PNG\r\n\x1a\nimage-data")
    )


@pytest.mark.asyncio
async def test_create_job_validates_mode_upload_pairing(job_context) -> None:
    session, service, _storage = job_context
    with pytest.raises(ValidationError, match="Upload a product image"):
        await service.create(
            session, CreateJobInput(mode="uploaded_image", prompt="A clean shot")
        )
    with pytest.raises(ValidationError, match="Leave the image empty"):
        await service.create(
            session,
            CreateJobInput(
                mode="generate_still", prompt="A clean shot", image=image_upload()
            ),
        )
    assert service.list_jobs(session) == []


@pytest.mark.asyncio
async def test_create_job_persists_normalized_form_and_isolated_manifest(
    job_context,
) -> None:
    session, service, storage = job_context
    job = await service.create(
        session,
        CreateJobInput(
            mode="uploaded_image",
            prompt="  Rotate the product  ",
            negative_prompt=" blur ",
            seed="42",
            aspect_ratio="square",
            duration_preset="short_25",
            image=image_upload(),
        ),
    )
    assert job.status == JobStatus.queued.value
    assert (job.prompt, job.negative_prompt, job.seed) == (
        "Rotate the product",
        "blur",
        42,
    )
    assert (job.width, job.height, job.num_frames) == (512, 512, 25)
    manifest = (storage.job_dir(job.id) / "job.json").read_text(encoding="utf-8")
    assert job.id in manifest
    assert "source.png" in manifest
    assert "Queued locally" in storage.read_logs(job.id)


def add_job(session: Session, status: str) -> Job:
    job = Job(
        id="a4e95a21-70dd-4f03-b6cb-1a3d783faf22",
        status=status,
        mode="generate_still",
        prompt="prompt",
        negative_prompt="",
        aspect_ratio="square",
        duration_preset="short_25",
        width=512,
        height=512,
        num_frames=25,
    )
    session.add(job)
    session.commit()
    return job


def test_cancel_queued_is_terminal_but_running_requests_remote_manual_stop(
    job_context,
) -> None:
    session, service, storage = job_context
    job = add_job(session, JobStatus.queued.value)
    storage.ensure_layout(job.id)
    canceled = service.cancel(session, job.id)
    assert canceled.status == JobStatus.canceled.value
    assert canceled.finished_at is not None
    assert "nothing was submitted" in storage.read_logs(job.id)

    canceled.status = JobStatus.running.value
    canceled.finished_at = None
    session.commit()
    requested = service.cancel(session, job.id)
    assert requested.status == JobStatus.cancel_requested.value
    assert requested.finished_at is None
    assert "stop the running kernel manually" in storage.read_logs(job.id)


@pytest.mark.parametrize(
    "terminal",
    [JobStatus.failed.value, JobStatus.canceled.value, JobStatus.completed.value],
)
def test_retry_resets_remote_and_terminal_state(job_context, terminal: str) -> None:
    session, service, storage = job_context
    job = add_job(session, terminal)
    storage.ensure_layout(job.id)
    job.error_message = "old failure"
    job.kaggle_kernel_ref = "user/kernel"
    job.kaggle_dataset_version = "9"
    job.output_filename = "result.mp4"
    session.commit()

    retried = service.retry(session, job.id)
    assert retried.status == JobStatus.queued.value
    assert retried.error_message is None
    assert retried.kaggle_kernel_ref is None
    assert retried.kaggle_dataset_version is None
    assert retried.output_filename is None


def test_invalid_state_transitions_are_rejected(job_context) -> None:
    session, service, storage = job_context
    job = add_job(session, JobStatus.running.value)
    storage.ensure_layout(job.id)
    with pytest.raises(ValidationError, match="retried"):
        service.retry(session, job.id)
    job.status = JobStatus.completed.value
    session.commit()
    with pytest.raises(ValidationError, match="canceled"):
        service.cancel(session, job.id)
