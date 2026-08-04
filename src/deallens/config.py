"""Loaders for jurisdiction source packs and severity policies.

Both are plain YAML so a fund can adapt DealLens without touching code.
Tier assignment uses registrable-domain suffix matching: "www.fca.org.uk"
matches the pack entry "fca.org.uk", but "notfca.org.uk" does not.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field

from .models import Severity, SourceTier

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


class JurisdictionPack(BaseModel):
    name: str
    primary: list[str] = Field(default_factory=list)
    credible_secondary: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    registry_query: str = ""

    def tier_for(self, url: str) -> SourceTier:
        host = _host(url)
        if _matched_domain(host, self.primary):
            return "primary"
        if _matched_domain(host, self.credible_secondary):
            return "credible_secondary"
        return "other"

    def publisher_for(self, url: str) -> str:
        """Return the configured publisher identity, not an arbitrary subdomain."""
        host = _host(url)
        return (
            _matched_domain(host, self.primary + self.credible_secondary + self.exclude)
            or (host[4:] if host.startswith("www.") else host)
        )

    def is_excluded(self, url: str) -> bool:
        return _matches(_host(url), self.exclude)


class PolicyRule(BaseModel):
    base: Severity = "medium"
    escalate_when: list[str] = Field(default_factory=list)


class Policy(BaseModel):
    rules: dict[str, PolicyRule] = Field(default_factory=dict)


def _host(url: str) -> str:
    netloc = urlparse(url if "//" in url else f"https://{url}").netloc
    return netloc.split("@")[-1].split(":")[0].lower()


def _matches(host: str, domains: list[str]) -> bool:
    return _matched_domain(host, domains) is not None


def _matched_domain(host: str, domains: list[str]) -> str | None:
    matches = [
        domain.lower()
        for domain in domains
        if host == domain.lower() or host.endswith("." + domain.lower())
    ]
    return max(matches, key=len) if matches else None


def load_jurisdiction(code: str, root: Path | None = None) -> JurisdictionPack:
    path = (root or PACKAGE_ROOT) / "jurisdictions" / f"{code.lower()}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in path.parent.glob("*.yaml"))
        raise FileNotFoundError(
            f"No jurisdiction pack '{code}'. Available: {', '.join(available)}"
        )
    data = yaml.safe_load(path.read_text()) or {}
    return JurisdictionPack(name=code.upper(), **data)


def load_policy(path: str | Path | None = None, root: Path | None = None) -> Policy:
    policy_path = Path(path) if path else (root or PACKAGE_ROOT) / "policy.yaml"
    data = yaml.safe_load(policy_path.read_text()) or {}
    return Policy(**data)


def registry_domain(pack: JurisdictionPack) -> str | None:
    """Return the registry host declared by a jurisdiction's query template."""
    match = re.search(r"site:([^\s\"']+)", pack.registry_query or "")
    return match.group(1).lower() if match else None
