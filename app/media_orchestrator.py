"""End-to-end affiliate media orchestration pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from textwrap import shorten
from typing import Any, Callable, Mapping

from app.ai_presenter import AiPresenterError, build_ai_presenter_prompt, generate_replicate_presenter_video
from app.asset_importer import AssetImportError, import_product_assets
from app.exporter import create_local_export_package
from app.media_normalizer import normalize_product_images
from app.project_generator import create_product_project
from app.video_renderer import RendererDependencyError, render_script_video


@dataclass(slots=True)
class OrchestrationResult:
    """Result of a zero-touch media orchestration run."""

    status: str
    export_dir: Path
    video_path: Path | None
    plan_path: Path
    manifest_path: Path
    messages: list[str]


def _progress(callback: Callable[[float, str], None] | None, value: float, message: str) -> None:
    """Safely report pipeline progress."""
    if callback:
        callback(value, message)


def _load_json(path: Path) -> dict[str, Any]:
    """Load JSON if present."""
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _commercial_claims(product: Mapping[str, Any], commercial_metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Merge database and dereferenced product metadata into commercial claims."""
    return {
        "product_name": product.get("product_name") or commercial_metadata.get("title"),
        "category": product.get("category"),
        "platform": product.get("platform"),
        "product_url": product.get("product_url"),
        "canonical_url": commercial_metadata.get("canonical_url"),
        "brand": commercial_metadata.get("brand"),
        "price": product.get("price") or commercial_metadata.get("price"),
        "currency": commercial_metadata.get("currency"),
        "rating": product.get("rating") or commercial_metadata.get("rating"),
        "review_count": product.get("review_count") or commercial_metadata.get("review_count"),
        "description": commercial_metadata.get("description"),
        "availability": commercial_metadata.get("availability"),
    }


