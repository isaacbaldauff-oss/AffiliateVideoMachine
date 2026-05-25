"""Overview dashboard page."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import streamlit as st

from app.database import Database


def render(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render top-level pipeline metrics and recent work."""
    st.title("Overview")
    st.caption("Local pipeline health, product quality, and production readiness.")

    stats = db.dashboard_stats()
    compliance_counts = stats["compliance_counts"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Products", stats["products"])
    col2.metric("Average score", stats["average_score"])
    col3.metric("Scripts", stats["scripts"])
    col4.metric("Export queue", stats["queue"])

    st.divider()

    left, right = st.columns([2, 1])
    with left:
        st.subheader("Top products")
        products = db.get_products()
        if products:
            display = [
                {
                    "Product": row["product_name"],
                    "Platform": row["platform"],
                    "Category": row["category"],
                    "Score": row["score"],
                    "Status": row["status"],
                }
                for row in products[:10]
            ]
            st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
        else:
            st.info("Add your first product to begin scoring opportunities.")

    with right:
        st.subheader("Compliance")
        st.metric("Pass", compliance_counts.get("pass", 0))
        st.metric("Warning", compliance_counts.get("warning", 0))
        st.metric("Fail", compliance_counts.get("fail", 0))

    st.subheader("Recent scripts")
    scripts = db.list_scripts()
    if scripts:
        display = [
            {
                "Product": row["product_name"],
                "Angle": row["angle"].replace("_", " ").title(),
                "Compliance": row["compliance_status"],
                "Updated": row["updated_at"],
            }
            for row in scripts[:8]
        ]
        st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
    else:
        st.write("No scripts generated yet.")

    logger.info("Rendered overview page")
