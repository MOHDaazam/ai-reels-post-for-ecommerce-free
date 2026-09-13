from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.basic_auth import basic_auth_middleware
from app.business_profile import (
    BUSINESS_LINE_LABELS,
    campaign_variables,
    default_profile as default_business_profile,
    load_profile_safe,
    quick_template_id,
    save_profile,
)
from app.campaigns import BRAND_DEFAULTS, list_categories, list_presets, plan_campaign
from app.festivals import festival_variables, format_festival_date, get_festival, upcoming_festivals
from app.trending_audio import (
    ensure_track_file,
    list_tracks,
    preview_ready,
    resolve_trending_audio_id,
    track_label,
)
from app.config import settings
from app.credentials import MAX_CREDENTIAL_BYTES, CredentialStore
from app.database import get_session, init_db
from app.estimates import estimate
from app.health import HealthService
from app.jobs import VOICES, CreateJobInput, JobService, job_to_dict
from app.kaggle.client import CredentialState, KaggleService, _safe_error
from app.localtime import display as local_display
from app.localtime import isoformat as local_iso
from app.localtime import parse_log_stamp, to_local
from app.models import JobStatus
from app.storage import JobStorage
from app.validation import (
    ASPECT_PRESETS,
    DEFAULT_ASPECT,
    DEFAULT_DURATION,
    DURATION_PRESETS,
    ValidationError,
)
from app.studio_boot import BootstrapRuntime, bootstrap_runtime, set_bootstrap_runtime
from app.worker import JobWorker, KaggleOrchestrator

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
job_service = JobService()
credential_store = CredentialStore()
credential_store.configure_environment()
kaggle_service = KaggleService(credential_store.runtime_settings())
health_service = HealthService(client=kaggle_service)
worker = JobWorker(orchestrator=KaggleOrchestrator(client=kaggle_service))


def db_session():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(db_session)]


