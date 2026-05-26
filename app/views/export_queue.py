"""Export queue dashboard page."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app.ai_presenter import AiPresenterError, build_ai_presenter_prompt, generate_replicate_presenter_video
from app.asset_importer import AssetImportError, import_product_assets
from app.config import resolve_project_path
from app.database import Database
from app.exporter import create_local_export_package
from app.media_orchestrator import run_autonomous_media_pipeline
from app.project_generator import create_product_project
from app.video_renderer import RendererDependencyError, render_script_video


def _queue_table(rows: list[dict[str, Any]]) -> None:
    """Display export queue in a table."""
    if not rows:
        st.info("No export queue items yet.")
        return

    display = [
        {
            "ID": row["id"],
            "Product": row.get("product_name") or "",
            "Angle": (row.get("angle") or "").replace("_", " ").title(),
            "Type": row["export_type"],
            "Status": row["status"],
            "Destination": row.get("destination") or "",
            "Updated": row["updated_at"],
        }
        for row in rows
    ]
    st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)


def _ai_default_duration(ai_config: dict[str, Any]) -> int:
    """Return the configured AI clip duration bounded to the provider range."""
    return max(1, min(10, int(ai_config.get("duration", 5))))


def _estimated_ai_cost(ai_config: dict[str, Any], duration: int) -> float:
    """Estimate provider cost from configured per-second pricing."""
    per_second = float(ai_config.get("estimated_cost_per_output_second", 0.05))
    return max(0.0, per_second) * max(0, duration)


def _already_has_ai_video(item: dict[str, Any]) -> bool:
    """Return whether this queue item appears to have a rendered AI MP4 already."""
    destination = Path(str(item.get("destination") or ""))
    return item.get("status") == "AI Rendered" and destination.suffix.lower() == ".mp4"


def render(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render export queue add and update workflows."""
    st.title("Export Queue")
    st.caption("Package approved scripts and render local MP4 drafts. Nothing is uploaded or published.")

    exports_root = resolve_project_path(config.get("app", {}).get("exports_path", "exports"))
    st.info(f"Local export packages are saved under: {exports_root}")

    scripts = db.list_scripts()
    with st.form("add_export_item_form"):
        if scripts:
            labels = {
                f"{row['product_name']} | {row['angle'].replace('_', ' ').title()} | #{row['id']}": row
                for row in scripts
            }
            selected_label = st.selectbox("Script", list(labels.keys()))
            export_type = st.text_input("Export type", value="Short-form video script")
            destination = st.text_input("Destination", value=str(exports_root))
            notes = st.text_area("Notes", value="Ready for editing.")
            submitted = st.form_submit_button("Add to queue")
        else:
            st.info("Generate scripts before adding queue items.")
            submitted = False

    if submitted and scripts:
        selected_script = labels[selected_label]
        try:
            db.add_export_item(
                product_id=int(selected_script["product_id"]),
                script_id=int(selected_script["id"]),
                export_type=export_type.strip() or "Short-form video script",
                status="Planned",
                destination=destination.strip(),
                notes=notes.strip(),
            )
            st.success("Added to export queue.")
            logger.info("Added export queue item for script %s", selected_script["id"])
            st.rerun()
        except Exception:
            logger.exception("Failed to add export queue item")
            st.error("Queue item could not be added. Check logs/errors.log for details.")

    st.subheader("Queue")
    rows = db.list_export_queue()
    _queue_table(rows)

    if not rows:
        return

    st.subheader("Update item")
    item_labels = {f"#{row['id']} - {row.get('product_name') or 'Untitled'}": row for row in rows}
    selected_item_label = st.selectbox("Queue item", list(item_labels.keys()))
    item = item_labels[selected_item_label]
    status_options = config.get("defaults", {}).get("export_status_options", ["Planned", "Ready", "Exported", "Blocked"])
    status_index = status_options.index(item["status"]) if item["status"] in status_options else 0

    with st.form("update_export_item_form"):
        status = st.selectbox("Status", status_options, index=status_index)
        destination = st.text_input("Destination", value=item.get("destination") or "")
        notes = st.text_area("Notes", value=item.get("notes") or "")
        submitted = st.form_submit_button("Update queue item")

    if submitted:
        try:
            db.update_export_item(int(item["id"]), status, destination.strip(), notes.strip())
            st.success("Queue item updated.")
            logger.info("Updated export queue item %s", item["id"])
            st.rerun()
        except Exception:
            logger.exception("Failed to update export queue item")
            st.error("Queue item could not be updated. Check logs/errors.log for details.")

    selected_product = db.get_product(int(item["product_id"])) if item.get("product_id") else None
    selected_script = db.get_script(int(item["script_id"])) if item.get("script_id") else None
    projects_root = resolve_project_path(config.get("app", {}).get("projects_path", "data/projects"))

    ai_config = config.get("ai_video", {})
    if not isinstance(ai_config, dict):
        ai_config = {}

    token_env = str(ai_config.get("replicate_api_token_env", "REPLICATE_API_TOKEN"))
    env_token = os.getenv(token_env, "")
    default_ai_duration = _ai_default_duration(ai_config)
    default_ai_cost = _estimated_ai_cost(ai_config, default_ai_duration)
    require_paid_confirmation = bool(ai_config.get("require_paid_generation_confirmation", True))
    already_has_ai_video = _already_has_ai_video(item)

    st.subheader("Zero-touch orchestration")
    st.write(
        "Run the whole pipeline: dereference the affiliate URL, acquire product assets, normalize imagery, "
        "build a conversion media plan, and generate an actual AI video when provider access is available."
    )
    require_ai_video = st.checkbox(
        "Require actual AI-generated video; do not fall back to image-composited local render",
        value=True,
    )
    orchestration_token = st.text_input(
        "Replicate API token for zero-touch AI video",
        value="",
        type="password",
        help=f"Uses `{token_env}` when set. If AI-only is checked, a token is required.",
    )
    raw_orchestration_api_token = orchestration_token.strip() or env_token
    st.caption(
        f"Paid AI cost guard: this action can start at most one Replicate video job. "
        f"Estimated cost at the current {default_ai_duration}-second default is about ${default_ai_cost:.2f}."
    )
    if already_has_ai_video:
        st.warning("This queue item already has an AI-rendered MP4. Regenerating may create another paid provider job.")
    allow_orchestration_regeneration = False
    if already_has_ai_video:
        allow_orchestration_regeneration = st.checkbox(
            "Allow a second paid AI generation for this queue item",
            value=False,
            key=f"allow_orchestration_regen_{item['id']}",
        )
    orchestration_paid_confirmed = st.checkbox(
        "I approve starting one paid Replicate AI video generation for this queue item",
        value=False,
        key=f"approve_orchestration_paid_ai_{item['id']}",
        disabled=not require_paid_confirmation,
    )
    if not require_paid_confirmation:
        orchestration_paid_confirmed = True
    orchestration_api_token = raw_orchestration_api_token if orchestration_paid_confirmed else ""
    orchestration_disabled = bool(raw_orchestration_api_token) and (
        not orchestration_paid_confirmed or (already_has_ai_video and not allow_orchestration_regeneration)
    )
    if st.button("Run autonomous media pipeline", disabled=orchestration_disabled):
        try:
            if not selected_product or not selected_script:
                st.error("This queue item is missing its linked product or script.")
                return
            if raw_orchestration_api_token and require_paid_confirmation and not orchestration_paid_confirmed:
                st.error("Confirm the paid AI generation checkbox before starting a Replicate video job.")
                return
            if raw_orchestration_api_token and already_has_ai_video and not allow_orchestration_regeneration:
                st.error("This item already has an AI video. Check the regeneration box before creating another paid job.")
                return
            if require_ai_video and not raw_orchestration_api_token:
                st.error(f"AI-only mode needs a Replicate API token. Set {token_env} or paste one above.")
                return
            if require_ai_video and not orchestration_api_token:
                st.error("AI-only mode needs your paid generation confirmation before it can start.")
                return

            start_status = "AI Rendering" if orchestration_api_token else "Rendering"
            db.update_export_item(int(item["id"]), start_status, str(exports_root), notes.strip())
            progress = st.progress(0.0, text="Starting autonomous media pipeline")

            def update_orchestration_progress(value: float, message: str) -> None:
                progress.progress(min(1.0, max(0.0, value)), text=message)

            result = run_autonomous_media_pipeline(
                queue_item=item,
                product=selected_product,
                script=selected_script,
                projects_root=Path(projects_root),
                exports_root=Path(exports_root),
                config=config,
                api_token=orchestration_api_token,
                require_ai_video=require_ai_video,
                progress_callback=update_orchestration_progress,
            )
            queue_status = "AI Rendered" if result.status == "ai_rendered" else "Rendered"
            if result.status == "blocked":
                queue_status = "Blocked"
            destination = str(result.video_path or result.export_dir)
            db.update_export_item(int(item["id"]), queue_status, destination, "\n".join(result.messages))
            st.success(f"Pipeline completed: {queue_status}")
            for message in result.messages:
                st.write(f"- {message}")
            st.write(f"Media plan: {result.plan_path}")
            st.write(f"Manifest: {result.manifest_path}")
            if result.video_path:
                st.video(str(result.video_path))
            logger.info("Autonomous media pipeline completed for queue item %s with %s", item["id"], result.status)
        except Exception:
            logger.exception("Autonomous media pipeline failed")
            db.update_export_item(int(item["id"]), "Blocked", str(exports_root), "Autonomous media pipeline failed.")
            st.error("Autonomous media pipeline failed. Check logs/errors.log for details.")

    st.subheader("Product assets")
    if selected_product:
        product_project_dir = create_product_project(selected_product, Path(projects_root))
        source_assets_dir = product_project_dir / "source_assets"
        st.write(f"Source asset folder: `{source_assets_dir}`")
        st.caption("The renderer will use images in this folder as the main product visuals.")
        max_images = st.slider("Images to import", min_value=1, max_value=12, value=8, step=1)
        if st.button("Import product images from affiliate link"):
            try:
                result = import_product_assets(selected_product, Path(projects_root), max_images=max_images)
                st.success(f"Imported {len(result.saved_images)} image(s) into {result.source_assets_dir}")
                logger.info(
                    "Imported %s product asset(s) for product %s from %s",
                    len(result.saved_images),
                    selected_product.get("id"),
                    result.final_url,
                )
            except AssetImportError as exc:
                logger.exception("Product asset import failed")
                st.warning(str(exc))
            except Exception:
                logger.exception("Unexpected product asset import failure")
                st.error("Product image import failed. Check logs/errors.log for details.")
    else:
        st.info("This queue item is missing its linked product.")

    st.subheader("AI presenter video")
    st.write(
        "Generate a fresh AI video of a presenter holding and talking about the product, using product images as references."
    )
    token_help = f"Uses the `{token_env}` environment variable when set. You can paste a token here for this run only."
    pasted_token = st.text_input("Replicate API token", value="", type="password", help=token_help)
    api_token = pasted_token.strip() or env_token

    ai_col1, ai_col2, ai_col3 = st.columns(3)
    ai_duration = ai_col1.slider(
        "AI clip seconds",
        min_value=1,
        max_value=10,
        value=default_ai_duration,
        step=1,
    )
    ai_resolution = ai_col2.selectbox(
        "AI resolution",
        ["720p", "480p"],
        index=0 if str(ai_config.get("resolution", "720p")) == "720p" else 1,
    )
    ai_aspect_ratio = ai_col3.selectbox(
        "AI aspect ratio",
        ["9:16", "16:9", "1:1", "3:4", "4:3", "2:3", "3:2"],
        index=0,
    )

    ai_prompt = ""
    if selected_product and selected_script:
        ai_prompt = build_ai_presenter_prompt(selected_product, selected_script)
        ai_prompt = st.text_area("AI presenter prompt", value=ai_prompt, height=260)
    else:
        st.info("This queue item needs a linked product and script before AI video generation.")

    manual_ai_cost = _estimated_ai_cost(ai_config, ai_duration)
    st.caption(f"Estimated Replicate cost for this manual AI job: about ${manual_ai_cost:.2f}.")
    allow_manual_regeneration = False
    if already_has_ai_video:
        allow_manual_regeneration = st.checkbox(
            "Allow manual AI regeneration for this item",
            value=False,
            key=f"allow_manual_regen_{item['id']}",
        )
    manual_paid_confirmed = st.checkbox(
        "I approve starting one paid Replicate AI presenter video job",
        value=False,
        key=f"approve_manual_paid_ai_{item['id']}",
        disabled=not require_paid_confirmation,
    )
    if not require_paid_confirmation:
        manual_paid_confirmed = True
    manual_disabled = require_paid_confirmation and (
        not manual_paid_confirmed or (already_has_ai_video and not allow_manual_regeneration)
    )

    if st.button("Generate AI presenter video", disabled=manual_disabled):
        try:
            if not selected_product or not selected_script:
                st.error("This queue item is missing its linked product or script.")
                return
            if require_paid_confirmation and not manual_paid_confirmed:
                st.error("Confirm the paid AI generation checkbox before starting a Replicate video job.")
                return
            if already_has_ai_video and not allow_manual_regeneration:
                st.error("This item already has an AI video. Check the regeneration box before creating another paid job.")
                return
            if not api_token:
                st.error(f"Add a Replicate API token or set the {token_env} environment variable.")
                return

            product_project_dir = create_product_project(selected_product, Path(projects_root))
            source_assets_dir = product_project_dir / "source_assets"
            export_dir = create_local_export_package(item, selected_product, selected_script, Path(exports_root))

            run_config = dict(ai_config)
            run_config["duration"] = ai_duration
            run_config["resolution"] = ai_resolution
            run_config["aspect_ratio"] = ai_aspect_ratio

            db.update_export_item(int(item["id"]), "AI Rendering", str(export_dir), notes.strip())
            progress = st.progress(0.0, text="Starting AI presenter generation")

            def update_ai_progress(value: float, message: str) -> None:
                progress.progress(min(1.0, max(0.0, value)), text=message)

            result = generate_replicate_presenter_video(
                product=selected_product,
                script=selected_script,
                source_assets_dir=source_assets_dir,
                export_dir=export_dir,
                api_token=api_token,
                config=run_config,
                prompt=ai_prompt,
                progress_callback=update_ai_progress,
            )
            db.update_export_item(int(item["id"]), "AI Rendered", str(result.video_path), notes.strip())
            st.success(f"AI presenter video created: {result.video_path}")
            if result.provider_url:
                st.write(f"Provider job: {result.provider_url}")
            st.video(str(result.video_path))
            logger.info("Generated AI presenter video for queue item %s at %s", item["id"], result.video_path)
        except AiPresenterError as exc:
            logger.exception("AI presenter generation failed")
            db.update_export_item(int(item["id"]), "Blocked", str(exports_root), str(exc))
            st.error(str(exc))
        except Exception:
            logger.exception("Unexpected AI presenter generation failure")
            db.update_export_item(int(item["id"]), "Blocked", str(exports_root), "AI presenter generation failed.")
            st.error("AI presenter generation failed. Check logs/errors.log for details.")

    st.subheader("Create local package")
    st.write("This creates a folder with `script.txt`, `metadata.json`, and `production_checklist.txt`.")
    if st.button("Create export package"):
        try:
            product = selected_product
            script = selected_script
            if not product or not script:
                st.error("This queue item is missing its linked product or script.")
                return

            export_dir = create_local_export_package(item, product, script, Path(exports_root))
            db.update_export_item(int(item["id"]), "Exported", str(export_dir), notes.strip())
            st.success(f"Export package created: {export_dir}")
            logger.info("Created local export package for queue item %s at %s", item["id"], export_dir)
            st.rerun()
        except Exception:
            logger.exception("Failed to create local export package")
            st.error("Export package could not be created. Check logs/errors.log for details.")

    st.subheader("Render local fallback video")
    st.write(
        "This creates an image-composited MP4 from product assets and captions. "
        "Use AI presenter video for a generated person holding the product."
    )

    base_render_config = config.get("video_rendering", {})
    if not isinstance(base_render_config, dict):
        base_render_config = {}

    render_mode = st.selectbox("Render size", ["Draft 720 x 1280", "Full 1080 x 1920"])
    render_config = dict(base_render_config)
    if render_mode.startswith("Full"):
        render_config["width"] = 1080
        render_config["height"] = 1920
    else:
        render_config["width"] = 720
        render_config["height"] = 1280

    col1, col2, col3 = st.columns(3)
    render_config["seconds_per_scene"] = col1.slider(
        "Seconds per scene",
        min_value=1.5,
        max_value=5.0,
        value=float(render_config.get("seconds_per_scene", 2.8)),
        step=0.1,
    )
    render_config["max_scenes"] = col2.slider(
        "Max scenes",
        min_value=3,
        max_value=10,
        value=int(render_config.get("max_scenes", 8)),
        step=1,
    )
    render_config["fps"] = col3.slider(
        "Frames per second",
        min_value=10,
        max_value=24,
        value=int(render_config.get("fps", 15)),
        step=1,
    )

    render_time = float(render_config["seconds_per_scene"]) * int(render_config["max_scenes"])
    st.caption(f"Estimated video length: up to {render_time:.1f} seconds. Draft renders usually take under a minute.")

    preview_product = selected_product
    if preview_product:
        preview_project_dir = create_product_project(preview_product, Path(projects_root))
        st.caption(f"Optional product visuals: place images in {preview_project_dir / 'source_assets'}")

    if st.button("Render MP4 locally"):
        try:
            product = selected_product
            script = selected_script
            if not product or not script:
                st.error("This queue item is missing its linked product or script.")
                return

            db.update_export_item(int(item["id"]), "Rendering", str(exports_root), notes.strip())
            export_dir = create_local_export_package(item, product, script, Path(exports_root))

            product_project_dir = create_product_project(product, Path(projects_root))
            source_assets_dir = product_project_dir / "source_assets"

            progress = st.progress(0.0, text="Starting render")

            def update_progress(value: float, message: str) -> None:
                progress.progress(min(1.0, max(0.0, value)), text=message)

            result = render_script_video(
                queue_item=item,
                product=product,
                script=script,
                export_dir=export_dir,
                source_assets_dir=source_assets_dir,
                render_config=render_config,
                progress_callback=update_progress,
            )
            db.update_export_item(int(item["id"]), "Rendered", str(result.video_path), notes.strip())
            st.success(f"Rendered video: {result.video_path}")
            st.video(str(result.video_path))
            logger.info("Rendered local MP4 for queue item %s at %s", item["id"], result.video_path)
        except RendererDependencyError as exc:
            logger.exception("Rendering dependencies are missing")
            db.update_export_item(int(item["id"]), "Blocked", str(exports_root), str(exc))
            st.error(str(exc))
        except Exception:
            logger.exception("Failed to render local video")
            db.update_export_item(int(item["id"]), "Blocked", str(exports_root), "Render failed. Check logs/errors.log.")
            st.error("Video render failed. Check logs/errors.log for details.")
