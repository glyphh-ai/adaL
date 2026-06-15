"""TUI smoke test: the app boots, connects (via a fake MCP backend),
renders the dashboard from stats, navigates the rail, and dispatches a
terminal command — all headless through Textual's run_test() harness.
"""

import asyncio

from textual.widgets import DataTable, Input, RichLog, Static

from ada.tui.app import AdaApp


class FakeBackend:
    """Stands in for repl.ServerBackend — canned MCP tool responses."""

    def __init__(self, url: str) -> None:
        self.url = url

    def call(self, tool: str, args: dict) -> dict:
        if tool == "stats":
            return {
                "count": 42,
                "versioned_keys": 7,
                "multi_version_keys": 3,
                "storage": "memory",
                "layer_fill": {"entity": 40, "spatial": 12, "relational": 20},
            }
        if tool == "keys":
            return {"facts": [
                {"key": "carol.location", "content": "Carol lives in Denver.",
                 "version": 2},
            ]}
        if tool == "token_list":
            return {"tokens": [
                {"prefix": "ada_abc1234", "name": "ci", "permissions": ["read"],
                 "status": "active", "expires_at": None},
            ]}
        if tool == "ask":
            return {"refused": False, "answer": "Denver", "confidence": 0.91}
        return {}


async def _settle(app, pred, tries: int = 60) -> bool:
    for _ in range(tries):
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


def test_tui_boots_navigates_and_dispatches(monkeypatch):
    monkeypatch.setattr("ada.tui.repl.ServerBackend", FakeBackend)

    async def run() -> None:
        app = AdaApp("http://localhost:0/mcp")
        async with app.run_test() as pilot:
            # the threaded connect should settle and populate the backend
            assert await _settle(app, lambda: app._connected), "never connected"

            # dashboard renders the stat cards from stats()
            assert await _settle(
                app,
                lambda: "42" in str(
                    app.query_one("#card-thoughts", Static).render()),
            ), "dashboard card not rendered"
            assert "memory" in str(app.query_one("#card-storage", Static).render())
            assert "entity" in str(app.query_one("#bars", Static).render())

            # memory + tokens tables populate from their tools
            assert await _settle(
                app, lambda: app.query_one("#mem-table", DataTable).row_count == 1)
            assert await _settle(
                app, lambda: app.query_one("#tok-table", DataTable).row_count == 1)

            # rail navigation switches the content view
            for view in ("term", "mem", "tok", "dash"):
                app.action_show(view)
                await pilot.pause()
                assert app.query_one("#views").current == view

            # a terminal command runs end-to-end and writes to the log
            log = app.query_one("#term-log", RichLog)
            before = len(log.lines)
            app.action_show("term")
            inp = app.query_one("#term-input", Input)
            inp.value = "ask where is carol"
            await app._term_submit(Input.Submitted(inp, inp.value))
            assert await _settle(app, lambda: len(log.lines) > before), \
                "terminal produced no output"

    asyncio.run(run())