async def _auto_bootstrap_kaggle() -> None:
    if not settings.studio_auto_bootstrap:
        return
    from app.kaggle.client import CredentialState

    set_bootstrap_runtime(
        BootstrapRuntime(
            status="pending",
            detail="Creating or reusing private Kaggle dataset and kernel…",
        )
    )
    creds = kaggle_service.credential_status()
    if creds.state is not CredentialState.present:
        set_bootstrap_runtime(
            BootstrapRuntime(status="failed", detail=creds.detail or "Missing Kaggle credentials.")
        )
        return
    try:
        result = await asyncio.to_thread(kaggle_service.bootstrap)
    except Exception as exc:
        set_bootstrap_runtime(
            BootstrapRuntime(status="failed", detail=_safe_error(exc))
        )
        return
    set_bootstrap_runtime(
        BootstrapRuntime(
            status="ready",
            detail=f"Private resources ready: {result.kernel_ref}",
            result=result,
        )
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    import asyncio

    task = asyncio.create_task(worker.run())
    bootstrap_task = asyncio.create_task(_auto_bootstrap_kaggle())
    try:
        yield
    finally:
        worker.stop()
        bootstrap_task.cancel()
        task.cancel()
        for pending in (bootstrap_task, task):
            try:
                await pending
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title=settings.app_name,
    description=settings.brand_line,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.middleware("http")(basic_auth_middleware)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _ctx(request: Request, **extra):
    report = health_service.report()
    campaign_templates = [*list_categories(), *list_presets()]
    ctx = {
        "request": request,
        "app_name": settings.app_name,
        "brand_line": settings.brand_line,
        "health": report,
        "aspect_presets": ASPECT_PRESETS,
        "duration_presets": DURATION_PRESETS,
        "default_aspect": DEFAULT_ASPECT,
        "default_duration": DEFAULT_DURATION,
        "error": None,
        "form": {},
        "campaign_categories": list_categories(),
        "campaign_presets": list_presets(),
        "campaign_template_defaults": {
            template.id: dict(template.variable_defaults) for template in campaign_templates
        },
        "brand_defaults": BRAND_DEFAULTS,
        "business_profile": load_profile_safe(),
        "business_lines": BUSINESS_LINE_LABELS,
        "festival_offers": upcoming_festivals(),
        "format_festival_date": format_festival_date,
        "trending_tracks": [
            track.to_public_dict(preview_ready=preview_ready(track.id))
            for track in list_tracks(language="hindi")
        ],
        "default_trending_audio_id": load_profile_safe().get("trending_audio_id")
        or "hindi-food-groove",
        "voices": VOICES,
        "max_image_bytes": settings.max_image_bytes,
        "max_audio_bytes": settings.max_audio_bytes,
    }
    ctx.update(extra)
    return ctx


def _require_local_secret_request(request: Request) -> None:
    """Restrict credential mutations to same-origin loopback requests."""
    loopback = {"127.0.0.1", "::1", "localhost"}
    client_host = request.client.host if request.client else ""
    request_host = (request.url.hostname or "").lower()
    if client_host not in loopback or request_host not in loopback:
        raise HTTPException(status_code=403, detail="Secret changes are localhost-only.")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        expected_port = request.url.port or (443 if request.url.scheme == "https" else 80)
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if (
            parsed.scheme != request.url.scheme
            or (parsed.hostname or "").lower() != request_host
            or origin_port != expected_port
        ):
            raise HTTPException(status_code=403, detail="Cross-origin secret change rejected.")


def _reload_kaggle_service() -> KaggleService:
    global kaggle_service
    credential_store.configure_environment()
    kaggle_service = KaggleService(credential_store.runtime_settings())
    health_service.client = kaggle_service
    orchestrator = getattr(worker, "orchestrator", None)
    if orchestrator is not None:
        orchestrator.client = kaggle_service
    return kaggle_service


async def _queue_planned_campaign(
    session: Session,
    *,
    plan: dict,
    language: str = "hindi",
    voice: str = "female_hindi",
    strategy: str = "credit_saver",
    campaign_size: int = 3,
    trending_audio_id: str | None = None,
) -> RedirectResponse:
    job = await job_service.create(
        session,
        CreateJobInput(
            mode="generate_still",
            prompt="",
            campaign_json=json.dumps(plan, ensure_ascii=False),
            language=language,
            voice=voice,
            strategy=strategy,
            campaign_size=campaign_size,
            trending_audio_id=trending_audio_id,
        ),
    )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: SessionDep):
    jobs = job_service.list_jobs(session)
    saved = request.query_params.get("saved") == "1"
    return templates.TemplateResponse(
        name="index.html",
        context=_ctx(request, jobs=jobs, page="studio", profile_saved=saved),
        request=request,
    )


@app.post("/studio/profile")
async def save_business_profile(
    request: Request,
    session: SessionDep,
    vendor_name: Annotated[str, Form()] = "",
    dish_name: Annotated[str, Form()] = "",
    offer_text: Annotated[str, Form()] = "",
    city: Annotated[str, Form()] = "",
    area: Annotated[str, Form()] = "",
    contact: Annotated[str, Form()] = "",
    app_name: Annotated[str, Form()] = "",
    brand_tagline: Annotated[str, Form()] = "",
    cta_url: Annotated[str, Form()] = "",
    app_kind: Annotated[str, Form()] = "",
    platforms: Annotated[str, Form()] = "",
    business_line: Annotated[str, Form()] = "food_delivery",
    trending_audio_id: Annotated[str, Form()] = "",
):
    try:
        if trending_audio_id.strip():
            resolve_trending_audio_id(trending_audio_id, {})
        save_profile(
            {
                "vendor_name": vendor_name,
                "dish_name": dish_name,
                "offer_text": offer_text,
                "city": city,
                "area": area,
                "contact": contact,
                "app_name": app_name,
                "brand_tagline": brand_tagline,
                "cta_url": cta_url,
                "app_kind": app_kind,
                "platforms": platforms,
                "business_line": business_line,
                "trending_audio_id": trending_audio_id,
            }
        )
    except ValidationError as exc:
        jobs = job_service.list_jobs(session)
        return templates.TemplateResponse(
            name="index.html",
            context=_ctx(request, jobs=jobs, page="studio", error=exc.message),
            request=request,
            status_code=400,
        )
    return RedirectResponse(url="/?saved=1", status_code=303)


