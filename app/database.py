"""SQLite database access layer."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.models import ComplianceResult, GeneratedScript


PRODUCT_FIELDS = [
    "product_name",
    "product_url",
    "platform",
    "category",
    "price",
    "commission_rate",
    "rating",
    "review_count",
    "visual_demo_score",
    "compliance_risk_score",
    "notes",
    "status",
    "score",
]


def utc_now() -> str:
    """Return an ISO timestamp for local database records."""
    return datetime.utcnow().isoformat(timespec="seconds")


class Database:
    """Small SQLite repository for dashboard data."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a SQLite connection with dictionary-like row access."""
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create required tables if they do not already exist."""
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    product_url TEXT,
                    platform TEXT,
                    category TEXT,
                    price REAL DEFAULT 0,
                    commission_rate REAL DEFAULT 0,
                    rating REAL DEFAULT 0,
                    review_count INTEGER DEFAULT 0,
                    visual_demo_score REAL DEFAULT 50,
                    compliance_risk_score REAL DEFAULT 0,
                    notes TEXT,
                    status TEXT DEFAULT 'Researching',
                    score REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    angle TEXT NOT NULL,
                    title TEXT NOT NULL,
                    script_text TEXT NOT NULL,
                    compliance_status TEXT DEFAULT 'unchecked',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
                    UNIQUE(product_id, angle)
                );

                CREATE TABLE IF NOT EXISTS compliance_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    script_id INTEGER,
                    content_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risky_terms TEXT NOT NULL,
                    has_disclosure INTEGER NOT NULL,
                    messages TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
                    FOREIGN KEY(script_id) REFERENCES scripts(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS export_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    script_id INTEGER,
                    export_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    destination TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
                    FOREIGN KEY(script_id) REFERENCES scripts(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS tiktok_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    open_id TEXT NOT NULL UNIQUE,
                    scope TEXT,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    token_type TEXT,
                    expires_at TEXT,
                    refresh_expires_at TEXT,
                    creator_info TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tiktok_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    export_queue_id INTEGER,
                    product_id INTEGER,
                    script_id INTEGER,
                    video_path TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    upload_mode TEXT NOT NULL,
                    privacy_level TEXT,
                    disable_comment INTEGER DEFAULT 0,
                    disable_duet INTEGER DEFAULT 0,
                    disable_stitch INTEGER DEFAULT 0,
                    branded_content INTEGER DEFAULT 1,
                    your_brand INTEGER DEFAULT 0,
                    publish_id TEXT,
                    status TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES tiktok_accounts(id) ON DELETE CASCADE,
                    FOREIGN KEY(export_queue_id) REFERENCES export_queue(id) ON DELETE SET NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
                    FOREIGN KEY(script_id) REFERENCES scripts(id) ON DELETE SET NULL
                );
                """
            )

    def create_product(self, data: dict[str, Any]) -> int:
        """Insert a product and return its ID."""
        now = utc_now()
        fields = [field for field in PRODUCT_FIELDS if field in data]
        columns = fields + ["created_at", "updated_at"]
        placeholders = ", ".join("?" for _ in columns)
        values = [data[field] for field in fields] + [now, now]

        with self.connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO products ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            return int(cursor.lastrowid)

    def update_product(self, product_id: int, data: dict[str, Any]) -> None:
        """Update product fields by ID."""
        fields = [field for field in PRODUCT_FIELDS if field in data]
        if not fields:
            return

        assignments = ", ".join(f"{field} = ?" for field in fields)
        values = [data[field] for field in fields] + [utc_now(), product_id]

        with self.connect() as connection:
            connection.execute(
                f"UPDATE products SET {assignments}, updated_at = ? WHERE id = ?",
                values,
            )

    def get_product(self, product_id: int) -> dict[str, Any] | None:
        """Fetch one product by ID."""
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None

    def get_products(self, search: str = "", status: str = "All") -> list[dict[str, Any]]:
        """Return products, optionally filtered by search text and status."""
        query = "SELECT * FROM products WHERE 1 = 1"
        params: list[Any] = []
        if search:
            query += " AND (product_name LIKE ? OR category LIKE ? OR platform LIKE ?)"
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        if status != "All":
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY score DESC, updated_at DESC"

        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def upsert_script(
        self,
        product_id: int,
        script: GeneratedScript,
        compliance_status: str = "unchecked",
    ) -> int:
        """Insert or update a generated script for a product and angle."""
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO scripts (
                    product_id, angle, title, script_text, compliance_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id, angle) DO UPDATE SET
                    title = excluded.title,
                    script_text = excluded.script_text,
                    compliance_status = excluded.compliance_status,
                    updated_at = excluded.updated_at
                """,
                (
                    product_id,
                    script.angle,
                    script.title,
                    script.script_text,
                    compliance_status,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM scripts WHERE product_id = ? AND angle = ?",
                (product_id, script.angle),
            ).fetchone()
        if row is None:
            raise RuntimeError("Script upsert succeeded but script could not be found.")
        return int(row["id"])

    def get_script(self, script_id: int) -> dict[str, Any] | None:
        """Fetch one script by ID."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT scripts.*, products.product_name
                FROM scripts
                JOIN products ON products.id = scripts.product_id
                WHERE scripts.id = ?
                """,
                (script_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_scripts(self, product_id: int | None = None) -> list[dict[str, Any]]:
        """List scripts, optionally for a single product."""
        params: list[Any] = []
        query = """
            SELECT scripts.*, products.product_name
            FROM scripts
            JOIN products ON products.id = scripts.product_id
        """
        if product_id is not None:
            query += " WHERE scripts.product_id = ?"
            params.append(product_id)
        query += " ORDER BY scripts.updated_at DESC"

        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def add_compliance_check(
        self,
        content_type: str,
        content: str,
        result: ComplianceResult,
        product_id: int | None = None,
        script_id: int | None = None,
    ) -> int:
        """Store a compliance check result."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO compliance_checks (
                    product_id, script_id, content_type, content, status, risky_terms,
                    has_disclosure, messages, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    script_id,
                    content_type,
                    content,
                    result.status,
                    json.dumps(result.risky_terms),
                    int(result.has_disclosure),
                    json.dumps(result.messages),
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def list_compliance_checks(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent compliance checks."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT compliance_checks.*, products.product_name, scripts.angle
                FROM compliance_checks
                LEFT JOIN products ON products.id = compliance_checks.product_id
                LEFT JOIN scripts ON scripts.id = compliance_checks.script_id
                ORDER BY compliance_checks.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_export_item(
        self,
        product_id: int | None,
        script_id: int | None,
        export_type: str,
        status: str,
        destination: str,
        notes: str,
    ) -> int:
        """Add an item to the local export queue."""
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO export_queue (
                    product_id, script_id, export_type, status, destination, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, script_id, export_type, status, destination, notes, now, now),
            )
            return int(cursor.lastrowid)

    def list_export_queue(self) -> list[dict[str, Any]]:
        """Return export queue rows with linked product and script data."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    export_queue.*,
                    products.product_name,
                    scripts.angle,
                    scripts.title
                FROM export_queue
                LEFT JOIN products ON products.id = export_queue.product_id
                LEFT JOIN scripts ON scripts.id = export_queue.script_id
                ORDER BY export_queue.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_export_item(self, item_id: int, status: str, destination: str, notes: str) -> None:
        """Update an export queue item."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE export_queue
                SET status = ?, destination = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, destination, notes, utc_now(), item_id),
            )

    def dashboard_stats(self) -> dict[str, Any]:
        """Return aggregate metrics for the overview page."""
        with self.connect() as connection:
            products = connection.execute("SELECT COUNT(*) AS count FROM products").fetchone()["count"]
            scripts = connection.execute("SELECT COUNT(*) AS count FROM scripts").fetchone()["count"]
            queue = connection.execute("SELECT COUNT(*) AS count FROM export_queue").fetchone()["count"]
            average_score = connection.execute("SELECT AVG(score) AS value FROM products").fetchone()["value"]
            compliance_rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM compliance_checks
                GROUP BY status
                """
            ).fetchall()

        compliance_counts = {row["status"]: row["count"] for row in compliance_rows}
        return {
            "products": products,
            "scripts": scripts,
            "queue": queue,
            "average_score": round(float(average_score or 0), 2),
            "compliance_counts": compliance_counts,
        }

    def upsert_tiktok_account(self, token_data: Any) -> int:
        """Insert or update a TikTok OAuth account."""
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tiktok_accounts (
                    open_id, scope, access_token, refresh_token, token_type,
                    expires_at, refresh_expires_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(open_id) DO UPDATE SET
                    scope = excluded.scope,
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    token_type = excluded.token_type,
                    expires_at = excluded.expires_at,
                    refresh_expires_at = excluded.refresh_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    token_data.open_id,
                    token_data.scope,
                    token_data.access_token,
                    token_data.refresh_token,
                    token_data.token_type,
                    token_data.expires_at,
                    token_data.refresh_expires_at,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM tiktok_accounts WHERE open_id = ?",
                (token_data.open_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("TikTok account was saved but could not be loaded.")
        return int(row["id"])

    def list_tiktok_accounts(self) -> list[dict[str, Any]]:
        """Return connected TikTok accounts."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tiktok_accounts ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_tiktok_account(self, account_id: int) -> dict[str, Any] | None:
        """Fetch one TikTok account."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tiktok_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_tiktok_account_creator_info(self, account_id: int, creator_info: dict[str, Any]) -> None:
        """Persist latest TikTok creator info."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tiktok_accounts
                SET creator_info = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(creator_info), utc_now(), account_id),
            )

    def update_tiktok_account_tokens(self, account_id: int, token_data: Any) -> None:
        """Update OAuth tokens for a TikTok account."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tiktok_accounts
                SET access_token = ?, refresh_token = ?, scope = ?, token_type = ?,
                    expires_at = ?, refresh_expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    token_data.access_token,
                    token_data.refresh_token,
                    token_data.scope,
                    token_data.token_type,
                    token_data.expires_at,
                    token_data.refresh_expires_at,
                    utc_now(),
                    account_id,
                ),
            )

    def create_tiktok_post(self, data: dict[str, Any]) -> int:
        """Create a TikTok publish tracking record."""
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tiktok_posts (
                    account_id, export_queue_id, product_id, script_id, video_path, caption,
                    upload_mode, privacy_level, disable_comment, disable_duet, disable_stitch,
                    branded_content, your_brand, publish_id, status, response_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["account_id"],
                    data.get("export_queue_id"),
                    data.get("product_id"),
                    data.get("script_id"),
                    data["video_path"],
                    data["caption"],
                    data["upload_mode"],
                    data.get("privacy_level"),
                    int(data.get("disable_comment", False)),
                    int(data.get("disable_duet", False)),
                    int(data.get("disable_stitch", False)),
                    int(data.get("branded_content", True)),
                    int(data.get("your_brand", False)),
                    data.get("publish_id"),
                    data.get("status", "initialized"),
                    json.dumps(data.get("response_json", {})),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_tiktok_posts(self) -> list[dict[str, Any]]:
        """Return TikTok upload/post records."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    tiktok_posts.*,
                    tiktok_accounts.open_id,
                    products.product_name,
                    scripts.angle
                FROM tiktok_posts
                JOIN tiktok_accounts ON tiktok_accounts.id = tiktok_posts.account_id
                LEFT JOIN products ON products.id = tiktok_posts.product_id
                LEFT JOIN scripts ON scripts.id = tiktok_posts.script_id
                ORDER BY tiktok_posts.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_tiktok_post_status(self, post_id: int, status: str, response_json: dict[str, Any]) -> None:
        """Update a TikTok post tracking record."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tiktok_posts
                SET status = ?, response_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(response_json), utc_now(), post_id),
            )
