"""
Ada CLI — interactive shell + headless server.

Usage:
    ada              Launch interactive shell
    ada serve        Start headless (MCP endpoint only)
    ada serve -p 9000  Custom port
    ada setup        Show how to connect to Claude/ChatGPT
    ada setup claude Auto-configure Claude Code
"""

import sys
import threading
import time

# ANSI colors
P = "\033[38;5;141m"   # purple
B = "\033[38;5;111m"   # blue
G = "\033[38;5;114m"   # green
D = "\033[38;5;244m"   # dim
W = "\033[37m"         # white
R = "\033[0m"          # reset
BOLD = "\033[1m"
PINK = "\033[38;5;204m"
CYAN = "\033[38;5;116m"

# Banner gradient
_GRAD = ["\033[38;5;204m", "\033[38;5;177m", "\033[38;5;141m", "\033[38;5;111m"]
_BANNER = [
    " ⣼⢻⡄ ⣿⠛⠛⢻⡄ ⣼⢻⡄",
    "⣼⠃ ⢻⡄⣿  ⢸⡇⣼⠃ ⢻⡄",
    "⣿⠛⠛⢻⡇⣿  ⢸⡇⣿⠛⠛⢻⡇",
    "⠛  ⠘⠃⠛⠛⠛⠛ ⠛  ⠘⠃",
]


def _print_banner(version: str = "0.2.0") -> None:
    width = max(len(line) for line in _BANNER)
    for i, line in enumerate(_BANNER):
        c = _GRAD[i] if i < len(_GRAD) else _GRAD[-1]
        print(f"  {c}{BOLD}{line}{R}")
    ver = f"v{version}"
    padding = width - len(ver)
    print(f"  {' ' * padding}{D}{ver}{R}")
    print()


class _BrailleSpinner:
    """Braille dot spinner: ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"""
    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str = "thinking..."):
        self._message = message
        self._running = False
        self._thread = None
        # Grab a direct handle to the terminal — survives logging shenanigans
        import io
        import os
        self._tty = io.TextIOWrapper(
            io.FileIO(os.dup(sys.stderr.fileno()), mode="w"),
            encoding="utf-8",
        )

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        self._tty.write("\r\033[2K")
        self._tty.flush()

    def _spin(self):
        i = 0
        while self._running:
            frame = self._FRAMES[i % len(self._FRAMES)]
            self._tty.write(f"\r  \033[38;5;141m{frame}\033[0m \033[38;5;244m{self._message}\033[0m")
            self._tty.flush()
            i += 1
            time.sleep(0.08)


def _print_config(host: str, port: int) -> None:
    import os
    display_host = "localhost" if host == "0.0.0.0" else host
    model = os.environ.get("ADA_MODEL", "claude-haiku-4-5-20251001")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    print(f"  {D}MCP{R}    http://{display_host}:{port}/mcp")
    print(f"  {D}Web{R}    http://{display_host}:{port} {D}(first login root/root — you'll be asked to change it){R}")
    print(f"  {D}Tools{R}  think · ask · tell · query · history · stats")
    print(f"  {D}LLM{R}    {model}")
    if has_key:
        print(f"  {D}Key{R}    {G}●{R} set")
    else:
        print(f"  {D}Key{R}    {PINK}○{R} not set {D}(run{R} setup key{D}){R}")
    print()