@app.post("/studio/quick-queue")
async def quick_queue_reel(
    session: SessionDep,
    trending_audio_id: Annotated[str, Form()] = "",
):
    profile = load_profile_safe()
    audio_id = resolve_trending_audio_id(trending_audio_id, profile)
    plan = plan_campaign(
        quick_template_id(profile),
        language="hindi",
        campaign_size=3,
        strategy="credit_saver",
        variables=campaign_variables(profile),
    ).to_dict()
    return await _queue_planned_campaign(session, plan=plan, trending_audio_id=audio_id)


@app.post("/festivals/{slug}/queue")
async def queue_festival_reel(
    slug: str,
    session: SessionDep,
    trending_audio_id: Annotated[str, Form()] = "",
):
    offer = get_festival(slug)
    if offer is None:
        raise HTTPException(status_code=404, detail="Unknown festival offer.")
    profile = load_profile_safe()
    audio_id = resolve_trending_audio_id(trending_audio_id, profile)
    plan = plan_campaign(
        offer.template_id,
        language="hindi",
        campaign_size=3,
        strategy="credit_saver",
        variables=festival_variables(offer, profile),
    ).to_dict()
    return await _queue_planned_campaign(session, plan=plan, trending_audio_id=audio_id)


@app.get("/api/trending-audio")
def api_trending_audio(language: str | None = None):
    tracks = [
        track.to_public_dict(preview_ready=preview_ready(track.id))
        for track in list_tracks(language=language)
    ]
    return {"tracks": tracks}


@app.get("/api/trending-audio/{track_id}/preview")
def api_trending_audio_preview(track_id: str):
    path = ensure_track_file(track_id)
    return FileResponse(path, media_type="audio/mpeg", filename=f"{track_id}.mp3")


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    return templates.TemplateResponse(
        name="setup.html",
        context=_ctx(request, page="setup"),
        request=request,
    )


@app.post("/setup/credentials", response_class=HTMLResponse)
async def save_credentials(
    request: Request,
    username: Annotated[str, Form()] = "",
    api_token: Annotated[str, Form()] = "",
    kaggle_json_text: Annotated[str, Form()] = "",
    kaggle_json_file: Annotated[UploadFile | None, File()] = None,
):
    _require_local_secret_request(request)
    try:
        upload = b""
        if kaggle_json_file is not None and kaggle_json_file.filename:
            upload = await kaggle_json_file.read(MAX_CREDENTIAL_BYTES + 1)
        legacy_sources = int(bool(upload)) + int(bool(kaggle_json_text.strip()))
        token_source = bool(username.strip() or api_token.strip())
        if legacy_sources and token_source:
            raise ValueError("Choose either username/token or one kaggle.json source.")
        if legacy_sources > 1:
            raise ValueError("Upload or paste kaggle.json, not both.")
        if upload:
            credential_store.save_legacy(upload)
        elif kaggle_json_text.strip():
            credential_store.save_legacy(kaggle_json_text)
        elif token_source:
            credential_store.save_token(username, api_token)
        else:
            raise ValueError("Enter Kaggle credentials before saving.")
        service = _reload_kaggle_service()
        status = await asyncio.to_thread(service.credential_status, True)
        if status.state is not CredentialState.present:
            raise ValueError(status.detail)
        message = "Credentials saved securely and accepted by the Kaggle API."
        return templates.TemplateResponse(
            name="setup.html",
            context=_ctx(request, page="setup", setup_success=message),
            request=request,
        )
    except (ValueError, OSError) as exc:
        return templates.TemplateResponse(
            name="setup.html",
            context=_ctx(
                request,
                page="setup",
                setup_error=_safe_error(exc, api_token),
            ),
            request=request,
            status_code=400,
        )


