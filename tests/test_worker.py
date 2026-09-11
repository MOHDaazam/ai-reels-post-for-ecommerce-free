from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.worker as worker_module
from app.config import Settings
from app.kaggle.client import (
    BootstrapResult,
    CredentialStatus,
    KernelState,
    Submission,
)
from app.models import Base, Job, JobStatus
from app.storage import JobStorage
from app.worker import JobWorker, KaggleOrchestrator


class FakeKaggle:
    def __init__(self, statuses: list[KernelState], *, produce_mp4: bool = True) -> None:
        self.statuses = statuses
        self.produce_mp4 = produce_mp4
        self.submissions: list[str] = []
        self.polls: list[str] = []
        self.downloads: list[str] = []

    def credential_status(self, validate: bool = False) -> CredentialStatus:
        raise AssertionError("worker should not probe credentials directly")

    def bootstrap(self) -> BootstrapResult:
        raise AssertionError("worker should submit through the client")

    def submit_job(self, job_id: str, job_dir: Path) -> Submission:
        assert (job_dir / "job.json").is_file()
        self.submissions.append(job_id)
        return Submission("alice/video-studio-runner", "7")

    def poll(self, kernel_ref: str) -> KernelState:
        self.polls.append(kernel_ref)
        return self.statuses.pop(0)

    def download_outputs(self, kernel_ref: str, dest: Path) -> list[Path]:
        self.downloads.append(kernel_ref)
        dest.mkdir(parents=True, exist_ok=True)
        log = dest / "run.log"
        log.write_text("remote log", encoding="utf-8")
        files = [log]
        if self.produce_mp4:
            result = dest / "result.mp4"
            result.write_bytes(b"mp4")
            files.append(result)
            manifest = dest / "manifest.json"
            manifest.write_text(
                '{"status":"succeeded","outputs":[{"reel_index":0,'
                '"script_filename":"reel_001_script.txt","srt_filename":"reel_001.srt"}]}',
                encoding="utf-8",
            )
            files.append(manifest)
        return files


def build_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker_module, "get_session", factory)
    cfg = Settings(
        root_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        kaggle_poll_initial_seconds=0,
        kaggle_poll_max_seconds=0,
    )
    storage = JobStorage(cfg)
    return engine, factory, storage, cfg


def insert_job(factory: sessionmaker, storage: JobStorage, status: str) -> Job:
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
    with factory() as session:
        session.add(job)
        session.commit()
    storage.ensure_layout(job.id)
    storage.write_job_json(job.id, {"id": job.id})
    return job


def load(factory: sessionmaker) -> Job:
    with factory() as session:
        return session.get_one(Job, "a4e95a21-70dd-4f03-b6cb-1a3d783faf22")


@pytest.mark.asyncio
async def test_submit_poll_download_completes_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, cfg = build_context(tmp_path, monkeypatch)
    job = insert_job(factory, storage, JobStatus.queued.value)
    client = FakeKaggle([KernelState("complete")])

    await KaggleOrchestrator(client=client, storage=storage, cfg=cfg).process(job)

    completed = load(factory)
    assert completed.status == JobStatus.completed.value
    assert completed.kaggle_dataset_version == "7"
    assert completed.output_filename == "result.mp4"
    assert "reel_001_script.txt" in (completed.output_manifest_json or "")
    assert storage.output_mp4(job.id).read_bytes() == b"mp4"
    assert client.submissions == [job.id]
    assert client.downloads == ["alice/video-studio-runner"]
    assert "remote log" in storage.read_logs(job.id)
    engine.dispose()


@pytest.mark.asyncio
async def test_mocked_multi_output_download_is_persisted_transactionally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, cfg = build_context(tmp_path, monkeypatch)
    job = insert_job(factory, storage, JobStatus.running.value)
    with factory() as session:
        stored = session.get_one(Job, job.id)
        stored.kaggle_kernel_ref = "alice/running"
        session.commit()

    class MultiOutputKaggle(FakeKaggle):
        def download_outputs(self, kernel_ref: str, dest: Path) -> list[Path]:
            dest.mkdir(parents=True)
            outputs = dest / "outputs"
            outputs.mkdir()
            result = dest / "result.mp4"
            result.write_bytes(b"legacy")
            files = [result]
            manifest_outputs = []
            for index in range(2):
                number = index + 1
                video = outputs / f"reel_{number:03d}.mp4"
                script = outputs / f"reel_{number:03d}_script.txt"
                srt = outputs / f"reel_{number:03d}.srt"
                video.write_bytes(f"video-{number}".encode())
                script.write_text(f"script-{number}", encoding="utf-8")
                srt.write_text(f"caption-{number}", encoding="utf-8")
                files.extend((video, script, srt))
                manifest_outputs.append(
                    {
                        "reel_index": index,
                        "filename": video.name,
                        "script_filename": script.name,
                        "srt_filename": srt.name,
                    }
                )
            manifest = outputs / "campaign_manifest.json"
            manifest.write_text(
                json.dumps({"status": "succeeded", "outputs": manifest_outputs}),
                encoding="utf-8",
            )
            files.append(manifest)
            return files

    client = MultiOutputKaggle([KernelState("complete")])
    await KaggleOrchestrator(client=client, storage=storage, cfg=cfg).process(job)

    completed = load(factory)
    metadata = json.loads(completed.output_manifest_json or "{}")
    assert completed.status == JobStatus.completed.value
    assert [item["reel_id"] for item in metadata["outputs"]] == ["reel-001", "reel-002"]
    assert metadata["campaign_zip_filename"] == "campaign.zip"
    with zipfile.ZipFile(storage.campaign_zip(job.id)) as bundle:
        assert "reels/reel_002.mp4" in bundle.namelist()
        zipped_metadata = json.loads(bundle.read("output_metadata.json"))
        assert zipped_metadata["campaign_zip_filename"] == "campaign.zip"
    engine.dispose()


