"""Product scoring helpers."""

from __future__ import annotations

from math import log10
from typing import Any, Mapping


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp a numeric value to the scoring range."""
    return max(low, min(high, value))


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert unknown input into a float without raising UI-facing errors."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _review_score(review_count: float, max_expected_reviews: float) -> float:
    """Score review volume with diminishing returns."""
    if review_count <= 0 or max_expected_reviews <= 0:
        return 0.0
    return clamp((log10(review_count + 1) / log10(max_expected_reviews + 1)) * 100)


def calculate_product_score(product: Mapping[str, Any], config: Mapping[str, Any]) -> float:
    """Calculate a 0-100 weighted product score from product fields and config."""
    scoring_config = config.get("scoring", {})
    weights = scoring_config.get("weights", {})
    max_price = _as_float(scoring_config.get("max_expected_price", 200.0), 200.0)
    max_commission = _as_float(scoring_config.get("max_expected_commission_rate", 50.0), 50.0)
    max_reviews = _as_float(scoring_config.get("max_expected_reviews", 5000), 5000)

    price = _as_float(product.get("price"))
    commission_rate = _as_float(product.get("commission_rate"))
    rating = _as_float(product.get("rating"))
    review_count = _as_float(product.get("review_count"))
    visual_demo_score = _as_float(product.get("visual_demo_score"), 50.0)
    compliance_risk_score = _as_float(product.get("compliance_risk_score"))

    components = {
        "commission_rate": clamp((commission_rate / max_commission) * 100 if max_commission else 0),
        "price": clamp((price / max_price) * 100 if max_price else 0),
        "rating": clamp((rating / 5.0) * 100),
        "review_count": _review_score(review_count, max_reviews),
        "visual_demo_score": clamp(visual_demo_score),
        "compliance_risk_score": clamp(100 - compliance_risk_score),
    }

    total_weight = sum(_as_float(weight) for weight in weights.values())
    if total_weight <= 0:
        return 0.0

    weighted_score = 0.0
    for key, component_score in components.items():
        weighted_score += component_score * _as_float(weights.get(key))

    return round(clamp(weighted_score / total_weight), 2)
