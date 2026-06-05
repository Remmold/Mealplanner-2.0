"""One-shot: ask an LLM which USDA ingredients should join the curated pantry.

Usage (from backend/):
    python -m scripts.expand_pantry --dry-run          # preview
    python -m scripts.expand_pantry                    # commit
    python -m scripts.expand_pantry --limit 300        # cap total candidates
    python -m scripts.expand_pantry --batch-size 80    # tune batch size

Idempotent: skips fdc_ids already in curated or pantry on every run.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent

# Add backend/ to sys.path so `api.*` imports work when run as a module or script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from api.database import get_connection  # noqa: E402
from api.ingredients import VALID_CATEGORIES  # noqa: E402
from api.recipe_db import get_recipe_db  # noqa: E402


# Food groups worth expanding. Skip prepared/branded/irrelevant groups entirely.
INCLUDE_FOOD_GROUPS = {
    "Vegetables and Vegetable Products",
    "Fruits and Fruit Juices",
    "Dairy and Egg Products",
    "Poultry Products",
    "Beef Products",
    "Pork Products",
    "Lamb, Veal, and Game Products",
    "Finfish and Shellfish Products",
    "Cereal Grains and Pasta",
    "Legumes and Legume Products",
    "Nut and Seed Products",
    "Fats and Oils",
    "Spices and Herbs",
    "Soups, Sauces, and Gravies",
    "Sausages and Luncheon Meats",
}

# Regexes to pre-filter junk/brand/prepared variants.
EXCLUDE_PATTERNS = [
    re.compile(r"\b(cooked|fried|boiled|baked|roasted|grilled|steamed|microwaved|reheated|braised|broiled|stewed|canned in oil|breaded)\b", re.I),
    re.compile(r"\b(dehydrated|freeze.?dried|powder|flakes|reconstituted|prepared)\b", re.I),
    re.compile(r"\b(infant|baby|toddler|junior)\b", re.I),
    re.compile(r"\b(low.?fat|reduced.?fat|fat.?free|lite|diet|sugar.?free|unsweetened)\b", re.I),
    re.compile(r"\b(NFS|UPC|with added|with [A-Z])\b"),
    re.compile(r"®|™"),
    # Very long names are almost always prepared dishes or branded variants
]


def looks_branded(name: str) -> bool:
    if len(name) > 80:
        return True
    # Obvious brand-like patterns: "Pillsbury, ...", "Kraft Foods, ..."
    if re.match(r"^[A-Z][a-zA-Z&' ]+,\s*[A-Z]", name) and "," in name[:30]:
        # Heuristic: starts like "Brand Name, Product"
        first_segment = name.split(",", 1)[0]
        generic_starts = {
            "Beef", "Pork", "Chicken", "Turkey", "Lamb", "Fish", "Cheese",
            "Milk", "Bread", "Nuts", "Seeds", "Oil", "Sauce", "Soup", "Egg",
            "Cereals", "Pasta", "Rice", "Vegetables", "Fruit",
        }
        if first_segment not in generic_starts:
            return True
    return False


def fetch_candidates(limit: int | None) -> list[dict]:
    """USDA rows in included food groups, not already in curated or pantry."""
    with get_recipe_db() as conn:
        pantry_ids = {r["fdc_id"] for r in conn.execute("SELECT fdc_id FROM pantry_ingredients").fetchall()}

    placeholders = ", ".join(["?"] * len(INCLUDE_FOOD_GROUPS))
    with get_connection() as conn:
        curated_ids = {r[0] for r in conn.execute("SELECT fdc_id FROM main.common_ingredients").fetchall()}
        rows = conn.execute(
            f"SELECT fdc_id, name, food_group FROM usda.ingredients "
            f"WHERE food_group IN ({placeholders}) "
            f"ORDER BY food_group, length(name), name",
            list(INCLUDE_FOOD_GROUPS),
        ).fetchall()

    excluded_ids = curated_ids | pantry_ids

    # Bucket by food_group so we can interleave
    buckets: dict[str, list[dict]] = {g: [] for g in INCLUDE_FOOD_GROUPS}
    for fdc_id, name, food_group in rows:
        if fdc_id in excluded_ids:
            continue
        if looks_branded(name):
            continue
        if any(p.search(name) for p in EXCLUDE_PATTERNS):
            continue
        buckets[food_group].append({"fdc_id": fdc_id, "name": name, "food_group": food_group})

    # Round-robin interleave so each batch sees variety across food groups
    out: list[dict] = []
    iters = {g: iter(items) for g, items in buckets.items()}
    while iters:
        for g in list(iters):
            try:
                out.append(next(iters[g]))
                if limit and len(out) >= limit:
                    return out
            except StopIteration:
                del iters[g]
    return out


# --- LLM agent ---


class PantryCandidate(BaseModel):
    fdc_id: int
    simple_name: str       # clean display name, e.g. "Cod" not "Fish, cod, Atlantic, raw"
    category: str          # one of VALID_CATEGORIES


class PantryBatchResult(BaseModel):
    accepted: list[PantryCandidate]


_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")

pantry_agent = Agent(
    _MODEL,
    output_type=PantryBatchResult,
    system_prompt=(
        "You curate a home cook's pantry. Given a list of USDA food items, "
        "decide which ones belong in a general-purpose cooking pantry.\n\n"
        "ACCEPT: staples and common ingredients a home cook would actually use "
        "(e.g. cod, feta, parsley, turmeric, tahini, kale, leek, shiitake, halloumi).\n\n"
        "REJECT:\n"
        "- Duplicates of common ingredients already present (the list you see is "
        "  already filtered, but USDA still has overlapping variants — pick ONE per concept).\n"
        "- Prepared/cooked variants ('raw' is preferred over 'cooked')\n"
        "- Weird processed forms (dehydrated, powder, reconstituted, concentrate)\n"
        "- Obscure game meats unless broadly useful (keep venison, skip ostrich)\n"
        "- Medical/infant/diet-specific foods\n"
        "- Branded products\n\n"
        "For each accepted item, provide:\n"
        "- fdc_id (exactly as given)\n"
        "- simple_name: clean, short display name. 'Fish, cod, Atlantic, raw' → 'Cod'. "
        "  'Cheese, feta' → 'Feta'. Title case, no USDA prefixes.\n"
        f"- category: one of {sorted(VALID_CATEGORIES)}\n\n"
        "Be selective — prefer quality over quantity. A typical batch of 100 might "
        "yield 15-40 accepted items."
    ),
)


async def classify_batch(batch: list[dict]) -> list[PantryCandidate]:
    lines = [f"fdc_id={c['fdc_id']} | {c['name']} | group={c['food_group']}" for c in batch]
    prompt = (
        "Classify these USDA items. Return only the ones that belong in a curated pantry.\n\n"
        + "\n".join(lines)
    )
    result = await pantry_agent.run(prompt)
    return result.output.accepted


def insert_accepted(accepted: list[PantryCandidate]) -> int:
    inserted = 0
    with get_recipe_db() as conn:
        for c in accepted:
            if c.category not in VALID_CATEGORIES:
                # Guard: coerce invalid category via food group mapping fallback
                c.category = "Other"
            conn.execute(
                "INSERT INTO pantry_ingredients (fdc_id, simple_name, category) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(fdc_id) DO NOTHING",
                [c.fdc_id, c.simple_name.strip(), c.category],
            )
            inserted += 1
    return inserted


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print accepted items, do not write")
    parser.add_argument("--limit", type=int, default=None, help="Cap total candidates (for testing)")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    candidates = fetch_candidates(args.limit)
    print(f"Candidates after pre-filter: {len(candidates)}")
    if not candidates:
        print("Nothing to classify.")
        return

    # Demonstrate our own category mapping for reference
    print(f"Using model: {_MODEL}")
    print(f"Batch size: {args.batch_size}, dry-run: {args.dry_run}")

    all_accepted: list[PantryCandidate] = []
    for i in range(0, len(candidates), args.batch_size):
        batch = candidates[i : i + args.batch_size]
        print(f"  Batch {i // args.batch_size + 1}: classifying {len(batch)} items...", flush=True)
        try:
            accepted = await classify_batch(batch)
        except Exception as e:
            print(f"    ERROR: {e}")
            continue
        # Guard: agent might return fdc_ids not in batch
        valid_ids = {c["fdc_id"] for c in batch}
        accepted = [a for a in accepted if a.fdc_id in valid_ids]
        print(f"    accepted {len(accepted)}/{len(batch)}")
        all_accepted.extend(accepted)

    # Dedup by fdc_id (in case of overlap)
    seen = set()
    deduped = []
    for a in all_accepted:
        if a.fdc_id in seen:
            continue
        seen.add(a.fdc_id)
        deduped.append(a)

    print(f"\nTotal accepted: {len(deduped)}")
    by_cat: dict[str, int] = {}
    for a in deduped:
        by_cat[a.category] = by_cat.get(a.category, 0) + 1
    for cat in sorted(by_cat):
        print(f"  {cat}: {by_cat[cat]}")

    if args.dry_run:
        print("\n--- Dry run sample ---")
        for a in deduped[:30]:
            print(f"  [{a.category}] {a.simple_name} (fdc_id={a.fdc_id})")
        if len(deduped) > 30:
            print(f"  ... and {len(deduped) - 30} more")
        print("\nDry run — nothing written. Re-run without --dry-run to commit.")
        return

    inserted = insert_accepted(deduped)
    print(f"\nInserted {inserted} rows into pantry_ingredients.")


if __name__ == "__main__":
    asyncio.run(main())
