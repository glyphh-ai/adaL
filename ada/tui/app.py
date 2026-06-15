"""
Ada TUI — the single, first-class interface.

One full-screen terminal app that mirrors the web workbench: a left rail,
a status topbar, and a dashboard home that renders the substrate's vital
signs as live terminal graphs. It is a thin MCP client of the running Ada
server (the same `/mcp` door the REPL, Claude, and every other client use),
so there is no second copy of any logic — just one memory, rendered.

    Dashboard   live stat cards · per-layer slot-fill bars · session sparkline
    Terminal    the full command surface (tell / ask / think / query / …)
    Memory      keyed facts, current belief, filterable
    Tokens      mint / list / revoke the credentials that open /mcp

Launched by `ada` (see ada.tui.cli). Falls back to the line REPL if Textual
is not installed.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Input,
    RichLog,
    Sparkline,
    Static,
)
from textual.widgets import ContentSwitcher

# ── Brand palette — the exact --ada-* tokens from the workbench ────────
INK_SUNKEN = "#0e0b15"
INK = "#16121f"
INK_RAISED = "#241e33"
BORDER = "#2c2540"
TEXT = "#f2effb"
TEXT_SOFT = "#c9c2e0"
TEXT_MUTED = "#9a92b3"
TEXT_FAINT = "#6b6480"
SIGNAL = "#ff5f87"   # pink
ACCENT = "#d787ff"
PRIMARY = "#af87ff"  # lead / purple
CALM = "#87afff"     # blue
GREEN = "#87d7af"

# Fixed layer order of the universal schema — the dashboard bars follow it.
_LAYERS = [
    "entity",
    "perceptual",
    "spatial",
    "temporal",
    "relational",
    "quantitative",
    "epistemic",
]


def _grad(frac: float) -> str:
    """A hex stop on the brand pink (#ff5f87) → blue (#87afff) ramp."""
    frac = max(0.0, min(1.0, frac))
    r0, g0, b0 = 0xFF, 0x5F, 0x87
    r1, g1, b1 = 0x87, 0xAF, 0xFF
    r = round(r0 + (r1 - r0) * frac)
    g = round(g0 + (g1 - g0) * frac)
    b = round(b0 + (b1 - b0) * frac)
    return f"#{r:02x}{g:02x}{b:02x}"


def _parse_conditions(body: str) -> dict | None:
    """'l.r=v l.r=v2' → conditions dict; repeated slots become lists."""
    conditions: dict = {}
    for part in body.split():
        if "=" not in part or "." not in part.split("=", 1)[0]:
            return None
        lr, value = part.split("=", 1)
        if lr in conditions:
            prev = conditions[lr]
            conditions[lr] = (prev if isinstance(prev, list) else [prev]) + [value]
        else:
            conditions[lr] = value
    return conditions or None


_TERM_HELP = """[b]memory[/b]
  tell <text>            absorb a fact (durable, shared)
  tell key=K <text>      absorb as the next version of K
  ask <question>         targeted retrieval (refuses 'I don't know')
  think <input>          broad associative recall
  recall <query>         lexical search, top matches + scores
[b]query[/b]
  count <l.r>=<v> ...    count entities matching ALL conditions
  find <l.r>=<v> ...     entities matching ALL conditions
  top <layer.role> [pred]  distribution
  list [filter]          keyed facts (current belief)
  fact <key>             anatomy of a fact: slots, chain, provenance
  history <key>          version chain
[b]session[/b]
  space [id]             show / switch space
  me [name]              show / set identity (resolves 'I/my')
  stats                  substrate vital signs
  clear                  clear the scrollback
  help                   this help

Bare text with no verb is treated as [b]ask[/b]."""


class Dashboard(VerticalScroll):
    """The home view: vital signs as terminal graphs, refreshed live."""

    def compose(self) -> ComposeResult:
        yield Static("dashboard", classes="view-title")
        yield Static(
            "schema-on-write memory · live vital signs", classes="view-sub"
        )
        with Horizontal(id="cards"):
            yield Static(id="card-thoughts", classes="card")
            yield Static(id="card-keys", classes="card")
            yield Static(id="card-multi", classes="card")
            yield Static(id="card-storage", classes="card")
        yield Static("slot fill by layer", classes="section")
        yield Static(id="bars", classes="panel")
        yield Static("facts this session", classes="section")
        yield Sparkline([0], id="spark", summary_function=max)

    def render_card(self, wid: str, value: Any, label: str, color: str) -> None:
        self.query_one(f"#{wid}", Static).update(
            f"[b {color}]{value}[/]\n[{TEXT_FAINT}]{label}[/]"
        )

    def render_bars(self, layer_fill: dict[str, int]) -> None:
        peak = max(layer_fill.values(), default=0) or 1
        width = 34
        lines = []
        for i, layer in enumerate(_LAYERS):
            n = int(layer_fill.get(layer, 0))
            filled = round(width * n / peak)
            color = _grad(i / (len(_LAYERS) - 1))
            bar = f"[{color}]{'█' * filled}[/]" + f"[{BORDER}]{'░' * (width - filled)}[/]"
            lines.append(
                f"[{TEXT_MUTED}]{layer:>12}[/] {bar} [{TEXT_SOFT}]{n}[/]"
            )
        self.query_one("#bars", Static).update("\n".join(lines))


class AdaApp(App):
    """The Ada terminal — one interface for the whole substrate."""

    TITLE = "ada"
    SUB_TITLE = "schema-on-write memory"

    CSS = f"""
    Screen {{ background: {INK_SUNKEN}; color: {TEXT}; }}

    #shell {{ height: 1fr; }}

    #rail {{
        width: 8; background: {INK}; border-right: solid {BORDER};
        padding: 1 0; align-horizontal: center;
    }}
    #rail .rail-brand {{
        color: {PRIMARY}; text-style: bold; width: 100%;
        text-align: center; margin-bottom: 1;
    }}
    .rail-btn {{
        width: 4; min-width: 4; height: 3; margin: 0 0 1 0;
        border: none; background: {INK};
        color: {TEXT_FAINT}; content-align: center middle;
    }}
    .rail-btn:hover {{ background: {INK_RAISED}; color: {TEXT_SOFT}; }}
    .rail-btn.-active {{ background: {INK_RAISED}; color: {PRIMARY}; text-style: bold; }}

    #main {{ width: 1fr; }}
    #topbar {{
        height: 1; background: {INK}; border-bottom: solid {BORDER};
        padding: 0 1;
    }}
    #crumb {{ width: 1fr; color: {TEXT_FAINT}; content-align: left middle; }}
    #status {{ width: auto; color: {TEXT_MUTED}; content-align: right middle; }}

    .view-title {{ color: {TEXT}; text-style: bold; padding: 1 2 0 2; }}
    .view-sub {{ color: {TEXT_FAINT}; padding: 0 2 1 2; }}
    .section {{ color: {ACCENT}; text-style: bold; padding: 1 2 0 2; }}
    .panel {{
        background: {INK}; border: round {BORDER}; padding: 1 2;
        margin: 0 2; color: {TEXT_SOFT};
    }}

    #cards {{ height: 5; padding: 0 1; }}
    .card {{
        width: 1fr; height: 4; margin: 0 1; padding: 1 2;
        background: {INK}; border: round {BORDER}; content-align: left top;
    }}

    #spark {{
        height: 4; margin: 0 2; background: {INK};
        border: round {BORDER};
    }}
    #spark > .sparkline--max-color {{ color: {PRIMARY}; }}
    #spark > .sparkline--min-color {{ color: {CALM}; }}

    #term {{ padding: 0 1; }}
    #term-log {{
        background: {INK}; border: round {BORDER}; padding: 0 1;
        height: 1fr; margin: 1 1 0 1;
    }}
    #term-input, #mem-input, #tok-input {{
        background: {INK}; border: round {BORDER}; margin: 1;
        color: {TEXT};
    }}
    #term-input:focus, #mem-input:focus, #tok-input:focus {{
        border: round {PRIMARY};
    }}

    DataTable {{ background: {INK}; margin: 0 1 1 1; height: 1fr; }}
    DataTable > .datatable--header {{
        background: {INK_RAISED}; color: {TEXT_SOFT}; text-style: bold;
    }}
    DataTable > .datatable--cursor {{ background: {INK_RAISED}; }}

    #tok-bar {{ height: auto; }}
    #tok-create {{
        width: auto; margin: 1 1 1 0; background: {INK_RAISED};
        color: {PRIMARY}; border: none;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "quit", show=True),
        Binding("1", "show('dash')", "dashboard", show=True),
        Binding("2", "show('term')", "terminal", show=True),
        Binding("3", "show('mem')", "memory", show=True),
        Binding("4", "show('tok')", "tokens", show=True),
    ]

    _RAIL = [
        ("dash", "▦", "dashboard"),
        ("term", "›_", "terminal"),
        ("mem", "⇄", "memory"),
        ("tok", "✱", "tokens"),
    ]

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.backend: Any = None
        self._connected = False
        self._session = {"space": "main", "me": None}
        self._series: deque[float] = deque(maxlen=60)

    # ── layout ────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        with Horizontal(id="shell"):
            with Vertical(id="rail"):
                yield Static("●", classes="rail-brand")
                for vid, glyph, tip in self._RAIL:
                    b = Button(glyph, id=f"nav-{vid}", classes="rail-btn")
                    b.tooltip = tip
                    yield b
            with Vertical(id="main"):
                with Horizontal(id="topbar"):
                    yield Static("ada / dashboard", id="crumb")
                    yield Static("○ connecting…", id="status")
                with ContentSwitcher(initial="dash", id="views"):
                    yield Dashboard(id="dash")
                    with Vertical(id="term"):
                        yield RichLog(id="term-log", wrap=True, markup=True,
                                      highlight=False)
                        yield Input(placeholder="tell / ask / think / count …  "
                                    "(type 'help')", id="term-input")
                    with Vertical(id="mem"):
                        yield Input(placeholder="filter keyed facts…",
                                    id="mem-input")
                        yield DataTable(id="mem-table", zebra_stripes=True)
                    with Vertical(id="tok"):
                        with Horizontal(id="tok-bar"):
                            yield Input(placeholder="name a new token…",
                                        id="tok-input")
                            yield Button("mint", id="tok-create")
                        yield DataTable(id="tok-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one(f"#nav-dash", Button).add_class("-active")
        mt = self.query_one("#mem-table", DataTable)
        mt.add_columns("key", "fact", "v")
        tt = self.query_one("#tok-table", DataTable)
        tt.add_columns("prefix", "name", "perms", "status", "expires")
        log = self.query_one("#term-log", RichLog)
        log.write(f"[{PRIMARY}]ada[/] [{TEXT_FAINT}]· one terminal for the "
                  f"whole substrate. type 'help'.[/]")
        self._connect()
        self.set_interval(3.0, self._refresh_dashboard)

    # ── connection ────────────────────────────────────────────────────
    @work(thread=True, exclusive=True)
    def _connect(self) -> None:
        try:
            from ada.tui.repl import ServerBackend
            backend = ServerBackend(self.url)
            self.backend = backend
            self._connected = True
            self.call_from_thread(self._on_connected)
        except Exception as exc:  # noqa: BLE001 — surface any failure in-UI
            self.call_from_thread(self._set_status, f"○ offline — {exc}", SIGNAL)

    def _on_connected(self) -> None:
        self._set_status(
            f"● online [{TEXT_FAINT}]· {self._session['space']}[/]", GREEN
        )
        self._refresh_dashboard()
        self._refresh_memory("")
        self._refresh_tokens()

    def _set_status(self, text: str, color: str = TEXT_MUTED) -> None:
        self.query_one("#status", Static).update(f"[{color}]{text}[/]")

    async def _call(self, tool: str, args: dict) -> dict:
        """Run a (blocking) MCP tool call off the event loop."""
        if not self.backend:
            return {"error": "not connected to a server"}
        a = dict(args)
        if self._session["space"] != "main" and "space" not in a:
            a["space"] = self._session["space"]
        if tool == "tell" and self._session["me"] and "speaker" not in a:
            a["speaker"] = self._session["me"]
        try:
            return await asyncio.to_thread(self.backend.call, tool, a)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # ── navigation ────────────────────────────────────────────────────
    def action_show(self, view: str) -> None:
        self.query_one("#views", ContentSwitcher).current = view
        for vid, _glyph, _tip in self._RAIL:
            self.query_one(f"#nav-{vid}", Button).set_class(vid == view, "-active")
        labels = {"dash": "dashboard", "term": "terminal",
                  "mem": "memory", "tok": "tokens"}
        self.query_one("#crumb", Static).update(f"ada / {labels[view]}")
        focus = {"term": "#term-input", "mem": "#mem-input", "tok": "#tok-input"}
        if view in focus:
            self.query_one(focus[view], Input).focus()

    @on(Button.Pressed, ".rail-btn")
    def _rail_click(self, event: Button.Pressed) -> None:
        assert event.button.id is not None
        self.action_show(event.button.id.removeprefix("nav-"))

    # ── dashboard ─────────────────────────────────────────────────────
    @work(exclusive=True, group="dash")
    async def _refresh_dashboard(self) -> None:
        if not self._connected:
            return
        r = await self._call("stats", {})
        if "error" in r:
            return
        dash = self.query_one(Dashboard)
        count = int(r.get("count", 0))
        dash.render_card("card-thoughts", count, "thoughts", PRIMARY)
        dash.render_card("card-keys", r.get("versioned_keys", 0),
                         "versioned keys", CALM)
        dash.render_card("card-multi", r.get("multi_version_keys", 0),
                         "multi-version", ACCENT)
        dash.render_card("card-storage", r.get("storage", "memory"),
                         "storage", GREEN)
        dash.render_bars(r.get("layer_fill", {}) or {})
        self._series.append(count)
        spark = self.query_one("#spark", Sparkline)
        spark.data = list(self._series) or [0]

    # ── terminal ──────────────────────────────────────────────────────
    @on(Input.Submitted, "#term-input")
    async def _term_submit(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return
        log = self.query_one("#term-log", RichLog)
        log.write(f"[{PRIMARY}]ada›[/] [{TEXT_SOFT}]{raw}[/]")
        await self._run_command(raw, log)

    async def _run_command(self, raw: str, log: RichLog) -> None:
        verb, _, rest = raw.partition(" ")
        verb = verb.lower()
        rest = rest.strip()

        def out(line: str) -> None:
            log.write(f"  {line}")

        def err(r: dict) -> bool:
            if "error" in r:
                out(f"[{SIGNAL}]{r['error']}[/]")
                return True
            return False

        async def do_ask(question: str) -> None:
            r = await self._call("ask", {"question": question})
            if err(r):
                return
            if r.get("refused"):
                out(f"[{TEXT_FAINT}]{r.get('answer') or 'I dont know.'}[/]")
                return
            conf = r.get("confidence")
            tail = f"  [{TEXT_FAINT}]{conf}[/]" if conf is not None else ""
            out(f"[{CALM}]{r.get('answer', '')}[/]{tail}")

        if verb in ("help", "?"):
            log.write(_TERM_HELP)
        elif verb == "clear":
            log.clear()
        elif verb == "space":
            if rest:
                self._session["space"] = rest
                out(f"[{TEXT_FAINT}]switched to space:[/] {rest}")
                self._set_status(f"● online [{TEXT_FAINT}]· {rest}[/]", GREEN)
                self._refresh_memory("")
            else:
                out(f"[{TEXT_FAINT}]current space:[/] {self._session['space']}")
        elif verb == "me":
            if rest:
                self._session["me"] = rest.lower()
                out(f"[{TEXT_FAINT}]you are:[/] {rest.lower()}")
            else:
                out(f"[{TEXT_FAINT}]identity:[/] {self._session['me'] or '(unset)'}")
        elif verb == "stats":
            r = await self._call("stats", {})
            if not err(r):
                for k, v in r.items():
                    out(f"[{TEXT_FAINT}]{k:<18}[/] {v}")
        elif verb == "tell":
            args = {"text": rest}
            if rest.startswith("key="):
                key, _, body = rest[4:].partition(" ")
                args = {"text": body.strip(), "key": key}
            r = await self._call("tell", args)
            if not err(r):
                if r.get("told"):
                    v = r.get("version")
                    out(f"[{GREEN}]absorbed[/]" + (f" [{TEXT_FAINT}]v{v}[/]" if v else ""))
                else:
                    out(f"[{TEXT_FAINT}]not stored ({r.get('reason', 'duplicate')})[/]")
                self._refresh_dashboard()
        elif verb == "ask":
            await do_ask(rest)
        elif verb == "think":
            r = await self._call("think", {"input": rest, "top_k": 8})
            if not err(r):
                acts = r.get("activated", [])
                if not acts:
                    out(f"[{TEXT_FAINT}](nothing surfaced)[/]")
                for a in acts:
                    out(f"[{TEXT_FAINT}][{a.get('similarity', 0):+.2f}][/] {a['content']}")
        elif verb == "recall":
            r = await self._call("recall", {"query": rest, "top_k": 8})
            if not err(r):
                res = r.get("results", [])
                if not res:
                    out(f"[{TEXT_FAINT}](no matches)[/]")
                for x in res:
                    tag = f"  [{TEXT_FAINT}][{x['key']}][/]" if x.get("key") else ""
                    out(f"[{TEXT_FAINT}][{x['similarity']:+.2f}][/] {x['content']}{tag}")
        elif verb in ("count", "find"):
            conditions = _parse_conditions(rest)
            if not conditions:
                out(f"[{TEXT_FAINT}]usage: {verb} layer.role=value …[/]")
            else:
                op = "count" if verb == "count" else "who"
                r = await self._call("query", {"op": op, "conditions": conditions})
                if not err(r):
                    out(f"[{CALM}]{r.get('answer')}[/]")
        elif verb == "top":
            parts = rest.split()
            if not parts or "." not in parts[0]:
                out(f"[{TEXT_FAINT}]usage: top layer.role [predicate][/]")
            else:
                q = {"op": "top", "slot": parts[0]}
                if len(parts) > 1:
                    q["predicate_contains"] = parts[1]
                r = await self._call("query", q)
                if not err(r):
                    out(f"[{CALM}]{r.get('answer')}[/]")
        elif verb in ("list", "keys"):
            self.action_show("mem")
            self._refresh_memory(rest)
            out(f"[{TEXT_FAINT}]→ see the Memory view[/]")
        elif verb == "fact":
            r = await self._call("inspect", {"key": rest})
            if not err(r):
                out(f"[{CALM}]{r.get('key') or r.get('thought_id')}[/]  {r.get('content')}")
                for sl in r.get("slots", []):
                    out(f"  [{TEXT_FAINT}]{sl['layer']}.{sl['role']:<14}[/] {sl['value']}")
        elif verb == "history":
            r = await self._call("history", {"key": rest})
            if not err(r):
                if not r.get("versions"):
                    out(f"[{TEXT_FAINT}]no history for {rest!r}[/]")
                for item in r.get("chain", []):
                    out(f"[{TEXT_FAINT}]v{item['version']}:[/] {item['content']}")
        else:
            # Bare text or an unrecognised verb → targeted ask over the line.
            await do_ask(raw)

    # ── memory ────────────────────────────────────────────────────────
    @on(Input.Submitted, "#mem-input")
    def _mem_submit(self, event: Input.Submitted) -> None:
        self._refresh_memory(event.value.strip())

    @work(exclusive=True, group="mem")
    async def _refresh_memory(self, q: str) -> None:
        if not self._connected:
            return
        args: dict = {"limit": 200}
        if q:
            args["q"] = q
        r = await self._call("keys", args)
        table = self.query_one("#mem-table", DataTable)
        table.clear()
        if "error" in r:
            return
        for f in r.get("facts", []):
            table.add_row(f["key"], f["content"], f"v{f['version']}")

    # ── tokens ────────────────────────────────────────────────────────
    @on(Button.Pressed, "#tok-create")
    @on(Input.Submitted, "#tok-input")
    async def _tok_create(self, event: Any) -> None:
        inp = self.query_one("#tok-input", Input)
        name = inp.value.strip() or "tui-token"
        inp.value = ""
        r = await self._call("create_token",
                             {"name": name, "permissions": ["read", "write"]})
        if "error" in r:
            self.notify(r["error"], severity="error", title="token")
        else:
            self.notify(
                f"{r.get('token')}\n\nshown once — store it now.",
                title=f"minted {name}", timeout=20,
            )
            self._refresh_tokens()

    @work(exclusive=True, group="tok")
    async def _refresh_tokens(self) -> None:
        if not self._connected:
            return
        r = await self._call("token_list", {})
        table = self.query_one("#tok-table", DataTable)
        table.clear()
        if "error" in r:
            return
        for t in r.get("tokens", []):
            table.add_row(
                t["prefix"], t["name"], ",".join(t.get("permissions", [])),
                t["status"], t.get("expires_at") or "never",
            )


def run_app(url: str) -> None:
    """Launch the Ada TUI against the MCP server at `url`."""
    AdaApp(url).run()
