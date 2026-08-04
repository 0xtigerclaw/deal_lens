"""Offline contract tests for Tavily's asynchronous Research API wrapper."""

from __future__ import annotations

import pytest

from deallens.models import UsageLedger
from deallens.discover import OUTPUT_SCHEMA
from deallens.tavily_client import Tavily


class FakeClient:
    def __init__(self, polls: list[dict]):
        self.polls = iter(polls)
        self.request_ids: list[str] = []

    def research(self, **_kwargs) -> dict:
        return {"request_id": "research-123", "status": "pending"}

    def get_research(self, request_id: str) -> dict:
        self.request_ids.append(request_id)
        return next(self.polls)


class FakeUsageResponse:
    def __init__(self, usage):
        self.usage = usage

    def raise_for_status(self):
        return None

    def json(self):
        key = self.usage if isinstance(self.usage, dict) else {"usage": self.usage}
        return {"key": key}


class FakeUsageSession:
    def __init__(self, values):
        self.values = iter(values)

    def get(self, _url, timeout=30):
        assert timeout == 30
        return FakeUsageResponse(next(self.values))


def wrapper(polls: list[dict]) -> Tavily:
    tavily = object.__new__(Tavily)
    tavily._client = FakeClient(polls)
    tavily.ledger = UsageLedger()
    return tavily


def test_research_polls_pending_task_until_structured_content_is_complete():
    tavily = wrapper(
        [
            {"request_id": "research-123", "status": "pending"},
            {
                "request_id": "research-123",
                "status": "completed",
                "content": {"candidates": [{"claim": "A director resigned"}]},
            },
        ]
    )

    result = tavily.research(input="screen company", poll_interval=0)

    assert result["content"]["candidates"][0]["claim"] == "A director resigned"
    assert tavily._client.request_ids == ["research-123", "research-123"]


def test_research_failure_is_not_returned_as_an_empty_result():
    tavily = wrapper(
        [{"request_id": "research-123", "status": "failed", "error": "worker error"}]
    )

    with pytest.raises(RuntimeError, match="worker error"):
        tavily.research(input="screen company", poll_interval=0)


def test_research_requires_a_request_id():
    tavily = wrapper([])
    tavily._client.research = lambda **_kwargs: {"status": "pending"}

    with pytest.raises(RuntimeError, match="request_id"):
        tavily.research(input="screen company", poll_interval=0)


def test_research_schema_uses_tavily_top_level_contract():
    assert set(OUTPUT_SCHEMA) == {"properties", "required"}
    candidates = OUTPUT_SCHEMA["properties"]["candidates"]
    assert candidates["description"]
    assert all(
        definition.get("description")
        for definition in candidates["items"]["properties"].values()
    )
    assert candidates["items"]["properties"]["date"]["type"] == "string"


def test_research_books_account_usage_delta():
    tavily = wrapper(
        [{"request_id": "research-123", "status": "completed", "content": {}}]
    )
    tavily._client.base_url = "https://api.tavily.test"
    tavily._client.session = FakeUsageSession(
        [
            {"usage": 100, "research_usage": 40},
            {"usage": 123, "research_usage": 55},
        ]
    )

    tavily.research(input="screen company", poll_interval=0)

    assert tavily.ledger.credits_by_endpoint["research"] == 15
    assert tavily.ledger.usage_complete


def test_research_usage_warning_describes_delayed_counter(monkeypatch):
    tavily = wrapper(
        [{"request_id": "research-123", "status": "completed", "content": {}}]
    )
    tavily._client.base_url = "https://api.tavily.test"
    unchanged = {"usage": 100, "research_usage": 40}
    tavily._client.session = FakeUsageSession([unchanged] * 6)
    monkeypatch.setattr("deallens.tavily_client.time.sleep", lambda _seconds: None)

    tavily.research(input="screen company", poll_interval=0)

    assert not tavily.ledger.usage_complete
    assert tavily.ledger.usage_notes == []


def test_extract_uses_bounded_query_focused_chunks():
    class ExtractClient:
        def __init__(self):
            self.kwargs = None

        def extract(self, **kwargs):
            self.kwargs = kwargs
            return {"results": [], "failed_results": [], "usage": {"credits": 1}}

    tavily = object.__new__(Tavily)
    tavily._client = ExtractClient()
    tavily.ledger = UsageLedger()

    tavily.extract(
        urls=["https://example.com/filing"],
        query="specific claim " * 100,
        chunks_per_source=99,
    )

    assert tavily._client.kwargs["query"] == ("specific claim " * 100)[:400]
    assert tavily._client.kwargs["chunks_per_source"] == 5
    assert tavily._client.kwargs["extract_depth"] == "basic"
    assert tavily.ledger.credits_by_endpoint["extract"] == 1
