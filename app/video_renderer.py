"""Local short-form video rendering utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import re
from textwrap import shorten
from typing import Any, Callable, Iterable, Mapping

from app.project_generator import slugify


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class RendererDependencyError(RuntimeError):
    """Raised when optional rendering dependencies are missing."""


@dataclass(slots=True)
class RenderResult:
    """Paths and timing details for a rendered video."""

    video_path: Path
    manifest_path: Path
    duration_seconds: float
    scene_count: int


@dataclass(slots=True)
class VideoScene:
    """One timed visual scene in the rendered video."""

    heading: str
    body: str


def _require_render_dependencies() -> tuple[Any, Any, Any]:
    """Import optional video rendering dependencies only when rendering."""
    try:
        import imageio.v2 as imageio
        import numpy as np
        from PIL import Image, ImageDraw, ImageEnhance, ImageFont
    except ImportError as exc:
        raise RendererDependencyError(
            "Video rendering requires Pillow, imageio, imageio-ffmpeg, and numpy. "
            "Run: pip install -r requirements.txt"
        ) from exc

    pillow = {
        "Image": Image,
        "ImageDraw": ImageDraw,
        "ImageEnhance": ImageEnhance,
        "ImageFont": ImageFont,
    }
    return imageio, np, pillow


def _as_int(value: Any, default: int) -> int:
    """Convert unknown config input into an integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    """Convert unknown config input into a float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any) -> str:
    """Normalize text for use on video frames."""
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _split_script_sections(script_text: str) -> list[VideoScene]:
    """Split a generated script into labeled sections."""
    sections: list[VideoScene] = []
    current_heading = ""
    current_lines: list[str] = []

    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        is_heading = line.endswith(":") and len(line) <= 42
        if is_heading:
            if current_heading and current_lines:
                sections.append(VideoScene(current_heading, _clean_text(" ".join(current_lines))))
            current_heading = line[:-1].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading and current_lines:
        sections.append(VideoScene(current_heading, _clean_text(" ".join(current_lines))))

    filtered = [scene for scene in sections if scene.heading.lower() != "disclosure"]
    if filtered:
        return filtered

    sentences = re.split(r"(?<=[.!?])\s+", _clean_text(script_text))
    chunks = [sentence for sentence in sentences if sentence]
    return [VideoScene(f"Beat {index + 1}", chunk) for index, chunk in enumerate(chunks[:6])]


def _build_scenes(product: Mapping[str, Any], script: Mapping[str, Any], max_scenes: int) -> list[VideoScene]:
    """Build title and script scenes for the renderer."""
    product_name = _clean_text(product.get("product_name")) or "Product"
    angle = _clean_text(script.get("angle")).replace("_", " ").title() or "Short-Form Video"
    script_text = str(script.get("script_text") or "")
    scenes = [
        VideoScene(angle, f"{product_name} | {shorten(_clean_text(product.get('category')), width=42, placeholder='...')}")
    ]
    scenes.extend(_split_script_sections(script_text))
    return scenes[: max(2, max_scenes)]


def find_source_images(source_assets_dir: Path) -> list[Path]:
    """Find usable local product images for video backgrounds."""
    if not source_assets_dir.exists():
        return []
    return [
        path
        for path in sorted(source_assets_dir.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]


def _hex_to_rgb(value: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    """Convert a hex color string to RGB."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return default
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return default


def _font(size: int, bold: bool, image_font: Any) -> Any:
    """Load a readable Windows font, falling back to Pillow defaults."""
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return image_font.truetype(str(path), size=size)
    return image_font.load_default()


