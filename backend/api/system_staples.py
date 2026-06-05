"""Curated list of ingredients most households treat as 'always have on hand'.

Each entry references a `simple_name` that MUST exist in the curated
hearth.pantry_ingredients catalogue. That catalogue gives us:
  * a clean, generalized display name ('Salt' not 'Spices, salt, table')
  * the canonical fdc_id (so the household_staples FK + recipe-ingredient
    comparison both work without ambiguity)

The household_staples seeder resolves `simple_name` -> fdc_id by exact
match on first lookup. Categories are kitchen-relevant, not USDA-food-group
relevant — keep them short and obvious.

Cuisine filter: if `cuisines` is empty, the staple is universal and applied
to every household. Otherwise we include it only when profile.cuisines
overlaps.
"""

from __future__ import annotations

# Eight categories. If you add a new one, also add it to PANTRY_CATEGORIES
# below so the UI groups it.
CATEGORIES = [
    "Oils & fats",
    "Vinegars",
    "Sauces & condiments",
    "Spices",
    "Dried herbs",
    "Baking",
    "Pantry basics",
    "Dairy & eggs",
]


# fmt: off
SYSTEM_STAPLES: list[dict] = [
    # ---- Oils & fats ----
    {"simple_name": "Olive oil",      "category": "Oils & fats", "cuisines": []},
    {"simple_name": "Vegetable oil",  "category": "Oils & fats", "cuisines": []},
    {"simple_name": "Butter",         "category": "Oils & fats", "cuisines": []},
    {"simple_name": "Sesame oil",     "category": "Oils & fats", "cuisines": ["asian", "thai", "chinese", "japanese", "korean", "vietnamese"]},

    # ---- Vinegars ----
    {"simple_name": "Vinegar",            "category": "Vinegars", "cuisines": []},
    {"simple_name": "Cider Vinegar",      "category": "Vinegars", "cuisines": []},
    {"simple_name": "Balsamic Vinegar",   "category": "Vinegars", "cuisines": ["italian", "mediterranean", "greek"]},
    {"simple_name": "Red Wine Vinegar",   "category": "Vinegars", "cuisines": ["mediterranean", "spanish", "french"]},
    # Rice Vinegar intentionally omitted — not in USDA's Foundation/Legacy
    # data. Asian-cuisine households should add it manually via the UI or chat.

    # ---- Sauces & condiments ----
    {"simple_name": "Soy sauce",            "category": "Sauces & condiments", "cuisines": ["asian", "japanese", "chinese", "thai", "vietnamese", "korean"]},
    {"simple_name": "Fish sauce",           "category": "Sauces & condiments", "cuisines": ["thai", "vietnamese"]},
    {"simple_name": "Mustard",              "category": "Sauces & condiments", "cuisines": []},
    {"simple_name": "Ketchup",              "category": "Sauces & condiments", "cuisines": []},
    {"simple_name": "Mayonnaise",           "category": "Sauces & condiments", "cuisines": []},
    {"simple_name": "Worcestershire Sauce", "category": "Sauces & condiments", "cuisines": []},
    {"simple_name": "Sriracha",             "category": "Sauces & condiments", "cuisines": ["thai", "american", "mexican"]},
    {"simple_name": "Tahini",               "category": "Sauces & condiments", "cuisines": ["greek", "mediterranean", "middle eastern", "lebanese", "turkish"]},
    {"simple_name": "Miso",                 "category": "Sauces & condiments", "cuisines": ["japanese", "korean"]},
    # Gochujang intentionally omitted — not in USDA. Korean-cuisine households
    # should add it manually.

    # ---- Spices ----
    {"simple_name": "Salt",            "category": "Spices", "cuisines": []},
    {"simple_name": "Black pepper",    "category": "Spices", "cuisines": []},
    {"simple_name": "Paprika",         "category": "Spices", "cuisines": []},
    {"simple_name": "Cumin",           "category": "Spices", "cuisines": []},
    {"simple_name": "Garlic powder",   "category": "Spices", "cuisines": []},
    {"simple_name": "Onion powder",    "category": "Spices", "cuisines": []},
    {"simple_name": "Chili powder",    "category": "Spices", "cuisines": []},
    {"simple_name": "Cinnamon",        "category": "Spices", "cuisines": []},
    {"simple_name": "Nutmeg",          "category": "Spices", "cuisines": []},
    {"simple_name": "Ginger (ground)", "category": "Spices", "cuisines": []},
    {"simple_name": "Turmeric",        "category": "Spices", "cuisines": ["indian", "moroccan", "middle eastern", "thai"]},
    {"simple_name": "Coriander",       "category": "Spices", "cuisines": ["indian", "moroccan", "middle eastern", "mexican"]},
    {"simple_name": "Cardamom",        "category": "Spices", "cuisines": ["indian", "middle eastern", "moroccan"]},
    {"simple_name": "Red pepper flakes", "category": "Spices", "cuisines": ["italian", "mediterranean"]},

    # ---- Dried herbs ----
    {"simple_name": "Oregano (dried)",  "category": "Dried herbs", "cuisines": ["italian", "greek", "mediterranean", "spanish", "mexican"]},
    {"simple_name": "Basil (dried)",    "category": "Dried herbs", "cuisines": ["italian", "mediterranean"]},
    {"simple_name": "Thyme (dried)",    "category": "Dried herbs", "cuisines": []},
    {"simple_name": "Rosemary (dried)", "category": "Dried herbs", "cuisines": ["mediterranean", "italian"]},
    {"simple_name": "Bay Leaf",         "category": "Dried herbs", "cuisines": []},
    {"simple_name": "Parsley (dried)",  "category": "Dried herbs", "cuisines": []},

    # ---- Baking ----
    {"simple_name": "Flour",           "category": "Baking", "cuisines": []},
    {"simple_name": "Sugar",           "category": "Baking", "cuisines": []},
    {"simple_name": "Brown sugar",     "category": "Baking", "cuisines": []},
    {"simple_name": "Baking powder",   "category": "Baking", "cuisines": []},
    {"simple_name": "Baking soda",     "category": "Baking", "cuisines": []},
    {"simple_name": "Vanilla extract", "category": "Baking", "cuisines": []},
    {"simple_name": "Yeast",           "category": "Baking", "cuisines": []},
    {"simple_name": "Honey",           "category": "Baking", "cuisines": []},
    {"simple_name": "Maple syrup",     "category": "Baking", "cuisines": ["american", "british"]},

    # ---- Pantry basics ----
    {"simple_name": "Rice (white)",     "category": "Pantry basics", "cuisines": []},
    {"simple_name": "Pasta",            "category": "Pantry basics", "cuisines": ["italian", "mediterranean"]},
    {"simple_name": "Tomato paste",     "category": "Pantry basics", "cuisines": []},
    {"simple_name": "Chicken broth",   "category": "Pantry basics", "cuisines": []},
    {"simple_name": "Vegetable broth",  "category": "Pantry basics", "cuisines": []},
    {"simple_name": "Canned tomatoes",  "category": "Pantry basics", "cuisines": ["italian", "mediterranean"]},
    {"simple_name": "Black beans",      "category": "Pantry basics", "cuisines": ["mexican", "american"]},
    {"simple_name": "Chickpeas",        "category": "Pantry basics", "cuisines": ["mediterranean", "middle eastern", "indian"]},

    # ---- Dairy & eggs ----
    {"simple_name": "Egg",      "category": "Dairy & eggs", "cuisines": []},
    {"simple_name": "Milk",     "category": "Dairy & eggs", "cuisines": []},
    {"simple_name": "Parmesan", "category": "Dairy & eggs", "cuisines": ["italian", "mediterranean"]},
]
# fmt: on


def applicable_to(cuisines_profile: list[str]) -> list[dict]:
    """Filter the system list to entries that apply to a household given
    their profile.cuisines. Empty cuisines on an entry = universal."""
    profile = {c.lower() for c in cuisines_profile}
    out: list[dict] = []
    for s in SYSTEM_STAPLES:
        cs = [c.lower() for c in s.get("cuisines", [])]
        if not cs or profile & set(cs):
            out.append(s)
    return out