@app.post("/setup/bootstrap", response_class=HTMLResponse)
async def bootstrap_kaggle(request: Request):
    _require_local_secret_request(request)
    try:
        result = await asyncio.to_thread(kaggle_service.bootstrap)
        return templates.TemplateResponse(
            name="setup.html",
            context=_ctx(
                request,
                page="setup",
                bootstrap_result=result,
                setup_success="Private Kaggle resources are connected and ready.",
            ),
            request=request,
        )
    except Exception as exc:  # Kaggle's generated client raises several exception classes
        return templates.TemplateResponse(
            name="setup.html",
            context=_ctx(
                request,
                page="setup",
                setup_error=f"Bootstrap failed: {_safe_error(exc)}",
            ),
            request=request,
            status_code=502,
        )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: str, request: Request, session: SessionDep):
    try:
        job = job_service.get(session, job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    logs = job_service.logs(job.id)
    output_exists = JobStorage().output_mp4(job.id).is_file()
    job_data = job_to_dict(job)
    pending = job.status in {
        JobStatus.queued.value,
        JobStatus.submitting.value,
        JobStatus.running.value,
        JobStatus.cancel_requested.value,
    }
    prediction = estimate(session, job, started_at=job.started_at) if pending else None
    output_manifest = job_data["output_manifest"]
    reel_outputs = (
        output_manifest.get("outputs", [])
        if isinstance(output_manifest, dict)
        else []
    )
    return templates.TemplateResponse(
        name="job_detail.html",
        context=_ctx(
            request,
            jobs=[],
            job=job,
            campaign=job_data["campaign"],
            output_manifest=output_manifest,
            reel_outputs=reel_outputs,
            campaign_zip_exists=JobStorage().campaign_zip(job.id).is_file(),
            estimate=prediction,
            logs=logs,
            output_exists=output_exists,
            trending_audio_label=track_label(job.trending_audio_id),
            page="job",
        ),
        request=request,
    )


@app.post("/jobs")
async def create_job(
    request: Request,
    session: SessionDep,
    mode: Annotated[str, Form()] = "generate_still",
    prompt: Annotated[str, Form()] = "",
    negative_prompt: Annotated[str, Form()] = "",
    seed: Annotated[str, Form()] = "",
    aspect_ratio: Annotated[str, Form()] = DEFAULT_ASPECT,
    duration_preset: Annotated[str, Form()] = DEFAULT_DURATION,
    image: Annotated[UploadFile | None, File()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
    logo: Annotated[UploadFile | None, File()] = None,
    voice_upload: Annotated[UploadFile | None, File()] = None,
    campaign_json: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
    voice: Annotated[str, Form()] = "",
    strategy: Annotated[str, Form()] = "",
    campaign_size: Annotated[int | None, Form()] = None,
    trending_audio_id: Annotated[str, Form()] = "",
):
    form_state = {
        "mode": mode,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "aspect_ratio": aspect_ratio,
        "duration_preset": duration_preset,
        "language": language,
        "voice": voice,
        "strategy": strategy,
        "campaign_size": campaign_size,
    }
    try:
        profile = load_profile_safe()
        audio_id = resolve_trending_audio_id(trending_audio_id, profile)
        job = await job_service.create(
            session,
            CreateJobInput(
                mode=mode,
                prompt=prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                aspect_ratio=aspect_ratio,
                duration_preset=duration_preset,
                image=image,
                audio=audio,
                logo=logo,
                voice_upload=voice_upload,
                campaign_json=campaign_json or None,
                language=language or None,
                voice=voice or None,
                strategy=strategy or None,
                campaign_size=campaign_size,
                trending_audio_id=audio_id,
            ),
        )
    except ValidationError as exc:
        jobs = job_service.list_jobs(session)
        return templates.TemplateResponse(
            name="index.html",
            context=_ctx(request, jobs=jobs, error=exc.message, form=form_state, page="studio"),
            request=request,
            status_code=400,
        )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/campaigns/samples/{preset_id}/queue")
async def queue_sample_campaign(preset_id: str, session: SessionDep):
    try:
        preset_ids = {preset.id for preset in list_presets()}
        if preset_id not in preset_ids:
            raise ValidationError("Unknown sample campaign.", "preset_id")
        plan = plan_campaign(
            preset_id,
            language="hindi",
            campaign_size=3,
            strategy="credit_saver",
        ).to_dict()
        job = await job_service.create(
            session,
            CreateJobInput(
                mode="generate_still",
                prompt="",
                campaign_json=json.dumps(plan, ensure_ascii=False),
                language="hindi",
                voice="female_hindi",
                strategy="credit_saver",
                campaign_size=3,
            ),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, session: SessionDep):
    try:
        job_service.cancel(session, job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, session: SessionDep):
    try:
        job_service.retry(session, job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}/preview")
def preview_job(job_id: str, session: SessionDep):
    try:
        path = job_service.preview_path(session, job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return FileResponse(path, media_type="video/mp4", filename="preview.mp4")


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str, session: SessionDep):
    try:
        path = job_service.preview_path(session, job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")


@app.get("/jobs/{job_id}/reels/{reel_ref}/preview")
def preview_reel(job_id: str, reel_ref: str, session: SessionDep):
    try:
        path, _output = job_service.reel_asset_path(session, job_id, reel_ref, "video")
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return FileResponse(path, media_type="video/mp4")


@app.get("/jobs/{job_id}/reels/{reel_ref}/download")
def download_reel(job_id: str, reel_ref: str, session: SessionDep):
    try:
        path, output = job_service.reel_asset_path(session, job_id, reel_ref, "video")
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{output['reel_id']}.mp4",
    )


@app.get("/jobs/{job_id}/reels/{reel_ref}/script")
def download_reel_script(job_id: str, reel_ref: str, session: SessionDep):
    try:
        path, output = job_service.reel_asset_path(session, job_id, reel_ref, "script")
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=f"{output['reel_id']}-script.txt",
    )


@app.get("/jobs/{job_id}/reels/{reel_ref}/captions")
def download_reel_captions(job_id: str, reel_ref: str, session: SessionDep):
    try:
        path, output = job_service.reel_asset_path(session, job_id, reel_ref, "captions")
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return FileResponse(
        path,
        media_type="application/x-subrip; charset=utf-8",
        filename=f"{output['reel_id']}.srt",
    )


@app.get("/jobs/{job_id}/reels/{reel_ref}/thumbnail")
def download_reel_thumbnail(job_id: str, reel_ref: str, session: SessionDep):
    try:
        path, output = job_service.reel_asset_path(session, job_id, reel_ref, "thumbnail")
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    suffix = path.suffix.lower()
    return FileResponse(
        path,
        media_type="image/png" if suffix == ".png" else "image/jpeg",
        filename=f"{output['reel_id']}-thumbnail{suffix}",
    )


@app.get("/jobs/{job_id}/campaign.zip")
def download_campaign_zip(job_id: str, session: SessionDep):
    try:
        path = job_service.campaign_zip_path(session, job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{job_id}-campaign.zip",
    )


@app.get("/api/health")
def api_health():
    report = health_service.report()
    return {
        "ready": report.ready,
        "generated_at": report.generated_at,
        "credentials": {
            "state": report.credentials.state.value,
            "source": report.credentials.source,
            "username_hint": report.credentials.username_hint,
            "detail": report.credentials.detail,
        },
        "checks": [
            {
                "key": c.key,
                "label": c.label,
                "ok": c.ok,
                "detail": c.detail,
                "level": c.level,
            }
            for c in report.checks
        ],
    }


@app.get("/api/jobs")
def api_jobs(session: SessionDep):
    return [job_to_dict(job) for job in job_service.list_jobs(session)]


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, session: SessionDep):
    jobs = job_service.list_jobs(session, limit=200)
    return templates.TemplateResponse(
        name="logs.html",
        context=_ctx(request, jobs=jobs, page="logs"),
        request=request,
    )


