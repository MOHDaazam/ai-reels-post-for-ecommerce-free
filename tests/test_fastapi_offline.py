from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.main as main_module
from app.models import Base


class OfflineWorker:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def run(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class NetworkForbidden:
    def credential_status(self, validate: bool = False):
        if validate:
            raise AssertionError("startup attempted Kaggle network validation")
        raise AssertionError("unexpected credential probe")


@pytest.mark.asyncio
async def test_fastapi_starts_and_serves_api_without_kaggle_network(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    offline_worker = OfflineWorker()

    def session_override():
        session: Session = factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "worker", offline_worker)
    monkeypatch.setattr(main_module, "kaggle_service", NetworkForbidden())
    main_module.app.dependency_overrides[main_module.db_session] = session_override
    try:
        transport = httpx.ASGITransport(app=main_module.app)
        async with main_module.lifespan(main_module.app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://offline.test"
            ) as client:
                response = await client.get("/api/jobs")
                assert response.status_code == 200
                assert response.json() == []

                bad_id = await client.get("/api/jobs/not-a-uuid")
                assert bad_id.status_code == 400
                assert bad_id.json() == {"detail": "Invalid job id."}
        assert offline_worker.started
        assert offline_worker.stopped
    finally:
        main_module.app.dependency_overrides.clear()
        engine.dispose()
