"""One OpenAI-compatible client for every host Dex's model can run on.

Meta Model API, Baseten and Fireworks all serve Meta's models behind the same
OpenAI-style endpoint, so which host and model back Dex is configuration:

    DEX_PROVIDER=meta            # meta | baseten | fireworks
    DEX_MODEL=muse-spark-1.3     # optional: the host's own model id
"""
import os
from dataclasses import dataclass

from openai import OpenAI

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


class LLMConfigError(Exception):
    """The provider, model or API key isn't set up."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    base_url: str
    api_key_env: str
    model: str | None

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
    return LLMConfig(provider, base_url, key_env, model)


def client(config: LLMConfig) -> OpenAI:
    """An OpenAI-compatible client for the configured host, or LLMConfigError."""
    if not config.api_key:
        raise LLMConfigError(f"{config.api_key_env} is not set")
    if not config.model:
        raise LLMConfigError(f"Set DEX_MODEL for provider {config.provider!r}")
    return OpenAI(base_url=config.base_url, api_key=config.api_key)


def chat(messages: list[dict], config: LLMConfig | None = None, **kwargs) -> str:
    """Send a chat completion and return the reply text."""
    config = config or config_from_env()
    response = client(config).chat.completions.create(
        model=config.model, messages=messages, **kwargs
    )
    return response.choices[0].message.content or ""
