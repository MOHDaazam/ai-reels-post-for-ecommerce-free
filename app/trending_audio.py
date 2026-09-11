"""Curated Reels-style background tracks (Hindi-first) for immediate reel mixing."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.validation import ValidationError

_TRACK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_RESOURCES = Path(__file__).resolve().parent / "resources" / "trending_audio"
_MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True)
class TrendingTrack:
    id: str
    title: str
    artist: str
    language: str
    reels_tag: str
    mood: str
    bundled_file: str | None = None
    source_url: str | None = None

    def to_public_dict(self, *, preview_ready: bool) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "language": self.language,
            "reels_tag": self.reels_tag,
            "mood": self.mood,
            "preview_url": f"/api/trending-audio/{self.id}/preview",
            "preview_ready": preview_ready,
        }


_BUILTIN: tuple[TrendingTrack, ...] = (
    TrendingTrack(
        "hindi-food-groove",
        "Street Food Groove",
        "Reels picks",
        "hindi",
        "Food delivery Reels trend",
        "Dhol-lite hunger beat",
        bundled_file="hindi-food-groove.mp3",
    ),
    TrendingTrack(
        "hindi-delivery-hype",
        "30 Min Delivery Hype",
        "Reels picks",
        "hindi",
        "Hyperlocal promo trend",
        "Fast tabla + bass",
        bundled_file="hindi-delivery-hype.mp3",
    ),
    TrendingTrack(
        "hindi-festival-dhol",
        "Festival Dhol Drop",
        "Reels picks",
        "hindi",
        "Navratri / Dussehra trend",
        "Festive dhol energy",
        bundled_file="hindi-festival-dhol.mp3",
    ),
    TrendingTrack(
        "hindi-karva-romance",
        "Karva Soft Romance",
        "Reels picks",
        "hindi",
        "Couple / sargi reel trend",
        "Warm romantic bed",
        bundled_file="hindi-karva-romance.mp3",
    ),
    TrendingTrack(
        "hindi-diwali-beat",
        "Diwali Night Beat",
        "Reels picks",
        "hindi",
        "Diwali offer trend",
        "Bright festival pulse",
        bundled_file="hindi-diwali-beat.mp3",
    ),
    TrendingTrack(
        "hindi-chai-lofi",
        "Chai & Rain Lofi",
        "Reels picks",
        "hindi",
        "Cafe / monsoon reel trend",
        "Cozy lofi tabla",
        bundled_file="hindi-chai-lofi.mp3",
    ),
    TrendingTrack(
        "english-reel-pop",
        "Reel Pop Spark",
        "Reels picks",
        "english",
        "Global Reels pop trend",
        "Upbeat promo pop",
        bundled_file="english-reel-pop.mp3",
    ),
    TrendingTrack(
        "english-cafe-vibe",
        "Cafe Story Vibe",
        "Reels picks",
        "english",
        "Cafe discovery trend",
        "Soft indie bed",
        bundled_file="english-cafe-vibe.mp3",
    ),
)


def _user_catalog_path() -> Path:
    return settings.data_dir / "trending_audio" / "catalog.user.json"


def _cache_dir() -> Path:
    return settings.data_dir / "trending_audio" / "cache"


def _load_user_catalog() -> tuple[TrendingTrack, ...]:
    path = _user_catalog_path()
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError("Custom trending audio catalog is not valid JSON.") from exc
    if not isinstance(payload, list):
        raise ValidationError("Custom trending audio catalog must be a JSON array.")
    tracks: list[TrendingTrack] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        track_id = str(entry.get("id") or "").strip()
        if not _TRACK_ID.match(track_id):
            continue
        tracks.append(
            TrendingTrack(
                id=track_id,
                title=str(entry.get("title") or track_id),
                artist=str(entry.get("artist") or "Custom"),
                language=str(entry.get("language") or "hindi"),
                reels_tag=str(entry.get("reels_tag") or "Custom Reels trend"),
                mood=str(entry.get("mood") or ""),
                bundled_file=None,
                source_url=str(entry.get("source_url") or "").strip() or None,
            )
        )
    return tuple(tracks)


def catalog() -> dict[str, TrendingTrack]:
    merged: dict[str, TrendingTrack] = {track.id: track for track in _BUILTIN}
    for track in _load_user_catalog():
        merged[track.id] = track
    return merged


def get_track(track_id: str) -> TrendingTrack | None:
    tid = (track_id or "").strip()
    if not tid:
        return None
    return catalog().get(tid)


def list_tracks(*, language: str | None = None) -> list[TrendingTrack]:
    lang = (language or "").strip().lower()
    tracks = list(catalog().values())
    if lang in {"hindi", "english"}:
        hindi = [t for t in tracks if t.language == "hindi"]
        other = [t for t in tracks if t.language != "hindi"]
        tracks = hindi + other if lang == "hindi" else other + hindi
    else:
        tracks.sort(key=lambda t: (0 if t.language == "hindi" else 1, t.title.lower()))
    return tracks


def track_label(track_id: str | None) -> str | None:
    if not track_id:
        return None
    track = get_track(track_id)
    return f"{track.title} · {track.reels_tag}" if track else track_id


def _bundled_path(filename: str) -> Path:
    path = (_RESOURCES / filename).resolve()
    if _RESOURCES.resolve() not in path.parents:
        raise ValidationError("Bundled trending audio path is invalid.")
    if not path.is_file():
        raise ValidationError("Bundled trending audio file is missing.", "trending_audio_id")
    return path


def _cache_path(track_id: str) -> Path:
    if not _TRACK_ID.match(track_id):
        raise ValidationError("Unknown trending audio track.", "trending_audio_id")
    return _cache_dir() / f"{track_id}.mp3"


def _download_source(url: str, dest: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError("Trending audio source URL must be HTTPS.", "trending_audio_id")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        size = 0
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes(64 * 1024):
                size += len(chunk)
                if size > _MAX_DOWNLOAD_BYTES:
                    dest.unlink(missing_ok=True)
                    raise ValidationError(
                        "Trending audio download exceeds the size limit.", "trending_audio_id"
                    )
                handle.write(chunk)


def ensure_track_file(track_id: str) -> Path:
    track = get_track(track_id)
    if track is None:
        raise ValidationError("Unknown trending audio track.", "trending_audio_id")
    cached = _cache_path(track_id)
    if cached.is_file():
        return cached
    _cache_dir().mkdir(parents=True, exist_ok=True)
    if track.bundled_file:
        shutil.copyfile(_bundled_path(track.bundled_file), cached)
        return cached
    if track.source_url:
        _download_source(track.source_url, cached)
        return cached
    raise ValidationError("Trending audio track has no audio source.", "trending_audio_id")


def preview_ready(track_id: str) -> bool:
    track = get_track(track_id)
    if track is None:
        return False
    if _cache_path(track_id).is_file():
        return True
    if track.bundled_file:
        return (_RESOURCES / track.bundled_file).is_file()
    return bool(track.source_url)


def resolve_trending_audio_id(form_value: str | None, profile: Mapping[str, str]) -> str | None:
    tid = (form_value or "").strip() or (profile.get("trending_audio_id") or "").strip()
    if not tid:
        return None
    if get_track(tid) is None:
        raise ValidationError("Pick a trending audio track from the list.", "trending_audio_id")
    return tid
