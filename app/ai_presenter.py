"""AI presenter video generation provider integrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import base64
import json
from pathlib import Path
import time
from textwrap import shorten
from typing import Any, Callable, Mapping

from app.video_renderer import find_source_images


class AiPresenterError(RuntimeError):
    """Raised when AI presenter generation cannot complete."""


@dataclass(slots=True)
class AiPresenterResult:
    """Generated AI presenter video output paths."""

    video_path: Path
    manifest_path: Path
    prompt_path: Path
    provider_url: str


TERMINAL_SUCCEEDED = {"succeeded", "successful"}
TERMINAL_FAILED = {"failed", "canceled", "cancelled"}


def _require_dependencies() -> tuple[Any, Any]:
    """Import optional dependencies used by AI video generation."""
    try:
        import requests
        from PIL import Image
    except ImportError as exc:
        raise AiPresenterError(
            "AI presenter generation requires requests and Pillow. Run: pip install -r requirements.txt"
        ) from exc
    return requests, Image


def _clean_text(value: Any) -> str:
    """Normalize text for prompts."""
    return " ".join(str(value or "").split())


def _script_summary(script_text: str, max_chars: int = 650) -> str:
    """Extract compact talking points from a generated script."""
    lines = []
    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line or line.endswith(":"):
            continue
        if line.lower().startswith("disclosure"):
            continue
        lines.append(line)
    return shorten(" ".join(lines), width=max_chars, placeholder="...")


def build_ai_presenter_prompt(product: Mapping[str, Any], script: Mapping[str, Any]) -> str:
    """Build a prompt for a reference-to-video product presenter clip."""
    product_name = _clean_text(product.get("product_name")) or "the product"
    category = _clean_text(product.get("category")) or "this category"
    platform = _clean_text(product.get("platform")) or "affiliate platform"
    angle = _clean_text(script.get("angle")).replace("_", " ") or "quick product demo"
    talking_points = _script_summary(str(script.get("script_text") or ""))

    prompt = f"""
Create a realistic vertical UGC-style affiliate product video.

Scene:
A natural-looking adult presenter is standing in a bright bathroom or bedroom vanity setup, holding the exact product shown in the reference images. The presenter talks directly to camera while showing the product in hand, turning it slightly so the packaging and shape are visible. The tone is casual, honest, and useful, like a creator explaining a product they are about to try.

Product:
{product_name}
Category: {category}
Platform context: {platform}
Video angle: {angle}

Action:
The presenter holds the product near chest level, points to it briefly, then demonstrates the basic usage gesture in a realistic way. For hair or grooming products, show the presenter applying or miming application naturally without exaggerated transformation claims. Keep the product recognizable from the reference images.

What the presenter is saying:
{talking_points}

Style:
Realistic handheld phone video, natural lighting, subtle camera movement, authentic creator energy, no studio commercial gloss, no floating text-heavy slides. Keep the person and product in frame. Make the product the clear focus.

Compliance:
Include affiliate-disclosure-safe phrasing in the spoken tone such as "I may earn a commission." Avoid claims like cure, guaranteed, weight loss, medical, pain relief, before and after, cheapest, official, or FDA approved. Do not imply guaranteed results.
""".strip()
    return prompt[:4096]


def _mime_type(path: Path) -> str:
    """Return a MIME type for a local image path."""
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    return "image/jpeg"


def _prepare_image_data_uri(image_path: Path, output_dir: Path, image_module: Any, max_edge: int = 1600) -> str:
    """Resize a local reference image and return a base64 data URI."""
    output_dir.mkdir(parents=True, exist_ok=True)
    image = image_module.open(image_path).convert("RGB")
    longest_edge = max(image.width, image.height)
    if longest_edge > max_edge:
        scale = max_edge / longest_edge
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))

    prepared_path = output_dir / f"{image_path.stem}.jpg"
    image.save(prepared_path, "JPEG", quality=88, optimize=True)
    encoded = base64.b64encode(prepared_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _prediction_error(prediction: Mapping[str, Any]) -> str:
    """Extract an API error message from a prediction response."""
    error = prediction.get("error")
    if error:
        return str(error)
    return json.dumps(prediction, indent=2)[:1000]


def _output_url(output: Any) -> str:
    """Find the first usable video URL in a prediction output."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                url = item.get("url") or item.get("uri")
                if url:
                    return str(url)
    if isinstance(output, dict):
        url = output.get("url") or output.get("uri") or output.get("video")
        if url:
            return str(url)
    raise AiPresenterError("AI provider finished but did not return a downloadable video URL.")


def _download_video(requests: Any, video_url: str, destination: Path) -> None:
    """Download generated video output to disk."""
    response = requests.get(video_url, timeout=120)
    response.raise_for_status()
    destination.write_bytes(response.content)


