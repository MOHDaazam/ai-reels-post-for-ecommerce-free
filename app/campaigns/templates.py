from __future__ import annotations

from app.campaigns.models import (
    BRAND_DEFAULTS,
    CATEGORIES,
    PRESET_IDS,
    VARIANT_SLOTS,
    CopyVariant,
    ScenarioTemplate,
)

_FOOD_FLUX = (
    "photorealistic vertical 9:16 food commercial still, appetizing North Indian small-city "
    "evening light, steam and texture, shallow depth of field, no text, no watermark, no logo"
)


def _copy(hook: str, narration: str, captions: tuple[str, ...], cta: str) -> CopyVariant:
    return CopyVariant(hook=hook, narration=narration, captions=captions, cta=cta)


def _still(detail: str) -> str:
    return f"{_FOOD_FLUX}, {detail}"


def _vars(**overrides: str) -> dict[str, str]:
    merged = dict(BRAND_DEFAULTS)
    merged.update(
        {
            "vendor_name": "Local Kitchen",
            "dish_name": "today's special",
            "offer_text": "20% off first order",
            "rating": "4.8",
            "eta_minutes": "25",
            "festival_name": "festive weekend",
        }
    )
    merged.update(overrides)
    return merged


def _template(
    *,
    id: str,
    category: str,
    kind: str,
    title_en: str,
    title_hi: str,
    description: str,
    variable_defaults: dict[str, str],
    english: tuple[CopyVariant, ...],
    hindi: tuple[CopyVariant, ...],
    flux_prompt: str,
    flux_variants: tuple[str, ...],
    ltx_motion_prompt: str,
    ltx_variants: tuple[str, ...],
    transition_style: str,
    music_mood: str,
) -> ScenarioTemplate:
    if len(english) != VARIANT_SLOTS or len(hindi) != VARIANT_SLOTS:
        raise ValueError(f"{id} must define {VARIANT_SLOTS} English and Hindi variants")
    if len(flux_variants) != VARIANT_SLOTS or len(ltx_variants) != VARIANT_SLOTS:
        raise ValueError(f"{id} must define {VARIANT_SLOTS} visual and motion variants")
    return ScenarioTemplate(
        id=id,
        category=category,
        kind=kind,
        title_en=title_en,
        title_hi=title_hi,
        description=description,
        variable_defaults=variable_defaults,
        english=english,
        hindi=hindi,
        flux_prompt=flux_prompt,
        flux_variants=flux_variants,
        ltx_motion_prompt=ltx_motion_prompt,
        ltx_variants=ltx_variants,
        transition_style=transition_style,
        music_mood=music_mood,
    )


NEW_VENDOR = _template(
    id="new_vendor_onboarded",
    category="new_vendor_onboarded",
    kind="category",
    title_en="New vendor onboarded",
    title_hi="नया वेंडर जुड़ा",
    description="Welcome a newly listed kitchen to Aonla Online with first-order energy.",
    variable_defaults=_vars(),
    english=(
        _copy(
            "New in {city}: {vendor_name} just went live.",
            "{vendor_name} is now on {app_name}. Fresh menus, local flavour, {offer_text}. "
            "Open the app and welcome them with your first order.",
            ("NEW ON {app_name}", "{vendor_name}", "{offer_text}"),
            "Order now on {app_name}",
        ),
        _copy(
            "{city} just got tastier. {vendor_name} has arrived.",
            "Tap {app_name}, find {vendor_name}, and try {dish_name} while the welcome offer lasts.",
            ("JUST LANDED", "{dish_name}", "Welcome offer live"),
            "First order · {cta_url}",
        ),
        _copy(
            "Meet {city}'s newest kitchen on {app_name}.",
            "{vendor_name} joined tonight. {eta_minutes} minutes to your door. {brand_tagline}.",
            ("NEW KITCHEN", "{eta_minutes} min delivery", "{vendor_name}"),
            "Welcome them · order on {app_name}",
        ),
        _copy(
            "They just switched on. You should too.",
            "Be among the first to rate {vendor_name}. Start with {dish_name} and {offer_text}.",
            ("BE FIRST", "Rate {vendor_name}", "{offer_text}"),
            "Order · rate · repeat",
        ),
        _copy(
            "A new favourite in {city} starts today.",
            "{app_name} added {vendor_name}. Same streets, hotter food, faster tap-to-door.",
            ("{city} UPDATE", "{vendor_name} is live", "Tap to order"),
            "Open {app_name} now",
        ),
    ),
    hindi=(
        _copy(
            "{city} में नया: {vendor_name} अब लाइव है।",
            "{vendor_name} अब {app_name} पर है। ताज़ा मेन्यू, अपना स्वाद, {offer_text}। "
            "ऐप खोलो और पहले ऑर्डर से स्वागत करो।",
            ("नया वेंडर", "{vendor_name}", "{offer_text}"),
            "अभी ऑर्डर करें · {app_name}",
        ),
        _copy(
            "{city} और स्वादिष्ट हो गया। {vendor_name} आ गया।",
            "{app_name} खोलो, {vendor_name} ढूँढो, और {dish_name} वेलकम ऑफ़र में आज़माओ।",
            ("अभी जुड़ा", "{dish_name}", "वेलकम ऑफ़र"),
            "पहला ऑर्डर · {cta_url}",
        ),
        _copy(
            "{app_name} पर {city} की नई किचन।",
            "{vendor_name} आज शामिल हुआ। दरवाज़े तक {eta_minutes} मिनट। {brand_tagline}।",
            ("नई किचन", "{eta_minutes} मिनट", "{vendor_name}"),
            "स्वागत ऑर्डर · {app_name}",
        ),
        _copy(
            "उन्होंने अभी चालू किया। आप भी करो।",
            "{vendor_name} को सबसे पहले रेट करो। {dish_name} से शुरू करो, {offer_text} के साथ।",
            ("पहले बनो", "{vendor_name} रेट करो", "{offer_text}"),
            "ऑर्डर करो · रेट करो",
        ),
        _copy(
            "{city} का नया पसंदीदा आज से शुरू।",
            "{app_name} ने {vendor_name} जोड़ा। वही गलियाँ, गरम खाना, तेज़ डिलीवरी।",
            ("{city} अपडेट", "{vendor_name} लाइव", "ऐप से ऑर्डर"),
            "{app_name} अभी खोलो",
        ),
    ),
    flux_prompt=_still(
        "newly opened neighbourhood restaurant storefront at dusk in {city}, "
        "chef plating {dish_name} in the window, warm fairy lights, inviting doorway"
    ),
    flux_variants=(
        "wide dusk storefront with a small opening-day marigold rangoli",
        "close-up of the first plated {dish_name} leaving the pass",
        "delivery bag handed over under a yellow porch lamp",
        "chef smiling beside a handwritten new-on-app chalkboard, face not talking",
        "overhead table spread of the new menu heroes with steam",
    ),
    ltx_motion_prompt=(
        "gentle push-in toward the glowing shopfront, steam drifting, fairy lights twinkling, "
        "appetizing commercial motion, no abrupt cuts"
    ),
    ltx_variants=(
        "slow push-in through the doorway toward plated food",
        "steam rising, camera eases over the dish",
        "rider accepts a warm packet, slight handheld sway",
        "lights shimmer, slow tilt up the storefront sign",
        "orbit around the table spread, steam catching the light",
    ),
    transition_style="warm iris wipe into app CTA",
    music_mood="hopeful acoustic with light dhol accents",
)

