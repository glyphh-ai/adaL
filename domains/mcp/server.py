"""
MCP Server — Ada's substrate exposed as deterministic skills.

Cognitive surfaces:
  think(input)        — broad recall, returns what matches
  ask(question)       — targeted retrieval, one fact + confidence
  tell(text[,key])    — absorb a fact (optional versioning)
  tell_raw(facts[,key]) — absorb a pre-structured universal-schema fact (no LLM)

Deterministic skills (no LLM in the path):
  recall(query)       — lexical search, top-k matches + similarity
  history(key)        — full version chain for a versioned key
  stats()             — substrate vital signs

Access management:
  create_token(...)   — mint an API token for this MCP server

This is the tool surface an LLM drives: the model decides WHAT to do
(chat, ingest, query); these tools guarantee HOW (deterministic scans).
"""

import json
import logging
from typing import Any

from mcp.server.lowlevel.server import Server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)

from domains.auth.service import AuthService

logger = logging.getLogger(__name__)

# Single-tenant runtime: every thought/token lives under one org.
ADA_ORG_ID = "ada"


def create_mcp_server(brain: Any, auth_service: AuthService) -> Server:
    """Create the MCP server with three cognitive tools.

    Args:
        brain: The Brain instance (domains.brain.think.Brain)
        auth_service: AuthService for token validation
    """
    app = Server("ada")

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="think",
                description=(
                    "Pure associative recall over Ada's substrate. Surfaces the "
                    "constellation of thoughts that resonate with the input — "
                    "no answer, no refusal, no synthesis. Call this when you "
                    "want CONTEXT to bring into a response."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "input": {"type": "string"},
                        "top_k": {"type": "integer", "default": 8},
                        "space": {"type": "string"},
                    },
                    "required": ["input"],
                },
            ),
            Tool(
                name="ask",
                description=(
                    "Targeted retrieval — find me the fact that answers this "
                    "question. Returns a single fact + confidence, or refuses "
                    "with 'I don't know.' Call this when you NEED a specific "
                    "answer and would rather be told 'no' than guess."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "space": {"type": "string"},
                        "speaker": {
                            "type": "string",
                            "description": "who is asking — first-person "
                                "tokens (my/i/me) resolve to this entity "
                                "before retrieval",
                        },
                    },
                    "required": ["question"],
                },
            ),
            Tool(
                name="tell",
                description=(
                    "Tell Ada something to remember. Optional `key` makes "
                    "this a new version of that key (versioned chain, drift "
                    "queryable). Call this on every decision or observation "
                    "you'd want to recall later."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "key": {"type": "string"},
                        "space": {"type": "string", "description": "space id (default 'main')"},
                        "speaker": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="tell_raw",
                description=(
                    "Programmatically tell Ada a pre-structured fact. NO LLM "
                    "in the path — bypasses the enricher entirely. Use this "
                    "for curriculum loaders, batch importers, or anywhere you "
                    "know the universal-schema slot fill ahead of time. The "
                    "`facts` argument is {layer: {role: value}} matching the "
                    "universal schema (entity, perceptual, spatial, temporal, "
                    "relational, quantitative, epistemic)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "facts": {
                            "type": "object",
                            "description": "Universal-schema slot fill, e.g. "
                                "{\"entity\": {\"name\": \"blue\", \"kind\": "
                                "\"color\"}, \"perceptual\": {\"wavelength\": "
                                "\"470\"}}",
                        },
                        "key": {"type": "string"},
                        "text": {
                            "type": "string",
                            "description": "Optional human-readable label "
                                "(synthesized from facts if omitted).",
                        },
                        "space": {"type": "string", "description": "space id (default 'main')"},
                    },
                    "required": ["facts"],
                },
            ),
            Tool(
                name="recall",
                description=(
                    "Deterministic lexical search over Ada's substrate "
                    "(no LLM). Returns the top matching thoughts with "
                    "similarity scores and their versioned key."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                        "space": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="history",
                description=(
                    "The full version chain for a versioned key (e.g. "
                    "'market.SPY', 'chris.age') in chronological order."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"key": {"type": "string"},
                                   "space": {"type": "string"}},
                    "required": ["key"],
                },
            ),
            Tool(
                name="query",
                description=(
                    "Run ONE structured query operation against the "
                    "substrate — the closed op set: lookup / prev / count / "
                    "count_not / top / who / compare. Exact, deterministic, "
                    "no LLM. Conditions are {'layer.role': value} (value may "
                    "be a list when one slot must hold several values). "
                    "Examples: {\"op\":\"count\",\"conditions\":"
                    "{\"spatial.location\":\"boston\"}} · "
                    "{\"op\":\"top\",\"slot\":\"relational.object\","
                    "\"predicate_contains\":\"work\"} · "
                    "{\"op\":\"who\",\"conditions\":{\"perceptual.color\":"
                    "\"blue\",\"relational.object\":[\"engineer\",\"chess\"]}}"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "op": {"type": "string",
                               "enum": ["lookup", "prev", "count", "count_not",
                                        "top", "who", "compare"]},
                        "person": {"type": "string"},
                        "slot": {"type": "string"},
                        "conditions": {"type": "object"},
                        "value": {"type": "string"},
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                        "k": {"type": "integer", "default": 5},
                        "predicate_contains": {"type": "string"},
                        "space": {"type": "string"},
                    },
                    "required": ["op"],
                },
            ),
            Tool(
                name="keys",
                description=(
                    "Current belief for every versioned key in a space, "
                    "newest first — the workbench slot grid. Superseded "
                    "versions excluded; use `history` for the chain."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 60},
                        "space": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="stats",
                description=(
                    "Substrate vital signs: total thoughts, versioned keys, "
                    "multi-version keys, and per-layer slot fill."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="consolidate",
                description=(
                    "Offline maintenance pass over a space: re-enrich "
                    "slotless facts, retroactively resolve first-person "
                    "facts to the operator's entity (`me`), archive "
                    "near-duplicate misspellings (newer wins). "
                    "Deterministic, never in the answer path. dry_run "
                    "previews without writing."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "space": {"type": "string"},
                        "me": {"type": "string",
                               "description": "operator identity for "
                                   "retroactive first-person resolution"},
                        "dry_run": {"type": "boolean", "default": False},
                    },
                },
            ),
            Tool(
                name="token_list",
                description=(
                    "List API tokens for this server (prefix, name, "
                    "permissions, status, expiry). Never returns raw tokens."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="token_revoke",
                description=(
                    "Revoke an API token by id or prefix. Revocation is "
                    "immediate and permanent."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"token": {"type": "string",
                                             "description": "token id or prefix"}},
                    "required": ["token"],
                },
            ),
            Tool(
                name="create_token",
                description=(
                    "Mint an API token for accessing this MCP server. The raw "
                    "token is returned ONCE — store it now. Optionally scope by "
                    "permissions and expiry."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "default": "repl-token"},
                        "permissions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["read", "write"],
                        },
                        "expires_days": {"type": "integer"},
                        "model_id": {"type": "string"},
                    },
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> CallToolResult:
        args = arguments or {}

        if name == "think":
            return await _handle_think(brain, args)
        if name == "ask":
            return await _handle_ask(brain, args)
        if name == "tell":
            return await _handle_tell(brain, args)
        if name == "tell_raw":
            return await _handle_tell_raw(brain, args)
        if name == "recall":
            return await _handle_recall(brain, args)
        if name == "history":
            return await _handle_history(brain, args)
        if name == "query":
            return await _handle_query(brain, args)
        if name == "keys":
            return await _handle_keys(brain, args)
        if name == "consolidate":
            return await _handle_consolidate(brain, args)
        if name == "stats":
            return await _handle_stats(brain, args)
        if name == "create_token":
            return await _handle_create_token(brain, args)
        if name == "token_list":
            return await _handle_token_list(brain, args)
        if name == "token_revoke":
            return await _handle_token_revoke(brain, args)
        return _err(f"Unknown tool: {name}")

    return app