def _text_size(draw: Any, text: str, font: Any) -> tuple[int, int]:
    """Return text width and height for a drawing context."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _wrap_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    """Wrap text to fit within a pixel width."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        width, _ = _text_size(draw, candidate, font)
        if width <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _cover_image(image: Any, width: int, height: int, zoom: float) -> Any:
    """Resize and crop an image to cover the video canvas."""
    ratio = max(width / image.width, height / image.height) * zoom
    resized = image.resize((math.ceil(image.width * ratio), math.ceil(image.height * ratio)))
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _draw_generated_background(draw: Any, width: int, height: int, colors: Mapping[str, str], progress: float) -> None:
    """Draw a simple animated background when no source image exists."""
    background = _hex_to_rgb(str(colors.get("background", "#111827")), (17, 24, 39))
    accent = _hex_to_rgb(str(colors.get("accent", "#2dd4bf")), (45, 212, 191))
    warm = _hex_to_rgb(str(colors.get("warm", "#f59e0b")), (245, 158, 11))

    draw.rectangle((0, 0, width, height), fill=background)
    offset = int(progress * 90)
    draw.rectangle((-80 + offset, 120, width // 2 + offset, 250), fill=accent)
    draw.rectangle((width // 2 - offset, height - 310, width + 80 - offset, height - 170), fill=warm)
    draw.rectangle((0, 0, width, height), outline=(255, 255, 255), width=2)


def _load_background(scene_index: int, source_images: list[Path], width: int, height: int, progress: float, pillow: Any) -> Any | None:
    """Load a source asset as the scene background."""
    if not source_images:
        return None

    image = pillow["Image"].open(source_images[scene_index % len(source_images)]).convert("RGB")
    image = _cover_image(image, width, height, 1.03 + progress * 0.025)
    image = pillow["ImageEnhance"].Brightness(image).enhance(0.58)
    return image


def _contain_image(image: Any, box_width: int, box_height: int, zoom: float) -> Any:
    """Resize an image so the whole product remains visible inside a box."""
    ratio = min(box_width / image.width, box_height / image.height) * zoom
    new_width = max(1, math.floor(image.width * ratio))
    new_height = max(1, math.floor(image.height * ratio))
    return image.resize((new_width, new_height))


def _draw_asset_forward_scene(
    canvas: Any,
    draw: Any,
    scene: VideoScene,
    product: Mapping[str, Any],
    source_image_path: Path,
    width: int,
    height: int,
    colors: Mapping[str, str],
    image_font: Any,
    image_module: Any,
) -> None:
    """Draw a product-image-led scene with short caption text."""
    margin = int(width * 0.07)
    text_color = _hex_to_rgb(str(colors.get("text", "#f8fafc")), (248, 250, 252))
    muted = _hex_to_rgb(str(colors.get("muted", "#cbd5e1")), (203, 213, 225))
    accent = _hex_to_rgb(str(colors.get("accent", "#2dd4bf")), (45, 212, 191))
    overlay = _hex_to_rgb(str(colors.get("overlay", "#0f172a")), (15, 23, 42))

    eyebrow_font = _font(max(18, width // 34), bold=True, image_font=image_font)
    heading_font = _font(max(32, width // 15), bold=True, image_font=image_font)
    body_font = _font(max(23, width // 26), bold=False, image_font=image_font)
    footer_font = _font(max(16, width // 40), bold=False, image_font=image_font)

    product_name = _clean_text(product.get("product_name")) or "Product"
    platform = _clean_text(product.get("platform")) or "Local"
    category = _clean_text(product.get("category")) or "Affiliate pick"

    draw.rectangle((0, 0, width, height), fill=(0, 0, 0, 105))
    draw.text((margin, int(height * 0.045)), product_name[:60], font=eyebrow_font, fill=text_color)
    draw.text((margin, int(height * 0.078)), f"{platform} | {category}"[:70], font=footer_font, fill=muted)

    visual_top = int(height * 0.13)
    visual_bottom = int(height * 0.58)
    visual_left = margin
    visual_right = width - margin
    draw.rounded_rectangle(
        (visual_left, visual_top, visual_right, visual_bottom),
        radius=26,
        fill=(255, 255, 255, 235),
        outline=(255, 255, 255, 255),
        width=2,
    )

    product_image = image_module.open(source_image_path).convert("RGBA")
    contained = _contain_image(
        product_image,
        visual_right - visual_left - 48,
        visual_bottom - visual_top - 48,
        1.0,
    )
    paste_x = visual_left + ((visual_right - visual_left) - contained.width) // 2
    paste_y = visual_top + ((visual_bottom - visual_top) - contained.height) // 2
    canvas.paste(contained, (paste_x, paste_y), contained)

    panel_top = int(height * 0.62)
    panel_bottom = int(height * 0.89)
    draw.rounded_rectangle(
        (margin, panel_top, width - margin, panel_bottom),
        radius=22,
        fill=overlay,
    )

    content_width = width - margin * 2 - 42
    y = panel_top + 28
    for line in _wrap_text(draw, scene.heading.upper(), heading_font, content_width)[:2]:
        draw.text((margin + 22, y), line, font=heading_font, fill=accent)
        _, line_height = _text_size(draw, line, heading_font)
        y += line_height + 10

    y += 10
    body = shorten(scene.body, width=145, placeholder="...")
    for line in _wrap_text(draw, body, body_font, content_width)[:4]:
        draw.text((margin + 22, y), line, font=body_font, fill=text_color)
        _, line_height = _text_size(draw, line, body_font)
        y += line_height + 12

    disclosure = "Affiliate disclosure: I may earn a commission at no extra cost to you."
    draw.text((margin, height - int(height * 0.075)), disclosure, font=footer_font, fill=muted)


def _draw_text_block(
    draw: Any,
    scene: VideoScene,
    product: Mapping[str, Any],
    width: int,
    height: int,
    colors: Mapping[str, str],
    image_font: Any,
) -> None:
    """Draw product context, scene heading, caption text, and footer."""
    margin = int(width * 0.075)
    content_width = width - margin * 2
    text_color = _hex_to_rgb(str(colors.get("text", "#f8fafc")), (248, 250, 252))
    muted = _hex_to_rgb(str(colors.get("muted", "#cbd5e1")), (203, 213, 225))
    accent = _hex_to_rgb(str(colors.get("accent", "#2dd4bf")), (45, 212, 191))
    overlay = _hex_to_rgb(str(colors.get("overlay", "#0f172a")), (15, 23, 42))

    eyebrow_font = _font(max(18, width // 34), bold=True, image_font=image_font)
    heading_font = _font(max(34, width // 13), bold=True, image_font=image_font)
    body_font = _font(max(24, width // 23), bold=False, image_font=image_font)
    footer_font = _font(max(16, width // 38), bold=False, image_font=image_font)

    card_top = int(height * 0.24)
    card_bottom = int(height * 0.74)
    draw.rounded_rectangle(
        (margin - 18, card_top - 28, width - margin + 18, card_bottom + 28),
        radius=22,
        fill=overlay,
    )

    product_name = _clean_text(product.get("product_name")) or "Product"
    platform = _clean_text(product.get("platform")) or "Local"
    category = _clean_text(product.get("category")) or "Affiliate pick"
    draw.text((margin, int(height * 0.08)), product_name[:62], font=eyebrow_font, fill=text_color)
    draw.text((margin, int(height * 0.115)), f"{platform} | {category}"[:70], font=footer_font, fill=muted)

    y = card_top
    for line in _wrap_text(draw, scene.heading.upper(), heading_font, content_width):
        draw.text((margin, y), line, font=heading_font, fill=accent)
        _, line_height = _text_size(draw, line, heading_font)
        y += line_height + 12

    y += 18
    body_lines = _wrap_text(draw, scene.body, body_font, content_width)
    max_body_lines = 9
    if len(body_lines) > max_body_lines:
        body_lines = body_lines[: max_body_lines - 1] + [shorten(body_lines[max_body_lines - 1], width=46)]
    for line in body_lines:
        draw.text((margin, y), line, font=body_font, fill=text_color)
        _, line_height = _text_size(draw, line, body_font)
        y += line_height + 13

    disclosure = "Affiliate disclosure: I may earn a commission at no extra cost to you."
    draw.text((margin, height - int(height * 0.11)), disclosure, font=footer_font, fill=muted)
    url = _clean_text(product.get("product_url"))
    if url:
        draw.text((margin, height - int(height * 0.075)), shorten(url, width=62), font=footer_font, fill=muted)


def _draw_progress(draw: Any, width: int, height: int, progress: float, colors: Mapping[str, str]) -> None:
    """Draw a subtle render-time progress bar on the video frame."""
    accent = _hex_to_rgb(str(colors.get("accent", "#2dd4bf")), (45, 212, 191))
    base = _hex_to_rgb(str(colors.get("muted", "#334155")), (51, 65, 85))
    left = int(width * 0.075)
    right = width - left
    y = height - int(height * 0.035)
    draw.rounded_rectangle((left, y, right, y + 8), radius=4, fill=base)
    draw.rounded_rectangle((left, y, left + int((right - left) * progress), y + 8), radius=4, fill=accent)


def render_script_video(
    queue_item: Mapping[str, Any],
    product: Mapping[str, Any],
    script: Mapping[str, Any],
    export_dir: Path,
    source_assets_dir: Path,
    render_config: Mapping[str, Any],
    progress_callback: Callable[[float, str], None] | None = None,
) -> RenderResult:
    """Render a vertical MP4 draft video for one queued script."""
    imageio, np, pillow = _require_render_dependencies()

    width = _as_int(render_config.get("width"), 720)
    height = _as_int(render_config.get("height"), 1280)
    fps = max(1, _as_int(render_config.get("fps"), 15))
    seconds_per_scene = max(1.0, _as_float(render_config.get("seconds_per_scene"), 2.8))
    max_scenes = max(2, _as_int(render_config.get("max_scenes"), 8))
    colors = render_config.get("colors", {})
    if not isinstance(colors, dict):
        colors = {}

    export_dir.mkdir(parents=True, exist_ok=True)
    source_images = find_source_images(source_assets_dir)
    scenes = _build_scenes(product, script, max_scenes)
    frames_per_scene = max(1, int(round(seconds_per_scene * fps)))
    total_frames = frames_per_scene * len(scenes)

    product_slug = slugify(str(product.get("product_name") or "product"))
    angle_slug = slugify(str(script.get("angle") or "script"))
    video_path = export_dir / f"{product_slug}-{angle_slug}.mp4"
    manifest_path = export_dir / "render_manifest.json"

    writer = imageio.get_writer(
        video_path,
        fps=fps,
        codec="libx264",
        quality=8,
        macro_block_size=16,
        ffmpeg_log_level="error",
    )
    try:
        frame_number = 0
        for scene_index, scene in enumerate(scenes):
            source_image_path = source_images[scene_index % len(source_images)] if source_images else None
            for local_frame in range(frames_per_scene):
                local_progress = local_frame / max(1, frames_per_scene - 1)
                overall_progress = frame_number / max(1, total_frames - 1)
                image = _load_background(scene_index, source_images, width, height, local_progress, pillow)
                if image is None:
                    image = pillow["Image"].new("RGB", (width, height))
                    draw = pillow["ImageDraw"].Draw(image)
                    _draw_generated_background(draw, width, height, colors, local_progress)
                draw = pillow["ImageDraw"].Draw(image, "RGBA")
                if source_image_path:
                    _draw_asset_forward_scene(
                        image,
                        draw,
                        scene,
                        product,
                        source_image_path,
                        width,
                        height,
                        colors,
                        pillow["ImageFont"],
                        pillow["Image"],
                    )
                else:
                    draw.rectangle((0, 0, width, height), fill=(0, 0, 0, 60))
                    _draw_text_block(draw, scene, product, width, height, colors, pillow["ImageFont"])
                _draw_progress(draw, width, height, overall_progress, colors)
                writer.append_data(np.asarray(image))

                frame_number += 1
                if progress_callback and frame_number % max(1, fps) == 0:
                    progress_callback(frame_number / total_frames, f"Rendering scene {scene_index + 1}/{len(scenes)}")
    finally:
        writer.close()

    manifest = {
        "video_path": str(video_path),
        "duration_seconds": round(len(scenes) * seconds_per_scene, 2),
        "scene_count": len(scenes),
        "source_images": [str(path) for path in source_images],
        "settings": {
            "width": width,
            "height": height,
            "fps": fps,
            "seconds_per_scene": seconds_per_scene,
            "max_scenes": max_scenes,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback(1.0, "Render complete")

    return RenderResult(
        video_path=video_path,
        manifest_path=manifest_path,
        duration_seconds=len(scenes) * seconds_per_scene,
        scene_count=len(scenes),
    )
