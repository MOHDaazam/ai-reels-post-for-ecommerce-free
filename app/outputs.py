"""Securely persist and describe files downloaded from a Kaggle run."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Iterable

from app.validation import ValidationError

REEL_RE = re.compile(r"(?:^|[_-])reel[_-]?(\d{1,3})(?:[_\-.]|$)", re.IGNORECASE)
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
MANIFEST_NAMES = {"manifest.json", "campaign_manifest.json", "runner_manifest.json"}
THUMBNAIL_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def safe_output_name(value: Any, *, field: str = "output filename") -> str:
    """Accept a portable basename only; never a path supplied by a remote manifest."""
    if not isinstance(value, str):
        raise ValidationError(f"{field.capitalize()} must be text.", field)
    name = value.strip()
    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or not SAFE_NAME_RE.fullmatch(name)
    ):
        raise ValidationError(f"Unsafe {field}.", field)
    return name


def _validated_download_files(download_dir: Path, reported: Iterable[Path]) -> list[Path]:
    root = download_dir.resolve()
    for raw_path in reported:
        path = Path(raw_path)
        candidate = path if path.is_absolute() else download_dir / path
        resolved = candidate.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValidationError("Kaggle output path escapes the download directory.")
        if candidate.is_symlink():
            raise ValidationError("Kaggle output contains a symbolic link.")

    files: list[Path] = []
    if download_dir.exists():
        for path in sorted(download_dir.rglob("*")):
            if path.is_symlink():
                raise ValidationError("Kaggle output contains a symbolic link.")
            if path.is_file():
                resolved = path.resolve()
                if root not in resolved.parents:
                    raise ValidationError("Kaggle output path escapes the download directory.")
                files.append(path)
    return files


def _read_manifests(files: list[Path]) -> tuple[list[tuple[Path, dict[str, Any]]], list[str]]:
    manifests: list[tuple[Path, dict[str, Any]]] = []
    warnings: list[str] = []
    for path in files:
        lower = path.name.lower()
        if lower not in MANIFEST_NAMES and not lower.endswith("_manifest.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            warnings.append(f"Could not parse {path.name}: {type(exc).__name__}.")
            continue
        if not isinstance(payload, dict):
            warnings.append(f"Ignored {path.name}: manifest root is not an object.")
            continue
        manifests.append((path, payload))
    return manifests, warnings


def _unique_by_name(files: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    duplicates: set[str] = set()
    for path in files:
        name = safe_output_name(path.name)
        if name in found and found[name].resolve() != path.resolve():
            duplicates.add(name)
        found[name] = path
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise ValidationError(f"Kaggle output contains duplicate filenames: {names}.")
    return found


def _index_from_name(name: str) -> int | None:
    match = REEL_RE.search(name)
    return int(match.group(1)) - 1 if match and int(match.group(1)) > 0 else None


def _manifest_outputs(manifests: list[tuple[Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    for _path, payload in manifests:
        outputs = payload.get("outputs")
        if isinstance(outputs, list):
            return [dict(item) for item in outputs if isinstance(item, dict)]
    return []


def persist_kaggle_outputs(
    download_dir: Path,
    reported_files: Iterable[Path],
    output_dir: Path,
) -> dict[str, Any]:
    """Copy all useful campaign artifacts and return canonical output metadata."""
    files = _validated_download_files(download_dir, reported_files)
    by_name = _unique_by_name(files)
    manifests, warnings = _read_manifests(files)
    mp4s = [path for path in files if path.suffix.lower() == ".mp4"]
    if not mp4s:
        raise RuntimeError("Kaggle completed but returned no MP4 output.")

    output_dir.mkdir(parents=True, exist_ok=True)
    reels_dir = output_dir / "reels"
    scripts_dir = output_dir / "scripts"
    captions_dir = output_dir / "captions"
    manifests_dir = output_dir / "manifests"
    thumbnails_dir = output_dir / "thumbnails"
    for directory in (reels_dir, scripts_dir, captions_dir, manifests_dir, thumbnails_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for path, _payload in manifests:
        shutil.copy2(path, manifests_dir / safe_output_name(path.name))

    declared = _manifest_outputs(manifests)
    outputs: list[dict[str, Any]] = []
    used_mp4s: set[str] = set()
    for position, item in enumerate(declared):
        raw_index = item.get("reel_index", item.get("index", position))
        if isinstance(raw_index, bool) or not isinstance(raw_index, int) or raw_index < 0:
            raise ValidationError("Manifest reel index is invalid.")
        requested_filename = item.get("filename")
        if requested_filename in (None, ""):
            numbered = f"reel_{raw_index + 1:03d}.mp4"
            requested_filename = numbered if numbered in by_name else "result.mp4"
        filename = safe_output_name(requested_filename, field="reel filename")
        source = by_name.get(filename)
        if source is None or source.suffix.lower() != ".mp4":
            raise ValidationError(f"Manifest reel file is missing: {filename}.")
        destination = reels_dir / filename
        shutil.copy2(source, destination)
        used_mp4s.add(filename)
        normalized = dict(item)
        normalized.update(
            index=raw_index,
            reel_index=raw_index,
            reel_id=f"reel-{raw_index + 1:03d}",
            filename=filename,
        )
        for key, suffix, directory in (
            ("script_filename", ".txt", scripts_dir),
            ("srt_filename", ".srt", captions_dir),
            ("thumbnail_filename", None, thumbnails_dir),
        ):
            value = item.get(key)
            if value in (None, ""):
                normalized[key] = None
                continue
            name = safe_output_name(value, field=key.replace("_", " "))
            source_asset = by_name.get(name)
            valid_suffix = (
                source_asset is not None
                and (
                    source_asset.suffix.lower() == suffix
                    if suffix
                    else source_asset.suffix.lower() in THUMBNAIL_EXTENSIONS
                )
            )
            if not valid_suffix or source_asset is None:
                warnings.append(f"Manifest asset was not downloaded: {name}.")
                normalized[key] = None
                continue
            shutil.copy2(source_asset, directory / name)
            normalized[key] = name
        outputs.append(normalized)

    # Preserve undeclared reel MP4s too. result.mp4 remains the compatibility copy.
    for source in sorted(mp4s):
        name = safe_output_name(source.name)
        if name == "result.mp4" or name in used_mp4s:
            continue
        index = _index_from_name(name)
        if index is None:
            index = max((item["index"] for item in outputs), default=-1) + 1
        shutil.copy2(source, reels_dir / name)
        outputs.append(
            {
                "index": index,
                "reel_index": index,
                "reel_id": f"reel-{index + 1:03d}",
                "filename": name,
                "script_filename": None,
                "srt_filename": None,
                "thumbnail_filename": None,
            }
        )

    # Persist scripts, captions, and thumbnails even when an older manifest did not list them.
    for source in files:
        name = safe_output_name(source.name)
        suffix = source.suffix.lower()
        target: Path | None = None
        if suffix == ".txt" and "script" in name.lower():
            target = scripts_dir / name
        elif suffix == ".srt":
            target = captions_dir / name
        elif suffix in THUMBNAIL_EXTENSIONS and any(
            marker in name.lower() for marker in ("thumb", "thumbnail", "poster")
        ):
            target = thumbnails_dir / name
        if target is not None and not target.exists():
            shutil.copy2(source, target)

    if not outputs:
        source = by_name.get("result.mp4") or sorted(mp4s)[0]
        shutil.copy2(source, reels_dir / "reel_001.mp4")
        outputs.append(
            {
                "index": 0,
                "reel_index": 0,
                "reel_id": "reel-001",
                "filename": "reel_001.mp4",
                "script_filename": None,
                "srt_filename": None,
                "thumbnail_filename": None,
                "legacy": True,
            }
        )

    outputs.sort(key=lambda item: (item["index"], item["filename"]))
    indexes = [item["index"] for item in outputs]
    reel_ids = [item["reel_id"] for item in outputs]
    if len(indexes) != len(set(indexes)) or len(reel_ids) != len(set(reel_ids)):
        raise ValidationError("Manifest contains duplicate reel indexes.")

    preferred = by_name.get("result.mp4")
    if preferred is None:
        preferred = by_name[outputs[0]["filename"]]
    legacy = output_dir / "result.mp4"
    shutil.copy2(preferred, legacy)

    metadata: dict[str, Any] = {
        "schema_version": 1,
        "status": "succeeded",
        "legacy_filename": legacy.name,
        "outputs": outputs,
        "manifests": [path.name for path, _payload in manifests],
        "warnings": warnings,
    }
    for _path, payload in manifests:
        remote_warnings = payload.get("warnings")
        if isinstance(remote_warnings, list):
            metadata["warnings"].extend(remote_warnings)
        for key in ("strategy", "delivery", "voice_over_disclosure", "postproduction"):
            if key in payload:
                metadata[key] = payload[key]
    return metadata


def build_campaign_zip(output_dir: Path, metadata: dict[str, Any], *, job_id: str) -> Path:
    """Build a deterministic, useful archive from already-validated local artifacts."""
    archive = output_dir / "campaign.zip"
    readme = (
        f"Campaign output for job {job_id}\n\n"
        "reels/ contains final MP4s.\n"
        "scripts/ contains UTF-8 narration scripts.\n"
        "captions/ contains UTF-8 SRT captions.\n"
        "manifests/ contains Kaggle runner/campaign metadata.\n"
        "thumbnails/ contains generated preview images when available.\n\n"
        "Videos target Instagram Reels and Facebook Reels. Narration is voice-over; "
        "generated people are not lip-synced. Review every asset before publishing.\n"
    )
    include_dirs = ("reels", "scripts", "captions", "manifests", "thumbnails")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.txt", readme)
        bundle.writestr(
            "output_metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
        )
        for dirname in include_dirs:
            directory = output_dir / dirname
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if path.is_symlink() or not path.is_file():
                    continue
                bundle.write(path, f"{dirname}/{safe_output_name(path.name)}")
    return archive
