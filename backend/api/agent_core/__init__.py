"""Transport-agnostic core for the Mealplanner agent.

`tools` holds pure tool implementations shared by two adapters:
  * `api.agent_tools` — in-process PydanticAI tools (thesis control group)
  * `api.mcp.server`  — the MCP server (thesis experiment)

Both must expose the SAME tools so the only variable between them is the
integration mechanism (in-process vs MCP), not the toolset.
"""

from api.agent_core.context import Proposal, ToolContext

__all__ = ["Proposal", "ToolContext"]
