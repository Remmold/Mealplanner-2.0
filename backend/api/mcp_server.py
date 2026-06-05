"""MCP server exposing the shared tool core over Streamable HTTP.

This is the thesis EXPERIMENT arm: instead of attaching tools in-process, the
chat agent reaches them as an MCP client over HTTP. The server is identity-less
and host-agnostic — it carries no session/household closures. Every request
must present the user's Supabase access token (Authorization: Bearer <jwt>);
the server validates it, derives the household, and opens an RLS-scoped
connection, exactly like the REST API does.

Tool surface mirrors the in-process adapter (api.agent_tools) 1:1 — same names,
same descriptions (sourced from the core docstrings) — so the only variable
between the two transports is the integration mechanism.

Writes never mutate: they return a `{"status": "proposed", ...}` descriptor.
The host (api.chat) harvests those descriptors, queues them as pending actions,
and applies them only when the user accepts. Applying is NOT an MCP tool.
"""

from __future__ import annotations

import contextvars
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from api.agent_core import tools as core
from api.agent_core.context import Proposal, ToolContext
from api.auth import CurrentUser, _decode
from api.db import service_tx

# Set by the ASGI middleware from the inbound Authorization header, read by the
# tools when they build their ToolContext. A contextvar (not a closure) is how
# per-request identity crosses into an otherwise identity-less server.
_request_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_request_token", default=None
)

# FastMCP enforces DNS-rebinding protection (Host/Origin allowlist). Empty lists
# block everything, so allow the hosts the agent actually calls. Override via
# HEARTH_MCP_ALLOWED_HOSTS (comma-separated host[:port]) when deploying behind a
# real domain; set HEARTH_MCP_DISABLE_HOST_CHECK=1 to turn the guard off.
_allowed_hosts = [
    h.strip()
    for h in os.getenv(
        "HEARTH_MCP_ALLOWED_HOSTS",
        "127.0.0.1:8000,localhost:8000,127.0.0.1,localhost",
    ).split(",")
    if h.strip()
]
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=os.getenv("HEARTH_MCP_DISABLE_HOST_CHECK", "") != "1",
    allowed_hosts=_allowed_hosts,
    allowed_origins=[f"http://{h}" for h in _allowed_hosts]
    + [f"https://{h}" for h in _allowed_hosts],
)

# stateless_http: each request stands alone (no server-side session), which
# suits a per-request-JWT model. streamable_http_path="/" so mounting the app
# at "/mcp" on the main API yields a clean "/mcp" endpoint.
mcp_app = FastMCP(
    "hearth",
    stateless_http=True,
    streamable_http_path="/",
    transport_security=_transport_security,
)


async def _ctx_from_token() -> ToolContext:
    """Validate the per-request JWT and build the ToolContext (user + household).
    Raises if the token is missing/invalid or the user has no household."""
    token = _request_token.get()
    if not token:
        raise ValueError("Missing bearer token — the MCP client must forward the user's JWT.")
    claims = _decode(token)  # verifies signature, expiry, audience (Supabase JWKS / HS)
    user_id = claims.get("sub")
    if not user_id:
        raise ValueError("Token missing sub claim.")
    user = CurrentUser(
        user_id=user_id, email=claims.get("email"), raw_token=token, claims=claims
    )
    async with service_tx() as conn:
        hid = await conn.fetchval(
            "SELECT household_id::text FROM public.household_members "
            "WHERE user_id = $1::uuid LIMIT 1",
            user_id,
        )
    if hid is None:
        raise ValueError("User is not a member of any household.")
    return ToolContext(user=user, household_id=hid)


def _proposal_payload(res: Proposal | str) -> dict:
    """Shape a core write result for the wire: a proposed-action descriptor the
    host can queue, or an error the agent can read."""
    if isinstance(res, Proposal):
        return {"status": "proposed", "kind": res.kind, "summary": res.summary, "params": res.params}
    return {"status": "error", "message": res}


# =========================================================
# READ tools (return strings)
# =========================================================


async def list_recipes() -> str:
    return await core.list_recipes(await _ctx_from_token())


async def search_recipes(query: str) -> str:
    return await core.search_recipes(await _ctx_from_token(), query)


async def search_pool_recipes(query: str) -> str:
    return await core.search_pool_recipes(await _ctx_from_token(), query)


async def get_recipe(recipe_id: str) -> str:
    return await core.get_recipe(await _ctx_from_token(), recipe_id)


async def search_pantry(query: str) -> str:
    return await core.search_pantry(await _ctx_from_token(), query)


async def search_usda(query: str, limit: int = 25) -> str:
    return await core.search_usda(await _ctx_from_token(), query, limit)


async def get_profile() -> str:
    return await core.get_profile(await _ctx_from_token())


async def household_summary() -> str:
    return await core.household_summary(await _ctx_from_token())


