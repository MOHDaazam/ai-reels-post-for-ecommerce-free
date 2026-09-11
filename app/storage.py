from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import Settings, settings
from app.validation import (
    ValidationError,
    sniff_audio,
    sniff_image,
)


class JobStorage:
    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or settings

    def job_dir(self, job_id: str) -> Path:
        path = (self.settings.jobs_dir / job_id).resolve()
        jobs_root = self.settings.jobs_dir.resolve()
        if path != jobs_root and jobs_root not in path.parents:
            raise ValidationError("Job path escapes the jobs directory.")
        return path

    def ensure_layout(self, job_id: str) -> Path:
        root = self.job_dir(job_id)
        (root / "input").mkdir(parents=True, exist_ok=True)
        (root / "output").mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        return root

    def log_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "logs" / "job.log"

    def output_mp4(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "output" / "result.mp4"

    def output_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "output"

    def campaign_zip(self, job_id: str) -> Path:
        return self.output_dir(job_id) / "campaign.zip"

    def output_asset(self, job_id: str, directory: str, filename: str) -> Path:
        if directory not in {"reels", "scripts", "captions", "manifests", "thumbnails"}:
            raise ValidationError("Unknown output asset directory.")
        from app.outputs import safe_output_name

        name = safe_output_name(filename)
        root = self.output_dir(job_id).resolve()
        path = (root / directory / name).resolve()
        if root not in path.parents:
            raise ValidationError("Output asset path escapes the job directory.")
        return path

    def append_log(self, job_id: str, message: str) -> None:
        path = self.log_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")

    def read_logs(self, job_id: str, *, tail: int | None = 4000) -> str:
        path = self.log_path(job_id)
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        if tail is not None and len(text) > tail:
            return text[-tail:]
        return text

    def write_job_json(self, job_id: str, payload: dict) -> None:
        path = self.job_dir(job_id) / "job.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    async def save_image(self, job_id: str, upload: UploadFile, *, max_bytes: int) -> str:
        header, data = await self._read_upload(upload, max_bytes, field="image")
        ext = sniff_image(header, upload.filename or "image.bin", field="image")
        dest = self.job_dir(job_id) / "input" / f"source.{ext}"
        dest.write_bytes(data)
        return dest.name

    async def save_audio(self, job_id: str, upload: UploadFile, *, max_bytes: int) -> str:
        header, data = await self._read_upload(upload, max_bytes, field="audio")
        ext = sniff_audio(header, upload.filename or "audio.bin", field="audio")
        dest = self.job_dir(job_id) / "input" / f"music.{ext}"
        dest.write_bytes(data)
        return dest.name

    def attach_music_file(self, job_id: str, source: Path) -> str:
        if not source.is_file() or source.is_symlink():
            raise ValidationError("Trending audio file is not available.", "trending_audio_id")
        ext = source.suffix.lower().lstrip(".") or "mp3"
        if ext not in {"mp3", "m4a", "wav", "aac", "ogg"}:
            ext = "mp3"
        dest = self.job_dir(job_id) / "input" / f"music.{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        return dest.name

    async def save_logo(self, job_id: str, upload: UploadFile, *, max_bytes: int) -> str:
        header, data = await self._read_upload(upload, max_bytes, field="logo")
        ext = sniff_image(header, upload.filename or "logo.bin", field="logo")
        dest = self.job_dir(job_id) / "input" / f"logo.{ext}"
        dest.write_bytes(data)
        return dest.name

    async def save_voice(self, job_id: str, upload: UploadFile, *, max_bytes: int) -> str:
        header, data = await self._read_upload(upload, max_bytes, field="voice")
        ext = sniff_audio(header, upload.filename or "voice.bin", field="voice_upload")
        dest = self.job_dir(job_id) / "input" / f"voice.{ext}"
        dest.write_bytes(data)
        return dest.name

    async def _read_upload(
        self, upload: UploadFile, max_bytes: int, *, field: str
    ) -> tuple[bytes, bytes]:
        if not upload.filename or not upload.filename.strip():
            raise ValidationError(f"Missing {field} filename.", field)
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = await upload.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ValidationError(
                    f"{field.capitalize()} exceeds the {max_bytes // (1024 * 1024)} MB limit.",
                    field,
                )
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            raise ValidationError(f"{field.capitalize()} file is empty.", field)
        return data[:64], data


def new_job_id() -> str:
    return str(uuid4())
