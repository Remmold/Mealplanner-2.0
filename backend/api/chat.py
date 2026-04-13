"""Chat agent: lets the user manage recipes, meal plans, and the pantry via natural language.

Architecture:
- One PydanticAI Agent per request (cheap to construct), with all tools registered
  via `agent_tools.register_all`. Tools close over the household_id and an AuditLog
  so every mutation is recorded for the UI.
- Conversation history is persisted as JSON on `chat_sessions.message_history`
  using PydanticAI's `ModelMessagesTypeAdapter`, so a session can be resumed
  across requests / app restarts.
- The send-message endpoint returns the assistant's text reply plus the list of
  audit events, so the frontend can show "Updated 'Tuesday dinner' to ..." cards
  and refresh affected views.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessagesTypeAdapter

from api.agent_tools import AuditLog, register_all
from api.recipe_db import DEFAULT_HOUSEHOLD_ID, get_recipe_db, new_id

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/chat", tags=["chat"])

_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")

SYSTEM_PROMPT = (
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
    "  confirm with the user before acting."
)


# ============================================================
# Request / response models
# ============================================================


class SendMessageRequest(BaseModel):
    content: str


class AuditEvent(BaseModel):
    kind: str
    summary: str
    meta: dict


class SendMessageResponse(BaseModel):
    reply: str
    audit: list[AuditEvent]
    session_id: str


class ChatMessageOut(BaseModel):
    role: str  # 'user' | 'assistant' | 'system'
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


def _summarise_messages(message_history_json: bytes) -> list[ChatMessageOut]:
    """Extract user/assistant text from PydanticAI's structured message history.

    PydanticAI stores rich messages with parts (text, tool calls, tool returns).
    For UI display we only surface text content. Tool calls/returns are visible
    via the audit events that come back from each turn."""
    if not message_history_json:
        return []
    try:
        messages = ModelMessagesTypeAdapter.validate_json(message_history_json)
    except Exception:
        return []

    out: list[ChatMessageOut] = []
    for msg in messages:
        kind = msg.kind  # 'request' or 'response'
        # Text parts only
        text_parts = []
        for part in msg.parts:
            part_kind = getattr(part, "part_kind", None)
            if part_kind in ("user-prompt", "text"):
                text_parts.append(getattr(part, "content", ""))
        text = "\n".join(p for p in text_parts if p).strip()
        if not text:
            continue
        if kind == "request":
            # User-side message
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
def list_sessions(household_id: str = DEFAULT_HOUSEHOLD_ID):
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT s.id, s.title, s.created_at, s.updated_at, "
            "(SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS n "
            "FROM chat_sessions s WHERE s.household_id = ? "
            "ORDER BY s.updated_at DESC",
            [household_id],
        ).fetchall()
    return [
        ChatSessionSummary(
            id=r["id"], title=r["title"],
            created_at=r["created_at"], updated_at=r["updated_at"],
            message_count=r["n"],
        )
        for r in rows
    ]


@router.post("/sessions", response_model=ChatSessionDetail, status_code=201)
def create_session(household_id: str = DEFAULT_HOUSEHOLD_ID):
    sid = new_id()
    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, household_id, title) VALUES (?, ?, ?)",
            [sid, household_id, "New chat"],
        )
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions WHERE id = ?",
            [sid],
        ).fetchone()
    return ChatSessionDetail(
        id=row["id"], title=row["title"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        messages=[],
    )


@router.get("/sessions/{sid}", response_model=ChatSessionDetail)
def get_session(sid: str):
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at, message_history "
            "FROM chat_sessions WHERE id = ?",
            [sid],
        ).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
    history_bytes = (row["message_history"] or "").encode("utf-8")
    return ChatSessionDetail(
        id=row["id"], title=row["title"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        messages=_summarise_messages(history_bytes),
    )


@router.delete("/sessions/{sid}", status_code=204)
def delete_session(sid: str):
    with get_recipe_db() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", [sid])


@router.post("/sessions/{sid}/messages", response_model=SendMessageResponse)
async def send_message(sid: str, body: SendMessageRequest, household_id: str = DEFAULT_HOUSEHOLD_ID):
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT title, message_history FROM chat_sessions WHERE id = ? AND household_id = ?",
            [sid, household_id],
        ).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
        prior_history_str: str = row["message_history"] or ""
        title = row["title"]

    # Build a fresh agent for this turn (cheap; tools close over household_id + audit)
    audit = AuditLog()
    agent = Agent(_MODEL, system_prompt=SYSTEM_PROMPT)
    register_all(agent, household_id, audit)

    # Deserialise prior history
    if prior_history_str:
        try:
            prior_history = ModelMessagesTypeAdapter.validate_json(prior_history_str.encode("utf-8"))
        except Exception:
            prior_history = []
    else:
        prior_history = []

    # Run the turn
    try:
        result = await agent.run(body.content, message_history=prior_history)
    except Exception as e:
        raise HTTPException(500, f"Agent failed: {e}")

    reply_text = str(result.output) if result.output is not None else ""

    # Persist the new full history
    all_messages = result.all_messages()
    new_history_bytes = ModelMessagesTypeAdapter.dump_json(all_messages)

    # Derive a title from the first user message if still default
    new_title = title
    if title == "New chat":
        new_title = _derive_title(body.content)

    with get_recipe_db() as conn:
        conn.execute(
            "UPDATE chat_sessions SET message_history = ?, title = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [new_history_bytes.decode("utf-8"), new_title, sid],
        )

    return SendMessageResponse(
        reply=reply_text,
        audit=[AuditEvent(**e) for e in audit.events],
        session_id=sid,
    )
