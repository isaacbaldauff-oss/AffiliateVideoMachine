"""Local compliance checks for affiliate short-form scripts."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from app.models import ComplianceResult


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Build a case-insensitive pattern for a risky phrase."""
    escaped = re.escape(phrase.strip().lower())
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", flags=re.IGNORECASE)


def _find_terms(text: str, terms: Iterable[str]) -> list[str]:
    """Return configured terms that appear in the provided text."""
    found: list[str] = []
    for term in terms:
        if term and _phrase_pattern(term).search(text):
            found.append(term)
    return found


def check_compliance(content: str, config: Mapping[str, Any]) -> ComplianceResult:
    """Check content for risky terms and affiliate disclosure language."""
    compliance_config = config.get("compliance", {})
    risky_terms = compliance_config.get("risky_terms", [])
    fail_terms = compliance_config.get("fail_terms", [])
    disclosure_terms = compliance_config.get("disclosure_terms", [])

    normalized = content.lower()
    found_risky_terms = _find_terms(normalized, risky_terms)
    found_fail_terms = set(_find_terms(normalized, fail_terms))
    has_disclosure = bool(_find_terms(normalized, disclosure_terms))

    messages: list[str] = []
    if found_risky_terms:
        messages.append("Risky terms or claims found: " + ", ".join(found_risky_terms))
    if not has_disclosure:
        messages.append("Affiliate disclosure language is missing.")
    if not messages:
        messages.append("No configured risky terms found and disclosure language is present.")

    if found_fail_terms:
        status = "fail"
    elif found_risky_terms or not has_disclosure:
        status = "warning"
    else:
        status = "pass"

    return ComplianceResult(
        status=status,
        risky_terms=found_risky_terms,
        has_disclosure=has_disclosure,
        messages=messages,
    )
