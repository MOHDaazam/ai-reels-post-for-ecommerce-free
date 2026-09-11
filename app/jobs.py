from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.campaigns import LANGUAGES, STRATEGIES, plan_campaign
from app.campaigns.planning import validate_unicode_text
from app.config import settings
from app.estimates import estimate
from app.localtime import isoformat as local_iso
from app.localtime import stamp as local_stamp
from app.models import Job, JobMode, JobStatus, utcnow
from app.storage import JobStorage, new_job_id
from app.trending_audio import ensure_track_file
from app.validation import (
    DEFAULT_ASPECT,
    DEFAULT_DURATION,
    ValidationError,
    parse_seed,
    resolve_presets,
    safe_job_id,
    validate_mode,
    validate_negative_prompt,
    validate_prompt,
)

TERMINAL_RETRY = {JobStatus.failed.value, JobStatus.canceled.value, JobStatus.completed.value}
VOICES = ("female_hindi", "male_hindi", "female_english", "male_english", "uploaded")
MAX_CAMPAIGN_JSON_BYTES = 256 * 1024
MAX_VARIABLE_CHARS = 300
MAX_CAPTION_CHARS = 500
REEL_ID_RE = re.compile(r"reel-(\d{3})")


@dataclass
class CreateJobInput:
    mode: str
    prompt: str
    negative_prompt: str = ""
    seed: str | None = None
    aspect_ratio: str = DEFAULT_ASPECT
    duration_preset: str = DEFAULT_DURATION
    image: UploadFile | None = None
    audio: UploadFile | None = None
    logo: UploadFile | None = None
    voice_upload: UploadFile | None = None
    campaign_json: str | None = None
    language: str | None = None
    voice: str | None = None
    strategy: str | None = None
    campaign_size: int | None = None
    trending_audio_id: str | None = None


