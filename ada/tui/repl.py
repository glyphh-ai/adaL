"""
Ada interactive REPL — the admin interface to a running Ada server.

The REPL is an MCP client: every command is a tool call against the
server at ADA_URL (default http://localhost:8002/mcp), so the REPL,
Claude, and every other MCP client share ONE memory backed by SQL.
Writes are write-through durable; reads hit the server's in-process
indexes.

If no server is reachable, the REPL offers an OFFLINE SANDBOX — a
private in-memory space, clearly labeled, where nothing persists.

Commands:

    tell <text>         — absorb a fact ('tell key=foo text' for versioned)
    ask <question>      — targeted retrieval, refuses with 'I don't know'
    think <input>       — broad recall, returns matches
    count <l.r>=<v> ... — structured count (ALL conditions must hold)
    top <layer.role> [pred] — distribution, optional predicate filter
    find <l.r>=<v> ...  — entities matching ALL conditions
    history <key>       — version chain for a stable key
    stats               — substrate vital signs
    token create|list|revoke — manage API tokens (when auth is enabled)
    aurora              — load the 77-fact demo corpus
    quit                — exit

    PYTHONPATH=. python scripts/ada_repl.py [--url http://host:port/mcp]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# ── Colors / banner ───────────────────────────────────────────────────

_GRAD = ["\033[38;5;204m", "\033[38;5;177m", "\033[38;5;141m", "\033[38;5;111m"]
_BANNER = [
    " ⣼⢻⡄ ⣿⠛⠛⢻⡄ ⣼⢻⡄",
    "⣼⠃ ⢻⡄⣿  ⢸⡇⣼⠃ ⢻⡄",
    "⣿⠛⠛⢻⡇⣿  ⢸⡇⣿⠛⠛⢻⡇",
    "⠛  ⠘⠃⠛⠛⠛⠛ ⠛  ⠘⠃",
]
D = "\033[38;5;244m"
P = "\033[38;5;141m"
C = "\033[38;5;116m"
PINK = "\033[38;5;204m"
R = "\033[0m"


# ── Backends ──────────────────────────────────────────────────────────

class ServerBackend:
    """MCP client against a running Ada server (the normal mode)."""

    label = "server"

    def __init__(self, url: str):
        import httpx
        self.url = url
        self._http = httpx.Client(timeout=60.0)
        self._headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        token = os.environ.get("ADA_TOKEN")
        if token:
            self._headers["authorization"] = f"Bearer {token}"
        r = self._rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "ada-repl", "version": "0.7"},
        }, rpc_id=1)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self._headers["mcp-session-id"] = sid
        self._notify("notifications/initialized")

    def _rpc(self, method: str, params: dict, rpc_id: int = 2):
        body = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        return self._http.post(self.url, json=body, headers=self._headers)

    def _notify(self, method: str) -> None:
        self._http.post(self.url, json={"jsonrpc": "2.0", "method": method},
                        headers=self._headers)

    def call(self, tool: str, args: dict) -> dict:
        resp = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = resp.text
        m = re.search(r"^data: (.*)$", text, re.M)
        payload = json.loads(m.group(1)) if m else json.loads(text)
        if "error" in payload:
            return {"error": payload["error"].get("message", str(payload["error"]))}
        content = payload["result"]["content"][0]["text"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"answer": content}


class LocalBackend:
    """Offline sandbox: a private in-memory space. Nothing persists."""

    label = "OFFLINE SANDBOX — nothing persists"

    def __init__(self):
        from ada.cognitive.generate import build_llm_renderer
        from ada.cognitive.surface import CognitiveSurface
        from ada.encoder.llm_enricher import auto_enricher
        from ada.memory.thought_space import ThoughtSpace
        self.space = ThoughtSpace(enricher=auto_enricher())
        self.surface = CognitiveSurface(self.space, renderer=build_llm_renderer())

    def call(self, tool: str, args: dict) -> dict:
        from ada.cognitive.ops import execute_op
        if tool == "tell":
            stored = self.space.absorb(args["text"], key=args.get("key"))
            if stored is None:
                return {"told": False, "reason": "duplicate"}
            return {"told": True, "durable": False,
                    "thought_id": stored.thought_id,
                    "version": stored.metadata.get("_version")}
        if tool == "ask":
            a = self.surface.ask(args["question"])
            return {"refused": a.refused, "answer": a.rendered,
                    "fact": a.fact.content if a.fact else None,
                    "confidence": round(a.confidence, 3)}
        if tool == "think":
            act = self.surface.think(args["input"], top_k=args.get("top_k", 8))
            return {"activated": [
                {"content": t.content, "similarity": round(s, 3)}
                for t, s in zip(act.thoughts, act.similarities)]}
        if tool == "query":
            return {"answer": execute_op(self.space, args)}
        if tool == "history":
            chain = self.space.history(args["key"])
            return {"versions": len(chain), "chain": [
                {"version": t.metadata.get("_version"), "content": t.content}
                for t in chain]}
        if tool == "stats":
            return self.space.stats()
        return {"error": f"unknown tool {tool}"}


def connect(url: str):
    import httpx
    health = url.rsplit("/mcp", 1)[0] + "/health"
    try:
        if httpx.get(health, timeout=2.0).status_code == 200:
            return ServerBackend(url)
    except Exception:
        pass
    print(f"  {PINK}No Ada server at {url}.{R}")
    print(f"  {D}Start one with{R} make dev {D}(or `ada serve`) for shared, "
          f"durable memory.{R}")
    try:
        choice = input(f"  {D}Continue in offline sandbox? [y/N]{R} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)
    if choice != "y":
        sys.exit(1)
    return LocalBackend()


# ── Command helpers ───────────────────────────────────────────────────

HELP = """  commands:
    tell <text>             — absorb a fact (durable, shared)
    tell key=K <text>       — absorb as next version of K
    ask <question>          — targeted retrieval (refuses 'I don't know')
    think <input>           — broad recall
    count <l.r>=<v> ...     — count entities matching ALL conditions
    top <layer.role> [pred] — distribution (pred filters relational verbs)
    find <l.r>=<v> ...      — entities matching ALL conditions
    history <key>           — version chain
    stats                   — substrate vital signs
    token create [name]     — mint an API token (shown once)
    token list              — list tokens (prefixes only)
    token revoke <id|prefix>— revoke a token immediately
    aurora                  — load the 77-fact demo corpus
    help / ?                — this help
    quit / exit             — leave
"""


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


def _call(backend, tool: str, args: dict) -> dict:
    """Backend call wrapped in the braille spinner (server round-trips
    can take a second when the LLM renderer is involved)."""
    from ada.tui.cli import _BrailleSpinner
    spinner = _BrailleSpinner()
    spinner.start()
    try:
        return backend.call(tool, args)
    finally:
        spinner.stop()


def _show_error(result: dict) -> bool:
    if "error" in result:
        print(f"  {PINK}{result['error']}{R}")
        return True
    return False


# ── REPL loop ─────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get(
        "ADA_URL", f"http://localhost:{os.environ.get('PORT', '8002')}/mcp"))
    args = p.parse_args()
    run_repl(args.url)


def run_repl(url: str, banner: bool = True) -> None:
    backend = connect(url)

    if banner:
        for i, line in enumerate(_BANNER):
            print(f"  {_GRAD[min(i, len(_BANNER)-1)]}\033[1m{line}{R}")
        mode = (f"connected: {url}" if isinstance(backend, ServerBackend)
                else backend.label)
        print(f"  {D}schema-on-write memory · {mode}{R}")
        print(f"  {D}type 'help' for commands, 'quit' to exit{R}\n")

    while True:
        try:
            raw = input(f"  {P}ada{D}>{R} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw in ("quit", "exit", "q"):
            break
        if raw in ("help", "?"):
            print(HELP)
            continue

        if raw == "stats":
            r = _call(backend, "stats", {})
            if _show_error(r):
                continue
            for k, v in r.items():
                print(f"  {D}{k:<18}:{R} {v}")
            continue

        if raw == "aurora":
            sys.path.insert(0, "scripts")
            from hard_test import SESSION_1
            n = 0
            for text, key in SESSION_1:
                r = _call(backend, "tell", {"text": text, **({"key": key} if key else {})})
                n += bool(r.get("told"))
            print(f"  {D}loaded {n}/{len(SESSION_1)} Aurora facts.{R}")
            continue

        if raw == "token" or raw.startswith("token "):
            parts = raw.split()
            sub = parts[1] if len(parts) > 1 else "list"
            if sub == "create":
                name = parts[2] if len(parts) > 2 else "repl-token"
                r = _call(backend, "create_token", {"name": name})
                if not _show_error(r):
                    print(f"  {C}{r.get('token')}{R}")
                    print(f"  {D}id {r.get('id')} · perms "
                          f"{','.join(r.get('permissions', []))} · "
                          f"shown ONCE — store it now{R}")
            elif sub == "revoke" and len(parts) > 2:
                r = _call(backend, "token_revoke", {"token": parts[2]})
                if not _show_error(r):
                    print(f"  {D}revoked: {', '.join(r.get('revoked', []))}{R}")
            else:
                r = _call(backend, "token_list", {})
                if not _show_error(r):
                    toks = r.get("tokens", [])
                    if not toks:
                        print(f"  {D}no tokens{R}")
                    for t in toks:
                        print(f"  {D}{t['prefix']:<14} {t['name']:<16} "
                              f"{','.join(t['permissions']):<12} {t['status']}"
                              f"{' · expires ' + t['expires_at'] if t['expires_at'] else ''}{R}")
            continue

        if raw.startswith("history "):
            key = raw[len("history "):].strip()
            r = _call(backend, "history", {"key": key})
            if _show_error(r):
                continue
            if not r.get("versions"):
                print(f"  {D}no history for {key!r}{R}")
                continue
            for item in r["chain"]:
                print(f"  {D}v{item['version']}:{R} {item['content']}")
            continue

        if raw.startswith("count ") or raw.startswith("find "):
            cmd, body = raw.split(" ", 1)
            conditions = _parse_conditions(body.strip())
            if not conditions:
                print(f"  {D}usage: {cmd} layer.role=value [layer.role=value ...]{R}")
                continue
            op = "count" if cmd == "count" else "who"
            r = _call(backend, "query", {"op": op, "conditions": conditions})
            if _show_error(r):
                continue
            print(f"  {C}{r['answer']}{R}")
            continue

        if raw.startswith("top "):
            parts = raw[len("top "):].strip().split()
            if not parts or "." not in parts[0]:
                print(f"  {D}usage: top layer.role [predicate_filter]{R}")
                continue
            q = {"op": "top", "slot": parts[0]}
            if len(parts) > 1:
                q["predicate_contains"] = parts[1]
            r = _call(backend, "query", q)
            if _show_error(r):
                continue
            print(f"  {C}{r['answer']}{R}")
            continue

        if raw.startswith("tell ") or raw.startswith("write "):
            _, _, body = raw.partition(" ")
            body = body.strip()
            key = None
            if body.startswith("key="):
                head, _, body = body.partition(" ")
                key = head[len("key="):]
            if not body:
                print(f"  {D}usage: tell [key=K] <text>{R}")
                continue
            r = _call(backend, "tell", {"text": body, **({"key": key} if key else {})})
            if _show_error(r):
                continue
            if not r.get("told"):
                print(f"  {D}(duplicate, not absorbed){R}")
                continue
            v = r.get("version")
            tag = f" v{v}" if v else ""
            durable = "" if r.get("durable", True) else f"  {PINK}(NOT persisted){R}"
            print(f"  {D}absorbed{tag}: {R}{r.get('thought_id')}{durable}")
            continue

        if raw.startswith("think "):
            r = _call(backend, "think", {"input": raw[len("think "):].strip(), "top_k": 6})
            if _show_error(r):
                continue
            hits = r.get("activated", [])
            if not hits:
                print(f"  {D}(no activation){R}")
                continue
            for h in hits:
                print(f"    {D}[{h['similarity']:+.2f}]{R}  {h['content']}")
            continue

        # `ask ...` or bare question
        q = raw[len("ask "):].strip() if raw.startswith("ask ") else raw
        r = _call(backend, "ask", {"question": q})
        if _show_error(r):
            continue
        print(f"  {C}{r.get('answer')}{R}")
        if r.get("fact"):
            print(f"  {D}grounded in: {r['fact']}{R}")

    print(f"  {D}bye.{R}")


if __name__ == "__main__":
    main()
