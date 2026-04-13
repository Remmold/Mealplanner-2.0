"""Recipe image generation via Pollinations.ai (free, no API key).

Flow: `generate_recipe_image(recipe_id, name)` kicks off a background task
that hits Pollinations, streams the bytes to disk, and writes `image_path`
back onto the recipe row. The endpoint caller never waits on the image —
the UI polls/refreshes and shows a placeholder until the file exists.

Endpoints: mounted under `/recipe-images/*` (static) so `<img src>` works
directly from the frontend.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.recipe_db import DEFAULT_HOUSEHOLD_ID, get_recipe_db

log = logging.getLogger("image_gen")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "recipe_images"
IMAGES_DIR.mkdir(exist_ok=True)

router = APIRouter(tags=["recipe-images"])

# Pollinations endpoint. `model=flux` is the current best free option.
# `nologo=true` removes their watermark. Square keeps layout predictable.
_POLL_URL = "https://image.pollinations.ai/prompt/{prompt}"
_DEFAULT_PARAMS = {
    "width": "768",
    "height": "768",
    "nologo": "true",
    "model": "flux",
    "enhance": "true",
}

_PROMPT_TEMPLATE = (
    "Food photograph of {name}. Overhead 3/4 angle, natural window light, "
    "rustic wooden table, ceramic plate, shallow depth of field, magazine "
    "quality food styling, warm tones, cozy homemade feel. No text, no "
    "utensils obscuring the food, no people, no hands."
)


def build_prompt(name: str) -> str:
    return _PROMPT_TEMPLATE.format(name=name.strip())


async def _fetch_and_save(recipe_id: str, prompt: str) -> Path | None:
    """Fetch from Pollinations and write to disk. Returns the path on success.

    Pollinations is community-run and occasionally slow or flaky — we retry
    a couple of times with backoff before giving up."""
    out_path = IMAGES_DIR / f"{recipe_id}.jpg"
    encoded = urllib.parse.quote(prompt, safe="")
    url = _POLL_URL.format(prompt=encoded)

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                r = await client.get(url, params=_DEFAULT_PARAMS)
                r.raise_for_status()
                if not r.content or len(r.content) < 1000:
                    raise RuntimeError(f"suspiciously small response ({len(r.content)} bytes)")
                out_path.write_bytes(r.content)
            log.info("[image_gen] fetched %s on attempt %d (%d bytes)",
                     recipe_id, attempt + 1, len(r.content))
            return out_path
        except Exception as e:
            last_err = e
            log.warning("[image_gen] attempt %d for %s failed: %s", attempt + 1, recipe_id, e)
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
    log.error("[image_gen] GAVE UP for %s after 3 attempts: %s", recipe_id, last_err)
    return None


async def generate_recipe_image(recipe_id: str, name: str, household_id: str = DEFAULT_HOUSEHOLD_ID) -> None:
    """Background entry: generate an image for `recipe_id` and persist its path."""
    log.info("[image_gen] starting for %s (%s)", recipe_id, name[:50])
    try:
        prompt = build_prompt(name)
        path = await _fetch_and_save(recipe_id, prompt)
        if not path:
            return
        rel = path.name
        with get_recipe_db() as conn:
            conn.execute(
                "UPDATE recipes SET image_path = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND household_id = ?",
                [rel, recipe_id, household_id],
            )
        log.info("[image_gen] saved %s for recipe %s", rel, recipe_id)
    except Exception:
        # Log full traceback — without this, tasks scheduled via create_task
        # silently drop their errors.
        log.exception("[image_gen] unexpected failure for %s", recipe_id)


# Strong refs keep background tasks alive until done; without this, the asyncio
# event loop can garbage-collect a task before it runs (well-known gotcha).
_BG_TASKS: set[asyncio.Task] = set()


def schedule_image(recipe_id: str, name: str, household_id: str = DEFAULT_HOUSEHOLD_ID) -> None:
    """Fire-and-forget scheduling. Safe to call from any async context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from a non-async context — run inline sync.
        asyncio.run(generate_recipe_image(recipe_id, name, household_id))
        return
    task = loop.create_task(generate_recipe_image(recipe_id, name, household_id))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    log.info("[image_gen] scheduled task for %s (%d background tasks active)",
             recipe_id, len(_BG_TASKS))


# ============================================================
# Endpoints
# ============================================================


@router.get("/recipe-images/{filename}")
def serve_recipe_image(filename: str):
    # Defensive: no path traversal.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Bad filename")
    path = IMAGES_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/recipes/{recipe_id}/image/regenerate")
async def regenerate_image(recipe_id: str, household_id: str = DEFAULT_HOUSEHOLD_ID):
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
            [recipe_id, household_id],
        ).fetchone()
    if not row:
        raise HTTPException(404, "Recipe not found")
    # Run inline so the caller sees the new image immediately.
    await generate_recipe_image(recipe_id, row["name"], household_id)
    return {"status": "ok"}
