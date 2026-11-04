from types import SimpleNamespace as NS

import pytest

from dex_ai import llm


def test_baseten_reasons_low_by_default(monkeypatch):
    monkeypatch.setenv("DEX_PROVIDER", "baseten")
    monkeypatch.delenv("DEX_REASONING_EFFORT", raising=False)
    assert llm.config_from_env().reasoning_effort == "low"
    monkeypatch.setenv("DEX_PROVIDER", "meta")
    assert llm.config_from_env().reasoning_effort is None
    monkeypatch.setenv("DEX_REASONING_EFFORT", "high")
    assert llm.config_from_env().reasoning_effort == "high"
    monkeypatch.setenv("DEX_REASONING_EFFORT", "max")
    with pytest.raises(llm.LLMConfigError):
        llm.config_from_env()


def test_effort_is_sent_with_each_call(monkeypatch):
    sent = {}

    class Fake:
        chat = NS(completions=NS(create=lambda **kw: sent.update(kw) or NS(usage=None, choices=[])))
    monkeypatch.setattr(llm, "client", lambda config: Fake())
    cfg = llm.LLMConfig("baseten", "u", "K", "m", "low")
    llm.complete(cfg, messages=[])
    assert sent["reasoning_effort"] == "low"
