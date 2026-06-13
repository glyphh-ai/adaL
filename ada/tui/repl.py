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
B = "\033[38;5;111m"
G = "\033[38;5;114m"
W = "\033[37m"
PINK = "\033[38;5;204m"
BOLD = "\033[1m"
R = "\033[0m"


def _connect_configs(url: str, token: str) -> None:
    """Print copy-paste MCP configs for every client, token embedded."""
    auth = f"Authorization: Bearer {token}"
    print(f"\n  {G}{BOLD}Token minted — shown once. Store it now.{R}")
    print(f"  {C}{token}{R}\n")
    print(f"  {B}{BOLD}Claude Code{R}  {D}(or run: connect claude){R}")
    print(f"  {W}claude mcp add ada --transport http {url} "
          f"--header \"{auth}\"{R}\n")
    print(f"  {B}{BOLD}Claude Desktop{R}  {D}(claude_desktop_config.json){R}")
    print(f'  {W}{{"mcpServers":{{"ada":{{"transport":"http","url":"{url}",'
          f'"headers":{{"Authorization":"Bearer {token}"}}}}}}}}{R}\n')
    print(f"  {B}{BOLD}Cursor / VS Code{R}  {D}(MCP settings){R}")
    print(f'  {W}{{"ada":{{"transport":"http","url":"{url}",'
          f'"headers":{{"Authorization":"Bearer {token}"}}}}}}{R}\n')
    print(f"  {B}{BOLD}ChatGPT · Gemini · any MCP client{R}")
    print(f"  {W}Endpoint:{R} {url}")
    print(f"  {W}Header:  {R} {auth}\n")
    print(f"  {D}revoke anytime:  token revoke {token[:12]}{R}\n")