@pytest.mark.asyncio
async def test_restart_recovers_interrupted_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, cfg = build_context(tmp_path, monkeypatch)
    job = insert_job(factory, storage, JobStatus.submitting.value)
    client = FakeKaggle([KernelState("complete")])

    await KaggleOrchestrator(client=client, storage=storage, cfg=cfg).process(job)

    assert client.submissions == [job.id]
    assert load(factory).status == JobStatus.completed.value
    assert "Recovering an interrupted submission" in storage.read_logs(job.id)
    engine.dispose()


@pytest.mark.asyncio
async def test_restart_resumes_known_kernel_without_resubmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, cfg = build_context(tmp_path, monkeypatch)
    job = insert_job(factory, storage, JobStatus.running.value)
    with factory() as session:
        stored = session.get_one(Job, job.id)
        stored.kaggle_kernel_ref = "alice/existing"
        session.commit()
    client = FakeKaggle([KernelState("complete")])

    await KaggleOrchestrator(client=client, storage=storage, cfg=cfg).process(job)

    assert client.submissions == []
    assert client.polls == ["alice/existing"]
    assert load(factory).status == JobStatus.completed.value
    engine.dispose()


@pytest.mark.asyncio
async def test_cancel_requested_is_monitored_to_remote_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, cfg = build_context(tmp_path, monkeypatch)
    job = insert_job(factory, storage, JobStatus.cancel_requested.value)
    with factory() as session:
        stored = session.get_one(Job, job.id)
        stored.kaggle_kernel_ref = "alice/running"
        session.commit()
    client = FakeKaggle([KernelState("canceled", "Stopped on Kaggle")])

    await KaggleOrchestrator(client=client, storage=storage, cfg=cfg).process(job)

    failed = load(factory)
    assert failed.status == JobStatus.failed.value
    assert failed.error_message == "Stopped on Kaggle"
    assert "remote log" in storage.read_logs(job.id)
    engine.dispose()


@pytest.mark.asyncio
async def test_failure_reports_the_runner_error_from_the_remote_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, cfg = build_context(tmp_path, monkeypatch)
    job = insert_job(factory, storage, JobStatus.running.value)
    with factory() as session:
        stored = session.get_one(Job, job.id)
        stored.kaggle_kernel_ref = "alice/running"
        session.commit()

    class FailingKaggle(FakeKaggle):
        def download_outputs(self, kernel_ref: str, dest: Path) -> list[Path]:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "manifest.json").write_text(
                '{"status":"failed","error":"RuntimeError: no internet access"}',
                encoding="utf-8",
            )
            return [dest / "manifest.json"]

    client = FailingKaggle([KernelState("error")])

    await KaggleOrchestrator(client=client, storage=storage, cfg=cfg).process(job)

    failed = load(factory)
    assert failed.status == JobStatus.failed.value
    assert failed.error_message == "RuntimeError: no internet access"
    engine.dispose()


@pytest.mark.asyncio
async def test_completed_kernel_without_mp4_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, cfg = build_context(tmp_path, monkeypatch)
    job = insert_job(factory, storage, JobStatus.running.value)
    with factory() as session:
        stored = session.get_one(Job, job.id)
        stored.kaggle_kernel_ref = "alice/running"
        session.commit()
    client = FakeKaggle([KernelState("complete")], produce_mp4=False)

    await KaggleOrchestrator(client=client, storage=storage, cfg=cfg).process(job)

    failed = load(factory)
    assert failed.status == JobStatus.failed.value
    assert "no MP4" in (failed.error_message or "")
    engine.dispose()


def test_worker_prioritizes_restart_recovery_over_new_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, storage, _cfg = build_context(tmp_path, monkeypatch)
    queued = insert_job(factory, storage, JobStatus.queued.value)
    active = Job(
        id="9bbcd97e-5ef5-481d-a0e0-a16f1ca9a65b",
        status=JobStatus.running.value,
        mode="generate_still",
        prompt="active",
        negative_prompt="",
        aspect_ratio="square",
        duration_preset="short_25",
        width=512,
        height=512,
        num_frames=25,
    )
    with factory() as session:
        session.add(active)
        session.commit()

    selected = JobWorker()._next_queued()
    assert selected is not None
    assert selected.id == active.id
    assert selected.id != queued.id
    engine.dispose()
