"""
MCP — Ada's single /mcp endpoint.

One tool: think(input).
"""

from domains.mcp.app import MCPRoutingMiddleware, create_mcp_session_managers
from domains.mcp.server import create_mcp_server

__all__ = [
    "create_mcp_server",
    "create_mcp_session_managers",
    "MCPRoutingMiddleware",
]
