"""MCP server exposing the shared tool core over Streamable HTTP.

This is the thesis EXPERIMENT arm: instead of attaching tools in-process, the
chat agent reaches them as an MCP client over HTTP. The server is identity-less
and host-agnostic — it carries no session/household closures. Every request
must present the user's Supabase access token (Authorization: Bearer <jwt>);
the server validates it, derives the household, and opens an RLS-scoped
connection, exactly like the REST API does.

It is an OAuth 2.1 Resource Server: it advertises the Supabase project as its
Authorization Server (RFC 9728 protected-resource metadata) and validates the
bearer tokens Supabase issues. That lets any MCP client connect as a "connector"
— browser login + automatic token refresh — instead of pasting a raw JWT.

Tool surface mirrors the in-process adapter (api.agent_tools) 1:1 — same names,
same descriptions (sourced from the core docstrings) — so the only variable
between the two transports is the integration mechanism.

Writes never mutate directly: they return a `{"status": "proposed", ...}` descriptor.
For our own chat host, api.chat harvests those and queues them as pending actions the
web app applies on accept. For a generic MCP host (Claude Code), `apply_proposals` applies the changes the user
approved. (We tried a server-side elicitation gate to enforce confirmation, but this
client auto-declines elicitation without rendering it, so confirmation is driven by the
agent's own question UI per the server instructions — see _AGENT_INSTRUCTIONS.)
"""

from __future__ import annotations

import os

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from api.agent_core import tools as core
from api.agent_core.context import Proposal, ToolContext
from api.auth import CurrentUser, _decode
from api.db import service_tx
from api.pending_actions import _EXECUTORS as _PENDING_EXECUTORS, execute as _execute_pending

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

# OAuth 2.1 Resource Server config. The issuer is the Supabase project's auth
# server (which actually logs the user in + issues/refreshes tokens); the
# resource URL identifies THIS server and anchors its RFC 9728 metadata.
_ISSUER_URL = os.getenv("HEARTH_MCP_ISSUER_URL") or (
    f"{os.getenv('SUPABASE_URL', '').rstrip('/')}/auth/v1"
)
_RESOURCE_URL = os.getenv("HEARTH_MCP_RESOURCE_URL", "http://127.0.0.1:8000/mcp")


