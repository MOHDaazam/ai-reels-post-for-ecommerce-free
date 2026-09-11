from __future__ import annotations

from sqlalchemy import create_engine, event, inspect
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


def _sqlite_url() -> str:
    path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


engine = create_engine(
    _sqlite_url(),
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema(engine)


def migrate_sqlite_schema(target_engine: Engine) -> None:
    """Add nullable campaign columns without rebuilding existing SQLite tables."""
    if target_engine.dialect.name != "sqlite" or not inspect(target_engine).has_table("jobs"):
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


def get_session() -> Session:
    return SessionLocal()