VENDOR_SPOTLIGHT = _template(
    id="vendor_spotlight",
    category="vendor_spotlight",
    kind="category",
    title_en="Vendor spotlight",
    title_hi="वेंडर स्पॉटलाइट",
    description="Put a trusted local restaurant in the hero slot.",
    variable_defaults=_vars(vendor_name="Ghar Ka Swad", dish_name="thandai thali"),
    english=(
        _copy(
            "{vendor_name} is {city}'s weeknight hero.",
            "From the tawa to your gate: {vendor_name} on {app_name}. {rating} stars. "
            "Tonight, start with {dish_name}.",
            ("SPOTLIGHT", "{vendor_name}", "{rating}★ in {city}"),
            "Order {vendor_name} on {app_name}",
        ),
        _copy(
            "Local love. {vendor_name} on {app_name}.",
            "Neighbours already know. Now the app does too. {eta_minutes} minutes, {dish_name} hot.",
            ("LOCAL LOVE", "{dish_name}", "{eta_minutes} min"),
            "Tap {app_name} · {cta_url}",
        ),
        _copy(
            "Why {city} keeps coming back to {vendor_name}.",
            "Consistent spice, honest portions, {brand_tagline}. See {dish_name} tonight.",
            ("WHY THEM", "Honest portions", "{dish_name}"),
            "Reorder in {app_name}",
        ),
        _copy(
            "A kitchen {city} already trusts.",
            "{vendor_name} plated {dish_name} the same way for years. Now it rides with {app_name}.",
            ("TRUSTED", "{vendor_name}", "Now on the app"),
            "Find them on {app_name}",
        ),
        _copy(
            "Tonight's table is {vendor_name}.",
            "Skip the queue. Spotlight kitchen, {offer_text}, doorstep in {eta_minutes}.",
            ("TONIGHT", "{vendor_name}", "{offer_text}"),
            "Order the spotlight",
        ),
    ),
    hindi=(
        _copy(
            "{vendor_name} है {city} का वीकनाइट हीरो।",
            "तवे से गेट तक: {vendor_name} अब {app_name} पर। {rating} स्टार। आज {dish_name} से शुरू करो।",
            ("स्पॉटलाइट", "{vendor_name}", "{city} में {rating}★"),
            "{app_name} पर ऑर्डर करें",
        ),
        _copy(
            "अपना प्यार। {vendor_name} {app_name} पर।",
            "पड़ोसी पहले से जानते हैं। अब ऐप भी। {eta_minutes} मिनट, गरम {dish_name}।",
            ("लोकल लव", "{dish_name}", "{eta_minutes} मिनट"),
            "{app_name} खोलो · {cta_url}",
        ),
        _copy(
            "{city} {vendor_name} पर बार-बार क्यों आता है।",
            "सही मसाला, ईमानदार हिस्सा, {brand_tagline}। आज रात {dish_name} देखो।",
            ("इसीलिए", "ईमानदार हिस्सा", "{dish_name}"),
            "{app_name} से रीऑर्डर",
        ),
        _copy(
            "एक किचन जिस पर {city} यकीन करता है।",
            "{vendor_name} सालों से {dish_name} ऐसे ही सजाता है। अब सवार है {app_name}।",
            ("भरोसा", "{vendor_name}", "अब ऐप पर"),
            "{app_name} पर ढूँढो",
        ),
        _copy(
            "आज रात की मेज़: {vendor_name}।",
            "कतार छोड़ो। स्पॉटलाइट किचन, {offer_text}, {eta_minutes} में दरवाज़ा।",
            ("आज रात", "{vendor_name}", "{offer_text}"),
            "स्पॉटलाइट ऑर्डर करो",
        ),
    ),
    flux_prompt=_still(
        "signature restaurant interior of {vendor_name} in {city}, "
        "hero plate of {dish_name}, brass and wood, inviting family table"
    ),
    flux_variants=(
        "chef's hands finishing {dish_name} with a garnish",
        "packed dining room bokeh behind a sharp hero plate",
        "thali layout photographed from above",
        "storefront at blue hour with warm interior spill",
        "close-up texture of gravy catching the light",
    ),
    ltx_motion_prompt="slow orbit around the hero plate, garnish settle, steam drift, cinematic food ad",
    ltx_variants=(
        "orbit the plate, spoon gliding through gravy",
        "rack focus from bokeh lamps to the dish",
        "gentle Ken Burns over the thali",
        "tilt from signboard down to a waiting packet",
        "macro steam with a tiny push-in",
    ),
    transition_style="match-cut steam to branded end card",
    music_mood="warm sitar-lofi with soft tabla",
)

SIGNATURE_DISH = _template(
    id="signature_dish",
    category="signature_dish",
    kind="category",
    title_en="Signature dish",
    title_hi="सिग्नेचर डिश",
    description="Launch or celebrate one hero dish.",
    variable_defaults=_vars(dish_name="butter chicken", vendor_name="Spice House"),
    english=(
        _copy(
            "This is the {dish_name} {city} talks about.",
            "{vendor_name}'s signature {dish_name} is on {app_name}. One plate. Full story. {offer_text}.",
            ("SIGNATURE", "{dish_name}", "{vendor_name}"),
            "Order the signature",
        ),
        _copy(
            "Not a side. The reason you open {app_name}.",
            "Crave {dish_name}? {vendor_name} made it famous. {eta_minutes} minutes, still steaming.",
            ("THE REASON", "{dish_name}", "{eta_minutes} min hot"),
            "Tap for {dish_name}",
        ),
        _copy(
            "{dish_name}, exactly how {city} likes it.",
            "Spice that remembers home. {brand_tagline}. Order {dish_name} from {vendor_name}.",
            ("EXACTLY THIS", "{city} style", "{dish_name}"),
            "Get it on {app_name}",
        ),
        _copy(
            "One dish. Instant mood change.",
            "Skip the debate. {dish_name} from {vendor_name}, {rating} stars, {offer_text}.",
            ("MOOD: HUNGRY", "{rating}★ {dish_name}", "{offer_text}"),
            "Add to cart · {cta_url}",
        ),
        _copy(
            "If you only order once tonight, make it {dish_name}.",
            "Hero plate from {vendor_name}. Caption-worthy, doorstep-ready, on {app_name}.",
            ("ORDER ONCE", "Make it {dish_name}", "{vendor_name}"),
            "Order now on {app_name}",
        ),
    ),
    hindi=(
        _copy(
            "यही है वो {dish_name} जिसकी {city} बात करता है।",
            "{vendor_name} की सिग्नेचर {dish_name} अब {app_name} पर। एक प्लेट, पूरी कहानी। {offer_text}।",
            ("सिग्नेचर", "{dish_name}", "{vendor_name}"),
            "सिग्नेचर ऑर्डर करो",
        ),
        _copy(
            "साइड डिश नहीं। {app_name} खोलने की वजह।",
            "{dish_name} चाहिए? {vendor_name} ने मशहूर किया। {eta_minutes} मिनट, भाप अभी बाकी।",
            ("वजह यही", "{dish_name}", "{eta_minutes} मिनट गरम"),
            "{dish_name} टैप करो",
        ),
        _copy(
            "{dish_name}, बिल्कुल जैसे {city} पसंद करे।",
            "घर जैसा मसाला। {brand_tagline}। {vendor_name} से {dish_name} मँगवाओ।",
            ("बिल्कुल ये", "{city} स्टाइल", "{dish_name}"),
            "{app_name} पर लो",
        ),
        _copy(
            "एक डिश। मूड तुरंत बदल जाए।",
            "बहस छोड़ो। {vendor_name} की {dish_name}, {rating} स्टार, {offer_text}।",
            ("मूड: भूख", "{rating}★ {dish_name}", "{offer_text}"),
            "कार्ट में डालो · {cta_url}",
        ),
        _copy(
            "आज रात एक ही ऑर्डर हो तो वो {dish_name} हो।",
            "{vendor_name} की हीरो प्लेट। कैप्शन-योग्य, दरवाज़े तक, {app_name} पर।",
            ("एक ऑर्डर", "{dish_name} लो", "{vendor_name}"),
            "{app_name} पर अभी ऑर्डर",
        ),
    ),
    flux_prompt=_still(
        "hero close-up of {dish_name} from {vendor_name}, "
        "glistening gravy, naan tear, copper bowl, dramatic key light"
    ),
    flux_variants=(
        "cheese or gravy pull frozen mid-stretch",
        "overhead hero bowl with scattered spices",
        "hand tearing bread toward the plate, no talking",
        "steam halo around a dark-background dish",
        "side angle showing texture and garnish height",
    ),
    ltx_motion_prompt="slow push into the signature dish, steam rising, sauce glistening, food-porn motion",
    ltx_variants=(
        "push-in with a slow gravy swirl",
        "subtle rotation around the bowl",
        "bread tear in slow motion",
        "steam catch-light drifting up",
        "tilt from garnish down into the sauce",
    ),
    transition_style="zoom punch into CTA",
    music_mood="hungry bass with sizzling foley",
)