class SupabaseTokenVerifier:
    """Verifies a bearer token as a Supabase-issued JWT (JWKS / HS256) and exposes
    its claims to the tools. This is the whole of being a Resource Server: trust
    tokens minted by the Supabase Authorization Server; never mint or store any."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # audience=None: OAuth-server tokens may not carry aud="authenticated";
            # signature + expiry are still verified via the project JWKS.
            claims = _decode(token, audience=None)
        except Exception:
            return None
        sub = claims.get("sub")
        if not sub:
            return None
        scope = claims.get("scope") or ""
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("aud") or sub),
            scopes=scope.split() if scope else ["mcp"],
            expires_at=claims.get("exp"),
            subject=sub,
            claims=claims,
        )


# Surfaced to the MCP client (Claude Code etc.) as server instructions. Tells a
# generic host how to drive the propose→apply loop, since the propose tools alone
# imply "the app accepts" — which is only true for our own chat host.
_AGENT_INSTRUCTIONS = (
    "Write tools here only PROPOSE changes: they return "
    '{"summary", "status": "proposed", "kind", "params"} and do NOT mutate anything. '
    "Before applying ANYTHING, you MUST get the user's approval: present the proposed "
    "change(s) using your interactive multiple-choice question UI — list each change as a "
    "selectable option and allow multiple selections — and let the user pick which to apply. "
    "Then call apply_proposals(proposals=[...]) with ONLY the approved changes (each item is "
    "the {kind, params, summary} from a proposal). The apply tools mutate immediately, so the "
    "human-in-the-loop is YOUR approval question — never apply a change the user didn't pick, "
    "and never tell them to 'accept it in the app'. When you describe a proposed or applied "
    "change, use the human-readable summary/message text — never surface raw kind/params/JSON."
)

# stateless_http: each request stands alone (per-request-JWT model). We briefly went
# stateful to enable server→client elicitation as an enforced confirmation gate, but
# this MCP client (VSCode extension) auto-declines elicitation without rendering it — so
# confirmation is handled agent-side (see _AGENT_INSTRUCTIONS) and we keep the simpler
# stateless transport. streamable_http_path="/" → clean "/mcp"; token_verifier + auth
# make the SDK emit the 401 + RFC 9728 challenge and validate every bearer.
mcp_app = FastMCP(
    "Mealplanner",
    instructions=_AGENT_INSTRUCTIONS,
    stateless_http=True,
    streamable_http_path="/",
    transport_security=_transport_security,
    token_verifier=SupabaseTokenVerifier(),
    auth=AuthSettings(
        issuer_url=_ISSUER_URL,
        resource_server_url=_RESOURCE_URL,
        required_scopes=None,
    ),
)


async def _ctx_from_token() -> ToolContext:
    """Build the ToolContext (user + household) from the request's verified token.
    The SDK auth middleware has already validated the bearer (SupabaseTokenVerifier)
    and stashed it on the request context. Raises if unauthenticated or no household."""
    at = get_access_token()
    if at is None:
        raise ValueError("Unauthenticated MCP request — no verified access token.")
    claims = at.claims or {}
    user_id = at.subject or claims.get("sub")
    if not user_id:
        raise ValueError("Token missing sub claim.")
    user = CurrentUser(
        user_id=user_id, email=claims.get("email"), raw_token=at.token, claims=claims
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
        # summary first + human-readable: the host shows this to the user. kind/params
        # are the machine bits apply_proposal needs. Apply guidance lives in the server
        # instructions (not echoed here) so this stays clean and legible.
        return {
            "summary": res.summary,
            "status": "proposed",
            "kind": res.kind,
            "params": res.params,
        }
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


async def apply_proposal(kind: str, params: dict, summary: str = "") -> dict:
    """Apply a single proposed write (status="proposed") the user has APPROVED. Pass the
    EXACT `kind` and `params` from the proposal. This MUTATES data immediately, so only
    call it after the user approved this change in your confirmation question. Prefer
    apply_proposals for one-or-more changes. Returns {"status":"applied","message":...}
    (plus "created" ids when relevant) or {"status":"error","message":...}. Show the user
    the `message`, never the raw fields."""
    ctx = await _ctx_from_token()
    if kind not in _PENDING_EXECUTORS:
        return {"status": "error", "message": f"Unknown action kind '{kind}'."}
    try:
        result, created = await _execute_pending(kind, ctx.user, params, ctx.locale)
    except Exception as e:
        return {"status": "error", "message": f"Apply failed: {e}"}
    payload: dict = {"status": "applied", "message": result}
    if created:
        payload["created"] = created
    return payload


async def apply_proposals(proposals: list[dict]) -> dict:
    """Apply one or more proposed writes the user has APPROVED. `proposals` is a list where
    each item is the {"kind","params","summary"} a propose_* tool returned — include ONLY
    the changes the user approved in your confirmation question. This MUTATES data
    immediately. Returns {"status":"done","applied":N,"results":[...]} where each result
    carries the change's summary + applied/error. Show the user the per-change messages,
    never the raw fields."""
    ctx = await _ctx_from_token()
    items: list[dict] = []
    for i, p in enumerate(proposals or []):
        p = p or {}
        kind = p.get("kind")
        if kind not in _PENDING_EXECUTORS:
            return {"status": "error", "message": f"Unknown action kind '{kind}' in change #{i + 1}."}
        items.append({"kind": kind, "params": p.get("params") or {}, "summary": p.get("summary") or kind})
    if not items:
        return {"status": "error", "message": "No changes to apply."}

    results: list[dict] = []
    applied = 0
    for it in items:
        try:
            msg, created = await _execute_pending(it["kind"], ctx.user, it["params"], ctx.locale)
        except Exception as e:
            results.append({"summary": it["summary"], "status": "error", "message": f"Apply failed: {e}"})
            continue
        r: dict = {"summary": it["summary"], "status": "applied", "message": msg}
        if created:
            r["created"] = created
        results.append(r)
        applied += 1
    return {"status": "done", "applied": applied, "results": results}


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

# apply_proposal is MCP-only (no shared-core twin). The in-process adapter applies
# writes via the web app's accept UI; a generic MCP host like Claude Code has no such
# UI, so the accept step becomes an explicit tool (gated by the host's tool-approval
# prompt). Registering it only here leaves the in-process control-group toolset unchanged.
mcp_app.tool(name="apply_proposal", description=(apply_proposal.__doc__ or "").strip())(apply_proposal)
mcp_app.tool(name="apply_proposals", description=(apply_proposals.__doc__ or "").strip())(apply_proposals)


def protected_resource_metadata() -> dict:
    """RFC 9728 Protected Resource Metadata. The SDK builds this too, but registers
    it INSIDE the FastMCP app — which, once mounted at /mcp, hides it under the
    mount while the WWW-Authenticate header advertises the root path. So the main
    app serves this dict at the advertised root path instead (see api.main)."""
    return {
        "resource": _RESOURCE_URL,
        "authorization_servers": [_ISSUER_URL],
        "scopes_supported": [],
        "bearer_methods_supported": ["header"],
    }


def build_mcp_asgi():
    """ASGI app for the MCP server. The SDK's own auth middleware extracts and
    validates the per-request bearer (SupabaseTokenVerifier) and serves the RFC
    9728 challenge on 401, so no extra wrapper is needed. Mount this on the main
    FastAPI app (and run `mcp_app.session_manager` in the app lifespan)."""
    return mcp_app.streamable_http_app()
