"""One log record per request ("turn"), and latency percentiles over recent ones.

Each API route wraps its work in `turn(...)`. Model calls made inside it add
their latency and token usage to the same record, so one line answers: what
was asked (as sizes, never content), which tools ran, how long it took, what
it cost, and how it ended. Records go to the `dex.turns` logger as JSON and
into a small in-memory window that /api/metrics summarizes as p50/p95/p99.

No transcripts, names, item names or amounts are logged: only counts.
"""
import json
import logging
import os
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar

RECENT: deque = deque(maxlen=500)
_current: ContextVar[dict | None] = ContextVar("dex_turn", default=None)

log = logging.getLogger("dex.turns")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    if os.environ.get("DEX_LOG_FILE"):
        log.addHandler(logging.FileHandler(os.environ["DEX_LOG_FILE"]))
    log.setLevel(logging.INFO)
    log.propagate = False


@contextmanager
def turn(route: str, **fields):
    """Time a request and log it once, however it ends."""
    record = {
        "route": route,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **fields,
        "llm_calls": 0,
        "llm_ms": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "tools": [],
        "outcome": "ok",
    }
    token = _current.set(record)
    start = time.perf_counter()
    try:
        yield record
    except Exception as e:
        record["outcome"] = getattr(e, "outcome", type(e).__name__)
        raise
    finally:
        record["latency_ms"] = round((time.perf_counter() - start) * 1000)
        _current.reset(token)
        RECENT.append(record)
        log.info(json.dumps(record))


def record_llm(latency_ms: float, usage=None, model: str | None = None) -> None:
    """Add one model call to the current turn, if there is one."""
    record = _current.get()
    if record is None:
        return
    record["llm_calls"] += 1
    record["llm_ms"] += round(latency_ms)
    if model:
        record["model"] = model
    if usage is not None:
        record["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
        record["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0


def record_tool(name: str, ok: bool) -> None:
    record = _current.get()
    if record is not None:
        record["tools"].append(name if ok else f"{name}!")


def note(**fields) -> None:
    """Attach extra fields to the current turn's record."""
    record = _current.get()
    if record is not None:
        record.update(fields)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))   # ceil(n * p / 100)
    return ordered[int(rank) - 1]


def metrics() -> dict:
    """Per-route latency percentiles and error rates over the recent window."""
    out = {}
    for route in sorted({r["route"] for r in RECENT}):
        rows = [r for r in RECENT if r["route"] == route]
        lat = [r["latency_ms"] for r in rows]
        out[route] = {
            "count": len(rows),
            "p50_ms": percentile(lat, 50),
            "p95_ms": percentile(lat, 95),
            "p99_ms": percentile(lat, 99),
            "errors": sum(r["outcome"] != "ok" for r in rows),
            "avg_llm_calls": round(sum(r["llm_calls"] for r in rows) / len(rows), 2),
            "avg_tokens": round(sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows) / len(rows)),
        }
    return out