# ── handlers ────────────────────────────────────────────────────────

async def _handle_think(brain, args: dict) -> CallToolResult:
    input_text = args.get("input", "")
    top_k = int(args.get("top_k", 8))
    if not input_text:
        return _err("Missing 'input' parameter")
    try:
        store, _ = _space(brain, args)
        results = await _maybe(store.recall(input_text, top_k=top_k,
                                            exclude_speakers=("ada",)))
        return _ok({
            "input": input_text, "space": store.space_id,
            "activated": [
                {"content": r.thought.content,
                 "similarity": round(float(r.global_similarity), 3)}
                for r in results
            ],
        })
    except Exception as e:
        logger.error("think failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_ask(brain, args: dict) -> CallToolResult:
    question = args.get("question", "")
    if not question:
        return _err("Missing 'question' parameter")
    try:
        from ada.memory.thought_space import resolve_question_identity
        store, _ = _space(brain, args)
        surface = _get_surface(brain, store)
        resolved = resolve_question_identity(question, args.get("speaker"))
        a = await surface.ask_async(resolved)
        out = {
            "question": question, "space": store.space_id,
            "refused": a.refused,
            "confidence": round(a.confidence, 3),
            "fact": a.fact.content if a.fact else None,
            "answer": a.rendered,
        }
        if resolved != question:
            out["resolved_question"] = resolved
        return _ok(out)
    except Exception as e:
        logger.error("ask failed: %s", e, exc_info=True)
        return _err(str(e))


async def _persist_now(brain, stored) -> bool:
    """Write-through: persist synchronously; fall back to the background
    queue on failure so the fact is retried rather than lost."""
    try:
        from ada.memory.thought_persistence import save_thought
        await save_thought(brain._session_factory, stored)
        return True
    except Exception:
        logger.warning("write-through failed; queued for retry", exc_info=True)
        brain._persist_queue.append(stored)
        return False


def _space(brain, args: dict):
    """Resolve the target space store. `space` arg selects it; default 'main'.
    Returns (store, is_sql)."""
    space_id = args.get("space") or "main"
    store = brain.space(space_id)
    return store, getattr(store, "is_sql", False)


async def _maybe(value):
    """Await coroutines, pass through plain values — so handlers work
    against both the sync ThoughtSpace and the async SqlFactStore."""
    import inspect
    return await value if inspect.isawaitable(value) else value


async def _handle_tell_raw(brain, args: dict) -> CallToolResult:
    facts = args.get("facts") or {}
    key = args.get("key")
    text = args.get("text")
    if not facts or not isinstance(facts, dict):
        return _err("Missing or invalid 'facts' parameter (must be dict)")
    try:
        store, is_sql = _space(brain, args)
        stored = await _maybe(store.tell_raw(facts=facts, key=key, text=text,
                                             speaker="curriculum"))
        if stored is None:
            return _ok({"told": False, "reason": "duplicate or empty"})
        durable = True if is_sql else await _persist_now(brain, stored)
        return _ok({
            "told": True, "durable": durable, "space": store.space_id,
            "thought_id": stored.thought_id,
            "version": stored.metadata.get("_version"),
            "key": stored.metadata.get("_key"),
            "synthesized_text": stored.content,
        })
    except Exception as e:
        logger.error("tell_raw failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_tell(brain, args: dict) -> CallToolResult:
    text = args.get("text", "")
    key = args.get("key")
    if not text:
        return _err("Missing 'text' parameter")
    try:
        store, is_sql = _space(brain, args)
        speaker = args.get("speaker") or "incoming"
        stored = await _maybe(store.absorb(text, key=key, speaker=speaker))
        if stored is None:
            return _ok({"told": False, "reason": "duplicate"})
        durable = True if is_sql else await _persist_now(brain, stored)
        return _ok({
            "told": True, "durable": durable, "space": store.space_id,
            "thought_id": stored.thought_id,
            "version": stored.metadata.get("_version"),
            "key": stored.metadata.get("_key"),
        })
    except Exception as e:
        logger.error("tell failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_query(brain, args: dict) -> CallToolResult:
    from ada.cognitive.ops import execute_op
    try:
        store, is_sql = _space(brain, args)
        op = {k: v for k, v in args.items() if k != "space"}
        if is_sql:
            answer = await store.execute_op(op)
        else:
            answer = execute_op(store, op)
        return _ok({"op": args.get("op"), "space": store.space_id, "answer": answer})
    except (ValueError, KeyError) as e:
        return _err(f"bad query op: {e}")
    except Exception as e:
        logger.error("query failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_recall(brain, args: dict) -> CallToolResult:
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    if not query:
        return _err("Missing 'query' parameter")
    try:
        store, _ = _space(brain, args)
        results = await _maybe(store.recall(query, top_k=top_k))
        return _ok({
            "query": query, "space": store.space_id,
            "results": [
                {"content": r.thought.content,
                 "similarity": round(float(r.global_similarity), 3),
                 "key": r.thought.metadata.get("_key")}
                for r in results
            ],
        })
    except Exception as e:
        logger.error("recall failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_history(brain, args: dict) -> CallToolResult:
    key = args.get("key", "")
    if not key:
        return _err("Missing 'key' parameter")
    try:
        store, _ = _space(brain, args)
        hist = await _maybe(store.history(key))
        return _ok({
            "key": key, "space": store.space_id, "versions": len(hist),
            "chain": [
                {"version": h.metadata.get("_version"), "content": h.content,
                 "thought_id": h.thought_id}
                for h in hist
            ],
        })
    except Exception as e:
        logger.error("history failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_consolidate(brain, args: dict) -> CallToolResult:
    from ada.memory.consolidate import consolidate
    space_id = args.get("space") or "main"
    dry_run = bool(args.get("dry_run", False))
    try:
        report = await consolidate(
            brain._session_factory, space_id=space_id,
            me=args.get("me"), enricher=brain._enricher, dry_run=dry_run)
        if not dry_run:
            # Memory-mode spaces hold stale state in RAM — rebuild from
            # the consolidated DB. (SQL mode reads the DB directly.)
            store = brain.space(space_id)
            if not getattr(store, "is_sql", False):
                from ada.memory.thought_persistence import load_thoughts
                from ada.memory.thought_space import ThoughtSpace
                fresh = ThoughtSpace(enricher=brain._enricher,
                                     space_id=space_id)
                await load_thoughts(brain._session_factory, fresh,
                                    space_id=space_id)
                brain._spaces[space_id] = fresh
                if brain._cognitive.thought_space is store:
                    brain._cognitive._space = fresh  # property is read-only
            _surface_cache.pop((id(brain), space_id), None)
        return _ok(report)
    except Exception as e:
        logger.error("consolidate failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_keys(brain, args: dict) -> CallToolResult:
    try:
        store, _ = _space(brain, args)
        limit = int(args.get("limit", 60))
        facts = await _maybe(store.keyed_facts(limit=limit))
        return _ok({"space": store.space_id, "count": len(facts),
                    "facts": facts})
    except Exception as e:
        logger.error("keys failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_stats(brain, args: dict) -> CallToolResult:
    try:
        store, _ = _space(brain, args)
        return _ok(await _maybe(store.stats()))
    except Exception as e:
        logger.error("stats failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_token_list(brain, args: dict) -> CallToolResult:
    from sqlalchemy import select
    from domains.models.db_models import Token
    session_factory = getattr(brain, "_session_factory", None)
    if session_factory is None:
        return _err("No database session available")
    try:
        async with session_factory() as session:
            rows = (await session.execute(
                select(Token).order_by(Token.created_at))).scalars().all()
        return _ok({"tokens": [
            {"id": str(t.id), "prefix": t.token_prefix, "name": t.name,
             "permissions": t.permissions, "status": t.status,
             "expires_at": t.expires_at.isoformat() if t.expires_at else None}
            for t in rows]})
    except Exception as e:
        logger.error("token_list failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_token_revoke(brain, args: dict) -> CallToolResult:
    from datetime import datetime
    from sqlalchemy import or_, select, cast, String
    from domains.models.db_models import Token
    needle = (args.get("token") or "").strip()
    if not needle:
        return _err("Missing 'token' (id or prefix)")
    session_factory = getattr(brain, "_session_factory", None)
    if session_factory is None:
        return _err("No database session available")
    try:
        async with session_factory() as session:
            rows = (await session.execute(select(Token).where(or_(
                cast(Token.id, String) == needle,
                Token.token_prefix == needle[:12],
            )))).scalars().all()
            if not rows:
                return _err(f"No token matching {needle!r}")
            for t in rows:
                t.status = "revoked"
                t.revoked_at = datetime.utcnow()
            await session.commit()
        return _ok({"revoked": [str(t.id) for t in rows]})
    except Exception as e:
        logger.error("token_revoke failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_create_token(brain, args: dict) -> CallToolResult:
    import hashlib
    import secrets
    from datetime import datetime, timedelta

    from domains.models.db_models import Token

    session_factory = getattr(brain, "_session_factory", None)
    if session_factory is None:
        return _err("No database session available for token creation")

    name = args.get("name") or "repl-token"
    permissions = args.get("permissions") or ["read", "write"]
    model_id = args.get("model_id")
    expires_days = args.get("expires_days")
    expires_at = (
        datetime.utcnow() + timedelta(days=int(expires_days)) if expires_days else None
    )

    raw_token = f"ada_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    try:
        async with session_factory() as session:
            tok = Token(
                name=name,
                token_hash=token_hash,
                token_prefix=raw_token[:12],
                org_id=ADA_ORG_ID,
                model_id=model_id,
                permissions=permissions,
                expires_at=expires_at,
            )
            session.add(tok)
            await session.commit()
            await session.refresh(tok)
            token_id = str(tok.id)
        return _ok({
            "id": token_id,
            "name": name,
            "token": raw_token,
            "token_prefix": raw_token[:12],
            "permissions": permissions,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "note": "Store this token now — it is not shown again.",
        })
    except Exception as e:
        logger.error("create_token failed: %s", e, exc_info=True)
        return _err(str(e))


# ── plumbing ────────────────────────────────────────────────────────

_surface_cache: dict = {}


def _get_surface(brain, store=None):
    """Build a CognitiveSurface over a space's store (default: the
    brain's main space). One surface per (brain, space) — the renderer
    is shared, the retrieval target isn't."""
    if store is None:
        store = brain.space("main")
    cache_key = (id(brain), store.space_id)
    if cache_key in _surface_cache:
        return _surface_cache[cache_key]
    from ada.cognitive.generate import build_llm_renderer
    from ada.cognitive.surface import CognitiveSurface
    surface = CognitiveSurface(space=store, renderer=build_llm_renderer())
    _surface_cache[cache_key] = surface
    return surface


def _ok(payload: dict) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
    )


def _err(msg: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": msg}))],
        isError=True,
    )
