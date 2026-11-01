__version__ = "0.1.0"


def main() -> None:
    """Run the Dex API locally: `uv run dex-ai` (auto-reloads on code changes).

    Production runs uvicorn directly (see Dockerfile); HOST and PORT override
    the local defaults.
    """
    import os

    import uvicorn

    uvicorn.run("dex_ai.app:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")),
                reload=os.environ.get("DEX_RELOAD", "1") == "1")
