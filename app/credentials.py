"""Local Kaggle credential persistence.

Secrets are intentionally kept out of database rows and template contexts.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.config import Settings, settings

MAX_CREDENTIAL_BYTES = 64 * 1024


class CredentialStore:
    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or settings
        self.directory = self.settings.data_dir / "secrets"
        self.path = self.directory / "kaggle.json"

    def save_token(self, username: str, token: str) -> Path:
        user = username.strip()
        secret = token.strip()
        if not user or not secret:
            raise ValueError("Kaggle username and API token are required.")
        return self._write({"username": user, "api_token": secret})

    def save_legacy(self, raw: str | bytes) -> Path:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if not data or len(data) > MAX_CREDENTIAL_BYTES:
            raise ValueError("kaggle.json must be between 1 byte and 64 KB.")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("kaggle.json must contain valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("kaggle.json must contain a JSON object.")
        username = payload.get("username")
        key = payload.get("key")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("kaggle.json is missing a username.")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("kaggle.json is missing a key.")
        return self._write({"username": username.strip(), "key": key.strip()})

    def runtime_settings(self) -> Settings:
        if not self.path.is_file():
            return self.settings
        payload = self._read()
        username = _text(payload.get("username"))
        token = _text(payload.get("api_token"))
        return replace(
            self.settings,
            kaggle_username=username,
            kaggle_api_token=token,
            kaggle_json_path=self.path,
        )

    def configure_environment(self) -> None:
        """Point the official client at the project credential directory."""
        if not self.path.is_file():
            return
        payload = self._read()
        os.environ["KAGGLE_CONFIG_DIR"] = str(self.directory)
        username = _text(payload.get("username"))
        api_token = _text(payload.get("api_token"))
        legacy_key = _text(payload.get("key"))
        if username:
            os.environ["KAGGLE_USERNAME"] = username
        if api_token:
            os.environ["KAGGLE_API_TOKEN"] = api_token
            os.environ.pop("KAGGLE_KEY", None)
        elif legacy_key:
            os.environ["KAGGLE_KEY"] = legacy_key
            os.environ.pop("KAGGLE_API_TOKEN", None)

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Saved Kaggle credentials are unreadable.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Saved Kaggle credentials are invalid.")
        return payload

    def _write(self, payload: dict[str, str]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
        return self.path


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
