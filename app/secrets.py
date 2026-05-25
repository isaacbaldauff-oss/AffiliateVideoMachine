"""Secret loading helpers for local and Streamlit Cloud deployments."""

from __future__ import annotations

import os
from typing import Any


def _streamlit_secret_value(name: str) -> Any:
    """Return a Streamlit secret value when running inside Streamlit."""
    try:
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        return None
    return None


def get_secret(name: str) -> str:
    """Read a secret from the environment, falling back to Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value.strip()

    secret_value = _streamlit_secret_value(name)
    if isinstance(secret_value, (str, int, float, bool)):
        return str(secret_value).strip()
    return ""


def load_streamlit_secrets_to_env() -> None:
    """Copy scalar Streamlit secrets into environment variables for existing integrations."""
    try:
        import streamlit as st

        secret_items = dict(st.secrets).items()
    except Exception:
        return

    for name, value in secret_items:
        if name in os.environ:
            continue
        if isinstance(value, (str, int, float, bool)):
            os.environ[name] = str(value)
