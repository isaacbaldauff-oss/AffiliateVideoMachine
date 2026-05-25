"""TikTok publishing dashboard page."""

from __future__ import annotations

import json
import logging
import secrets as token_secrets
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd
import streamlit as st

from app.database import Database
from app.secrets import get_secret
from app.tiktok_caption import build_tiktok_caption
from app.tiktok_client import (
    TikTokApiError,
    build_authorization_url,
    exchange_auth_code,
    fetch_publish_status,
    initialize_direct_post,
    initialize_inbox_upload,
    query_creator_info,
    refresh_access_token,
    upload_video_file,
)


def _tiktok_credentials(config: dict[str, Any]) -> tuple[str, str, str, list[str], str, str, str]:
    """Return TikTok credential values and env var names."""
    tiktok_config = config.get("tiktok", {})
    if not isinstance(tiktok_config, dict):
        tiktok_config = {}
    client_key_env = str(tiktok_config.get("client_key_env", "TIKTOK_CLIENT_KEY"))
    client_secret_env = str(tiktok_config.get("client_secret_env", "TIKTOK_CLIENT_SECRET"))
    redirect_uri_env = str(tiktok_config.get("redirect_uri_env", "TIKTOK_REDIRECT_URI"))
    redirect_uri = get_secret(redirect_uri_env) or str(tiktok_config.get("redirect_uri", "https://your-app.streamlit.app"))
    scopes = tiktok_config.get("scopes", ["user.info.basic", "video.upload", "video.publish"])
    if not isinstance(scopes, list):
        scopes = ["user.info.basic", "video.upload", "video.publish"]
    return (
        get_secret(client_key_env),
        get_secret(client_secret_env),
        redirect_uri,
        scopes,
        client_key_env,
        client_secret_env,
        redirect_uri_env,
    )


def _query_param(name: str) -> str:
    """Read a Streamlit query parameter as a single string."""
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def _extract_query_value(value: str, name: str) -> str:
    """Extract a named query value from a pasted callback URL."""
    parsed = urlparse(value.strip())
    if not parsed.query:
        return ""
    return parse_qs(parsed.query).get(name, [""])[0]


def _account_label(account: dict[str, Any]) -> str:
    """Build a readable account label."""
    creator_info = json.loads(account.get("creator_info") or "{}")
    username = creator_info.get("creator_username") or creator_info.get("creator_nickname")
    suffix = f" - @{username}" if username else ""
    return f"#{account['id']}{suffix} ({account.get('open_id', '')[:8]})"


def _video_queue_options(db: Database) -> dict[str, dict[str, Any]]:
    """Return export queue rows that point at local MP4 files."""
    options: dict[str, dict[str, Any]] = {}
    for row in db.list_export_queue():
        destination = str(row.get("destination") or "")
        path = Path(destination)
        if path.suffix.lower() != ".mp4" or not path.exists():
            continue
        label = f"#{row['id']} - {row.get('product_name') or 'Untitled'} - {path.name}"
        options[label] = row
    return options


def _history_table(rows: list[dict[str, Any]]) -> None:
    """Render TikTok publish/upload history."""
    if not rows:
        st.info("No TikTok uploads tracked yet.")
        return
    display = [
        {
            "ID": row["id"],
            "Product": row.get("product_name") or "",
            "Mode": row["upload_mode"],
            "Status": row["status"],
            "Publish ID": row.get("publish_id") or "",
            "Updated": row["updated_at"],
        }
        for row in rows
    ]
    st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)


