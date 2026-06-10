"""Backfill images for amcoff recipes in the public pool.

Fetches each recipe's source URL (ICA.se), extracts the og:image / schema.org
Recipe image, downloads the JPG/PNG, saves to backend/recipe_images/, and
updates hearth.public_recipes.image_path.

og:image is a public, opt-in meta tag every modern site exposes precisely so
external sites can embed preview images (Facebook/Twitter cards, etc.) — this
is the legitimate path, not screen-scraping.

Idempotent: rows that already have image_path are skipped. Concurrency is
deliberately low (3 parallel) so ICA's CDN isn't hammered. Polite User-Agent
identifies the project for any rate-limit appeals."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import asyncpg
import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

IMAGES_DIR = BACKEND / "recipe_images"
IMAGES_DIR.mkdir(exist_ok=True)

SEED_PATH = BACKEND / "seeds" / "amcoff_pool_seed.json"
CONCURRENCY = 3
PER_REQUEST_TIMEOUT = 15

USER_AGENT = "Mealplanner/0.1 (dev pilot; contact via project repo)"

# amcoff stores ICA URLs as relative paths like '/recept/foo-12345/'.
ICA_BASE = "https://www.ica.se"


def _absolute_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return ICA_BASE + url
    return ICA_BASE + "/" + url

# Match the og:image meta tag in HTML. Tolerant of attribute order + quote style.
OG_IMAGE_RE = re.compile(
    r'<meta\s+(?:[^>]*\s+)?(?:property|name)\s*=\s*["\']og:image["\'][^>]*'
    r'content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Fallback: schema.org Recipe JSON-LD with "image" field. Picks first URL.
JSON_LD_IMAGE_RE = re.compile(
    r'"image"\s*:\s*(?:"([^"]+)"|\[\s*"([^"]+)"|\{\s*"@type"\s*:\s*"ImageObject"[^}]*"url"\s*:\s*"([^"]+)")',
    re.IGNORECASE,
)


def _extract_image_url(html: str) -> str | None:
    m = OG_IMAGE_RE.search(html)
    if m:
        return m.group(1)
    m = JSON_LD_IMAGE_RE.search(html)
    if m:
        return m.group(1) or m.group(2) or m.group(3)
    return None


def _ext_from_content_type(ct: str) -> str:
    ct = (ct or "").lower().split(";")[0].strip()
    if "jpeg" in ct or "jpg" in ct:
        return "jpg"
    if "png" in ct:
        return "png"
    if "webp" in ct:
        return "webp"
    return "jpg"


async def _process_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    public_id: str,
    name: str,
    source_url: str,
    dsn: str,
) -> str:
    """Returns 'ok' / 'skip' / 'no_url' / 'no_image' / 'error'."""
    async with sem:
        # Already downloaded?
        for ext in ("jpg", "png", "webp"):
            existing = IMAGES_DIR / f"pool_{public_id}.{ext}"
            if existing.exists():
                # Also make sure DB knows about it (in case earlier crash)
                conn = await asyncpg.connect(dsn, statement_cache_size=0)
                try:
                    await conn.execute(
                        "UPDATE hearth.public_recipes SET image_path = $1 "
                        "WHERE id = $2::uuid AND image_path IS NULL",
                        existing.name, public_id,
                    )
                finally:
                    await conn.close()
                return "skip"

        if not source_url:
            return "no_url"

        abs_source_url = _absolute_url(source_url)
        # Fetch HTML
        try:
            r = await client.get(abs_source_url, follow_redirects=True)
            r.raise_for_status()
        except Exception as e:
            print(f"  ERROR fetch html for {name[:50]}: {e}")
            return "error"

        img_url = _extract_image_url(r.text)
        if not img_url:
            return "no_image"

        # Resolve relative URLs (rare for og:image but safe)
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            from urllib.parse import urljoin
            img_url = urljoin(abs_source_url, img_url)

        # Download image
        try:
            r = await client.get(img_url)
            r.raise_for_status()
        except Exception as e:
            print(f"  ERROR fetch img for {name[:50]}: {e}")
            return "error"

        if len(r.content) < 1000:
            print(f"  ERROR tiny img for {name[:50]}: {len(r.content)} bytes")
            return "error"

        ext = _ext_from_content_type(r.headers.get("content-type", ""))
        out_path = IMAGES_DIR / f"pool_{public_id}.{ext}"
        out_path.write_bytes(r.content)

        # Update DB
        conn = await asyncpg.connect(dsn, statement_cache_size=0)
        try:
            await conn.execute(
                "UPDATE hearth.public_recipes SET image_path = $1 WHERE id = $2::uuid",
                out_path.name, public_id,
            )
        finally:
            await conn.close()

        return "ok"


async def main() -> None:
    if not SEED_PATH.exists():
        raise SystemExit(f"Seed file not found: {SEED_PATH}")

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    by_name = {r["name"].lower(): r.get("source_url") for r in seed}
    print(f"Seed has {len(by_name)} recipes with source_urls")

    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            "SELECT id::text AS id, name, image_path FROM hearth.public_recipes "
            "WHERE source = 'starter_corpus' AND image_path IS NULL "
            "AND lower(name) = ANY($1::text[])",
            list(by_name.keys()),
        )
    finally:
        await conn.close()

    if not rows:
        print("Nothing to backfill — every amcoff pool recipe already has an image.")
        return

    print(f"Backfilling {len(rows)} amcoff images (concurrency={CONCURRENCY})")
    print("-" * 70)

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=PER_REQUEST_TIMEOUT,
    ) as client:
        tasks = [
            _process_one(
                client, sem,
                r["id"], r["name"], by_name.get(r["name"].lower(), ""),
                dsn,
            )
            for r in rows
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    stats = {"ok": 0, "skip": 0, "no_url": 0, "no_image": 0, "error": 0}
    for r in results:
        stats[r] = stats.get(r, 0) + 1
    print("-" * 70)
    print(f"Results: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
