"""Provider-boundary tests that do not make network calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from deallens.llm import LLM
from deallens.models import UsageLedger


class Probe(BaseModel):
    status: str


class SequenceInvoker:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def invoke(self, _prompt):
        self.calls += 1
        return next(self.results)


class FakeModel:
    def __init__(self, invoker):
        self.invoker = invoker

    def with_structured_output(self, _schema, method=None, include_raw=False):
        assert include_raw
        assert method == "json_mode"
        return self.invoker


def llm_with(results) -> tuple[LLM, SequenceInvoker]:
    invoker = SequenceInvoker(results)
    llm = object.__new__(LLM)
    llm.ledger = UsageLedger()
    llm._model = FakeModel(invoker)
    return llm, invoker


def raw(input_tokens=3, output_tokens=2):
    return SimpleNamespace(
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens}
    )


def test_structured_retries_once_when_provider_returns_no_parsed_object():
    llm, invoker = llm_with(
        [
            {"raw": raw(), "parsed": None, "parsing_error": None},
            {"raw": raw(), "parsed": Probe(status="OK"), "parsing_error": None},
        ]
    )

    result = llm.structured(Probe, "probe")

    assert result.status == "OK"
    assert invoker.calls == 2
    assert llm.ledger.llm_input_tokens == 6
    assert llm.ledger.llm_output_tokens == 4


def test_structured_raises_clear_error_after_bounded_retries():
    llm, invoker = llm_with(
        [
            {"raw": raw(), "parsed": None, "parsing_error": ValueError("bad output")},
            {"raw": raw(), "parsed": None, "parsing_error": ValueError("bad output")},
        ]
    )

    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        llm.structured(Probe, "probe")

    assert invoker.calls == 2
