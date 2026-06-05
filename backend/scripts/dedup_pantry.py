"""One-shot: ask the LLM to find duplicate ingredients in the curated pantry
and register them as aliases so the shopping list consolidates them.

Strategy:
1. Load all 819 curated ingredients (dbt seed + pantry).
2. Group candidates by category (dedup only within the same category — avoids
   e.g. "Tomato" (Vegetables) aliasing to "Tomato paste" (Sauces)).
3. Hand each category batch to an LLM that returns groups of ids that refer
   to the same concept. It picks a canonical (preferring dbt seed ids — lower
   ids — when available, because those are shorter/cleaner names).
4. Write every non-canonical id -> canonical into `ingredient_aliases`.

Idempotent: skips ids already aliased on re-runs.

Usage (from backend/):
    uv run python -m scripts.dedup_pantry --dry-run
    uv run python -m scripts.dedup_pantry
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from api.ingredients import load_aliases, load_all_curated_meta  # noqa: E402
from api.recipe_db import get_recipe_db  # noqa: E402


# ============================================================
# LLM contract
# ============================================================


class DuplicateGroup(BaseModel):
    canonical_fdc_id: int
    alias_fdc_ids: list[int]


class DedupResult(BaseModel):
    groups: list[DuplicateGroup]


_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")

dedup_agent = Agent(
    _MODEL,
    output_type=DedupResult,
    system_prompt=(
        "You are cleaning up a home cook's pantry. The list contains ingredient "
        "entries that should be unique by concept but often have near-duplicates "
        "(e.g. 'Butter' and 'Butter, Unsalted'; 'Milk (whole)' and 'Whole Milk'; "
        "'Flour (all-purpose)' and 'White Flour').\n\n"
        "Task: identify GROUPS of ids that refer to the same cooking concept. "
        "For each group, pick ONE canonical_fdc_id (prefer the shortest, cleanest "
        "name — usually the lower id which comes from the curated seed list) and "
        "list all other equivalent ids as alias_fdc_ids.\n\n"
        "Rules:\n"
        "- Only group items that are truly interchangeable in a recipe. "
        "  'Salted butter' and 'Unsalted butter' ARE interchangeable in most "
        "  home cooking — group them. 'Yoghurt' and 'Greek yoghurt' are NOT "
        "  quite — keep separate.\n"
        "- Singular vs plural of the same food -> same (e.g. 'Apple' = 'Apples').\n"
        "- Raw vs cooked/canned of the same food -> same if the raw form is the\n"
        "  canonical cooking ingredient (Cod Raw ≈ Cod). But 'Tomato paste' ≠ 'Tomato'.\n"
        "- Different colour/variety of essentially the same ingredient -> same "
        "  (e.g. 'Red potatoes' ≈ 'White potatoes' ≈ 'Potato').\n"
        "- If no duplicates exist in the batch, return an empty groups list.\n"
        "- Never put the same id in both canonical and alias fields.\n"
        "- A group must have at least 2 ids total."
    ),
)


async def classify_batch(category: str, items: list[tuple[int, str]]) -> list[DuplicateGroup]:
    if len(items) < 2:
        return []
    lines = [f"fdc_id={fid} | {name}" for fid, name in items]
    prompt = (
        f"Category: {category}\n"
        f"Ingredients:\n" + "\n".join(lines)
    )
    result = await dedup_agent.run(prompt)
    return result.output.groups


def insert_aliases(groups: list[DuplicateGroup]) -> int:
    inserted = 0
    with get_recipe_db() as conn:
        for g in groups:
            for alias_id in g.alias_fdc_ids:
                if alias_id == g.canonical_fdc_id:
                    continue
                conn.execute(
                    "INSERT INTO ingredient_aliases (alias_fdc_id, canonical_fdc_id) "
                    "VALUES (?, ?) ON CONFLICT(alias_fdc_id) DO NOTHING",
                    [alias_id, g.canonical_fdc_id],
                )
                inserted += 1
    return inserted


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=120,
                        help="Items per LLM call. Keep under 150 to avoid context bloat.")
    args = parser.parse_args()

    # Collect candidates: dbt seed ∪ pantry, skipping anything already aliased
    meta = load_all_curated_meta()
    existing_aliases = load_aliases()
    candidates: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for fid, info in meta.items():
        if fid in existing_aliases:
            continue
        candidates[info["category"]].append((fid, info["simple_name"]))

    total = sum(len(v) for v in candidates.values())
    print(f"Candidates: {total} ingredients across {len(candidates)} categories")
    for cat, items in sorted(candidates.items(), key=lambda x: -len(x[1])):
        print(f"  {cat}: {len(items)}")

    all_groups: list[DuplicateGroup] = []
    for category, items in candidates.items():
        if len(items) < 2:
            continue
        # Sort by id so canonical (likely lower id from dbt seed) lands early
        items.sort(key=lambda x: x[0])
        for i in range(0, len(items), args.batch_size):
            batch = items[i:i + args.batch_size]
            print(f"\n[{category}] batch {i // args.batch_size + 1}: {len(batch)} items", flush=True)
            try:
                groups = await classify_batch(category, batch)
            except Exception as e:
                print(f"  ERROR: {e}")
                continue

            # Filter: only keep ids that were actually in this batch
            batch_ids = {fid for fid, _ in batch}
            kept = []
            for g in groups:
                canonical_ok = g.canonical_fdc_id in batch_ids
                aliases_ok = [a for a in g.alias_fdc_ids if a in batch_ids and a != g.canonical_fdc_id]
                if canonical_ok and aliases_ok:
                    kept.append(DuplicateGroup(
                        canonical_fdc_id=g.canonical_fdc_id,
                        alias_fdc_ids=aliases_ok,
                    ))
            print(f"  -> {len(kept)} duplicate groups ({sum(len(g.alias_fdc_ids) for g in kept)} aliases)")
            all_groups.extend(kept)

    total_aliases = sum(len(g.alias_fdc_ids) for g in all_groups)
    print(f"\nTotal: {len(all_groups)} groups, {total_aliases} aliases")

    # Show a sample
    print("\n--- Sample ---")
    name_by_id = {fid: info["simple_name"] for fid, info in meta.items()}
    for g in all_groups[:20]:
        canon = name_by_id.get(g.canonical_fdc_id, f"?{g.canonical_fdc_id}")
        aliases = ", ".join(name_by_id.get(a, f"?{a}") for a in g.alias_fdc_ids)
        print(f"  {canon} (fdc_id={g.canonical_fdc_id}) <- {aliases}")
    if len(all_groups) > 20:
        print(f"  ...and {len(all_groups) - 20} more groups")

    if args.dry_run:
        print("\nDry run — nothing written. Re-run without --dry-run to commit.")
        return

    inserted = insert_aliases(all_groups)
    print(f"\nInserted {inserted} alias rows.")


if __name__ == "__main__":
    asyncio.run(main())
