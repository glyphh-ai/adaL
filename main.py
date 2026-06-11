"""Thin shim — the real app lives in ada.server."""

try:  # honor project-root .env for the dev path (vault still wins in the CLI)
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

from ada.server import app  # noqa: E402,F401

if __name__ == "__main__":
    import uvicorn
    from infrastructure.config import get_settings

    settings = get_settings()
    uvicorn.run("ada.server:app", host=settings.host, port=settings.port, log_level="info")
