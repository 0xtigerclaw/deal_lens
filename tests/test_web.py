"""Local web interface contracts without external provider calls."""

import time

from fastapi.testclient import TestClient

from deallens.entity import EntityCandidate, EntityResolution
from deallens import web as web_module
from deallens.web import ScreenRequest, app

client = TestClient(app)


def test_interface_shell_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "DealLens — Acquisition Intelligence for GPs" in response.text
    assert "Prepare IC memo" in response.text
    assert "Active screenings" in response.text
    assert "Fixture memo" not in response.text


def test_health_reports_provider_presence_without_exposing_secrets():
    payload = client.get("/api/health").json()

    assert payload["status"] == "ok"
    assert set(payload["providers"]) == {"tavily", "nebius", "langsmith"}
    assert "api_key" not in str(payload).lower()
    assert "Kimi-K3" in payload["model"]
    assert payload["observability"]["root_span"] == "deallens.screen"
    assert payload["observability"]["project"] == "Deal_Lens"


def test_personal_tavily_key_is_accepted_without_being_exposed(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    response = client.get(
        "/api/health", headers={"X-Tavily-API-Key": "tvly-personal-secret"}
    )

    assert response.status_code == 200
    assert response.json()["providers"]["tavily"] is True
    assert "personal-secret" not in response.text


def test_company_presets_return_runnable_legal_entities():
    response = client.get("/api/presets")
    presets = response.json()

    assert response.status_code == 200
    assert [preset["id"] for preset in presets] == ["wise", "revolut", "thg"]
    assert all(
        preset["company"]
        and preset["domain"]
        and preset["company_id"]
        and preset["jurisdiction"] == "UK"
        for preset in presets
    )


def test_new_user_can_start_without_a_legal_entity_id():
    request = ScreenRequest(
        company="  Monzo  ",
        domain="https://www.monzo.com",
        company_id="  ",
    )

    assert request.company == "Monzo"
    assert request.domain == "monzo.com"
    assert request.company_id is None
    assert request.jurisdiction == "UK"


def test_entity_endpoint_returns_candidates_without_starting_a_screen(
    monkeypatch,
):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    class FakeTavily:
        def __init__(self, ledger):
            self.ledger = ledger

    def fake_resolve(tavily, pack, company, domain):
        assert company == "Monzo"
        assert domain == "monzo.com"
        return EntityResolution(
            query=company,
            jurisdiction=pack.name,
            registry="find-and-update.company-information.service.gov.uk",
            candidates=[
                EntityCandidate(
                    legal_name="MONZO BANK LIMITED",
                    company_id="09446231",
                    registry_url=(
                        "https://find-and-update.company-information.service.gov.uk/"
                        "company/09446231"
                    ),
                    confidence=0.94,
                    source="find-and-update.company-information.service.gov.uk",
                )
            ],
            tavily_credits=1,
        )

    monkeypatch.setattr("deallens.tavily_client.Tavily", FakeTavily)
    monkeypatch.setattr("deallens.web.resolve_entity", fake_resolve)

    response = client.post(
        "/api/entities/resolve",
        json={"company": "Monzo", "domain": "monzo.com", "jurisdiction": "UK"},
    )

    assert response.status_code == 200
    assert response.json()["candidates"][0]["company_id"] == "09446231"


def test_active_screen_ledger_lists_every_background_job(monkeypatch):
    request = ScreenRequest(company="Arm Holdings", domain="arm.com")
    running = web_module.JobRecord("arm-running", request)
    running.status = "running"
    running.started_monotonic = time.monotonic() - 12
    running.update("verification", "Checking 3 of 9: regulatory", 51)
    queued = web_module.JobRecord(
        "shell-queued",
        ScreenRequest(company="Shell", domain="shell.com"),
    )
    monkeypatch.setattr(
        web_module,
        "_jobs",
        {running.id: running, queued.id: queued},
    )

    response = client.get("/api/screens")

    assert response.status_code == 200
    assert [job["id"] for job in response.json()] == ["arm-running", "shell-queued"]
    assert response.json()[0]["request"]["company"] == "Arm Holdings"
    assert response.json()[0]["percent"] == 51


def test_duplicate_active_screen_submission_reuses_existing_job(
    monkeypatch,
):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    request = ScreenRequest(company="Arm Holdings", domain="arm.com")
    running = web_module.JobRecord("arm-running", request)
    running.status = "running"
    running.started_monotonic = time.monotonic()
    monkeypatch.setattr(web_module, "_jobs", {running.id: running})
    submissions = []

    class RecordingExecutor:
        def submit(self, *args):
            submissions.append(args)

    monkeypatch.setattr(web_module, "_executor", RecordingExecutor())

    response = client.post(
        "/api/screens",
        json={"company": "Arm Holdings", "domain": "arm.com"},
    )

    assert response.status_code == 202
    assert response.json()["id"] == "arm-running"
    assert len(web_module._jobs) == 1
    assert submissions == []


def test_archive_reopens_retained_wise_and_revolut_screens(
    monkeypatch, tmp_path
):
    # Prove the committed examples work on a fresh clone without local reports.
    monkeypatch.setattr(web_module, "WEB_REPORT_ROOT", tmp_path / "reports")
    monkeypatch.setattr(web_module, "LEGACY_ARCHIVE_JSONS", ())
    response = client.get("/api/archive")
    archive = response.json()

    assert response.status_code == 200
    assert {record["target"] for record in archive} >= {"Wise Limited", "Revolut Ltd"}

    wise_summary = next(record for record in archive if record["target"] == "Wise Limited")
    detail = client.get(f"/api/archive/{wise_summary['id']}")
    payload = detail.json()

    assert detail.status_code == 200
    assert payload["archived"] is True
    assert payload["status"] == "completed"
    assert payload["result"]["target"] == "Wise Limited"
    assert client.get(payload["memo_url"]).status_code == 200
    assert client.get(payload["evidence_url"]).status_code == 200


def test_demo_endpoint_returns_a_complete_renderable_screen():
    response = client.post("/api/demo", json={})
    payload = response.json()

    assert response.status_code == 201
    assert payload["status"] == "completed"
    assert payload["percent"] == 100
    assert payload["result"]["risk_level"] == "REVIEW REQUIRED"
    assert payload["memo_url"].endswith("/memo")
    assert payload["evidence_url"].endswith("/evidence")

    memo = client.get(payload["memo_url"])
    evidence = client.get(payload["evidence_url"])
    assert memo.status_code == 200
    assert "Investment Committee Diligence Memo" in memo.text
    assert evidence.status_code == 200
    assert evidence.json()["target"] == "Acme Industrial Ltd"


def test_screen_request_rejects_an_invalid_domain_before_starting_job():
    response = client.post(
        "/api/screens",
        json={
            "company": "Acme Ltd",
            "domain": "not a domain",
            "company_id": "12345678",
            "jurisdiction": "UK",
        },
    )

    assert response.status_code == 422


def test_unknown_job_is_not_found():
    response = client.get("/api/screens/does-not-exist")

    assert response.status_code == 404
