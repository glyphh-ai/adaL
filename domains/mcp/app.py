"""
MCP ASGI Application for Ada.

Single /mcp endpoint. No org_id, no model_id. One door into the brain.

Transport selection:
- Accept: application/json → JSON transport (Studio, Platform)
- Default / text/event-stream → SSE transport (Claude Code, CLI agents)
"""

import json
import logging
import re
from typing import Callable, Optional, Tuple

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Single MCP path — no org/model in the URL
_MCP_PATH_RE = re.compile(r"^/mcp(/.*)?$")

ADA_ORG_ID = "ada"

# Tools that mutate state require write permission; everything else read.
_WRITE_TOOLS = {"tell", "tell_raw", "consolidate", "archive", "merge",
                "forget"}
# Minting or revoking credentials is privilege management, not data
# writing — a write-permission token must not be able to mint itself
# an admin successor.
_ADMIN_TOOLS = {"create_token", "token_revoke", "token_delete"}


async def _read_body(receive: Receive) -> tuple[bytes, Receive]:
    """Buffer the request body and return a replaying receive callable."""
    chunks: list[dict] = []
    body = b""
    while True:
        message = await receive()
        chunks.append(message)
        if message["type"] != "http.request":
            break
        body += message.get("body", b"")
        if not message.get("more_body"):
            break

    sent = {"i": 0}

    async def replay() -> dict:
        if sent["i"] < len(chunks):
            msg = chunks[sent["i"]]
            sent["i"] += 1
            return msg
        return await receive()

    return body, replay


async def _deny(send: Send, status: int, message: str) -> None:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": None,
        "error": {"code": -32001 if status == 401 else -32002,
                  "message": message},
    }).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer")]})
    await send({"type": "http.response.body", "body": payload})


def _wants_json(scope: Scope) -> bool:
    """Return True if the client explicitly accepts application/json without SSE."""
    for key, value in scope.get("headers", []):
        if key == b"accept":
            return (
                b"application/json" in value
                and b"text/event-stream" not in value
            )
    return False


class MCPRoutingMiddleware:
    """ASGI middleware that intercepts /mcp requests and forwards to
    the MCP session manager. No org/model scoping — Ada is the brain."""

    def __init__(
        self,
        app: ASGIApp,
        mcp_app_getter: Callable[[], Optional[Tuple]],
        auth_getter: Callable[[], Optional[object]] = lambda: None,
        auth_required: bool = False,
    ):
        self.app = app
        self._mcp_app_getter = mcp_app_getter
        self._auth_getter = auth_getter
        self._auth_required = auth_required

    def _bearer(self, scope: Scope) -> Optional[str]:
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                v = value.decode("latin-1")
                return v[7:] if v.lower().startswith("bearer ") else v
        return None

    def _session_cookie(self, scope: Scope) -> Optional[str]:
        for key, value in scope.get("headers", []):
            if key == b"cookie":
                for part in value.decode("latin-1").split(";"):
                    name, _, val = part.strip().partition("=")
                    if name == "ada_session":
                        return val
        return None

    async def _authorize(self, scope: Scope, receive: Receive,
                         send: Send) -> Optional[Receive]:
        """Enforce auth — bearer token (machine principal) or workbench
        session cookie (human principal); both resolve to the same User.
        Returns a (replaying) receive on success, None after having sent
        a 401/403 denial."""
        token = self._bearer(scope)
        cookie = None if token else self._session_cookie(scope)
        if not token and not cookie:
            await _deny(send, 401, "Authentication required: pass "
                        "'Authorization: Bearer <token>' (mint one with "
                        "`ada token create`) or log in to the workbench")
            return None

        auth = self._auth_getter()
        try:
            user = (await auth.validate_token(token) if token
                    else await auth.validate_session(cookie))
        except Exception:
            await _deny(send, 401, "Invalid, expired, or revoked credential")
            return None

        body, replay = await _read_body(receive)
        tool = None
        try:
            parsed = json.loads(body or b"{}")
            if parsed.get("method") == "tools/call":
                tool = (parsed.get("params") or {}).get("name")
        except Exception:
            pass  # non-JSON bodies fall through as read-level requests

        needs_admin = tool in _ADMIN_TOOLS
        needs_write = tool in _WRITE_TOOLS
        if needs_admin:
            allowed = user.is_admin(ADA_ORG_ID)
        elif needs_write:
            allowed = user.can_write(ADA_ORG_ID)
        else:
            allowed = user.can_read(ADA_ORG_ID) or user.can_write(ADA_ORG_ID)
        if not allowed:
            level = "admin" if needs_admin else ("write" if needs_write else "read")
            await _deny(send, 403, f"Credential lacks {level} permission")
            return None

        # Space binding: a token scoped to a space may only touch that space.
        bound = getattr(user, "allowed_space", None)
        if bound:
            try:
                requested = (parsed.get("params") or {}).get("arguments", {}).get("space", "main")
            except Exception:
                requested = "main"
            if requested != bound:
                await _deny(send, 403,
                            f"Token is bound to space '{bound}', cannot access "
                            f"'{requested}'")
                return None
        return replay

    def _get_origin(self, scope: Scope) -> Optional[str]:
        for key, value in scope.get("headers", []):
            if key == b"origin":
                return value.decode("latin-1")
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            match = _MCP_PATH_RE.match(path)
            if match:
                origin = self._get_origin(scope)

                # CORS preflight
                if scope.get("method") == "OPTIONS" and origin:
                    await self.app(scope, receive, send)
                    return

                managers = self._mcp_app_getter()
                if managers is not None:
                    if self._auth_required and scope["type"] == "http":
                        replay = await self._authorize(scope, receive, send)
                        if replay is None:
                            return
                        receive = replay

                    json_manager, sse_manager = managers
                    manager = json_manager if _wants_json(scope) else sse_manager

                    # Inject CORS headers (MCP SDK runs outside FastAPI's CORSMiddleware)
                    async def cors_send(message) -> None:
                        if message["type"] == "http.response.start" and origin:
                            headers = list(message.get("headers", []))
                            headers.append((b"access-control-allow-origin", origin.encode()))
                            headers.append((b"access-control-allow-headers", b"*"))
                            headers.append((b"access-control-allow-methods", b"GET, POST, OPTIONS"))
                            message = {**message, "headers": headers}
                        await send(message)

                    await manager.handle_request(scope, receive, cors_send)
                    return

        await self.app(scope, receive, send)


def create_mcp_session_managers(brain, auth_service):
    """Create dual MCP session managers (JSON + SSE).

    Args:
        brain: The Brain instance (domains.brain.think.Brain)
        auth_service: AuthService for token validation
    """
    from domains.mcp.server import create_mcp_server
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings

    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    server = create_mcp_server(brain, auth_service)

    json_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        json_response=True,
        security_settings=security,
    )

    sse_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        json_response=False,
        security_settings=security,
    )

    return json_manager, sse_manager
