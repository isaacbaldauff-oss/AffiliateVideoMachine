"""Streamlit entry point for AffiliateVideoMachine."""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_config, resolve_project_path
from app.database import Database
from app.logging_config import setup_logging
from app.secrets import load_streamlit_secrets_to_env
from app.views import compliance_page, export_queue, overview, products, scripts, settings, tiktok


@st.cache_resource
def get_database(db_path: str) -> Database:
    """Create and initialize the SQLite database connection helper."""
    database = Database(Path(db_path))
    database.initialize()
    return database


def load_styles() -> None:
    """Load optional Streamlit CSS customizations."""
    css_path = ROOT / "assets" / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def main() -> None:
    """Run the Streamlit app."""
    load_streamlit_secrets_to_env()
    config = load_config()
    logger = setup_logging(config)
    app_name = config.get("app", {}).get("name", "AffiliateVideoMachine")

    st.set_page_config(page_title=app_name, layout="wide")
    load_styles()

    db_path = resolve_project_path(config.get("app", {}).get("database_path", "data/affiliate_video_machine.db"))
    db = get_database(str(db_path))

    st.sidebar.title(app_name)
    page_options = ["Overview", "Products", "Scripts", "Compliance", "Export Queue", "TikTok", "Settings"]
    if st.query_params.get("code") or st.query_params.get("error"):
        st.session_state["dashboard_page"] = "TikTok"

    page_name = st.sidebar.radio(
        "Dashboard",
        page_options,
        key="dashboard_page",
    )
    st.sidebar.caption("Local build + official API workflow")

    pages = {
        "Overview": overview.render,
        "Products": products.render,
        "Scripts": scripts.render,
        "Compliance": compliance_page.render,
        "Export Queue": export_queue.render,
        "TikTok": tiktok.render,
        "Settings": settings.render,
    }

    try:
        pages[page_name](config, db, logger)
    except Exception:
        logger.exception("Unhandled page error on %s", page_name)
        st.error("Something went wrong on this page. Details were written to logs/errors.log.")


if __name__ == "__main__":
    main()
