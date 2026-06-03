"""Recipe image generation via OpenAI gpt-image-1.

Flow: `schedule_image` / `schedule_pool_image` kick off a background task that
calls OpenAI, decodes the base64 image bytes to disk, and writes the
`image_path` back onto the recipe row in Postgres. The endpoint caller never
waits on the image — the UI shows a placeholder until the file exists and
refetches once `recipes` data changes.

Image-sharing policy: when a recipe gets mirrored into hearth.public_recipes,
we schedule a SINGLE pool image. Personal copies (in hearth.recipes) inherit
that path either through copy_to_household at like-swipe time or via a
post-generation back-fill that finds personal rows pointing at the same
public_origin_id and patches their image_path.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.db import get_current_household_id, service_tx

log = logging.getLogger("image_gen")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "recipe_images"
IMAGES_DIR.mkdir(exist_ok=True)

router = APIRouter(tags=["recipe-images"])

_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
_IMAGE_SIZE = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024")
_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY", "medium")  # low | medium | high

# A set of distinct, internally-coherent food-photography looks. We pick one per
# recipe (deterministically, by id) instead of using a single template, so the
# calendar grid reads like a real cookbook rather than one photoshoot. Each
# fragment is a complete STYLE (surface, light, angle, color mood, lens) and
# leaves the vessel/plating to _PLATING so the framing suits the dish.
_STYLE_PRESETS = (
    "Shot straight down as a clean flat-lay on a honed white marble slab with "
    "faint grey veining, broad high-key diffused light from a large overhead "
    "scrim, near-shadowless and cool neutral white balance, crisp even focus "
    "across the frame, bright airy editorial mood.",

    "Low raking light from a single window hard at left across a dark riven "
    "slate surface, camera at a moody thirty-degree angle, deep falling shadows "
    "against a bright highlight edge, desaturated cool tones, fast lens with "
    "soft background falloff, dramatic chiaroscuro feel.",

    "Warm golden-hour sun streaming low from behind across a weathered "
    "terracotta surface with a hazy sunlit glow and long soft shadows, "
    "amber-honey color grade with gentle lens flare bloom, low twenty-degree "
    "angle, very shallow depth of field melting the background.",

    "Eye-level hero shot framed low against a soft blurred warm-beige linen "
    "backdrop, golden directional sidelight from the right with a feathered "
    "highlight, intimate amber-and-cream color mood, 85mm lens at f2 for a "
    "creamy shallow depth of field.",

    "Flat overcast daylight from above-left on a weathered grey zinc tabletop "
    "scuffed with patina, camera at a forty-five-degree three-quarter view, "
    "muted neutral tones with cool steel undertones, medium depth of field, "
    "understated industrial editorial look.",

    "Intimate warm restaurant ambience lit by flickering candle and tungsten "
    "glow from the side over a dark walnut surface, bokeh light spots in a deep "
    "blurred background, cozy amber low-key tones, close forty-five-degree "
    "angle, dreamy shallow depth of field.",

    "Vibrant street-food energy on a scuffed stainless-steel counter, mixed "
    "warm tungsten glow with a cool colored neon backlight, candid eye-level "
    "angle, saturated punchy contrast and reflective highlights, fast lens with "
    "a busy blurred night backdrop.",
)

_PLATING = (
    "Plate and garnish the dish in the vessel that best suits it — the right "
    "bowl, plate, board, or glass — with natural, restaurant-quality styling "
    "and a crop that frames the food as the hero while leaving a little "
    "breathing room."
)

_CONSTRAINTS = (
    "Realistic appetizing food photography with the food as the clear hero, no "
    "text, watermarks, or logos, and no people or hands."
)


def _preset_for(seed: str) -> str:
    """Deterministically pick a style preset from a STABLE hash of the seed, so a
    given recipe always gets the same look (stable across regenerations) while
    different recipes spread across the full set. (Python's built-in hash() is
    salted per process, so we use md5 for stability.)"""
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    return _STYLE_PRESETS[h % len(_STYLE_PRESETS)]


def build_prompt(name: str, seed: str | None = None) -> str:
    """Compose the image prompt: the dish, a dish-appropriate plating note, a
    per-recipe style preset, and the global constraints. `seed` (the recipe/pool
    id) fixes which preset this recipe gets; it falls back to the name."""
    name = name.strip()
    return f"Food photograph of {name}. {_PLATING} {_preset_for(seed or name)} {_CONSTRAINTS}"


async def _generate_via_openai(prompt: str) -> bytes:
    """Call OpenAI images.generate and return raw image bytes (PNG/JPEG)."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = await client.images.generate(
        model=_IMAGE_MODEL,
        prompt=prompt,
        size=_IMAGE_SIZE,
        quality=_IMAGE_QUALITY,
        n=1,
    )
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("OpenAI image response had no data")
    return base64.b64decode(response.data[0].b64_json)