FIRST_ORDER = _template(
    id="first_order_offer",
    category="first_order_offer",
    kind="category",
    title_en="First-order / limited offer",
    title_hi="पहला ऑर्डर / लिमिटेड ऑफ़र",
    description="Urgency for a first order or a short-lived combo.",
    variable_defaults=_vars(offer_text="₹99 combo today only"),
    english=(
        _copy(
            "{offer_text}. Then it's gone.",
            "First order on {app_name} from {vendor_name}. {dish_name} plus the clock. Don't overthink it.",
            ("LIMITED", "{offer_text}", "Today on {app_name}"),
            "Claim {offer_text}",
        ),
        _copy(
            "New to {app_name}? Start cheaper.",
            "{offer_text} on {dish_name} from {vendor_name}. First-order window, {city} only vibe.",
            ("FIRST ORDER", "{dish_name}", "{offer_text}"),
            "Unlock on {cta_url}",
        ),
        _copy(
            "The combo {city} will screenshot.",
            "{vendor_name} stacked {dish_name} under {offer_text}. Tap before the tile disappears.",
            ("SCREENSHOT THIS", "{offer_text}", "{vendor_name}"),
            "Grab the combo",
        ),
        _copy(
            "Timer's on. Hunger should be too.",
            "Limited tile: {dish_name}, {offer_text}, {eta_minutes} minutes. {brand_tagline}.",
            ("TIMER ON", "{eta_minutes} min", "{offer_text}"),
            "Order before it ends",
        ),
        _copy(
            "One tap. First-order luck.",
            "If you have never ordered {vendor_name} on {app_name}, this is the cheap hello: {offer_text}.",
            ("HELLO DEAL", "{vendor_name}", "{offer_text}"),
            "First order now",
        ),
    ),
    hindi=(
        _copy(
            "{offer_text}। फिर खत्म।",
            "{app_name} पर {vendor_name} का पहला ऑर्डर। {dish_name} और घड़ी। ज़्यादा मत सोचो।",
            ("लिमिटेड", "{offer_text}", "आज {app_name} पर"),
            "{offer_text} क्लेम करो",
        ),
        _copy(
            "{app_name} पर नए हो? सस्ते शुरू करो।",
            "{vendor_name} की {dish_name} पर {offer_text}। पहला ऑर्डर विंडो, {city} वाला मूड।",
            ("पहला ऑर्डर", "{dish_name}", "{offer_text}"),
            "{cta_url} पर अनलॉक",
        ),
        _copy(
            "वो कॉम्बो जिसका {city} स्क्रीनशॉट लेगा।",
            "{vendor_name} ने {dish_name} को {offer_text} में बाँधा। टाइल गायब होने से पहले टैप करो।",
            ("ये सेव करो", "{offer_text}", "{vendor_name}"),
            "कॉम्बो पकड़ो",
        ),
        _copy(
            "टाइमर चालू है। भूख भी होनी चाहिए।",
            "लिमिटेड टाइल: {dish_name}, {offer_text}, {eta_minutes} मिनट। {brand_tagline}।",
            ("टाइमर ऑन", "{eta_minutes} मिनट", "{offer_text}"),
            "खत्म होने से पहले ऑर्डर",
        ),
        _copy(
            "एक टैप। पहले ऑर्डर की किस्मत।",
            "{app_name} पर {vendor_name} कभी न मँगवाया हो तो सस्ता सलाम यही है: {offer_text}।",
            ("हैलो डील", "{vendor_name}", "{offer_text}"),
            "पहला ऑर्डर अभी",
        ),
    ),
    flux_prompt=_still(
        "stacked combo of {dish_name} with a soft-focus offer vibe, "
        "bold food styling, no readable text in the frame"
    ),
    flux_variants=(
        "two-item combo on a metal tray, soda beads of condensation",
        "overhead value spread that looks abundant",
        "rider holding a sealed combo bag at dusk",
        "close-up of the hero item with a second item blurred",
        "night window counter with packed combo boxes",
    ),
    ltx_motion_prompt="snappy push-in, slight speed ramp, crumbs and steam, offer-energy motion",
    ltx_variants=(
        "quick push then settle on the combo",
        "speed ramp over the tray",
        "bag logo-free sway as rider turns",
        "whip to the second item",
        "timer-like pulsing lights in bokeh only",
    ),
    transition_style="whip pan into countdown end card",
    music_mood="upbeat promo with ticking percussion",
)

FAST_DELIVERY = _template(
    id="fast_delivery",
    category="fast_delivery",
    kind="category",
    title_en="Fast delivery",
    title_hi="तेज़ डिलीवरी",
    description="Convenience and speed across Aonla streets.",
    variable_defaults=_vars(eta_minutes="20", dish_name="hot rolls"),
    english=(
        _copy(
            "{eta_minutes} minutes. Still hot.",
            "{city} is small enough for speed. {app_name} brings {dish_name} from {vendor_name} before the craving cools.",
            ("FAST", "{eta_minutes} min", "Still steaming"),
            "Order for now, not later",
        ),
        _copy(
            "Craving shouldn't wait for a weekend.",
            "Tap {app_name}. Rider on the {city} grid. {dish_name} at your gate in {eta_minutes}.",
            ("NOW", "{city} grid", "{eta_minutes} min"),
            "Fast order · {app_name}",
        ),
        _copy(
            "From tawa to tote in a blink.",
            "{vendor_name} packs tight. {app_name} moves quicker. {brand_tagline}.",
            ("TAWA → GATE", "{vendor_name}", "Quick pack"),
            "Get it moving",
        ),
        _copy(
            "Rain, rush, or 9 pm. Still {eta_minutes}.",
            "Convenience is the product. {dish_name} on {app_name}, {offer_text}.",
            ("ANY HOUR", "{eta_minutes} min", "{dish_name}"),
            "Tap {cta_url}",
        ),
        _copy(
            "Don't go out. Get it in.",
            "Skip the scooter. {vendor_name} via {app_name} keeps {dish_name} honest and hot.",
            ("STAY IN", "Hot {dish_name}", "{app_name}"),
            "Deliver {dish_name}",
        ),
    ),
    hindi=(
        _copy(
            "{eta_minutes} मिनट। अभी भी गरम।",
            "{city} छोटा है, स्पीड बनती है। {app_name} {vendor_name} से {dish_name} पहुँचाए, चाहत ठंडी होने से पहले।",
            ("तेज़", "{eta_minutes} मिनट", "भाप बाकी"),
            "अभी के लिए ऑर्डर करो",
        ),
        _copy(
            "चाहत वीकेंड का इंतज़ार न करे।",
            "{app_name} टैप करो। {city} की गलियों में राइडर। {eta_minutes} में गेट पर {dish_name}।",
            ("अभी", "{city} रूट", "{eta_minutes} मिनट"),
            "तेज़ ऑर्डर · {app_name}",
        ),
        _copy(
            "तवे से बैग तक, पलक झपकते।",
            "{vendor_name} टाइट पैक करता है। {app_name} तेज़ चलता है। {brand_tagline}।",
            ("तवा → गेट", "{vendor_name}", "क्विक पैक"),
            "चलाना शुरू करो",
        ),
        _copy(
            "बारिश, रश, या रात 9। फिर भी {eta_minutes}।",
            "सुविधा ही प्रॉडक्ट है। {app_name} पर {dish_name}, {offer_text}।",
            ("कभी भी", "{eta_minutes} मिनट", "{dish_name}"),
            "{cta_url} टैप करो",
        ),
        _copy(
            "बाहर मत निकलो। अंदर मँगवा लो।",
            "स्कूटर छोड़ो। {app_name} से {vendor_name} {dish_name} गरम और ईमानदार रखता है।",
            ("घर रहो", "गरम {dish_name}", "{app_name}"),
            "{dish_name} पहुँचाओ",
        ),
    ),
    flux_prompt=_still(
        "food delivery rider on a scooter at {city} dusk, "
        "insulated bag, warm shop lights, {dish_name} implied in packaging, motion-ready still"
    ),
    flux_variants=(
        "close-up of a sealed hot packet with steam venting",
        "scooter blur past a lit market street",
        "hands receiving a bag at a courtyard gate",
        "kitchen pass to packed bag in one frame",
        "clock-like bokeh behind a sharp food close-up",
    ),
    ltx_motion_prompt="forward tracking with the rider, bag stable, street lights streaking softly",
    ltx_variants=(
        "subtle speed lines via light streaks, bag stays sharp",
        "handoff in slow motion",
        "steam from packet as lid lifts a millimetre",
        "kitchen to bag match motion",
        "gate opening, bag entering frame",
    ),
    transition_style="motion blur swipe to map-style CTA",
    music_mood="brisk electronic with cycle-bell ear candy",
)