def _connect_claude(url: str, token: str) -> None:
    """Auto-wire Claude Code with the auth header."""
    import shutil
    import subprocess
    auth = f"Authorization: Bearer {token}"
    if not shutil.which("claude"):
        print(f"\n  {D}claude CLI not found — install: "
              f"npm i -g @anthropic-ai/claude-code{R}")
        _connect_configs(url, token)
        return
    try:
        r = subprocess.run(
            ["claude", "mcp", "add", "ada", "--transport", "http", url,
             "--header", auth],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            print(f"\n  {G}{BOLD}Connected.{R} Ada is wired into Claude Code "
                  f"with a fresh token.")
            print(f"  {C}{token}{R}  {D}(stored once — revoke: "
                  f"token revoke {token[:12]}){R}\n")
        elif "already exists" in (r.stderr or "").lower():
            print(f"\n  {D}'ada' already configured. To swap in this token: "
                  f"claude mcp remove ada, then connect claude again.{R}\n")
            _connect_configs(url, token)
        else:
            print(f"\n  {PINK}claude mcp add failed:{R} {r.stderr.strip()}")
            _connect_configs(url, token)
    except Exception as e:
        print(f"\n  {PINK}error:{R} {e}")
        _connect_configs(url, token)


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
   memory
    tell <text>             — absorb a fact (durable, shared)
    tell key=K <text>       — absorb as next version of K
    ask <question>          — targeted retrieval (refuses 'I don't know')
    think <input>           — broad associative recall
    recall <query>          — lexical search, top matches + scores
   query
    count <l.r>=<v> ...     — count entities matching ALL conditions
    find <l.r>=<v> ...      — entities matching ALL conditions
    top <layer.role> [pred] — distribution (pred filters relational verbs)
    list [filter]           — keyed facts (current belief)
    fact <key>              — anatomy of a fact: slots, chain, provenance
    history <key>           — version chain
    similar <entity> [k]    — nearest profiles by exact jaccard
    drift <entity> [days]   — what moved in the window (added/dropped/churn)
   curate
    merges                  — deterministic alias proposals
    merge <src> => <tgt>    — merge src into tgt (run again with `confirm`)
    consolidate [dry]       — maintenance: re-enrich · resolve identity · dedup
    amend <key> <text>      — fix a fact in place (no new version)
    amend id <tid> <text>   — fix a specific version in place
    archive <l.r>=<v> ...   — soft-remove a cohort, reversible (+ `confirm`)
    forget <key>            — erase a key's whole chain (+ `confirm`)
    forget entity <name>    — erase every fact of an entity (+ `confirm`)
    forget all <space>      — wipe the whole space (type the space name)
   session / admin
    stats                   — substrate vital signs
    space [id]              — show / switch space
    me [name]               — show / set identity (resolves 'I/my')
    config                  — storage mode, space, identity
    connect                 — mint a token + print MCP configs (all clients)
    connect claude          — auto-wire Claude Code (with auth header)
    token create [name]     — mint an API token (shown once)
    token list              — list tokens (prefixes only)
    token revoke <id|pfx>   — revoke a token immediately
    token delete <id|pfx>   — delete a revoked token's record
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


# Session state: current space + identity, injected into every call.
_SESSION = {"space": "main", "me": None}


def _call(backend, tool: str, args: dict) -> dict:
    """Backend call wrapped in the braille spinner. Injects the session's
    current space (and speaker identity on writes) automatically."""
    from ada.tui.cli import _BrailleSpinner
    args = dict(args)
    if _SESSION["space"] != "main" and "space" not in args:
        args["space"] = _SESSION["space"]
    if tool == "tell" and _SESSION["me"] and "speaker" not in args:
        args["speaker"] = _SESSION["me"]
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

        if raw == "connect" or raw.startswith("connect "):
            parts = raw.split()
            target = parts[1] if len(parts) > 1 else "show"
            name = (parts[2] if len(parts) > 2
                    else ("claude-code" if target == "claude" else "mcp-client"))
            # provisioning a token IS the first step — connect always mints
            tok = _call(backend, "create_token",
                        {"name": name, "permissions": ["read", "write"]})
            if _show_error(tok):
                print(f"  {D}minting a token needs an admin credential — set "
                      f"ADA_TOKEN to an admin token, or run the local "
                      f"bootstrap.{R}")
                continue
            raw_token = tok.get("token", "")
            if target == "claude":
                _connect_claude(url, raw_token)
            else:
                _connect_configs(url, raw_token)
            continue

        if raw == "space" or raw.startswith("space "):
            parts = raw.split()
            if len(parts) > 1:
                _SESSION["space"] = parts[1]
                print(f"  {D}switched to space:{R} {parts[1]}")
            else:
                print(f"  {D}current space:{R} {_SESSION['space']}")
            continue

        if raw == "me" or raw.startswith("me "):
            parts = raw.split(maxsplit=1)
            if len(parts) > 1:
                _SESSION["me"] = parts[1].strip().lower()
                print(f"  {D}you are:{R} {_SESSION['me']} "
                      f"{D}(your 'I/my' facts attach to this identity){R}")
            else:
                print(f"  {D}identity:{R} {_SESSION['me'] or '(unset)'}")
            continue

        if raw == "config" or raw.startswith("config "):
            parts = raw.split()
            if len(parts) == 1:
                r = _call(backend, "stats", {})
                mode = r.get("storage", "memory") if isinstance(r, dict) else "memory"
                print(f"  {D}storage mode :{R} {mode}")
                print(f"  {D}current space:{R} {_SESSION['space']}")
                print(f"  {D}identity     :{R} {_SESSION['me'] or '(unset)'}")
                print(f"  {D}(storage mode is server-side: set ADA_STORAGE="
                      f"sql and restart){R}")
            elif parts[1].startswith("storage="):
                print(f"  {PINK}storage mode is a server setting.{R} "
                      f"{D}Set ADA_STORAGE={parts[1][8:]} in the environment "
                      f"and restart the server.{R}")
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
            elif sub == "delete" and len(parts) > 2:
                r = _call(backend, "token_delete", {"token": parts[2]})
                if not _show_error(r):
                    print(f"  {D}deleted: {', '.join(r.get('deleted', []))}{R}")
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

        if raw.startswith("recall "):
            r = _call(backend, "recall", {"query": raw[len("recall "):].strip(),
                                          "top_k": 8})
            if _show_error(r):
                continue
            res = r.get("results", [])
            if not res:
                print(f"  {D}(no matches){R}")
                continue
            for x in res:
                tag = f"  {D}[{x['key']}]{R}" if x.get("key") else ""
                print(f"    {D}[{x['similarity']:+.2f}]{R}  {x['content']}{tag}")
            continue

        if raw == "list" or raw == "keys" or raw.startswith("list ") \
                or raw.startswith("keys "):
            _, _, q = raw.partition(" ")
            args = {"limit": 60}
            if q.strip():
                args["q"] = q.strip()
            r = _call(backend, "keys", args)
            if _show_error(r):
                continue
            facts = r.get("facts", [])
            if not facts:
                print(f"  {D}no keyed facts{R}")
                continue
            for f in facts:
                print(f"  {C}{f['key']:<22}{R} {f['content']}  {D}v{f['version']}{R}")
            continue

        if raw.startswith("fact "):
            r = _call(backend, "inspect", {"key": raw[len("fact "):].strip()})
            if _show_error(r):
                continue
            print(f"  {C}{r.get('key') or r.get('thought_id')}{R}  {r.get('content')}")
            print(f"  {D}entity {r.get('entity') or '—'} · speaker "
                  f"{r.get('speaker')} · {(r.get('created_at') or '')[:16]}{R}")
            if r.get("key"):
                print(f"  {D}v{r.get('version')} of {r.get('versions')}{R}")
            for sl in r.get("slots", []):
                print(f"    {D}{sl['layer']}.{sl['role']:<14}{R} {sl['value']}")
            chain = r.get("chain") or []
            if len(chain) > 1:
                for v in chain:
                    print(f"  {D}v{v['version']}:{R} {v['content']}")
            continue

        if raw.startswith("similar "):
            parts = raw[len("similar "):].split()
            k = 5
            if len(parts) > 1 and parts[-1].isdigit():
                k = int(parts[-1]); parts = parts[:-1]
            ent = " ".join(parts)
            r = _call(backend, "similar", {"entity": ent, "k": k})
            if _show_error(r):
                continue
            sim = r.get("similar", [])
            if not sim:
                print(f"  {D}{ent} shares no slot value — it stands alone{R}")
                continue
            for e in sim:
                print(f"  {C}{e['name']:<18}{R} {D}jaccard {e['similarity']}{R}")
                print(f"    {D}shared: {' · '.join(e['shared'][:4])}{R}")
            continue

        if raw.startswith("drift "):
            parts = raw[len("drift "):].split()
            days = 30
            if len(parts) > 1 and parts[-1].isdigit():
                days = int(parts[-1]); parts = parts[:-1]
            ent = " ".join(parts)
            r = _call(backend, "drift", {"entity": ent, "window_days": days})
            if _show_error(r):
                continue
            print(f"  {C}drift {r.get('drift')}{R}  {D}{ent} · last {days}d · "
                  f"+{len(r.get('added', []))} −{len(r.get('dropped', []))} · "
                  f"{len(r.get('churned_keys', []))} keys churned{R}")
            for d in r.get("added", [])[:6]:
                print(f"    {C}+ {d}{R}")
            for d in r.get("dropped", [])[:6]:
                print(f"    {PINK}− {d}{R}")
            continue

        if raw == "merges":
            r = _call(backend, "merge_candidates", {})
            if _show_error(r):
                continue
            cands = r.get("candidates", [])
            if not cands:
                print(f"  {D}no alias proposals — every name stands alone{R}")
                continue
            for c in cands:
                print(f"  {C}{c['a']}{R} ≈ {C}{c['b']}{R}  {D}overlap {c['score']}{R}")
                if c["shared"]:
                    print(f"    {D}shared: {' · '.join(c['shared'][:4])}{R}")
                if c["conflicts"]:
                    print(f"    {PINK}conflicts: {' · '.join(c['conflicts'])}{R}")
                print(f"    {D}merge: merge {c['a']} => {c['b']}{R}")
            continue

        if raw.startswith("merge "):
            body = raw[len("merge "):].strip()
            confirm = body.endswith(" confirm")
            if confirm:
                body = body[:-len(" confirm")].strip()
            if "=>" in body:
                src, tgt = [x.strip().lower() for x in body.split("=>", 1)]
            else:
                p = body.split()
                src, tgt = (p[0].lower(), p[1].lower()) if len(p) == 2 else (None, None)
            if not src or not tgt:
                print(f"  {D}usage: merge <source> => <target> [confirm]"
                      f"  (target absorbs source){R}")
                continue
            r = _call(backend, "merge", {"source": src, "target": tgt,
                                         "dry_run": not confirm})
            if _show_error(r):
                continue
            if confirm:
                print(f"  {D}merged {src} → {tgt} · {r.get('facts')} facts "
                      f"re-pointed · sentences kept verbatim{R}")
            else:
                print(f"  {PINK}would merge {src} → {tgt} · {r.get('facts')} facts{R}")
                print(f"  {D}run: merge {src} => {tgt} confirm{R}")
            continue

        if raw == "consolidate" or raw == "consolidate dry":
            dry = raw.endswith("dry")
            a = {"dry_run": dry}
            if _SESSION["me"]:
                a["me"] = _SESSION["me"]
            r = _call(backend, "consolidate", a)
            if _show_error(r):
                continue
            print(f"  {D}{'preview' if dry else 'consolidated'} · "
                  f"{r.get('scanned')} scanned · re-enriched "
                  f"{r.get('re_enriched')} · identity "
                  f"{r.get('identity_resolved')} · dups "
                  f"{len(r.get('duplicates_archived', []))}{R}")
            for d in r.get("duplicates_archived", []):
                print(f"    {D}archived “{d['archived']}” ⇒ kept “{d['kept']}”{R}")
            if not _SESSION["me"]:
                print(f"  {D}tip: set `me <name>` first to resolve first-person facts{R}")
            continue

        if raw.startswith("archive "):
            body = raw[len("archive "):].strip()
            confirm = body.endswith(" confirm")
            if confirm:
                body = body[:-len(" confirm")].strip()
            conditions = _parse_conditions(body)
            if not conditions:
                print(f"  {D}usage: archive l.r=v [l.r=v ...] [confirm]{R}")
                continue
            r = _call(backend, "archive", {"conditions": conditions,
                                           "dry_run": not confirm})
            if _show_error(r):
                continue
            verb_word = "archived" if confirm else "would archive"
            print(f"  {PINK if not confirm else D}{verb_word} {r.get('facts')} "
                  f"facts of {r.get('entities_matched')} entities{R}")
            if not confirm and r.get("facts"):
                print(f"  {D}run: archive {body} confirm{R}")
            continue

        if raw.startswith("amend "):
            # amend <key> <new text>  ·  amend id <tid> <new text>
            # fixes a fact in place (no new version)
            body = raw[len("amend "):].strip()
            parts = body.split(None, 1)
            if parts and parts[0] == "id" and len(parts) == 2:
                idtext = parts[1].split(None, 1)
                if len(idtext) < 2:
                    print(f"  {D}usage: amend id <thought_id> <new text>{R}")
                    continue
                req = {"thought_id": idtext[0], "text": idtext[1]}
                label = "fact " + idtext[0]
            elif len(parts) == 2:
                req = {"key": parts[0].lower(), "text": parts[1]}
                label = "key " + parts[0].lower() + " (current version)"
            else:
                print(f"  {D}usage: amend <key> <new text>  ·  "
                      f"amend id <tid> <new text>{R}")
                continue
            r = _call(backend, "amend", req)
            if _show_error(r):
                continue
            print(f"  {D}amended in place — {label} · v{r.get('version')} "
                  f"(no new version){R}")
            continue

        if raw == "forget" or raw.startswith("forget "):
            body = raw[len("forget"):].strip()
            confirm = body == "confirm" or body.endswith(" confirm")
            if confirm:
                body = "" if body == "confirm" else body[:-len(" confirm")].rstrip()
            # forget all [space] — wipe the whole space (typed confirm)
            if body == "all" or body.startswith("all "):
                arg = body[len("all"):].strip().lower()
                a = {"dry_run": not arg}
                if arg:
                    a["confirm"] = arg
                r = _call(backend, "forget_all", a)
                if _show_error(r):
                    continue
                sp = r.get("space", _SESSION["space"])
                if r.get("dry_run"):
                    if not r.get("facts"):
                        print(f"  {D}space {sp} is already empty{R}")
                    else:
                        print(f"  {PINK}would erase ALL {r['facts']} facts "
                              f"in space {sp}{R}")
                        print(f"  {D}no undo. run: forget all {sp}{R}")
                else:
                    print(f"  {D}erased {r['facts']} facts — space {sp} "
                          f"is empty{R}")
                continue
            # forget <key> | forget entity <name> | forget id <tid>
            parts = body.split(None, 1)
            if len(parts) == 2 and parts[0] in ("entity", "id"):
                scope = ({"entity": parts[1].strip().lower()} if parts[0] == "entity"
                         else {"thought_id": parts[1].strip()})
                label = f"{parts[0]} {parts[1].strip()}"
            elif body:
                scope = {"key": body.lower()}
                label = f"key {body.lower()}"
            else:
                print(f"  {D}usage: forget <key> | forget entity <name> | "
                      f"forget id <tid> | forget all   [confirm]{R}")
                continue
            r = _call(backend, "forget", {**scope, "dry_run": not confirm})
            if _show_error(r):
                continue
            n = r.get("facts", 0)
            plural = "" if n == 1 else "s"
            if confirm:
                print(f"  {D}erased {n} fact{plural} — {label}{R}")
            elif not n:
                print(f"  {D}nothing matches {label}{R}")
            else:
                print(f"  {PINK}would erase {n} fact{plural} — {label}{R}")
                print(f"  {D}no undo. run: forget {body} confirm{R}")
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
