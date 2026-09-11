from __future__ import annotations

import pytest

from app.campaigns import (
    CATEGORIES,
    PRESET_IDS,
    expand_template,
    get_template,
    list_categories,
    list_presets,
    list_templates,
    plan_campaign,
)
from app.campaigns.planning import (
    expand_placeholders,
    require_devanagari,
    validate_unicode_text,
)
from app.validation import ValidationError


def test_catalog_covers_categories_and_presets() -> None:
    categories = list_categories()
    presets = list_presets()
    assert [item.id for item in categories] == list(CATEGORIES)
    assert [item.id for item in presets] == list(PRESET_IDS)
    assert {item.kind for item in categories} == {"category"}
    assert {item.kind for item in presets} == {"preset"}
    assert len(list_templates()) == 15
    for template in list_templates():
        assert template.category in CATEGORIES
        assert len(template.english) == len(template.hindi) == 5
        assert template.flux_prompt
        assert template.ltx_motion_prompt
        assert template.transition_style
        assert template.music_mood
        assert "app_name" in template.variable_defaults
        assert "vendor_name" in template.variable_defaults
        assert any("\u0900" <= char <= "\u097f" for char in template.hindi[0].hook)
        plan = plan_campaign(template.id, campaign_size=3, base_seed=0)
        for reel in plan.reels:
            assert "{" not in reel.flux_prompt
            assert "{" not in reel.hook
            assert "{" not in reel.narration


def test_unknown_template_and_variables_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown campaign template"):
        get_template("mystery_reel")
    with pytest.raises(ValidationError, match="Unknown template variables"):
        plan_campaign("pizza_onboarding", variables={"secret_coupon": "x"})
    with pytest.raises(ValidationError, match="Unknown template variables"):
        expand_placeholders("Order {ghost_var} now", {"vendor_name": "X"}, field="hook")


def test_unicode_validation_rejects_controls_and_surrogates() -> None:
    assert validate_unicode_text("आंवला Online", field="hook") == "आंवला Online"
    with pytest.raises(ValidationError, match="control"):
        validate_unicode_text("bad\x00text", field="hook")
    with pytest.raises(ValidationError, match="surrogate"):
        validate_unicode_text("\ud800", field="hook")
    with pytest.raises(ValidationError, match="Devanagari"):
        require_devanagari("Aonla Online only", field="hook")


def test_plan_expands_defaults_and_overrides() -> None:
    plan = expand_template(
        "pizza_onboarding",
        language="english",
        campaign_size=3,
        variables={"vendor_name": "Azam Pizza Co"},
        base_seed=42,
    )
    assert plan.category == "new_vendor_onboarded"
    assert plan.variables["app_name"] == "Aonla Online"
    assert "Azam Pizza Co" in plan.reels[0].narration
    assert "{" not in plan.reels[0].flux_prompt
    assert "}" not in plan.reels[0].flux_prompt
    assert "{" not in plan.reels[0].ltx_motion_prompt
    assert all(reel.language == "english" for reel in plan.reels)
    assert all(reel.companion_language is None for reel in plan.reels)


def test_bilingual_campaign_alternates_and_keeps_companion_copy() -> None:
    plan = plan_campaign("biryani_craving", language="bilingual", campaign_size=4, base_seed=7)
    assert [reel.language for reel in plan.reels] == ["hindi", "english", "hindi", "english"]
    hindi = plan.reels[0]
    assert hindi.companion_language == "english"
    assert any("\u0900" <= char <= "\u097f" for char in hindi.hook)
    assert hindi.companion_hook and "biryani" in hindi.companion_hook.lower()


def test_render_strategies_bound_unique_animations() -> None:
    saver = plan_campaign(
        "burger_combo", strategy="credit_saver", campaign_size=5, base_seed=1
    )
    balanced_small = plan_campaign(
        "burger_combo", strategy="balanced", campaign_size=3, base_seed=1
    )
    balanced_large = plan_campaign(
        "burger_combo", strategy="balanced", campaign_size=5, base_seed=1
    )
    unique = plan_campaign(
        "burger_combo", strategy="unique_visuals", campaign_size=4, base_seed=1
    )
    assert saver.unique_animation_count == 1
    assert sum(reel.animate for reel in saver.reels) == 1
    assert all(reel.motion_source_index == 0 for reel in saver.reels)
    assert balanced_small.unique_animation_count == 2
    assert balanced_large.unique_animation_count == 3
    assert unique.unique_animation_count == 4
    assert all(reel.animate and reel.motion_source_index == reel.index for reel in unique.reels)


def test_seeds_are_deterministic_and_per_reel() -> None:
    first = plan_campaign("sweets_festival", campaign_size=5, base_seed=99)
    second = plan_campaign("sweets_festival", campaign_size=5, base_seed=99)
    seeds = [reel.seed for reel in first.reels]
    assert seeds == [reel.seed for reel in second.reels]
    assert len(set(seeds)) == 5
    third = plan_campaign("local_restaurant_discovery", campaign_size=5, base_seed=99)
    assert [reel.seed for reel in third.reels] != seeds


def test_editable_reel_replace_and_payload() -> None:
    plan = plan_campaign("local_restaurant_discovery", campaign_size=3, base_seed=3)
    original_hook = plan.reels[0].hook
    edited = plan.reels[0].apply_edits(hook="क़िला ढाबा आज आज़माओ")
    assert edited.hook == "क़िला ढाबा आज आज़माओ"
    assert plan.reels[0].hook == original_hook
    payload = plan.to_dict()
    assert payload["campaign_size"] == 3
    assert payload["reels"][0]["seed"] == plan.reels[0].seed
    copies = plan.editable_reels()
    copies[0].captions.append("extra")
    assert "extra" not in plan.reels[0].captions


def test_campaign_size_and_strategy_bounds() -> None:
    with pytest.raises(ValidationError, match="between 3 and 5"):
        plan_campaign("app_awareness", campaign_size=2)
    with pytest.raises(ValidationError, match="Hindi"):
        plan_campaign("app_awareness", language="hinglish")
    with pytest.raises(ValidationError, match="credit saver"):
        plan_campaign("app_awareness", strategy="max_spend")
