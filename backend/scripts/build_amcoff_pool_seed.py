"""Build a pool-seed JSON from amcoff/recept using the Swedish alias table.

Deterministic — NO LLM calls. Each ingredient is either resolved via the alias
table (gold standard) or dropped from the recipe. Recipes where less than
MIN_COVERAGE of ingredients resolve are skipped entirely.

The output JSON matches the shape backend/scripts/seed_public_pool.py already
ingests for starter_recipes.json, so the existing pool-import code path works
unchanged."""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download

BACKEND = Path(__file__).resolve().parent.parent
SEEDS = BACKEND / "seeds"
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from scripts.extract_swedish_ingredients import _stream_decode, normalize  # noqa: E402
from api.pool_filters import (  # noqa: E402
    is_component_recipe,
    is_dessert_recipe,
    is_drink_recipe,
)
from seeds.swedish_aliases import build_sv_to_fdc  # noqa: E402

PILOT_N = 1000         # Sample size — bigger now that the gate is strict
MIN_COVERAGE = 1.00    # Accuracy-first: skip recipes with ANY unresolved ingredient
RANDOM_SEED = 13

# Title or category match → recipe is a component (dough, sauce, dressing,
# jam, stock, etc.), not a standalone meal. Skip these. Matched as
# whole-word, lowercased.
COMPONENT_TITLE_KEYWORDS = (
    "deg",            # dough — Pizzadeg, Pajdeg, Bulldeg
    "smet",           # batter — pannkakssmet, smet
    "sås", "såser",   # sauces
    "kräm",           # cream-style spread / sauce
    "dressing",
    "vinaigrette",
    "marinad",
    "sirap",
    "saft",           # syrup/cordial
    "sylt",
    "marmelad",
    "kompott",
    "chutney",
    "pickles",
    "pickle",
    "fond",
    "buljong",
    "smörkräm",
    "glasyr",
    "frosting",
    "krydda",         # spice blend
    "kryddblandning",
    "rub",
    "pesto",
    "majonnäs",
    "remoulade",
    "aioli",
    "hummus",
    "tzatziki",
    "raita",
    "tapenade",
    "topping",
    "salsa", "salsor",   # spenat- och valnötssalsa, mangosalsa, tomatsalsa
    "röra",              # Swedish spread/mash: tomatröra, gurkröra
    "dipp", "dip",
    "relish",
    "chimichurri",
    "gremolata",
    "guacamole",
    "ajvar",
    "pebre",
    "mojo",
    "smörgåsröra",
    "tillbehör",
    "garnering",
    "garnish",
    "smaksättning",
)

COMPONENT_CATEGORY_HITS = (
    "tillbehör",
    "sås & dressing",
    "såser",
    "marinader",
    "sylt och inläggningar",
    "sylt & inlagt",
    "drycker",
    "drink",
    "smoothie",
    "saft",
)

# Dessert / baked-treat / candy keywords — these are *not meals*, they don't
# belong in a dinner-focused pool. Matched as suffix-of-compound or whole
# word against the main thing (pre-' med ') in the title.
DESSERT_TITLE_KEYWORDS = (
    "kaka", "kakor",
    "tårta", "tårtor",
    "bakelse", "bakelser",
    "muffin", "muffins",
    "cupcake", "cupcakes",
    "cookie", "cookies",
    "kex",
    "scones",
    "biskvi", "biskvier",
    "bulle", "bullar",
    "wienerbröd",
    "kanelbulle", "kanelbullar",
    "semla", "semlor",
    "lussekatt", "lussekatter",
    "pepparkaka", "pepparkakor",
    "mandelmussla", "mandelmusslor",
    "praliner", "pralin",
    "godis",
    "fudge",
    "kola",
    "knäck",
    "marshmallow",
    "glass",
    "sorbet",
    "gelato",
    "popsicle", "popsicles",
    "isglass",
    "parfait",
    "mousse",
    "tiramisu",
    "cheesecake",
    "creme brulee", "crème brûlée",
    "pannacotta", "panna cotta",
    "pavlova",
    "souffle", "soufflé",
    "fondant",
    "ganache",
    "trifle",
    "smoothiebowl",
    "fruktsallad",
    "fruktsalad",
    "kompottdessert",
    "rabarberpaj",
    "blåbärspaj",
    "äppelpaj",
    "äppelkaka",
    "morotskaka",
    "chokladbiskvi",
    "chokladtårta",
    "chokladkaka",
    "moccatårta",
    "prinsesstårta",
    "rulltårta",
    "sockerkaka",
    "mjuk kaka",
    "småkakor",
    "småkaka",
    "drömmar",
    "rutor", "ruta",       # Hallonrutor, Chokladrutor, Kokosrutor — Swedish bars
    "ostkaka", "ostkakor", # Swedish dessert "cheesecake"
    "kladdkaka", "kladdig",
    "biscotti",
    "macaron", "macarons",
    "donut", "donuts", "munk", "munkar",
    "våffla", "våfflor",
    "pannkaka", "pannkakor",
    "plättar",
)

