"""Dex HTTP API and the capture page."""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dex_ai import __version__, llm, receipt, voice

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
