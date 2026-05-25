"""Create local production folders and save generated scripts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from app.models import GeneratedScript


PROJECT_SUBFOLDERS = [
    "source_assets",
    "scripts",
    "ai_video",
    "edited_video",
    "captions",
    "exports",
]


def slugify(value: str, fallback: str = "product") -> str:
    """Create a filesystem-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def product_folder_name(product: Mapping[str, Any]) -> str:
    """Build a stable project folder name for a product."""
    product_id = product.get("id") or "new"
    product_name = slugify(str(product.get("product_name") or "product"))
    return f"{product_id}-{product_name}"


def create_product_project(product: Mapping[str, Any], projects_root: Path) -> Path:
    """Create a product project folder and expected subfolders."""
    project_dir = projects_root / product_folder_name(product)
    for subfolder in PROJECT_SUBFOLDERS:
        (project_dir / subfolder).mkdir(parents=True, exist_ok=True)
    return project_dir


def save_generated_scripts(
    product: Mapping[str, Any],
    scripts: list[GeneratedScript],
    projects_root: Path,
) -> list[Path]:
    """Save generated scripts as text files in the product project folder."""
    project_dir = create_product_project(product, projects_root)
    scripts_dir = project_dir / "scripts"
    saved_paths: list[Path] = []

    for script in scripts:
        script_path = scripts_dir / f"{slugify(script.angle)}.txt"
        script_path.write_text(
            f"{script.title}\n\n{script.script_text}",
            encoding="utf-8",
        )
        saved_paths.append(script_path)

    return saved_paths
