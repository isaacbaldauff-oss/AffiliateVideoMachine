"""Import product images from configured affiliate/product URLs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from app.project_generator import create_product_project, slugify


class AssetImportError(RuntimeError):
    """Raised when product assets cannot be imported."""


@dataclass(slots=True)
class AssetImportResult:
    """Summary of an attempted product asset import."""

    final_url: str
    title: str
    commercial_metadata: dict[str, Any]
    saved_images: list[Path]
    skipped_images: int
    metadata_path: Path
    source_assets_dir: Path


@dataclass(slots=True)
class ProductPageInspection:
    """Metadata and image candidates found on a product URL."""

    requested_url: str
    final_url: str
    title: str
    commercial_metadata: dict[str, Any]
    image_urls: list[str]
    candidate_count: int


def _require_dependencies() -> tuple[Any, Any]:
    """Import optional web parsing dependencies only when needed."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise AssetImportError(
            "Asset import requires requests and beautifulsoup4. Run: pip install -r requirements.txt"
        ) from exc
    return requests, BeautifulSoup


def _headers() -> dict[str, str]:
    """Return conservative browser-like request headers."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _clean_url(value: str, base_url: str) -> str:
    """Normalize common image URL forms from product pages."""
    url = value.strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    url = urljoin(base_url, url)
    return url


def _srcset_urls(value: str, base_url: str) -> list[str]:
    """Extract URLs from an HTML srcset value."""
    urls: list[str] = []
    for part in value.split(","):
        candidate = part.strip().split(" ")[0]
        cleaned = _clean_url(candidate, base_url)
        if cleaned:
            urls.append(cleaned)
    return urls


def _amazon_dynamic_urls(value: str, base_url: str) -> list[str]:
    """Extract Amazon-style image URLs from data-a-dynamic-image JSON."""
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, dict):
        return []
    return [_clean_url(str(url), base_url) for url in loaded.keys()]


def _candidate_urls_from_html(html: str, final_url: str, soup: Any) -> list[str]:
    """Collect likely product image URLs from metadata and image tags."""
    candidates: list[str] = []

    meta_selectors = [
        ("property", "og:image"),
        ("property", "og:image:secure_url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    ]
    for attr, value in meta_selectors:
        for tag in soup.find_all("meta", attrs={attr: value}):
            content = tag.get("content")
            if content:
                candidates.append(_clean_url(content, final_url))

    for tag in soup.find_all("link", attrs={"rel": re.compile("image_src", re.I)}):
        href = tag.get("href")
        if href:
            candidates.append(_clean_url(href, final_url))

    image_attrs = ["src", "data-src", "data-old-hires", "data-a-hires", "data-lazy-src"]
    for img in soup.find_all("img"):
        for attr in image_attrs:
            value = img.get(attr)
            if value:
                candidates.append(_clean_url(value, final_url))
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            candidates.extend(_srcset_urls(srcset, final_url))
        dynamic = img.get("data-a-dynamic-image")
        if dynamic:
            candidates.extend(_amazon_dynamic_urls(dynamic, final_url))

    # Some product pages hide image URLs inside scripts.
    for match in re.findall(r"https?:\\/\\/[^\"']+?\\.(?:jpg|jpeg|png|webp)", html, flags=re.I):
        candidates.append(match.replace("\\/", "/"))

    return _dedupe_urls(candidates)


def _meta_content(soup: Any, *names: str) -> str:
    """Return the first matching meta tag content value."""
    for name in names:
        for attrs in ({"property": name}, {"name": name}, {"itemprop": name}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
    return ""


def _text_for_selector(soup: Any, selectors: list[str]) -> str:
    """Return compact text from the first matching selector."""
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            text = " ".join(tag.get_text(" ", strip=True).split())
            if text:
                return text
    return ""


def _json_ld_objects(value: Any) -> list[dict[str, Any]]:
    """Flatten JSON-LD into candidate objects."""
    objects: list[dict[str, Any]] = []
    if isinstance(value, dict):
        objects.append(value)
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                objects.extend(_json_ld_objects(item))
    elif isinstance(value, list):
        for item in value:
            objects.extend(_json_ld_objects(item))
    return objects


def _json_ld_product_objects(soup: Any) -> list[dict[str, Any]]:
    """Extract JSON-LD product objects from a page."""
    products: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _json_ld_objects(loaded):
            item_type = item.get("@type")
            item_types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(value).lower() == "product" for value in item_types):
                products.append(item)
    return products


def _offer_value(product_object: dict[str, Any], key: str) -> str:
    """Extract a product offer value from JSON-LD."""
    offers = product_object.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict):
        value = offers.get(key)
        if value is not None:
            return str(value)
    return ""


def _rating_value(product_object: dict[str, Any], key: str) -> str:
    """Extract aggregate rating values from JSON-LD."""
    rating = product_object.get("aggregateRating")
    if isinstance(rating, dict):
        value = rating.get(key)
        if value is not None:
            return str(value)
    return ""


def _brand_name(product_object: dict[str, Any]) -> str:
    """Extract brand name from JSON-LD."""
    brand = product_object.get("brand")
    if isinstance(brand, dict):
        return str(brand.get("name") or "").strip()
    return str(brand or "").strip()


def extract_commercial_metadata(html: str, final_url: str, soup: Any) -> dict[str, Any]:
    """Extract commercial product metadata from generic page markup."""
    json_products = _json_ld_product_objects(soup)
    json_product = json_products[0] if json_products else {}

    title = (
        str(json_product.get("name") or "").strip()
        or _meta_content(soup, "og:title", "twitter:title")
        or _text_for_selector(soup, ["#productTitle", "[itemprop='name']", "h1"])
        or _page_title(soup)
    )
    description = (
        str(json_product.get("description") or "").strip()
        or _meta_content(soup, "og:description", "twitter:description", "description")
        or _text_for_selector(soup, ["#feature-bullets", "[itemprop='description']"])
    )
    price = (
        _offer_value(json_product, "price")
        or _meta_content(soup, "product:price:amount")
        or _text_for_selector(soup, [".a-price .a-offscreen", "[itemprop='price']", ".price"])
    )
    currency = (
        _offer_value(json_product, "priceCurrency")
        or _meta_content(soup, "product:price:currency")
    )
    commercial_metadata = {
        "requested_url": final_url,
        "canonical_url": _clean_url(str(soup.find("link", rel="canonical").get("href")), final_url)
        if soup.find("link", rel="canonical")
        else final_url,
        "title": title,
        "description": description,
        "brand": _brand_name(json_product),
        "price": price,
        "currency": currency,
        "availability": _offer_value(json_product, "availability"),
        "rating": _rating_value(json_product, "ratingValue"),
        "review_count": _rating_value(json_product, "reviewCount") or _rating_value(json_product, "ratingCount"),
        "sku": str(json_product.get("sku") or "").strip(),
        "gtin": str(
            json_product.get("gtin")
            or json_product.get("gtin8")
            or json_product.get("gtin12")
            or json_product.get("gtin13")
            or json_product.get("gtin14")
            or ""
        ).strip(),
        "json_ld_product_count": len(json_products),
    }
    return {key: value for key, value in commercial_metadata.items() if value not in ("", None)}


def _dedupe_urls(urls: Iterable[str]) -> list[str]:
    """Remove duplicate and obviously unusable URLs while preserving order."""
    seen: set[str] = set()
    unique: list[str] = []
    for raw_url in urls:
        url = raw_url.strip()
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if any(token in url.lower() for token in ["sprite", "logo", "favicon", "transparent-pixel"]):
            continue
        seen.add(url)
        unique.append(url)
    return unique


def _file_extension(url: str, content_type: str) -> str:
    """Choose a sensible image file extension."""
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "bmp" in content_type:
        return ".bmp"
    return ".jpg"


def _download_image(requests: Any, url: str, destination: Path, timeout: int) -> bool:
    """Download one image URL to a local destination."""
    response = requests.get(url, headers=_headers(), timeout=timeout, stream=True)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if "image" not in content_type:
        return False

    content = response.content
    if len(content) < 4096:
        return False

    destination.write_bytes(content)
    return True


def _page_title(soup: Any) -> str:
    """Extract a product page title."""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return str(og_title["content"]).strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def import_product_assets(
    product: dict[str, Any],
    projects_root: Path,
    max_images: int = 8,
    timeout: int = 20,
    inspection: ProductPageInspection | None = None,
) -> AssetImportResult:
    """Fetch product page imagery into the product project source assets folder."""
    product_url = str(product.get("product_url") or "").strip()
    if not product_url:
        raise AssetImportError("Product URL is empty.")

    requests, _ = _require_dependencies()
    project_dir = create_product_project(product, projects_root)
    source_assets_dir = project_dir / "source_assets"
    source_assets_dir.mkdir(parents=True, exist_ok=True)

    page = inspection or inspect_product_url(product_url, timeout=timeout)
    final_url = page.final_url
    title = page.title
    commercial_metadata = page.commercial_metadata
    candidates = page.image_urls

    saved_images: list[Path] = []
    skipped = 0
    product_slug = slugify(str(product.get("product_name") or title or "product"))
    for index, url in enumerate(candidates, start=1):
        if len(saved_images) >= max_images:
            break
        try:
            extension = _file_extension(url, "")
            image_path = source_assets_dir / f"{product_slug}-{len(saved_images) + 1:02d}{extension}"
            if _download_image(requests, url, image_path, timeout):
                saved_images.append(image_path)
            else:
                skipped += 1
        except Exception:
            skipped += 1

    metadata = {
        "product_id": product.get("id"),
        "product_name": product.get("product_name"),
        "requested_url": product_url,
        "final_url": final_url,
        "title": title,
        "commercial_metadata": commercial_metadata,
        "saved_images": [str(path) for path in saved_images],
        "skipped_images": skipped,
        "candidate_count": page.candidate_count,
    }
    metadata_path = source_assets_dir / "asset_import_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    if not saved_images:
        raise AssetImportError(
            "No usable product images were saved. The site may block automated fetches, "
            "or the page may not expose image URLs. Save product/lifestyle images manually "
            f"into: {source_assets_dir}"
        )

    return AssetImportResult(
        final_url=final_url,
        title=title,
        commercial_metadata=commercial_metadata,
        saved_images=saved_images,
        skipped_images=skipped,
        metadata_path=metadata_path,
        source_assets_dir=source_assets_dir,
    )


def inspect_product_url(product_url: str, timeout: int = 20) -> ProductPageInspection:
    """Dereference a product URL and extract metadata plus image candidates."""
    clean_url = product_url.strip()
    if not clean_url:
        raise AssetImportError("Product URL is empty.")

    requests, BeautifulSoup = _require_dependencies()
    response = requests.get(clean_url, headers=_headers(), timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    final_url = response.url
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    title = _page_title(soup)
    commercial_metadata = extract_commercial_metadata(html, final_url, soup)
    candidates = _candidate_urls_from_html(html, final_url, soup)

    return ProductPageInspection(
        requested_url=clean_url,
        final_url=final_url,
        title=title,
        commercial_metadata=commercial_metadata,
        image_urls=candidates,
        candidate_count=len(candidates),
    )
