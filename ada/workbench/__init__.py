"""Ada workbench — the management UI, served by the runtime at /.

A single self-contained static page (no build step, no Node): the
design-system CSS, the login/rotation gate, and a vanilla-JS client
that speaks the same public contract as every other MCP client.
"""

from pathlib import Path

INDEX = Path(__file__).parent / "index.html"