def _require_api_key() -> bool:
    """Check for API key. If missing, prompt to set it. Returns True if key is set."""
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True

    print(f"\n  {PINK}Ada needs an Anthropic API key to start.{R}")
    print(f"  {D}Get one at:{R} {B}https://console.anthropic.com/settings/keys{R}\n")
    _setup_key(quiet=True)

    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _token_cmd(args: list[str]) -> None:
    """Local, bootstrap token management (mint/list/revoke).

    This is the one MCP-can't-do-itself piece: the first token has to be minted
    locally with direct DB access, because minting over MCP needs a token.
    Raw tokens are printed once — store them now.

    A freshly minted token is printed once, then wiped from the terminal after
    a countdown (default 30s) so the secret doesn't linger on an admin's screen.
    The wipe is TTY-only — piped/redirected output stays scriptable.

    Usage:
        ada token create [--name N] [--expires-days D] [--permissions read,write]
                         [--model-id M] [--clear-after SECONDS | --no-clear]
        ada token list
        ada token revoke <id-or-prefix>
    """
    import asyncio

    sub = args[0] if args else "list"

    def _opt(flag: str, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    async def _run() -> None:
        import hashlib
        import secrets
        from datetime import datetime, timedelta

        from infrastructure.database import async_session_maker, init_db
        from domains.models.db_models import Token
        from sqlalchemy import select

        await init_db()  # ensure schema exists (create_all on SQLite / migrate on PG)
        org_id = "ada"

        if sub == "create":
            name = _opt("--name", "cli-token")
            model_id = _opt("--model-id")
            perms_raw = _opt("--permissions", "read,write")
            permissions = [p.strip() for p in perms_raw.split(",") if p.strip()]
            days = _opt("--expires-days")
            expires_at = (
                datetime.utcnow() + timedelta(days=int(days)) if days else None
            )
            raw = f"ada_{secrets.token_urlsafe(32)}"
            token_hash = hashlib.sha256(raw.encode()).hexdigest()
            async with async_session_maker() as session:
                tok = Token(
                    name=name,
                    token_hash=token_hash,
                    token_prefix=raw[:12],
                    org_id=org_id,
                    model_id=model_id,
                    permissions=permissions,
                    expires_at=expires_at,
                )
                session.add(tok)
                await session.commit()
                await session.refresh(tok)
                tok_id = str(tok.id)
            clear_after = (
                0 if "--no-clear" in args else int(_opt("--clear-after", "30") or 30)
            )
            block = [
                "",
                f"  {G}Token created.{R} {D}Store it now — it is not shown again.{R}",
                "",
                f"  {BOLD}{raw}{R}",
                "",
                f"  {D}id{R}          {tok_id}",
                f"  {D}name{R}        {name}",
                f"  {D}permissions{R} {', '.join(permissions)}",
                f"  {D}expires{R}     {expires_at.isoformat() if expires_at else 'never'}",
                "",
                f"  {D}Use it:{R} Authorization: Bearer {raw[:12]}…",
                "",
            ]
            for ln in block:
                print(ln)

            # Wipe the secret from the terminal after a countdown (TTY only;
            # piped/redirected output just prints and exits, so it stays
            # scriptable). Ctrl-C keeps it on screen.
            if clear_after > 0 and sys.stdout.isatty():
                try:
                    for rem in range(clear_after, 0, -1):
                        sys.stdout.write(
                            f"\r  {D}clearing in {rem:2d}s — copy it now "
                            f"(Ctrl-C to keep on screen){R}"
                        )
                        sys.stdout.flush()
                        time.sleep(1)
                    sys.stdout.write("\r\033[2K")  # erase countdown line
                    for _ in range(len(block)):
                        sys.stdout.write("\033[1A\033[2K")  # up + erase each block line
                    sys.stdout.write(f"  {D}(token cleared from screen){R}\n")
                    sys.stdout.flush()
                except KeyboardInterrupt:
                    sys.stdout.write("\r\033[2K")
                    sys.stdout.write(f"  {D}(kept on screen){R}\n")
                    sys.stdout.flush()

        elif sub == "revoke":
            ident = args[1] if len(args) > 1 else None
            if not ident:
                print(f"  {PINK}Usage: ada token revoke <id-or-prefix>{R}")
                return
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Token).where(
                        (Token.token_prefix == ident) | (Token.token_prefix == ident[:12])
                    )
                )
                tok = result.scalar_one_or_none()
                if tok is None:
                    # try by id
                    try:
                        result = await session.execute(select(Token).where(Token.id == ident))
                        tok = result.scalar_one_or_none()
                    except Exception:
                        tok = None
                if tok is None:
                    print(f"  {PINK}No token matching {ident!r}.{R}")
                    return
                tok.status = "revoked"
                tok.revoked_at = datetime.utcnow()
                await session.commit()
                print(f"  {G}Revoked{R} {tok.name} ({tok.token_prefix}…)")

        else:  # list
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Token).order_by(Token.created_at.desc())
                )
                tokens = result.scalars().all()
            if not tokens:
                print(f"  {D}No tokens. Mint one: ada token create{R}")
                return
            print(f"\n  {BOLD}Tokens{R}\n")
            for t in tokens:
                exp = t.expires_at.date().isoformat() if t.expires_at else "never"
                print(f"  {t.token_prefix}…  {t.name:<18} {t.status:<8} "
                      f"{','.join(t.permissions or [])}  exp:{exp}")
            print()

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"  {PINK}Token command failed: {e}{R}")


