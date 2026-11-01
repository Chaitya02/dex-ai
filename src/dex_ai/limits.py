"""Rate limits for a public deploy, so a URL in a demo can't run up the API bill.

Two kinds, both in memory (one process; a restart resets them, which is fine
for keeping a demo's costs bounded):

- per visitor: each route has a budget per IP per hour;
- per day: the receipt routes (the expensive ones: a vision call and up to
  sixteen SAM calls) have a global cap per UTC day.

A request over a limit gets 429 with a message the page shows. Limits are off
unless DEX_LIMITS=1, so local runs and tests aren't throttled.

Behind Render's proxy the visitor's address is the first entry of
X-Forwarded-For; that header is only trusted when DEX_TRUST_PROXY=1, since
anyone can send it to a server that isn't behind a proxy.
"""
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# route -> requests per visitor per hour
PER_HOUR = {
    "receipt": 20,
    "locate": 20,
    "assign": 120,
    "transcribe": 120,
    "split": 600,
    "save": 30,
}
DAILY_RECEIPTS = int(os.environ.get("DEX_DAILY_RECEIPTS", "300"))

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_day = {"date": "", "receipts": 0}


def enabled() -> bool:
    return os.environ.get("DEX_LIMITS") == "1"


def client_ip(request: Request) -> str:
    if os.environ.get("DEX_TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(request: Request, route: str) -> None:
    """Count this request against the visitor's hourly budget (and the daily
    receipt cap), or raise 429."""
    if not enabled():
        return
    now = time.time()
    key = (client_ip(request), route)
    with _lock:
        hits = _hits[key]
        while hits and hits[0] < now - 3600:
            hits.popleft()
        if len(hits) >= PER_HOUR[route]:
            wait = int(hits[0] + 3600 - now) // 60 + 1
            raise HTTPException(status_code=429, detail=f"Slow down: try again in about {wait} min")
        if route == "receipt":
            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            if _day["date"] != today:
                _day.update(date=today, receipts=0)
            if _day["receipts"] >= DAILY_RECEIPTS:
                raise HTTPException(status_code=429,
                                    detail="This demo has read its receipts for today; try again tomorrow")
            _day["receipts"] += 1
        hits.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
        _day.update(date="", receipts=0)
