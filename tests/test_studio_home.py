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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        root_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'studio.db'}",
        kaggle_json_path=tmp_path / "kaggle.json",
    )


def _patch_studio_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> sessionmaker:
    cfg = _settings(tmp_path)
    import app.trending_audio as trending_module

    monkeypatch.setattr(config_module, "settings", cfg)
    monkeypatch.setattr(business_profile_module, "settings", cfg)
    monkeypatch.setattr(trending_module, "settings", cfg)
    engine = create_engine(
        cfg.database_url, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = JobStorage(cfg)
    monkeypatch.setattr(main_module, "job_service", JobService(storage))

    def session_override():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[main_module.db_session] = session_override
    return factory


@pytest.mark.asyncio
async def test_dashboard_shows_profile_and_festivals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_studio_db(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/")
    assert page.status_code == 200
    assert "Quick queue" in page.text
    assert "Advanced builder" in page.text
    assert "Navratri" in page.text or "Diwali" in page.text


@pytest.mark.asyncio
async def test_save_profile_redirects_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_studio_db(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        saved = await client.post(
            "/studio/profile",
            data={
                "vendor_name": "Test Vendor",
                "city": "Bareilly",
                "area": "Civil Lines",
                "business_line": "food_delivery",
            },
            follow_redirects=False,
        )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/?saved=1"
    profile_path = tmp_path / "data" / "business_profile.json"
    assert profile_path.is_file()
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    assert payload["vendor_name"] == "Test Vendor"
    assert payload["city"] == "Bareilly"


@pytest.mark.asyncio
async def test_quick_queue_creates_campaign_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _patch_studio_db(tmp_path, monkeypatch)
    business_profile_module.save_profile(
        {"vendor_name": "Quick Shop", "business_line": "food_delivery"}
    )
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        queued = await client.post("/studio/quick-queue", follow_redirects=False)
    assert queued.status_code == 303
    job_id = queued.headers["location"].rsplit("/", 1)[-1]
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        campaign = json.loads(job.campaign_json or "{}")
        assert job.strategy == "credit_saver"
        assert job.campaign_size == 3
        assert len(campaign["reels"]) == 3


@pytest.mark.asyncio
async def test_festival_queue_unknown_slug_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_studio_db(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/festivals/not-a-festival/queue")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_festival_queue_creates_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _patch_studio_db(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        queued = await client.post(
            "/festivals/diwali-2026/queue", follow_redirects=False
        )
    assert queued.status_code == 303
    job_id = queued.headers["location"].rsplit("/", 1)[-1]
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        campaign = json.loads(job.campaign_json or "{}")
        assert len(campaign["reels"]) == 3
