"""Ada workbench — the legacy browser management UI, served at /.

DEPRECATED. The terminal TUI (``ada`` → ``ada.tui.app``) is now the
single, first-class interface; it mirrors this workbench's design over
the same /mcp door. The page is still served for the no-terminal browser
path, but it is in maintenance mode and slated for removal. New work goes
into the TUI.

A single self-contained static page (no build step, no Node): the
design-system CSS, the login/rotation gate, and a vanilla-JS client
that speaks the same public contract as every other MCP client.
"""

from pathlib import Path

INDEX = Path(__file__).parent / "index.html"
