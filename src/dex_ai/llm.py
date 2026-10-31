"""One OpenAI-compatible client for every host Dex's model can run on.

Meta Model API, Baseten and Fireworks all serve Meta's models behind the same
OpenAI-style endpoint, so which host and model back Dex is configuration:

    DEX_PROVIDER=meta            # meta | baseten | fireworks
    DEX_MODEL=muse-spark-1.3     # optional: the host's own model id
    DEX_REASONING_EFFORT=low     # optional: none | low | medium | high

Muse Spark Open reasons before it answers. Left to itself it spent ~4,000
reasoning tokens (18.6s) reading one receipt; at "low" it spends ~1,000 (7.2s)
with the same answer, so that's Baseten's default.

Every call has a timeout (the SDK's default is ten minutes) and at most one
retry. Model calls only read, so a retry can't double anything; writes to
Balance Desk carry their own idempotency key.
"""
import os
import time
from dataclasses import dataclass

import openai
from openai import OpenAI

from dex_ai import telemetry

# provider -> (base URL, env var holding its API key, default model)
PROVIDERS = {
    "meta": ("https://api.meta.ai/v1", "MODEL_API_KEY", "muse-spark-1.3"),
    "baseten": (
        "https://inference.baseten.co/v1",
        "BASETEN_API_KEY",
        "meta-models/muse-spark-open-1026",
    ),
    "fireworks": ("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY", None),
}
DEFAULT_PROVIDER = "meta"
# Reasoning effort sent by default, per host (None: don't send the parameter).
DEFAULT_EFFORT = {"baseten": "low"}
EFFORTS = ("none", "low", "medium", "high")
STEP_TIMEOUT = 30.0   # seconds for one model call
MAX_RETRIES = 1


class LLMConfigError(Exception):
    """The provider, model or API key isn't set up."""


class LLMUnavailable(Exception):
    """The model host timed out or failed. The message is user-facing."""

    def __init__(self, message: str, status: int, outcome: str):
        super().__init__(message)
        self.status = status
        self.outcome = outcome


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    base_url: str
    api_key_env: str
    model: str | None
    reasoning_effort: str | None = None

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


def config_from_env() -> LLMConfig:
    provider = os.environ.get("DEX_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider not in PROVIDERS:
        raise LLMConfigError(
            f"Unknown DEX_PROVIDER {provider!r}; use one of {', '.join(PROVIDERS)}"
        )
    base_url, key_env, default_model = PROVIDERS[provider]
    model = os.environ.get("DEX_MODEL", "").strip() or default_model
    effort = os.environ.get("DEX_REASONING_EFFORT", "").strip().lower() or DEFAULT_EFFORT.get(provider)
    if effort and effort not in EFFORTS:
        raise LLMConfigError(f"DEX_REASONING_EFFORT must be one of {', '.join(EFFORTS)}")
    return LLMConfig(provider, base_url, key_env, model, effort)


def client(config: LLMConfig) -> OpenAI:
    """An OpenAI-compatible client for the configured host, or LLMConfigError."""
    if not config.api_key:
        raise LLMConfigError(f"{config.api_key_env} is not set")
    if not config.model:
        raise LLMConfigError(f"Set DEX_MODEL for provider {config.provider!r}")
    return OpenAI(base_url=config.base_url, api_key=config.api_key,
                  timeout=STEP_TIMEOUT, max_retries=MAX_RETRIES)


def complete(config: LLMConfig, timeout: float | None = None, **kwargs):
    """One chat completion with a timeout, recorded on the current turn.

    Raises LLMUnavailable (504 on timeout, 502 otherwise) instead of the SDK's
    many exception types, so routes can fail with a clear message.
    """
    c = client(config)
    if config.reasoning_effort and "reasoning_effort" not in kwargs:
        kwargs["reasoning_effort"] = config.reasoning_effort
    start = time.perf_counter()
    try:
        response = c.chat.completions.create(
            model=config.model, timeout=timeout or STEP_TIMEOUT, **kwargs
        )
    except openai.APITimeoutError:
        telemetry.record_llm((time.perf_counter() - start) * 1000, model=config.model)
        raise LLMUnavailable("The model took too long to answer; try again", 504, "timeout")
    except openai.APIStatusError as e:
        telemetry.record_llm((time.perf_counter() - start) * 1000, model=config.model)
        raise LLMUnavailable(f"The model host returned an error ({e.status_code})", 502,
                             f"http_{e.status_code}")
    except openai.APIConnectionError:
        telemetry.record_llm((time.perf_counter() - start) * 1000, model=config.model)
        raise LLMUnavailable("Couldn't reach the model host", 502, "unreachable")
    telemetry.record_llm((time.perf_counter() - start) * 1000,
                         getattr(response, "usage", None), config.model)
    return response


def chat(messages: list[dict], config: LLMConfig | None = None, **kwargs) -> str:
    """Send a chat completion and return the reply text."""
    config = config or config_from_env()
    response = complete(config, messages=messages, **kwargs)
    return response.choices[0].message.content or ""
