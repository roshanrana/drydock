"""MCP surface of DRYDOCK (docs/design/03-lld.md section 6).

- :mod:`drydock.mcp.sources_server` — the ``drydock-sources`` server the Planner queries.
- :mod:`drydock.mcp.toolbox` — the sync :class:`McpToolBox` graph nodes use to call it.
"""

from drydock.mcp.sources_server import build_server
from drydock.mcp.toolbox import McpToolBox

__all__ = ["McpToolBox", "build_server"]
