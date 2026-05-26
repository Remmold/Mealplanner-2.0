"""Household + membership + invite endpoints.

These power the onboarding flow: sign in -> create or join a household ->
get on with cooking.

Authorization model:
- GET /me                                       — any authenticated user
- POST /households                              — any authenticated user with no household
- POST /households/join/{token}                 — any authenticated user with no household
- POST /households/{id}/invites                 — any member
- DELETE /households/{id}/invites/{token}       — any member (revoke)
- DELETE /households/{id}/members/{user_id}     — self (leave) or owner (kick)

Inserts that span multiple rows under one invariant (create household +
owner-member, consume invite + insert member) use service_tx so the API
owns the atomicity.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import CurrentUser, get_current_user
from api.db import service_tx, user_tx


router = APIRouter(tags=["households"])


# ---- Models -----------------------------------------------------------------

class HouseholdInfo(BaseModel):
    id: str
    name: str
    role: str          # 'owner' | 'member'
    locale: str        # 'en' | 'sv'
    member_count: int


class MeResponse(BaseModel):
    user_id: str
    email: Optional[str]
    household: Optional[HouseholdInfo]


class CreateHouseholdRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    locale: str = Field("en", pattern="^(en|sv)$")


class JoinHouseholdRequest(BaseModel):
    locale: str = Field("en", pattern="^(en|sv)$")


class InviteResponse(BaseModel):
    token: str
    expires_at: datetime
    join_url: str


# ---- Helpers ----------------------------------------------------------------

def _new_invite_token() -> str:
    # 32 bytes of URL-safe random => ~43 chars, ~256 bits of entropy.
    return secrets.token_urlsafe(32)


def _public_base_url() -> str:
    return os.environ.get("HEARTH_PUBLIC_URL", "http://localhost:5173").rstrip("/")


def _join_url(token: str) -> str:
    return f"{_public_base_url()}/join/{token}"


# ---- Endpoints --------------------------------------------------------------

@router.get("/me", response_model=MeResponse)
async def get_me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the current user's identity + household membership (if any)."""
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            """
            SELECT
                hm.household_id,
                h.name,
                hm.role,
                hm.locale,
                (SELECT count(*)
                 FROM public.household_members
                 WHERE household_id = h.id)::int AS member_count
            FROM public.household_members hm
            JOIN public.households h ON h.id = hm.household_id
            WHERE hm.user_id = $1::uuid
            """,
            user.user_id,
        )
    household = None
    if row is not None:
        household = HouseholdInfo(
            id=str(row["household_id"]),
            name=row["name"],
            role=row["role"],
            locale=row["locale"],
            member_count=row["member_count"],
        )
    return MeResponse(user_id=user.user_id, email=user.email, household=household)


@router.post("/households", response_model=HouseholdInfo, status_code=201)
async def create_household(
    body: CreateHouseholdRequest,
    user: CurrentUser = Depends(get_current_user),
) -> HouseholdInfo:
    """Create a household and insert the caller as its owner-member.

    Atomic via service-role transaction. Refuses if the user is already a
    member of any household (one-household-per-user invariant).
    """
    async with service_tx() as conn:
        already = await conn.fetchval(
            "SELECT household_id FROM public.household_members WHERE user_id = $1::uuid",
            user.user_id,
        )
        if already is not None:
            raise HTTPException(
                status_code=409,
                detail="You are already a member of a household. Leave it before creating a new one.",
            )

        row = await conn.fetchrow(
            "INSERT INTO public.households (name) VALUES ($1) RETURNING id, name",
            body.name,
        )
        household_id = row["id"]
        await conn.execute(
            """
            INSERT INTO public.household_members (household_id, user_id, role, locale)
            VALUES ($1, $2::uuid, 'owner', $3)
            """,
            household_id, user.user_id, body.locale,
        )

    return HouseholdInfo(
        id=str(household_id),
        name=row["name"],
        role="owner",
        locale=body.locale,
        member_count=1,
    )


