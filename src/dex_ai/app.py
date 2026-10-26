"""Dex HTTP API."""
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from dex_ai import __version__, llm

load_dotenv()

SYSTEM_PROMPT = (
    "You are Dex, an expense companion for students and roommates who share "
    "costs. Be brief and concrete."
)

app = FastAPI(title="Dex", version=__version__)


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
