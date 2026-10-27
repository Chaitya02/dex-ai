"""Dex HTTP API and the capture page."""
from fractions import Fraction
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, PositiveFloat

from dex_ai import __version__, assign, llm, receipt, split, voice

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

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
    return ChatResponse(reply=reply, provider=config.provider, model=config.model)


@app.post("/api/receipts/parse")
async def parse_receipt(image: UploadFile = File(...)) -> dict:
    """Receipt photo -> line items, tax, tip, total in cents, plus arithmetic checks."""
    data = await image.read()
    try:
        return receipt.parse(data)
    except receipt.ReceiptError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except llm.LLMConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))


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
    if not req.receipt.get("items"):
        raise HTTPException(status_code=400, detail="Read a receipt first")
    state = assign.new_state(
        req.receipt, req.people, [a.model_dump() for a in req.assignments],
        payer=req.payer, tax_tip=req.tax_tip,
    )
    try:
        return assign.run(state, req.transcript)
    except llm.LLMConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/voice/transcribe")
async def transcribe(audio: UploadFile = File(...), keywords: str = Form("")) -> dict:
    """WAV recording (mono 16-bit, 16 kHz) -> transcript.

    `keywords` is a comma-separated list (people's names, the receipt's item
    names) that biases recognition; without it "Aayush and Ketan" comes back
    as "I and Caton".
    """
    data = await audio.read()
    hints = [k.strip() for k in keywords.split(",") if k.strip()][:100]
    try:
        return voice.transcribe(data, keywords=hints or None)
    except voice.VoiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