@router.post("/households/join/{token}", response_model=HouseholdInfo)
async def join_household(
    token: str,
    body: JoinHouseholdRequest,
    user: CurrentUser = Depends(get_current_user),
) -> HouseholdInfo:
    """Consume an invite token and join the household it points to.

    Atomic via service-role: validate -> mark used -> insert membership in
    one transaction so partial failures can't leave half-states.
    """
    async with service_tx() as conn:
        invite = await conn.fetchrow(
            """
            SELECT household_id, expires_at, used_at
            FROM public.household_invites
            WHERE token = $1
            FOR UPDATE
            """,
            token,
        )
        if invite is None:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite["used_at"] is not None:
            raise HTTPException(status_code=410, detail="Invite already used")
        if invite["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Invite expired")

        already = await conn.fetchval(
            "SELECT household_id FROM public.household_members WHERE user_id = $1::uuid",
            user.user_id,
        )
        if already is not None:
            raise HTTPException(
                status_code=409,
                detail="You are already a member of a household. Leave it before joining another.",
            )

        await conn.execute(
            "UPDATE public.household_invites SET used_at = now(), used_by = $1::uuid WHERE token = $2",
            user.user_id, token,
        )
        await conn.execute(
            """
            INSERT INTO public.household_members (household_id, user_id, role, locale)
            VALUES ($1, $2::uuid, 'member', $3)
            """,
            invite["household_id"], user.user_id, body.locale,
        )

        h = await conn.fetchrow(
            """
            SELECT name,
                   (SELECT count(*) FROM public.household_members
                    WHERE household_id = $1)::int AS member_count
            FROM public.households WHERE id = $1
            """,
            invite["household_id"],
        )

    return HouseholdInfo(
        id=str(invite["household_id"]),
        name=h["name"],
        role="member",
        locale=body.locale,
        member_count=h["member_count"],
    )


@router.post("/households/{household_id}/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    household_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> InviteResponse:
    """Generate a tokenized invite. Any member can issue invites."""
    token = _new_invite_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    async with user_tx(user) as conn:
        try:
            await conn.execute(
                """
                INSERT INTO public.household_invites
                    (token, household_id, created_by, expires_at)
                VALUES ($1, $2::uuid, $3::uuid, $4)
                """,
                token, household_id, user.user_id, expires_at,
            )
        except Exception as e:
            # RLS rejects insert if user is not a member of this household.
            raise HTTPException(
                status_code=403,
                detail="Cannot create invite for this household",
            ) from e

    return InviteResponse(token=token, expires_at=expires_at, join_url=_join_url(token))


@router.delete("/households/{household_id}/invites/{token}", status_code=204)
async def revoke_invite(
    household_id: str,
    token: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Revoke an unused invite. Any member can revoke."""
    async with user_tx(user) as conn:
        result = await conn.execute(
            """
            DELETE FROM public.household_invites
            WHERE token = $1 AND household_id = $2::uuid AND used_at IS NULL
            """,
            token, household_id,
        )
    # asyncpg returns the command tag, e.g. "DELETE 1"
    if result.endswith(" 0"):
        raise HTTPException(status_code=404, detail="Invite not found or already used")


@router.delete("/households/{household_id}/members/{member_user_id}", status_code=204)
async def remove_member(
    household_id: str,
    member_user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Remove a member from a household.

    Allowed actions:
      - leave: caller removes themselves (regardless of role)
      - kick:  caller is owner and removes another member

    Special cases:
      - An owner trying to leave while other members remain must transfer
        ownership first (returns 409). The schema's partial unique index on
        owners would otherwise refuse to promote another member silently.
      - When the last member leaves, the household row is deleted too,
        cascading the hearth.* tenant resources.
    """
    async with service_tx() as conn:
        caller = await conn.fetchrow(
            """
            SELECT role FROM public.household_members
            WHERE household_id = $1::uuid AND user_id = $2::uuid
            """,
            household_id, user.user_id,
        )
        if caller is None:
            raise HTTPException(status_code=404, detail="Not a member of that household")

        is_self = (user.user_id == member_user_id)
        is_owner = (caller["role"] == "owner")
        if not is_self and not is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can remove other members")

        if is_self and is_owner:
            other_member_count = await conn.fetchval(
                """
                SELECT count(*) FROM public.household_members
                WHERE household_id = $1::uuid AND user_id != $2::uuid
                """,
                household_id, user.user_id,
            )
            if other_member_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Transfer ownership before leaving (other members exist).",
                )

        result = await conn.execute(
            """
            DELETE FROM public.household_members
            WHERE household_id = $1::uuid AND user_id = $2::uuid
            """,
            household_id, member_user_id,
        )
        if result.endswith(" 0"):
            raise HTTPException(status_code=404, detail="Target user is not a member")

        remaining = await conn.fetchval(
            "SELECT count(*) FROM public.household_members WHERE household_id = $1::uuid",
            household_id,
        )
        if remaining == 0:
            await conn.execute("DELETE FROM public.households WHERE id = $1::uuid", household_id)