MEAL_TIME = _template(
    id="meal_time_cravings",
    category="meal_time_cravings",
    kind="category",
    title_en="Meal-time cravings",
    title_hi="भूख का टाइम",
    description="Lunch, dinner, late-night, and weekend hunger windows.",
    variable_defaults=_vars(dish_name="chicken biryani"),
    english=(
        _copy(
            "Lunch window is open. {dish_name} is louder.",
            "Office break, {city} heat, {vendor_name} on {app_name}. {eta_minutes} minutes to {dish_name}.",
            ("LUNCH", "{dish_name}", "{eta_minutes} min"),
            "Order lunch on {app_name}",
        ),
        _copy(
            "Dinner plans: none. {dish_name}: yes.",
            "Let {vendor_name} cook. You only tap {app_name}. {offer_text}.",
            ("DINNER", "No plans needed", "{dish_name}"),
            "Dinner, delivered",
        ),
        _copy(
            "Late night in {city} still eats.",
            "{dish_name} after 10. {app_name} doesn't lecture. {vendor_name} still plates it hot.",
            ("LATE NIGHT", "After 10", "{dish_name}"),
            "Night order · {cta_url}",
        ),
        _copy(
            "Weekend craving has a name: {dish_name}.",
            "Slow morning, fast order. {brand_tagline}. {rating} stars from people like you.",
            ("WEEKEND", "{dish_name}", "{rating}★"),
            "Treat the weekend",
        ),
        _copy(
            "Rainy {city} evening. You know what you want.",
            "Hot {dish_name} from {vendor_name}. Stay in. {app_name} does the wet streets.",
            ("RAINY EVENING", "Stay in", "Hot {dish_name}"),
            "Crave it on {app_name}",
        ),
    ),
    hindi=(
        _copy(
            "लंच विंडो खुली है। {dish_name} और जोर से बोल रहा है।",
            "ऑफिस ब्रेक, {city} की गर्मी, {app_name} पर {vendor_name}। {eta_minutes} मिनट में {dish_name}।",
            ("लंच", "{dish_name}", "{eta_minutes} मिनट"),
            "{app_name} पर लंच ऑर्डर",
        ),
        _copy(
            "डिनर प्लान: कुछ नहीं। {dish_name}: हाँ।",
            "{vendor_name} पकाने दो। तुम सिर्फ़ {app_name} टैप करो। {offer_text}।",
            ("डिनर", "प्लान की ज़रूरत नहीं", "{dish_name}"),
            "डिनर, डिलीवर",
        ),
        _copy(
            "{city} की देर रात भी खाती है।",
            "10 बजे के बाद {dish_name}। {app_name} लेक्चर नहीं देता। {vendor_name} गरम प्लेट करता है।",
            ("लेट नाइट", "10 के बाद", "{dish_name}"),
            "रात का ऑर्डर · {cta_url}",
        ),
        _copy(
            "वीकेंड की चाहत का नाम: {dish_name}।",
            "सुबह धीमी, ऑर्डर तेज़। {brand_tagline}। तुम्हारे जैसे लोगों के {rating} स्टार।",
            ("वीकेंड", "{dish_name}", "{rating}★"),
            "वीकेंड ट्रीट",
        ),
        _copy(
            "{city} की बरसाती शाम। पता है क्या चाहिए।",
            "{vendor_name} की गरम {dish_name}। घर रहो। गीली गलियाँ {app_name} सँभाले।",
            ("बरसात", "घर रहो", "गरम {dish_name}"),
            "{app_name} पर क्रेव करो",
        ),
    ),
    flux_prompt=_still(
        "{dish_name} in a comforting meal-time setting, "
        "window light or fairy lights, family-scale portion, {city} home table"
    ),
    flux_variants=(
        "lunch desk with a opened {dish_name} box, appetizing not messy",
        "dinner table with warm lamps and the hero plate",
        "late-night kitchen counter, low key light",
        "weekend brass tray brunch-style Indian spread",
        "rain-streaked window bokeh behind steaming {dish_name}",
    ),
    ltx_motion_prompt="cozy push-in, steam, soft lamp flicker, comfort-food motion",
    ltx_variants=(
        "slow comfort push at lunch hour light",
        "candle-warm dinner drift",
        "late-night handheld micro sway",
        "weekend overhead drift across the tray",
        "rain bokeh with steam rising",
    ),
    transition_style="soft dissolve between craving and CTA",
    music_mood="cozy indie with rain and spoon foley",
)

SOCIAL_PROOF = _template(
    id="ratings_social_proof",
    category="ratings_social_proof",
    kind="category",
    title_en="Ratings / social proof",
    title_hi="रेटिंग / ग्राहक प्यार",
    description="Customer-love and star ratings without fake testimonials.",
    variable_defaults=_vars(rating="4.9", vendor_name="Al-Baik Corner"),
    english=(
        _copy(
            "{rating} stars. Not a rumour.",
            "{city} already rated {vendor_name} on {app_name}. {dish_name} keeps the average honest.",
            ("{rating}★", "{vendor_name}", "Loved in {city}"),
            "Join the ratings",
        ),
        _copy(
            "People reorder. That's the review.",
            "Repeat orders of {dish_name} say more than a paragraph. {brand_tagline}.",
            ("REORDERS", "{dish_name}", "{rating}★"),
            "Reorder on {app_name}",
        ),
        _copy(
            "Customer love, plated.",
            "{vendor_name} is trending in {city} because {dish_name} shows up hot and right.",
            ("TRENDING", "{city}", "{vendor_name}"),
            "Taste why · {cta_url}",
        ),
        _copy(
            "Don't take our word. Take {city}'s.",
            "{rating} on {app_name}. Start with {dish_name}. Leave yours after the last bite.",
            ("{city} SAYS", "{rating}★", "Leave yours"),
            "Order then rate",
        ),
        _copy(
            "The bag people photograph.",
            "Social proof is steam, not slogans. {vendor_name}, {offer_text}, {app_name}.",
            ("PHOTO THIS", "{vendor_name}", "{offer_text}"),
            "Get the bag",
        ),
    ),
    hindi=(
        _copy(
            "{rating} स्टार। अफ़वाह नहीं।",
            "{city} ने {app_name} पर {vendor_name} रेट कर दिया। {dish_name} औसत ईमानदार रखता है।",
            ("{rating}★", "{vendor_name}", "{city} को पसंद"),
            "रेटिंग में शामिल हो",
        ),
        _copy(
            "लोग रीऑर्डर करते हैं। यही रिव्यू है।",
            "{dish_name} के बार-बार ऑर्डर एक पैराग्राफ़ से ज़्यादा कहते हैं। {brand_tagline}।",
            ("रीऑर्डर", "{dish_name}", "{rating}★"),
            "{app_name} पर रीऑर्डर",
        ),
        _copy(
            "ग्राहक प्यार, प्लेट पर।",
            "{city} में {vendor_name} ट्रेंड इसलिए है कि {dish_name} गरम और सही आता है।",
            ("ट्रेंडिंग", "{city}", "{vendor_name}"),
            "वजह चखो · {cta_url}",
        ),
        _copy(
            "हमारी बात नहीं। {city} की बात।",
            "{app_name} पर {rating}। {dish_name} से शुरू करो। आखिरी निवाले के बाद अपनी रेटिंग दो।",
            ("{city} कहता है", "{rating}★", "अपनी दो"),
            "ऑर्डर करो, रेट करो",
        ),
        _copy(
            "वो बैग जिसका फोटो बनता है।",
            "सोशल प्रूफ भाप है, नारा नहीं। {vendor_name}, {offer_text}, {app_name}।",
            ("फोटो लो", "{vendor_name}", "{offer_text}"),
            "बैग मँगवाओ",
        ),
    ),
    flux_prompt=_still(
        "happy customers receiving food at a {city} doorstep, faces relaxed not speaking, "
        "hero {dish_name} unboxed, genuine evening light, no readable review text"
    ),
    flux_variants=(
        "unboxed {dish_name} with a satisfied but silent diner",
        "stack of packed orders on a pass, quality cues",
        "close-up of glistening food that implies five stars",
        "family sharing {dish_name} at home",
        "phone-on-table still, screen not legible, food in focus",
    ),
    ltx_motion_prompt="gentle reveal of the unboxed meal, smiles without lip movement, steam, social-ad motion",
    ltx_variants=(
        "lid lift reveal",
        "share-the-plate slow pan",
        "doorstep handoff freeze into smile",
        "sparkle on gravy, slow push",
        "group table tiny orbit",
    ),
    transition_style="star-burst light leak to CTA",
    music_mood="bright ukulele with crowd-warmth pads",
)

