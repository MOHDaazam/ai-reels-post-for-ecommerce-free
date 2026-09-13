#!/usr/bin/env python3
"""One-shot: apply MySQL schema, copy local SQLite jobs + business profile to shared MySQL."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import init_db, migrate_job_schema
from app.models import Base, Job
from app.studio_store import ensure_studio_kv_table, kv_set


def _sqlite_path() -> Path:
    return settings.data_dir / "studio.db"


def main() -> int:
    if not settings.database_url.startswith("mysql"):
        print("MYSQL_* / DATABASE_URL must point at MySQL before running this script.", file=sys.stderr)
        return 1
    sqlite_file = _sqlite_path()
    if not sqlite_file.is_file():
        print(f"No local SQLite at {sqlite_file}; skipping job copy.")
        local_jobs: list[Job] = []
    else:
        sqlite_engine = create_engine(
            f"sqlite:///{sqlite_file.resolve()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=sqlite_engine)
        migrate_job_schema(sqlite_engine)
        with Session(sqlite_engine) as session:
            local_jobs = list(session.scalars(select(Job)).all())
            # Detach copies for insert into MySQL
            for job in local_jobs:
                session.expunge(job)

    init_db()
    mysql_engine = create_engine(settings.database_url, pool_pre_ping=True)
    imported = 0
    skipped = 0
    with Session(mysql_engine) as session:
        for job in local_jobs:
            if session.get(Job, job.id):
                skipped += 1
                continue
            session.merge(job)
            imported += 1
        session.commit()

    profile_path = settings.data_dir / "business_profile.json"
    if profile_path.is_file():
        blob = profile_path.read_text(encoding="utf-8")
        json.loads(blob)  # validate
        ensure_studio_kv_table()
        kv_set("business_profile", blob)
        print("business_profile synced to studio_kv")
    elif local_jobs:
        print("No business_profile.json (defaults will apply on Cloud until you save profile).")

    mysql_count = 0
    with mysql_engine.connect() as conn:
        from sqlalchemy import text

        mysql_count = conn.execute(text("SELECT COUNT(*) FROM jobs")).scalar_one()

    print(
        f"MySQL ready at {settings.mysql_host}/{settings.mysql_database}: "
        f"{mysql_count} jobs ({imported} imported, {skipped} already present)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
