"""Credit ledger reads/writes for the capped-AI beta.

The ledger lives in Postgres (`hearth.credit_ledger`). Every household gets
a monthly `monthly_grant` row inserted lazily on first AI action of the
month; every AI call inserts a `debit` row; variable-cost ops (the weekly
planner) reserve credits with a `hold` row that is later either replaced
with a `debit` (success) or deleted (refund on failure).

Writes happen as service_role (the ledger has SELECT-only RLS for the
authenticated role) — the API itself is the gatekeeper.

Reads happen through user_tx so RLS scopes balance lookups to the caller's
household automatically.
"""

from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException

from api.db import get_pool, service_tx


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# How many credits each kind of AI action costs.
# Calibrated for gpt-4o-mini (~$0.0015 / recipe-gen-equivalent).
ACTION_COST: dict[str, float] = {
    "recipe_gen": 1.0,
    "chat_turn":  0.5,
    "weekly_plan": 7.0,  # used as a default estimate when planner doesn't know yet
}

# Free monthly grant per household — env-configurable so we can tune in prod
# without a redeploy.
MONTHLY_GRANT = float(os.environ.get("MONTHLY_CREDIT_GRANT", "30"))

# Translation between abstract credits and dollars (for the global kill-switch).
# 1 credit ≈ one gpt-4o-mini recipe generation ≈ $0.0015.
CREDIT_USD_VALUE = float(os.environ.get("CREDIT_USD_VALUE", "0.0015"))

# Global month-to-date USD spend ceiling. Crossing this trips the kill-switch
# and AI endpoints start returning 503.
MONTHLY_BUDGET_USD = float(os.environ.get("MONTHLY_BUDGET_USD", "50"))


# ----------------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------------

class InsufficientCredits(HTTPException):
    """Raised when a household doesn't have enough credits for an AI action."""

    def __init__(self, balance: float, required: float):
        super().__init__(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "balance": round(balance, 1),
                "required": round(required, 1),
                "message": (
                    f"Not enough credits: have {balance:.1f}, need {required:.1f}. "
                    "Free grant resets on the 1st of next month."
                ),
            },
        )


class GlobalBudgetTripped(HTTPException):
    """Raised when month-to-date OpenAI spend has crossed MONTHLY_BUDGET_USD."""

    def __init__(self, spent_usd: float):
        super().__init__(
            status_code=503,
            detail={
                "error": "global_budget_tripped",
                "spent_usd": round(spent_usd, 2),
                "budget_usd": round(MONTHLY_BUDGET_USD, 2),
                "message": (
                    "AI is temporarily unavailable while we catch our breath. "
                    "Manual app keeps working; try again next month or check back later."
                ),
            },
        )


# ----------------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------------

