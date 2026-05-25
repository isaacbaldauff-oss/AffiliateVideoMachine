"""Local script generation from editable templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from app.config import PROJECT_ROOT
from app.models import GeneratedScript


DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "script_angles.yaml"


class SafeFormatDict(dict[str, str]):
    """Format dictionary that keeps unknown placeholders visible."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _clean_value(value: Any, fallback: str = "this product") -> str:
    """Convert a product field into display-safe template text."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _load_templates(template_path: Path = DEFAULT_TEMPLATE_PATH) -> dict[str, Any]:
    """Load script templates from YAML."""
    if not template_path.exists():
        raise FileNotFoundError(f"Script template file not found: {template_path}")
    with template_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    angles = loaded.get("angles")
    if not isinstance(angles, dict):
        raise ValueError("Script template file must contain an 'angles' mapping.")
    return angles


def _product_context(product: Mapping[str, Any]) -> SafeFormatDict:
    """Build string context used by script templates."""
    price = product.get("price")
    price_text = f"${float(price):.2f}" if isinstance(price, int | float) and price > 0 else "the current listed price"
    rating = product.get("rating")
    rating_text = f"{float(rating):.1f}/5" if isinstance(rating, int | float) and rating > 0 else "the listed rating"

    return SafeFormatDict(
        product_name=_clean_value(product.get("product_name")),
        product_url=_clean_value(product.get("product_url"), "the product link"),
        platform=_clean_value(product.get("platform"), "the affiliate platform"),
        category=_clean_value(product.get("category"), "everyday essentials"),
        price=price_text,
        commission_rate=_clean_value(product.get("commission_rate"), "the configured"),
        rating=rating_text,
        review_count=_clean_value(product.get("review_count"), "available"),
        notes=_clean_value(product.get("notes"), "Focus on a useful, honest demo."),
    )


def generate_scripts(product: Mapping[str, Any], template_path: Path = DEFAULT_TEMPLATE_PATH) -> list[GeneratedScript]:
    """Generate one local script for every configured angle."""
    templates = _load_templates(template_path)
    context = _product_context(product)
    generated: list[GeneratedScript] = []

    for angle, template in templates.items():
        if not isinstance(template, dict):
            continue
        title_template = str(template.get("title", "{product_name} short"))
        body_template = str(template.get("body", ""))
        generated.append(
            GeneratedScript(
                angle=str(angle),
                title=title_template.format_map(context),
                script_text=body_template.format_map(context).strip() + "\n",
            )
        )

    return generated
