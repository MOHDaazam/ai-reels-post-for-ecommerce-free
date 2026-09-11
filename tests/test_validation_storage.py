from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.config import Settings
from app.storage import JobStorage
from app.validation import (
    ValidationError,
    parse_seed,
    resolve_presets,
    safe_job_id,
    sniff_audio,
    sniff_image,
    validate_negative_prompt,
    validate_prompt,
)


def storage_for(tmp_path: Path) -> JobStorage:
    return JobStorage(
        Settings(
            root_dir=tmp_path,
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'studio.db'}",
        )
    )


def upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(data))


def test_form_values_are_trimmed_and_bounded() -> None:
    assert validate_prompt("  product shot  ", max_chars=20) == "product shot"
    assert validate_negative_prompt(None, max_chars=20) == ""
    assert parse_seed(" 0 ") == 0
    assert parse_seed("") is None
    with pytest.raises(ValidationError, match="required"):
        validate_prompt("  ", max_chars=20)
    with pytest.raises(ValidationError, match="at most"):
        validate_negative_prompt("x" * 21, max_chars=20)
    with pytest.raises(ValidationError, match="between"):
        parse_seed("-1")
    with pytest.raises(ValidationError, match="integer"):
        parse_seed("3.14")


def test_presets_enforce_model_legal_dimensions_and_frames() -> None:
    preset = resolve_presets("widescreen_16_9", "standard_49")
    assert (preset.width, preset.height, preset.num_frames) == (736, 416, 49)
    assert preset.width % 32 == preset.height % 32 == 0
    assert (preset.num_frames - 1) % 8 == 0
    with pytest.raises(ValidationError):
        resolve_presets("custom", "standard_49")


@pytest.mark.parametrize(
    ("header", "name", "kind"),
    [
        (b"\xff\xd8\xffpayload", "photo.jpeg", "jpg"),
        (b"\x89PNG\r\n\x1a\npayload", "photo.png", "png"),
        (b"RIFFxxxxWEBPpayload", "photo.webp", "webp"),
    ],
)
def test_image_sniffing_requires_matching_contents(
    header: bytes, name: str, kind: str
) -> None:
    assert sniff_image(header, name) == kind
    with pytest.raises(ValidationError):
        sniff_image(header, "../" + name)


@pytest.mark.parametrize(
    ("header", "name", "kind"),
    [
        (b"ID3payload", "music.mp3", "mp3"),
        (b"RIFFxxxxWAVEpayload", "music.wav", "wav"),
        (b"OggSpayload", "music.ogg", "ogg"),
        (b"\x00\x00\x00\x18ftypM4A ", "music.m4a", "m4a"),
        (b"\xff\xf1payload", "music.aac", "aac"),
    ],
)
def test_audio_sniffing_accepts_supported_signatures(
    header: bytes, name: str, kind: str
) -> None:
    assert sniff_audio(header, name) == kind


def test_job_storage_isolates_job_paths(tmp_path: Path) -> None:
    storage = storage_for(tmp_path)
    first = storage.ensure_layout("first")
    second = storage.ensure_layout("second")
    storage.append_log("first", "first-only")
    storage.write_job_json("second", {"id": "second"})

    assert first != second
    assert "first-only" in storage.read_logs("first")
    assert storage.read_logs("second") == ""
    assert not (first / "job.json").exists()
    with pytest.raises(ValidationError, match="escapes"):
        storage.job_dir("../../outside")


@pytest.mark.asyncio
async def test_uploads_are_renamed_and_size_limited(tmp_path: Path) -> None:
    storage = storage_for(tmp_path)
    storage.ensure_layout("job")
    image_name = await storage.save_image(
        "job", upload("customer name.PNG", b"\x89PNG\r\n\x1a\npayload"), max_bytes=64
    )
    audio_name = await storage.save_audio(
        "job", upload("track.MP3", b"ID3payload"), max_bytes=64
    )
    logo_name = await storage.save_logo(
        "job", upload("brand.PNG", b"\x89PNG\r\n\x1a\npayload"), max_bytes=64
    )
    voice_name = await storage.save_voice(
        "job", upload("voice.WAV", b"RIFFxxxxWAVEpayload"), max_bytes=64
    )
    assert image_name == "source.png"
    assert audio_name == "music.mp3"
    assert logo_name == "logo.png"
    assert voice_name == "voice.wav"
    assert (storage.job_dir("job") / "input" / image_name).is_file()

    with pytest.raises(ValidationError, match="exceeds"):
        await storage.save_image(
            "job", upload("large.jpg", b"\xff\xd8\xff" + b"x" * 64), max_bytes=8
        )
    with pytest.raises(ValidationError, match="empty"):
        await storage.save_audio("job", upload("empty.mp3", b""), max_bytes=64)
    with pytest.raises(ValidationError, match="contents"):
        await storage.save_image("job", upload("fake.jpg", b"not-an-image"), max_bytes=64)


def test_safe_job_id_rejects_non_uuid_and_normalizes_case() -> None:
    value = "A4E95A21-70DD-4F03-B6CB-1A3D783FAF22"
    assert safe_job_id(value) == value.lower()
    for unsafe in ("", "../outside", "not-a-uuid", "g" * 36):
        with pytest.raises(ValidationError):
            safe_job_id(unsafe)