FESTIVAL = _template(
    id="festival_seasonal",
    category="festival_seasonal",
    kind="category",
    title_en="Festival / seasonal",
    title_hi="त्योहार / सीज़न",
    description="Festive and seasonal sweets or thalis without claiming dates.",
    variable_defaults=_vars(
        festival_name="Diwali week",
        dish_name="mithai thali",
        vendor_name="Mithai Ghar",
    ),
    english=(
        _copy(
            "{festival_name} tastes like {dish_name}.",
            "Light the house. Let {vendor_name} handle {dish_name} on {app_name}. {offer_text}.",
            ("{festival_name}", "{dish_name}", "{vendor_name}"),
            "Order festive on {app_name}",
        ),
        _copy(
            "Gifting hunger, not traffic.",
            "Send {dish_name} across {city} without leaving the courtyard. {eta_minutes} minutes.",
            ("GIFT HOT", "{city}", "{dish_name}"),
            "Send via {app_name}",
        ),
        _copy(
            "Seasonal menu. Same {app_name} tap.",
            "{vendor_name} dressed {dish_name} for {festival_name}. {brand_tagline}.",
            ("SEASONAL", "{festival_name}", "{dish_name}"),
            "Taste the season",
        ),
        _copy(
            "Guests coming. Kitchen already knows.",
            "Pre-order {dish_name}. {offer_text}. Keep the evening for people, not pans.",
            ("GUESTS", "Pre-order {dish_name}", "{offer_text}"),
            "Pre-order now",
        ),
        _copy(
            "Festival nights deserve better than leftover oil.",
            "Fresh {dish_name} from {vendor_name}. {rating} stars. {cta_url}.",
            ("FESTIVE NIGHT", "Fresh {dish_name}", "{rating}★"),
            "Celebrate on {app_name}",
        ),
    ),
    hindi=(
        _copy(
            "{festival_name} का स्वाद है {dish_name}।",
            "घर जलाओ। {dish_name} {vendor_name} और {app_name} सँभालें। {offer_text}।",
            ("{festival_name}", "{dish_name}", "{vendor_name}"),
            "{app_name} पर त्योहार ऑर्डर",
        ),
        _copy(
            "भूख गिफ्ट करो, ट्रैफ़िक नहीं।",
            "आँगन से निकले बिना {city} में {dish_name} भेजो। {eta_minutes} मिनट।",
            ("गरम गिफ्ट", "{city}", "{dish_name}"),
            "{app_name} से भेजो",
        ),
        _copy(
            "सीज़न मेन्यू। वही {app_name} टैप।",
            "{festival_name} के लिए {vendor_name} ने {dish_name} सजाया। {brand_tagline}।",
            ("सीज़न", "{festival_name}", "{dish_name}"),
            "सीज़न चखो",
        ),
        _copy(
            "मेहमान आ रहे हैं। किचन पहले से जानती है।",
            "{dish_name} प्री-ऑर्डर करो। {offer_text}। शाम लोगों के लिए रखो, तवे के लिए नहीं।",
            ("मेहमान", "{dish_name} प्री-ऑर्डर", "{offer_text}"),
            "अभी प्री-ऑर्डर",
        ),
        _copy(
            "त्योहारी रात बासी तेल की मोहताज नहीं।",
            "{vendor_name} की ताज़ा {dish_name}। {rating} स्टार। {cta_url}।",
            ("त्योहारी रात", "ताज़ा {dish_name}", "{rating}★"),
            "{app_name} पर मनाओ",
        ),
    ),
    flux_prompt=_still(
        "festive Indian sweets and {dish_name} with diyas and marigold, "
        "rich colour, {festival_name} mood, no readable greeting text"
    ),
    flux_variants=(
        "mithai boxes and diyas on a brass tray",
        "family-scale festive thali overhead",
        "marigold and warm fairy lights behind desserts",
        "gift-ready stacked sweet boxes",
        "night courtyard table with seasonal dishes",
    ),
    ltx_motion_prompt="slow sparkle on mithai, diya flicker, gentle camera drift, festive commercial",
    ltx_variants=(
        "diya flicker with a tiny push-in",
        "box lid reveal of sweets",
        "marigold petals drifting, food sharp",
        "tray rotation of festive items",
        "warm light sweep across desserts",
    ),
    transition_style="gold light leak into festive CTA",
    music_mood="festive dholak and shehnai, modern mix, not overpowering",
)

FREE_DELIVERY = _template(
    id="free_delivery_value",
    category="free_delivery_value",
    kind="category",
    title_en="Free delivery / value",
    title_hi="फ़्री डिलीवरी / वैल्यू",
    description="Value messaging for free delivery or extra portion deals.",
    variable_defaults=_vars(offer_text="free delivery over ₹249"),
    english=(
        _copy(
            "The fee isn't the flavour. {offer_text}.",
            "Keep the rupees for {dish_name}. {vendor_name} on {app_name} with {offer_text}.",
            ("VALUE", "{offer_text}", "{dish_name}"),
            "Save the fee",
        ),
        _copy(
            "More plate. Less extra.",
            "{city} eats better when delivery is {offer_text}. Tonight: {vendor_name}.",
            ("MORE PLATE", "{vendor_name}", "{offer_text}"),
            "Order value on {app_name}",
        ),
        _copy(
            "Free delivery. Full {dish_name}.",
            "Value window is open. {eta_minutes} minutes, {rating} stars, {brand_tagline}.",
            ("FREE DELIVERY", "{dish_name}", "{eta_minutes} min"),
            "Use {offer_text}",
        ),
        _copy(
            "Don't tip the algorithm. Tip the kitchen.",
            "Skip the extra fee when you can. {offer_text} on {app_name}.",
            ("TIP THE KITCHEN", "{offer_text}", "{app_name}"),
            "Claim value · {cta_url}",
        ),
        _copy(
            "Same streets. Better maths.",
            "{dish_name} from {vendor_name} plus {offer_text}. That is the {city} deal.",
            ("BETTER MATHS", "{city} deal", "{dish_name}"),
            "Get the deal",
        ),
    ),
    hindi=(
        _copy(
            "स्वाद फ़ीस नहीं है। {offer_text}।",
            "रुपये {dish_name} के लिए रखो। {app_name} पर {vendor_name}, {offer_text} के साथ।",
            ("वैल्यू", "{offer_text}", "{dish_name}"),
            "फ़ीस बचाओ",
        ),
        _copy(
            "ज़्यादा प्लेट। कम एक्स्ट्रा।",
            "जब डिलीवरी {offer_text} हो तब {city} बेहतर खाता है। आज रात: {vendor_name}।",
            ("ज़्यादा प्लेट", "{vendor_name}", "{offer_text}"),
            "{app_name} पर वैल्यू ऑर्डर",
        ),
        _copy(
            "फ़्री डिलीवरी। पूरी {dish_name}।",
            "वैल्यू विंडो खुली है। {eta_minutes} मिनट, {rating} स्टार, {brand_tagline}।",
            ("फ़्री डिलीवरी", "{dish_name}", "{eta_minutes} मिनट"),
            "{offer_text} लगाओ",
        ),
        _copy(
            "एल्गोरिदम को टिप नहीं। किचन को टिप।",
            "एक्स्ट्रा फ़ीस छोड़ सकते हो तो छोड़ो। {app_name} पर {offer_text}।",
            ("किचन को टिप", "{offer_text}", "{app_name}"),
            "वैल्यू लो · {cta_url}",
        ),
        _copy(
            "वही गलियाँ। बेहतर हिसाब।",
            "{vendor_name} की {dish_name} प्लस {offer_text}। यही है {city} डील।",
            ("बेहतर हिसाब", "{city} डील", "{dish_name}"),
            "डील पकड़ो",
        ),
    ),
    flux_prompt=_still(
        "generous portion of {dish_name} looking like strong value, "
        "delivery bag nearby, no price numerals or coupon text in frame"
    ),
    flux_variants=(
        "abundant platter that reads as extra value",
        "two meals for a shared table",
        "bag plus open box showing full portion",
        "kitchen packing an oversized portion honestly",
        "home table with leftovers still looking good",
    ),
    ltx_motion_prompt="generous reveal of portion size, slow pull-back, value-ad motion",
    ltx_variants=(
        "pull back from close-up to full plentiful plate",
        "box opening to a packed meal",
        "split to second item on the table",
        "bag set down, lid lift",
        "steam and a satisfied silent nod",
    ),
    transition_style="price-free stamp wipe to CTA",
    music_mood="playful bass and coin-free percussion",
)

