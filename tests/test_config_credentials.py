from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings, _float_env, _int_env
from app.kaggle.client import (
    CredentialProbe,
    CredentialState,
    KaggleService,
)


def settings_for(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "root_dir": tmp_path,
        "data_dir": tmp_path / "data",
        "database_url": f"sqlite:///{tmp_path / 'studio.db'}",
        "kaggle_json_path": tmp_path / "kaggle.json",
        "kaggle_username": None,
        "kaggle_api_token": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_numeric_environment_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_NUMBER", raising=False)
    assert _int_env("TEST_NUMBER", 7) == 7
    monkeypatch.setenv("TEST_NUMBER", " 12 ")
    assert _int_env("TEST_NUMBER", 7) == 12
    assert _float_env("TEST_NUMBER", 1.5) == 12.0
    monkeypatch.setenv("TEST_NUMBER", "not-a-number")
    with pytest.raises(ValueError):
        _int_env("TEST_NUMBER", 7)


def test_settings_derive_isolated_job_and_database_paths(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path)
    assert cfg.jobs_dir == tmp_path / "data" / "jobs"
    assert cfg.db_path == tmp_path / "studio.db"


def test_credential_probe_prefers_token_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "kaggle.json").write_text(
        json.dumps({"username": "file-user", "key": "file-secret"}), encoding="utf-8"
    )
    cfg = settings_for(
        tmp_path, kaggle_username="env-user", kaggle_api_token="env-secret"
    )
    status = CredentialProbe(cfg).credential_status()
    assert status.state is CredentialState.present
    assert status.source == "environment"
    assert status.username_hint == "env-user"
    assert "env-secret" not in status.detail

    monkeypatch.setenv("KAGGLE_KEY", "legacy-secret")
    legacy = CredentialProbe(settings_for(tmp_path / "other")).credential_status()
    assert legacy.state is CredentialState.present
    assert "KAGGLE_KEY" in legacy.detail
    assert "legacy-secret" not in legacy.detail


@pytest.mark.parametrize(
    ("contents", "state"),
    [
        ('{"username":"alice","key":"secret"}', CredentialState.present),
        ('{"username":"alice"}', CredentialState.invalid),
        ("not-json", CredentialState.invalid),
        ("[]", CredentialState.invalid),
    ],
)
def test_credential_probe_handles_token_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: str,
    state: CredentialState,
) -> None:
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    path = tmp_path / "kaggle.json"
    path.write_text(contents, encoding="utf-8")
    status = CredentialProbe(settings_for(tmp_path)).credential_status()
    assert status.state is state
    assert "secret" not in status.detail


def test_missing_credentials_are_reported_without_importing_kaggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    status = CredentialProbe(settings_for(tmp_path)).credential_status()
    assert status.state is CredentialState.missing
    assert status.source is None


class RejectingAdapter:
    def authenticate(self) -> str:
        raise RuntimeError("rejected token=configured-secret")


def test_remote_validation_redacts_configured_secret(tmp_path: Path) -> None:
    cfg = settings_for(tmp_path, kaggle_api_token="configured-secret")
    service = KaggleService(cfg, adapter=RejectingAdapter())  # type: ignore[arg-type]
    status = service.credential_status(validate=True)
    assert status.state is CredentialState.invalid
    assert "configured-secret" not in status.detail
    assert "[redacted]" in status.detail


def test_share_preflight_only_requires_cloudflared(monkeypatch) -> None:
    from pathlib import Path

    import app.share as share

    monkeypatch.setattr(share, "cloudflared_path", lambda: Path("/usr/bin/cloudflared"))
    assert share.preflight() == []

    monkeypatch.setattr(share, "cloudflared_path", lambda: None)
    assert any("cloudflared" in problem for problem in share.preflight())


def test_tunnel_url_is_read_from_cloudflared_output() -> None:
    import app.share as share

    line = "2026-09-11T19:48Z INF |  https://processing-spaces-flavor-sherman.trycloudflare.com |"
    assert (
        share.extract_tunnel_url(line)
        == "https://processing-spaces-flavor-sherman.trycloudflare.com"
    )
    assert share.extract_tunnel_url("INF Registered tunnel connection") is None
