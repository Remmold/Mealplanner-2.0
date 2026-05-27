"""Chat agent: lets the user manage recipes, meal plans, and the pantry via
natural language (Postgres-backed, RLS-scoped per household).

Storage:
- Conversation history persisted as JSONB on `hearth.chat_sessions.message_history`.
  We round-trip through PydanticAI's `ModelMessagesTypeAdapter.dump_python`
  (mode='json') so what we write is JSON-serializable Python (list of dicts),
  which asyncpg's jsonb codec handles natively. Reading back, `validate_python`
  reconstructs the typed `ModelMessage` objects.
- The `chat_messages` table exists in the schema but isn't used yet — the
  JSONB blob is the source of truth for now.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessagesTypeAdapter

from api.agent_tools import register_all
from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, user_tx
from api.pending_actions import PendingProposer
from api.profile import is_profile_sparse, load_profile, render_profile_context

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/chat", tags=["chat"])

_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")

_SYSTEM_PROMPT_BASE = (
    "You are a helpful kitchen assistant inside the Hearth meal-planning app. "
    "You help the user manage their saved recipes, meal plans, and pantry by "
    "calling the available tools.\n\n"
    "Guidelines:\n"
    "- Always use tools to look things up before claiming something exists or "
    "  doesn't. Never invent IDs.\n"
    "- When the user asks to do something (add a meal, create a plan, generate "
    "  a recipe), DO IT — don't just describe what you would do.\n"
    "- For meal plan operations, dates are ISO format YYYY-MM-DD. Slots are "
    "  'breakfast', 'lunch', or 'dinner'.\n"
    "- When generating a recipe to fill a meal slot, first call "
    "  generate_and_save_recipe, then add_meal_to_plan with the returned id.\n"
    "- Be concise. After completing actions, give a brief summary of what you did.\n"
    "- If unsure about destructive operations (delete recipe, delete plan), "
    "  confirm with the user before acting.\n"
    "\n"
    "Getting to know the household:\n"
    "- The profile below is what you know about this household's eating habits. "
    "  Use it whenever you pick or generate recipes — respect allergies strictly, "
    "  avoid dislikes, lean into likes/cuisines, match their cook-time tolerance "
    "  and batch-cook preference.\n"
    "- When the user mentions something persistent (a preference, a habit, an "
    "  aversion, family size, equipment), PROPOSE it via propose_profile_field "
    "  or propose_profile_note. Don't re-propose things already on file.\n"
    "- Never spam the user with questionnaires. Ask at most one natural "
    "  profile-discovery question per turn, and only when it would improve the "
    "  answer you're about to give.\n"
    "\n"
    "Human-in-the-loop writes:\n"
    "- Every write is via a `propose_*` tool. These DO NOT mutate anything — "
    "  they queue a card the user accepts or rejects in the UI.\n"
    "- It's fine (and expected) to propose multiple actions in one turn.\n"
    "- After proposing, do NOT pretend the change happened. Say things like "
    "  'I've put 3 cards above for you to accept' rather than 'I've added X'.\n"
    "- If a previous turn's proposal was rejected, don't re-propose the exact "
    "  same thing — ask what the user would prefer instead."
)


async def _build_system_prompt(household_id: str) -> str:
    profile = await load_profile(household_id)
    profile_block = render_profile_context(profile)
    sparse_hint = ""
    if is_profile_sparse(profile):
        sparse_hint = (
            "\n\nPROFILE IS SPARSE — if the current conversation is about meal "
            "planning or recipe generation, ask one or two quick discovery "
            "questions first and record the answers via the profile tools."
        )
    return (
        _SYSTEM_PROMPT_BASE
        + "\n\n--- Household profile ---\n"
        + profile_block
        + sparse_hint
    )


# ============================================================
# Request / response models
# ============================================================


class SendMessageRequest(BaseModel):
    content: str


class ProposedAction(BaseModel):
    id: str
    kind: str
    summary: str
    params: dict


class SendMessageResponse(BaseModel):
    reply: str
    pending: list[ProposedAction]
    session_id: str


class ChatMessageOut(BaseModel):
    role: str
    content: str


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ChatSessionDetail(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessageOut]


# ============================================================
# Helpers
# ============================================================


def _summarise_messages(message_history) -> list[ChatMessageOut]:
    """Extract user/assistant text from PydanticAI's structured message history.

    `message_history` is a list of dicts (from JSONB) or empty. We parse it
    back to typed ModelMessage objects via validate_python, then extract text
    parts only — tool calls/returns are surfaced via the audit events that come
    back from each turn instead.
    """
    if not message_history:
        return []
    try:
        messages = ModelMessagesTypeAdapter.validate_python(message_history)
    except Exception:
        return []

    out: list[ChatMessageOut] = []
    for msg in messages:
        kind = msg.kind  # 'request' or 'response'
        text_parts = []
        for part in msg.parts:
            part_kind = getattr(part, "part_kind", None)
            if part_kind in ("user-prompt", "text"):
                text_parts.append(getattr(part, "content", ""))
        text = "\n".join(p for p in text_parts if p).strip()
        if not text:
            continue
        if kind == "request":
            out.append(ChatMessageOut(role="user", content=text))
        elif kind == "response":
            out.append(ChatMessageOut(role="assistant", content=text))
    return out


def _derive_title(first_user_msg: str) -> str:
    text = first_user_msg.strip().replace("\n", " ")
    return (text[:60] + "…") if len(text) > 60 else text or "New chat"


# ============================================================
# Endpoints
# ============================================================


@router.get("/sessions", response_model=list[ChatSessionSummary])
async def list_sessions(user: CurrentUser = Depends(get_current_user)):
    async with user_tx(user) as conn:
        rows = await conn.fetch(
            """
            SELECT id::text AS id, title, created_at, updated_at,
                   COALESCE(jsonb_array_length(message_history), 0) AS n
            FROM hearth.chat_sessions
            ORDER BY updated_at DESC
            """
        )
    return [
        ChatSessionSummary(
            id=r["id"],
            title=r["title"],
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
            updated_at=r["updated_at"].isoformat() if r["updated_at"] else "",
            message_count=int(r["n"]),
        )
        for r in rows
    ]


@router.post("/sessions", response_model=ChatSessionDetail, status_code=201)
async def create_session(
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO hearth.chat_sessions (household_id, title)
            VALUES ($1::uuid, $2)
            RETURNING id::text AS id, title, created_at, updated_at
            """,
            household_id, "New chat",
        )
    return ChatSessionDetail(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else "",
        messages=[],
    )


