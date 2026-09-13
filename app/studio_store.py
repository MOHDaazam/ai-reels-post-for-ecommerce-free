"""Key-value settings on shared MySQL (business profile, etc.)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from app.database import engine
from app.models import utcnow


def ensure_studio_kv_table() -> None:
    if engine.dialect.name != "mysql":
        return
    ddl = """
    CREATE TABLE IF NOT EXISTS studio_kv (
        kv_key VARCHAR(64) NOT NULL PRIMARY KEY,
        kv_value MEDIUMTEXT NOT NULL,
        updated_at DATETIME(6) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))


def kv_get(key: str) -> str | None:
    if engine.dialect.name != "mysql":
        return None
    ensure_studio_kv_table()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT kv_value FROM studio_kv WHERE kv_key = :key"),
            {"key": key},
        ).first()
    return str(row[0]) if row else None


def kv_set(key: str, value: str) -> None:
    if engine.dialect.name != "mysql":
        return
    ensure_studio_kv_table()
    now = utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO studio_kv (kv_key, kv_value, updated_at)
                VALUES (:key, :value, :updated_at)
                ON DUPLICATE KEY UPDATE kv_value = VALUES(kv_value), updated_at = VALUES(updated_at)
                """
            ),
            {"key": key, "value": value, "updated_at": now},
        )
