"""Back-compat shim — the admin REPL lives at ada.tui.repl.

    PYTHONPATH=. python scripts/ada_repl.py [--url http://host:port/mcp]
"""

from ada.tui.repl import main

if __name__ == "__main__":
    main()
