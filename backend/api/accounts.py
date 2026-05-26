"""GDPR endpoints: self-serve account deletion + data export.

DELETE /accounts/me  — right to erasure (Art. 17). Drops the user from
                       auth.users; cascades take care of household_members
                       and any household where the user was the last member.
                       Refuses if the user is an owner with co-members
                       (transfer ownership first).

GET /accounts/me/export — right to portability (Art. 20). Returns a JSON
                          bundle of every household-scoped resource the
                          user can read under RLS.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from supabase import Client, create_client

from api.auth import CurrentUser, get_current_user
from api.db import service_tx, user_tx


router = APIRouter(tags=["accounts"])


_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_admin_client: Client | None = None


def _admin() -> Client:
    """Lazy-init the Supabase admin client (service role) for auth.admin calls."""
    global _admin_client
    if _admin_client is None:
        if not _SUPABASE_URL or not _SUPABASE_SERVICE_ROLE_KEY:
            raise HTTPException(
                status_code=500,
                detail="SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured",
            )
        _admin_client = create_client(_SUPABASE_URL, _SUPABASE_SERVICE_ROLE_KEY)
    return _admin_client


@router.delete("/accounts/me", status_code=204)
async def delete_account(user: CurrentUser = Depends(get_current_user)) -> Response:
    """Delete the user's account (GDPR right to erasure).

    If the user owns a household with other members, they must transfer
    ownership first. Otherwise the cascade chain handles cleanup:
    auth.users -> household_members (CASCADE) -> if household is now empty,
    we delete it manually so the hearth.* resources cascade away too.
    """
    async with service_tx() as conn:
        membership = await conn.fetchrow(
            """
            SELECT household_id, role
            FROM public.household_members
            WHERE user_id = $1::uuid
            """,
            user.user_id,
        )

        if membership is not None and membership["role"] == "owner":
            other_member_count = await conn.fetchval(
                """
                SELECT count(*) FROM public.household_members
                WHERE household_id = $1::uuid AND user_id != $2::uuid
                """,
                membership["household_id"], user.user_id,
            )
            if other_member_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "You own a household with other members. Transfer ownership "
                        "(or remove the other members) before deleting your account."
                    ),
                )

        # If the user is the last member of a household, capture its id so
        # we can delete the household row after auth.users is gone.
        household_to_cleanup = None
        if membership is not None:
            remaining_others = await conn.fetchval(
                """
                SELECT count(*) FROM public.household_members
                WHERE household_id = $1::uuid AND user_id != $2::uuid
                """,
                membership["household_id"], user.user_id,
            )
            if remaining_others == 0:
                household_to_cleanup = membership["household_id"]

    # Drop from auth.users -- cascades household_members and credit_ledger,
    # invites created by the user, etc. (everything FK'd ON DELETE CASCADE
    # to auth.users(id)).
    try:
        _admin().auth.admin.delete_user(user.user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete auth user: {e}") from e

    # Clean up an orphan household (last-member-leaves).
    if household_to_cleanup is not None:
        async with service_tx() as conn:
            await conn.execute(
                "DELETE FROM public.households WHERE id = $1::uuid",
                household_to_cleanup,
            )

    return Response(status_code=204)


@router.get("/accounts/me/export")
async def export_account(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Return a JSON bundle of every household-scoped resource the user
    can read (GDPR right to data portability)."""
    bundle: dict[str, Any] = {
        "exported_at": None,
        "user": {"id": user.user_id, "email": user.email},
        "household": None,
        "members": [],
        "invites": [],
        "recipes": [],
        "recipe_ingredients": [],
        "meal_plans": [],
        "meal_plan_entries": [],
        "household_profile": None,
        "store_layout": [],
        "shopping_list_template": [],
        "chat_sessions": [],
        "chat_messages": [],
        "pending_actions": [],
        "credit_ledger": [],
    }

    async with user_tx(user) as conn:
        # exported_at as set by Postgres for traceability
        bundle["exported_at"] = (await conn.fetchval("SELECT now()::text"))

        household_row = await conn.fetchrow(
            """
            SELECT h.id, h.name, h.created_at, h.updated_at
            FROM public.households h
            JOIN public.household_members hm ON hm.household_id = h.id
            WHERE hm.user_id = $1::uuid
            LIMIT 1
            """,
            user.user_id,
        )
        if household_row is None:
            return bundle

        bundle["household"] = dict(household_row)

        # RLS scopes every subsequent query automatically to this user's
        # household (since they're in only one).
        bundle["members"]                = [dict(r) for r in await conn.fetch("SELECT * FROM public.household_members")]
        bundle["invites"]                = [dict(r) for r in await conn.fetch("SELECT * FROM public.household_invites")]
        bundle["recipes"]                = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.recipes")]
        bundle["recipe_ingredients"]     = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.recipe_ingredients")]
        bundle["meal_plans"]             = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.meal_plans")]
        bundle["meal_plan_entries"]      = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.meal_plan_entries")]
        bundle["store_layout"]           = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.store_layout")]
        bundle["shopping_list_template"] = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.shopping_list_template")]
        bundle["chat_sessions"]          = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.chat_sessions")]
        bundle["chat_messages"]          = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.chat_messages")]
        bundle["pending_actions"]        = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.pending_actions")]
        bundle["credit_ledger"]          = [dict(r) for r in await conn.fetch("SELECT * FROM hearth.credit_ledger")]

        prof = await conn.fetchrow("SELECT * FROM hearth.household_profiles LIMIT 1")
        if prof is not None:
            bundle["household_profile"] = dict(prof)

    # asyncpg returns UUID / datetime / Decimal objects that JSON can't
    # serialise directly. Walk and coerce.
    def _coerce(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: _coerce(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_coerce(x) for x in v]
        if hasattr(v, "isoformat"):
            return v.isoformat()
        # UUID, Decimal, etc. -> str
        if v.__class__.__module__ == "uuid" or v.__class__.__name__ == "Decimal":
            return str(v)
        return v

    return _coerce(bundle)
