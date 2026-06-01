"""In-process adapter: exposes the shared tool core (`api.agent_core.tools`) to
the PydanticAI chat agent.

This is the thesis CONTROL GROUP — the "traditional" in-process tool-calling
path. It is a thin wrapper: each tool delegates to the matching pure function in
`agent_core.tools` and carries that function's docstring as its description
(single source of truth, so the MCP server and this path describe tools
identically). Write tools turn the returned `Proposal` into a buffered pending
action via `PendingProposer`; reads pass through unchanged.
"""

from __future__ import annotations

from pydantic_ai import Tool

from api.agent_core import tools as core
from api.agent_core.context import Proposal, ToolContext
from api.pending_actions import PendingProposer


def _emit(proposer: PendingProposer, res: Proposal | str) -> str:
    """Realize a core write result: buffer a Proposal (returning the stable
    'Proposed (id=…)' reply) or pass an error string straight through."""
    if isinstance(res, Proposal):
        pid = proposer.propose(res.kind, res.summary, res.params)
        return f"Proposed (id={pid}): {res.summary}. Waiting for the user to accept."
    return res


def build_chat_toolset(ctx: ToolContext, proposer: PendingProposer) -> list[Tool]:
    """Build the PydanticAI Tool list for one chat turn. Each tool closes over
    `ctx` (so no per-call context plumbing) and the write tools over `proposer`.
    Descriptions come from the core function docstrings."""

    # ---- READ — run inline ----
    async def list_recipes() -> str:
        return await core.list_recipes(ctx)

    async def search_recipes(query: str) -> str:
        return await core.search_recipes(ctx, query)

    async def search_pool_recipes(query: str) -> str:
        return await core.search_pool_recipes(ctx, query)

    async def get_recipe(recipe_id: str) -> str:
        return await core.get_recipe(ctx, recipe_id)

    async def search_pantry(query: str) -> str:
        return await core.search_pantry(ctx, query)

    async def search_usda(query: str, limit: int = 25) -> str:
        return await core.search_usda(ctx, query, limit)

    async def get_profile() -> str:
        return await core.get_profile(ctx)

    async def household_summary() -> str:
        return await core.household_summary(ctx)

    async def list_calendar_meals(start_date: str, end_date: str) -> str:
        return await core.list_calendar_meals(ctx, start_date, end_date)

    async def search_usda_for_staple(query: str) -> str:
        return await core.search_usda_for_staple(ctx, query)

    # ---- WRITE — propose for user approval ----
    async def propose_rename_recipe(recipe_id: str, new_name: str) -> str:
        return _emit(proposer, await core.propose_rename_recipe(ctx, recipe_id, new_name))

    async def propose_update_recipe_servings(recipe_id: str, servings: int) -> str:
        return _emit(proposer, await core.propose_update_recipe_servings(ctx, recipe_id, servings))

    async def propose_delete_recipe(recipe_id: str) -> str:
        return _emit(proposer, await core.propose_delete_recipe(ctx, recipe_id))

    async def propose_generate_recipe(prompt: str, servings: int = 4) -> str:
        return _emit(proposer, await core.propose_generate_recipe(ctx, prompt, servings))

    async def propose_import_pool_recipe(public_recipe_id: str) -> str:
        return _emit(proposer, await core.propose_import_pool_recipe(ctx, public_recipe_id))

    async def propose_add_meal_to_calendar(
        recipe_id: str, plan_date: str, slot: str = "dinner", portions: float = 1,
    ) -> str:
        return _emit(proposer, await core.propose_add_meal_to_calendar(
            ctx, recipe_id, plan_date, slot, portions))

    async def propose_remove_meal_from_calendar(entry_id: str) -> str:
        return _emit(proposer, await core.propose_remove_meal_from_calendar(ctx, entry_id))

    async def propose_update_meal_portions(entry_id: str, portions: float) -> str:
        return _emit(proposer, await core.propose_update_meal_portions(ctx, entry_id, portions))

    async def propose_pantry_add(fdc_id: int) -> str:
        return _emit(proposer, await core.propose_pantry_add(ctx, fdc_id))

    async def propose_pantry_remove(fdc_id: int) -> str:
        return _emit(proposer, await core.propose_pantry_remove(ctx, fdc_id))

    async def propose_profile_field(field: str, value: str) -> str:
        return _emit(proposer, await core.propose_profile_field(ctx, field, value))

    async def propose_profile_note(note: str) -> str:
        return _emit(proposer, await core.propose_profile_note(ctx, note))

    # (wrapper, core fn whose docstring is the canonical description)
    pairs = [
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
    return [
        Tool(
            wrapper,
            takes_ctx=False,
            name=core_fn.__name__,
            description=(core_fn.__doc__ or "").strip(),
        )
        for wrapper, core_fn in pairs
    ]