@router.get("/sessions/{sid}", response_model=ChatSessionDetail)
async def get_session(sid: str, user: CurrentUser = Depends(get_current_user)):
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            """
            SELECT id::text AS id, title, created_at, updated_at, message_history
            FROM hearth.chat_sessions WHERE id = $1::uuid
            """,
            sid,
        )
    if row is None:
        raise HTTPException(404, "Session not found")
    return ChatSessionDetail(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else "",
        messages=_summarise_messages(row["message_history"]),
    )


@router.delete("/sessions/{sid}", status_code=204)
async def delete_session(sid: str, user: CurrentUser = Depends(get_current_user)):
    async with user_tx(user) as conn:
        await conn.execute(
            "DELETE FROM hearth.chat_sessions WHERE id = $1::uuid",
            sid,
        )


@router.post("/sessions/{sid}/messages", response_model=SendMessageResponse)
async def send_message(
    sid: str,
    body: SendMessageRequest,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    from api.credits import debit, require_credits

    await require_credits(household_id, "chat_turn")

    # Load the session (RLS-scoped — wrong-household sessions are invisible).
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            "SELECT title, message_history FROM hearth.chat_sessions "
            "WHERE id = $1::uuid",
            sid,
        )
    if row is None:
        raise HTTPException(404, "Session not found")
    prior_history = row["message_history"] or []
    title = row["title"]

    # Build a fresh agent for this turn.
    proposer = PendingProposer(session_id=sid, household_id=household_id, user=user)
    agent = Agent(_MODEL, system_prompt=await _build_system_prompt(household_id))
    register_all(agent, household_id, proposer, user)

    if prior_history:
        try:
            typed_prior = ModelMessagesTypeAdapter.validate_python(prior_history)
        except Exception:
            typed_prior = []
    else:
        typed_prior = []

    try:
        result = await agent.run(body.content, message_history=typed_prior)
    except Exception as e:
        raise HTTPException(500, f"Agent failed: {e}")

    await debit(household_id, "chat_turn", ref_id=sid)

    reply_text = str(result.output) if result.output is not None else ""

    all_messages = result.all_messages()
    new_history = ModelMessagesTypeAdapter.dump_python(all_messages, mode="json")

    new_title = title if title != "New chat" else _derive_title(body.content)

    # Persist queued proposals (via service_tx — proposer owns its own writes).
    flushed = await proposer.flush()

    async with user_tx(user) as conn:
        await conn.execute(
            """
            UPDATE hearth.chat_sessions
            SET message_history = $1::jsonb, title = $2, updated_at = now()
            WHERE id = $3::uuid
            """,
            new_history, new_title, sid,
        )

    return SendMessageResponse(
        reply=reply_text,
        pending=[
            ProposedAction(
                id=p["id"], kind=p["kind"], summary=p["summary"], params=p["params"]
            )
            for p in flushed
        ],
        session_id=sid,
    )
