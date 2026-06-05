"""Backfill images for every hearth.public_recipes row that doesn't have one.

Uses the same OpenAI gpt-image-1 generator wired up in api/image_gen.py. Safe
to re-run: rows that already have image_path are skipped.

Cost (defaults): 59 recipes × $0.042 (medium 1024x1024) ≈ $2.50 one-time.
Override with OPENAI_IMAGE_QUALITY=low (~$0.011 each) for cheaper.

Usage (from backend/, venv activated):
    python -m scripts.backfill_pool_images
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from api.image_gen import _generate_to_disk, build_prompt  # noqa: E402


CONCURRENCY = int(os.getenv("IMAGE_GEN_CONCURRENCY", "3"))


async def _do_one(idx: int, total: int, public_id: str, name: str, sem: asyncio.Semaphore, dsn: str) -> bool:
    async with sem:
        t0 = time.monotonic()
        path = await _generate_to_disk(f"pool_{public_id}", build_prompt(name))
        duration = time.monotonic() - t0
        if not path:
            print(f"[{idx:2d}/{total}] FAIL ({duration:.1f}s): {name[:60]}")
            return False
        # Single-connection update — these are cheap and we don't want a long-
        # lived pool for a one-off script. asyncpg.connect creates a per-call
        # connection.
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(
                "UPDATE hearth.public_recipes SET image_path = $1 WHERE id = $2::uuid",
                path.name, public_id,
            )
            # Back-fill any personal copies that already inherited this pool
            # row but lacked an image.
            await conn.execute(
                "UPDATE hearth.recipes SET image_path = $1, updated_at = now() "
                "WHERE public_origin_id = $2::uuid AND image_path IS NULL",
                path.name, public_id,
            )
        finally:
            await conn.close()
        print(f"[{idx:2d}/{total}] ({duration:5.1f}s) {name[:70]}")
        return True


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT id::text AS id, name FROM hearth.public_recipes "
            "WHERE image_path IS NULL ORDER BY created_at",
        )
    finally:
        await conn.close()

    if not rows:
        print("Nothing to backfill — every pool recipe has an image.")
        return

    print(f"Backfilling {len(rows)} pool images (concurrency={CONCURRENCY})")
    print("-" * 80)
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [_do_one(i + 1, len(rows), r["id"], r["name"], sem, dsn) for i, r in enumerate(rows)]
    overall = time.monotonic()
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - overall
    ok = sum(1 for r in results if r)
    print("-" * 80)
    print(f"Done in {elapsed:.0f}s — {ok}/{len(rows)} images saved.")


if __name__ == "__main__":
    asyncio.run(main())