async def _ensure_monthly_grant(conn: asyncpg.Connection, household_id: str) -> None:
    has_grant = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM hearth.credit_ledger
            WHERE household_id = $1::uuid
              AND reason = 'monthly_grant'
              AND created_at >= date_trunc('month', now() at time zone 'UTC')
        )
        """,
        household_id,
    )
    if not has_grant:
        await conn.execute(
            """
            INSERT INTO hearth.credit_ledger (household_id, delta, reason)
            VALUES ($1::uuid, $2, 'monthly_grant')
            """,
            household_id, MONTHLY_GRANT,
        )


async def _balance(conn: asyncpg.Connection, household_id: str) -> float:
    val = await conn.fetchval(
        "SELECT COALESCE(SUM(delta), 0) FROM hearth.credit_ledger "
        "WHERE household_id = $1::uuid",
        household_id,
    )
    return float(val or 0)


async def _month_spend_usd(conn: asyncpg.Connection) -> float:
    """Sum of debits + holds (positive number) across ALL households this calendar month,
    converted to USD."""
    val = await conn.fetchval(
        """
        SELECT COALESCE(-SUM(delta), 0)
        FROM hearth.credit_ledger
        WHERE reason IN ('debit', 'hold')
          AND created_at >= date_trunc('month', now() at time zone 'UTC')
        """
    )
    return float(val or 0) * CREDIT_USD_VALUE


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

async def get_balance_for(household_id: str) -> float:
    """Current credit balance for a household, ensuring the monthly grant has
    been issued. Cheap (one read after a write check)."""
    async with service_tx() as conn:
        await _ensure_monthly_grant(conn, household_id)
        return await _balance(conn, household_id)


async def require_credits(household_id: str, action_type: str, amount: Optional[float] = None) -> float:
    """Gate: raise InsufficientCredits + 402 if the household can't afford the
    action. Also trips the global kill-switch (503) if month-to-date spend is
    over budget. Returns the post-grant balance.
    """
    cost = amount if amount is not None else ACTION_COST.get(action_type, 1.0)

    async with service_tx() as conn:
        # Global kill-switch first — applies to everyone.
        spent_usd = await _month_spend_usd(conn)
        if spent_usd >= MONTHLY_BUDGET_USD:
            raise GlobalBudgetTripped(spent_usd)

        await _ensure_monthly_grant(conn, household_id)
        balance = await _balance(conn, household_id)
        if balance < cost:
            raise InsufficientCredits(balance, cost)
        return balance


async def debit(
    household_id: str,
    action_type: str,
    amount: Optional[float] = None,
    ref_id: Optional[str] = None,
) -> None:
    """Record a finalized AI action. Use after a successful call."""
    cost = amount if amount is not None else ACTION_COST.get(action_type, 1.0)
    async with service_tx() as conn:
        await conn.execute(
            """
            INSERT INTO hearth.credit_ledger (household_id, delta, reason, action_type, ref_id)
            VALUES ($1::uuid, $2, 'debit', $3, $4)
            """,
            household_id,
            -abs(cost),
            action_type,
            UUID(ref_id) if ref_id else None,
        )


async def hold(
    household_id: str,
    action_type: str,
    amount: float,
    ref_id: Optional[str] = None,
) -> str:
    """Reserve credits for a variable-cost op. Returns the hold's id (UUID string).
    Always call either finalize_hold (on success) or release_hold (on failure)."""
    async with service_tx() as conn:
        # Check + place the hold in one tx to avoid races.
        spent_usd = await _month_spend_usd(conn)
        if spent_usd >= MONTHLY_BUDGET_USD:
            raise GlobalBudgetTripped(spent_usd)
        await _ensure_monthly_grant(conn, household_id)
        balance = await _balance(conn, household_id)
        if balance < amount:
            raise InsufficientCredits(balance, amount)

        hold_id = await conn.fetchval(
            """
            INSERT INTO hearth.credit_ledger (household_id, delta, reason, action_type, ref_id)
            VALUES ($1::uuid, $2, 'hold', $3, $4)
            RETURNING id::text
            """,
            household_id,
            -abs(amount),
            action_type,
            UUID(ref_id) if ref_id else None,
        )
    return hold_id


async def release_hold(hold_id: str) -> None:
    """Refund a hold by deleting it. Use on action failure."""
    async with service_tx() as conn:
        await conn.execute(
            "DELETE FROM hearth.credit_ledger WHERE id = $1::uuid AND reason = 'hold'",
            UUID(hold_id),
        )


async def finalize_hold(hold_id: str, actual_amount: float) -> None:
    """Replace a hold with a finalized debit row of `actual_amount`."""
    async with service_tx() as conn:
        row = await conn.fetchrow(
            "SELECT household_id, action_type, ref_id "
            "FROM hearth.credit_ledger WHERE id = $1::uuid",
            UUID(hold_id),
        )
        if row is None:
            return
        await conn.execute(
            "DELETE FROM hearth.credit_ledger WHERE id = $1::uuid",
            UUID(hold_id),
        )
        await conn.execute(
            """
            INSERT INTO hearth.credit_ledger (household_id, delta, reason, action_type, ref_id)
            VALUES ($1::uuid, $2, 'debit', $3, $4)
            """,
            row["household_id"],
            -abs(actual_amount),
            row["action_type"],
            row["ref_id"],
        )
