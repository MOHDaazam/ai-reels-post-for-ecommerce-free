from __future__ import annotations

from dataclasses import dataclass

# LTX-safe: width/height divisible by 32; frames = 8k+1.
ASPECT_PRESETS: dict[str, tuple[int, int, str]] = {
    "cinematic_3_2": (704, 480, "704×480 cinematic"),
    "portrait_2_3": (480, 704, "480×704 portrait"),
    "square": (512, 512, "512×512 square"),
    "widescreen_16_9": (736, 416, "736×416 widescreen"),
}

DURATION_PRESETS: dict[str, tuple[int, str]] = {
    "short_25": (25, "Short · 25 frames"),
    "standard_49": (49, "Standard · 49 frames"),
    "cinematic_81": (81, "Cinematic · 81 frames"),
}

# Portrait inference preserves substantially more source detail when the final
# delivery is cropped and upscaled to a 9:16 social reel.
DEFAULT_ASPECT = "portrait_2_3"
DEFAULT_DURATION = "cinematic_81"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"RIFF", "webp_or_wav"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


class ValidationError(ValueError):
    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class ResolvedPreset:
    aspect_ratio: str
    duration_preset: str
    width: int
    height: int
    num_frames: int
    aspect_label: str
    duration_label: str


def resolve_presets(aspect_ratio: str, duration_preset: str) -> ResolvedPreset:
    if aspect_ratio not in ASPECT_PRESETS:
        raise ValidationError("Choose a supported aspect ratio.", "aspect_ratio")
    if duration_preset not in DURATION_PRESETS:
        raise ValidationError("Choose a supported duration preset.", "duration_preset")
    width, height, aspect_label = ASPECT_PRESETS[aspect_ratio]
    frames, duration_label = DURATION_PRESETS[duration_preset]
    if width % 32 or height % 32:
        raise ValidationError("Internal resolution must be divisible by 32.")
    if (frames - 1) % 8:
        raise ValidationError("Frame count must be 8k+1.")
    return ResolvedPreset(
        aspect_ratio=aspect_ratio,
        duration_preset=duration_preset,
        width=width,
        height=height,
        num_frames=frames,
        aspect_label=aspect_label,
        duration_label=duration_label,
    )


def parse_seed(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise ValidationError("Seed must be an integer.", "seed") from exc
    if value < 0 or value > 2_147_483_647:
        raise ValidationError("Seed must be between 0 and 2147483647.", "seed")
    return value


def validate_prompt(prompt: str, *, max_chars: int) -> str:
    text = (prompt or "").strip()
    if not text:
        raise ValidationError("Prompt is required.", "prompt")
    if len(text) > max_chars:
        raise ValidationError(f"Prompt must be at most {max_chars} characters.", "prompt")
    return text


def validate_negative_prompt(prompt: str | None, *, max_chars: int) -> str:
    text = (prompt or "").strip()
    if len(text) > max_chars:
        raise ValidationError(
            f"Negative prompt must be at most {max_chars} characters.",
            "negative_prompt",
        )
    return text


def validate_mode(mode: str) -> str:
    if mode not in {"generate_still", "uploaded_image"}:
        raise ValidationError("Choose generate still or uploaded image.", "mode")
    return mode


def sniff_image(header: bytes, filename: str, *, field: str = "image") -> str:
    name = filename.lower()
    suffix = _suffix(name)
    if suffix not in IMAGE_EXTENSIONS:
        raise ValidationError(f"{field.capitalize()} must be JPEG, PNG, or WebP.", field)
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"RIFF") and b"WEBP" in header[:16]:
        return "webp"
    raise ValidationError(
        f"{field.capitalize()} file contents do not match a supported type.", field
    )


def sniff_audio(header: bytes, filename: str, *, field: str = "audio") -> str:
    name = filename.lower()
    suffix = _suffix(name)
    if suffix not in AUDIO_EXTENSIONS:
        raise ValidationError(
            f"{field.capitalize()} must be MP3, WAV, M4A, AAC, or OGG.", field
        )
    if header.startswith(b"ID3") or header[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa"}:
        return "mp3"
    if header.startswith(b"RIFF") and b"WAVE" in header[:16]:
        return "wav"
    if header.startswith(b"OggS"):
        return "ogg"
    if header[4:8] == b"ftyp":
        return "m4a"
    if suffix in {".m4a", ".aac"} and len(header) >= 8:
        # Allow AAC ADTS
        if header[0] == 0xFF and (header[1] & 0xF0) == 0xF0:
            return "aac"
    raise ValidationError(
        f"{field.capitalize()} file contents do not match a supported type.", field
    )


def safe_job_id(job_id: str) -> str:
    text = (job_id or "").strip().lower()
    if len(text) != 36:
        raise ValidationError("Invalid job id.")
    parts = text.split("-")
    if len(parts) != 5:
        raise ValidationError("Invalid job id.")
    hexpart = text.replace("-", "")
    if len(hexpart) != 32 or any(c not in "0123456789abcdef" for c in hexpart):
        raise ValidationError("Invalid job id.")
    return text


def _suffix(name: str) -> str:
    if "/" in name or "\\" in name or ".." in name:
        raise ValidationError("Upload filename is not allowed.")
    dot = name.rfind(".")
    if dot < 0:
        return ""
    return name[dot:]
