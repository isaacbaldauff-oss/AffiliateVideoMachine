"""Compliance dashboard page."""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd
import streamlit as st

from app.compliance import check_compliance
from app.database import Database


def _render_result(status: str, messages: list[str], risky_terms: list[str], has_disclosure: bool) -> None:
    """Show compliance result with status-specific styling."""
    if status == "pass":
        st.success("Pass")
    elif status == "fail":
        st.error("Fail")
    else:
        st.warning("Warning")

    st.write("Disclosure present:", "Yes" if has_disclosure else "No")
    st.write("Risky terms:", ", ".join(risky_terms) if risky_terms else "None")
    for message in messages:
        st.write(f"- {message}")


def _history_table(rows: list[dict[str, Any]]) -> None:
    """Render recent compliance checks."""
    if not rows:
        st.write("No compliance checks saved yet.")
        return

    display = []
    for row in rows:
        risky_terms = json.loads(row["risky_terms"] or "[]")
        display.append(
            {
                "Created": row["created_at"],
                "Status": row["status"],
                "Product": row.get("product_name") or "",
                "Angle": row.get("angle") or "",
                "Disclosure": "Yes" if row["has_disclosure"] else "No",
                "Risky terms": ", ".join(risky_terms),
            }
        )
    st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)


def render(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render compliance checking tools and history."""
    st.title("Compliance")
    st.caption("Check scripts or ad copy for risky claims and affiliate disclosure language.")

    source = st.radio("Content source", ["Custom text", "Product notes", "Existing script"], horizontal=True)
    content = ""
    product_id: int | None = None
    script_id: int | None = None
    content_type = "custom"

    if source == "Product notes":
        products = db.get_products()
        if products:
            labels = {f"{row['id']} - {row['product_name']}": row["id"] for row in products}
            selected = st.selectbox("Product", list(labels.keys()))
            product = db.get_product(labels[selected])
            if product:
                product_id = int(product["id"])
                content = str(product.get("notes") or "")
                content_type = "product_notes"
                st.text_area("Content", value=content, height=220, disabled=True)
        else:
            st.info("No products available.")
    elif source == "Existing script":
        scripts = db.list_scripts()
        if scripts:
            labels = {
                f"{row['product_name']} | {row['angle'].replace('_', ' ').title()} | #{row['id']}": row["id"]
                for row in scripts
            }
            selected = st.selectbox("Script", list(labels.keys()))
            script = db.get_script(labels[selected])
            if script:
                product_id = int(script["product_id"])
                script_id = int(script["id"])
                content = str(script.get("script_text") or "")
                content_type = "script"
                st.text_area("Content", value=content, height=220, disabled=True)
        else:
            st.info("No scripts available.")
    else:
        content = st.text_area("Content", height=220, placeholder="Paste caption, hook, script, or ad copy here.")

    if st.button("Run compliance check", disabled=not bool(content.strip())):
        try:
            result = check_compliance(content, config)
            db.add_compliance_check(content_type, content, result, product_id=product_id, script_id=script_id)
            _render_result(result.status, result.messages, result.risky_terms, result.has_disclosure)
            logger.info("Compliance check completed with status %s", result.status)
        except Exception:
            logger.exception("Compliance check failed")
            st.error("Compliance check failed. Check logs/errors.log for details.")

    st.subheader("Recent checks")
    _history_table(db.list_compliance_checks())
