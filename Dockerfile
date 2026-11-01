FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# Not root.
RUN useradd --create-home dex
USER dex

# Render sets PORT. One worker: the rate limits live in process memory.
CMD ["sh", "-c", "/app/.venv/bin/uvicorn dex_ai.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
