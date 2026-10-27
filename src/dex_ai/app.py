"""Dex HTTP API and the capture page."""
import json
from fractions import Fraction
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, PositiveFloat

from dex_ai import __version__, assign, llm, locate, receipt, split, telemetry, voice

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"
MAX_TRANSCRIPT = 2000   # characters; a spoken split is a few sentences

SYSTEM_PROMPT = (
    "You are Dex, an expense companion for students and roommates who share "
    "costs. Be brief and concrete."
)

app = FastAPI(title="Dex", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str


@app.get("/health")
def health() -> dict:
    """Liveness plus which model host is configured (never the key itself)."""
    try:
        config = llm.config_from_env()
    except llm.LLMConfigError as e:
        return {"status": "ok", "version": __version__, "llm": {"error": str(e)}}
    return {
        "status": "ok",
        "version": __version__,
        "llm": {
            "provider": config.provider,
            "model": config.model,
            "key_set": config.api_key is not None,
        },
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        config = llm.config_from_env()
        reply = llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": req.message},
            ],
            config,
        )
    except llm.LLMConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except llm.LLMUnavailable as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return ChatResponse(reply=reply, provider=config.provider, model=config.model)


@app.get("/api/metrics")
def metrics() -> dict:
    """Latency percentiles and error counts per route over recent requests."""
    return telemetry.metrics()


@app.post("/api/receipts/parse")
async def parse_receipt(image: UploadFile = File(...)) -> dict:
    """Receipt photo -> line items, tax, tip, total in cents, plus arithmetic checks."""
    data = await image.read()
    # The model call blocks, so it runs on a worker thread, not the event loop.
    return await run_in_threadpool(_parse_receipt, data)


def _parse_receipt(data: bytes) -> dict:
    try:
        with telemetry.turn("receipt", image_kb=len(data) // 1024):
            return receipt.parse(data)
    except receipt.ReceiptError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except llm.LLMConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except llm.LLMUnavailable as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@app.post("/api/receipts/locate")
async def locate_items(image: UploadFile = File(...), receipt_json: str = Form(..., alias="receipt")) -> dict:
    """Receipt photo + its parsed items -> each item's box on the photo (SAM 3.1)."""
    data = await image.read()
    try:
        parsed = json.loads(receipt_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="receipt must be the JSON from /api/receipts/parse")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        raise HTTPException(status_code=400, detail="receipt must be the JSON from /api/receipts/parse")
    return await run_in_threadpool(_locate, parsed, data)


def _locate(parsed: dict, data: bytes) -> dict:
    try:
        mime = receipt.sniff_image(data)
        with telemetry.turn("locate", image_kb=len(data) // 1024, items=len(parsed["items"])):
            return locate.locate(parsed, data, mime)
    except receipt.ReceiptError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except locate.LocateError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


class ItemAssignment(BaseModel):
    item_id: int
    # Either people (equal split) or weights ("I had 2 of the 3 sodas").
    people: list[str] = Field(default_factory=list)
    weights: dict[str, PositiveFloat] = Field(default_factory=dict)


class SplitRequest(BaseModel):
    receipt: dict
    assignments: list[ItemAssignment]
    payer: str = "me"
    tax_tip: Literal["proportional", "equal"] = "proportional"


@app.post("/api/split")
def split_receipt(req: SplitRequest) -> dict:
    """Receipt + who had which item -> each person's share and who owes whom."""
    assignments = []
    for a in req.assignments:
        weights = {n.strip(): Fraction(str(w)) for n, w in a.weights.items() if n.strip()}
        for n in a.people:
            if n.strip():
                weights.setdefault(n.strip(), Fraction(1))
        assignments.append(split.Assignment(a.item_id, weights))
    try:
        return split.split(req.receipt, assignments, req.payer.strip() or "me", req.tax_tip)
    except (split.SplitError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class AssignRequest(BaseModel):
    receipt: dict
    transcript: str
    people: list[str] = Field(default_factory=list)
    # The current split, so a spoken correction changes only what it mentions.
    assignments: list[ItemAssignment] = Field(default_factory=list)
    payer: str = "me"
    tax_tip: Literal["proportional", "equal"] = "proportional"


@app.post("/api/assign")
def assign_items(req: AssignRequest) -> dict:
    """Transcript -> item assignments, through the Muse Spark tool-calling agent."""
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Say who had what first")
    if len(req.transcript) > MAX_TRANSCRIPT:
        raise HTTPException(status_code=400, detail="That's too long; say it in a few sentences")
    if not req.receipt.get("items"):
        raise HTTPException(status_code=400, detail="Read a receipt first")
    state = assign.new_state(
        req.receipt, req.people, [a.model_dump() for a in req.assignments],
        payer=req.payer, tax_tip=req.tax_tip,
    )
    try:
        with telemetry.turn("assign", items=len(state.items), people=len(state.people),
                            transcript_chars=len(req.transcript),
                            correction=bool(req.assignments)):
            return assign.run(state, req.transcript)
    except llm.LLMConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except llm.LLMUnavailable as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@app.post("/api/voice/transcribe")
async def transcribe(audio: UploadFile = File(...), keywords: str = Form("")) -> dict:
    """WAV recording (mono 16-bit, 16 kHz) -> transcript.

    `keywords` is a comma-separated list (people's names, the receipt's item
    names) that biases recognition; without it "Aayush and Ketan" comes back
    as "I and Caton".
    """
    data = await audio.read()
    hints = [k.strip()[:60] for k in keywords.split(",") if k.strip()][:100]
    return await run_in_threadpool(_transcribe, data, hints)


def _transcribe(data: bytes, hints: list[str]) -> dict:
    try:
        with telemetry.turn("transcribe", audio_kb=len(data) // 1024, keywords=len(hints)) as t:
            out = voice.transcribe(data, keywords=hints or None)
            t["audio_ms"] = out.get("duration_ms")
            return out
    except voice.VoiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
