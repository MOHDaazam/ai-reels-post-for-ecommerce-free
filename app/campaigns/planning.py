from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

from app.campaigns.models import (
    CATALOG_VERSION,
    LANGUAGES,
    MAX_CAMPAIGN_SIZE,
    MAX_SEED,
    MIN_CAMPAIGN_SIZE,
    STRATEGIES,
    STRATEGY_COST_LABELS,
    CampaignPlan,
    CopyVariant,
    EditableReel,
    ScenarioTemplate,
)
from app.campaigns.templates import get_template
from app.validation import ValidationError

PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def unique_animation_count(strategy: str, campaign_size: int) -> int:
    if strategy == "credit_saver":
        return 1
    if strategy == "unique_visuals":
        return campaign_size
    if strategy == "balanced":
        return 2 if campaign_size <= 4 else 3
    raise ValidationError("Choose credit saver, balanced, or unique visuals.", "strategy")


def animation_indices(count: int, campaign_size: int) -> tuple[int, ...]:
    if count <= 0:
        raise ValidationError("A campaign needs at least one animation.")
    if count >= campaign_size:
        return tuple(range(campaign_size))
    if count == 1:
        return (0,)
    span = campaign_size - 1
    chosen: list[int] = []
    for step in range(count):
        index = round(step * span / (count - 1))
        if index not in chosen:
            chosen.append(index)
    while len(chosen) < count:
        for index in range(campaign_size):
            if index not in chosen:
                chosen.append(index)
                break
    return tuple(sorted(chosen))


def resolve_variables(
    template: ScenarioTemplate, overrides: Mapping[str, str] | None
) -> dict[str, str]:
    allowed = set(template.variable_defaults)
    incoming = dict(overrides or {})
    unknown = sorted(set(incoming) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ValidationError(f"Unknown template variables: {names}.", "variables")
    merged = dict(template.variable_defaults)
    for key, value in incoming.items():
        merged[key] = validate_unicode_text(value, field=f"variables.{key}")
    return merged


def expand_placeholders(text: str, values: Mapping[str, str], *, field: str) -> str:
    needed = set(PLACEHOLDER_RE.findall(text))
    missing = sorted(needed - set(values))
    if missing:
        names = ", ".join(missing)
        raise ValidationError(f"Unknown template variables: {names}.", field)

    def _replace(match: re.Match[str]) -> str:
        return values[match.group(1)]

    expanded = PLACEHOLDER_RE.sub(_replace, text)
    leftover = PLACEHOLDER_RE.findall(expanded)
    if leftover:
        names = ", ".join(sorted(set(leftover)))
        raise ValidationError(f"Unknown template variables: {names}.", field)
    return validate_unicode_text(expanded, field=field)


def validate_unicode_text(text: str, *, field: str) -> str:
    if not isinstance(text, str):
        raise ValidationError("Text must be a Unicode string.", field)
    normalized = unicodedata.normalize("NFC", text)
    for char in normalized:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise ValidationError("Text contains invalid Unicode surrogates.", field)
        category = unicodedata.category(char)
        if char in "\n\t":
            continue
        if category.startswith("C") or char == "\x00":
            raise ValidationError("Text contains disallowed control characters.", field)
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValidationError("Text must be valid UTF-8 Unicode.", field) from exc
    return normalized


def require_devanagari(text: str, *, field: str) -> str:
    cleaned = validate_unicode_text(text, field=field)
    if not DEVANAGARI_RE.search(cleaned):
        raise ValidationError("Hindi copy must include Devanagari text.", field)
    return cleaned


def expand_copy(variant: CopyVariant, values: Mapping[str, str], *, locale: str) -> CopyVariant:
    prefix = f"{locale}."
    captions = tuple(
        expand_placeholders(line, values, field=f"{prefix}captions") for line in variant.captions
    )
    hook = expand_placeholders(variant.hook, values, field=f"{prefix}hook")
    narration = expand_placeholders(variant.narration, values, field=f"{prefix}narration")
    cta = expand_placeholders(variant.cta, values, field=f"{prefix}cta")
    if locale == "hindi":
        hook = require_devanagari(hook, field=f"{prefix}hook")
        narration = require_devanagari(narration, field=f"{prefix}narration")
        cta = require_devanagari(cta, field=f"{prefix}cta")
        captions = tuple(validate_unicode_text(line, field=f"{prefix}captions") for line in captions)
    return CopyVariant(hook=hook, narration=narration, captions=captions, cta=cta)


def derive_base_seed(
    template_id: str, variables: Mapping[str, str], base_seed: int | None
) -> int:
    if base_seed is not None:
        if base_seed < 0 or base_seed > MAX_SEED:
            raise ValidationError("Seed must be between 0 and 2147483647.", "seed")
        return base_seed
    payload = json.dumps(
        {"template_id": template_id, "variables": dict(sorted(variables.items()))},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % (MAX_SEED + 1)


def reel_seed(base_seed: int, template_id: str, index: int) -> int:
    material = f"{base_seed}:{template_id}:{index}".encode()
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:4], "big") % (MAX_SEED + 1)


