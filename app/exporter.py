"""Create local export packages from queued scripts."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from app.project_generator import slugify


def _timestamp() -> str:
    """Return a filesystem-safe local timestamp."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_local_export_package(
    queue_item: Mapping[str, Any],
    product: Mapping[str, Any],
    script: Mapping[str, Any],
    exports_root: Path,
) -> Path:
    """Write a local export package with script, metadata, and checklist files."""
    product_slug = slugify(str(product.get("product_name") or "product"))
    angle_slug = slugify(str(script.get("angle") or "script"))
    queue_id = queue_item.get("id") or "new"
    export_dir = exports_root / f"{_timestamp()}-queue-{queue_id}-{product_slug}-{angle_slug}"
    export_dir.mkdir(parents=True, exist_ok=True)

    script_text = str(script.get("script_text") or "").strip()
    title = str(script.get("title") or "Untitled script").strip()
    (export_dir / "script.txt").write_text(f"{title}\n\n{script_text}\n", encoding="utf-8")

    metadata = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "export_type": queue_item.get("export_type"),
        "queue_status": queue_item.get("status"),
        "product": {
            "id": product.get("id"),
            "product_name": product.get("product_name"),
            "product_url": product.get("product_url"),
            "platform": product.get("platform"),
            "category": product.get("category"),
            "score": product.get("score"),
        },
        "script": {
            "id": script.get("id"),
            "angle": script.get("angle"),
            "title": script.get("title"),
            "compliance_status": script.get("compliance_status"),
        },
        "notes": queue_item.get("notes"),
    }
    (export_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    checklist = [
        "Local export package",
        "",
        "[ ] Import product images from the affiliate link or add images manually.",
        "[ ] Render a local draft video from the Export Queue.",
        "[ ] Replace draft slides with recorded or generated demo footage when ready.",
        "[ ] Edit the short-form video.",
        "[ ] Add captions.",
        "[ ] Re-check disclosure text before publishing.",
        "[ ] Save final video in this export folder or the product project exports folder.",
        "",
        "No upload or paid video tool integration is included in v1.",
    ]
    (export_dir / "production_checklist.txt").write_text("\n".join(checklist) + "\n", encoding="utf-8")
    return export_dir