@app.get("/api/logs")
def api_logs(
    session: SessionDep,
    status: str = "",
    job: str = "",
    text: str = "",
):
    jobs = job_service.list_jobs(session, limit=200)
    status_key = status.strip().lower()
    job_key = job.strip().lower()
    text_key = text.strip().lower()
    if status_key:
        jobs = [item for item in jobs if item.status.lower() == status_key]
    if job_key:
        jobs = [item for item in jobs if job_key in item.id.lower()]
    items: list[dict[str, object]] = []
    for item in jobs:
        raw = job_service.logs(item.id)
        for sequence, line in enumerate(raw.splitlines()):
            if text_key and text_key not in line.lower():
                continue
            moment = _log_moment(line, item.created_at)
            items.append(
                {
                    "timestamp": moment.isoformat(),
                    "sort_key": moment,
                    "job_id": item.id,
                    "status": item.status,
                    "line": line,
                    "sequence": sequence,
                    "kernel_ref": item.kaggle_kernel_ref,
                    "dataset_version": item.kaggle_dataset_version,
                    "job_url": f"/jobs/{item.id}",
                    "kernel_url": (
                        f"https://www.kaggle.com/code/{item.kaggle_kernel_ref}"
                        if item.kaggle_kernel_ref
                        else None
                    ),
                }
            )
    items.sort(
        key=lambda entry: (
            entry["sort_key"],
            str(entry["job_id"]),
            str(entry["sequence"]).zfill(8),
        )
    )
    for entry in items:
        del entry["sort_key"]
    return {
        "generated_at": local_iso(),
        "jobs": [job_to_dict(item) for item in jobs],
        "entries": items,
    }


