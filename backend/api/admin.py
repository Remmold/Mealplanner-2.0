"""Admin-only surface, gated to ADMIN_USER_IDS via require_admin.

English-only by design: it's a personal back-office for data otherwise curated
through one-off scripts, so it can be reviewed and fixed with eyes on it.
Recipe translations live here today; ingredient names + aliases land next.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import catalog_cache
from api.auth import CurrentUser, require_admin
from api.db import get_current_household_id, user_tx

# require_admin on the router → every endpoint below 403s for non-admins.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---- Recipe translations (hearth.recipes.translations jsonb) ----------------

class LocaleContent(BaseModel):
    name: str
    instructions: list[str]


class RecipeTranslationRow(BaseModel):
    id: str
    base_name: str          # the canonical name, shown for reference
    en: LocaleContent
    sv: LocaleContent


@router.get("/recipes", response_model=list[RecipeTranslationRow])
async def list_recipe_translations(
    user: CurrentUser = Depends(require_admin),
    household_id: str = Depends(get_current_household_id),
) -> list[RecipeTranslationRow]:
    """Every recipe in the admin's household with its EN + SV content resolved
    (translations[locale] falling back to the base columns) for side-by-side
    editing."""
    async with user_tx(user) as conn:
        rows = await conn.fetch(
            "SELECT id, name, instructions, translations "
            "FROM hearth.recipes WHERE household_id = $1::uuid ORDER BY name",
            household_id,
        )

    out: list[RecipeTranslationRow] = []
    for r in rows:
        base_name = r["name"]
        base_instr = list(r["instructions"] or [])
        tr = r["translations"] or {}

        def resolve(loc: str) -> LocaleContent:
            entry = tr.get(loc) or {}
            return LocaleContent(
                name=entry.get("name") or base_name,
                instructions=entry.get("instructions") or list(base_instr),
            )

        out.append(RecipeTranslationRow(
            id=str(r["id"]), base_name=base_name, en=resolve("en"), sv=resolve("sv"),
        ))
    return out


class UpdateRecipeTranslations(BaseModel):
    en: LocaleContent
    sv: LocaleContent


@router.put("/recipes/{recipe_id}/translations")
async def update_recipe_translations(
    recipe_id: str,
    body: UpdateRecipeTranslations,
    user: CurrentUser = Depends(require_admin),
    household_id: str = Depends(get_current_household_id),
) -> dict:
    payload = {
        "en": {"name": body.en.name, "instructions": body.en.instructions},
        "sv": {"name": body.sv.name, "instructions": body.sv.instructions},
    }
    async with user_tx(user) as conn:
        res = await conn.execute(
            "UPDATE hearth.recipes SET translations = $1::jsonb "
            "WHERE id = $2::uuid AND household_id = $3::uuid",
            payload, recipe_id, household_id,
        )
    if res.endswith(" 0"):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"ok": True}


# ---- Catalog cache reload (after editing ingredient data) -------------------

@router.post("/reload-catalog")
async def reload_catalog(user: CurrentUser = Depends(require_admin)) -> dict:
    """Re-load the in-memory pantry/alias/unit cache from Postgres without a
    backend restart (the cache is loaded once at startup otherwise)."""
    await catalog_cache.load_all()
    return {"ok": True, "pantry": len(catalog_cache.get_pantry())}
