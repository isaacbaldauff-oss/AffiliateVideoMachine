"""Normalize acquired product imagery for downstream media generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
from typing import Any

from app.project_generator import slugify
from app.video_renderer import find_source_images


class MediaNormalizationError(RuntimeError):
    """Raised when product media cannot be normalized."""


@dataclass(slots=True)
class NormalizedAsset:
    """A normalized product image and its quality metadata."""

    source_path: Path
    normalized_path: Path
    width: int
    height: int
    score: float


@dataclass(slots=True)
class NormalizationResult:
    """Result of normalizing source imagery."""

    normalized_assets_dir: Path
    assets: list[NormalizedAsset]
    manifest_path: Path


def _require_dependencies() -> tuple[Any, Any, Any, Any]:
    """Import optional image dependencies only when needed."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError as exc:
        raise MediaNormalizationError("Image normalization requires Pillow. Run: pip install -r requirements.txt") from exc
    return Image, ImageEnhance, ImageFilter, ImageOps


def _asset_score(width: int, height: int, file_size: int) -> float:
    """Score image usefulness for video reference generation."""
    megapixels = (width * height) / 1_000_000
    aspect = width / max(1, height)
    aspect_bonus = 1.0 if 0.45 <= aspect <= 1.8 else 0.72
    size_bonus = min(1.0, file_size / 80_000)
    return round((megapixels * 55 + aspect_bonus * 30 + size_bonus * 15), 2)


def _cover(image: Any, width: int, height: int) -> Any:
    """Resize/crop an image to cover a target canvas."""
    ratio = max(width / image.width, height / image.height)
    resized = image.resize((math.ceil(image.width * ratio), math.ceil(image.height * ratio)))
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _contain(image: Any, width: int, height: int) -> Any:
    """Resize an image so it is fully visible on a target canvas."""
    ratio = min(width / image.width, height / image.height)
    return image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))))


def normalize_product_images(
    source_assets_dir: Path,
    normalized_assets_dir: Path,
    product_name: str,
    max_images: int = 7,
    canvas_size: tuple[int, int] = (1080, 1920),
) -> NormalizationResult:
    """Create portrait-friendly normalized product references."""
    Image, ImageEnhance, ImageFilter, ImageOps = _require_dependencies()
    normalized_assets_dir.mkdir(parents=True, exist_ok=True)

    source_images = find_source_images(source_assets_dir)
    scored: list[tuple[float, Path, int, int]] = []
    for image_path in source_images:
        try:
            with Image.open(image_path) as image:
                image = ImageOps.exif_transpose(image)
                width, height = image.size
            if width < 240 or height < 240:
                continue
            scored.append((_asset_score(width, height, image_path.stat().st_size), image_path, width, height))
        except Exception:
            continue

    scored.sort(key=lambda item: item[0], reverse=True)
    assets: list[NormalizedAsset] = []
    canvas_width, canvas_height = canvas_size
    product_slug = slugify(product_name or "product")

    for index, (score, image_path, width, height) in enumerate(scored[:max_images], start=1):
        image = Image.open(image_path).convert("RGB")
        image = ImageOps.exif_transpose(image)

        background = _cover(image, canvas_width, canvas_height)
        background = background.filter(ImageFilter.GaussianBlur(radius=28))
        background = ImageEnhance.Brightness(background).enhance(0.55)

        foreground = _contain(image, int(canvas_width * 0.86), int(canvas_height * 0.76))
        paste_x = (canvas_width - foreground.width) // 2
        paste_y = (canvas_height - foreground.height) // 2
        background.paste(foreground, (paste_x, paste_y))

        normalized_path = normalized_assets_dir / f"{product_slug}-normalized-{index:02d}.jpg"
        background.save(normalized_path, "JPEG", quality=90, optimize=True)
        assets.append(
            NormalizedAsset(
                source_path=image_path,
                normalized_path=normalized_path,
                width=width,
                height=height,
                score=score,
            )
        )

    manifest = {
        "source_assets_dir": str(source_assets_dir),
        "normalized_assets_dir": str(normalized_assets_dir),
        "canvas_size": {"width": canvas_width, "height": canvas_height},
        "assets": [
            {
                "source_path": str(asset.source_path),
                "normalized_path": str(asset.normalized_path),
                "width": asset.width,
                "height": asset.height,
                "score": asset.score,
            }
            for asset in assets
        ],
    }
    manifest_path = normalized_assets_dir / "normalized_assets_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return NormalizationResult(normalized_assets_dir=normalized_assets_dir, assets=assets, manifest_path=manifest_path)
