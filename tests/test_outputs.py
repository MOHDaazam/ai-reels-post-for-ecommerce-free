from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.config import Settings
from app.jobs import JobService
from app.models import Base, Job, JobStatus
from app.outputs import build_campaign_zip, persist_kaggle_outputs
from app.storage import JobStorage
from app.validation import ValidationError

JOB_ID = "a4e95a21-70dd-4f03-b6cb-1a3d783faf22"


def _download_tree(root: Path) -> list[Path]:
    nested = root / "outputs"
    nested.mkdir(parents=True)
    (root / "result.mp4").write_bytes(b"legacy")
    (nested / "reel_001.mp4").write_bytes(b"one")
    (nested / "reel_002.mp4").write_bytes(b"two")
    (nested / "reel_001_script.txt").write_text("हिंदी script", encoding="utf-8")
    (nested / "reel_002_script.txt").write_text("English script", encoding="utf-8")
    (nested / "reel_001.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nएक", encoding="utf-8")
    (nested / "reel_002.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nTwo", encoding="utf-8")
    (nested / "reel_001_thumbnail.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = {
        "status": "succeeded",
        "strategy": "credit_saver",
        "delivery": {"reels": 1, "shots": 3, "shot_transition": "crossfade"},
        "warnings": [{"reel_index": 1, "warning": "TTS fallback"}],
        "outputs": [
            {
                "reel_index": 0,
                "filename": "reel_001.mp4",
                "script_filename": "reel_001_script.txt",
                "srt_filename": "reel_001.srt",
                "thumbnail_filename": "reel_001_thumbnail.png",
                "reused": False,
            },
            {
                "reel_index": 1,
                "filename": "reel_002.mp4",
                "script_filename": "reel_002_script.txt",
                "srt_filename": "reel_002.srt",
                "reused": True,
                "source_reel_index": 0,
            },
        ],
    }
    (nested / "campaign_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return [path for path in root.rglob("*") if path.is_file()]


def test_multi_output_persistence_and_campaign_zip(tmp_path: Path) -> None:
    download = tmp_path / "download"
    files = _download_tree(download)
    output = tmp_path / "local-output"

    metadata = persist_kaggle_outputs(download, files, output)
    archive = build_campaign_zip(output, metadata, job_id=JOB_ID)

    assert [item["reel_id"] for item in metadata["outputs"]] == ["reel-001", "reel-002"]
    assert metadata["outputs"][1]["reused"] is True
    assert metadata["strategy"] == "credit_saver"
    assert metadata["delivery"]["shot_transition"] == "crossfade"
    assert (output / "result.mp4").read_bytes() == b"legacy"
    assert (output / "reels" / "reel_002.mp4").read_bytes() == b"two"
    assert (output / "scripts" / "reel_001_script.txt").is_file()
    assert (output / "captions" / "reel_001.srt").is_file()
    assert (output / "thumbnails" / "reel_001_thumbnail.png").is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert {
        "README.txt",
        "output_metadata.json",
        "reels/reel_001.mp4",
        "reels/reel_002.mp4",
        "scripts/reel_001_script.txt",
        "captions/reel_002.srt",
        "manifests/campaign_manifest.json",
    } <= names


def test_download_path_and_manifest_traversal_are_rejected(tmp_path: Path) -> None:
    download = tmp_path / "download"
    download.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"bad")
    with pytest.raises(ValidationError, match="escapes"):
        persist_kaggle_outputs(download, [outside], tmp_path / "output")

    (download / "result.mp4").write_bytes(b"legacy")
    (download / "manifest.json").write_text(
        json.dumps({"outputs": [{"reel_index": 0, "filename": "../outside.mp4"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="Unsafe reel filename"):
        persist_kaggle_outputs(
            download,
            list(download.iterdir()),
            tmp_path / "other-output",
        )


def test_legacy_output_without_manifest_is_preserved(tmp_path: Path) -> None:
    download = tmp_path / "download"
    download.mkdir()
    result = download / "result.mp4"
    result.write_bytes(b"old")
    metadata = persist_kaggle_outputs(download, [result], tmp_path / "output")
    assert metadata["outputs"] == [
        {
            "index": 0,
            "reel_index": 0,
            "reel_id": "reel-001",
            "filename": "reel_001.mp4",
            "script_filename": None,
            "srt_filename": None,
            "thumbnail_filename": None,
            "legacy": True,
        }
    ]
    assert (tmp_path / "output" / "result.mp4").read_bytes() == b"old"


@pytest.mark.asyncio
async def test_validated_reel_and_zip_endpoints(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = JobStorage(
        Settings(root_dir=tmp_path, data_dir=tmp_path / "data", database_url="sqlite://")
    )
    storage.ensure_layout(JOB_ID)
    reel = storage.output_asset(JOB_ID, "reels", "reel_001.mp4")
    reel.parent.mkdir(parents=True)
    reel.write_bytes(b"video")
    script = storage.output_asset(JOB_ID, "scripts", "reel_001_script.txt")
    script.parent.mkdir(parents=True)
    script.write_text("script", encoding="utf-8")
    srt = storage.output_asset(JOB_ID, "captions", "reel_001.srt")
    srt.parent.mkdir(parents=True)
    srt.write_text("captions", encoding="utf-8")
    metadata = {
        "outputs": [
            {
                "index": 0,
                "reel_index": 0,
                "reel_id": "reel-001",
                "filename": reel.name,
                "script_filename": script.name,
                "srt_filename": srt.name,
            }
        ]
    }
    build_campaign_zip(storage.output_dir(JOB_ID), metadata, job_id=JOB_ID)
    with factory() as session:
        session.add(
            Job(
                id=JOB_ID,
                status=JobStatus.completed.value,
                mode="generate_still",
                prompt="campaign",
                negative_prompt="",
                aspect_ratio="square",
                duration_preset="short_25",
                width=512,
                height=512,
                num_frames=25,
                output_filename="result.mp4",
                output_manifest_json=json.dumps(metadata),
            )
        )
        session.commit()

    previous = main_module.job_service
    main_module.job_service = JobService(storage)

    def session_override():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[main_module.db_session] = session_override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            for url in (
                f"/jobs/{JOB_ID}/reels/reel-001/preview",
                f"/jobs/{JOB_ID}/reels/0/download",
                f"/jobs/{JOB_ID}/reels/reel-001/script",
                f"/jobs/{JOB_ID}/reels/0/captions",
                f"/jobs/{JOB_ID}/campaign.zip",
            ):
                assert (await client.get(url)).status_code == 200
            assert (await client.get(f"/jobs/{JOB_ID}/reels/../preview")).status_code != 200
            assert (
                await client.get(f"/jobs/{JOB_ID}/reels/reel-999/download")
            ).status_code == 404
    finally:
        main_module.job_service = previous
        main_module.app.dependency_overrides.clear()
        engine.dispose()
