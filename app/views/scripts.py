"""Scripts dashboard page."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import streamlit as st

from app.compliance import check_compliance
from app.config import resolve_project_path
from app.database import Database
from app.models import GeneratedScript
from app.project_generator import save_generated_scripts
from app.script_generator import DEFAULT_TEMPLATE_PATH, generate_scripts


def _script_label(row: dict[str, Any]) -> str:
    """Build a readable script option label."""
    angle = str(row["angle"]).replace("_", " ").title()
    return f"{row['product_name']} | {angle} | #{row['id']}"


def _show_script_editor(
    script: dict[str, Any],
    product: dict[str, Any],
    config: dict[str, Any],
    db: Database,
    logger: logging.Logger,
) -> None:
    """Display an editable existing script."""
    angle_label = str(script["angle"]).replace("_", " ").title()
    with st.expander(f"{angle_label} - {script['compliance_status']}", expanded=False):
        title = st.text_input("Title", value=script["title"], key=f"title_{script['id']}")
        script_text = st.text_area("Script", value=script["script_text"], height=260, key=f"script_{script['id']}")

        col1, col2 = st.columns(2)
        if col1.button("Save script", key=f"save_{script['id']}"):
            try:
                result = check_compliance(script_text, config)
                generated = GeneratedScript(angle=script["angle"], title=title.strip(), script_text=script_text.strip() + "\n")
                script_id = db.upsert_script(int(product["id"]), generated, result.status)
                db.add_compliance_check("script", script_text, result, product_id=int(product["id"]), script_id=script_id)
                projects_root = resolve_project_path(config.get("app", {}).get("projects_path", "data/projects"))
                save_generated_scripts(product, [generated], Path(projects_root))
                st.success("Script saved and compliance checked.")
                logger.info("Saved script %s", script_id)
                st.rerun()
            except Exception:
                logger.exception("Failed to save script")
                st.error("The script could not be saved. Check logs/errors.log for details.")

        if col2.button("Queue for export", key=f"queue_{script['id']}"):
            try:
                db.add_export_item(
                    product_id=int(product["id"]),
                    script_id=int(script["id"]),
                    export_type="Short-form video script",
                    status="Planned",
                    destination="Local exports",
                    notes="Queued from Scripts page.",
                )
                st.success("Added to export queue.")
                logger.info("Queued script %s for export", script["id"])
            except Exception:
                logger.exception("Failed to queue script")
                st.error("The script could not be queued. Check logs/errors.log for details.")


def render(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render script generation and editing workflows."""
    st.title("Scripts")
    st.caption("Generate local script angles and save them to each product project folder.")

    products = db.get_products()
    if not products:
        st.info("Add a product before generating scripts.")
        return

    labels = {f"{row['id']} - {row['product_name']}": row["id"] for row in products}
    selected_label = st.selectbox("Choose product", list(labels.keys()))
    product = db.get_product(labels[selected_label])
    if not product:
        st.error("Selected product could not be loaded.")
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("Product score", product["score"])
        st.write(f"Status: {product['status']}")
    with col2:
        st.write(product.get("notes") or "No notes yet.")

    if st.button("Generate 5 scripts"):
        try:
            generated_scripts = generate_scripts(product, DEFAULT_TEMPLATE_PATH)
            projects_root = resolve_project_path(config.get("app", {}).get("projects_path", "data/projects"))
            save_generated_scripts(product, generated_scripts, Path(projects_root))

            for generated in generated_scripts:
                result = check_compliance(generated.script_text, config)
                script_id = db.upsert_script(int(product["id"]), generated, result.status)
                db.add_compliance_check(
                    "script",
                    generated.script_text,
                    result,
                    product_id=int(product["id"]),
                    script_id=script_id,
                )
            db.update_product(int(product["id"]), {"status": "Scripted"})
            st.success("Generated, saved, and compliance checked 5 scripts.")
            logger.info("Generated scripts for product %s", product["id"])
            st.rerun()
        except Exception:
            logger.exception("Failed to generate scripts")
            st.error("Scripts could not be generated. Check logs/errors.log for details.")

    st.subheader("Existing scripts")
    scripts = db.list_scripts(product_id=int(product["id"]))
    if not scripts:
        st.write("No scripts generated for this product yet.")
        return

    for script in scripts:
        _show_script_editor(script, product, config, db, logger)
