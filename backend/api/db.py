"""Async Postgres pool + RLS-aware transaction contexts + auth helpers."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncpg
from fastapi import Depends, HTTPException

from api.auth import CurrentUser, get_current_user


DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool: Optional[asyncpg.Pool] = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    """Per-connection setup: register a JSONB codec so reads return dicts/lists
    directly and writes accept Python objects. Without this, asyncpg treats
    jsonb columns as opaque text and every call site has to json.dumps/loads."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_pool() -> None:
    """Create the global connection pool. Call once at app startup."""
    global _pool
    if _pool is not None:
        return
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        statement_cache_size=0,  # transaction-pooler-friendly
        init=_init_conn,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized; check FastAPI lifespan")
    return _pool


@asynccontextmanager
async def user_tx(user: CurrentUser) -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection inside a transaction configured for `user`.

    Inside the yielded block, every query runs as the `authenticated` role
    with auth.uid() returning the JWT sub. SET LOCAL keeps the state scoped
    to this transaction only, so Supabase's transaction-mode pooler reuses
    the connection cleanly between requests.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL role = 'authenticated'")
            await conn.execute(
                "SELECT set_config('request.jwt.claims', $1, true)",
                json.dumps(user.claims),
            )
            yield conn


@asynccontextmanager
async def service_tx() -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection inside a service-role transaction (bypasses RLS).

    Use only for operations that cross multiple rows under invariants the
    API itself owns (create household + insert owner-member atomically,
    validate + consume invite token, etc).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL role = 'service_role'")
            yield conn


# ============================================================================
# FastAPI dependencies
# ============================================================================

async def get_current_household_id(
    user: CurrentUser = Depends(get_current_user),
) -> str:
    """Resolve the authenticated user's household_id (UUID string).

    Used as a FastAPI dependency on every household-scoped endpoint. All
    tenant tables now live in Postgres + RLS so we just look up the
    membership row and return the id."""
    pool = get_pool()
    async with pool.acquire() as conn:
        hid = await conn.fetchval(
            """
            SELECT household_id::text
            FROM public.household_members
            WHERE user_id = $1::uuid
            LIMIT 1
            """,
            user.user_id,
        )
    if hid is None:
        raise HTTPException(
            status_code=400,
            detail="You are not a member of any household. Create or join one first.",
        )
    return hid
