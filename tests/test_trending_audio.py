from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.business_profile as business_profile_module
import app.config as config_module
import app.main as main_module
from app.config import Settings
from app.jobs import JobService
from app.models import Base, Job
from app.storage import JobStorage
from app.trending_audio import ensure_track_file, get_track, list_tracks


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        root_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'studio.db'}",
        kaggle_json_path=tmp_path / "kaggle.json",
    )


def test_hindi_tracks_listed_first() -> None:
    tracks = list_tracks(language="hindi")
    assert tracks
    assert tracks[0].language == "hindi"
    assert get_track("hindi-food-groove") is not None


def test_ensure_track_file_caches_bundled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _settings(tmp_path)
    import app.trending_audio as trending_module

    monkeypatch.setattr(trending_module, "settings", cfg)
    path = ensure_track_file("hindi-food-groove")
    assert path.is_file()
    assert path.name == "hindi-food-groove.mp3"


@pytest.mark.asyncio
async def test_quick_queue_attaches_trending_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _settings(tmp_path)
    monkeypatch.setattr(config_module, "settings", cfg)
    monkeypatch.setattr(business_profile_module, "settings", cfg)
    engine = create_engine(cfg.database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = JobStorage(cfg)
    import app.trending_audio as trending_module

    monkeypatch.setattr(trending_module, "settings", cfg)
    monkeypatch.setattr(main_module, "job_service", JobService(storage))

    def session_override():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[main_module.db_session] = session_override
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.get("/api/trending-audio/hindi-food-groove/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"].startswith("audio/")
        queued = await client.post(
            "/studio/quick-queue",
            data={"trending_audio_id": "hindi-food-groove"},
            follow_redirects=False,
        )
    assert queued.status_code == 303
    job_id = queued.headers["location"].rsplit("/", 1)[-1]
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.trending_audio_id == "hindi-food-groove"
        assert job.audio_filename is not None
    music = tmp_path / "data" / "jobs" / job_id / "input" / job.audio_filename
    assert music.is_file()


@pytest.mark.asyncio
async def test_trending_audio_api_lists_tracks() -> None:
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/trending-audio", params={"language": "hindi"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tracks"]
    assert any(track["language"] == "hindi" for track in payload["tracks"])
