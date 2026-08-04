"""Local analyst UI and background-job API for DealLens."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from .config import PACKAGE_ROOT, load_jurisdiction, load_policy
from .demo import run_demo
from .entity import resolve_entity
from .memo import pdf_filename, render_pdf, write_outputs
from .models import ScreenResult, UsageLedger

load_dotenv()

UI_ROOT = Path(__file__).with_name("ui")
WEB_REPORT_ROOT = PACKAGE_ROOT / "reports" / "web"
EXAMPLE_ARCHIVE_ROOT = PACKAGE_ROOT / "examples" / "screens"
MAX_CONCURRENT_SCREENS = 2
COMPANY_PRESETS = (
    {
        "id": "wise",
        "company": "Wise Limited",
        "domain": "wise.com",
        "company_id": "13211214",
        "jurisdiction": "UK",
        "descriptor": "Payments",
    },
    {
        "id": "revolut",
        "company": "Revolut Ltd",
        "domain": "revolut.com",
        "company_id": "08804411",
        "jurisdiction": "UK",
        "descriptor": "Fintech",
    },
    {
        "id": "thg",
        "company": "THG PLC",
        "domain": "thg.com",
        "company_id": "06539496",
        "jurisdiction": "UK",
        "descriptor": "Commerce",
    },
)
LEGACY_ARCHIVE_JSONS = (
    PACKAGE_ROOT / "reports" / "wise-live-focused" / "wise-limited-2026-08-03.json",
)

app = FastAPI(
    title="DealLens",
    description="Evidence-backed acquisition intelligence for IC memos",
    version="0.2.0",
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/assets", StaticFiles(directory=UI_ROOT), name="assets")


class ScreenRequest(BaseModel):
    company: str = Field(min_length=2, max_length=160)
    domain: str = Field(min_length=3, max_length=253)
    company_id: str | None = Field(default=None, min_length=2, max_length=40)
    jurisdiction: str = Field(default="UK", min_length=2, max_length=10)
    policy_profile: Literal["default", "searchfund"] = "default"

    @field_validator("company", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("company_id", mode="before")
    @classmethod
    def normalize_company_id(cls, value: object) -> str | None:
        normalized = str(value).strip() if value is not None else ""
        return normalized or None

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        raw = value.strip().lower()
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        domain = (parsed.hostname or "").removeprefix("www.")
        if not domain or "." not in domain or not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise ValueError("Enter a valid company domain")
        return domain

    @field_validator("jurisdiction")
    @classmethod
    def normalize_jurisdiction(cls, value: str) -> str:
        return value.strip().upper()


class JobRecord:
    def __init__(
        self,
        job_id: str,
        request: ScreenRequest,
        *,
        demo: bool = False,
        tavily_api_key: str | None = None,
    ):
        now = datetime.now(timezone.utc)
        self.id = job_id
        self.request = request
        self.demo = demo
        # Request-scoped secret. It is deliberately omitted from public().
        self.tavily_api_key = tavily_api_key
        self.tavily_key_fingerprint = (
            hashlib.sha256(tavily_api_key.encode()).hexdigest()
            if tavily_api_key
            else None
        )
        self.status: Literal["queued", "running", "completed", "failed"] = "queued"
        self.stage = "queued"
        self.message = "Queued for memo preparation"
        self.percent = 0
        self.created_at = now
        self.updated_at = now
        self.started_monotonic: float | None = None
        self.finished_monotonic: float | None = None
        self.events: list[dict] = []
        self.result: ScreenResult | None = None
        self.memo_path: Path | None = None
        self.evidence_path: Path | None = None
        self.error: str | None = None

    def update(self, stage: str, message: str, percent: int) -> None:
        self.stage = stage
        self.message = message
        self.percent = percent
        self.updated_at = datetime.now(timezone.utc)
        self.events.append(
            {
                "stage": stage,
                "message": message,
                "percent": percent,
                "at": self.updated_at.isoformat(),
            }
        )
        self.events = self.events[-16:]

    def public(self) -> dict:
        end = self.finished_monotonic or time.monotonic()
        elapsed = end - self.started_monotonic if self.started_monotonic else 0.0
        payload = {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "percent": self.percent,
            "elapsed_seconds": round(elapsed, 1),
            "created_at": self.created_at.isoformat(),
            "request": self.request.model_dump(),
            "demo": self.demo,
            "events": list(self.events),
            "error": self.error,
            "result": self.result.model_dump(mode="json") if self.result else None,
            "memo_url": f"/api/screens/{self.id}/memo" if self.memo_path else None,
            "pdf_url": f"/api/screens/{self.id}/pdf" if self.result else None,
            "evidence_url": (
                f"/api/screens/{self.id}/evidence" if self.evidence_path else None
            ),
        }
        return payload


@dataclass(frozen=True)
class ArchiveRecord:
    id: str
    result: ScreenResult
    memo_path: Path
    evidence_path: Path


_jobs: dict[str, JobRecord] = {}
_jobs_lock = threading.RLock()
_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_SCREENS,
    thread_name_prefix="deallens-screen",
)


def _new_job(request: ScreenRequest, *, demo: bool = False) -> JobRecord:
    job = JobRecord(uuid.uuid4().hex[:12], request, demo=demo)
    with _jobs_lock:
        _jobs[job.id] = job
    return job


def _get_job(job_id: str) -> JobRecord:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Screen not found")
    return job


def _public_job(job: JobRecord) -> dict:
    with _jobs_lock:
        return job.public()


def _active_jobs() -> list[JobRecord]:
    """Return every server-held job that is still consuming worker capacity."""
    with _jobs_lock:
        jobs = [
            job for job in _jobs.values() if job.status in ("queued", "running")
        ]
    return sorted(jobs, key=lambda job: job.created_at)


def _new_live_job(
    request: ScreenRequest, tavily_api_key: str | None = None
) -> tuple[JobRecord, bool]:
    """Atomically create a live job or return its active identical run."""
    request_data = request.model_dump()
    key_fingerprint = (
        hashlib.sha256(tavily_api_key.encode()).hexdigest()
        if tavily_api_key
        else None
    )
    with _jobs_lock:
        existing = next(
            (
                job
                for job in _jobs.values()
                if job.status in ("queued", "running")
                and job.request.model_dump() == request_data
                and not job.demo
                and job.tavily_key_fingerprint == key_fingerprint
            ),
            None,
        )
        if existing is not None:
            return existing, False
        job = JobRecord(
            uuid.uuid4().hex[:12], request, tavily_api_key=tavily_api_key
        )
        _jobs[job.id] = job
    return job, True


def _archive_records() -> dict[str, ArchiveRecord]:
    """Load the newest completed report per legal entity from durable artifacts."""
    candidates = list(WEB_REPORT_ROOT.glob("*/*.json"))
    candidates.extend(EXAMPLE_ARCHIVE_ROOT.glob("*/*.json"))
    candidates.extend(path for path in LEGACY_ARCHIVE_JSONS if path.exists())
    newest_by_entity: dict[str, ArchiveRecord] = {}

    for evidence_path in candidates:
        memo_path = evidence_path.with_suffix(".md")
        if (
            not memo_path.exists()
            and evidence_path.is_relative_to(EXAMPLE_ARCHIVE_ROOT)
        ):
            memo_path = evidence_path.parent / "memo.md"
        if not memo_path.exists():
            continue
        try:
            result = ScreenResult.model_validate_json(evidence_path.read_text())
        except (OSError, ValueError):
            continue
        if result.domain.endswith(".example"):
            continue

        if evidence_path.is_relative_to(WEB_REPORT_ROOT):
            archive_id = evidence_path.parent.name
        elif evidence_path.is_relative_to(EXAMPLE_ARCHIVE_ROOT):
            archive_id = f"example-{evidence_path.parent.name}"
        else:
            archive_id = f"legacy-{evidence_path.stem}"
        record = ArchiveRecord(
            id=archive_id,
            result=result,
            memo_path=memo_path,
            evidence_path=evidence_path,
        )
        entity_key = result.company_id or result.domain
        current = newest_by_entity.get(entity_key)
        if current is None or result.generated_at > current.result.generated_at:
            newest_by_entity[entity_key] = record

    records = sorted(
        newest_by_entity.values(),
        key=lambda record: record.result.generated_at,
        reverse=True,
    )
    return {record.id: record for record in records}


def _get_archive_record(archive_id: str) -> ArchiveRecord:
    record = _archive_records().get(archive_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Archived screen not found")
    return record


def _archive_summary(record: ArchiveRecord) -> dict:
    result = record.result
    surfaced = sum(finding.status != "rejected" for finding in result.findings)
    return {
        "id": record.id,
        "target": result.target,
        "domain": result.domain,
        "company_id": result.company_id,
        "jurisdiction": result.jurisdiction,
        "generated_at": result.generated_at.isoformat(),
        "risk_level": result.risk_level,
        "surfaced_findings": surfaced,
        "total_findings": len(result.findings),
    }


def _archive_public(record: ArchiveRecord) -> dict:
    result = record.result
    return {
        "id": record.id,
        "status": "completed",
        "stage": "complete",
        "message": "Archived evidence package loaded",
        "percent": 100,
        "elapsed_seconds": result.usage.wall_seconds,
        "created_at": result.generated_at.isoformat(),
        "request": {
            "company": result.target,
            "domain": result.domain,
            "company_id": result.company_id or "Not supplied",
            "jurisdiction": result.jurisdiction,
            "policy_profile": "default",
        },
        "demo": False,
        "archived": True,
        "events": [],
        "error": None,
        "result": result.model_dump(mode="json"),
        "memo_url": f"/api/archive/{record.id}/memo",
        "pdf_url": f"/api/archive/{record.id}/pdf",
        "evidence_url": f"/api/archive/{record.id}/evidence",
    }


def _execute_live(job_id: str) -> None:
    from .llm import LLM
    from .pipeline import run_screen
    from .tavily_client import Tavily

    job = _get_job(job_id)
    job.status = "running"
    job.started_monotonic = time.monotonic()
    job.update("starting", "Starting memo research", 2)

    def progress(stage: str, message: str, percent: int) -> None:
        with _jobs_lock:
            job.update(stage, message, percent)

    try:
        policy_path = (
            PACKAGE_ROOT / "policy.searchfund.yaml"
            if job.request.policy_profile == "searchfund"
            else None
        )
        ledger = UsageLedger()
        tavily_api_key = job.tavily_api_key
        # Keep the request secret only long enough for the worker to claim it.
        job.tavily_api_key = None
        tavily = Tavily(api_key=tavily_api_key, ledger=ledger)
        result = run_screen(
            company=job.request.company,
            domain=job.request.domain,
            company_id=job.request.company_id,
            jurisdiction_pack=load_jurisdiction(job.request.jurisdiction),
            policy=load_policy(policy_path),
            tavily=tavily,
            llm=LLM(ledger),
            progress=progress,
        )
        memo_path, evidence_path = write_outputs(result, WEB_REPORT_ROOT / job.id)
        with _jobs_lock:
            job.result = result
            job.memo_path = memo_path
            job.evidence_path = evidence_path
            job.status = "completed"
            job.finished_monotonic = time.monotonic()
            job.update("complete", "IC memo ready", 100)
    except Exception as exc:
        with _jobs_lock:
            job.status = "failed"
            job.finished_monotonic = time.monotonic()
            job.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            job.update(
                "failed",
                "IC memo incomplete; no memo produced",
                job.percent,
            )


@app.get("/api/health")
def health(x_tavily_api_key: str | None = Header(default=None)) -> dict:
    return {
        "status": "ok",
        "providers": {
            "tavily": bool(x_tavily_api_key or os.getenv("TAVILY_API_KEY")),
            "nebius": bool(os.getenv("NEBIUS_API_KEY")),
            "langsmith": bool(os.getenv("LANGSMITH_API_KEY")),
        },
        "model": os.getenv("DEALLENS_MODEL", "moonshotai/Kimi-K3"),
        "observability": {
            "enabled": os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
            "project": os.getenv("LANGSMITH_PROJECT", "Deal_Lens"),
            "region": (
                "EU"
                if "eu.api.smith.langchain.com"
                in os.getenv("LANGSMITH_ENDPOINT", "")
                else "US"
            ),
            "root_span": "deallens.screen",
        },
    }


@app.get("/api/presets")
def company_presets() -> list[dict[str, str]]:
    """Return curated, legally identified targets for quick UI smoke tests."""
    return [dict(preset) for preset in COMPANY_PRESETS]


@app.get("/api/screens")
def list_screens() -> list[dict]:
    """List all queued/running jobs so browsers cannot lose background work."""
    return [_public_job(job) for job in _active_jobs()]


@app.post("/api/entities/resolve")
def resolve_company_entity(
    request: ScreenRequest,
    x_tavily_api_key: str | None = Header(default=None),
) -> dict:
    """Return registry candidates for explicit user confirmation."""
    tavily_api_key = x_tavily_api_key or os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise HTTPException(
            status_code=503,
            detail="Missing provider configuration: TAVILY_API_KEY",
        )
    try:
        pack = load_jurisdiction(request.jurisdiction)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    from .tavily_client import Tavily

    try:
        tavily = (
            Tavily(api_key=x_tavily_api_key, ledger=UsageLedger())
            if x_tavily_api_key
            else Tavily(ledger=UsageLedger())
        )
        resolution = resolve_entity(
            tavily,
            pack,
            request.company,
            request.domain,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Registry lookup failed: {type(exc).__name__}: {str(exc)[:240]}",
        ) from exc
    return resolution.model_dump(mode="json")


@app.get("/api/archive")
def archive_screens() -> list[dict]:
    return [_archive_summary(record) for record in _archive_records().values()]


@app.get("/api/archive/{archive_id}")
def read_archived_screen(archive_id: str) -> dict:
    return _archive_public(_get_archive_record(archive_id))


@app.get("/api/archive/{archive_id}/memo")
def download_archived_memo(archive_id: str) -> FileResponse:
    record = _get_archive_record(archive_id)
    return FileResponse(
        record.memo_path,
        media_type="text/markdown",
        filename=record.memo_path.name,
    )


@app.get("/api/archive/{archive_id}/pdf")
def download_archived_pdf(archive_id: str) -> Response:
    result = _get_archive_record(archive_id).result
    return Response(
        content=render_pdf(result),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_filename(result)}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/archive/{archive_id}/evidence")
def download_archived_evidence(archive_id: str) -> FileResponse:
    record = _get_archive_record(archive_id)
    return FileResponse(
        record.evidence_path,
        media_type="application/json",
        filename=record.evidence_path.name,
    )


@app.post("/api/screens", status_code=202)
def create_screen(
    request: ScreenRequest,
    x_tavily_api_key: str | None = Header(default=None),
) -> dict:
    tavily_api_key = x_tavily_api_key or os.getenv("TAVILY_API_KEY")
    missing = [
        name
        for name in ("TAVILY_API_KEY", "NEBIUS_API_KEY")
        if not (tavily_api_key if name == "TAVILY_API_KEY" else os.getenv(name))
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Missing provider configuration: {', '.join(missing)}",
        )
    # Validate the jurisdiction before creating an asynchronous job.
    try:
        load_jurisdiction(request.jurisdiction)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job, created = _new_live_job(request, x_tavily_api_key)
    if created:
        _executor.submit(_execute_live, job.id)
    return _public_job(job)


@app.post("/api/demo", status_code=201)
def create_demo() -> dict:
    request = ScreenRequest(
        company="Acme Industrial Ltd",
        domain="acme-industrial.example",
        company_id="00000000",
        jurisdiction="UK",
    )
    job = _new_job(request, demo=True)
    job.status = "running"
    job.started_monotonic = time.monotonic()
    job.update("decision", "Running deterministic fixture gate", 70)
    try:
        result = run_demo(PACKAGE_ROOT)
        memo_path, evidence_path = write_outputs(result, WEB_REPORT_ROOT / job.id)
        job.result = result
        job.memo_path = memo_path
        job.evidence_path = evidence_path
        job.status = "completed"
        job.finished_monotonic = time.monotonic()
        job.update("complete", "Fixture memo ready", 100)
    except Exception as exc:  # pragma: no cover - fixture is covered elsewhere
        job.status = "failed"
        job.finished_monotonic = time.monotonic()
        job.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        job.update("failed", "Fixture screen failed", job.percent)
    return _public_job(job)


@app.get("/api/screens/{job_id}")
def read_screen(job_id: str) -> dict:
    return _public_job(_get_job(job_id))


@app.get("/api/screens/{job_id}/memo")
def download_memo(job_id: str) -> FileResponse:
    job = _get_job(job_id)
    if not job.memo_path or not job.memo_path.exists():
        raise HTTPException(status_code=409, detail="Memo is not ready")
    return FileResponse(
        job.memo_path,
        media_type="text/markdown",
        filename=job.memo_path.name,
    )


@app.get("/api/screens/{job_id}/pdf")
def download_pdf(job_id: str) -> Response:
    job = _get_job(job_id)
    if not job.result or job.status != "completed":
        raise HTTPException(status_code=409, detail="PDF memo is not ready")
    return Response(
        content=render_pdf(job.result),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_filename(job.result)}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/screens/{job_id}/evidence")
def download_evidence(job_id: str) -> FileResponse:
    job = _get_job(job_id)
    if not job.evidence_path or not job.evidence_path.exists():
        raise HTTPException(status_code=409, detail="Evidence package is not ready")
    return FileResponse(
        job.evidence_path,
        media_type="application/json",
        filename=job.evidence_path.name,
    )


@app.get("/{path:path}", include_in_schema=False)
def interface(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    return FileResponse(UI_ROOT / "index.html")
