"""Headless FLUX still + LTX image-to-video runner for a Kaggle T4.

This file is intentionally self-contained: the orchestrator stages only
``run.py`` in the private Kaggle script kernel.  Heavy imports happen after
the Kaggle runtime dependencies have been checked/installed so importing this
module for helper tests does not require torch or diffusers.
"""

from __future__ import annotations

import asyncio
import gc
import importlib.metadata
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

WORKING_DIR = Path(os.environ.get("KAGGLE_WORKING_DIR", "/kaggle/working"))
INPUT_DIR = Path(os.environ.get("KAGGLE_INPUT_DIR", "/kaggle/input"))
RESULT_PATH = WORKING_DIR / "result.mp4"
MANIFEST_PATH = WORKING_DIR / "manifest.json"
OUTPUTS_DIR = WORKING_DIR / "outputs"
CAMPAIGN_MANIFEST_PATH = OUTPUTS_DIR / "campaign_manifest.json"

FLUX_MODEL = "black-forest-labs/FLUX.1-schnell"
SDXL_QUALITY_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_TURBO_MODEL = "stabilityai/sdxl-turbo"
# FLUX is a gated repo: without an accepted licence and a token, Hugging Face
# answers 401. This ungated model keeps campaigns running on its own.
FALLBACK_STILL_MODEL = SDXL_TURBO_MODEL
GATED_MODELS = {FLUX_MODEL}
HF_SECRET_LABEL = "HF_TOKEN"
# This is the original 2B LTX checkpoint supported by LTXImageToVideoPipeline.
LTX_MODEL = "Lightricks/LTX-Video"
FPS = 24
FINAL_FPS = 30
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1920
MAX_PIXELS = 704 * 480
MIN_SIDE = 256
# CLIP text encoders (SDXL-turbo and friends) hard-truncate past this.
CLIP_TOKEN_LIMIT = 77
DEFAULT_SHOT_COUNT = 3
# One reel is delivered per job, so bound how many shots it is worth generating
# and let the credit mode choose within that bound.
MAX_REEL_SHOTS = 6
STRATEGY_SHOT_COUNTS = {"credit_saver": 3, "balanced": 4, "unique_visuals": 6}
CROSSFADE_FRAMES = 8
END_CARD_SECONDS = 2.5
VOICE_LEAD_MS = 250
WATERMARK_BOX = 220
WATERMARK_MARGIN = 54
DEFAULT_APP_KIND = "Food delivery app"
DEFAULT_PLATFORMS = "Android, iOS & Laptop"
DEFAULT_NEGATIVE = (
    "worst quality, inconsistent motion, blurry, jittery, distorted, "
    # Only the brand mark and end card may carry wording, and generated
    # signage always comes out as misspelled gibberish.
    "watermark, text, signage text, lettering, letters, words, captions"
)

# Keep torch supplied by Kaggle so its CUDA build continues to match the host.
RUNTIME_REQUIREMENTS = {
    "diffusers": "0.32.2",
    "transformers": "4.47.1",
    "accelerate": "1.2.1",
    "sentencepiece": "0.2.0",
    "safetensors": "0.4.5",
    "imageio": "2.36.1",
    "imageio-ffmpeg": "0.5.1",
    "Pillow": "11.0.0",
    "edge-tts": "7.2.3",
}

EDGE_VOICES = {
    "female_hindi": "hi-IN-SwaraNeural",
    "male_hindi": "hi-IN-MadhurNeural",
    "female_english": "en-IN-NeerjaNeural",
    "male_english": "en-IN-PrabhatNeural",
}
KNOWN_EDGE_VOICES = frozenset(EDGE_VOICES.values())
SYSTEM_FONT_DIRS = (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"))
LATIN_FONT_NAMES = (
    "DejaVuSans.ttf",
    "NotoSans-Regular.ttf",
    "LiberationSans-Regular.ttf",
    "Ubuntu-R.ttf",
)
FONT_DOWNLOAD_URLS = (
    "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts/"
    "NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf",
    "https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/fonts/"
    "NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf",
)


def _now() -> float:
    return time.monotonic()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def safe_error(exc: BaseException) -> str:
    """Return a bounded error message with common credential forms redacted."""
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"(?i)(token|authorization|api[_-]?key)(\s*[=:]\s*)\S+", r"\1\2[redacted]", text)
    text = re.sub(r"hf_[A-Za-z0-9]{12,}", "hf_[redacted]", text)
    return text[:2000]


def resolve_voice(requested: Any, language: Any) -> str:
    """Map UI aliases to a fixed, known Edge voice without accepting arbitrary names."""
    value = str(requested or "").strip()
    if value in EDGE_VOICES:
        return EDGE_VOICES[value]
    if value in KNOWN_EDGE_VOICES:
        return value
    return (
        EDGE_VOICES["female_english"]
        if str(language or "").lower() == "english"
        else EDGE_VOICES["female_hindi"]
    )


def reel_script(reel: dict[str, Any]) -> str:
    """Return the complete spoken script, including a bilingual companion."""
    parts = [str(reel.get("narration") or "").strip()]
    companion = str(reel.get("companion_narration") or "").strip()
    if companion and companion not in parts:
        parts.append(companion)
    return "\n\n".join(part for part in parts if part)


def reel_voice_lines(reel: dict[str, Any]) -> list[str]:
    """Spoken lines for the delivered reel.

    A single reel has to stay reel-length, so the hook and the call to action
    are voiced and the longer narration ships as text in the script file.
    """
    lines = [
        str(reel.get("hook") or "").strip(),
        str(reel.get("cta") or "").strip(),
    ]
    spoken = [line for line in lines if line]
    return spoken or [reel_script(reel)]


def estimate_speech_seconds(text: str) -> float:
    words = re.findall(r"\S+", text, flags=re.UNICODE)
    return max(3.0, min(90.0, len(words) / 1.8 + 2.0))


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def build_srt(captions: Iterable[Any], duration: float) -> str:
    """Build UTF-8 SRT with weighted, readable and non-overlapping timings."""
    cleaned = [str(value).strip() for value in captions if str(value).strip()]
    if not cleaned:
        return ""
    duration = max(float(duration), len(cleaned) * 0.8)
    weights = [max(1, len(re.findall(r"\S+", caption, flags=re.UNICODE))) for caption in cleaned]
    total_weight = sum(weights)
    distributable = duration - len(cleaned) * 0.8
    cursor = 0.0
    blocks: list[str] = []
    for index, (caption, weight) in enumerate(zip(cleaned, weights, strict=True), start=1):
        end = (
            duration
            if index == len(cleaned)
            else cursor + 0.8 + distributable * weight / total_weight
        )
        blocks.append(
            f"{index}\n{_srt_timestamp(cursor)} --> {_srt_timestamp(end)}\n{caption}\n"
        )
        cursor = end
    return "\n".join(blocks)


