"""Thin Tavily wrapper: usage accounting, 429 retry, failure surfacing.

Every call passes include_usage=True and books credits into a UsageLedger so
each screen can print what it actually cost.
"""

from __future__ import annotations

import time
from typing import Any

from langsmith import traceable
from tavily import TavilyClient

from .models import UsageLedger

_MAX_RETRIES = 2
_RESEARCH_POLL_SECONDS = 5.0
_RESEARCH_TIMEOUT_SECONDS = 600.0
_RESEARCH_USAGE_RETRIES = 5
_RESEARCH_USAGE_POLL_SECONDS = 1.0


class Tavily:
    def __init__(self, api_key: str | None = None, ledger: UsageLedger | None = None):
        self._client = TavilyClient(api_key=api_key) if api_key else TavilyClient()
        self.ledger = ledger or UsageLedger()

    # -- internals -----------------------------------------------------------

    def _call(self, endpoint: str, fn, /, **kwargs) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = fn(**kwargs)
                self._book(endpoint, response)
                return response
            except Exception as exc:  # tavily-python raises per-status exceptions
                last_exc = exc
                retry_after = getattr(exc, "retry_after", None)
                is_rate_limit = "429" in str(exc) or retry_after is not None
                if attempt < _MAX_RETRIES and is_rate_limit:
                    time.sleep(float(retry_after or 2 * (attempt + 1)))
                    continue
                raise
        raise last_exc  # pragma: no cover

    def _book(self, endpoint: str, response: dict[str, Any]) -> None:
        usage = response.get("usage") if isinstance(response, dict) else None
        if isinstance(usage, dict):
            credits = usage.get("credits", 0) or 0
            self.ledger.add_credits(endpoint, float(credits))

    def _usage_snapshot(self) -> dict[str, float] | None:
        """Read key-level Tavily counters for Research delta accounting."""
        session = getattr(self._client, "session", None)
        base_url = getattr(self._client, "base_url", None)
        if session is None or not base_url:
            return None
        try:
            response = session.get(f"{base_url}/usage", timeout=30)
            response.raise_for_status()
            key_usage = response.json().get("key", {})
            return {
                key: float(value)
                for key, value in key_usage.items()
                if key in {"usage", "research_usage"} and value is not None
            }
        except Exception:
            return None

    @staticmethod
    def _research_counter(snapshot: dict[str, float] | None) -> float | None:
        if not snapshot:
            return None
        return snapshot.get("research_usage", snapshot.get("usage"))

    def _book_research_delta(
        self,
        before: dict[str, float] | None,
        booked_before: float,
    ) -> None:
        # Newer Research responses may eventually carry per-call usage. If the
        # normal response accounting already booked it, do not add a second
        # account-level delta.
        if self.ledger.credits_by_endpoint.get("research", 0.0) > booked_before:
            return

        before_value = self._research_counter(before)
        after_value: float | None = None
        for attempt in range(_RESEARCH_USAGE_RETRIES):
            after_value = self._research_counter(self._usage_snapshot())
            if (
                before_value is not None
                and after_value is not None
                and after_value > before_value
            ):
                self.ledger.add_credits("research", after_value - before_value)
                return
            if before_value is None or after_value is None:
                break
            if attempt < _RESEARCH_USAGE_RETRIES - 1:
                time.sleep(_RESEARCH_USAGE_POLL_SECONDS)

        self.ledger.usage_complete = False

    # -- endpoints -------------------------------------------------------------

    @traceable(name="tavily.research", run_type="retriever")
    def research(
        self,
        *,
        input: str,
        output_schema: dict | None = None,
        poll_interval: float = _RESEARCH_POLL_SECONDS,
        timeout: float = _RESEARCH_TIMEOUT_SECONDS,
    ) -> dict:
        """Create a research task and poll until Tavily returns its content.

        The non-streaming Research API is asynchronous: POST /research returns
        a pending task, not the report. Returning that task to discovery would
        turn an unfinished observation into an empty screen.
        """
        kwargs: dict[str, Any] = {"input": input, "model": "mini"}
        if output_schema is not None:
            kwargs["output_schema"] = output_schema

        usage_before = self._usage_snapshot()
        booked_before = self.ledger.credits_by_endpoint.get("research", 0.0)
        response = self._call("research", self._client.research, **kwargs)
        if response.get("status") == "completed":
            self._book_research_delta(usage_before, booked_before)
            return response

        request_id = response.get("request_id")
        if not request_id:
            raise RuntimeError("Tavily Research did not return a request_id")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if poll_interval:
                time.sleep(poll_interval)
            response = self._call(
                "research", self._client.get_research, request_id=request_id
            )
            status = response.get("status")
            if status == "completed":
                self._book_research_delta(usage_before, booked_before)
                return response
            if status == "failed":
                raise RuntimeError(
                    f"Tavily Research task {request_id} failed: "
                    f"{response.get('error') or 'no reason provided'}"
                )

        raise TimeoutError(
            f"Tavily Research task {request_id} did not finish within {timeout:g}s"
        )

    @traceable(name="tavily.search", run_type="retriever")
    def search(
        self,
        *,
        query: str,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        topic: str = "general",
        country: str | None = None,
        max_results: int = 8,
        search_depth: str = "basic",
        chunks_per_source: int = 3,
        time_range: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        exact_match: bool = False,
    ) -> dict:
        kwargs: dict[str, Any] = {
            "query": query[:400],
            "include_domains": include_domains or [],
            "exclude_domains": exclude_domains or [],
            "topic": topic,
            "max_results": max_results,
            "search_depth": search_depth,
            "chunks_per_source": max(1, min(chunks_per_source, 3)),
            "exact_match": exact_match,
            "include_usage": True,
        }
        if time_range:
            kwargs["time_range"] = time_range
        if country and topic == "general":
            kwargs["country"] = country
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        return self._call(
            "search",
            self._client.search,
            **kwargs,
        )

    @traceable(name="tavily.map", run_type="retriever")
    def map(
        self,
        *,
        url: str,
        instructions: str,
        max_depth: int = 2,
        max_breadth: int = 20,
        limit: int = 12,
    ) -> dict:
        return self._call(
            "map",
            self._client.map,
            url=url,
            instructions=instructions,
            max_depth=max(1, min(max_depth, 5)),
            max_breadth=max(1, min(max_breadth, 500)),
            limit=max(1, min(limit, 50)),
            allow_external=False,
            include_usage=True,
        )

    @traceable(name="tavily.extract", run_type="retriever")
    def extract(
        self,
        *,
        urls: list[str],
        query: str | None = None,
        chunks_per_source: int = 3,
    ) -> dict:
        """Batch extract (<=20 URLs per call, enforced by caller batching).
        A query asks Tavily to return only the most relevant short chunks from
        long pages, keeping the downstream quote-classification prompt bounded.
        Failed results are surfaced, never swallowed.
        """
        kwargs: dict[str, Any] = {
            "urls": urls[:20],
            "extract_depth": "basic",
            "format": "markdown",
            "include_usage": True,
        }
        if query:
            kwargs["query"] = query[:400]
            kwargs["chunks_per_source"] = max(1, min(chunks_per_source, 5))
        return self._call(
            "extract",
            self._client.extract,
            **kwargs,
        )