class JobService:
    def __init__(self, storage: JobStorage | None = None) -> None:
        self.storage = storage or JobStorage()

    def list_jobs(self, session: Session, *, limit: int = 50) -> list[Job]:
        stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
        return list(session.scalars(stmt))

    def get(self, session: Session, job_id: str) -> Job | None:
        return session.get(Job, safe_job_id(job_id))

    async def create(self, session: Session, payload: CreateJobInput) -> Job:
        mode = validate_mode(payload.mode)
        campaign = _validate_campaign_payload(payload)
        default_prompt = campaign["reels"][0]["flux_prompt"] if campaign else payload.prompt
        prompt = validate_prompt(payload.prompt or default_prompt, max_chars=settings.max_prompt_chars)
        negative = validate_negative_prompt(
            payload.negative_prompt, max_chars=settings.max_negative_prompt_chars
        )
        seed = parse_seed(payload.seed)
        preset = resolve_presets(payload.aspect_ratio, payload.duration_preset)

        has_image = payload.image is not None and bool(payload.image.filename)
        has_audio = payload.audio is not None and bool(payload.audio.filename)
        has_logo = payload.logo is not None and bool(payload.logo.filename)
        has_voice_upload = payload.voice_upload is not None and bool(payload.voice_upload.filename)
        if mode == JobMode.uploaded_image.value and not has_image:
            raise ValidationError("Upload a product image for this mode.", "image")
        if mode == JobMode.generate_still.value and has_image:
            raise ValidationError(
                "Leave the image empty when generating a still, or switch mode to uploaded image.",
                "image",
            )
        if payload.voice == "uploaded" and not has_voice_upload:
            raise ValidationError(
                "Upload a voice sample for the uploaded voice option.", "voice_upload"
            )

        job_id = new_job_id()
        self.storage.ensure_layout(job_id)
        image_name = None
        audio_name = None
        logo_name = None
        voice_name = None
        if has_image and payload.image is not None:
            image_name = await self.storage.save_image(
                job_id, payload.image, max_bytes=settings.max_image_bytes
            )
        if has_audio and payload.audio is not None:
            audio_name = await self.storage.save_audio(
                job_id, payload.audio, max_bytes=settings.max_audio_bytes
            )
        if has_logo and payload.logo is not None:
            logo_name = await self.storage.save_logo(
                job_id, payload.logo, max_bytes=settings.max_image_bytes
            )
        if has_voice_upload and payload.voice_upload is not None:
            voice_name = await self.storage.save_voice(
                job_id, payload.voice_upload, max_bytes=settings.max_audio_bytes
            )
        trending_audio_id = (payload.trending_audio_id or "").strip() or None
        if not audio_name and trending_audio_id:
            audio_name = self.storage.attach_music_file(
                job_id, ensure_track_file(trending_audio_id)
            )
        output_manifest = None
        if campaign:
            # The planned reels are scenes of one delivered reel.
            output_manifest = {
                "status": "planned",
                "outputs": [{"index": 0, "status": "pending", "filename": None}],
            }

        job = Job(
            id=job_id,
            status=JobStatus.queued.value,
            mode=mode,
            prompt=prompt,
            negative_prompt=negative,
            seed=seed,
            aspect_ratio=preset.aspect_ratio,
            duration_preset=preset.duration_preset,
            width=preset.width,
            height=preset.height,
            num_frames=preset.num_frames,
            image_filename=image_name,
            audio_filename=audio_name,
            trending_audio_id=trending_audio_id,
            logo_filename=logo_name,
            voice_filename=voice_name,
            campaign_json=json.dumps(campaign, ensure_ascii=False) if campaign else None,
            language=payload.language if campaign else None,
            voice=payload.voice if campaign else None,
            strategy=payload.strategy if campaign else None,
            campaign_size=payload.campaign_size if campaign else None,
            output_manifest_json=json.dumps(output_manifest) if output_manifest else None,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        self.storage.write_job_json(job_id, _job_payload(job))
        self.storage.append_log(
            job_id,
            f"[{_ts()}] Job created · mode={mode} · {preset.width}x{preset.height} · {preset.num_frames} frames",
        )
        self.storage.append_log(
            job_id,
            f"[{_ts()}] Queued locally for the serialized Kaggle worker.",
        )
        self._log_estimate(session, job)
        return job

    def _log_estimate(self, session: Session, job: Job) -> None:
        prediction = estimate(session, job)
        self.storage.append_log(job.id, f"[{_ts()}] {prediction.describe()}")

    def cancel(self, session: Session, job_id: str) -> Job:
        job = self._require(session, job_id)
        if job.status == JobStatus.queued.value:
            job.status = JobStatus.canceled.value
            job.finished_at = utcnow()
            message = "Canceled while queued; nothing was submitted to Kaggle."
        elif job.status in {
            JobStatus.submitting.value,
            JobStatus.running.value,
        }:
            job.status = JobStatus.cancel_requested.value
            message = (
                "Cancellation requested locally. The Kaggle API does not provide a reliable "
                "stop operation; stop the running kernel manually on Kaggle. This studio will "
                "continue monitoring it."
            )
        else:
            raise ValidationError("Only queued or active jobs can be canceled.")
        job.updated_at = utcnow()
        session.commit()
        session.refresh(job)
        self.storage.append_log(job.id, f"[{_ts()}] {message}")
        self.storage.write_job_json(job.id, _job_payload(job))
        return job

    def retry(self, session: Session, job_id: str) -> Job:
        job = self._require(session, job_id)
        if job.status not in TERMINAL_RETRY:
            raise ValidationError("Only completed, failed, or canceled jobs can be retried.")
        if job.status == JobStatus.running.value:
            raise ValidationError("Cannot retry a running job.")
        job.status = JobStatus.queued.value
        job.error_message = None
        job.started_at = None
        job.finished_at = None
        job.kaggle_kernel_ref = None
        job.kaggle_dataset_version = None
        job.output_filename = None
        job.updated_at = utcnow()
        session.commit()
        session.refresh(job)
        self.storage.append_log(job.id, f"[{_ts()}] Re-queued for retry.")
        self._log_estimate(session, job)
        self.storage.write_job_json(job.id, _job_payload(job))
        return job

    def logs(self, job_id: str) -> str:
        safe_job_id(job_id)
        # Operational views and copy/download controls must retain the complete
        # local submission, polling, and downloaded Kaggle log history.
        return self.storage.read_logs(job_id, tail=None)

    def preview_path(self, session: Session, job_id: str):
        job = self._require(session, job_id)
        if job.status != JobStatus.completed.value:
            raise ValidationError("Preview is available after the job completes.")
        path = self.storage.output_mp4(job.id)
        if not path.is_file():
            raise ValidationError("Output MP4 is not on disk yet.")
        return path

    def reel_asset_path(
        self,
        session: Session,
        job_id: str,
        reel_ref: str,
        kind: str,
    ) -> tuple[Path, dict[str, Any]]:
        job = self._require(session, job_id)
        if job.status != JobStatus.completed.value:
            raise ValidationError("Reel output is available after the job completes.")
        metadata = _json_value(job.output_manifest_json)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("outputs"), list):
            raise ValidationError("Reel output metadata is unavailable.")
        output = _resolve_reel(metadata["outputs"], reel_ref)
        fields = {
            "video": ("reels", "filename"),
            "script": ("scripts", "script_filename"),
            "captions": ("captions", "srt_filename"),
            "thumbnail": ("thumbnails", "thumbnail_filename"),
        }
        if kind not in fields:
            raise ValidationError("Unknown reel asset type.")
        directory, field = fields[kind]
        filename = output.get(field)
        if not isinstance(filename, str) or not filename:
            raise ValidationError(f"Reel {kind} is unavailable.")
        path = self.storage.output_asset(job.id, directory, filename)
        if not path.is_file() or path.is_symlink():
            raise ValidationError(f"Reel {kind} is not on disk.")
        return path, output

    def campaign_zip_path(self, session: Session, job_id: str) -> Path:
        job = self._require(session, job_id)
        if job.status != JobStatus.completed.value:
            raise ValidationError("Campaign ZIP is available after the job completes.")
        path = self.storage.campaign_zip(job.id)
        if not path.is_file() or path.is_symlink():
            raise ValidationError("Campaign ZIP is not on disk.")
        return path

    def _require(self, session: Session, job_id: str) -> Job:
        job = self.get(session, job_id)
        if job is None:
            raise ValidationError("Job not found.")
        return job


