__version__ = "0.1.0"


def main() -> None:
    """Run the Dex API locally: `uv run dex-ai`."""
    import uvicorn

    uvicorn.run("dex_ai.app:app", host="127.0.0.1", port=8000, reload=True)
