"""Products dashboard page."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from app.asset_importer import AssetImportError, ProductPageInspection, import_product_assets, inspect_product_url
from app.compliance import check_compliance
from app.config import resolve_project_path
from app.database import Database
from app.project_generator import create_product_project
from app.project_generator import save_generated_scripts
from app.scoring import calculate_product_score
from app.script_generator import DEFAULT_TEMPLATE_PATH, generate_scripts
from app.tiktok_shop import (
    PRODUCT_BOX_STATUS_OPTIONS,
    extract_tiktok_shop_product_id,
    is_tiktok_shop_url,
    product_box_status_for_platform,
    tiktok_shop_box_notes,
)


CATEGORY_KEYWORDS = [
    ("Hair product", ["hair", "sea salt", "texture spray", "shampoo", "conditioner", "styling"]),
    ("Skincare", ["skin", "serum", "moisturizer", "cleanser", "sunscreen"]),
    ("Kitchen", ["kitchen", "cook", "coffee", "pan", "knife", "blender"]),
    ("Home", ["home", "organizer", "storage", "cleaning", "decor"]),
    ("Tech", ["charger", "phone", "usb", "camera", "bluetooth", "keyboard"]),
    ("Fitness", ["fitness", "workout", "gym", "yoga", "training"]),
    ("Pet", ["dog", "cat", "pet"]),
]


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


def _normalize_product_url(value: str) -> str:
    """Add a scheme when a pasted product URL omits one."""
    text = value.strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme:
        return text
    return f"https://{text}"


def _parse_float(value: Any, default: float = 0.0, maximum: float | None = None) -> float:
    """Parse the first reasonable decimal number from scraped metadata."""
    if value is None:
        return default
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
    if not match:
        return default
    try:
        parsed = float(match.group(0).replace(",", ""))
    except ValueError:
        return default
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _parse_int(value: Any, default: int = 0) -> int:
    """Parse the first reasonable integer from scraped metadata."""
    if value is None:
        return default
    match = re.search(r"\d[\d,]*", str(value))
    if not match:
        return default
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return default


def _clean_product_name(value: str) -> str:
    """Clean a scraped page title into a usable product name."""
    text = " ".join(value.split())
    text = re.sub(r"\s*[:|-]\s*Amazon\.com.*$", "", text, flags=re.I)
    text = re.sub(r"\s*\|\s*Amazon.*$", "", text, flags=re.I)
    text = re.sub(r"\s*\|\s*TikTok.*$", "", text, flags=re.I)
    return text[:140].strip()


def _platform_from_url(product_url: str, platforms: list[str], override: str) -> str:
    """Infer an affiliate platform from the URL host unless the user overrides it."""
    if override != "Auto":
        return override

    host = urlparse(product_url).netloc.lower()
    platform_map = [
        ("shop.tiktok.com", "TikTok Shop"),
        ("tiktokshop", "TikTok Shop"),
        ("tiktok.", "TikTok Shop"),
        ("vt.tiktok.com", "TikTok Shop"),
        ("amazon.", "Amazon"),
        ("amzn.to", "Amazon"),
        ("impact.", "Impact"),
        ("shareasale.", "ShareASale"),
    ]
    for token, platform in platform_map:
        if token in host and platform in platforms:
            return platform
    return "Other" if "Other" in platforms else platforms[0]


def _category_from_metadata(metadata: dict[str, Any], title: str, override: str) -> str:
    """Infer a broad category from product text unless the user overrides it."""
    if override.strip():
        return override.strip()

    haystack = " ".join(
        str(metadata.get(key) or "")
        for key in ["title", "description", "brand"]
    )
    haystack = f"{haystack} {title}".lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return category
    return "Uncategorized"


def _compliance_risk_from_text(metadata: dict[str, Any], title: str) -> float:
    """Estimate starting compliance risk from sensitive product language."""
    haystack = " ".join(str(value or "") for value in metadata.values())
    haystack = f"{haystack} {title}".lower()
    risky = ["supplement", "medical", "pain", "relief", "weight loss", "cure", "before and after", "fda"]
    return 25.0 if any(term in haystack for term in risky) else 5.0


def _auto_product_data(
    product_url: str,
    inspection: ProductPageInspection | None,
    config: dict[str, Any],
    platform_override: str,
    category_override: str,
    commission_rate: float,
) -> dict[str, Any]:
    """Build a product record from a URL inspection with conservative defaults."""
    defaults = config.get("defaults", {})
    platforms = defaults.get("platforms", ["TikTok Shop", "Amazon", "Impact", "ShareASale", "Direct", "Other"])
    metadata = inspection.commercial_metadata if inspection else {}
    title = str(metadata.get("title") or (inspection.title if inspection else "") or "").strip()
    parsed_url = urlparse(inspection.final_url if inspection else product_url)
    host_name = parsed_url.netloc.replace("www.", "") or "product link"
    product_name = _clean_product_name(title) or f"Product from {host_name}"
    description = str(metadata.get("description") or "").strip()
    final_url = inspection.final_url if inspection else product_url
    image_count = len(inspection.image_urls) if inspection else 0
    platform = _platform_from_url(final_url, platforms, platform_override)
    tiktok_product_id = extract_tiktok_shop_product_id(final_url) if platform == "TikTok Shop" else ""
    product_box_status = product_box_status_for_platform(platform)

    data = {
        "product_name": product_name,
        "product_url": final_url,
        "platform": platform,
        "category": _category_from_metadata(metadata, title, category_override),
        "price": _parse_float(metadata.get("price")),
        "commission_rate": float(commission_rate),
        "rating": _parse_float(metadata.get("rating"), maximum=5.0),
        "review_count": _parse_int(metadata.get("review_count")),
        "visual_demo_score": 75.0 if image_count else 55.0,
        "compliance_risk_score": _compliance_risk_from_text(metadata, title),
        "tiktok_shop_product_id": tiktok_product_id,
        "product_box_status": product_box_status,
        "product_box_notes": tiktok_shop_box_notes(tiktok_product_id, final_url)
        if platform == "TikTok Shop"
        else "Generic affiliate product. This will not create the native TikTok Shop product box.",
        "notes": "\n\n".join(
            part
            for part in [
                f"Auto-created from URL: {final_url}",
                description[:1200],
                f"Found {image_count} candidate product image(s)." if inspection else "URL inspection was not available.",
            ]
            if part
        ),
        "status": "Researching",
    }
    data["score"] = calculate_product_score(data, config)
    return data


def _generate_scripts_for_product(
    product: dict[str, Any],
    config: dict[str, Any],
    db: Database,
    projects_root: Path,
    queue_first_script: bool,
) -> tuple[int, int | None]:
    """Generate scripts, run compliance checks, and optionally queue the first angle."""
    generated_scripts = generate_scripts(product, DEFAULT_TEMPLATE_PATH)
    save_generated_scripts(product, generated_scripts, projects_root)

    script_ids: dict[str, int] = {}
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
        script_ids[generated.angle] = script_id

    queued_id = None
    if queue_first_script and script_ids:
        preferred_script_id = script_ids.get("problem_solution") or next(iter(script_ids.values()))
        exports_root = resolve_project_path(config.get("app", {}).get("exports_path", "exports"))
        queued_id = db.add_export_item(
            product_id=int(product["id"]),
            script_id=preferred_script_id,
            export_type="Short-form video script",
            status="Planned",
            destination=str(exports_root),
            notes="Auto-queued from quick URL setup.",
        )
    return len(generated_scripts), queued_id


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
    with st.expander("TikTok Shop product box", expanded=False):
        tiktok_shop_product_id = st.text_input(
            "TikTok Shop product ID",
            value=str(existing.get("tiktok_shop_product_id") or ""),
            key=f"{prefix}_tiktok_shop_product_id",
        )
        product_box_status = st.selectbox(
            "Product box status",
            PRODUCT_BOX_STATUS_OPTIONS,
            index=_status_index(PRODUCT_BOX_STATUS_OPTIONS, existing.get("product_box_status") or "Needs product box"),
            key=f"{prefix}_product_box_status",
        )
        product_box_notes = st.text_area(
            "Product box notes",
            value=str(existing.get("product_box_notes") or ""),
            height=90,
            key=f"{prefix}_product_box_notes",
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
        "tiktok_shop_product_id": tiktok_shop_product_id.strip(),
        "product_box_status": product_box_status,
        "product_box_notes": product_box_notes.strip(),
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
            "Box": row.get("product_box_status") or "",
            "TikTok Product ID": row.get("tiktok_shop_product_id") or "",
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
    st.caption("TikTok Shop-first product intake for shoppable affiliate videos.")

    projects_root = resolve_project_path(config.get("app", {}).get("projects_path", "data/projects"))
    quick_tab, add_tab, edit_tab, table_tab = st.tabs(["Quick add URL", "Manual add", "Edit product", "Product list"])

    with quick_tab:
        st.write("Paste one TikTok Shop product URL. The app fills what it can, generates scripts, and queues the first draft.")
        defaults = config.get("defaults", {})
        platforms = defaults.get("platforms", ["TikTok Shop", "Amazon", "Impact", "ShareASale", "Direct", "Other"])
        with st.form("quick_add_product_form"):
            product_url = st.text_input("TikTok Shop product URL")
            with st.expander("Optional overrides", expanded=False):
                platform_override = st.selectbox("Platform", ["Auto"] + platforms)
                category_override = st.text_input("Category override")
                commission_rate = st.number_input(
                    "Commission rate if known (%)",
                    min_value=0.0,
                    max_value=100.0,
                    value=0.0,
                    step=0.5,
                )
                max_images = st.slider("Images to import", min_value=1, max_value=12, value=10, step=1)
                auto_generate_scripts = st.checkbox("Generate scripts automatically", value=True)
                queue_first_script = st.checkbox("Add the first script to Export Queue", value=True)
            submitted = st.form_submit_button("Auto-create product")

        if submitted:
            clean_product_url = _normalize_product_url(product_url)
            if not clean_product_url:
                st.error("Paste a product or affiliate URL first.")
            else:
                try:
                    inspection: ProductPageInspection | None = None
                    with st.spinner("Reading product URL and extracting product details..."):
                        if not is_tiktok_shop_url(clean_product_url):
                            st.warning(
                                "This does not look like a TikTok Shop product link. "
                                "The app will still create a product, but it may not support the native TikTok product box."
                            )
                        try:
                            inspection = inspect_product_url(clean_product_url)
                        except Exception as exc:
                            logger.warning("Product URL inspection failed: %s", exc)
                            st.warning("The URL could not be fully inspected, so the app will create a basic product record.")

                        data = _auto_product_data(
                            product_url=clean_product_url,
                            inspection=inspection,
                            config=config,
                            platform_override=platform_override,
                            category_override=category_override,
                            commission_rate=commission_rate,
                        )
                        product_id = db.create_product(data)
                        product = db.get_product(product_id)
                        if not product:
                            raise RuntimeError("Product was created but could not be reloaded.")
                        create_product_project(product, Path(projects_root))

                        imported_count = 0
                        try:
                            import_result = import_product_assets(
                                product,
                                Path(projects_root),
                                max_images=max_images,
                                inspection=inspection,
                            )
                            imported_count = len(import_result.saved_images)
                        except AssetImportError as exc:
                            logger.warning("Quick add asset import warning for product %s: %s", product_id, exc)
                        except Exception:
                            logger.exception("Quick add asset import failed for product %s", product_id)

                        generated_count = 0
                        queue_id = None
                        if auto_generate_scripts:
                            generated_count, queue_id = _generate_scripts_for_product(
                                product,
                                config,
                                db,
                                Path(projects_root),
                                queue_first_script=queue_first_script,
                            )
                            db.update_product(int(product["id"]), {"status": "Scripted"})

                    st.success(
                        f"Created product #{product_id}. Imported {imported_count} image(s). "
                        f"Generated {generated_count} script(s)."
                    )
                    if queue_id:
                        st.info(f"Queued the first script for export as item #{queue_id}. Open Export Queue next.")
                    logger.info("Quick-created product %s from URL", product_id)
                except Exception:
                    logger.exception("Quick product setup failed")
                    st.error("Quick setup could not finish. Check logs/errors.log for details.")

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