APP_AWARENESS = _template(
    id="app_awareness",
    category="app_awareness",
    kind="category",
    title_en="App awareness",
    title_hi="ऐप अवेयरनेस",
    description="Order-now-on-Aonla-Online brand reminder.",
    variable_defaults=_vars(dish_name="whatever you're craving"),
    english=(
        _copy(
            "{city}'s food app is {app_name}.",
            "Local kitchens. Hindi and English. {brand_tagline}. If it's in {city}, start here.",
            ("{app_name}", "{city} food", "{brand_tagline}"),
            "Order now on {app_name}",
        ),
        _copy(
            "Stop scrolling menus in five chats.",
            "One app. {vendor_name} to late-night {dish_name}. {cta_url}.",
            ("ONE APP", "Many kitchens", "{cta_url}"),
            "Download-free: open {app_name}",
        ),
        _copy(
            "Made for {city}, not a megacity template.",
            "Riders who know the gali. Kitchens you already trust. {eta_minutes} minute habits.",
            ("MADE FOR {city}", "Known galis", "{eta_minutes} min"),
            "Try {app_name} tonight",
        ),
        _copy(
            "Hungry in {city}? That's an {app_name} problem.",
            "We collect {vendor_name}, {dish_name}, and {offer_text} so you don't hunt.",
            ("HUNGRY?", "{app_name}", "{offer_text}"),
            "Solve it in the app",
        ),
        _copy(
            "Tell the group: order on {app_name}.",
            "Instagram tonight, dinner still on time. {rating} kitchens, one tap, {brand_tagline}.",
            ("TELL THE GROUP", "Order on {app_name}", "{rating}★ kitchens"),
            "Share {cta_url}",
        ),
    ),
    hindi=(
        _copy(
            "{city} का फ़ूड ऐप है {app_name}।",
            "लोकल किचन। हिंदी और अंग्रेज़ी। {brand_tagline}। {city} में है तो यहीं से शुरू करो।",
            ("{app_name}", "{city} फ़ूड", "{brand_tagline}"),
            "{app_name} पर अभी ऑर्डर",
        ),
        _copy(
            "पाँच चैट में मेन्यू स्क्रॉल करना बंद करो।",
            "एक ऐप। {vendor_name} से लेट-नाइट {dish_name} तक। {cta_url}।",
            ("एक ऐप", "कई किचन", "{cta_url}"),
            "{app_name} खोलो",
        ),
        _copy(
            "मेगा सिटी टेम्पलेट नहीं। {city} के लिए बना।",
            "राइडर गली जानते हैं। किचन पहले से भरोसे में। {eta_minutes} मिनट की आदत।",
            ("{city} के लिए", "जानी गलियाँ", "{eta_minutes} मिनट"),
            "आज रात {app_name} ट्राई करो",
        ),
        _copy(
            "{city} में भूख? ये {app_name} का काम है।",
            "हम {vendor_name}, {dish_name} और {offer_text} इकट्ठा करते हैं, तुम ढूँढो मत।",
            ("भूख?", "{app_name}", "{offer_text}"),
            "ऐप में हल करो",
        ),
        _copy(
            "ग्रुप को कहो: {app_name} पर ऑर्डर करो।",
            "इंस्टाग्राम चलता रहे, डिनर समय पर आए। {rating} किचन, एक टैप, {brand_tagline}।",
            ("ग्रुप को बताओ", "{app_name} पर ऑर्डर", "{rating}★ किचन"),
            "{cta_url} शेयर करो",
        ),
    ),
    flux_prompt=_still(
        "collage-like but single still of {city} street food culture, "
        "phone in hand with unreadable screen, steaming {dish_name}, brand-free surfaces"
    ),
    flux_variants=(
        "phone and food on a {city} rooftop at dusk",
        "market street food stall, appetizing, no logos",
        "family sofa, food arriving, phone aside",
        "split composition of three dishes, one still frame",
        "map-like street bokeh with a sharp hero plate",
    ),
    ltx_motion_prompt="lifestyle push from city lights to the meal, phone idle, appetizing motion",
    ltx_variants=(
        "tilt from skyline-ish small-city lights to plate",
        "phone set down, food takes focus",
        "slow pan across multiple dishes",
        "door opening onto a waiting meal",
        "gentle zoom out to the whole table",
    ),
    transition_style="app-icon-free snap to wordmark CTA",
    music_mood="confident brand anthem lite with dhol",
)


def _pizza() -> ScenarioTemplate:
    return _template(
        id="pizza_onboarding",
        category="new_vendor_onboarded",
        kind="preset",
        title_en="Pizza vendor onboarding",
        title_hi="पिज़्ज़ा वेंडर ऑनबोर्डिंग",
        description="Concrete sample: a new pizza kitchen joining Aonla Online.",
        variable_defaults=_vars(
            vendor_name="Aonla Pizza Hub",
            dish_name="wood-fired margherita",
            offer_text="buy 1 get 1 on first order",
            eta_minutes="30",
        ),
        english=(
            _copy(
                "{city}'s new pizza night just landed.",
                "Hot oven pizza from {vendor_name} is on {app_name}. First order {offer_text}. "
                "Start with {dish_name}.",
                ("NEW PIZZA", "{vendor_name}", "{offer_text}"),
                "Order pizza on {app_name}",
            ),
            _copy(
                "Cheese pull incoming. {vendor_name} is live.",
                "{dish_name}, {eta_minutes} minutes, {city} streets. {brand_tagline}.",
                ("CHEESE PULL", "{dish_name}", "{eta_minutes} min"),
                "First slice · {cta_url}",
            ),
            _copy(
                "Welcome the new oven in {city}.",
                "Be first to rate {vendor_name}. {offer_text} while the tile is new.",
                ("WELCOME OVEN", "{vendor_name}", "Rate first"),
                "Welcome with an order",
            ),
            _copy(
                "Weeknight pizza without leaving the gali.",
                "{app_name} added {vendor_name}. {dish_name} plus garlic bread energy.",
                ("WEEKNIGHT", "{dish_name}", "{app_name}"),
                "Tap for pizza",
            ),
            _copy(
                "If {city} wanted a pizza button, this is it.",
                "{vendor_name} on {app_name}. {rating} starting love, {offer_text}.",
                ("PIZZA BUTTON", "{city}", "{offer_text}"),
                "Hit order now",
            ),
        ),
        hindi=(
            _copy(
                "{city} की नई पिज़्ज़ा नाइट आ गई है।",
                "{vendor_name} की गरम ओवन पिज़्ज़ा अब {app_name} पर। पहला ऑर्डर {offer_text}। "
                "{dish_name} से शुरू करो।",
                ("नई पिज़्ज़ा", "{vendor_name}", "{offer_text}"),
                "{app_name} पर पिज़्ज़ा ऑर्डर",
            ),
            _copy(
                "चीज़ पुल आने वाला है। {vendor_name} लाइव है।",
                "{dish_name}, {eta_minutes} मिनट, {city} की गलियाँ। {brand_tagline}।",
                ("चीज़ पुल", "{dish_name}", "{eta_minutes} मिनट"),
                "पहला स्लाइस · {cta_url}",
            ),
            _copy(
                "{city} के नए ओवन का स्वागत करो।",
                "{vendor_name} को पहले रेट करो। टाइल नई है तो {offer_text}।",
                ("नया ओवन", "{vendor_name}", "पहले रेट"),
                "ऑर्डर से स्वागत",
            ),
            _copy(
                "गली छोड़े बिना वीकनाइट पिज़्ज़ा।",
                "{app_name} ने {vendor_name} जोड़ा। {dish_name} और गार्लिक ब्रेड वाला मूड।",
                ("वीकनाइट", "{dish_name}", "{app_name}"),
                "पिज़्ज़ा टैप करो",
            ),
            _copy(
                "{city} को पिज़्ज़ा बटन चाहिए था तो ये है।",
                "{app_name} पर {vendor_name}। शुरूआती प्यार {rating}, {offer_text}।",
                ("पिज़्ज़ा बटन", "{city}", "{offer_text}"),
                "अभी ऑर्डर दबाओ",
            ),
        ),
            flux_prompt=_still(
                "bubbling cheese pizza {dish_name} on a rustic tin, "
                "stretchy mozzarella, fairy lights, small-town pizzeria counter in {city}"
            ),
        flux_variants=(
            "overhead pepperoni and basil, steam, no text",
            "cheese stretch frozen mid-pull",
            "pizza box crack opening, glow from cheese",
            "storefront pizza oven glow at dusk",
            "slice lift with stringy cheese toward camera",
        ),
        ltx_motion_prompt="slow push-in, cheese stretch, steam, oven glow flicker, pizza commercial motion",
        ltx_variants=(
            "cheese pull in slow motion",
            "box lid lift with steam bloom",
            "turntable-like pizza rotation",
            "oven flame flicker, pizza sharp",
            "slice lift toward lens",
        ),
        transition_style="steam dissolve into app CTA",
        music_mood="warm Italian-indie with dhol accent",
    )