def _render_connect_tab(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render TikTok OAuth connection tools."""
    st.subheader("Connect TikTok")
    (
        client_key,
        client_secret,
        redirect_uri,
        scopes,
        client_key_env,
        client_secret_env,
        redirect_uri_env,
    ) = _tiktok_credentials(config)

    st.write(f"Client key env: `{client_key_env}`")
    st.write(f"Client secret env: `{client_secret_env}`")
    st.write(f"Redirect URI env: `{redirect_uri_env}`")
    st.write(f"Redirect URI: `{redirect_uri}`")
    st.caption(
        "Register this exact HTTPS URL in Login Kit. For Streamlit Community Cloud, use the deployed app URL with no query string."
    )

    pasted_client_key = st.text_input("Client key override", value="", type="password")
    pasted_client_secret = st.text_input("Client secret override", value="", type="password")
    effective_client_key = pasted_client_key.strip() or client_key
    effective_client_secret = pasted_client_secret.strip() or client_secret

    query_error = _query_param("error")
    query_error_description = _query_param("error_description")
    query_code = _query_param("code")
    query_state = _query_param("state")
    query_scopes = _query_param("scopes")

    if "tiktok_oauth_state" not in st.session_state:
        st.session_state["tiktok_oauth_state"] = token_secrets.token_urlsafe(24)

    if query_error:
        st.error(f"TikTok returned an authorization error: {query_error} {query_error_description}".strip())

    if query_code:
        st.success("TikTok returned an authorization code to this dashboard.")
        if query_scopes:
            st.caption(f"Granted scopes: {query_scopes}")
        if query_state and query_state != st.session_state.get("tiktok_oauth_state"):
            st.warning("The returned state does not match this browser session. Start a fresh authorization if this was unexpected.")
        if st.session_state.get("tiktok_code_prefill") != query_code:
            st.session_state["tiktok_exchange_input"] = query_code
            st.session_state["tiktok_code_prefill"] = query_code
        if st.button("Clear TikTok callback from URL"):
            st.query_params.clear()
            st.rerun()

    if effective_client_key:
        try:
            auth_url = build_authorization_url(
                effective_client_key,
                redirect_uri,
                scopes,
                state=str(st.session_state["tiktok_oauth_state"]),
            )
            st.link_button("Open TikTok authorization", auth_url)
            st.text_area("Authorization URL", value=auth_url, height=90)
        except TikTokApiError as exc:
            st.error(str(exc))
    else:
        st.warning("Set the TikTok client key environment variable or paste it above.")

    with st.form("tiktok_exchange_code_form"):
        code_or_url = st.text_area(
            "Paste returned callback URL or authorization code",
            height=110,
            key="tiktok_exchange_input",
        )
        submitted = st.form_submit_button("Save TikTok account")

    if submitted:
        try:
            if not effective_client_key or not effective_client_secret:
                st.error("Client key and client secret are required.")
                return
            returned_state = _extract_query_value(code_or_url, "state") or query_state
            expected_state = str(st.session_state.get("tiktok_oauth_state") or "")
            if returned_state and expected_state and returned_state != expected_state:
                st.error("The TikTok callback state did not match this browser session. Open a new authorization link and try again.")
                return
            token_data = exchange_auth_code(effective_client_key, effective_client_secret, redirect_uri, code_or_url)
            account_id = db.upsert_tiktok_account(token_data)
            st.session_state["tiktok_oauth_state"] = token_secrets.token_urlsafe(24)
            st.query_params.clear()
            st.success(f"TikTok account saved as #{account_id}.")
            logger.info("Saved TikTok account %s", account_id)
            st.rerun()
        except Exception:
            logger.exception("TikTok account connection failed")
            st.error("TikTok account connection failed. Check logs/errors.log for details.")


def _render_account_tab(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render connected account tools."""
    st.subheader("Connected Accounts")
    accounts = db.list_tiktok_accounts()
    if not accounts:
        st.info("No TikTok account connected yet.")
        return

    labels = {_account_label(account): account for account in accounts}
    selected = st.selectbox("Account", list(labels.keys()), key="tiktok_account_tools")
    account = labels[selected]
    client_key, client_secret, _, _, _, _, _ = _tiktok_credentials(config)

    col1, col2 = st.columns(2)
    if col1.button("Refresh access token"):
        try:
            token_data = refresh_access_token(client_key, client_secret, account["refresh_token"])
            db.update_tiktok_account_tokens(int(account["id"]), token_data)
            st.success("Access token refreshed.")
            logger.info("Refreshed TikTok account %s", account["id"])
            st.rerun()
        except Exception:
            logger.exception("TikTok token refresh failed")
            st.error("Token refresh failed. Check logs/errors.log for details.")

    if col2.button("Query creator info"):
        try:
            creator_info = query_creator_info(account["access_token"])
            db.update_tiktok_account_creator_info(int(account["id"]), creator_info)
            st.success("Creator info updated.")
            logger.info("Updated TikTok creator info for account %s", account["id"])
            st.rerun()
        except Exception:
            logger.exception("TikTok creator info query failed")
            st.error("Creator info query failed. Check logs/errors.log for details.")

    creator_info = json.loads(account.get("creator_info") or "{}")
    if creator_info:
        st.json(creator_info)
    else:
        st.info("Query creator info before posting so the app can use TikTok's current privacy and duration rules.")


def _render_publish_tab(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render TikTok upload/direct post workflow."""
    st.subheader("Publish or Upload Draft")
    accounts = db.list_tiktok_accounts()
    video_options = _video_queue_options(db)
    if not accounts:
        st.info("Connect a TikTok account first.")
        return
    if not video_options:
        st.info("No rendered MP4 found in the export queue. Run the autonomous media pipeline first.")
        return

    account_labels = {_account_label(account): account for account in accounts}
    selected_account_label = st.selectbox("TikTok account", list(account_labels.keys()), key="tiktok_publish_account")
    account = account_labels[selected_account_label]

    video_label = st.selectbox("Rendered video", list(video_options.keys()))
    queue_row = video_options[video_label]
    video_path = Path(str(queue_row["destination"]))
    product = db.get_product(int(queue_row["product_id"])) if queue_row.get("product_id") else {}
    script = db.get_script(int(queue_row["script_id"])) if queue_row.get("script_id") else {}
    caption = build_tiktok_caption(product or {}, script or {})

    creator_info = json.loads(account.get("creator_info") or "{}")
    if not creator_info:
        st.warning("Query creator info on the Accounts tab before posting.")

    privacy_options = creator_info.get("privacy_level_options") or ["SELF_ONLY"]
    max_duration = creator_info.get("max_video_post_duration_sec")
    st.write(f"Video: `{video_path}`")
    if max_duration:
        st.caption(f"TikTok creator max duration: {max_duration} seconds")

    upload_mode = st.radio(
        "TikTok mode",
        ["Upload to TikTok inbox draft", "Direct post to TikTok"],
        horizontal=True,
    )
    edited_caption = st.text_area("Caption", value=caption, height=150, max_chars=2200)

    privacy_level = ""
    disable_comment = False
    disable_duet = False
    disable_stitch = False
    if upload_mode == "Direct post to TikTok":
        privacy_choice = st.selectbox("Privacy", ["Choose privacy"] + list(privacy_options), index=0)
        privacy_level = "" if privacy_choice == "Choose privacy" else privacy_choice
        creator_comment_disabled = bool(creator_info.get("comment_disabled", False))
        creator_duet_disabled = bool(creator_info.get("duet_disabled", False))
        creator_stitch_disabled = bool(creator_info.get("stitch_disabled", False))
        disable_comment = st.checkbox("Disable comments", value=creator_comment_disabled, disabled=creator_comment_disabled)
        disable_duet = st.checkbox("Disable duets", value=creator_duet_disabled, disabled=creator_duet_disabled)
        disable_stitch = st.checkbox("Disable stitches", value=creator_stitch_disabled, disabled=creator_stitch_disabled)

    st.subheader("Commercial disclosure")
    branded_content = st.checkbox("Branded content / third-party product", value=True)
    your_brand = st.checkbox("My own brand", value=False)
    is_aigc = st.checkbox("AI-generated content", value=True)
    consent = st.checkbox(
        "I reviewed the video, caption, disclosure, and TikTok account. I consent to send this video to TikTok.",
        value=False,
    )

    if st.button("Send to TikTok", disabled=not consent):
        try:
            if upload_mode == "Direct post to TikTok" and not privacy_level:
                st.error("Choose a privacy level before direct posting.")
                return
            if upload_mode == "Direct post to TikTok" and not (branded_content or your_brand):
                st.error("Commercial content disclosure requires at least one disclosure type.")
                return

            access_token = account["access_token"]
            if upload_mode == "Upload to TikTok inbox draft":
                init_data = initialize_inbox_upload(access_token, video_path)
                mode = "inbox"
            else:
                init_data = initialize_direct_post(
                    access_token=access_token,
                    video_path=video_path,
                    title=edited_caption,
                    privacy_level=privacy_level,
                    disable_comment=disable_comment,
                    disable_duet=disable_duet,
                    disable_stitch=disable_stitch,
                    branded_content=branded_content,
                    your_brand=your_brand,
                    is_aigc=is_aigc,
                )
                mode = "direct_post"

            publish_id = init_data.get("publish_id")
            upload_url = init_data.get("upload_url")
            if not publish_id or not upload_url:
                raise TikTokApiError(f"TikTok did not return publish_id and upload_url: {init_data}")

            with st.spinner("Uploading video to TikTok..."):
                upload_video_file(upload_url, video_path)

            status_data = fetch_publish_status(access_token, str(publish_id))
            post_id = db.create_tiktok_post(
                {
                    "account_id": int(account["id"]),
                    "export_queue_id": int(queue_row["id"]),
                    "product_id": queue_row.get("product_id"),
                    "script_id": queue_row.get("script_id"),
                    "video_path": str(video_path),
                    "caption": edited_caption,
                    "upload_mode": mode,
                    "privacy_level": privacy_level,
                    "disable_comment": disable_comment,
                    "disable_duet": disable_duet,
                    "disable_stitch": disable_stitch,
                    "branded_content": branded_content,
                    "your_brand": your_brand,
                    "publish_id": publish_id,
                    "status": str(status_data.get("status") or "uploaded"),
                    "response_json": status_data,
                }
            )
            st.success(f"Sent to TikTok. Tracking record #{post_id}.")
            st.json(status_data)
            logger.info("Uploaded TikTok video for queue item %s with publish_id %s", queue_row["id"], publish_id)
        except Exception:
            logger.exception("TikTok upload failed")
            st.error("TikTok upload failed. Check logs/errors.log for details.")


def _render_history_tab(db: Database, logger: logging.Logger) -> None:
    """Render TikTok status history and status refresh controls."""
    st.subheader("TikTok Status")
    posts = db.list_tiktok_posts()
    _history_table(posts)
    if not posts:
        return

    accounts = {account["id"]: account for account in db.list_tiktok_accounts()}
    post_labels = {f"#{row['id']} - {row.get('product_name') or row['publish_id']}": row for row in posts}
    selected = st.selectbox("Tracking record", list(post_labels.keys()))
    post = post_labels[selected]
    if st.button("Refresh TikTok status"):
        try:
            account = accounts.get(post["account_id"])
            if not account:
                st.error("Connected account for this record is missing.")
                return
            status_data = fetch_publish_status(account["access_token"], post["publish_id"])
            db.update_tiktok_post_status(int(post["id"]), str(status_data.get("status") or "unknown"), status_data)
            st.success("Status refreshed.")
            st.json(status_data)
            logger.info("Refreshed TikTok post %s", post["id"])
            st.rerun()
        except Exception:
            logger.exception("TikTok status refresh failed")
            st.error("TikTok status refresh failed. Check logs/errors.log for details.")


def render(config: dict[str, Any], db: Database, logger: logging.Logger) -> None:
    """Render official TikTok publishing integration."""
    st.title("TikTok")
    st.caption("Official API flow for drafts/direct posts. Product-link attachment may still require TikTok Shop tools.")
    connect_tab, account_tab, publish_tab, history_tab = st.tabs(
        ["Connect", "Accounts", "Publish", "Status"]
    )
    with connect_tab:
        _render_connect_tab(config, db, logger)
    with account_tab:
        _render_account_tab(config, db, logger)
    with publish_tab:
        _render_publish_tab(config, db, logger)
    with history_tab:
        _render_history_tab(db, logger)