async def _generate_to_disk(image_id: str, prompt: str) -> Path | None:
    """Generate via OpenAI, save to recipe_images/<image_id>.jpg. Retries 3x."""
    out_path = IMAGES_DIR / f"{image_id}.jpg"
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            data = await _generate_via_openai(prompt)
            if len(data) < 1000:
                raise RuntimeError(f"suspiciously small response ({len(data)} bytes)")
            out_path.write_bytes(data)
            log.info("[image_gen] generated %s on attempt %d (%d bytes)",
                     image_id, attempt + 1, len(data))
            return out_path
        except Exception as e:
            last_err = e
            log.warning("[image_gen] attempt %d for %s failed: %s", attempt + 1, image_id, e)
            await asyncio.sleep(2 ** attempt * 2)
    log.error("[image_gen] GAVE UP for %s after 3 attempts: %s", image_id, last_err)
    return None


# ---------------------------------------------------------------------------
# Personal-recipe image (legacy path; still used for direct edits)
# ---------------------------------------------------------------------------


async def generate_recipe_image(recipe_id: str, name: str, household_id: str) -> None:
    """Background entry: generate an image for a personal recipe row."""
    log.info("[image_gen] starting personal image for %s (%s)", recipe_id, name[:50])
    try:
        path = await _generate_to_disk(recipe_id, build_prompt(name, recipe_id))
        if not path:
            return
        async with service_tx() as conn:
            await conn.execute(
                "UPDATE hearth.recipes SET image_path = $1, updated_at = now() "
                "WHERE id = $2::uuid AND household_id = $3::uuid",
                path.name, recipe_id, household_id,
            )
    except Exception:
        log.exception("[image_gen] unexpected failure for personal recipe %s", recipe_id)


# ---------------------------------------------------------------------------
# Shared pool image (Explore cards, starter library)
# ---------------------------------------------------------------------------


async def generate_pool_image(public_recipe_id: str, name: str) -> None:
    """Generate a shared image for a hearth.public_recipes row. Once saved,
    we also back-fill the image_path on any personal copies that already
    inherited from this pool entry but lacked an image at copy time."""
    log.info("[image_gen] starting pool image for %s (%s)", public_recipe_id, name[:50])
    try:
        seed = f"pool_{public_recipe_id}"
        path = await _generate_to_disk(seed, build_prompt(name, seed))
        if not path:
            return
        async with service_tx() as conn:
            await conn.execute(
                "UPDATE hearth.public_recipes SET image_path = $1 WHERE id = $2::uuid",
                path.name, public_recipe_id,
            )
            await conn.execute(
                "UPDATE hearth.recipes SET image_path = $1, updated_at = now() "
                "WHERE public_origin_id = $2::uuid AND image_path IS NULL",
                path.name, public_recipe_id,
            )
    except Exception:
        log.exception("[image_gen] unexpected failure for pool recipe %s", public_recipe_id)


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


def schedule_image(recipe_id: str, name: str, household_id: str) -> None:
    """Fire-and-forget personal-recipe image generation."""
    _spawn(generate_recipe_image(recipe_id, name, household_id))


def schedule_pool_image(public_recipe_id: str, name: str) -> None:
    """Fire-and-forget shared pool-recipe image generation."""
    _spawn(generate_pool_image(public_recipe_id, name))


# ============================================================
# Endpoints
# ============================================================


@router.get("/recipe-images/{filename}")
def serve_recipe_image(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Bad filename")
    path = IMAGES_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/recipes/{recipe_id}/image/regenerate")
async def regenerate_image(
    recipe_id: str,
    household_id: str = Depends(get_current_household_id),
):
    async with service_tx() as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid AND household_id = $2::uuid",
            recipe_id, household_id,
        )
    if row is None:
        raise HTTPException(404, "Recipe not found")
    await generate_recipe_image(recipe_id, row["name"], household_id)
    return {"status": "ok"}
