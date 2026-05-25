"""Official TikTok Content Posting API client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import math
import secrets
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, urlencode, urlparse


class TikTokApiError(RuntimeError):
    """Raised when TikTok API requests fail."""


@dataclass(slots=True)
class TikTokTokenResponse:
    """OAuth token response values."""

    open_id: str
    access_token: str
    refresh_token: str
    scope: str
    expires_at: str
    refresh_expires_at: str
    token_type: str


def _require_requests() -> Any:
    """Import requests only when TikTok API calls are made."""
    try:
        import requests
    except ImportError as exc:
        raise TikTokApiError("TikTok integration requires requests. Run: pip install -r requirements.txt") from exc
    return requests


def utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.utcnow()


def iso_from_seconds(seconds: int | float) -> str:
    """Return an ISO timestamp seconds from now."""
    return (utc_now() + timedelta(seconds=float(seconds))).isoformat(timespec="seconds")


def extract_auth_code(value: str) -> str:
    """Extract a TikTok authorization code from a pasted URL or raw code."""
    text = value.strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.query:
        query = parse_qs(parsed.query)
        code = query.get("code", [""])[0]
        if code:
            return code
    return text


def build_authorization_url(client_key: str, redirect_uri: str, scopes: list[str], state: str | None = None) -> str:
    """Build a TikTok OAuth authorization URL."""
    if not client_key or not redirect_uri:
        raise TikTokApiError("Client key and redirect URI are required.")
    state_value = state or secrets.token_urlsafe(24)
    query = {
        "client_key": client_key,
        "response_type": "code",
        "scope": ",".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state_value,
    }
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(query, quote_via=quote)


def _parse_token_response(data: Mapping[str, Any]) -> TikTokTokenResponse:
    """Convert OAuth response JSON into a typed token payload."""
    if "access_token" not in data:
        raise TikTokApiError(f"TikTok did not return an access token: {data}")
    return TikTokTokenResponse(
        open_id=str(data.get("open_id") or ""),
        access_token=str(data["access_token"]),
        refresh_token=str(data.get("refresh_token") or ""),
        scope=str(data.get("scope") or ""),
        expires_at=iso_from_seconds(float(data.get("expires_in") or 0)),
        refresh_expires_at=iso_from_seconds(float(data.get("refresh_expires_in") or 0)),
        token_type=str(data.get("token_type") or "Bearer"),
    )


def exchange_auth_code(client_key: str, client_secret: str, redirect_uri: str, code_or_url: str) -> TikTokTokenResponse:
    """Exchange an authorization code for TikTok user access tokens."""
    requests = _require_requests()
    code = extract_auth_code(code_or_url)
    if not code:
        raise TikTokApiError("Authorization code is empty.")

    response = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise TikTokApiError(f"TikTok token exchange failed: {response.text[:1000]}")
    return _parse_token_response(response.json())


def refresh_access_token(client_key: str, client_secret: str, refresh_token: str) -> TikTokTokenResponse:
    """Refresh a TikTok access token."""
    requests = _require_requests()
    response = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise TikTokApiError(f"TikTok token refresh failed: {response.text[:1000]}")
    return _parse_token_response(response.json())


def query_creator_info(access_token: str) -> dict[str, Any]:
    """Fetch latest creator posting settings from TikTok."""
    requests = _require_requests()
    response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise TikTokApiError(f"TikTok creator info request failed: {response.text[:1000]}")
    payload = response.json()
    error = payload.get("error", {})
    if error.get("code") not in (None, "ok"):
        raise TikTokApiError(f"TikTok creator info error: {error}")
    return dict(payload.get("data") or {})


def _chunk_plan(video_size: int) -> tuple[int, int]:
    """Return chunk size and count that satisfy TikTok media transfer limits."""
    if video_size <= 0:
        raise TikTokApiError("Video file is empty.")
    minimum = 5 * 1024 * 1024
    maximum = 64 * 1024 * 1024
    if video_size <= minimum:
        return video_size, 1
    chunk_size = min(maximum, max(minimum, video_size))
    total_chunks = math.ceil(video_size / chunk_size)
    return chunk_size, total_chunks


def initialize_inbox_upload(access_token: str, video_path: Path) -> dict[str, Any]:
    """Initialize Upload-to-Inbox video transfer."""
    requests = _require_requests()
    video_size = video_path.stat().st_size
    chunk_size, total_chunks = _chunk_plan(video_size)
    response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            }
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise TikTokApiError(f"TikTok inbox upload init failed: {response.text[:1000]}")
    payload = response.json()
    error = payload.get("error", {})
    if error.get("code") not in (None, "ok"):
        raise TikTokApiError(f"TikTok inbox upload init error: {error}")
    return dict(payload.get("data") or {})


def initialize_direct_post(
    access_token: str,
    video_path: Path,
    title: str,
    privacy_level: str,
    disable_comment: bool,
    disable_duet: bool,
    disable_stitch: bool,
    branded_content: bool,
    your_brand: bool,
    is_aigc: bool,
) -> dict[str, Any]:
    """Initialize a direct video post."""
    requests = _require_requests()
    video_size = video_path.stat().st_size
    chunk_size, total_chunks = _chunk_plan(video_size)
    response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "post_info": {
                "title": title,
                "privacy_level": privacy_level,
                "disable_duet": disable_duet,
                "disable_comment": disable_comment,
                "disable_stitch": disable_stitch,
                "video_cover_timestamp_ms": 1000,
                "brand_content_toggle": branded_content,
                "brand_organic_toggle": your_brand,
                "is_aigc": is_aigc,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            },
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise TikTokApiError(f"TikTok direct post init failed: {response.text[:1000]}")
    payload = response.json()
    error = payload.get("error", {})
    if error.get("code") not in (None, "ok"):
        raise TikTokApiError(f"TikTok direct post init error: {error}")
    return dict(payload.get("data") or {})


def upload_video_file(upload_url: str, video_path: Path, chunk_size: int | None = None) -> None:
    """Upload local MP4 bytes to TikTok's upload URL."""
    requests = _require_requests()
    video_size = video_path.stat().st_size
    planned_chunk_size = chunk_size or _chunk_plan(video_size)[0]
    with video_path.open("rb") as file:
        first_byte = 0
        while first_byte < video_size:
            chunk = file.read(planned_chunk_size)
            last_byte = first_byte + len(chunk) - 1
            response = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {first_byte}-{last_byte}/{video_size}",
                },
                data=chunk,
                timeout=180,
            )
            if response.status_code >= 400:
                raise TikTokApiError(f"TikTok video upload failed: {response.text[:1000]}")
            first_byte = last_byte + 1


def fetch_publish_status(access_token: str, publish_id: str) -> dict[str, Any]:
    """Fetch TikTok processing/publish status."""
    requests = _require_requests()
    response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={"publish_id": publish_id},
        timeout=60,
    )
    if response.status_code >= 400:
        raise TikTokApiError(f"TikTok publish status request failed: {response.text[:1000]}")
    payload = response.json()
    error = payload.get("error", {})
    if error.get("code") not in (None, "ok"):
        raise TikTokApiError(f"TikTok publish status error: {error}")
    return dict(payload.get("data") or {})