def _biryani() -> ScenarioTemplate:
    return _template(
        id="biryani_craving",
        category="meal_time_cravings",
        kind="preset",
        title_en="Biryani craving",
        title_hi="बिरयानी क्रेविंग",
        description="Concrete sample: dum biryani for lunch, dinner, and late night.",
        variable_defaults=_vars(
            vendor_name="Dum Pukht Aonla",
            dish_name="hyderabadi dum biryani",
            offer_text="free raita on orders after 8",
            rating="4.9",
        ),
        english=(
            _copy(
                "The {city} biryani craving is specific.",
                "{dish_name} from {vendor_name} on {app_name}. Seal broken, steam up, {eta_minutes} minutes.",
                ("BIRYANI", "{vendor_name}", "Dum seal"),
                "Order dum on {app_name}",
            ),
            _copy(
                "Lunch is a handi, not a meeting.",
                "Break the dum on {dish_name}. {offer_text}. {brand_tagline}.",
                ("LUNCH HANDI", "{dish_name}", "{offer_text}"),
                "Biryani for lunch",
            ),
            _copy(
                "Dinner without debate: biryani.",
                "{rating} stars. Saffron, heat, bone or boneless — {vendor_name} already decided well.",
                ("DINNER", "{rating}★ biryani", "{vendor_name}"),
                "Tonight's handi",
            ),
            _copy(
                "Late night still deserves dum.",
                "After 10 in {city}, {app_name} still carries {dish_name} hot.",
                ("LATE NIGHT DUM", "After 10", "{dish_name}"),
                "Night biryani · {cta_url}",
            ),
            _copy(
                "Weekend biryani is a plan.",
                "Share the handi. {vendor_name}, {offer_text}, one tap on {app_name}.",
                ("WEEKEND HANDI", "Share {dish_name}", "{offer_text}"),
                "Share the order",
            ),
        ),
        hindi=(
            _copy(
                "{city} की बिरयानी चाहत साफ़ है।",
                "{app_name} पर {vendor_name} की {dish_name}। सील टूटी, भाप उठी, {eta_minutes} मिनट।",
                ("बिरयानी", "{vendor_name}", "दम सील"),
                "{app_name} पर दम ऑर्डर",
            ),
            _copy(
                "लंच मीटिंग नहीं, हांडी है।",
                "{dish_name} की दम तोड़ो। {offer_text}। {brand_tagline}।",
                ("लंच हांडी", "{dish_name}", "{offer_text}"),
                "लंच बिरयानी",
            ),
            _copy(
                "डिनर बिना बहस: बिरयानी।",
                "{rating} स्टार। केसर, गर्मी, बोन या बोनलेस — {vendor_name} ने सही तय कर लिया।",
                ("डिनर", "{rating}★ बिरयानी", "{vendor_name}"),
                "आज रात की हांडी",
            ),
            _copy(
                "देर रात को भी दम चाहिए।",
                "{city} में 10 बजे बाद भी {app_name} {dish_name} गरम पहुँचाता है।",
                ("लेट नाइट दम", "10 के बाद", "{dish_name}"),
                "रात की बिरयानी · {cta_url}",
            ),
            _copy(
                "वीकेंड बिरयानी एक प्लान है।",
                "हांडी शेयर करो। {vendor_name}, {offer_text}, {app_name} पर एक टैप।",
                ("वीकेंड हांडी", "{dish_name} शेयर", "{offer_text}"),
                "ऑर्डर शेयर करो",
            ),
        ),
        flux_prompt=_still(
            "dum biryani handi cracked open, saffron rice, steam column, "
            "copper pot, {vendor_name} kitchen mood in {city}"
        ),
        flux_variants=(
            "handi lid lift with a steam bloom",
            "close-up layered rice and meat",
            "family sharing from one handi",
            "late-night low-key biryani plate",
            "overhead spice scatter around the pot",
        ),
        ltx_motion_prompt="lid lift, steam rush, rice settle, slow rotation of the handi",
        ltx_variants=(
            "seal break steam burst",
            "spoon diving through layers",
            "slow orbit of copper handi",
            "late-night steam in a dark kitchen",
            "share-plate pan across rice",
        ),
        transition_style="steam bloom into craving CTA",
        music_mood="rich tabla and hungry low strings",
    )


def _burger() -> ScenarioTemplate:
    return _template(
        id="burger_combo",
        category="first_order_offer",
        kind="preset",
        title_en="Burger combo offer",
        title_hi="बर्गर कॉम्बो ऑफ़र",
        description="Concrete sample: limited burger combo for first orders.",
        variable_defaults=_vars(
            vendor_name="Grill & Bun",
            dish_name="crispy chicken burger combo",
            offer_text="₹149 combo till midnight",
            eta_minutes="22",
        ),
        english=(
            _copy(
                "{offer_text}. Bun's still loud.",
                "{dish_name} from {vendor_name} on {app_name}. Fries, fizz, timer. {city} tonight.",
                ("COMBO", "{offer_text}", "{vendor_name}"),
                "Grab the combo",
            ),
            _copy(
                "First-order burger luck.",
                "New to {app_name}? {offer_text} on {dish_name}. Don't screenshot forever — tap.",
                ("FIRST ORDER", "{dish_name}", "{offer_text}"),
                "Claim on {cta_url}",
            ),
            _copy(
                "Crunch you can hear in the Reel.",
                "{eta_minutes} minutes. Melt, pickle, {brand_tagline}.",
                ("CRUNCH", "{eta_minutes} min", "{dish_name}"),
                "Order the crunch",
            ),
            _copy(
                "Midnight is the expiry, not the vibe.",
                "Limited tile: {vendor_name} {dish_name}. {offer_text}.",
                ("TILL MIDNIGHT", "{vendor_name}", "{offer_text}"),
                "Beat the timer",
            ),
            _copy(
                "Combo maths for {city} hunger.",
                "Burger plus sides without a second debate. {rating} early love on {app_name}.",
                ("COMBO MATHS", "{city}", "{rating}★"),
                "Tap combo now",
            ),
        ),
        hindi=(
            _copy(
                "{offer_text}। बन अभी भी ज़ोर से बोल रहा है।",
                "{app_name} पर {vendor_name} का {dish_name}। फ्राइज़, फ़िज़, टाइमर। आज रात {city}।",
                ("कॉम्बो", "{offer_text}", "{vendor_name}"),
                "कॉम्बो पकड़ो",
            ),
            _copy(
                "पहले ऑर्डर की बर्गर किस्मत।",
                "{app_name} पर नए हो? {dish_name} पर {offer_text}। स्क्रीनशॉट हमेशा के लिए मत रखो — टैप करो।",
                ("पहला ऑर्डर", "{dish_name}", "{offer_text}"),
                "{cta_url} पर क्लेम",
            ),
            _copy(
                "क्रंच जो रील में सुनाई दे।",
                "{eta_minutes} मिनट। मेल्ट, अचार, {brand_tagline}।",
                ("क्रंच", "{eta_minutes} मिनट", "{dish_name}"),
                "क्रंच ऑर्डर करो",
            ),
            _copy(
                "मिडनाइट एक्सपायरी है, मूड नहीं।",
                "लिमिटेड टाइल: {vendor_name} {dish_name}। {offer_text}।",
                ("मिडनाइट तक", "{vendor_name}", "{offer_text}"),
                "टाइमर से पहले",
            ),
            _copy(
                "{city} की भूख का कॉम्बो हिसाब।",
                "बर्गर और साइड, दूसरी बहस नहीं। {app_name} पर शुरुआती {rating} प्यार।",
                ("कॉम्बो हिसाब", "{city}", "{rating}★"),
                "कॉम्बो अभी टैप",
            ),
        ),
        flux_prompt=_still(
            "stacked {dish_name} with fries and condensation-beaded drink, "
            "sesame bun, melted cheese, diner light, no price text"
        ),
        flux_variants=(
            "hero burger cross-section, juices catching light",
            "combo tray overhead",
            "fry toss freeze-frame",
            "late-night window pickup of a combo bag",
            "close-up pickle and sauce drip",
        ),
        ltx_motion_prompt="snappy push, bun compress, fry salt sparkle, promo speed ramp",
        ltx_variants=(
            "bun compress then spring",
            "fast push onto the tray",
            "fizz bubbles rising",
            "whip from burger to fries",
            "bag drop onto a table, slight bounce",
        ),
        transition_style="whip pan into midnight CTA",
        music_mood="upbeat trap-lite with burger foley",
    )