def _job_payload(job: Job) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "mode": job.mode,
        "prompt": job.prompt,
        "negative_prompt": job.negative_prompt,
        "seed": job.seed,
        "aspect_ratio": job.aspect_ratio,
        "duration_preset": job.duration_preset,
        "width": job.width,
        "height": job.height,
        "num_frames": job.num_frames,
        "image_filename": job.image_filename,
        "audio_filename": job.audio_filename,
        "trending_audio_id": job.trending_audio_id,
        "logo_filename": job.logo_filename,
        "voice_filename": job.voice_filename,
        "output_filename": job.output_filename,
        "campaign": _json_value(job.campaign_json),
        "language": job.language,
        "voice": job.voice,
        "strategy": job.strategy,
        "campaign_size": job.campaign_size,
        "still_model": settings.still_model,
        "output_manifest": _json_value(job.output_manifest_json),
        "error_message": job.error_message,
        "kaggle_kernel_ref": job.kaggle_kernel_ref,
        "kaggle_dataset_version": job.kaggle_dataset_version,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _ts() -> str:
    return local_stamp()


def job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "mode": job.mode,
        "prompt": job.prompt,
        "negative_prompt": job.negative_prompt,
        "seed": job.seed,
        "aspect_ratio": job.aspect_ratio,
        "duration_preset": job.duration_preset,
        "width": job.width,
        "height": job.height,
        "num_frames": job.num_frames,
        "image_filename": job.image_filename,
        "audio_filename": job.audio_filename,
        "trending_audio_id": job.trending_audio_id,
        "logo_filename": job.logo_filename,
        "voice_filename": job.voice_filename,
        "output_filename": job.output_filename,
        "error_message": job.error_message,
        "kaggle_kernel_ref": job.kaggle_kernel_ref,
        "kaggle_dataset_version": job.kaggle_dataset_version,
        "has_output": bool(job.output_filename),
        "campaign": _json_value(job.campaign_json),
        "language": job.language,
        "voice": job.voice,
        "strategy": job.strategy,
        "campaign_size": job.campaign_size,
        "output_manifest": _json_value(job.output_manifest_json),
        "created_at": local_iso(job.created_at) if job.created_at else None,
        "updated_at": local_iso(job.updated_at) if job.updated_at else None,
        "started_at": local_iso(job.started_at) if job.started_at else None,
        "finished_at": local_iso(job.finished_at) if job.finished_at else None,
    }


