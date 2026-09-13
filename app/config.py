from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from urllib.parse import quote_plus

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _mysql_database_url() -> str | None:
    """Same MYSQL_* contract as automatiom-napps (services/control_plane/repository.py)."""
    host = os.getenv("MYSQL_HOST", "").strip()
    user = os.getenv("MYSQL_USER", "").strip()
    password = os.getenv("MYSQL_PASSWORD", "").strip()
    database = os.getenv("MYSQL_DATABASE", "").strip()
    port = os.getenv("MYSQL_PORT", "3306").strip() or "3306"
    if not host:
        return None
    if not (user and password and database):
        raise RuntimeError(
            "MYSQL_HOST is set but MYSQL_USER, MYSQL_PASSWORD, or MYSQL_DATABASE is missing."
        )
    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )


def _resolve_database_url() -> str:
    explicit = os.getenv("DATABASE_URL", "").strip()
    default_sqlite = "sqlite:///./data/studio.db"
    if explicit and explicit != default_sqlite:
        return explicit
    mysql = _mysql_database_url()
    if mysql is not None:
        return mysql
    if explicit:
        return explicit
    return default_sqlite


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Kaggle Video Studio"
    brand_line: str = "Powered by napps.in"
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = _int_env("APP_PORT", 8000)
    # Blank means the machine's local zone.
    app_timezone: str | None = os.getenv("APP_TIMEZONE") or None
    root_dir: Path = _ROOT
    data_dir: Path = Path(os.getenv("DATA_DIR", str(_ROOT / "data"))).expanduser()
    database_url: str = _resolve_database_url()
    mysql_host: str = os.getenv("MYSQL_HOST", "").strip()
    mysql_port: int = _int_env("MYSQL_PORT", 3306)
    mysql_user: str = os.getenv("MYSQL_USER", "").strip()
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "").strip()
    mysql_database: str = os.getenv("MYSQL_DATABASE", "").strip()
    max_image_bytes: int = _int_env("MAX_IMAGE_BYTES", 15 * 1024 * 1024)
    max_audio_bytes: int = _int_env("MAX_AUDIO_BYTES", 20 * 1024 * 1024)
    max_prompt_chars: int = 4000
    max_negative_prompt_chars: int = 2000
    kaggle_username: str | None = os.getenv("KAGGLE_USERNAME") or None
    kaggle_api_token: str | None = os.getenv("KAGGLE_API_TOKEN") or None
    kaggle_json_path: Path = Path.home() / ".kaggle" / "kaggle.json"
    kaggle_dataset_slug: str = os.getenv("KAGGLE_DATASET_SLUG", "video-studio-jobs")
    kaggle_kernel_slug: str = os.getenv("KAGGLE_KERNEL_SLUG", "video-studio-runner")
    kaggle_runner_dir: Path = Path(
        os.getenv("KAGGLE_RUNNER_DIR", str(_ROOT / "kaggle_runner"))
    ).expanduser()
    kaggle_poll_initial_seconds: float = _float_env("KAGGLE_POLL_INITIAL_SECONDS", 10.0)
    kaggle_poll_max_seconds: float = _float_env("KAGGLE_POLL_MAX_SECONDS", 60.0)
    kaggle_dataset_ready_timeout_seconds: int = _int_env(
        "KAGGLE_DATASET_READY_TIMEOUT_SECONDS", 600
    )
    kaggle_unknown_status_timeout_seconds: int = _int_env(
        "KAGGLE_UNKNOWN_STATUS_TIMEOUT_SECONDS", 900
    )
    # Full SDXL is a T4-safe quality default. FLUX remains selectable when its
    # license and HF_TOKEN are attached to the Kaggle kernel.
    still_model: str = os.getenv(
        "STILL_MODEL", "stabilityai/stable-diffusion-xl-base-1.0"
    )
    # When true, connect private Kaggle dataset/kernel on process start (for Cloud).
    studio_auto_bootstrap: bool = _bool_env("STUDIO_AUTO_BOOTSTRAP", False)
    # When true, require HTTP Basic Auth (defaults: napps / napps).
    studio_basic_auth_enabled: bool = _bool_env("STUDIO_BASIC_AUTH", False)
    studio_basic_auth_user: str = os.getenv("STUDIO_BASIC_AUTH_USER", "napps")
    studio_basic_auth_password: str = os.getenv("STUDIO_BASIC_AUTH_PASSWORD", "napps")

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            path = Path(self.database_url.removeprefix("sqlite:///"))
            if not path.is_absolute():
                return (_ROOT / path).resolve()
            return path
        return self.data_dir / "studio.db"


settings = Settings()
