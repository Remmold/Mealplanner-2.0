"""Shared filter rules that decide whether a recipe belongs in the public
pool (the Explore deck). Used by:
  * backend/_build_amcoff_pool_seed.py — bulk amcoff import
  * backend/api/public_pool.py — every LLM-generated chat recipe that wants
    to mirror itself to the pool.

Keeping these rules in one place is what guarantees that "no desserts /
components / drinks in the dinner deck" applies to FUTURE recipes too, not
just the corpus we backfilled.

Pool-eligibility = the recipe is a real dinner meal. Sub-recipes (sauces,
doughs, marinades, dressings, jams), desserts (cakes, cookies, ice creams,
sweet bars), drinks (cocktails, smoothies, juices), and pure snacks/dips
are excluded — they may still be saved as the user's personal recipe, just
not surfaced to other households via Explore.
"""

from __future__ import annotations

import re


# Sub-recipes / accompaniments / condiments — not standalone meals.
COMPONENT_TITLE_KEYWORDS: tuple[str, ...] = (
    "deg",            # dough — Pizzadeg, Pajdeg
    "smet",           # batter
    "sås", "såser",   # sauces
    "kräm",           # cream-style spread
    "dressing", "vinaigrette",
    "marinad",
    "sirap", "saft",
    "sylt", "marmelad", "kompott", "chutney",
    "pickles", "pickle",
    "fond", "buljong",
    "smörkräm", "glasyr", "frosting",
    "krydda", "kryddblandning", "rub",
    "pesto", "majonnäs", "remoulade", "aioli",
    "hummus", "tzatziki", "raita", "tapenade",
    "topping",
    "salsa", "salsor",
    "röra", "smörgåsröra",
    "dipp", "dip",
    "relish", "chimichurri", "gremolata",
    "guacamole", "ajvar", "pebre", "mojo",
    "tillbehör", "garnering", "garnish", "smaksättning",
)
COMPONENT_CATEGORY_HITS: tuple[str, ...] = (
    "tillbehör",
    "sås & dressing",
    "såser",
    "marinader",
    "sylt och inläggningar",
    "sylt & inlagt",
)


# Sweets / desserts / baked treats.
DESSERT_TITLE_KEYWORDS: tuple[str, ...] = (
    "kaka", "kakor",
    "tårta", "tårtor",
    "bakelse", "bakelser",
    "muffin", "muffins",
    "cupcake", "cupcakes",
    "cookie", "cookies",
    "kex", "scones",
    "biskvi", "biskvier",
    "bulle", "bullar",
    "wienerbröd",
    "kanelbulle", "kanelbullar",
    "semla", "semlor",
    "lussekatt", "lussekatter",
    "pepparkaka", "pepparkakor",
    "mandelmussla", "mandelmusslor",
    "praliner", "pralin",
    "godis", "fudge", "kola", "knäck", "marshmallow",
    "glass", "sorbet", "gelato", "isglass", "popsicle", "popsicles",
    "parfait",
    "mousse",
    "tiramisu",
    "cheesecake",
    "ostkaka", "ostkakor",
    "kladdkaka", "kladdig",
    "creme brulee", "crème brûlée",
    "pannacotta", "panna cotta",
    "pavlova", "souffle", "soufflé",
    "fondant", "ganache",
    "trifle",
    "smoothiebowl",
    "fruktsallad", "fruktsalad",
    "kompottdessert",
    "rabarberpaj", "blåbärspaj", "äppelpaj",
    "äppelkaka", "morotskaka", "sockerkaka",
    "chokladbiskvi", "chokladtårta", "chokladkaka",
    "moccatårta", "prinsesstårta", "rulltårta",
    "mjuk kaka", "småkakor", "småkaka",
    "drömmar", "biscotti",
    "macaron", "macarons",
    "donut", "donuts", "munk", "munkar",
    "våffla", "våfflor",
    "pannkaka", "pannkakor", "plättar",
    "rutor", "ruta",
)
DESSERT_CATEGORY_HITS: tuple[str, ...] = (
    "dessert", "efterrätt", "bakat",
    "småkakor", "söta bullar", "tårtor", "tårta", "kakor",
    "godis", "glass", "choklad", "fika", "söta bröd",
)


