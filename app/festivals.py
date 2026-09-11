"""Upcoming festival offers for Bareilly / North India food-delivery reels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from app.localtime import now_local


@dataclass(frozen=True)
class FestivalOffer:
    slug: str
    when: date
    title_en: str
    title_hi: str
    template_id: str
    variables: Mapping[str, str]
    blurb: str


# Panchang-aligned observance dates for planning reels (Sep 2026 – Apr 2027).
_CATALOG: tuple[FestivalOffer, ...] = (
    FestivalOffer(
        "navratri-2026",
        date(2026, 10, 11),
        "Navratri",
        "नवरात्रि",
        "festival_seasonal",
        {"festival_name": "Navratri", "offer_text": "vrat-friendly combos"},
        "Fasting-friendly combos and thalis for nine nights.",
    ),
    FestivalOffer(
        "dussehra-2026",
        date(2026, 10, 20),
        "Dussehra",
        "दशहरा",
        "festival_seasonal",
        {"festival_name": "Dussehra", "offer_text": "family feast offer"},
        "Family feast boxes after the festive week.",
    ),
    FestivalOffer(
        "karva-chauth-2026",
        date(2026, 10, 29),
        "Karva Chauth",
        "करवा चौथ",
        "festival_seasonal",
        {"festival_name": "Karva Chauth", "offer_text": "sargi & dinner bundle"},
        "Sargi sweets and dinner bundles for couples.",
    ),
    FestivalOffer(
        "dhanteras-2026",
        date(2026, 11, 6),
        "Dhanteras",
        "धनतेरस",
        "sweets_festival",
        {"festival_name": "Dhanteras", "offer_text": "mithai box from ₹399"},
        "Mithai and snack hampers for Dhanteras.",
    ),
    FestivalOffer(
        "diwali-2026",
        date(2026, 11, 8),
        "Diwali",
        "दीवाली",
        "sweets_festival",
        {"festival_name": "Diwali", "offer_text": "Diwali party platter"},
        "Diwali party platters and late-night delivery.",
    ),
    FestivalOffer(
        "bhai-dooj-2026",
        date(2026, 11, 10),
        "Bhai Dooj",
        "भाई दूज",
        "sweets_festival",
        {"festival_name": "Bhai Dooj", "offer_text": "brother-sister sweet box"},
        "Sibling sweet boxes and home-style meals.",
    ),
    FestivalOffer(
        "chhath-2026",
        date(2026, 11, 15),
        "Chhath Puja",
        "छठ पूजा",
        "festival_seasonal",
        {"festival_name": "Chhath Puja", "offer_text": "thekua & fruit basket"},
        "Thekua, fruits, and early-morning delivery slots.",
    ),
    FestivalOffer(
        "guru-nanak-2026",
        date(2026, 11, 24),
        "Guru Nanak Jayanti",
        "गुरु नानक जयंती",
        "festival_seasonal",
        {"festival_name": "Guru Nanak Jayanti", "offer_text": "langar-style meal"},
        "Langar-style vegetarian meals and karah prasad orders.",
    ),
    FestivalOffer(
        "makar-sankranti-2027",
        date(2027, 1, 15),
        "Makar Sankranti",
        "मकर संक्रांति",
        "sweets_festival",
        {"festival_name": "Makar Sankranti", "offer_text": "til-gud treats"},
        "Til-gud sweets and kite-day snacks.",
    ),
    FestivalOffer(
        "maha-shivratri-2027",
        date(2027, 3, 6),
        "Maha Shivratri",
        "महा शिवरात्रि",
        "festival_seasonal",
        {"festival_name": "Maha Shivratri", "offer_text": "fasting thali"},
        "Fasting-friendly thalis through the night.",
    ),
    FestivalOffer(
        "holi-2027",
        date(2027, 3, 22),
        "Holi",
        "होली",
        "festival_seasonal",
        {"festival_name": "Holi", "offer_text": "gujiya & thandai combo"},
        "Gujiya, thandai, and Holi party packs.",
    ),
    FestivalOffer(
        "ram-navami-2027",
        date(2027, 4, 15),
        "Ram Navami",
        "राम नवमी",
        "festival_seasonal",
        {"festival_name": "Ram Navami", "offer_text": "prasad & meal"},
        "Prasad boxes and satvik meal delivery.",
    ),
)


def upcoming_festivals(*, today: date | None = None, limit: int = 8) -> list[FestivalOffer]:
    anchor = today or now_local().date()
    rows = [item for item in _CATALOG if item.when >= anchor]
    rows.sort(key=lambda item: item.when)
    return rows[:limit]


def get_festival(slug: str) -> FestivalOffer | None:
    for item in _CATALOG:
        if item.slug == slug:
            return item
    return None


def festival_variables(
    offer: FestivalOffer, profile: Mapping[str, str]
) -> dict[str, str]:
    from app.business_profile import campaign_variables

    merged = campaign_variables(profile)
    merged.update(dict(offer.variables))
    return merged


def format_festival_date(value: date) -> str:
    return datetime(value.year, value.month, value.day).strftime("%d %b %Y")
