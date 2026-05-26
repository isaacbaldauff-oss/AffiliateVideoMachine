"""TikTok Shop product-link helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


PRODUCT_BOX_STATUS_OPTIONS = [
    "Needs product box",
    "Draft uploaded",
    "Product box attached",
    "Posted",
    "Not TikTok Shop",
]


def is_tiktok_shop_url(product_url: str) -> bool:
    """Return whether a URL looks like a TikTok or TikTok Shop product link."""
    parsed = urlparse(product_url.strip())
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(token in host for token in ["shop.tiktok.com", "tiktokshop", "tiktok.com", "vt.tiktok.com"]):
        return any(token in path or token in parsed.query.lower() for token in ["product", "shop", "goods", "item"])
    return False


def extract_tiktok_shop_product_id(product_url: str) -> str:
    """Extract a likely TikTok Shop product ID from URL query or path values."""
    parsed = urlparse(product_url.strip())
    query = parse_qs(parsed.query)
    for key in ["product_id", "productid", "goods_id", "item_id", "itemid", "sku_id", "ttspid"]:
        values = query.get(key)
        if values and values[0].strip():
            return values[0].strip()

    path = parsed.path.strip("/")
    product_match = re.search(r"(?:product|goods|item)[/-](\d{6,})", path, flags=re.I)
    if product_match:
        return product_match.group(1)

    numeric_segments = re.findall(r"\d{8,}", path)
    if numeric_segments:
        return numeric_segments[-1]
    return ""


def product_box_status_for_platform(platform: str) -> str:
    """Return the default product-box status for a platform."""
    return "Needs product box" if platform == "TikTok Shop" else "Not TikTok Shop"


def tiktok_shop_box_notes(product_id: str, product_url: str) -> str:
    """Build default product-box workflow notes."""
    parts = [
        "TikTok Shop workflow: upload the generated MP4 as an inbox draft, then open the TikTok app and attach the product through Add Link -> Products before posting.",
    ]
    if product_id:
        parts.append(f"Detected TikTok Shop product ID: {product_id}.")
    if product_url:
        parts.append(f"Product URL: {product_url}")
    return "\n".join(parts)