def _sweets() -> ScenarioTemplate:
    return _template(
        id="sweets_festival",
        category="festival_seasonal",
        kind="preset",
        title_en="Sweets / festival",
        title_hi="मिठाई / त्योहार",
        description="Concrete sample: festive mithai promotion for Aonla.",
        variable_defaults=_vars(
            vendor_name="Shankar Mithai Wale",
            dish_name="kesar peda and gulab jamun mix",
            festival_name="Diwali week",
            offer_text="festival box from ₹399",
        ),
        english=(
            _copy(
                "{festival_name} in {city} should taste like {vendor_name}.",
                "{dish_name} boxed fresh on {app_name}. {offer_text}. Light the diyas, skip the queue.",
                ("{festival_name}", "{vendor_name}", "{offer_text}"),
                "Order mithai on {app_name}",
            ),
            _copy(
                "Gift boxes without the market crush.",
                "Send {dish_name} across {city} in {eta_minutes}. {brand_tagline}.",
                ("GIFT BOX", "{dish_name}", "{eta_minutes} min"),
                "Send sweets · {cta_url}",
            ),
            _copy(
                "Guests at 8. Mithai before 7:30.",
                "Pre-order {vendor_name}. Keep {festival_name} for people, not counters.",
                ("PRE-ORDER", "{vendor_name}", "{festival_name}"),
                "Pre-order the box",
            ),
            _copy(
                "Kesar first. Traffic never.",
                "{rating} stars of syrup and saffron. {dish_name} on {app_name}.",
                ("KESAR FIRST", "{rating}★", "{dish_name}"),
                "Box it tonight",
            ),
            _copy(
                "Festival night, fresh syrup.",
                "{offer_text} from {vendor_name}. {city} knows this counter — now the app does.",
                ("FRESH SYRUP", "{offer_text}", "{city}"),
                "Celebrate with {app_name}",
            ),
        ),
        hindi=(
            _copy(
                "{city} में {festival_name} का स्वाद {vendor_name} जैसा होना चाहिए।",
                "{app_name} पर ताज़ा पैक {dish_name}। {offer_text}। दिए जलाओ, कतार छोड़ो।",
                ("{festival_name}", "{vendor_name}", "{offer_text}"),
                "{app_name} पर मिठाई ऑर्डर",
            ),
            _copy(
                "बाजार की भीड़ बिना गिफ्ट बॉक्स।",
                "{eta_minutes} में {city} भर {dish_name} भेजो। {brand_tagline}।",
                ("गिफ्ट बॉक्स", "{dish_name}", "{eta_minutes} मिनट"),
                "मिठाई भेजो · {cta_url}",
            ),
            _copy(
                "मेहमान 8 बजे। मिठाई 7:30 से पहले।",
                "{vendor_name} प्री-ऑर्डर करो। {festival_name} लोगों के लिए रखो, काउंटर के लिए नहीं।",
                ("प्री-ऑर्डर", "{vendor_name}", "{festival_name}"),
                "बॉक्स प्री-ऑर्डर",
            ),
            _copy(
                "पहले केसर। ट्रैफ़िक कभी नहीं।",
                "शरबत और केसर के {rating} स्टार। {app_name} पर {dish_name}।",
                ("पहले केसर", "{rating}★", "{dish_name}"),
                "आज रात बॉक्स करो",
            ),
            _copy(
                "त्योहारी रात, ताज़ा चासनी।",
                "{vendor_name} से {offer_text}। {city} इस काउंटर को जानता है — अब ऐप भी।",
                ("ताज़ा चासनी", "{offer_text}", "{city}"),
                "{app_name} के साथ मनाओ",
            ),
        ),
        flux_prompt=_still(
            "festive mithai of {dish_name}, diyas, marigold, "
            "brass trays, rich amber light, {festival_name} mood, no greeting text"
        ),
        flux_variants=(
            "peda and gulab jamun close-up with syrup sheen",
            "stacked gift boxes and diyas",
            "overhead festive sweet thali",
            "night counter glow, sweets sharp",
            "hands offering a box, faces not speaking",
        ),
        ltx_motion_prompt="diya flicker, syrup gleam, slow box reveal, festive drift",
        ltx_variants=(
            "lid reveal of mixed mithai",
            "slow sparkle across peda",
            "marigold drift, tray sharp",
            "warm light sweep",
            "box tied, slight camera settle",
        ),
        transition_style="gold light leak into festive CTA",
        music_mood="festive dholak and shehnai, gentle modern bed",
    )


def _discovery() -> ScenarioTemplate:
    return _template(
        id="local_restaurant_discovery",
        category="vendor_spotlight",
        kind="preset",
        title_en="Local restaurant discovery",
        title_hi="लोकल रेस्तराँ डिस्कवरी",
        description="Concrete sample: discover a neighbourhood restaurant on the app.",
        variable_defaults=_vars(
            vendor_name="Qila Family Dhaba",
            dish_name="tandoori mixed grill",
            offer_text="discovery 15% off",
            rating="4.7",
        ),
        english=(
            _copy(
                "You have walked past {vendor_name}. Now order it.",
                "Discover {city}'s {vendor_name} on {app_name}. {dish_name}, {rating} stars, {offer_text}.",
                ("DISCOVER", "{vendor_name}", "{city}"),
                "Find them on {app_name}",
            ),
            _copy(
                "Neighbourhood dhaba, app-distance away.",
                "{eta_minutes} minutes from Qila streets to your plate. {brand_tagline}.",
                ("NEAR YOU", "Qila streets", "{eta_minutes} min"),
                "Discover tonight",
            ),
            _copy(
                "The mixed grill {city} already argues about.",
                "{dish_name} from {vendor_name}. Spotlight week on {app_name}.",
                ("SPOTLIGHT", "{dish_name}", "{vendor_name}"),
                "Order the grill",
            ),
            _copy(
                "New to you. Old to {city}.",
                "Local discovery tile: {offer_text}. Start with {dish_name}.",
                ("NEW TO YOU", "{offer_text}", "{dish_name}"),
                "Try the local",
            ),
            _copy(
                "Tonight, eat like you live here.",
                "{vendor_name} on {app_name}. Hindi menus, English taps, {cta_url}.",
                ("EAT LOCAL", "{vendor_name}", "{app_name}"),
                "Open {cta_url}",
            ),
        ),
        hindi=(
            _copy(
                "तुम {vendor_name} के आगे से निकले हो। अब ऑर्डर करो।",
                "{app_name} पर {city} का {vendor_name} ढूँढो। {dish_name}, {rating} स्टार, {offer_text}।",
                ("डिस्कवर", "{vendor_name}", "{city}"),
                "{app_name} पर ढूँढो",
            ),
            _copy(
                "मोहल्ले का ढाबा, ऐप जितनी दूरी।",
                "क़िला गलियों से प्लेट तक {eta_minutes} मिनट। {brand_tagline}।",
                ("पास में", "क़िला गलियाँ", "{eta_minutes} मिनट"),
                "आज रात डिस्कवर",
            ),
            _copy(
                "वो मिक्स्ड ग्रिल जिस पर {city} बहस करता है।",
                "{vendor_name} की {dish_name}। {app_name} पर स्पॉटलाइट वीक।",
                ("स्पॉटलाइट", "{dish_name}", "{vendor_name}"),
                "ग्रिल ऑर्डर करो",
            ),
            _copy(
                "तुम्हारे लिए नया। {city} के लिए पुराना।",
                "लोकल डिस्कवरी टाइल: {offer_text}। {dish_name} से शुरू करो।",
                ("तुम्हारे लिए नया", "{offer_text}", "{dish_name}"),
                "लोकल ट्राई करो",
            ),
            _copy(
                "आज रात ऐसे खाओ जैसे यहीं रहते हो।",
                "{app_name} पर {vendor_name}। हिंदी मेन्यू, अंग्रेज़ी टैप, {cta_url}।",
                ("लोकल खाओ", "{vendor_name}", "{app_name}"),
                "{cta_url} खोलो",
            ),
        ),
        flux_prompt=_still(
            "North Indian dhaba mixed grill {dish_name}, tandoor glow, "
            "charred edges, family table, {city} evening, {vendor_name} atmosphere"
        ),
        flux_variants=(
            "tandoor glow with kebab close-up",
            "family dhaba table overhead",
            "storefront at blue hour, warm interior",
            "mixed grill platter hero",
            "naan pull beside the grill",
        ),
        ltx_motion_prompt="tandoor flicker, slow platter reveal, inviting dhaba drift",
        ltx_variants=(
            "embers flicker, platter sharp",
            "orbit the mixed grill",
            "tilt from signboard to table",
            "naan tear slow motion",
            "doorway push into the dining room",
        ),
        transition_style="match-cut tandoor glow to discovery CTA",
        music_mood="earthy folk guitar with soft dhol",
    )


TEMPLATES: dict[str, ScenarioTemplate] = {
    NEW_VENDOR.id: NEW_VENDOR,
    VENDOR_SPOTLIGHT.id: VENDOR_SPOTLIGHT,
    SIGNATURE_DISH.id: SIGNATURE_DISH,
    FIRST_ORDER.id: FIRST_ORDER,
    FAST_DELIVERY.id: FAST_DELIVERY,
    MEAL_TIME.id: MEAL_TIME,
    SOCIAL_PROOF.id: SOCIAL_PROOF,
    FESTIVAL.id: FESTIVAL,
    FREE_DELIVERY.id: FREE_DELIVERY,
    APP_AWARENESS.id: APP_AWARENESS,
    _pizza().id: _pizza(),
    _biryani().id: _biryani(),
    _burger().id: _burger(),
    _sweets().id: _sweets(),
    _discovery().id: _discovery(),
}


def get_template(template_id: str) -> ScenarioTemplate:
    from app.validation import ValidationError

    key = (template_id or "").strip()
    template = TEMPLATES.get(key)
    if template is None:
        raise ValidationError(f"Unknown campaign template '{template_id}'.", "template_id")
    return template


def list_templates(*, kind: str | None = None) -> list[ScenarioTemplate]:
    items = list(TEMPLATES.values())
    if kind is not None:
        items = [item for item in items if item.kind == kind]
    return items


def list_categories() -> list[ScenarioTemplate]:
    by_id = {item.id: item for item in list_templates(kind="category")}
    return [by_id[category] for category in CATEGORIES]


def list_presets() -> list[ScenarioTemplate]:
    by_id = {item.id: item for item in list_templates(kind="preset")}
    return [by_id[preset_id] for preset_id in PRESET_IDS]