DESSERT_CATEGORY_HITS = (
    "dessert",
    "efterrätt",
    "bakat",
    "småkakor",
    "söta bullar",
    "tårtor",
    "tårta",
    "kakor",
    "godis",
    "glass",
    "choklad",
    "fika",
    "söta bröd",
)

# Default grams per ingredient when qty is null or unparseable, keyed by
# USDA food_group. A pinch of salt has to be tiny; a serving of lettuce
# is a hundred grams. One-size-fits-all defaults like the 1g we used before
# made "1g sallad" possible.
FOOD_GROUP_DEFAULT_G: dict[str, float] = {
    "Spices and Herbs":                       2.0,
    "Fats and Oils":                         15.0,
    "Vegetables and Vegetable Products":    100.0,
    "Fruits and Fruit Juices":              100.0,
    "Dairy and Egg Products":               100.0,
    "Cereal Grains and Pasta":               75.0,
    "Legumes and Legume Products":          100.0,
    "Nut and Seed Products":                 30.0,
    "Beef Products":                        150.0,
    "Pork Products":                        150.0,
    "Poultry Products":                     150.0,
    "Finfish and Shellfish Products":       150.0,
    "Lamb, Veal, and Game Products":        150.0,
    "Sausages and Luncheon Meats":           75.0,
    "Soups, Sauces, and Gravies":            60.0,
    "Beverages":                            200.0,
    "Sweets":                                15.0,
    "Baked Products":                        50.0,
    "Breakfast Cereals":                     40.0,
    "Restaurant Foods":                      50.0,
    "Fast Foods":                            50.0,
}
FOOD_GROUP_DEFAULT_FALLBACK = 50.0

# Words that, when present in an unresolved ingredient name, mean the recipe
# is meaningless without it. Even if MIN_COVERAGE somehow loosens, a recipe
# that drops a protein gets quarantined.
PROTEIN_KEYWORDS = (
    "fläsk", "kotlett", "kassler", "skinka", "bacon", "korv",
    "kyckling", "höns", "kalkon", "anka",
    "biff", "stek", "nöt", "kött", "färs", "filé", "ox",
    "lamm", "älg", "rådjur", "ren", "vilt",
    "lax", "torsk", "fisk", "räka", "räkor", "kräft", "musslor",
    "tonfisk", "sill", "makrill", "öring", "sej", "gös", "ansjov",
    "ägg", "tofu", "tempeh", "halloumi",
)

# Swedish unit -> grams. Values are per 1 unit. None = count unit, handled
# specially below.
UNIT_TO_GRAMS: dict[str, float] = {
    "dl": 100.0, "cl": 10.0, "ml": 1.0, "l": 1000.0,
    "msk": 15.0, "tsk": 5.0, "krm": 1.0,
    "g": 1.0, "gram": 1.0, "kg": 1000.0, "hg": 100.0,
}

# Per-item gram estimate for COUNT units like "1 st" when no better
# context is available. Used only as a last-resort fallback.
COUNT_DEFAULT_G = 80.0