def build_conversion_media_plan(
    product: Mapping[str, Any],
    script: Mapping[str, Any],
    commercial_metadata: Mapping[str, Any],
    normalized_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a conversion-oriented media plan for an affiliate clip."""
    claims = _commercial_claims(product, commercial_metadata)
    script_text = " ".join(str(script.get("script_text") or "").split())
    description = str(claims.get("description") or product.get("notes") or "")
    hook = shorten(description or script_text, width=180, placeholder="...")
    product_name = str(claims.get("product_name") or "the product")
    category = str(claims.get("category") or "this product category")

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "Create a realistic affiliate UGC short that shows a presenter holding the product.",
        "conversion_strategy": {
            "hook": hook,
            "visual_priority": [
                "Presenter holds the exact referenced product close to camera.",
                "Packaging or product silhouette remains recognizable.",
                "Usage gesture is shown without guaranteed-results claims.",
                "Affiliate disclosure is naturally included.",
            ],
            "cta": "Check the current listing and compare details before buying.",
        },
        "commercial_claims": claims,
        "creative_direction": {
            "setting": "bright bathroom, bedroom vanity, or clean grooming station",
            "presenter": "natural adult creator, casual UGC style, direct-to-camera",
            "product_action": f"hold and demonstrate {product_name} as a {category} item",
            "camera": "vertical phone video, light handheld movement, close product reveal",
        },
        "asset_strategy": {
            "normalized_asset_count": len(normalized_assets),
            "reference_images": normalized_assets,
        },
        "guardrails": [
            "Include affiliate disclosure.",
            "Avoid medical, guaranteed, official, cheapest, cure, weight loss, pain relief, and unrealistic transformation claims.",
            "Do not imply results that are not visible or supported by provided product metadata.",
        ],
    }


def build_orchestrated_ai_prompt(
    media_plan: Mapping[str, Any],
    product: Mapping[str, Any],
    script: Mapping[str, Any],
    target_seconds: int | None = None,
) -> str:
    """Build a provider prompt from the conversion media plan."""
    base_prompt = build_ai_presenter_prompt(product, script, target_seconds=target_seconds)
    claims = media_plan.get("commercial_claims", {})
    creative = media_plan.get("creative_direction", {})
    strategy = media_plan.get("conversion_strategy", {})
    prompt = f"""
{base_prompt}

Autonomous media plan:
Primary hook: {strategy.get("hook")}
Conversion CTA: {strategy.get("cta")}
Commercial metadata to respect: {json.dumps(claims, ensure_ascii=True)}
Scene setting: {creative.get("setting")}
Presenter style: {creative.get("presenter")}
Camera direction: {creative.get("camera")}

Important visual requirement:
Use the reference images to preserve the product appearance. The presenter must be visibly holding the product, not merely standing beside floating product art.
""".strip()
    return prompt[:4096]


def run_autonomous_media_pipeline(
    queue_item: Mapping[str, Any],
    product: Mapping[str, Any],
    script: Mapping[str, Any],
    projects_root: Path,
    exports_root: Path,
    config: Mapping[str, Any],
    api_token: str = "",
    require_ai_video: bool = False,
    progress_callback: Callable[[float, str], None] | None = None,
) -> OrchestrationResult:
    """Run URL dereference, media normalization, planning, and rendering with minimal intervention."""
    messages: list[str] = []
    export_dir = create_local_export_package(queue_item, product, script, exports_root)
    project_dir = create_product_project(product, projects_root)
    source_assets_dir = project_dir / "source_assets"
    normalized_assets_dir = project_dir / "normalized_assets"

    _progress(progress_callback, 0.05, "Dereferencing affiliate URL and acquiring product assets")
    commercial_metadata: dict[str, Any] = {}
    try:
        import_result = import_product_assets(product=dict(product), projects_root=projects_root, max_images=10)
        commercial_metadata = import_result.commercial_metadata
        messages.append(f"Imported {len(import_result.saved_images)} product image(s).")
    except AssetImportError as exc:
        messages.append(f"Asset import warning: {exc}")
        metadata_path = source_assets_dir / "asset_import_metadata.json"
        imported_metadata = _load_json(metadata_path)
        commercial_metadata = imported_metadata.get("commercial_metadata", {})
    except Exception as exc:
        messages.append(f"Asset import failed unexpectedly: {exc}")

    _progress(progress_callback, 0.25, "Normalizing and ranking product imagery")
    normalization = normalize_product_images(
        source_assets_dir=source_assets_dir,
        normalized_assets_dir=normalized_assets_dir,
        product_name=str(product.get("product_name") or "product"),
        max_images=7,
    )
    normalized_assets = [
        {
            "path": str(asset.normalized_path),
            "source_path": str(asset.source_path),
            "score": asset.score,
            "width": asset.width,
            "height": asset.height,
        }
        for asset in normalization.assets
    ]
    messages.append(f"Normalized {len(normalized_assets)} image reference(s).")

    ai_config = config.get("ai_video", {})
    if not isinstance(ai_config, dict):
        ai_config = {}
    ai_duration = max(1, min(10, int(ai_config.get("duration", 5))))
    render_config = config.get("video_rendering", {})
    if not isinstance(render_config, dict):
        render_config = {}

    _progress(progress_callback, 0.38, "Generating conversion media plan")
    media_plan = build_conversion_media_plan(product, script, commercial_metadata, normalized_assets)
    plan_path = export_dir / "conversion_media_plan.json"
    plan_path.write_text(json.dumps(media_plan, indent=2), encoding="utf-8")
    ai_prompt = build_orchestrated_ai_prompt(media_plan, product, script, target_seconds=ai_duration)
    prompt_path = export_dir / "orchestrated_ai_presenter_prompt.txt"
    prompt_path.write_text(ai_prompt, encoding="utf-8")

    video_path: Path | None = None
    status = "local_rendered"
    if require_ai_video and not api_token:
        status = "blocked"
        messages.append("AI video is required, but no Replicate API token was provided.")
    elif require_ai_video and not normalized_assets:
        status = "blocked"
        messages.append("AI video is required, but no usable product reference images were available.")

    if api_token and normalized_assets:
        try:
            _progress(progress_callback, 0.48, "Generating AI presenter video")
            ai_result = generate_replicate_presenter_video(
                product=product,
                script=script,
                source_assets_dir=normalized_assets_dir,
                export_dir=export_dir,
                api_token=api_token,
                config=ai_config,
                prompt=ai_prompt,
                progress_callback=lambda value, message: _progress(progress_callback, 0.48 + value * 0.47, message),
            )
            video_path = ai_result.video_path
            status = "ai_rendered"
            messages.append("AI presenter video generated.")
        except AiPresenterError as exc:
            if require_ai_video:
                status = "blocked"
                messages.append(f"AI generation failed: {exc}")
            else:
                messages.append(f"AI generation warning: {exc}")

    if video_path is None and status != "blocked":
        _progress(progress_callback, 0.58, "Rendering deterministic local fallback video")
        try:
            fallback = render_script_video(
                queue_item=queue_item,
                product=product,
                script=script,
                export_dir=export_dir,
                source_assets_dir=normalized_assets_dir if normalized_assets else source_assets_dir,
                render_config=render_config,
                progress_callback=lambda value, message: _progress(progress_callback, 0.58 + value * 0.37, message),
            )
            video_path = fallback.video_path
            status = "fallback_rendered"
            messages.append("Local fallback video rendered.")
        except RendererDependencyError as exc:
            status = "blocked"
            messages.append(str(exc))

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "queue_item_id": queue_item.get("id"),
        "product_id": product.get("id"),
        "script_id": script.get("id"),
        "export_dir": str(export_dir),
        "video_path": str(video_path) if video_path else "",
        "source_assets_dir": str(source_assets_dir),
        "normalized_assets_dir": str(normalized_assets_dir),
        "plan_path": str(plan_path),
        "prompt_path": str(prompt_path),
        "messages": messages,
    }
    manifest_path = export_dir / "orchestration_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _progress(progress_callback, 1.0, "Autonomous media pipeline complete")

    return OrchestrationResult(
        status=status,
        export_dir=export_dir,
        video_path=video_path,
        plan_path=plan_path,
        manifest_path=manifest_path,
        messages=messages,
    )