# Drinks / beverages.
DRINK_TITLE_KEYWORDS: tuple[str, ...] = (
    "drink", "drinkar",
    "cocktail", "cocktails", "mocktail",
    "smoothie", "smoothies",
    "shake", "milkshake", "milkshakes",
    "juice", "juicer",
    "lemonad", "lemonade",
    "iste", "iskaffe",
    "kaffe", "kakao", "chokladdryck",
    "glögg", "punsch", "cider",
    "sangria", "spritz",
    "mojito", "martini", "bellini", "negroni",
    "kombucha", "kvass",
    "te",     # standalone "te" = tea recipe; suffix match (mostly safe)
    "dryck", "dricka",
    "saft",    # cordial / squash (already in components — kept here too)
    # Alcohol & spirits
    "gin", "vodka", "whisky", "whiskey", "bourbon", "tequila",
    "prosecco", "champagne", "vermouth",
    "alkoholfri",  # "Alkoholfri X" is virtually always a drink replacement
    # Note: 'rom' deliberately omitted (Swedish "rom" = caviar/roe — conflict)
    # Note: 'öl' (beer) omitted because compound-word false positives are
    # too risky for a 2-letter Swedish suffix
)
DRINK_CATEGORY_HITS: tuple[str, ...] = (
    "drycker", "drink", "drinkar",
    "smoothie", "smoothies",
    "saft",
)


def _main_thing(title: str) -> str:
    """The noun the recipe IS, before any 'med X' / 'och X' accompaniment.
    Special case: 'Spenat- och valnötssalsa' is a hyphenated compound where
    BOTH halves describe the same dish — the noun is in the second half. So
    when the first part ends in '-' we use the second part instead."""
    title_lower = title.lower()
    parts = re.split(r"\s+med\s+|\s+&\s+|\s+och\s+", title_lower, 1)
    if len(parts) > 1 and parts[0].rstrip().endswith("-"):
        main = parts[1].strip()
    else:
        main = parts[0].strip()
    main = re.sub(r"\s*\([^)]*\)", "", main).strip()
    return main


def _title_matches(main_thing: str, keywords: tuple[str, ...]) -> bool:
    for kw in keywords:
        # Whole-word match OR Swedish compound suffix ("pizzadeg" -> "deg").
        if main_thing.endswith(kw) or re.search(rf"\b{re.escape(kw)}\b", main_thing):
            return True
    return False


def _category_matches(categories: list[str], keywords: tuple[str, ...]) -> bool:
    cat_lower = " ".join((c or "").lower() for c in categories or [])
    return any(kw in cat_lower for kw in keywords)


def is_component_recipe(title: str, categories: list[str] | None = None) -> bool:
    main = _main_thing(title)
    return _title_matches(main, COMPONENT_TITLE_KEYWORDS) or _category_matches(
        categories or [], COMPONENT_CATEGORY_HITS,
    )


def is_dessert_recipe(title: str, categories: list[str] | None = None) -> bool:
    main = _main_thing(title)
    return _title_matches(main, DESSERT_TITLE_KEYWORDS) or _category_matches(
        categories or [], DESSERT_CATEGORY_HITS,
    )


def is_drink_recipe(title: str, categories: list[str] | None = None) -> bool:
    main = _main_thing(title)
    return _title_matches(main, DRINK_TITLE_KEYWORDS) or _category_matches(
        categories or [], DRINK_CATEGORY_HITS,
    )


def pool_rejection_reason(
    title: str, categories: list[str] | None = None,
) -> str | None:
    """If the recipe shouldn't enter the public dinner pool, return why.
    Returns None for eligible meals."""
    if is_component_recipe(title, categories):
        return "component"
    if is_dessert_recipe(title, categories):
        return "dessert"
    if is_drink_recipe(title, categories):
        return "drink"
    return None
