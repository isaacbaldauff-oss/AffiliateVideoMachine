"""TikTok caption and disclosure drafting helpers."""

from __future__ import annotations

from textwrap import shorten
from typing import Any, Mapping


def _clean(value: Any) -> str:
    """Normalize display text."""
    return " ".join(str(value or "").split())


def build_tiktok_caption(product: Mapping[str, Any], script: Mapping[str, Any]) -> str:
    """Draft an editable TikTok caption for an affiliate product video."""
    product_name = _clean(product.get("product_name")) or "this product"
    category = _clean(product.get("category")) or "find"
    platform = _clean(product.get("platform")) or "affiliate"
    notes = _clean(product.get("notes"))
    angle = _clean(script.get("angle")).replace("_", " ") or "quick demo"

    hook = notes or f"Quick {angle} for {product_name}."
    hashtags = {
        "#TikTokShop",
        "#TikTokMadeMeBuyIt",
        "#ProductFinds",
        "#Affiliate",
        "#" + "".join(part.capitalize() for part in category.split()[:3]),
    }
    caption = (
        f"Affiliate disclosure: I may earn a commission. "
        f"{shorten(hook, width=145, placeholder='...')} "
        f"Check the current listing for details before buying. "
        f"{' '.join(sorted(hashtags))}"
    )
    if platform.lower() not in caption.lower():
        caption += f" #{platform.replace(' ', '')}"
    return caption[:2200]