# When qty is null or unparseable, fall back to this small "pinch" value
# rather than a full COUNT_DEFAULT_G. ICA recipes use null-qty mostly for
# "salt och peppar" / "färska örter" sort of seasonings.
NULL_QTY_DEFAULT_G = 1.0

# Leading-word qty hints on the ingr field. When the SOURCE ingredient name
# starts with one of these (before normalization), a bare-count qty refers
# to N of that unit, not N whole items. "8 skivor lagrad ost" = 8 cheese
# slices, ~160g total, NOT 8 × 80g = 640g. Without this, the slice context
# is lost when normalize() strips the prefix.
INGR_LEADING_UNIT_G: dict[str, float] = {
    "skivor": 20.0, "skiva": 20.0, "skivat": 20.0, "skivad": 20.0,
    "klyfta": 5.0,  "klyftor": 5.0,                       # cloves
    "kruka": 25.0,  "krukor": 25.0,                       # potted herbs
    "burk": 400.0,  "burkar": 400.0,                      # cans ~400g
    "påse": 250.0,  "påsar": 250.0,                       # bags ~250g
    "förp": 200.0,  "förpackning": 200.0,
    "pkt": 200.0,   "paket": 200.0,
    "knippe": 100.0,"knippen": 100.0,                     # bunch
    "näve": 30.0,   "nävar": 30.0,                        # handful
    "ask": 200.0,   "askar": 200.0,                       # boxes
}

# Per-fdc_id "1 of these = N grams" — used when the qty is a bare count and
# we know what specific food it is. Reality-checked against typical Swedish
# household sizes.
FDC_WHOLE_ITEM_G: dict[int, float] = {
    # Eggs
    171287:  50.0,   # 1 whole egg
    172184:  18.0,   # 1 yolk
    172183:  33.0,   # 1 white
    # Alliums
    170000: 100.0,   # yellow onion
    170008: 100.0,   # red onion (mapped to sweet)
    170499:  30.0,   # shallot
    170006:  15.0,   # scallion
    169230:   5.0,   # 1 garlic clove
    169246: 100.0,   # leek
    # Tomatoes / vegetables sold by piece
    170457: 100.0,   # tomato
    169225: 250.0,   # cucumber
    170108: 150.0,   # red bell pepper
    170427: 150.0,   # green bell pepper
    169383: 150.0,   # yellow bell pepper
    170106:  15.0,   # chili pepper
    168576:  15.0,   # jalapeno
    169228: 300.0,   # eggplant
    169291: 200.0,   # zucchini
    170393:  80.0,   # carrot
    169145: 100.0,   # beetroot
    170417: 100.0,   # parsnip
    168448: 1000.0,  # whole pumpkin (rare to count as 1)
    169986: 600.0,   # cauliflower head
    170379: 350.0,   # broccoli head
    169975: 900.0,   # cabbage head
    169994:  20.0,   # bunch of chives (rough)
    # Fruits
    171689: 180.0,   # apple
    169118: 180.0,   # pear
    173944: 120.0,   # banana
    167746:  60.0,   # lemon
    168155:  60.0,   # lime
    169097: 130.0,   # orange
    169124: 800.0,   # whole pineapple
    169910: 200.0,   # mango
    168153:  80.0,   # kiwi
    169949:  70.0,   # plum
    171697:  35.0,   # apricot
    167762:  12.0,   # 1 strawberry (when counted singly — rare)
    171707: 200.0,   # avocado
    171705: 200.0,   # avocado (all)
    173021:  60.0,   # fig
    # Roots
    170032: 150.0,   # potato (medium)
    168482: 130.0,   # sweet potato
    169231:  30.0,   # ginger root piece
    173474:  20.0,   # horseradish
    # Mushrooms
    169251:  25.0,   # 1 button mushroom
    169255:  90.0,   # 1 portobello
    168422:  30.0,   # 1 chanterelle
    169242:  20.0,   # 1 shiitake
    # Baked
    174924:  30.0,   # bread slice
    175030:  30.0,   # generic bread slice
    172686:  50.0,   # wheat bread USED AS hamburger bun / roll default
                     # (slices of bread come through INGR_LEADING_UNIT_G at 20g)
    169716:  60.0,   # tortilla
    # Proteins (1 unit = 1 fillet/chop/portion)
    168251: 150.0,   # pork chop
    168249: 200.0,   # pork tenderloin
    171477: 150.0,   # chicken breast fillet
    172383: 120.0,   # chicken thigh fillet
    173614: 100.0,   # chicken drumstick
    173632:  50.0,   # chicken wing
    175167: 150.0,   # salmon portion
    173686: 150.0,
    171955: 150.0,   # cod portion
    173706: 150.0,
    173614: 100.0,
    # Sausages
    172934:  60.0,   # 1 pork sausage / falukorv slice
    172968:  50.0,   # frankfurter
    173864:  20.0,   # ham slice
    168277:  10.0,   # bacon strip
    # Dairy (individual items)
    173420:  20.0,   # 1 cube/portion of feta — when counted
    173418: 200.0,   # 1 cream-cheese tub
    # Eggs are above
}

