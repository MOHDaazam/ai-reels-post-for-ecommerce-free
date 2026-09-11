from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

CATALOG_VERSION = "1"

LANGUAGES = ("hindi", "english", "bilingual")
STRATEGIES = ("credit_saver", "balanced", "unique_visuals")
TEMPLATE_KINDS = ("category", "preset")

MIN_CAMPAIGN_SIZE = 3
MAX_CAMPAIGN_SIZE = 5
VARIANT_SLOTS = 5
MAX_SEED = 2_147_483_647

CATEGORIES = (
    "new_vendor_onboarded",
    "vendor_spotlight",
    "signature_dish",
    "first_order_offer",
    "fast_delivery",
    "meal_time_cravings",
    "ratings_social_proof",
    "festival_seasonal",
    "free_delivery_value",
    "app_awareness",
)

PRESET_IDS = (
    "pizza_onboarding",
    "biryani_craving",
    "burger_combo",
    "sweets_festival",
    "local_restaurant_discovery",
)

STRATEGY_COST_LABELS = {
    "credit_saver": "Lowest GPU · one reel from three crossfaded shots",
    "balanced": "Medium GPU · one reel from up to six crossfaded shots",
    "unique_visuals": "Highest GPU · one reel from six crossfaded shots",
}

DEFAULT_NEGATIVE_PROMPT = (
    "text overlay, watermark, logo, caption, subtitles, signage text, lettering, "
    "letters, words, shop name board, extra fingers, deformed food, "
    "blurry, low-res, plastic texture, duplicate dishes"
)

BRAND_DEFAULTS: dict[str, str] = {
    "app_name": "Aonla Online",
    "city": "Aonla",
    "area": "Aonla",
    "contact": "",
    "brand_tagline": "Aonla ki favourite food delivery",
    "cta_url": "aonla.online",
    # The end card and thumbnail are rendered from these, so the closing
    # wording changes with the brand instead of being baked into the runner.
    "app_kind": "Food delivery app",
    "platforms": "Android, iOS & Laptop",
}


@dataclass(frozen=True)
class CopyVariant:
    hook: str
    narration: str
    captions: tuple[str, ...]
    cta: str


@dataclass(frozen=True)
class ScenarioTemplate:
    id: str
    category: str
    kind: str
    title_en: str
    title_hi: str
    description: str
    variable_defaults: Mapping[str, str]
    english: tuple[CopyVariant, ...]
    hindi: tuple[CopyVariant, ...]
    flux_prompt: str
    flux_variants: tuple[str, ...]
    ltx_motion_prompt: str
    ltx_variants: tuple[str, ...]
    transition_style: str
    music_mood: str
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "variable_defaults",
            MappingProxyType(dict(self.variable_defaults)),
        )


@dataclass
class EditableReel:
    """Per-reel script the UI can edit before a later submit step."""

    index: int
    language: str
    hook: str
    narration: str
    captions: list[str]
    cta: str
    companion_language: str | None
    companion_hook: str | None
    companion_narration: str | None
    companion_captions: list[str] | None
    companion_cta: str | None
    flux_prompt: str
    ltx_motion_prompt: str
    negative_prompt: str
    transition_style: str
    music_mood: str
    seed: int
    animate: bool
    motion_source_index: int

    def apply_edits(self, **changes: Any) -> EditableReel:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "language": self.language,
            "hook": self.hook,
            "narration": self.narration,
            "captions": list(self.captions),
            "cta": self.cta,
            "companion_language": self.companion_language,
            "companion_hook": self.companion_hook,
            "companion_narration": self.companion_narration,
            "companion_captions": (
                list(self.companion_captions) if self.companion_captions is not None else None
            ),
            "companion_cta": self.companion_cta,
            "flux_prompt": self.flux_prompt,
            "ltx_motion_prompt": self.ltx_motion_prompt,
            "negative_prompt": self.negative_prompt,
            "transition_style": self.transition_style,
            "music_mood": self.music_mood,
            "seed": self.seed,
            "animate": self.animate,
            "motion_source_index": self.motion_source_index,
        }


@dataclass(frozen=True)
class CampaignPlan:
    catalog_version: str
    template_id: str
    category: str
    language: str
    strategy: str
    campaign_size: int
    unique_animation_count: int
    cost_label: str
    variables: Mapping[str, str]
    base_seed: int
    reels: tuple[EditableReel, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def editable_reels(self) -> list[EditableReel]:
        return [replace(reel, captions=list(reel.captions)) for reel in self.reels]

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "template_id": self.template_id,
            "category": self.category,
            "language": self.language,
            "strategy": self.strategy,
            "campaign_size": self.campaign_size,
            "unique_animation_count": self.unique_animation_count,
            "cost_label": self.cost_label,
            "variables": dict(self.variables),
            "base_seed": self.base_seed,
            "reels": [reel.to_dict() for reel in self.reels],
            "notes": list(self.notes),
        }