def _log_moment(line: str, fallback: datetime | None) -> datetime:
    parsed = parse_log_stamp(line)
    if parsed is not None:
        return to_local(parsed)
    if fallback is not None:
        return to_local(fallback)
    return datetime.min.replace(tzinfo=timezone.utc)


@app.get("/api/campaigns/templates")
def api_campaign_templates():
    def item(template):
        return {
            "id": template.id,
            "kind": template.kind,
            "category": template.category,
            "title_en": template.title_en,
            "title_hi": template.title_hi,
            "description": template.description,
            "variable_defaults": dict(template.variable_defaults),
        }

    return {
        "categories": [item(template) for template in list_categories()],
        "presets": [item(template) for template in list_presets()],
        "brand_defaults": BRAND_DEFAULTS,
    }


@app.post("/api/campaigns/preview")
async def api_campaign_preview(request: Request):
    try:
        payload = await request.json()
        plan = plan_campaign(
            payload.get("template_id", ""),
            language=payload.get("language", "bilingual"),
            campaign_size=int(payload.get("campaign_size", 3)),
            strategy=payload.get("strategy", "credit_saver"),
            variables=payload.get("variables"),
            base_seed=payload.get("base_seed"),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        message = exc.message if isinstance(exc, ValidationError) else "Invalid campaign request."
        raise HTTPException(status_code=400, detail=message) from exc
    return plan.to_dict()


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str, session: SessionDep):
    try:
        job = job_service.get(session, job_id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    data = job_to_dict(job)
    data["logs"] = job_service.logs(job.id)
    data["has_output"] = JobStorage().output_mp4(job.id).is_file()
    return data


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    accept = request.headers.get("accept", "")
    if "text/html" in accept and not request.url.path.startswith("/api/"):
        jobs: list = []
        return templates.TemplateResponse(
            name="error.html",
            context=_ctx(request, error=exc.detail, status_code=exc.status_code, jobs=jobs, page="error"),
            request=request,
            status_code=exc.status_code,
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def run() -> None:
    import uvicorn

    reload = os.getenv("APP_RELOAD", "").strip().lower() in {"1", "true", "yes"}
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload,
    )


# Status helper for templates
templates.env.globals["JobStatus"] = JobStatus
templates.env.globals["default_business_profile"] = default_business_profile
templates.env.filters["localtime"] = local_display
