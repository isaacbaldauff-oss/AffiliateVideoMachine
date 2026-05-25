"""Products dashboard page."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app.config import resolve_project_path
from app.database import Database
from app.project_generator import create_product_project
from app.scoring import calculate_product_score


def _number(value: Any, default: float = 0.0) -> float:
    """Convert database values into Streamlit number input defaults."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    """Convert database values into integer defaults."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _status_index(options: list[str], value: str | None) -> int:
    """Return a safe selectbox index."""
    if value in options:
        return options.index(value)
    return 0


def _product_form(prefix: str, config: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render shared product fields and return typed form data."""
    existing = existing or {}
    defaults = config.get("defaults", {})
    status_options = defaults.get("status_options", ["Researching", "Approved", "Scripted", "Needs Review", "Archived"])
    platforms = defaults.get("platforms", ["TikTok Shop", "Amazon", "Impact", "ShareASale", "Direct", "Other"])

    product_name = st.text_input("Product name", value=str(existing.get("product_name") or ""), key=f"{prefix}_name")
    product_url = st.text_input("Product URL", value=str(existing.get("product_url") or ""), key=f"{prefix}_url")

    col1, col2 = st.columns(2)
    with col1:
        platform = st.selectbox(
            "Platform",
            platforms,
            index=_status_index(platforms, existing.get("platform")),
            key=f"{prefix}_platform",
        )
        category = st.text_input("Category", value=str(existing.get("category") or ""), key=f"{prefix}_category")
        price = st.number_input("Price", min_value=0.0, value=_number(existing.get("price")), step=1.0, key=f"{prefix}_price")
        commission_rate = st.number_input(
            "Commission rate (%)",
            min_value=0.0,
            max_value=100.0,
            value=_number(existing.get("commission_rate")),
            step=0.5,
            key=f"{prefix}_commission",
        )
    with col2:
        rating = st.number_input(
            "Rating",
            min_value=0.0,
            max_value=5.0,
            value=_number(existing.get("rating")),
            step=0.1,
            key=f"{prefix}_rating",
        )
        review_count = st.number_input(
            "Review count",
            min_value=0,
            value=_integer(existing.get("review_count")),
            step=10,
            key=f"{prefix}_reviews",
        )
        visual_demo_score = st.slider(
            "Visual demo score",
            min_value=0,
            max_value=100,
            value=_integer(existing.get("visual_demo_score"), 50),
            key=f"{prefix}_visual",
        )
        compliance_risk_score = st.slider(
            "Compliance risk score",
            min_value=0,
            max_value=100,
            value=_integer(existing.get("compliance_risk_score"), 0),
            key=f"{prefix}_risk",
        )

    status = st.selectbox(
        "Status",
        status_options,
        index=_status_index(status_options, existing.get("status")),
        key=f"{prefix}_status",
    )
    notes = st.text_area("Notes", value=str(existing.get("notes") or ""), height=120, key=f"{prefix}_notes")

    data = {
        "product_name": product_name.strip(),
        "product_url": product_url.strip(),
        "platform": platform,
        "category": category.strip(),
        "price": price,
        "commission_rate": commission_rate,
        "rating": rating,
        "review_count": int(review_count),
        "visual_demo_score": float(visual_demo_score),
        "compliance_risk_score": float(compliance_risk_score),
        "notes": notes.strip(),
        "status": status,
    }
    data["score"] = calculate_product_score(data, config)
    return data


def _show_product_table(products: list[dict[str, Any]]) -> None:
    """Display products as a compact table."""
    if not products:
        st.info("No products match the current filters.")
        return

    display = [
        {
            "ID": row["id"],
            "Product": row["product_name"],
            "Platform": row["platform"],
            "Category": row["category"],
            "Price": row["price"],
            "Commission %": row["commission_rate"],
            "Rating": row["rating"],
            "Reviews": row["review_count"],
            "Score": row["score"],
            "Status": row["status"],
        }
        for row in products
    ]
    st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)


def render(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render product add, edit, and list workflows."""
    st.title("Products")
    st.caption("Track affiliate products and score their short-form video potential.")

    projects_root = resolve_project_path(config.get("app", {}).get("projects_path", "data/projects"))
    add_tab, edit_tab, table_tab = st.tabs(["Add product", "Edit product", "Product list"])

    with add_tab:
        with st.form("add_product_form"):
            data = _product_form("add", config)
            submitted = st.form_submit_button("Add product")

        if submitted:
            if not data["product_name"]:
                st.error("Product name is required.")
            else:
                try:
                    product_id = db.create_product(data)
                    product = db.get_product(product_id)
                    if product:
                        create_product_project(product, Path(projects_root))
                    st.success(f"Product added with score {data['score']}.")
                    logger.info("Created product %s", product_id)
                    st.rerun()
                except Exception:
                    logger.exception("Failed to create product")
                    st.error("The product could not be saved. Check logs/errors.log for details.")

    with edit_tab:
        products = db.get_products()
        if not products:
            st.info("Add a product before editing.")
        else:
            labels = {f"{row['id']} - {row['product_name']}": row["id"] for row in products}
            selected_label = st.selectbox("Choose product", list(labels.keys()))
            selected = db.get_product(labels[selected_label])
            if selected:
                with st.form("edit_product_form"):
                    edited = _product_form("edit", config, selected)
                    submitted = st.form_submit_button("Save changes")

                if submitted:
                    if not edited["product_name"]:
                        st.error("Product name is required.")
                    else:
                        try:
                            db.update_product(int(selected["id"]), edited)
                            updated = db.get_product(int(selected["id"]))
                            if updated:
                                create_product_project(updated, Path(projects_root))
                            st.success(f"Product updated with score {edited['score']}.")
                            logger.info("Updated product %s", selected["id"])
                            st.rerun()
                        except Exception:
                            logger.exception("Failed to update product")
                            st.error("The product could not be updated. Check logs/errors.log for details.")

    with table_tab:
        status_options = ["All"] + config.get("defaults", {}).get("status_options", [])
        col1, col2 = st.columns([2, 1])
        search = col1.text_input("Search products")
        status = col2.selectbox("Filter status", status_options)
        _show_product_table(db.get_products(search=search.strip(), status=status))
