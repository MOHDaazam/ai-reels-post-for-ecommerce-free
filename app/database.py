from __future__ import annotations

from urllib.parse import quote_plus

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

_ADDITIVE_JOB_COLUMNS = {
    "logo_filename": "VARCHAR(255)",
    "voice_filename": "VARCHAR(255)",
    "campaign_json": "TEXT",
    "language": "VARCHAR(32)",
    "voice": "VARCHAR(64)",
    "strategy": "VARCHAR(32)",
    "campaign_size": "INTEGER",
    "output_manifest_json": "TEXT",
    "trending_audio_id": "VARCHAR(64)",
}


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite:"):
        return {"connect_args": {"check_same_thread": False}}
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("mysql"):
        kwargs["pool_recycle"] = 3600
    return kwargs


def create_studio_engine(url: str) -> Engine:
    return create_engine(url, future=True, **_engine_kwargs(url))


engine = create_studio_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    if dbapi_connection.__class__.__module__ != "sqlite3.dbapi2":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    migrate_job_schema(engine)
    from app.studio_store import ensure_studio_kv_table

    ensure_studio_kv_table()


def migrate_job_schema(target_engine: Engine) -> None:
    """Add nullable campaign columns without rebuilding existing job tables."""
    if not inspect(target_engine).has_table("jobs"):
        return
    existing = {column["name"] for column in inspect(target_engine).get_columns("jobs")}
    missing = {
        name: sql_type for name, sql_type in _ADDITIVE_JOB_COLUMNS.items() if name not in existing
    }
    if not missing:
        return
    with target_engine.begin() as connection:
        for name, sql_type in missing.items():
            connection.exec_driver_sql(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")


def migrate_sqlite_schema(target_engine: Engine) -> None:
    """Backward-compatible alias for tests."""
    migrate_job_schema(target_engine)


def mysql_url_from_env() -> str:
    host = settings.mysql_host
    user = settings.mysql_user
    password = settings.mysql_password
    database = settings.mysql_database
    port = settings.mysql_port
    if not all([host, user, password, database]):
        raise RuntimeError(
            "MySQL env incomplete. Set MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE "
            "or set DATABASE_URL to a mysql+pymysql://… URL."
        )
    safe_user = quote_plus(user)
    safe_password = quote_plus(password)
    return f"mysql+pymysql://{safe_user}:{safe_password}@{host}:{port}/{database}"


def get_session() -> Session:
    return SessionLocal()
