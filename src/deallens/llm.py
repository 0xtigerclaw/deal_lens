"""Nebius-hosted LLM access for bounded, schema-constrained interpretation.

The model can be changed with DEALLENS_MODEL, but the supported and documented
take-home path uses Nebius Token Factory and langchain-nebius directly:
    moonshotai/Kimi-K3

The model interprets governed baseline snippets, selects supporting quotes out
of extracted content, and writes short narratives. Quote provenance, evidence
thresholds, status, and severity remain deterministic.
It never decides verification status or severity.
"""

from __future__ import annotations

import json
import os

from langchain_nebius import ChatNebius
from openai import OpenAI
from pydantic import BaseModel, Field

from .models import Candidate, UsageLedger

DEFAULT_MODEL = "moonshotai/Kimi-K3"
STRUCTURED_OUTPUT_ATTEMPTS = 2
MAX_COMPLETION_TOKENS = 8192


class QuotePick(BaseModel):
    url: str
    quote: str | None = Field(
        default=None,
        description="Verbatim supporting quote copied exactly from this source's "
        "content, or null if this source does not support the claim.",
    )
    supports_assertions: list[int] = Field(
        default_factory=list,
        description="Zero-based indexes of assertions fully supported by the quote.",
    )
    contradicts_assertions: list[int] = Field(
        default_factory=list,
        description="Zero-based indexes of assertions directly contradicted by the quote.",
    )


class QuoteSelection(BaseModel):
    picks: list[QuotePick]


class CandidateList(BaseModel):
    candidates: list[Candidate]


class LLM:
    def __init__(self, ledger: UsageLedger, model: str | None = None):
        self.ledger = ledger
        model_name = model or os.getenv("DEALLENS_MODEL", DEFAULT_MODEL)
        # langchain-nebius initializes the chat-completions client but not the
        # root client that LangChain's JSON-schema path requires. Supplying the
        # same OpenAI-compatible Nebius client explicitly makes response_format
        # work reliably with Kimi K3.
        root_client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY"),
        )
        self._model = ChatNebius(
            model=model_name,
            temperature=0,
            root_client=root_client,
            # Kimi K3 supports configurable reasoning. Low effort is ample for
            # these small extraction schemas and prevents hidden reasoning from
            # consuming the response window before its JSON is emitted. This
            # cap includes reasoning as well as visible output.
            reasoning_effort="low",
            max_tokens=MAX_COMPLETION_TOKENS,
        )

    def _track(self, message) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        self.ledger.llm_input_tokens += usage.get("input_tokens", 0)
        self.ledger.llm_output_tokens += usage.get("output_tokens", 0)

    def structured(self, schema: type[BaseModel], prompt: str) -> BaseModel:
        model = self._model.with_structured_output(
            schema, method="json_mode", include_raw=True
        )
        schema_prompt = (
            f"{prompt}\n\nReturn only JSON matching this schema:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        last_error: object = "provider returned no parsed object"
        for _attempt in range(STRUCTURED_OUTPUT_ATTEMPTS):
            result = model.invoke(schema_prompt)
            raw = result.get("raw")
            if raw is not None:
                self._track(raw)
            parsed = result.get("parsed")
            if parsed is not None:
                return parsed
            last_error = result.get("parsing_error") or last_error
        raise RuntimeError(
            f"Nebius structured output failed after {STRUCTURED_OUTPUT_ATTEMPTS} "
            f"attempts: {last_error}"
        )

    def text(self, prompt: str) -> str:
        message = self._model.invoke(prompt)
        self._track(message)
        content = message.content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        return content.strip()