def assign_reel_language(campaign_language: str, index: int) -> str:
    if campaign_language == "bilingual":
        return "hindi" if index % 2 == 0 else "english"
    return campaign_language


def motion_source_for(index: int, animated: tuple[int, ...]) -> int:
    source = animated[0]
    for candidate in animated:
        if candidate <= index:
            source = candidate
        else:
            break
    return source


def plan_campaign(
    template_id: str,
    *,
    language: str = "bilingual",
    campaign_size: int = MIN_CAMPAIGN_SIZE,
    strategy: str = "credit_saver",
    variables: Mapping[str, str] | None = None,
    base_seed: int | None = None,
) -> CampaignPlan:
    if language not in LANGUAGES:
        raise ValidationError("Choose Hindi, English, or bilingual.", "language")
    if strategy not in STRATEGIES:
        raise ValidationError("Choose credit saver, balanced, or unique visuals.", "strategy")
    if campaign_size < MIN_CAMPAIGN_SIZE or campaign_size > MAX_CAMPAIGN_SIZE:
        raise ValidationError("Campaign size must be between 3 and 5 scenes.", "campaign_size")

    template = get_template(template_id)
    values = resolve_variables(template, variables)
    seed = derive_base_seed(template.id, values, base_seed)
    unique_count = unique_animation_count(strategy, campaign_size)
    animated = animation_indices(unique_count, campaign_size)

    reels: list[EditableReel] = []
    for index in range(campaign_size):
        reel_language = assign_reel_language(language, index)
        english = expand_copy(template.english[index], values, locale="english")
        hindi = expand_copy(template.hindi[index], values, locale="hindi")
        primary = hindi if reel_language == "hindi" else english
        companion = english if reel_language == "hindi" else hindi
        include_companion = language == "bilingual"
        flux = expand_placeholders(
            f"{template.flux_prompt}. {template.flux_variants[index]}",
            values,
            field="flux_prompt",
        )
        motion = expand_placeholders(
            f"{template.ltx_motion_prompt}. {template.ltx_variants[index]}",
            values,
            field="ltx_motion_prompt",
        )
        negative = expand_placeholders(template.negative_prompt, values, field="negative_prompt")
        animate = index in animated
        reels.append(
            EditableReel(
                index=index,
                language=reel_language,
                hook=primary.hook,
                narration=primary.narration,
                captions=list(primary.captions),
                cta=primary.cta,
                companion_language=("english" if reel_language == "hindi" else "hindi")
                if include_companion
                else None,
                companion_hook=companion.hook if include_companion else None,
                companion_narration=companion.narration if include_companion else None,
                companion_captions=list(companion.captions) if include_companion else None,
                companion_cta=companion.cta if include_companion else None,
                flux_prompt=flux,
                ltx_motion_prompt=motion,
                negative_prompt=negative,
                transition_style=template.transition_style,
                music_mood=template.music_mood,
                seed=reel_seed(seed, template.id, index),
                animate=animate,
                motion_source_index=index if animate else motion_source_for(index, animated),
            )
        )

    notes = (
        f"Strategy {strategy}: {unique_count} unique animation(s) of {campaign_size} reels.",
        "Speech is voice-over; visuals may include people without lip-sync.",
    )
    return CampaignPlan(
        catalog_version=CATALOG_VERSION,
        template_id=template.id,
        category=template.category,
        language=language,
        strategy=strategy,
        campaign_size=campaign_size,
        unique_animation_count=unique_count,
        cost_label=STRATEGY_COST_LABELS[strategy],
        variables=MappingProxyType(values),
        base_seed=seed,
        reels=tuple(reels),
        notes=notes,
    )


def expand_template(
    template_id: str,
    *,
    variables: Mapping[str, str] | None = None,
    language: str = "bilingual",
    campaign_size: int = MIN_CAMPAIGN_SIZE,
    strategy: str = "credit_saver",
    base_seed: int | None = None,
) -> CampaignPlan:
    return plan_campaign(
        template_id,
        language=language,
        campaign_size=campaign_size,
        strategy=strategy,
        variables=variables,
        base_seed=base_seed,
    )