UNICODE_FRAC = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1/3, "⅔": 2/3,
                "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}

NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)")
RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)")
UNIT_TOKEN = re.compile(
    r"\b(dl|cl|ml|l|msk|tsk|krm|gram|g|kg|hg|st|styck|klyfta|klyftor|"
    r"kruka|krukor|påse|burk|pkt|förp|knippe|kruka)\b",
    re.IGNORECASE,
)


def parse_qty_to_grams(
    qty_str: str | None,
    *,
    null_default: float = 50.0,
    count_default: float = COUNT_DEFAULT_G,
) -> float:
    """Parse a Swedish qty string like '1 dl', '½ tsk', '2-3 msk' into grams.

    `null_default` is used when qty_str is null/unparseable.
    `count_default` is the per-item gram weight used when qty is a bare
    number (no unit) — callers compute this from the food's identity:
       slice/clove/burk context  → INGR_LEADING_UNIT_G
       known whole-item fdc      → FDC_WHOLE_ITEM_G
       otherwise                 → food-group default
    """
    if not qty_str:
        return null_default
    s = qty_str.strip().lower()

    # Range -> midpoint
    range_match = RANGE_RE.search(s)
    if range_match:
        a = float(range_match.group(1).replace(",", "."))
        b = float(range_match.group(2).replace(",", "."))
        num = (a + b) / 2
    else:
        num = None
        # Unicode fraction maybe combined with whole: "1½"
        whole = 0.0
        frac = 0.0
        m = re.match(r"^(\d+)?\s*([½¼¾⅓⅔⅛⅜⅝⅞])", s)
        if m:
            whole = float(m.group(1)) if m.group(1) else 0.0
            frac = UNICODE_FRAC.get(m.group(2), 0.0)
            num = whole + frac
        if num is None:
            # a/b fraction
            m = re.match(r"^(\d+)\s*/\s*(\d+)", s)
            if m:
                num = float(m.group(1)) / float(m.group(2))
        if num is None:
            # decimal
            m = re.match(r"^(\d+(?:[.,]\d+)?)", s)
            if m:
                num = float(m.group(1).replace(",", "."))
        if num is None:
            num = 1.0   # last resort

    unit_match = UNIT_TOKEN.search(s)
    if not unit_match:
        # Bare number — treat as a count. Multiplier times caller-supplied
        # per-item weight (depends on what the ingredient actually IS).
        return num * count_default

    unit = unit_match.group(1).lower()
    grams_per_unit = UNIT_TO_GRAMS.get(unit)
    if grams_per_unit is None:
        # Count units (st, klyfta, kruka, etc)
        # Smaller defaults for cloves/leaves
        if unit in ("klyfta", "klyftor"):
            return num * 5.0
        if unit in ("kruka", "krukor"):
            return num * 25.0
        return num * COUNT_DEFAULT_G
    return num * grams_per_unit


