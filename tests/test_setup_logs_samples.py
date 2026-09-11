from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.config import Settings
from app.credentials import CredentialStore
from app.jobs import JobService
from app.kaggle.client import (
    BootstrapResult,
    CredentialState,
    CredentialStatus,
)
from app.models import Base, Job
from app.storage import JobStorage


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        root_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'studio.db'}",
        kaggle_json_path=tmp_path / "home-kaggle.json",
        kaggle_username=None,
        kaggle_api_token=None,
    )


def test_credential_store_permissions_and_runtime_reload(tmp_path: Path) -> None:
    store = CredentialStore(_settings(tmp_path))
    store.save_token("alice", "never-show-this")
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    runtime = store.runtime_settings()
    assert runtime.kaggle_username == "alice"
    assert runtime.kaggle_api_token == "never-show-this"
    assert runtime.kaggle_json_path == store.path


class AcceptedService:
    def credential_status(self, validate: bool = False) -> CredentialStatus:
        assert validate
        return CredentialStatus(
            CredentialState.present,
            "project credential file",
            "alice",
            "Credentials were accepted by the Kaggle API.",
        )


@pytest.mark.asyncio
async def test_setup_save_redacts_secret_and_enforces_local_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = CredentialStore(_settings(tmp_path))
    monkeypatch.setattr(main_module, "credential_store", store)
    monkeypatch.setattr(main_module, "_reload_kaggle_service", lambda: AcceptedService())
    transport = httpx.ASGITransport(app=main_module.app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        rejected = await client.post(
            "/setup/credentials",
            headers={"Origin": "http://evil.example"},
            data={"username": "alice", "api_token": "never-show-this"},
        )
        assert rejected.status_code == 403
        saved = await client.post(
            "/setup/credentials",
            headers={"Origin": "http://localhost"},
            data={"username": "alice", "api_token": "never-show-this"},
        )
    assert saved.status_code == 200
    assert "never-show-this" not in saved.text
    assert "never-show-this" in store.path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_bootstrap_is_explicit_and_mockable(monkeypatch: pytest.MonkeyPatch) -> None:
    class BootstrapService:
        calls = 0

        def bootstrap(self) -> BootstrapResult:
            self.calls += 1
            return BootstrapResult("alice", "alice/jobs", "alice/runner")

        def credential_status(self, validate: bool = False) -> CredentialStatus:
            return CredentialStatus(CredentialState.present, "test", "alice", "Ready.")

    service = BootstrapService()
    monkeypatch.setattr(main_module, "kaggle_service", service)
    monkeypatch.setattr(main_module.health_service, "client", service)
    transport = httpx.ASGITransport(app=main_module.app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (await client.get("/setup")).status_code == 200
        assert service.calls == 0
        result = await client.post(
            "/setup/bootstrap", headers={"Origin": "http://localhost"}
        )
    assert result.status_code == 200
    assert service.calls == 1
    assert "alice/runner" in result.text


@pytest.mark.asyncio
async def test_sample_queue_and_logs_api_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ui.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = JobStorage(_settings(tmp_path))
    service = JobService(storage)
    monkeypatch.setattr(main_module, "job_service", service)

    def session_override():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[main_module.db_session] = session_override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            dashboard = await client.get("/")
            assert "Quick queue" in dashboard.text
            assert "Bareilly" in dashboard.text or "festival" in dashboard.text.lower()
            queued = await client.post(
                "/campaigns/samples/pizza_onboarding/queue",
                follow_redirects=False,
            )
            assert queued.status_code == 303
            job_id = queued.headers["location"].rsplit("/", 1)[-1]
            with factory() as session:
                job = session.get(Job, job_id)
                assert job is not None
                campaign = json.loads(job.campaign_json or "{}")
                assert job.mode == "generate_still"
                assert job.strategy == "credit_saver"
                assert job.campaign_size == 3
                assert len(campaign["reels"]) == 3
            storage.append_log(job_id, "[2026-01-01 00:00:01 UTC] searchable event")
            logs = await client.get("/api/logs", params={"status": "queued", "text": "searchable"})
            assert logs.status_code == 200
            assert logs.json()["entries"][0]["job_id"] == job_id
            page = await client.get("/logs")
            assert "Chronological stream" in page.text
            assert "Auto-scroll" in page.text
    finally:
        main_module.app.dependency_overrides.clear()
        engine.dispose()
