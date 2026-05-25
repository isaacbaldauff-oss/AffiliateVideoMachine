"""Configuration loading and path helpers for AffiliateVideoMachine."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "app": {
        "name": "AffiliateVideoMachine",
        "database_path": "data/affiliate_video_machine.db",
        "projects_path": "data/projects",
        "exports_path": "exports",
        "log_file": "logs/app.log",
        "error_log_file": "logs/errors.log",
    },
    "defaults": {
        "status_options": ["Researching", "Approved", "Scripted", "Needs Review", "Archived"],
        "export_status_options": [
            "Planned",
            "Ready",
            "Rendering",
            "Rendered",
            "AI Rendering",
            "AI Rendered",
            "Exported",
            "Blocked",
        ],
        "platforms": ["TikTok Shop", "Amazon", "Impact", "ShareASale", "Direct", "Other"],
    },
    "scoring": {
        "max_expected_price": 200.0,
        "max_expected_commission_rate": 50.0,
        "max_expected_reviews": 5000,
        "weights": {
            "commission_rate": 0.25,
            "price": 0.15,
            "rating": 0.20,
            "review_count": 0.15,
            "visual_demo_score": 0.15,
            "compliance_risk_score": 0.10,
        },
    },
    "compliance": {
        "risky_terms": [
            "cure",
            "guaranteed",
            "weight loss",
            "medical",
            "pain relief",
            "before and after",
            "free",
            "cheapest",
            "official",
            "FDA approved",
        ],
        "fail_terms": [
            "cure",
            "weight loss",
            "medical",
            "pain relief",
            "before and after",
            "FDA approved",
        ],
        "disclosure_terms": ["affiliate", "commission", "sponsored", "paid link", "#ad", "ad:"],
    },
    "video_rendering": {
        "width": 720,
        "height": 1280,
        "fps": 15,
        "seconds_per_scene": 2.8,
        "max_scenes": 8,
        "colors": {
            "background": "#111827",
            "overlay": "#0f172a",
            "text": "#f8fafc",
            "muted": "#cbd5e1",
            "accent": "#2dd4bf",
            "warm": "#f59e0b",
        },
    },
    "ai_video": {
        "provider": "replicate",
        "replicate_api_token_env": "REPLICATE_API_TOKEN",
        "replicate_model_version": "xai/grok-imagine-r2v:b412665331cd7343f79fe14d93bb4f4e8b0d3865ae6308d27868af7dddf4420e",
        "duration": 8,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "max_reference_images": 7,
        "poll_seconds": 5,
        "timeout_seconds": 900,
    },
    "tiktok": {
        "client_key_env": "TIKTOK_CLIENT_KEY",
        "client_secret_env": "TIKTOK_CLIENT_SECRET",
        "redirect_uri_env": "TIKTOK_REDIRECT_URI",
        "redirect_uri": "https://your-app.streamlit.app",
        "scopes": ["user.info.basic", "video.upload", "video.publish"],
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a recursive merge of two dictionaries."""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load YAML config and fill missing keys from defaults."""
    if not config_path.exists():
        return deepcopy(DEFAULT_CONFIG)

    with config_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a mapping: {config_path}")

    return deep_merge(DEFAULT_CONFIG, loaded)


def save_config(config: dict[str, Any], config_path: Path = CONFIG_PATH) -> None:
    """Persist app configuration to YAML."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(config, file, sort_keys=False)


def resolve_project_path(path_value: str | Path) -> Path:
    """Resolve a config path relative to the project root."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