def narration_fallback(tts_succeeded: bool, uploaded_voice: Path | None) -> tuple[str, str | None]:
    """Describe deterministic narration selection for tests and manifests."""
    if tts_succeeded:
        return "edge_tts", None
    if uploaded_voice is not None:
        return "uploaded_voice_over", "Edge TTS unavailable; uploaded voice-over used."
    return (
        "captions_music_only",
        "Edge TTS unavailable and no uploaded voice-over was supplied; continuing "
        "with music only and captions delivered as a sidecar SRT.",
    )


def legal_frames(value: Any, *, maximum: int = 81) -> int:
    """Clamp to a positive LTX frame count of the form 8k+1."""
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = 49
    requested = min(max(requested, 9), maximum)
    return ((requested - 1) // 8) * 8 + 1


def legal_dimensions(
    width: Any,
    height: Any,
    *,
    max_pixels: int = MAX_PIXELS,
    min_side: int = MIN_SIDE,
) -> tuple[int, int]:
    """Preserve aspect ratio while producing bounded multiples of 32."""
    try:
        width_f, height_f = float(width), float(height)
    except (TypeError, ValueError):
        width_f, height_f = 704.0, 480.0
    if not math.isfinite(width_f) or not math.isfinite(height_f) or width_f <= 0 or height_f <= 0:
        width_f, height_f = 704.0, 480.0

    scale = min(1.0, math.sqrt(max_pixels / (width_f * height_f)))
    width_i = max(32, int(width_f * scale) // 32 * 32)
    height_i = max(32, int(height_f * scale) // 32 * 32)

    # Do not upscale tiny user requests, but avoid unusably small fallback sizes.
    if min(width_i, height_i) < min_side and min(width_f, height_f) >= min_side:
        grow = min_side / min(width_i, height_i)
        grown_w = max(32, round(width_i * grow / 32) * 32)
        grown_h = max(32, round(height_i * grow / 32) * 32)
        if grown_w * grown_h <= max_pixels:
            width_i, height_i = grown_w, grown_h
    return width_i, height_i


def retry_settings(width: int, height: int, frames: int) -> list[tuple[int, int, int]]:
    """Return deterministic, progressively cheaper legal T4 attempts."""
    candidates = [(width, height, frames)]
    for pixel_ratio, frame_cap in ((0.78, 49), (0.62, 33), (0.48, 25)):
        retry_w, retry_h = legal_dimensions(
            width,
            height,
            max_pixels=max(MIN_SIDE * MIN_SIDE, int(width * height * pixel_ratio)),
            min_side=192,
        )
        candidate = (retry_w, retry_h, legal_frames(min(frames, frame_cap)))
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _json_object(value: Any, *, field: str) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} must contain valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object.")
    return value


def campaign_from_job(job: dict[str, Any]) -> dict[str, Any] | None:
    """Accept current staged payloads plus older campaign_json/top-level forms."""
    campaign = _json_object(job.get("campaign"), field="campaign")
    if campaign is None:
        campaign = _json_object(job.get("campaign_json"), field="campaign_json")
    if campaign is None and "reels" in job:
        campaign = {"reels": job["reels"]}
    return campaign


def plan_batch(job: dict[str, Any]) -> dict[str, Any]:
    """Build a torch-free execution plan for campaign and legacy jobs."""
    campaign = campaign_from_job(job)
    if campaign is None:
        validate_job(job)
        reel = {
            "index": 0,
            "prompt": str(job["prompt"]),
            "negative_prompt": str(job.get("negative_prompt") or DEFAULT_NEGATIVE),
            "seed": job.get("seed"),
            "animate": True,
            "motion_source_index": 0,
        }
        return {"legacy": True, "strategy": "unique_visuals", "reels": [reel]}

    reels_value = campaign.get("reels")
    if not isinstance(reels_value, list):
        raise ValueError("Campaign reels must be an array.")
    if not 3 <= len(reels_value) <= 5:
        raise ValueError("Campaign must contain between 3 and 5 scenes.")
    strategy = str(job.get("strategy") or campaign.get("strategy") or "credit_saver")
    if strategy not in STRATEGY_SHOT_COUNTS:
        raise ValueError("strategy must be credit_saver, balanced, or unique_visuals.")
    reels: list[dict[str, Any]] = []
    for position, value in enumerate(reels_value):
        if not isinstance(value, dict):
            raise ValueError(f"Campaign reel {position} must be an object.")
        prompt = str(value.get("flux_prompt") or value.get("prompt") or "").strip()
        motion_prompt = str(value.get("ltx_motion_prompt") or prompt).strip()
        if not prompt or not motion_prompt:
            raise ValueError(f"Campaign reel {position} requires visual prompts.")
        reel = dict(value)
        reel.update(index=position, prompt=prompt, motion_prompt=motion_prompt)
        reels.append(reel)

    return {"legacy": False, "strategy": strategy, "reels": reels}


def planned_shot_count(plan: dict[str, Any]) -> int:
    """One reel is delivered, so the credit mode buys shots rather than reels."""
    if plan["legacy"]:
        return 1
    requested = STRATEGY_SHOT_COUNTS.get(plan["strategy"], DEFAULT_SHOT_COUNT)
    return max(1, min(requested, MAX_REEL_SHOTS))


def planned_shots(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Lay the campaign scenes out as the consecutive shots of one reel."""
    reels = plan["reels"]
    shots: list[dict[str, Any]] = []
    for shot_index in range(planned_shot_count(plan)):
        # More shots than scenes cycles back for a second, reseeded pass.
        reel_index = shot_index % len(reels)
        reel = reels[reel_index]
        reel_seed = int(reel.get("seed") if reel.get("seed") is not None else reel_index)
        shots.append(
            {
                "key": f"shot:{shot_index}",
                "shot_index": shot_index,
                "reel_index": reel_index,
                "prompt": str(reel["prompt"]),
                "motion_prompt": str(reel.get("motion_prompt") or reel["prompt"]),
                "negative_prompt": str(reel.get("negative_prompt") or DEFAULT_NEGATIVE),
                "seed": max(0, min(reel_seed + shot_index * 1009, 2_147_483_647)),
            }
        )
    return shots


def planned_model_load_counts(job: dict[str, Any]) -> dict[str, int]:
    """Expose the batch model schedule without importing ML dependencies."""
    shots = planned_shots(plan_batch(job))
    return {
        "flux": 1 if job.get("mode") == "generate_still" and shots else 0,
        "ltx_image_to_video": 1 if shots else 0,
    }


def find_job() -> tuple[Path, dict]:
    matches = sorted(INPUT_DIR.glob("**/job.json"))
    valid: list[tuple[Path, dict[str, Any]]] = []
    parse_errors: list[str] = []
    for path in matches:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                valid.append((path, payload))
            else:
                parse_errors.append(f"{path.name}: root is not an object")
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append(f"{path.name}: {type(exc).__name__}")
    if len(valid) != 1:
        detail = f"; invalid={parse_errors}" if parse_errors else ""
        raise RuntimeError(
            f"Expected exactly one valid mounted job.json, found {len(valid)} "
            f"from {len(matches)} candidate(s){detail}."
        )
    path, job = valid[0]
    return path.parent, job


def find_asset(dataset_dir: Path, filename: Any, *, required: bool) -> Path | None:
    if not filename:
        if required:
            raise ValueError("The job is missing a required asset filename.")
        return None
    name = str(filename)
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("Unsafe asset filename in job.")
    direct = dataset_dir / name
    if direct.is_file():
        return direct
    matches = [path for path in dataset_dir.rglob(name) if path.is_file()]
    if len(matches) == 1:
        return matches[0]
    if required:
        raise FileNotFoundError(f"Expected one mounted asset named {name!r}, found {len(matches)}.")
    return None


def _dependency_mismatches() -> list[str]:
    mismatches: list[str] = []
    for package, wanted in RUNTIME_REQUIREMENTS.items():
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != wanted:
            mismatches.append(f"{package}=={wanted}")
    return mismatches


NO_INTERNET_MESSAGE = (
    "This Kaggle session has no internet access, so inference packages and model "
    "weights cannot be downloaded. Open the kernel on Kaggle, turn Internet on in "
    "the session settings, and note that Kaggle only offers that switch to "
    "phone-verified accounts."
)


def internet_available(hosts: Iterable[str] = ("pypi.org", "huggingface.co")) -> bool:
    """Kaggle silently drops the internet toggle for unverified accounts."""
    import socket

    for host in hosts:
        try:
            socket.setdefaulttimeout(10)
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            continue
    return False


def ensure_runtime() -> None:
    requirements = _dependency_mismatches()
    if not requirements:
        return
    if not internet_available():
        raise RuntimeError(NO_INTERNET_MESSAGE)
    print("Installing pinned inference dependencies (torch is provided by Kaggle).", flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--no-cache-dir",
            # Fail fast instead of burning GPU minutes on unreachable mirrors.
            "--retries",
            "1",
            "--timeout",
            "20",
            *requirements,
        ],
        check=True,
    )


def _resize_crop(image: Any, width: int, height: int) -> Any:
    """EXIF-normalize and center-crop a PIL image to the exact model size."""
    from PIL import Image, ImageOps

    image = ImageOps.exif_transpose(image).convert("RGB")
    source_ratio = image.width / image.height
    target_ratio = width / height
    if source_ratio > target_ratio:
        crop_width = max(1, round(image.height * target_ratio))
        left = (image.width - crop_width) // 2
        image = image.crop((left, 0, left + crop_width, image.height))
    elif source_ratio < target_ratio:
        crop_height = max(1, round(image.width / target_ratio))
        top = (image.height - crop_height) // 2
        image = image.crop((0, top, image.width, top + crop_height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def load_uploaded_image(path: Path, width: int, height: int) -> Any:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as opened:
            opened.verify()
        with Image.open(path) as opened:
            if opened.width < 64 or opened.height < 64:
                raise ValueError("Uploaded image must be at least 64x64 pixels.")
            if opened.width * opened.height > 100_000_000:
                raise ValueError("Uploaded image is too large to decode safely.")
            return _resize_crop(opened, width, height)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Uploaded image is not a readable JPEG, PNG, or WebP.") from exc


def _cuda_cleanup(torch: Any) -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def huggingface_token() -> str | None:
    """Read a Hugging Face token from Kaggle Secrets, then the environment."""
    try:
        from kaggle_secrets import UserSecretsClient

        secret = UserSecretsClient().get_secret(HF_SECRET_LABEL)
        if secret and secret.strip():
            return secret.strip()
    except Exception:
        # No secret attached, or not running inside a Kaggle session.
        pass
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def configure_huggingface_auth() -> bool:
    token = huggingface_token()
    if not token:
        return False
    os.environ["HF_TOKEN"] = token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = token
    return True


def resolve_still_model(requested: str, authenticated: bool) -> tuple[str, str | None]:
    """Swap a gated model for an open one rather than failing the campaign."""
    if requested not in GATED_MODELS or authenticated:
        return requested, None
    warning = (
        f"{requested} is a gated Hugging Face repo and no {HF_SECRET_LABEL} secret is "
        f"attached to this kernel, so stills were generated with {FALLBACK_STILL_MODEL}. "
        f"To use {requested}, accept its licence on Hugging Face and add your token as a "
        f"Kaggle secret labelled {HF_SECRET_LABEL}."
    )
    return FALLBACK_STILL_MODEL, warning


def _is_flux(model_id: str) -> bool:
    return model_id in GATED_MODELS or "flux" in model_id.lower()


def load_still_pipeline(model_id: str, torch: Any) -> Any:
    print(f"Loading {model_id} once for campaign still generation.", flush=True)
    if _is_flux(model_id):
        from diffusers import FluxPipeline

        pipe = FluxPipeline.from_pretrained(model_id, torch_dtype=torch.float16)
    else:
        from diffusers import AutoPipelineForText2Image

        try:
            pipe = AutoPipelineForText2Image.from_pretrained(
                model_id, torch_dtype=torch.float16, variant="fp16"
            )
        except Exception:
            # Not every checkpoint publishes fp16 weights.
            pipe = AutoPipelineForText2Image.from_pretrained(
                model_id, torch_dtype=torch.float16
            )
    pipe.enable_sequential_cpu_offload()
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    return pipe


def native_still_size(model_id: str, width: int, height: int) -> tuple[int, int]:
    """Render keyframes near the model's useful native pixel density."""
    if _is_flux(model_id):
        return width, height
    minimum_side = 512 if model_id == SDXL_TURBO_MODEL else 768
    scale = minimum_side / max(1, min(width, height))
    if scale <= 1:
        return width, height

    def grow(value: int) -> int:
        return max(512, int(round(value * scale / 8)) * 8)

    return grow(width), grow(height)


def still_call_kwargs(model_id: str) -> dict[str, Any]:
    if _is_flux(model_id):
        return {
            "num_inference_steps": 4,
            "guidance_scale": 0.0,
            "max_sequence_length": 256,
        }
    if model_id == SDXL_TURBO_MODEL:
        return {"num_inference_steps": 4, "guidance_scale": 0.0}
    # Full SDXL needs classifier-free guidance and enough denoising steps to
    # produce a materially better keyframe than the distilled preview model.
    return {"num_inference_steps": 24, "guidance_scale": 7.0}


def fit_still_prompt(prompt: str, fits: Any) -> str:
    """Drop style boilerplate so a token-limited encoder keeps the subject.

    Campaign prompts read "<shared style and scenario>. <per-reel variant>",
    and CLIP truncates from the right, so an untrimmed prompt loses exactly
    the detail that makes each reel different.
    """
    text = prompt.strip()
    if not text or fits(text):
        return text
    head, separator, variant = text.rpartition(". ")
    if not separator:
        head, variant = text, ""
    clauses = [part.strip() for part in head.split(",") if part.strip()]

    def rebuild() -> str:
        joined = ", ".join(clauses)
        if joined and variant:
            return f"{joined}. {variant}"
        return joined or variant

    while len(clauses) > 1 and not fits(rebuild()):
        # The leading clause anchors medium and framing, so eat the rest.
        del clauses[1]
    if variant and clauses and not fits(rebuild()):
        clauses = []
    words = rebuild().split()
    while len(words) > 1 and not fits(" ".join(words)):
        words.pop()
    return " ".join(words)


def clip_prompt_fits(pipe: Any, model_id: str) -> Any:
    """Return a predicate for the CLIP encoders a pipeline actually uses."""
    candidates = [getattr(pipe, "tokenizer", None)]
    if not _is_flux(model_id):
        # SDXL runs two CLIP towers; FLUX's second encoder is T5, not CLIP.
        candidates.append(getattr(pipe, "tokenizer_2", None))
    tokenizers = [tokenizer for tokenizer in candidates if tokenizer is not None]
    if not tokenizers:
        return lambda _text: True

    def fits(text: str) -> bool:
        for tokenizer in tokenizers:
            limit = getattr(tokenizer, "model_max_length", CLIP_TOKEN_LIMIT)
            limit = int(limit or CLIP_TOKEN_LIMIT)
            if len(tokenizer(text, verbose=False).input_ids) > limit:
                return False
        return True

    return fits


def still_prompt_pair(pipe: Any, model_id: str, prompt: str) -> tuple[str, str | None]:
    """Return the CLIP prompt and, for FLUX, the untrimmed T5 prompt.

    FLUX conditions on both encoders, so the full text still reaches T5 as
    ``prompt_2`` while CLIP receives a copy that fits its 77-token window.
    """
    fitted = fit_still_prompt(prompt, clip_prompt_fits(pipe, model_id))
    return (fitted, prompt.strip()) if _is_flux(model_id) else (fitted, None)


def generate_still_with_pipe(
    pipe: Any,
    prompt: str,
    width: int,
    height: int,
    seed: int,
    torch: Any,
    model_id: str = FLUX_MODEL,
) -> Any:
    from PIL import Image

    started = _now()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    render_w, render_h = native_still_size(model_id, width, height)
    clip_prompt, t5_prompt = still_prompt_pair(pipe, model_id, prompt)
    kwargs = still_call_kwargs(model_id)
    if t5_prompt is not None:
        kwargs["prompt_2"] = t5_prompt
    elif clip_prompt != prompt.strip():
        print(
            f"Still prompt trimmed to the {CLIP_TOKEN_LIMIT}-token CLIP window: "
            f"{clip_prompt}",
            flush=True,
        )
    result = pipe(
        prompt=clip_prompt,
        width=render_w,
        height=render_h,
        generator=generator,
        **kwargs,
    )
    image = result.images[0].convert("RGB")
    if (render_w, render_h) != (width, height):
        image = image.resize((width, height), Image.LANCZOS)
    print(f"Still generated in {_now() - started:.1f}s.", flush=True)
    return image


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda error: memory allocation" in text


def load_ltx_pipeline(torch: Any) -> Any:
    from diffusers import LTXImageToVideoPipeline

    print("Loading LTX image-to-video pipeline once.", flush=True)
    pipe = LTXImageToVideoPipeline.from_pretrained(LTX_MODEL, torch_dtype=torch.float16)
    pipe.enable_sequential_cpu_offload()
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    return pipe


def generate_video_with_pipe(
    pipe: Any,
    image: Any,
    prompt: str,
    negative_prompt: str,
    attempts: Iterable[tuple[int, int, int]],
    seed: int,
    torch: Any,
    manifest: dict[str, Any],
    reel_index: int | str,
) -> list[Any]:
    attempt_settings = list(attempts)
    if not attempt_settings:
        raise ValueError("At least one video inference attempt is required.")
    errors: list[str] = []
    for attempt_number, (width, height, frames) in enumerate(attempt_settings, start=1):
        attempt = {
            "reel_index": reel_index,
            "attempt": attempt_number,
            "width": width,
            "height": height,
            "num_frames": frames,
            "status": "running",
        }
        manifest["attempts"].append(attempt)
        atomic_json(MANIFEST_PATH, manifest)
        prepared = _resize_crop(image, width, height)
        generator = torch.Generator(device="cpu").manual_seed(seed)
        print(
            f"LTX shot {reel_index} attempt {attempt_number}: "
            f"{width}x{height}, {frames} frames.",
            flush=True,
        )
        started = _now()
        try:
            result = pipe(
                image=prepared,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_frames=frames,
                num_inference_steps=40,
                guidance_scale=3.0,
                generator=generator,
            )
            output_frames = result.frames[0]
            attempt.update(status="succeeded", seconds=round(_now() - started, 3))
            manifest.setdefault("effective_settings", {})[str(reel_index)] = {
                "width": width,
                "height": height,
                "num_frames": frames,
                "fps": FPS,
                "seed": seed,
                "video_inference_steps": 40,
                "video_guidance_scale": 3.0,
            }
            return output_frames
        except Exception as exc:
            attempt.update(
                status="failed",
                seconds=round(_now() - started, 3),
                error=safe_error(exc),
            )
            errors.append(safe_error(exc))
            atomic_json(MANIFEST_PATH, manifest)
            _cuda_cleanup(torch)
            if not _is_oom(exc) or attempt_number == len(attempt_settings):
                raise
            print("CUDA OOM; retrying with lower legal settings.", flush=True)
    raise RuntimeError(f"All LTX attempts failed: {errors[-1] if errors else 'unknown error'}")


def _as_image(frame: Any) -> Any:
    """Normalize a pipeline frame, PIL or array, into an RGB PIL image."""
    from PIL import Image

    if isinstance(frame, Image.Image):
        return frame.convert("RGB")
    import numpy as np

    array = np.asarray(frame)
    if array.dtype.kind == "f":
        array = (array.clip(0, 1) * 255).astype("uint8")
    return Image.fromarray(array).convert("RGB")


def _rgb_bytes(frame: Any, width: int, height: int) -> bytes:
    from PIL import Image

    image = _as_image(frame)
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image.tobytes()


def encode_video(frames: list[Any], output: Path, fps: int = FPS) -> None:
    import imageio_ffmpeg

    if not frames:
        raise RuntimeError("The video pipeline returned no frames.")
    width, height = _as_image(frames[0]).size
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s:v",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for frame in frames:
            process.stdin.write(_rgb_bytes(frame, width, height))
        process.stdin.close()
        return_code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if return_code:
        raise RuntimeError(f"ffmpeg video encoding failed with exit code {return_code}.")


def join_shots_with_crossfade(
    shots: list[list[Any]], overlap: int = CROSSFADE_FRAMES
) -> list[Any]:
    """Dissolve consecutive shots so the reel plays as one continuous take.

    The crossfade is done on frames rather than with ffmpeg's `xfade`, which
    only exists from ffmpeg 4.3 and the bundled imageio-ffmpeg build is 4.2.2.
    """
    from PIL import Image

    if not shots or not all(shots):
        raise ValueError("Every shot must contain at least one frame.")
    joined: list[Any] = []
    for frames in shots:
        if not joined:
            joined.extend(frames)
            continue
        blend = min(overlap, len(joined), len(frames))
        tail = joined[-blend:] if blend else []
        del joined[len(joined) - blend :]
        for step, (outgoing, incoming) in enumerate(zip(tail, frames, strict=False)):
            weight = (step + 1) / (blend + 1)
            joined.append(
                Image.blend(_as_image(outgoing), _as_image(incoming), weight)
            )
        joined.extend(frames[blend:])
    return joined


def discover_devanagari_font(font_dir: Path) -> Path:
    """Find a Devanagari-capable font on Kaggle, downloading a fixed safe fallback."""
    candidates = (
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/local/share/fonts/NotoSansDevanagari-Regular.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    for root in SYSTEM_FONT_DIRS:
        if root.is_dir():
            matches = sorted(root.rglob("*Devanagari*.[ot]tf"))
            if matches:
                return matches[0]
    font_dir.mkdir(parents=True, exist_ok=True)
    fallback = font_dir / "NotoSansDevanagari-Regular.ttf"
    if not fallback.is_file():
        data = download_caption_font()
        temporary = fallback.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(fallback)
    return fallback


def download_caption_font() -> bytes:
    """Mirrors move; try each one before giving up on Devanagari captions."""
    failures: list[str] = []
    for url in FONT_DOWNLOAD_URLS:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(8 * 1024 * 1024 + 1)
        except Exception as exc:
            failures.append(f"{url}: {exc}")
            continue
        if len(data) > 8 * 1024 * 1024 or not data.startswith(b"\x00\x01\x00\x00"):
            failures.append(f"{url}: not a bounded TrueType font")
            continue
        return data
    raise RuntimeError(
        "Could not download a Devanagari caption font. Tried:\n" + "\n".join(failures)
    )


def discover_latin_font() -> Path | None:
    """Find a Latin-capable font already on the machine, preferring DejaVu."""
    try:
        import matplotlib

        bundled = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if bundled.is_file():
            return bundled
    except Exception:
        pass
    for name in LATIN_FONT_NAMES:
        for root in SYSTEM_FONT_DIRS:
            matches = sorted(root.rglob(name)) if root.is_dir() else []
            if matches:
                return matches[0]
    return None


def prepare_brand_fonts(font_dir: Path) -> tuple[list[Path], str | None]:
    """Resolve brand-wording fonts before any GPU work; never fail the run for one.

    Noto Sans Devanagari carries no Latin glyphs, so a Devanagari-only font
    draws "Aonla Online" as empty boxes. Both scripts get their own font and
    each string picks the one that can draw it.
    """
    fonts: list[Path] = []
    warning: str | None = None
    latin = discover_latin_font()
    if latin is not None:
        fonts.append(latin)
    try:
        fonts.append(discover_devanagari_font(font_dir))
    except Exception as exc:
        warning = (
            f"No Devanagari font was available ({exc}). Latin brand wording and all "
            "narration audio are unaffected; Hindi wording would render as boxes."
        )
    if fonts:
        return fonts, warning
    for root in SYSTEM_FONT_DIRS:
        matches = sorted(root.rglob("*.ttf")) if root.is_dir() else []
        if matches:
            return [matches[0]], warning
    raise RuntimeError("No usable TrueType font was found for the brand wording.")


def _font_covers(font: Path, text: str) -> bool | None:
    """Whether a font has a glyph for every character, or None if unmeasurable."""
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return None
    try:
        with TTFont(str(font), fontNumber=0, lazy=True) as opened:
            cmap = opened.getBestCmap()
    except Exception:
        return None
    return all(ord(char) in cmap for char in text if not char.isspace())


def font_for(text: str, fonts: Sequence[Path]) -> Path:
    """Pick a font that can draw this exact text, not merely its language."""
    if not fonts:
        raise ValueError("At least one font is required.")
    unmeasured: list[Path] = []
    for font in fonts:
        covers = _font_covers(font, text)
        if covers:
            return font
        if covers is None:
            unmeasured.append(font)
    devanagari = any(0x0900 <= ord(char) <= 0x097F for char in text)
    for font in unmeasured:
        if ("devanagari" in font.name.lower()) == devanagari:
            return font
    return unmeasured[0] if unmeasured else fonts[0]


def brand_identity(variables: Mapping[str, Any]) -> dict[str, str]:
    """Read the brand block from campaign variables so nothing is hardcoded."""
    def value(key: str, fallback: str) -> str:
        text = str(variables.get(key) or "").strip()
        return text or fallback

    name = value("app_name", "Aonla Online")
    return {
        "name": name[:40],
        "kind": value("app_kind", DEFAULT_APP_KIND)[:60],
        "platforms": f"Available for {value('platforms', DEFAULT_PLATFORMS)}"[:80],
        "url": value("cta_url", "")[:60],
    }


def _fitted_font(
    draw: Any, text: str, fonts: Sequence[Path], largest: int, smallest: int, width: int
) -> Any:
    from PIL import ImageFont

    font = font_for(text, fonts)
    for size in range(largest, smallest - 1, -2):
        selected = ImageFont.truetype(str(font), size)
        if draw.textbbox((0, 0), text, font=selected)[2] <= width:
            return selected
    return ImageFont.truetype(str(font), smallest)


def _open_logo(logo: Path | None, box: int) -> Any:
    """Load the uploaded logo as RGBA, bounded to a box; None when unusable."""
    from PIL import Image

    if not logo:
        return None
    try:
        with Image.open(logo) as opened:
            mark = opened.convert("RGBA")
    except Exception:
        return None
    mark.thumbnail((box, box), Image.Resampling.LANCZOS)
    return mark


def _draw_brand_block(
    canvas: Any, fonts: Sequence[Path], brand: dict[str, str], *, top: int
) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas)
    lines = (
        (brand["name"], top, 96, 52, "white"),
        (brand["kind"], top + 120, 58, 34, "#ffb000"),
        (brand["platforms"], top + 216, 46, 28, "#e8e8e8"),
    )
    for text, offset, largest, smallest, fill in lines:
        draw.text(
            (FINAL_WIDTH // 2, offset),
            text,
            font=_fitted_font(draw, text, fonts, largest, smallest, 920),
            fill=fill,
            anchor="mm",
        )


def create_end_card(
    output: Path, fonts: Sequence[Path], brand: dict[str, str], *, logo: Path | None = None
) -> None:
    """Render the reel's closing frame, the only place text is burned in."""
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (FINAL_WIDTH, FINAL_HEIGHT), "#101820")
    draw = ImageDraw.Draw(canvas)
    accent = "#ffb000"
    draw.rectangle((0, 0, FINAL_WIDTH, 34), fill=accent)
    mark = _open_logo(logo, 320)
    if mark is not None:
        canvas.paste(mark, ((FINAL_WIDTH - mark.width) // 2, 560), mark)
    # Without a logo the card would be top-heavy, so centre the wording instead.
    top = 1020 if mark is not None else 860
    _draw_brand_block(canvas, fonts, brand, top=top)
    if brand["url"]:
        draw.text(
            (FINAL_WIDTH // 2, top + 400),
            brand["url"],
            font=_fitted_font(draw, brand["url"], fonts, 44, 28, 860),
            fill=accent,
            anchor="mm",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG")


def create_thumbnail(
    output: Path,
    fonts: Sequence[Path],
    brand: dict[str, str],
    *,
    hero: Any,
    logo: Path | None = None,
) -> None:
    """Build the reel cover from its own hero keyframe plus the brand block."""
    from PIL import Image

    canvas = _resize_crop(hero, FINAL_WIDTH, FINAL_HEIGHT)
    scrim = Image.new("L", (1, FINAL_HEIGHT))
    fade_from = int(FINAL_HEIGHT * 0.52)
    for y in range(FINAL_HEIGHT):
        if y <= fade_from:
            continue
        scrim.putpixel((0, y), int(225 * (y - fade_from) / (FINAL_HEIGHT - fade_from)))
    canvas = Image.composite(
        Image.new("RGB", canvas.size, "#06090d"),
        canvas,
        scrim.resize((FINAL_WIDTH, FINAL_HEIGHT)),
    )
    _draw_brand_block(canvas, fonts, brand, top=1400)
    mark = _open_logo(logo, WATERMARK_BOX)
    if mark is not None:
        canvas.paste(
            mark,
            (
                FINAL_WIDTH - mark.width - WATERMARK_MARGIN,
                FINAL_HEIGHT - mark.height - WATERMARK_MARGIN,
            ),
            mark,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="JPEG", quality=90, optimize=True)


def create_watermark(
    output: Path, fonts: Sequence[Path], brand: dict[str, str], *, logo: Path | None = None
) -> Path:
    """Prepare the bottom-right mark: the uploaded logo, else a brand wordmark."""
    from PIL import Image, ImageDraw, ImageFont

    mark = _open_logo(logo, WATERMARK_BOX)
    if mark is None:
        # Without an uploaded logo the brand name itself is the only permitted
        # on-video text, so render it as a compact badge.
        badge_font = ImageFont.truetype(str(font_for(brand["name"], fonts)), 44)
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        left, top, right, bottom = (round(value) for value in probe.textbbox(
            (0, 0), brand["name"], font=badge_font
        ))
        padding = 26
        mark = Image.new(
            "RGBA",
            (right - left + padding * 2, bottom - top + padding * 2),
            (16, 24, 32, 170),
        )
        ImageDraw.Draw(mark).text(
            (padding - left, padding - top),
            brand["name"],
            font=badge_font,
            fill=(255, 255, 255, 236),
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    mark.save(output, format="PNG")
    return output


async def _save_edge_tts(text: str, voice: str, output: Path) -> None:
    import edge_tts

    await edge_tts.Communicate(text=text, voice=voice).save(str(output))


def generate_narration(text: str, voice: str, output: Path) -> None:
    """Generate speech with Edge TTS; caller owns network-failure fallback."""
    if not text.strip():
        raise ValueError("Narration script is empty.")
    output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_save_edge_tts(text, voice, output))
    if not output.is_file() or output.stat().st_size < 128:
        raise RuntimeError("Edge TTS returned no usable narration audio.")


def build_reel_ffmpeg_args(
    ffmpeg: str,
    *,
    video: Path,
    end_card: Path,
    watermark: Path | None,
    output: Path,
    content_duration: float,
    voice: Path | None,
    music: Path | None,
    total_duration: float,
) -> list[str]:
    """Construct a shell-free vertical post-production command.

    Nothing is written over the footage except the bottom-right brand mark;
    captions ship as a sidecar SRT and the wording lives on the end card.
    """
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video)]
    args += ["-loop", "1", "-t", f"{END_CARD_SECONDS:.3f}", "-i", str(end_card)]
    next_index = 2
    watermark_index: int | None = None
    if watermark:
        watermark_index = next_index
        next_index += 1
        args += ["-loop", "1", "-t", f"{content_duration:.3f}", "-i", str(watermark)]
    voice_index: int | None = None
    music_index: int | None = None
    if voice:
        voice_index = next_index
        next_index += 1
        args += ["-i", str(voice)]
    if music:
        music_index = next_index
        args += ["-stream_loop", "-1", "-i", str(music)]
    silence_index: int | None = None
    if voice is None and music is None:
        silence_index = next_index
        args += [
            "-f", "lavfi", "-t", f"{total_duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
    video_filter = (
        f"scale={FINAL_WIDTH}:{FINAL_HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={FINAL_WIDTH}:{FINAL_HEIGHT},unsharp=5:5:0.45:3:3:0.0,"
        f"setsar=1,fps={FINAL_FPS},"
        f"tpad=stop_mode=clone:stop_duration={content_duration:.3f},"
        f"trim=duration={content_duration:.3f},setpts=PTS-STARTPTS[content]"
    )
    filters = [f"[0:v]{video_filter}"]
    content = "[content]"
    if watermark_index is not None:
        filters.append(f"[{watermark_index}:v]scale={WATERMARK_BOX}:-1[mark]")
        filters.append(
            f"[content][mark]overlay="
            f"W-w-{WATERMARK_MARGIN}:H-h-{WATERMARK_MARGIN}[branded]"
        )
        content = "[branded]"
    filters.append(
        f"[1:v]scale={FINAL_WIDTH}:{FINAL_HEIGHT},fps={FINAL_FPS},setpts=PTS-STARTPTS[end]"
    )
    filters.append(f"{content}[end]concat=n=2:v=1:a=0[vout]")
    audio_inputs: list[str] = []
    if voice_index is not None:
        filters.append(
            f"[{voice_index}:a]aresample=48000,highpass=f=80,lowpass=f=12000,"
            "acompressor=threshold=0.125:ratio=3:attack=20:release=250,"
            "volume=1.0,"
            f"adelay={VOICE_LEAD_MS}|{VOICE_LEAD_MS},apad,"
            f"atrim=duration={total_duration:.3f}[voice]"
        )
        audio_inputs.append("[voice]")
    if music_index is not None:
        music_volume = 0.12 if voice_index is not None else 0.24
        filters.append(
            f"[{music_index}:a]aresample=48000,volume={music_volume:.2f},"
            f"atrim=duration={total_duration:.3f},asetpts=PTS-STARTPTS[music]"
        )
        audio_inputs.append("[music]")
    if silence_index is not None:
        filters.append(
            f"[{silence_index}:a]atrim=duration={total_duration:.3f},"
            "asetpts=PTS-STARTPTS[silence]"
        )
        audio_inputs.append("[silence]")
    if audio_inputs:
        # amix only learned the `normalize` option in ffmpeg 4.4 and the bundled
        # imageio-ffmpeg build is 4.2.2, so mix option-free and let loudnorm
        # restore the level. A lone stream needs no mixing at all.
        mix = (
            f"amix=inputs={len(audio_inputs)}:duration=longest,"
            if len(audio_inputs) > 1
            else ""
        )
        filters.append(
            "".join(audio_inputs)
            + mix
            + "loudnorm=I=-16:TP=-1.5:LRA=11,"
            # A mono TTS voice would otherwise deliver a mono reel.
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=duration={total_duration:.3f}[aout]"
        )
    args += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    args += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FINAL_FPS),
        "-t", f"{total_duration:.3f}", "-movflags", "+faststart", str(output),
    ]
    return args


def postprocess_reel(
    video: Path,
    output: Path,
    end_card: Path,
    *,
    watermark: Path | None,
    content_duration: float,
    voice: Path | None,
    music: Path | None,
) -> None:
    import imageio_ffmpeg

    command = build_reel_ffmpeg_args(
        imageio_ffmpeg.get_ffmpeg_exe(),
        video=video,
        end_card=end_card,
        watermark=watermark,
        output=output,
        content_duration=content_duration,
        voice=voice,
        music=music,
        total_duration=content_duration + END_CARD_SECONDS,
    )
    subprocess.run(command, check=True)


def validate_job(job: dict[str, Any]) -> None:
    if job.get("mode") not in {"generate_still", "uploaded_image"}:
        raise ValueError("mode must be 'generate_still' or 'uploaded_image'.")
    if campaign_from_job(job) is None and not str(job.get("prompt") or "").strip():
        raise ValueError("prompt is required.")


def run_job(dataset_dir: Path, job: dict) -> Path:
    validate_job(job)
    plan = plan_batch(job)
    ensure_runtime()

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("A CUDA GPU is required; enable the Kaggle T4 accelerator.")
    capability = torch.cuda.get_device_capability()
    if capability[0] != 7:
        print(f"Warning: expected T4 compute capability 7.x, found {capability}.", flush=True)

    seed = int(job.get("seed") if job.get("seed") is not None else 0)
    seed = max(0, min(seed, 2_147_483_647))
    width, height = legal_dimensions(job.get("width"), job.get("height"))
    frames = legal_frames(job.get("num_frames"))
    shots = planned_shots(plan)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    authenticated = configure_huggingface_auth()
    still_model, gated_warning = resolve_still_model(
        str(job.get("still_model") or FLUX_MODEL), authenticated
    )
    if gated_warning:
        print(gated_warning, flush=True)
    # Fetched before inference so a broken font mirror costs seconds, not a whole run.
    fonts, font_warning = prepare_brand_fonts(OUTPUTS_DIR / ".fonts")
    if font_warning:
        print(font_warning, flush=True)
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "job_id": str(job.get("id") or ""),
        "status": "running",
        "mode": job["mode"],
        "legacy": plan["legacy"],
        "strategy": plan["strategy"],
        "models": {
            "still": still_model if job["mode"] == "generate_still" else None,
            "video": LTX_MODEL,
        },
        "warnings": [text for text in (gated_warning, font_warning) if text],
        "model_load_counts": {"flux": 0, "ltx_image_to_video": 0},
        "planned_model_load_counts": planned_model_load_counts(job),
        "requested_settings": {
            "width": job.get("width"),
            "height": job.get("height"),
            "num_frames": job.get("num_frames"),
            "seed": job.get("seed"),
            "strategy": plan["strategy"],
            "scene_count": len(plan["reels"]),
            "shot_count": len(shots),
        },
        "shot_plan": shots,
        "effective_settings": {},
        "delivery": {
            "reels": 1,
            "shots": len(shots),
            "scene_concepts": len(plan["reels"]),
            "shot_transition": "crossfade",
        },
        "runtime": {
            "torch_dtype": "float16",
            "device": torch.cuda.get_device_name(0),
            "dependency_versions": {
                package: importlib.metadata.version(package)
                for package in RUNTIME_REQUIREMENTS
            },
        },
        "attempts": [],
        "timing_seconds": {},
        "errors": [],
    }
    atomic_json(MANIFEST_PATH, manifest)
    if not plan["legacy"]:
        atomic_json(CAMPAIGN_MANIFEST_PATH, manifest)
    total_started = _now()

    # Phase 1: prepare one keyframe per short shot while the still model is loaded.
    images: dict[str, Any] = {}
    still_started = _now()
    if job["mode"] == "uploaded_image":
        image_path = find_asset(dataset_dir, job.get("image_filename"), required=True)
        assert image_path is not None
        uploaded = load_uploaded_image(image_path, width, height)
        for shot in shots:
            images[shot["key"]] = uploaded
    else:
        flux = load_still_pipeline(still_model, torch)
        manifest["model_load_counts"]["flux"] += 1
        try:
            for shot in shots:
                shot_key = str(shot["key"])
                reel_seed = int(shot["seed"])
                still_error: BaseException | None = None
                tried_dimensions: set[tuple[int, int]] = set()
                for attempt_number, (attempt_w, attempt_h, _) in enumerate(
                    retry_settings(width, height, frames), start=1
                ):
                    if (attempt_w, attempt_h) in tried_dimensions:
                        continue
                    tried_dimensions.add((attempt_w, attempt_h))
                    attempt = {
                        "phase": "still",
                        "shot_key": shot_key,
                        "reel_index": shot["reel_index"],
                        "shot_index": shot["shot_index"],
                        "attempt": attempt_number,
                        "width": attempt_w,
                        "height": attempt_h,
                        "status": "running",
                    }
                    manifest["attempts"].append(attempt)
                    try:
                        images[shot_key] = generate_still_with_pipe(
                            flux,
                            str(shot["prompt"]),
                            attempt_w,
                            attempt_h,
                            reel_seed,
                            torch,
                            still_model,
                        )
                        attempt["status"] = "succeeded"
                        still_error = None
                        break
                    except Exception as exc:
                        still_error = exc
                        attempt.update(status="failed", error=safe_error(exc))
                        _cuda_cleanup(torch)
                        if not _is_oom(exc):
                            raise
                if still_error is not None:
                    raise still_error
        finally:
            del flux
            _cuda_cleanup(torch)
            print(f"{still_model} fully unloaded before video inference.", flush=True)
    manifest["timing_seconds"]["still_preparation"] = round(_now() - still_started, 3)

    # Phase 2: animate each 3–4 second shot, then dissolve them into one take.
    video_started = _now()
    shot_frames: list[list[Any]] = []
    ltx = load_ltx_pipeline(torch)
    manifest["model_load_counts"]["ltx_image_to_video"] += 1
    try:
        for shot in shots:
            shot_key = str(shot["key"])
            reel_seed = int(shot["seed"])
            try:
                video_frames = generate_video_with_pipe(
                    ltx,
                    images[shot_key],
                    str(shot["motion_prompt"]),
                    str(shot["negative_prompt"]),
                    retry_settings(width, height, frames),
                    reel_seed,
                    torch,
                    manifest,
                    shot_key,
                )
                shot_frames.append([_as_image(frame) for frame in video_frames])
                del video_frames
                _cuda_cleanup(torch)
            except Exception as exc:
                manifest["errors"].append(
                    {"shot_key": shot_key, "error": safe_error(exc)}
                )
                raise
    finally:
        del ltx
        _cuda_cleanup(torch)
        print("LTX fully unloaded before CPU post-processing.", flush=True)
    sequence_frames = join_shots_with_crossfade(shot_frames)
    shot_frames.clear()
    sequence_path = OUTPUTS_DIR / ".sequence.mp4"
    encode_video(sequence_frames, sequence_path)
    sequence_duration = len(sequence_frames) / FPS
    del sequence_frames
    manifest["timing_seconds"]["video_inference"] = round(_now() - video_started, 3)

    # Phase 3: narration, brand marks, end card, thumbnail and reel delivery.
    post_started = _now()
    music_path = find_asset(dataset_dir, job.get("audio_filename"), required=False)
    uploaded_voice = find_asset(dataset_dir, job.get("voice_filename"), required=False)
    logo_path = find_asset(dataset_dir, job.get("logo_filename"), required=False)
    campaign = campaign_from_job(job) or {}
    raw_variables = campaign.get("variables")
    brand = brand_identity(raw_variables if isinstance(raw_variables, dict) else {})
    reel = plan["reels"][0]
    manifest["voice_over_disclosure"] = (
        "Narration is voice-over only. People may appear visually; no lip-sync is generated."
    )
    manifest["postproduction"] = {
        "platforms": ["Instagram Reels", "Facebook Reels"],
        "width": FINAL_WIDTH,
        "height": FINAL_HEIGHT,
        "fps": FINAL_FPS,
        "video_codec": "h264",
        "pixel_format": "yuv420p",
        "audio_codec": "aac",
        "target_loudness_lufs": -16,
        "brand_fonts": [str(path) for path in fonts],
        "captions_burned_in": False,
        "on_video_text": "brand mark only, bottom right",
        "end_card_seconds": END_CARD_SECONDS,
        "crossfade_frames": CROSSFADE_FRAMES,
        "brand": brand,
    }

    spoken = reel_voice_lines(reel)
    script = "\n\n".join(spoken)
    script_path = OUTPUTS_DIR / "reel_001_script.txt"
    script_path.write_text(script + "\n", encoding="utf-8")
    content_duration = max(sequence_duration, estimate_speech_seconds(script))
    srt_path = OUTPUTS_DIR / "reel_001.srt"
    # Sidecar captions match the voice-over; nothing is burned into the video.
    srt_path.write_text(build_srt(spoken, content_duration), encoding="utf-8")

    generated_voice = OUTPUTS_DIR / ".reel_001.voice.mp3"
    tts_succeeded = False
    voice_error: str | None = None
    requested_voice = str(job.get("voice") or "")
    language = reel.get("language") or job.get("language")
    if requested_voice != "uploaded" and script:
        try:
            generate_narration(script, resolve_voice(requested_voice, language), generated_voice)
            tts_succeeded = True
        except Exception as exc:
            voice_error = safe_error(exc)
    narration_source, warning = narration_fallback(tts_succeeded, uploaded_voice)
    if requested_voice == "uploaded" and uploaded_voice is not None:
        narration_source, warning = "uploaded_voice_over", None
    selected_voice = (
        generated_voice
        if tts_succeeded
        else uploaded_voice
        if narration_source == "uploaded_voice_over"
        else None
    )
    if warning:
        warning_entry = {"reel_index": 0, "warning": warning}
        if voice_error:
            warning_entry["detail"] = voice_error
        manifest["warnings"].append(warning_entry)

    end_card = OUTPUTS_DIR / ".reel_001.end.png"
    create_end_card(end_card, fonts, brand, logo=logo_path)
    watermark = create_watermark(
        OUTPUTS_DIR / ".reel_001.mark.png", fonts, brand, logo=logo_path
    )
    thumbnail = OUTPUTS_DIR / "reel_001.thumb.jpg"
    create_thumbnail(
        thumbnail, fonts, brand, hero=images[str(shots[0]["key"])], logo=logo_path
    )
    output = OUTPUTS_DIR / "reel_001.mp4"
    postprocess_reel(
        sequence_path,
        output,
        end_card,
        watermark=watermark,
        content_duration=content_duration,
        voice=selected_voice,
        music=music_path,
    )
    for temporary in (sequence_path, generated_voice, end_card, watermark):
        temporary.unlink(missing_ok=True)
    outputs: list[dict[str, Any]] = [
        {
            "reel_index": 0,
            "filename": output.name,
            "script_filename": script_path.name,
            "srt_filename": srt_path.name,
            "thumbnail_filename": thumbnail.name,
            "shot_count": len(shots),
            "generated_sequence_seconds": round(sequence_duration, 3),
            "narration_source": narration_source,
            "voice": resolve_voice(requested_voice, language) if tts_succeeded else None,
            "voice_over_no_lip_sync": True,
            "duration_seconds": round(content_duration + END_CARD_SECONDS, 3),
            "bytes": output.stat().st_size,
        }
    ]

    shutil.copyfile(output, RESULT_PATH)
    manifest["audio"] = {
        "music_mixed": bool(music_path),
        "music_filename": music_path.name if music_path else None,
        "uploaded_voice_over_supplied": bool(uploaded_voice),
        "mix": "deterministic music ducking under voice-over; EBU R128 loudness normalization",
    }
    manifest["timing_seconds"]["cpu_postprocessing"] = round(_now() - post_started, 3)
    _cuda_cleanup(torch)
    manifest["timing_seconds"]["total"] = round(_now() - total_started, 3)
    manifest["status"] = "succeeded"
    manifest["outputs"] = outputs
    manifest["output"] = {
        "filename": RESULT_PATH.name,
        "codec": "h264",
        "pixel_format": "yuv420p",
        "width": FINAL_WIDTH,
        "height": FINAL_HEIGHT,
        "fps": FINAL_FPS,
        "audio_codec": "aac",
        "bytes": RESULT_PATH.stat().st_size,
    }
    atomic_json(MANIFEST_PATH, manifest)
    if not plan["legacy"]:
        atomic_json(CAMPAIGN_MANIFEST_PATH, manifest)
    return RESULT_PATH


def main() -> None:
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    started = _now()
    try:
        dataset_dir, job = find_job()
        if job.get("bootstrap"):
            atomic_json(
                MANIFEST_PATH,
                {
                    "schema_version": 1,
                    "job_id": str(job.get("id") or "bootstrap"),
                    "status": "bootstrap_succeeded",
                },
            )
            print("Video Studio runner bootstrap completed.")
            return
        output = run_job(dataset_dir, job)
        if output.resolve() != RESULT_PATH.resolve() or not RESULT_PATH.is_file():
            raise RuntimeError("Runner must produce /kaggle/working/result.mp4.")
    except BaseException as exc:
        try:
            existing: dict[str, Any] = {}
            if MANIFEST_PATH.is_file():
                loaded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            existing.update(
                status="failed",
                error=safe_error(exc),
                failed_after_seconds=round(_now() - started, 3),
            )
            existing.setdefault("errors", []).append(safe_error(exc))
            atomic_json(MANIFEST_PATH, existing)
            if CAMPAIGN_MANIFEST_PATH.is_file():
                atomic_json(CAMPAIGN_MANIFEST_PATH, existing)
        except Exception as manifest_exc:
            print(f"Could not write failure manifest: {safe_error(manifest_exc)}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