def generate_replicate_presenter_video(
    product: Mapping[str, Any],
    script: Mapping[str, Any],
    source_assets_dir: Path,
    export_dir: Path,
    api_token: str,
    config: Mapping[str, Any],
    prompt: str | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> AiPresenterResult:
    """Generate a presenter video with Replicate reference-to-video."""
    if not api_token:
        raise AiPresenterError("Replicate API token is missing.")

    requests, Image = _require_dependencies()
    reference_images = find_source_images(source_assets_dir)
    max_references = int(config.get("max_reference_images", 7))
    reference_images = reference_images[: max(1, min(7, max_references))]
    if not reference_images:
        raise AiPresenterError(
            f"No product reference images found. Import images or add them to: {source_assets_dir}"
        )

    export_dir.mkdir(parents=True, exist_ok=True)
    prompt_text = prompt or build_ai_presenter_prompt(product, script)
    prompt_path = export_dir / "ai_presenter_prompt.txt"
    prompt_path.write_text(prompt_text, encoding="utf-8")

    prepared_dir = export_dir / "prepared_references"
    reference_payload = [
        _prepare_image_data_uri(path, prepared_dir, Image)
        for path in reference_images
    ]

    model_version = str(
        config.get(
            "replicate_model_version",
            "xai/grok-imagine-r2v:b412665331cd7343f79fe14d93bb4f4e8b0d3865ae6308d27868af7dddf4420e",
        )
    )
    duration = int(config.get("duration", 8))
    resolution = str(config.get("resolution", "720p"))
    aspect_ratio = str(config.get("aspect_ratio", "9:16"))
    timeout_seconds = int(config.get("timeout_seconds", 900))
    poll_seconds = max(2, int(config.get("poll_seconds", 5)))

    payload = {
        "version": model_version,
        "input": {
            "prompt": prompt_text,
            "reference_images": reference_payload,
            "duration": max(1, min(10, duration)),
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        },
    }
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Prefer": "wait=5",
    }

    if progress_callback:
        progress_callback(0.05, "Sending reference images to AI video provider")

    response = requests.post(
        "https://api.replicate.com/v1/predictions",
        headers=headers,
        json=payload,
        timeout=120,
    )
    if response.status_code >= 400 and ":" in model_version:
        retry_payload = dict(payload)
        retry_payload["version"] = model_version.rsplit(":", 1)[1]
        response = requests.post(
            "https://api.replicate.com/v1/predictions",
            headers=headers,
            json=retry_payload,
            timeout=120,
        )
    if response.status_code >= 400:
        raise AiPresenterError(f"AI provider rejected the request: {response.text[:1000]}")

    prediction = response.json()
    prediction_url = prediction.get("urls", {}).get("get")
    started_at = time.monotonic()
    while str(prediction.get("status", "")).lower() not in TERMINAL_SUCCEEDED | TERMINAL_FAILED:
        if time.monotonic() - started_at > timeout_seconds:
            raise AiPresenterError("AI provider timed out before returning a video.")
        if not prediction_url:
            raise AiPresenterError("AI provider did not return a prediction polling URL.")
        if progress_callback:
            elapsed = time.monotonic() - started_at
            progress_callback(min(0.9, 0.1 + elapsed / max(1, timeout_seconds) * 0.8), "Waiting for AI video")
        time.sleep(poll_seconds)
        poll = requests.get(prediction_url, headers={"Authorization": f"Bearer {api_token}"}, timeout=60)
        poll.raise_for_status()
        prediction = poll.json()

    status = str(prediction.get("status", "")).lower()
    if status in TERMINAL_FAILED:
        raise AiPresenterError("AI provider failed: " + _prediction_error(prediction))

    video_url = _output_url(prediction.get("output"))
    video_path = export_dir / "ai_presenter_video.mp4"
    if progress_callback:
        progress_callback(0.94, "Downloading generated presenter video")
    _download_video(requests, video_url, video_path)

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "provider": "replicate",
        "model_version": model_version,
        "prediction_id": prediction.get("id"),
        "prediction_web_url": prediction.get("urls", {}).get("web"),
        "output_url": video_url,
        "video_path": str(video_path),
        "prompt_path": str(prompt_path),
        "reference_images": [str(path) for path in reference_images],
        "settings": {
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        },
    }
    manifest_path = export_dir / "ai_presenter_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if progress_callback:
        progress_callback(1.0, "AI presenter video complete")

    return AiPresenterResult(
        video_path=video_path,
        manifest_path=manifest_path,
        prompt_path=prompt_path,
        provider_url=str(prediction.get("urls", {}).get("web") or ""),
    )
