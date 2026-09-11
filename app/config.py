from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


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
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/studio.db")
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