# ---------------------------------------------------------------------------
# meal_type / time_min inference from amcoff metadata
# ---------------------------------------------------------------------------
BREAKFAST_KEYWORDS = ("frukost", "brunch", "müsli", "yoghurt", "havregryns")
LUNCH_KEYWORDS = ("lunch", "smörgås", "macka", "sallad")
SNACK_KEYWORDS = ("mellanmål", "snacks", "drink", "smoothie", "godis", "saft",
                  "marmelad", "sylt")

DESSERT_KEYWORDS = ("dessert", "kaka", "tårta", "glass", "sorbet", "pannkak",
                    "munk", "bulle", "kex", "praliner", "cookies", "muffin")

TIME_BUCKET_MIDPOINT = {
    "Under 15 minuter": 12,
    "Under 30 minuter": 22,
    "Under 60 minuter": 45,
    "Över 60 minuter": 75,
}


def infer_meal_type(title: str, categories: list[str]) -> str:
    text = (title + " " + " ".join(categories or [])).lower()
    if any(k in text for k in BREAKFAST_KEYWORDS):
        return "breakfast"
    if any(k in text for k in LUNCH_KEYWORDS):
        return "lunch"
    if any(k in text for k in SNACK_KEYWORDS + DESSERT_KEYWORDS):
        # Treat dessert/snack as dinner-adjacent so they show up; dinner is
        # the household's only enabled slot per the current UX.
        return "dinner"
    return "dinner"


def infer_dietary(categories: list[str]) -> list[str]:
    text = " ".join(categories or []).lower()
    flags: list[str] = []
    if "vegetar" in text:
        flags.append("vegetarian")
    if "veganskt" in text or "vegan" in text:
        flags.append("vegan")
    if "glutenfri" in text:
        flags.append("gluten_free")
    if "mjölkfri" in text or "mjölkproteinfri" in text:
        flags.append("dairy_free")
    if "laktosfri" in text:
        flags.append("lactose_free")
    return flags


def infer_time_min(cooking_time: str | None) -> int | None:
    return TIME_BUCKET_MIDPOINT.get(cooking_time or "")


# Filter functions live in api.pool_filters so the same rules apply to BOTH
# this backfill build AND every LLM/chat-generated recipe that calls
# mirror_to_pool() at runtime.


# ---------------------------------------------------------------------------
# LLM safety net: catches dessert / breakfast / component recipes that the
# keyword filter misses. Trained on every recipe title that survives the
# cheap deterministic filters above. Anything not classified as `meal` or
# `borderline_meal` gets dropped from the dinner pool.
# ---------------------------------------------------------------------------
LLM_CLASSIFIER_MODEL = os.getenv("OPENAI_CLASSIFIER_MODEL", "gpt-4o-mini")
LLM_CLASSIFIER_BATCH = 60   # titles per batch
LLM_CLASSIFIER_CONCURRENCY = 4

LLM_CLASSIFY_SYSTEM = (
    "You classify Swedish recipe TITLES for a meal-planning app. The user "
    "wants ONLY dinner meals — real, substantive dishes you'd serve as a "
    "main course.\n\n"
    "Categorize each title as exactly one of:\n"
    "  - meal:        a substantive dinner main (proteins + sides, casseroles, "
    "stews, pasta mains, savory pies with meat/fish, full grain bowls).\n"
    "  - dessert:     anything sweet — cakes (kaka, tårta), cookies (kakor, "
    "kex), candies (godis, praliner), ice creams (glass, sorbet), mousses, "
    "puddings, sweet bars (rutor), sweet pies (äppelpaj, kladdkaka), "
    "Swedish ostkaka, sweet pancakes/waffles, sweet buns (bullar, semlor).\n"
    "  - breakfast:   yogurt bowls, granola, overnight oats, smoothies, "
    "breakfast porridges (havregrynsgröt etc), egg-based brunch dishes.\n"
    "  - snack:       small bites, single-bite finger food, mellanmål, "
    "smoothies, drinks, single-ingredient snacks, dips alone.\n"
    "  - component:   sauces, dressings, doughs, marinades, jams, syrups, "
    "stocks, spice blends, SALSAS, dips, spreads (Swedish 'röra'), "
    "condiments, relishes, chutneys, pestos, tapenades, guacamole, hummus, "
    "tzatziki, pebre, ajvar, chimichurri — anything you SERVE WITH a meal "
    "but isn't a meal by itself, even if it has substantial ingredients.\n"
    "  - borderline_meal: arguable but lean meal — keep it.\n\n"
    "When in doubt, prefer `borderline_meal` over `dessert`/`component` — "
    "we'd rather keep one ambiguous meal than delete a real meal.\n\n"
    "Return ONLY JSON matching the requested schema, no prose."
)