def _print_help() -> None:
    print(f"""
  {D}Just type anything to talk to Ada.{R}

  {BOLD}Commands{R}

  {B}help{R}           Show this message
  {B}setup{R}          How to connect Ada to an LLM
  {B}setup claude{R}   Auto-configure Claude Code
  {B}setup key{R}      Set Anthropic API key
  {B}setup model{R}    Change Ada's internal LLM model
  {B}token create{R}   Mint an MCP access token (shown once)
  {B}token list{R}     List tokens
  {B}token revoke{R}   Revoke a token by id/prefix
  {B}status{R}         Show brain status
  {B}config{R}         Show current configuration
  {B}exit{R}           Quit
""")


def _print_status(brain) -> None:
    if not brain:
        print(f"  {D}Brain not loaded yet{R}")
        return

    llm = brain.llm
    stats = brain.cognitive.thought_space.stats()

    print(f"\n  {BOLD}Brain{R}")
    print(f"  {D}Thoughts:{R}       {stats['count']}")
    print(f"  {D}Versioned keys:{R} {stats['versioned_keys']}")

    if llm.available:
        print(f"  {D}LLM:{R}           {G}online{R} ({llm.usage.calls} calls, {llm.usage.input_tokens + llm.usage.output_tokens} tokens)")
    else:
        print(f"  {D}LLM:{R}           {D}offline (deterministic only){R}")
    print()


def _print_setup(port: int) -> None:
    url = f"http://localhost:{port}/mcp"
    print(f"""
  {P}{BOLD}Connect Ada to your LLM{R}

  {B}{BOLD}Claude Code{R} {G}(one command){R}
  {W}ada setup claude{R}

  {B}{BOLD}Claude Desktop{R}
  {D}Add to ~/Library/Application Support/Claude/claude_desktop_config.json:{R}
  {W}{{"mcpServers": {{"ada": {{"transport": "http", "url": "{url}"}}}}}}{R}

  {B}{BOLD}Cursor / VS Code{R}
  {D}Add to MCP settings:{R}
  {W}{{"ada": {{"transport": "http", "url": "{url}"}}}}{R}

  {B}{BOLD}Any MCP Client{R}
  {W}Endpoint: {url}{R}
  {W}Tool: think(input: string){R}
""")


def _get_ada_home() -> str:
    """~/.ada/ — Ada's config directory."""
    from pathlib import Path
    home = Path.home() / ".ada"
    home.mkdir(exist_ok=True)
    return str(home)


def _get_env_path() -> str:
    """Path to Ada's home env file (~/.ada/env)."""
    return f"{_get_ada_home()}/env"


def _project_env_paths() -> list[str]:
    """Candidate project .env files — the SAME file the runtime server reads.

    Checked so the REPL resolves storage/DB options (DATABASE_URL, etc.)
    identically to the server regardless of where it's launched from.
    """
    from pathlib import Path

    return [
        str(Path.cwd() / ".env"),
        str(Path(__file__).resolve().parents[2] / ".env"),  # repo root
    ]


def _load_ada_env() -> None:
    """Load Ada's secrets from vault + env file into os.environ."""
    import os

    # Load vault secrets first
    try:
        from domains.brain.skills.vault import get_vault
        vault = get_vault()

        # Map vault keys to env vars
        _VAULT_TO_ENV = {
            "anthropic_api_key": "ANTHROPIC_API_KEY",
        }
        for vault_key, env_key in _VAULT_TO_ENV.items():
            val = vault.get(vault_key)
            # Override absent OR blank env vars (an empty export must not win).
            if val and not os.environ.get(env_key):
                os.environ[env_key] = val
    except Exception:
        pass

    # Then load env files (lower priority than vault/explicit env). Includes
    # the project .env — the same file the runtime server reads — so the REPL
    # and server agree on storage/DB options like DATABASE_URL.
    seen: set[str] = set()
    for env_path in (_get_env_path(), *_project_env_paths()):
        if env_path in seen or not os.path.exists(env_path):
            continue
        seen.add(env_path)
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    # Override absent OR blank env vars so a stale/empty shell
                    # export can't shadow a real value from .env.
                    if value and not os.environ.get(key):
                        os.environ[key] = value