def _json_value(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _validate_campaign_payload(payload: CreateJobInput) -> dict[str, Any] | None:
    if not payload.campaign_json:
        campaign_fields = (payload.language, payload.voice, payload.strategy, payload.campaign_size)
        if any(value is not None for value in campaign_fields):
            raise ValidationError("Campaign plan is required for campaign fields.", "campaign_json")
        return None
    if payload.language not in LANGUAGES:
        raise ValidationError("Choose Hindi, English, or bilingual.", "language")
    if payload.strategy not in STRATEGIES:
        raise ValidationError("Choose a valid credit strategy.", "strategy")
    if payload.voice not in VOICES:
        raise ValidationError("Choose a valid campaign voice.", "voice")
    if len(payload.campaign_json.encode("utf-8", errors="surrogatepass")) > MAX_CAMPAIGN_JSON_BYTES:
        raise ValidationError("Campaign plan is too large.", "campaign_json")
    try:
        submitted = json.loads(payload.campaign_json)
    except json.JSONDecodeError as exc:
        raise ValidationError("Campaign plan must be valid JSON.", "campaign_json") from exc
    if not isinstance(submitted, dict):
        raise ValidationError("Campaign plan must be a JSON object.", "campaign_json")
    template_id = submitted.get("template_id")
    variables = submitted.get("variables")
    if not isinstance(template_id, str) or not isinstance(variables, dict):
        raise ValidationError("Campaign template and variables are required.", "campaign_json")
    if submitted.get("language") != payload.language:
        raise ValidationError("Campaign language does not match the submitted plan.", "language")
    if submitted.get("strategy") != payload.strategy:
        raise ValidationError("Campaign strategy does not match the submitted plan.", "strategy")
    if submitted.get("campaign_size") != payload.campaign_size:
        raise ValidationError("Campaign size does not match the submitted plan.", "campaign_size")
    base_seed = submitted.get("base_seed")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int):
        raise ValidationError("Campaign base seed must be an integer.", "seed")
    clean_variables: dict[str, str] = {}
    for key, value in variables.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValidationError("Campaign variables must be text.", "variables")
        clean = validate_unicode_text(value, field=f"variables.{key}").strip()
        if len(clean) > MAX_VARIABLE_CHARS:
            raise ValidationError(
                f"Campaign variable {key} must be at most {MAX_VARIABLE_CHARS} characters.",
                f"variables.{key}",
            )
        clean_variables[key] = clean
    canonical = plan_campaign(
        template_id,
        language=payload.language,
        campaign_size=payload.campaign_size or 0,
        strategy=payload.strategy,
        variables=clean_variables,
        base_seed=base_seed,
    ).to_dict()
    reels = submitted.get("reels")
    if not isinstance(reels, list) or len(reels) != payload.campaign_size:
        raise ValidationError("Campaign reel count does not match campaign size.", "reels")
    editable = (
        "hook",
        "narration",
        "cta",
        "flux_prompt",
        "ltx_motion_prompt",
        "negative_prompt",
    )
    for index, submitted_reel in enumerate(reels):
        if not isinstance(submitted_reel, dict) or submitted_reel.get("index") != index:
            raise ValidationError("Campaign reels must be ordered and indexed.", "reels")
        if any("filename" in str(key).lower() or str(key).lower().endswith("_path") for key in submitted_reel):
            raise ValidationError("Campaign edits cannot set output filenames.", "reels")
        reel = canonical["reels"][index]
        for field in editable:
            value = submitted_reel.get(field, reel[field])
            value = validate_unicode_text(value, field=f"reels.{index}.{field}").strip()
            limit = (
                settings.max_negative_prompt_chars
                if field == "negative_prompt"
                else settings.max_prompt_chars
                if "prompt" in field
                else 500
                if field in {"hook", "cta"}
                else 4000
            )
            if not value or len(value) > limit:
                raise ValidationError(f"Reel {index + 1} {field} is invalid.", field)
            reel[field] = value
        captions = submitted_reel.get("captions", reel["captions"])
        if not isinstance(captions, list) or not 1 <= len(captions) <= 8:
            raise ValidationError("Each reel needs 1 to 8 captions.", "captions")
        reel["captions"] = [
            validate_unicode_text(caption, field=f"reels.{index}.captions").strip()
            for caption in captions
            if isinstance(caption, str) and caption.strip()
        ]
        if len(reel["captions"]) != len(captions):
            raise ValidationError("Captions must be non-empty text.", "captions")
        if any(len(caption) > MAX_CAPTION_CHARS for caption in reel["captions"]):
            raise ValidationError(
                f"Each caption must be at most {MAX_CAPTION_CHARS} characters.", "captions"
            )
    return canonical


def _resolve_reel(outputs: list[Any], reel_ref: str) -> dict[str, Any]:
    text = str(reel_ref or "").strip().lower()
    requested_id: str | None = None
    requested_index: int | None = None
    match = REEL_ID_RE.fullmatch(text)
    if match:
        requested_id = text
    elif text.isascii() and text.isdigit() and len(text) <= 3:
        requested_index = int(text)
    else:
        raise ValidationError("Invalid reel ID or index.")
    matches = [
        output
        for output in outputs
        if isinstance(output, dict)
        and (
            output.get("reel_id") == requested_id
            if requested_id is not None
            else output.get("index", output.get("reel_index")) == requested_index
        )
    ]
    if len(matches) != 1:
        raise ValidationError("Reel not found.")
    return matches[0]