async def _classify_one_batch(
    client, titles: list[str], sem: asyncio.Semaphore,
) -> dict[str, str]:
    """Classify a batch of titles. Returns {title: classification}."""
    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "classification": {
                            "type": "string",
                            "enum": ["meal", "dessert", "breakfast", "snack",
                                     "component", "borderline_meal"],
                        },
                    },
                    "required": ["title", "classification"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["results"],
        "additionalProperties": False,
    }

    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    user_msg = (
        f"Classify each of these {len(titles)} Swedish recipe titles. "
        f"Return one entry per input title, in the same order, with the "
        f"EXACT original title string preserved.\n\n{numbered}"
    )
    async with sem:
        resp = await client.chat.completions.create(
            model=LLM_CLASSIFIER_MODEL,
            messages=[
                {"role": "system", "content": LLM_CLASSIFY_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ClassificationResult",
                    "schema": schema,
                    "strict": True,
                },
            },
            temperature=0,
        )
    payload = json.loads(resp.choices[0].message.content)
    out: dict[str, str] = {}
    for item in payload.get("results", []):
        out[item["title"]] = item["classification"]
    return out


async def llm_classify_titles(titles: list[str]) -> dict[str, str]:
    """Classify every title. Returns {title: classification}. Titles that
    the model didn't return a verdict for default to 'borderline_meal' (kept)
    so a single LLM hiccup doesn't drop real recipes."""
    if not titles:
        return {}
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(LLM_CLASSIFIER_CONCURRENCY)

    batches: list[list[str]] = []
    for i in range(0, len(titles), LLM_CLASSIFIER_BATCH):
        batches.append(titles[i:i + LLM_CLASSIFIER_BATCH])

    print(f"  llm classifier: {len(titles)} titles in {len(batches)} batches "
          f"(concurrency={LLM_CLASSIFIER_CONCURRENCY})")
    tasks = [_classify_one_batch(client, b, sem) for b in batches]
    chunks = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, str] = {}
    for chunk in chunks:
        if isinstance(chunk, Exception):
            print(f"  llm classifier batch failed: {chunk}")
            continue
        out.update(chunk)
    # Default any missing titles to borderline_meal (kept) for safety.
    for t in titles:
        out.setdefault(t, "borderline_meal")
    return out


async def _build_fdc_food_group_map(alias_fdcs: list[int]) -> dict[int, str]:
    """Query USDA once for each fdc_id used by the alias table. Used for
    food-group-aware default quantities when qty is null."""
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            "SELECT fdc_id, food_group FROM hearth.usda_ingredients "
            "WHERE fdc_id = ANY($1::int[])",
            list(set(alias_fdcs)),
        )
    finally:
        await conn.close()
    return {r["fdc_id"]: r["food_group"] for r in rows}


def default_g_for_fdc(fdc_id: int, food_group_map: dict[int, str]) -> float:
    fg = food_group_map.get(fdc_id)
    return FOOD_GROUP_DEFAULT_G.get(fg or "", FOOD_GROUP_DEFAULT_FALLBACK)


