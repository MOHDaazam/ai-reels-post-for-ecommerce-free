import base64
from dataclasses import replace

import httpx
import pytest

from app import basic_auth as basic_auth_module
from app import main as main_module
from app.config import settings


@pytest.mark.asyncio
async def test_basic_auth_blocks_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_settings = replace(
        settings,
        studio_basic_auth_enabled=True,
        studio_basic_auth_user="napps",
        studio_basic_auth_password="napps",
    )
    monkeypatch.setattr(basic_auth_module, "settings", auth_settings)
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/api/jobs")
        assert denied.status_code == 401
        token = base64.b64encode(b"napps:napps").decode("ascii")
        ok = await client.get("/api/jobs", headers={"Authorization": f"Basic {token}"})
        assert ok.status_code == 200


@pytest.mark.asyncio
async def test_basic_auth_off_by_default() -> None:
    assert settings.studio_basic_auth_enabled is False
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/jobs")
        assert response.status_code == 200
