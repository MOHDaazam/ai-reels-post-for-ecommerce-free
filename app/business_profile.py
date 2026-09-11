"""Saved business details reused by quick queue and festival campaigns."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.campaigns.models import BRAND_DEFAULTS
from app.campaigns.planning import validate_unicode_text
from app.config import settings
from app.validation import ValidationError

PROFILE_KEYS = (
    "vendor_name",
    "dish_name",
    "offer_text",
    "city",
    "area",
    "contact",
    "app_name",
    "brand_tagline",
    "cta_url",
    "app_kind",
    "platforms",
    "business_line",
    "trending_audio_id",
)

QUICK_TEMPLATE_BY_LINE: dict[str, str] = {
    "food_delivery": "pizza_onboarding",
    "restaurant": "local_restaurant_discovery",
    "sweets": "sweets_festival",
    "services": "app_awareness",
}

BUSINESS_LINE_LABELS: dict[str, str] = {
    "food_delivery": "Food delivery",
    "restaurant": "Restaurant / cafe",
    "sweets": "Sweets & mithai",
    "services": "Shop / services",
}


def profile_path() -> Path:
    return settings.data_dir / "business_profile.json"


def default_profile() -> dict[str, str]:
    base = dict(BRAND_DEFAULTS)
    base.update(
        {
            "vendor_name": base["app_name"],
            "dish_name": "special thali",
            "offer_text": "free delivery on first order",
            "city": "Bareilly",
            "area": "Civil Lines",
            "business_line": "food_delivery",
            "trending_audio_id": "hindi-food-groove",
        }
    )
    return base


def load_profile_safe() -> dict[str, str]:
    try:
        return load_profile()
    except ValidationError:
        return default_profile()


def load_profile() -> dict[str, str]:
    merged = default_profile()
    path = profile_path()
    if not path.is_file():
        return merged
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError("Saved business profile is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Saved business profile must be an object.")
    for key in PROFILE_KEYS:
        value = payload.get(key)
        if value in (None, ""):
            continue
        merged[key] = validate_unicode_text(str(value), field=key)
    return merged


def save_profile(values: Mapping[str, Any]) -> dict[str, str]:
    merged = load_profile()
    for key in PROFILE_KEYS:
        if key not in values:
            continue
        text = str(values.get(key) or "").strip()
        if key == "trending_audio_id":
            merged[key] = validate_unicode_text(text, field=key) if text else ""
            continue
        if not text:
            continue
        merged[key] = validate_unicode_text(text, field=key)
    if merged.get("business_line") not in QUICK_TEMPLATE_BY_LINE:
        merged["business_line"] = "food_delivery"
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                key: merged[key]
                for key in PROFILE_KEYS
                if merged.get(key) or key == "trending_audio_id"
            },
                   ensure_ascii=False,
                   indent=2),
        encoding="utf-8",
    )
    return merged


def campaign_variables(profile: Mapping[str, str]) -> dict[str, str]:
    """Map the saved profile into campaign template placeholders."""
    return {
        "vendor_name": profile.get("vendor_name") or profile.get("app_name") or "Local brand",
        "dish_name": profile.get("dish_name") or "today's special",
        "offer_text": profile.get("offer_text") or "order now",
        "city": profile.get("city") or "Bareilly",
        "area": profile.get("area") or profile.get("city") or "Bareilly",
        "contact": profile.get("contact") or "",
        "app_name": profile.get("app_name") or BRAND_DEFAULTS["app_name"],
        "brand_tagline": profile.get("brand_tagline") or BRAND_DEFAULTS["brand_tagline"],
        "cta_url": profile.get("cta_url") or BRAND_DEFAULTS["cta_url"],
        "app_kind": profile.get("app_kind") or BRAND_DEFAULTS["app_kind"],
        "platforms": profile.get("platforms") or BRAND_DEFAULTS["platforms"],
    }


def quick_template_id(profile: Mapping[str, str]) -> str:
    line = profile.get("business_line") or "food_delivery"
    return QUICK_TEMPLATE_BY_LINE.get(line, "pizza_onboarding")
