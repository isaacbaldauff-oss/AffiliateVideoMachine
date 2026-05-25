"""Settings dashboard page."""

from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any

import streamlit as st

from app.config import CONFIG_PATH, resolve_project_path, save_config
from app.database import Database


def render(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render editable local app settings."""
    st.title("Settings")
    st.caption("Tune scoring weights and compliance terms without changing code.")

    app_config = config.get("app", {})
    st.subheader("Local paths")
    st.write("Database:", str(resolve_project_path(app_config.get("database_path", "data/affiliate_video_machine.db"))))
    st.write("Projects:", str(resolve_project_path(app_config.get("projects_path", "data/projects"))))
    st.write("Exports:", str(resolve_project_path(app_config.get("exports_path", "exports"))))
    st.write("App log:", str(resolve_project_path(app_config.get("log_file", "logs/app.log"))))
    st.write("Error log:", str(resolve_project_path(app_config.get("error_log_file", "logs/errors.log"))))
    st.write("Config:", str(CONFIG_PATH))

    st.subheader("Scoring")
    updated = deepcopy(config)
    scoring = updated.setdefault("scoring", {})
    weights = scoring.setdefault("weights", {})

    with st.form("settings_form"):
        col1, col2 = st.columns(2)
        with col1:
            scoring["max_expected_price"] = st.number_input(
                "Max expected price",
                min_value=1.0,
                value=float(scoring.get("max_expected_price", 200.0)),
                step=10.0,
            )
            scoring["max_expected_commission_rate"] = st.number_input(
                "Max expected commission rate",
                min_value=1.0,
                max_value=100.0,
                value=float(scoring.get("max_expected_commission_rate", 50.0)),
                step=1.0,
            )
            scoring["max_expected_reviews"] = st.number_input(
                "Max expected reviews",
                min_value=1,
                value=int(scoring.get("max_expected_reviews", 5000)),
                step=100,
            )
        with col2:
            for key in [
                "commission_rate",
                "price",
                "rating",
                "review_count",
                "visual_demo_score",
                "compliance_risk_score",
            ]:
                weights[key] = st.number_input(
                    key.replace("_", " ").title(),
                    min_value=0.0,
                    value=float(weights.get(key, 0.0)),
                    step=0.01,
                    format="%.2f",
                )

        st.subheader("Compliance terms")
        compliance = updated.setdefault("compliance", {})
        risky_terms = st.text_area(
            "Risky terms, one per line",
            value="\n".join(compliance.get("risky_terms", [])),
            height=140,
        ).splitlines()
        fail_terms = st.text_area(
            "Fail terms, one per line",
            value="\n".join(compliance.get("fail_terms", [])),
            height=120,
        ).splitlines()
        disclosure_terms = st.text_area(
            "Disclosure terms, one per line",
            value="\n".join(compliance.get("disclosure_terms", [])),
            height=120,
        ).splitlines()
        compliance["risky_terms"] = [term.strip() for term in risky_terms if term.strip()]
        compliance["fail_terms"] = [term.strip() for term in fail_terms if term.strip()]
        compliance["disclosure_terms"] = [term.strip() for term in disclosure_terms if term.strip()]

        st.subheader("Video rendering")
        rendering = updated.setdefault("video_rendering", {})
        col1, col2 = st.columns(2)
        with col1:
            rendering["width"] = st.number_input(
                "Default video width",
                min_value=360,
                max_value=2160,
                value=int(rendering.get("width", 720)),
                step=10,
            )
            rendering["height"] = st.number_input(
                "Default video height",
                min_value=640,
                max_value=3840,
                value=int(rendering.get("height", 1280)),
                step=10,
            )
            rendering["fps"] = st.number_input(
                "Default frames per second",
                min_value=10,
                max_value=30,
                value=int(rendering.get("fps", 15)),
                step=1,
            )
        with col2:
            rendering["seconds_per_scene"] = st.number_input(
                "Seconds per scene",
                min_value=1.0,
                max_value=10.0,
                value=float(rendering.get("seconds_per_scene", 2.8)),
                step=0.1,
            )
            rendering["max_scenes"] = st.number_input(
                "Max scenes",
                min_value=2,
                max_value=15,
                value=int(rendering.get("max_scenes", 8)),
                step=1,
            )

        st.subheader("AI presenter video")
        ai_video = updated.setdefault("ai_video", {})
        ai_video["provider"] = st.selectbox(
            "AI video provider",
            ["replicate"],
            index=0,
        )
        ai_video["replicate_api_token_env"] = st.text_input(
            "Replicate token environment variable",
            value=str(ai_video.get("replicate_api_token_env", "REPLICATE_API_TOKEN")),
        )
        ai_video["replicate_model_version"] = st.text_input(
            "Replicate model version",
            value=str(
                ai_video.get(
                    "replicate_model_version",
                    "xai/grok-imagine-r2v:b412665331cd7343f79fe14d93bb4f4e8b0d3865ae6308d27868af7dddf4420e",
                )
            ),
        )
        col1, col2 = st.columns(2)
        with col1:
            ai_video["duration"] = st.number_input(
                "Default AI clip seconds",
                min_value=1,
                max_value=10,
                value=int(ai_video.get("duration", 8)),
                step=1,
            )
            ai_video["max_reference_images"] = st.number_input(
                "Max reference images",
                min_value=1,
                max_value=7,
                value=int(ai_video.get("max_reference_images", 7)),
                step=1,
            )
        with col2:
            ai_video["aspect_ratio"] = st.selectbox(
                "Default AI aspect ratio",
                ["9:16", "16:9", "1:1", "3:4", "4:3", "2:3", "3:2"],
                index=["9:16", "16:9", "1:1", "3:4", "4:3", "2:3", "3:2"].index(
                    str(ai_video.get("aspect_ratio", "9:16"))
                )
                if str(ai_video.get("aspect_ratio", "9:16")) in ["9:16", "16:9", "1:1", "3:4", "4:3", "2:3", "3:2"]
                else 0,
            )
            ai_video["resolution"] = st.selectbox(
                "Default AI resolution",
                ["720p", "480p"],
                index=0 if str(ai_video.get("resolution", "720p")) == "720p" else 1,
            )

        st.subheader("TikTok API")
        tiktok_config = updated.setdefault("tiktok", {})
        tiktok_config["client_key_env"] = st.text_input(
            "TikTok client key environment variable",
            value=str(tiktok_config.get("client_key_env", "TIKTOK_CLIENT_KEY")),
        )
        tiktok_config["client_secret_env"] = st.text_input(
            "TikTok client secret environment variable",
            value=str(tiktok_config.get("client_secret_env", "TIKTOK_CLIENT_SECRET")),
        )
        tiktok_config["redirect_uri_env"] = st.text_input(
            "TikTok redirect URI environment variable",
            value=str(tiktok_config.get("redirect_uri_env", "TIKTOK_REDIRECT_URI")),
        )
        tiktok_config["redirect_uri"] = st.text_input(
            "Fallback TikTok OAuth redirect URI",
            value=str(tiktok_config.get("redirect_uri", "https://your-app.streamlit.app")),
        )
        scopes = tiktok_config.get("scopes", ["user.info.basic", "video.upload", "video.publish"])
        if not isinstance(scopes, list):
            scopes = ["user.info.basic", "video.upload", "video.publish"]
        scope_text = st.text_area(
            "TikTok OAuth scopes, one per line",
            value="\n".join(str(scope) for scope in scopes),
            height=100,
        )
        tiktok_config["scopes"] = [scope.strip() for scope in scope_text.splitlines() if scope.strip()]

        submitted = st.form_submit_button("Save settings")

    if submitted:
        try:
            save_config(updated)
            st.success("Settings saved. The app will reload them now.")
            logger.info("Saved settings")
            st.rerun()
        except Exception:
            logger.exception("Failed to save settings")
            st.error("Settings could not be saved. Check logs/errors.log for details.")