def _setup_key(quiet: bool = False) -> None:
    """Set or update the Anthropic API key."""
    import os
    import getpass
    from domains.brain.skills.vault import get_vault

    vault = get_vault()
    current = os.environ.get("ANTHROPIC_API_KEY") or vault.get("anthropic_api_key") or ""

    if current:
        masked = current[:8] + "..." + current[-4:]
        print(f"\n  {D}Current key:{R} {masked}")
        print(f"  {D}Enter new key or press Enter to keep:{R}")
    elif not quiet:
        print(f"\n  {D}No API key set. Ada needs this for her internal LLM.{R}")
        print(f"  {D}Get one at:{R} {B}https://console.anthropic.com/settings/keys{R}")
        print()

    try:
        key = getpass.getpass(f"  {P}API key{D}>{R} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not key:
        if current:
            print(f"  {D}Keeping existing key.{R}\n")
        else:
            print(f"  {D}No key set.{R}\n")
        return

    if not key.startswith("sk-"):
        print(f"  {PINK}Doesn't look like an Anthropic key (should start with sk-){R}\n")
        return

    # Store encrypted in vault + set in env for current session
    vault.set("anthropic_api_key", key)
    os.environ["ANTHROPIC_API_KEY"] = key
    print(f"  {G}Key encrypted and saved.{R}")
    print(f"  {D}Restart Ada to activate.{R}\n")


def _setup_model() -> None:
    """Change which LLM model Ada uses internally."""
    import os

    env_path = _get_env_path()
    current = os.environ.get("ADA_MODEL", "claude-haiku-4-5-20251001")

    models = [
        ("claude-haiku-4-5-20251001", "Haiku 4.5", f"{G}fast, cheap — recommended{R}"),
        ("claude-sonnet-4-6", "Sonnet 4.6", f"{B}balanced{R}"),
        ("claude-opus-4-6", "Opus 4.6", f"{P}powerful, expensive{R}"),
    ]

    print(f"\n  {BOLD}Ada's internal LLM{R}")
    print(f"  {D}Current:{R} {current}\n")

    for i, (model_id, name, desc) in enumerate(models, 1):
        marker = f" {G}←{R}" if model_id == current else ""
        print(f"  {B}{i}{R}  {W}{name}{R} {D}({model_id}){R} {desc}{marker}")

    print(f"\n  {D}Enter number or model ID (Enter to keep current):{R}")

    try:
        choice = input(f"  {P}model{D}>{R} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not choice:
        print(f"  {D}Keeping {current}{R}\n")
        return

    # Resolve choice
    model_id = None
    if choice.isdigit() and 1 <= int(choice) <= len(models):
        model_id = models[int(choice) - 1][0]
    elif choice.startswith("claude-"):
        model_id = choice
    else:
        print(f"  {PINK}Invalid choice.{R}\n")
        return

    # Write to ~/.ada/env
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = [ln for ln in f.readlines() if not ln.strip().startswith("ADA_MODEL=")]

    lines.append(f"ADA_MODEL={model_id}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

    os.environ["ADA_MODEL"] = model_id
    print(f"  {G}Model set to {model_id}{R}")
    print(f"  {D}Restart Ada to activate.{R}\n")


def _setup_claude_code(port: int) -> None:
    import subprocess
    import shutil

    url = f"http://localhost:{port}/mcp"

    if not shutil.which("claude"):
        print(f"\n  {D}claude CLI not found. Install it first:{R}")
        print(f"  {W}npm install -g @anthropic-ai/claude-code{R}\n")
        return

    try:
        result = subprocess.run(
            ["claude", "mcp", "add", "ada", "--transport", "http", url],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            print(f"\n  {G}{BOLD}Done.{R} Ada is connected to Claude Code.\n")
        elif "already exists" in (result.stderr or "").lower():
            print(f"\n  {G}Already configured.{R}\n")
        else:
            print(f"\n  {D}Try manually: claude mcp add ada --transport http {url}{R}\n")
    except Exception as e:
        print(f"\n  {D}Error: {e}{R}")
        print(f"  {D}Try manually: claude mcp add ada --transport http {url}{R}\n")


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

_server_error: str | None = None


def _start_server_background(host: str, port: int) -> threading.Thread:
    """Start Ada's server in a background thread."""
    import uvicorn

    def _run():
        global _server_error
        try:
            uvicorn.run(
                "ada.server:app",
                host=host,
                port=port,
                log_level="error",
            )
        except Exception as e:
            _server_error = str(e)

    t = threading.Thread(target=_run, daemon=True, name="ada-server")
    t.start()
    return t


def _wait_for_server(host: str, port: int, timeout: float = 300.0) -> bool:
    """Wait for the server to be ready. First boot can take minutes (encoding exemplars)."""
    import socket

    check_host = "127.0.0.1" if host == "0.0.0.0" else host
    start = time.time()
    dots = 0
    while time.time() - start < timeout:
        try:
            with socket.create_connection((check_host, port), timeout=1):
                pass
            import httpx
            r = httpx.get(f"http://{check_host}:{port}/health", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass

        # Show progress dots so user knows it's working
        elapsed = int(time.time() - start)
        if elapsed > 5 and elapsed % 5 == 0 and elapsed // 5 > dots:
            dots = elapsed // 5
            sys.stdout.write(".")
            sys.stdout.flush()

        time.sleep(1.0)
    return False


def _get_brain():
    """Get the brain instance from the running server."""
    try:
        from ada.server import brain
        return brain
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Interactive shell
# ---------------------------------------------------------------------------

def _shell(host: str, port: int) -> None:
    """Interactive Ada shell."""
    _print_banner()

    # Require API key before starting
    if not _require_api_key():
        print(f"  {D}Cannot start without an API key.{R}\n")
        return

    # Suppress Ada's logging — keep uvicorn functional
    import logging
    for name in ["ada", "domains", "infrastructure", "shared", "api", "mcp"]:
        logging.getLogger(name).setLevel(logging.CRITICAL)
    # Suppress root handler output (structured JSON logs)
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.root.addHandler(logging.NullHandler())

    print(f"  {D}Starting...{R}", end="", flush=True)
    _start_server_background(host, port)

    if _wait_for_server(host, port):
        print(f"\r  {G}● Online{R}   ")
    else:
        print(f"\r  {PINK}● Failed to start{R}   ")
        if _server_error:
            print(f"  {PINK}{_server_error}{R}")
        else:
            print(f"  {D}Try: ada serve (to see full error output){R}")
        return

    _print_config(host, port)

    print(f"  {D}Type{R} help {D}for commands,{R} setup {D}to connect an LLM{R}")
    print()

    while True:
        try:
            line = input(f"  \x01{P}\x02ada\x01{D}\x02>\x01{R}\x02 ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("exit", "quit", "q"):
            break
        elif cmd == "help":
            _print_help()
        elif cmd == "setup":
            if len(parts) > 1 and parts[1] in ("claude", "claude-code"):
                _setup_claude_code(port)
            elif len(parts) > 1 and parts[1] == "key":
                _setup_key()
            elif len(parts) > 1 and parts[1] == "model":
                _setup_model()
            else:
                _print_setup(port)
        elif cmd == "token":
            _token_cmd(parts[1:])
        elif cmd == "status":
            brain = _get_brain()
            _print_status(brain)
        elif cmd == "config":
            _print_config(host, port)
        else:
            # Everything else goes to Ada's brain
            brain = _get_brain()
            if not brain:
                print(f"  {D}Brain not ready yet.{R}")
                continue

            spinner = _BrailleSpinner()
            spinner.start()
            try:
                # Run think() in a new thread since the server owns the event loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    import asyncio
                    future = pool.submit(lambda: asyncio.run(brain.think(line)))
                    result = future.result(timeout=30)
                spinner.stop()
                print(f"  {CYAN}{result.response}{R}")
                tags = []
                if result.capability:
                    tags.append(f"{result.capability}")
                    tags.append(f"{result.confidence:.0%}")
                if result.llm_fallback:
                    tags.append("llm")
                tags.append(f"{result.elapsed_ms:.0f}ms")
                print(f"  {D}[{' · '.join(tags)}]{R}")
            except Exception as e:
                spinner.stop()
                print(f"  {PINK}Error: {e}{R}")
            print()

    print(f"  {D}Goodbye.{R}")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def _serve(args: list[str]) -> None:
    """Run Ada headless (no shell, MCP endpoint only)."""
    import uvicorn
    from infrastructure.config import get_settings

    settings = get_settings()

    port = settings.port
    host = settings.host
    for i, arg in enumerate(args):
        if arg in ("-p", "--port") and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg in ("-h", "--host") and i + 1 < len(args):
            host = args[i + 1]

    _print_banner()

    if not _require_api_key():
        print(f"  {D}Cannot start without an API key.{R}\n")
        return

    _print_config(host, port)

    uvicorn.run(
        "ada.server:app",
        host=host,
        port=port,
        log_level="info",
    )


def main() -> None:
    from infrastructure.config import get_settings
    settings = get_settings()

    args = sys.argv[1:]

    # Parse global flags
    host = settings.host
    port = settings.port
    for i, arg in enumerate(args):
        if arg in ("-p", "--port") and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg in ("-h", "--host") and i + 1 < len(args):
            host = args[i + 1]

    # Load stored env vars (API key, model, etc.)
    _load_ada_env()

    if not args:
        _admin_repl(host, port)
    elif args[0] == "chat":
        _shell(host, port)
    elif args[0] == "serve":
        _load_ada_env()  # also for headless
        _serve(args[1:])
    elif args[0] == "setup":
        if len(args) > 1 and args[1] in ("claude", "claude-code"):
            _setup_claude_code(port)
        elif len(args) > 1 and args[1] == "key":
            _setup_key()
        elif len(args) > 1 and args[1] == "model":
            _setup_model()
        else:
            _print_setup(port)
    elif args[0] == "token":
        _token_cmd(args[1:])
    elif args[0] == "help":
        _print_banner()
        _print_help()
    else:
        print(f"Unknown command: {args[0]}")
        print("Usage: ada [chat|serve|setup|token|help]")
        sys.exit(1)


def _admin_repl(host: str, port: int) -> None:
    """The default `ada` experience: the admin REPL against the server,
    auto-starting one in-process when none is reachable. Boot look and
    feel match the original shell: banner, ● Online, config panel."""
    import httpx
    from ada import __version__

    _print_banner(__version__)

    probe_host = "localhost" if host == "0.0.0.0" else host
    url = f"http://{probe_host}:{port}/mcp"
    health = f"http://{probe_host}:{port}/health"
    up = False
    try:
        up = httpx.get(health, timeout=2.0).status_code == 200
    except Exception:
        pass

    if up:
        print(f"  {G}● Online{R}   ")
    else:
        import logging
        for name in ["ada", "domains", "infrastructure", "shared", "api", "mcp"]:
            logging.getLogger(name).setLevel(logging.CRITICAL)
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        logging.root.addHandler(logging.NullHandler())

        print(f"  {D}Starting...{R}", end="", flush=True)
        _start_server_background(host, port)
        if _wait_for_server(probe_host, port):
            print(f"\r  {G}● Online{R}   ")
        else:
            print(f"\r  {PINK}● Failed to start{R}   ")
            if _server_error:
                print(f"  {PINK}{_server_error}{R}")
            print(f"  {D}Try: ada serve (to see full error output){R}")
            return

    _print_config(host, port)
    print(f"  {D}Type{R} help {D}for commands,{R} setup {D}to connect an LLM{R}")
    print()

    from ada.tui.repl import run_repl
    run_repl(url, banner=False)


if __name__ == "__main__":
    main()