def count_default_for(
    raw_ingr_name: str,
    fdc_id: int,
    food_group_map: dict[int, str],
) -> float:
    """Compute the gram weight of '1 unit' for a bare-count quantity.
    Resolution order:
      1) Leading qty-unit prefix on the source ingr name ('skivor', 'klyftor',
         'burk', etc.) — overrides anything else because it tells us the
         intent directly.
      2) Per-fdc_id whole-item lookup (egg=50g, garlic clove=5g, etc.)
      3) Food-group default (vegetables=100g, dairy=50g, spices=2g, etc.)
    """
    ingr_lower = (raw_ingr_name or "").lower()
    for kw, weight in INGR_LEADING_UNIT_G.items():
        if ingr_lower.startswith(kw + " ") or ingr_lower == kw:
            return weight
    if fdc_id in FDC_WHOLE_ITEM_G:
        return FDC_WHOLE_ITEM_G[fdc_id]
    return default_g_for_fdc(fdc_id, food_group_map)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
async def main() -> None:
    print("[stage 1] loading amcoff ica.json ...")
    path = hf_hub_download(repo_id="amcoff/recept", filename="ica.json", repo_type="dataset")
    recipes = _stream_decode(Path(path).read_text(encoding="utf-8"))
    print(f"  {len(recipes)} recipes available")

    alias = build_sv_to_fdc()
    print(f"  alias table: {len(alias)} entries")

    food_group_map = await _build_fdc_food_group_map(list(alias.values()))
    print(f"  food-group lookup: {len(food_group_map)} fdc_ids classified")

    random.seed(RANDOM_SEED)
    sample = random.sample(recipes, PILOT_N)
    print(f"  pilot sample: {len(sample)} random recipes\n")

    seed_out: list[dict] = []
    skipped_low_coverage = 0
    skipped_protein_drop = 0
    skipped_no_ingredients = 0
    skipped_component = 0
    skipped_dessert = 0
    skipped_drink = 0

    for r in sample:
        title = (r.get("title") or "").strip()
        if not title:
            continue

        categories = r.get("categories") or []
        if is_component_recipe(title, categories):
            skipped_component += 1
            continue
        if is_dessert_recipe(title, categories):
            skipped_dessert += 1
            continue
        if is_drink_recipe(title, categories):
            skipped_drink += 1
            continue

        raw_groups = r.get("ingredients") or []
        ingredients_out: list[dict] = []
        ingr_total = 0
        ingr_hit = 0
        dropped_a_protein = False

        for grp in raw_groups:
            for item in grp.get("list") or []:
                raw_name = (item.get("ingr") or "").strip()
                raw_qty = item.get("qty")
                if not raw_name:
                    continue
                ingr_total += 1
                normalized_parts = normalize(raw_name)
                if not normalized_parts:
                    if any(kw in raw_name.lower() for kw in PROTEIN_KEYWORDS):
                        dropped_a_protein = True
                    continue

                # Resolve each part first; quantity gets a food-group-aware
                # default per part when raw_qty is null.
                resolved: list[tuple[str, int]] = []
                for n in normalized_parts:
                    fdc = alias.get(n)
                    if fdc is None:
                        if any(kw in n for kw in PROTEIN_KEYWORDS):
                            dropped_a_protein = True
                        continue
                    resolved.append((n, fdc))

                if not resolved:
                    continue

                # If qty is null/unparseable, give each part its own
                # category-appropriate default (sallad ≈ 100g, not 1g).
                if not raw_qty:
                    for n, fdc in resolved:
                        gms = default_g_for_fdc(fdc, food_group_map)
                        ingr_hit += 1
                        ingredients_out.append({
                            "fdc_id": fdc, "name": n, "quantity_g": round(gms, 1),
                        })
                else:
                    # Per-item weight depends on what THIS ingredient is.
                    # "8 skivor lagrad ost" → 1 unit = 1 slice (~20g), not
                    # 80g. "4 hamburgerbröd" → 1 unit = 1 bun (~50g).
                    first_fdc = resolved[0][1]
                    total_g = parse_qty_to_grams(
                        raw_qty,
                        null_default=default_g_for_fdc(first_fdc, food_group_map),
                        count_default=count_default_for(
                            raw_name, first_fdc, food_group_map,
                        ),
                    )
                    gms_each = total_g / len(resolved)
                    for n, fdc in resolved:
                        ingr_hit += 1
                        ingredients_out.append({
                            "fdc_id": fdc, "name": n, "quantity_g": round(gms_each, 1),
                        })

        if ingr_total == 0:
            skipped_no_ingredients += 1
            continue
        coverage = ingr_hit / ingr_total if ingr_total else 0
        if coverage < MIN_COVERAGE:
            skipped_low_coverage += 1
            continue
        if dropped_a_protein:
            skipped_protein_drop += 1
            continue

        instructions = [s.strip() for s in (r.get("instructions") or []) if s.strip()]
        if not instructions:
            continue

        seed_out.append({
            "name": title,
            "ingredients": ingredients_out,
            "instructions": instructions,
            "meal_type": infer_meal_type(title, categories),
            "cuisine": ["swedish"],
            "dietary": infer_dietary(categories),
            "time_min": infer_time_min(r.get("cooking_time")),
            "source": "amcoff_ica",
            "source_url": r.get("url"),
            "coverage_pct": round(min(coverage, 1.0) * 100, 1),
        })

    print(f"[stage 3] composing seed records ...")
    print(f"  built (before LLM gate):  {len(seed_out)}")
    print(f"  skipped (component recipe — dough/sauce/etc):  {skipped_component}")
    print(f"  skipped (dessert / sweet / baked treat):       {skipped_dessert}")
    print(f"  skipped (drink / beverage):                    {skipped_drink}")
    print(f"  skipped (coverage < {MIN_COVERAGE*100:.0f}%):  {skipped_low_coverage}")
    print(f"  skipped (protein dropped):                     {skipped_protein_drop}")
    print(f"  skipped (no ingredients):                      {skipped_no_ingredients}")

    # ---- LLM safety net ---------------------------------------------------
    print(f"\n[stage 4] LLM title classifier — catching dessert/breakfast/snack leaks the keyword filter missed ...")
    titles = [r["name"] for r in seed_out]
    classifications = await llm_classify_titles(titles)
    by_class: dict[str, int] = {}
    for cls in classifications.values():
        by_class[cls] = by_class.get(cls, 0) + 1
    print(f"  classifier verdicts: {by_class}")

    # Only keep recipes the LLM classified as `meal` or `borderline_meal`.
    KEEP_CLASSES = {"meal", "borderline_meal"}
    pre_llm = len(seed_out)
    seed_out = [
        r for r in seed_out
        if classifications.get(r["name"], "borderline_meal") in KEEP_CLASSES
    ]
    print(f"  dropped by LLM gate: {pre_llm - len(seed_out)}")
    print(f"  final pool count:    {len(seed_out)}")

    # Stamp the LLM verdict onto each record so we can inspect/debug later.
    for r in seed_out:
        r["llm_classification"] = classifications.get(r["name"], "borderline_meal")

    out_path = SEEDS / "amcoff_pool_seed.json"
    out_path.write_text(json.dumps(seed_out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path} ({out_path.stat().st_size/1024:.1f} KB)")

    if seed_out:
        print(f"\n--- sample recipe (first record) ---")
        first = seed_out[0]
        print(f"name:       {first['name']}")
        print(f"meal_type:  {first['meal_type']}")
        print(f"time_min:   {first['time_min']}")
        print(f"cuisine:    {first['cuisine']}")
        print(f"dietary:    {first['dietary']}")
        print(f"coverage:   {first['coverage_pct']}%")
        print(f"ingredients ({len(first['ingredients'])}):")
        for ing in first['ingredients'][:8]:
            print(f"  - {ing['quantity_g']:6.1f} g  [{ing['fdc_id']:6d}] {ing['name']}")
        if len(first['ingredients']) > 8:
            print(f"  ... +{len(first['ingredients']) - 8} more")
        print(f"first instruction: {first['instructions'][0][:140]}")


if __name__ == "__main__":
    asyncio.run(main())
