"""Per-ingredient icon images via OpenAI gpt-image-1.

Each ingredient gets ONE small image, generated lazily the first time it's used
and cached globally on disk by fdc_id (ingredient_images/<fdc_id>.png) — shared
across every recipe and household. Icons are 'low' quality (≈ $0.011 each) since
they're tiny thumbnails. The frontend shows a category fallback icon until the
file exists, then the image on the next load.

Trigger: the frontend POSTs the fdc_ids it's about to show to /ingredient-images/
ensure; we generate only the missing ones, in the background, capped per call.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.auth import CurrentUser, get_current_user
from api.db import service_tx

log = logging.getLogger("ingredient_images")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "ingredient_images"
IMAGES_DIR.mkdir(exist_ok=True)

router = APIRouter(tags=["ingredient-images"])

_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
# Thumbnails are deliberately cheap: 'low' 1024² ≈ $0.011 each.
_QUALITY = os.getenv("OPENAI_INGREDIENT_IMAGE_QUALITY", "low")
# Cap how many one ensure() call may kick off, so a big recipe (or a fresh
# library) can't fan out into a huge surprise bill — it catches up over loads.
_MAX_PER_REQUEST = 12
# gpt-image-1 image RPM is low (≈5/min on tier-1 orgs), so keep concurrency
# modest and let _generate back off generously on 429s.
_CONCURRENCY = 2


def _path(fdc_id: int) -> Path:
    return IMAGES_DIR / f"{fdc_id}.png"


def downscale(data: bytes, max_px: int = 192) -> bytes:
    """Shrink a generated 1024² image to a thumbnail (these render at ~34px), so
    each icon is a few KB instead of ~1 MB. Falls back to the original on error."""
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(data))
        img.thumbnail((max_px, max_px))
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        log.warning("[ingredient_images] downscale failed (%s) — keeping original", e)
        return data


def build_prompt(name: str) -> str:
    return (
        f"A minimalist flat illustrated icon of {name.strip()}, a single raw food "
        "ingredient, centered, simple clean rounded shapes, soft warm palette, "
        "gentle shadow, on a plain off-white background. No text, no labels, no "
        "packaging, no hands."
    )


async def _generate(fdc_id: int, name: str) -> bool:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    for attempt in range(6):
        try:
            resp = await client.images.generate(
                model=_MODEL, prompt=build_prompt(name),
                size="1024x1024", quality=_QUALITY, n=1,
            )
            b64 = resp.data[0].b64_json if resp.data else None
            if not b64:
                raise RuntimeError("no image data")
            data = base64.b64decode(b64)
            if len(data) < 1000:
                raise RuntimeError(f"suspiciously small ({len(data)} bytes)")
            _path(fdc_id).write_bytes(downscale(data))
            log.info("[ingredient_images] %s '%s' ok (%d bytes)", fdc_id, name[:40], len(data))
            return True
        except Exception as e:
            # Image RPM is low; a 429 says "try again in ~12s", so back off well
            # past that window (16s, 24s, 32s, …) rather than retrying too soon.
            wait = 8 * (attempt + 2)
            log.warning("[ingredient_images] %s attempt %d failed (%s) — wait %ds",
                        fdc_id, attempt + 1, e, wait)
            await asyncio.sleep(wait)
    log.error("[ingredient_images] gave up on %s", fdc_id)
    return False


async def resolve_names(fdc_ids: list[int]) -> dict[int, str]:
    """fdc_id -> a human name (curated simple_name preferred, USDA description else)."""
    if not fdc_ids:
        return {}
    async with service_tx() as conn:
        rows = await conn.fetch(
            "SELECT u.fdc_id, COALESCE(p.simple_name, u.description) AS name "
            "FROM hearth.usda_ingredients u "
            "LEFT JOIN hearth.pantry_ingredients p ON p.fdc_id = u.fdc_id "
            "WHERE u.fdc_id = ANY($1::int[])",
            list(fdc_ids),
        )
    return {int(r["fdc_id"]): str(r["name"]) for r in rows}


async def generate_missing(fdc_ids: list[int]) -> int:
    """Generate (concurrency-limited) any of these ingredients that lack a file.
    Returns the number generated. Used by both the ensure endpoint and the
    one-shot backfill script."""
    missing = [f for f in dict.fromkeys(fdc_ids) if not _path(f).exists()]
    if not missing:
        return 0
    names = await resolve_names(missing)
    sem = asyncio.Semaphore(_CONCURRENCY)
    done = 0

    async def one(fid: int):
        nonlocal done
        async with sem:
            if _path(fid).exists():
                return
            if await _generate(fid, names.get(fid, f"food ingredient {fid}")):
                done += 1

    await asyncio.gather(*(one(f) for f in missing))
    return done


_BG_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    task = loop.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


# ============================================================
# Endpoints
# ============================================================


class EnsureBody(BaseModel):
    fdc_ids: list[int]


@router.post("/ingredient-images/ensure")
async def ensure_images(
    body: EnsureBody,
    user: CurrentUser = Depends(get_current_user),
):
    """Kick off background generation for any of these ingredients missing an
    image (capped per call). Returns immediately; images appear on a later load."""
    if not os.getenv("OPENAI_API_KEY"):
        return {"queued": 0}
    pending = [f for f in dict.fromkeys(body.fdc_ids) if not _path(f).exists()][:_MAX_PER_REQUEST]
    if pending:
        _spawn(generate_missing(pending))
    return {"queued": len(pending)}


@router.get("/ingredient-images/{fdc_id}.png")
def serve_ingredient_image(fdc_id: int):
    path = _path(fdc_id)
    if not path.exists():
        raise HTTPException(404, "Not found")
    # Immutable (one image per ingredient) — cache hard so repeat views are free.
    return FileResponse(
        path, media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
