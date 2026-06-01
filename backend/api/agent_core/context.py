"""Per-request context + the write-proposal descriptor.

`ToolContext` carries everything a tool needs to act on behalf of a household
WITHOUT relying on closures — so the same tool body works whether it's called
in-process (context built from the FastAPI request) or over MCP (context built
from a validated per-request JWT).

`Proposal` is what every WRITE tool returns instead of mutating. The host turns
it into a pending-action card the user accepts or rejects.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from api.auth import CurrentUser


@dataclass
class ToolContext:
    user: CurrentUser
    household_id: str


class Proposal(BaseModel):
    """A proposed (not-yet-applied) mutation. `kind` must match an executor in
    `api.pending_actions._EXECUTORS`; `params` is that executor's input."""

    kind: str
    summary: str
    params: dict
