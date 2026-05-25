"""Shared typed models for local workflow objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GeneratedScript:
    """A locally generated short-form video script."""

    angle: str
    title: str
    script_text: str


@dataclass(slots=True)
class ComplianceResult:
    """Result returned by the compliance checker."""

    status: str
    risky_terms: list[str]
    has_disclosure: bool
    messages: list[str]