async def list_calendar_meals(start_date: str, end_date: str) -> str:
    return await core.list_calendar_meals(await _ctx_from_token(), start_date, end_date)


async def search_usda_for_staple(query: str) -> str:
    return await core.search_usda_for_staple(await _ctx_from_token(), query)


# =========================================================
# WRITE tools (return a proposal descriptor; never mutate)
# =========================================================


async def propose_rename_recipe(recipe_id: str, new_name: str) -> dict:
    return _proposal_payload(await core.propose_rename_recipe(await _ctx_from_token(), recipe_id, new_name))


async def propose_update_recipe_servings(recipe_id: str, servings: int) -> dict:
    return _proposal_payload(await core.propose_update_recipe_servings(await _ctx_from_token(), recipe_id, servings))


async def propose_delete_recipe(recipe_id: str) -> dict:
    return _proposal_payload(await core.propose_delete_recipe(await _ctx_from_token(), recipe_id))


async def propose_generate_recipe(prompt: str, servings: int = 4) -> dict:
    return _proposal_payload(await core.propose_generate_recipe(await _ctx_from_token(), prompt, servings))


async def propose_import_pool_recipe(public_recipe_id: str) -> dict:
    return _proposal_payload(await core.propose_import_pool_recipe(await _ctx_from_token(), public_recipe_id))


async def propose_add_meal_to_calendar(
    recipe_id: str, plan_date: str, slot: str = "dinner", portions: float = 1,
) -> dict:
    return _proposal_payload(await core.propose_add_meal_to_calendar(
        await _ctx_from_token(), recipe_id, plan_date, slot, portions))


async def propose_remove_meal_from_calendar(entry_id: str) -> dict:
    return _proposal_payload(await core.propose_remove_meal_from_calendar(await _ctx_from_token(), entry_id))


async def propose_update_meal_portions(entry_id: str, portions: float) -> dict:
    return _proposal_payload(await core.propose_update_meal_portions(await _ctx_from_token(), entry_id, portions))


async def propose_pantry_add(fdc_id: int) -> dict:
    return _proposal_payload(await core.propose_pantry_add(await _ctx_from_token(), fdc_id))


async def propose_pantry_remove(fdc_id: int) -> dict:
    return _proposal_payload(await core.propose_pantry_remove(await _ctx_from_token(), fdc_id))


async def propose_profile_field(field: str, value: str, mode: str = "add") -> dict:
    return _proposal_payload(await core.propose_profile_field(await _ctx_from_token(), field, value, mode))


async def propose_profile_note(note: str) -> dict:
    return _proposal_payload(await core.propose_profile_note(await _ctx_from_token(), note))


# (wrapper, core fn whose docstring is the canonical description)
_TOOLS = [
    (list_recipes, core.list_recipes),
    (search_recipes, core.search_recipes),
    (search_pool_recipes, core.search_pool_recipes),
    (get_recipe, core.get_recipe),
    (search_pantry, core.search_pantry),
    (search_usda, core.search_usda),
    (get_profile, core.get_profile),
    (household_summary, core.household_summary),
    (list_calendar_meals, core.list_calendar_meals),
    (search_usda_for_staple, core.search_usda_for_staple),
    (propose_rename_recipe, core.propose_rename_recipe),
    (propose_update_recipe_servings, core.propose_update_recipe_servings),
    (propose_delete_recipe, core.propose_delete_recipe),
    (propose_generate_recipe, core.propose_generate_recipe),
    (propose_import_pool_recipe, core.propose_import_pool_recipe),
    (propose_add_meal_to_calendar, core.propose_add_meal_to_calendar),
    (propose_remove_meal_from_calendar, core.propose_remove_meal_from_calendar),
    (propose_update_meal_portions, core.propose_update_meal_portions),
    (propose_pantry_add, core.propose_pantry_add),
    (propose_pantry_remove, core.propose_pantry_remove),
    (propose_profile_field, core.propose_profile_field),
    (propose_profile_note, core.propose_profile_note),
]

for _wrapper, _core_fn in _TOOLS:
    mcp_app.tool(name=_core_fn.__name__, description=(_core_fn.__doc__ or "").strip())(_wrapper)


class _TokenCaptureMiddleware:
    """Pure-ASGI middleware: lift the bearer token off the inbound request into
    the request-scoped contextvar so tools (running in the same async context)
    can derive identity. This is the per-request boundary the thesis hinges on."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token: str | None = None
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                val = v.decode("latin-1")
                if val.lower().startswith("bearer "):
                    token = val[7:].strip()
                break
        reset = _request_token.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            _request_token.reset(reset)


def build_mcp_asgi():
    """ASGI app for the MCP server, wrapped to capture the per-request token.
    Mount this on the main FastAPI app (and run `mcp_app.session_manager` in the
    app lifespan)."""
    return _TokenCaptureMiddleware(mcp_app.streamable_http_app())
