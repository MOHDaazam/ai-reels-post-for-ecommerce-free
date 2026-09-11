from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

import app.main as main_module
from app.campaigns import plan_campaign
from app.config import Settings
from app.database import migrate_sqlite_schema
from app.jobs import CreateJobInput, JobService
from app.models import Base, Job
from app.storage import JobStorage
from app.validation import ValidationError


def test_campaign_migration_preserves_existing_job_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE jobs (
                id VARCHAR(36) PRIMARY KEY, status VARCHAR(32), mode VARCHAR(32),
                prompt TEXT, negative_prompt TEXT, seed INTEGER, aspect_ratio VARCHAR(32),
                duration_preset VARCHAR(32), width INTEGER, height INTEGER, num_frames INTEGER,
                image_filename VARCHAR(255), audio_filename VARCHAR(255),
                output_filename VARCHAR(255), error_message TEXT,
                kaggle_kernel_ref VARCHAR(255), kaggle_dataset_version VARCHAR(64),
                created_at DATETIME, updated_at DATETIME, started_at DATETIME, finished_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO jobs (id, prompt, status) VALUES ('legacy', 'Old prompt', 'completed')"
        )
    migrate_sqlite_schema(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("jobs")}
    assert {"campaign_json", "language", "voice", "campaign_size", "output_manifest_json"} <= columns
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT prompt, campaign_json FROM jobs WHERE id='legacy'")
        ).one()
    assert row == ("Old prompt", None)
    engine.dispose()


@pytest.mark.asyncio
async def test_campaign_job_creation_persists_edited_plan_and_manifest(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    storage = JobStorage(
        Settings(root_dir=tmp_path, data_dir=tmp_path / "data", database_url="sqlite://")
    )
    service = JobService(storage)
    plan = plan_campaign("pizza_onboarding", campaign_size=3).to_dict()
    plan["reels"][0]["hook"] = "Aonla's edited pizza hook"
    job = await service.create(
        session,
        CreateJobInput(
            mode="generate_still",
            prompt="",
            campaign_json=json.dumps(plan),
            language="bilingual",
            voice="female_hindi",
            strategy="credit_saver",
            campaign_size=3,
        ),
    )
    assert job.campaign_size == 3
    assert json.loads(job.campaign_json or "{}")["reels"][0]["hook"] == plan["reels"][0]["hook"]
    # The planned reels are scenes of the single delivered reel.
    assert len(json.loads(job.output_manifest_json or "{}")["outputs"]) == 1
    assert job.prompt == plan["reels"][0]["flux_prompt"]
    session.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_campaign_validation_rejects_bad_reel_transport(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    service = JobService(
        JobStorage(Settings(root_dir=tmp_path, data_dir=tmp_path / "data", database_url="sqlite://"))
    )
    plan = plan_campaign("burger_combo", campaign_size=3).to_dict()
    plan["reels"] = plan["reels"][:2]
    with pytest.raises(ValidationError, match="reel count"):
        await service.create(
            session,
            CreateJobInput(
                mode="generate_still",
                prompt="",
                campaign_json=json.dumps(plan),
                language="bilingual",
                voice="female_hindi",
                strategy="credit_saver",
                campaign_size=3,
            ),
        )
    session.close()
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda plan: plan.update(language="english"), "language does not match"),
        (lambda plan: plan["reels"][0].update(filename="../escape.mp4"), "output filenames"),
        (lambda plan: plan["reels"][0].update(captions=["x" * 501]), "at most 500"),
        (lambda plan: plan["variables"].update(vendor_name="x" * 301), "at most 300"),
    ],
)
async def test_campaign_submission_rejects_malformed_edits_before_queue(
    tmp_path: Path, mutate, message: str
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    storage = JobStorage(
        Settings(root_dir=tmp_path, data_dir=tmp_path / "data", database_url="sqlite://")
    )
    plan = plan_campaign("pizza_onboarding", campaign_size=3).to_dict()
    mutate(plan)
    with pytest.raises(ValidationError, match=message):
        await JobService(storage).create(
            session,
            CreateJobInput(
                mode="generate_still",
                prompt="",
                campaign_json=json.dumps(plan),
                language="bilingual",
                voice="female_hindi",
                strategy="credit_saver",
                campaign_size=3,
            ),
        )
    assert not list(storage.settings.jobs_dir.glob("*"))
    assert session.query(Job).count() == 0
    session.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_campaign_preview_api_and_builder_ui(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ui.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    previous_service = main_module.job_service
    main_module.job_service = JobService(
        JobStorage(Settings(root_dir=tmp_path, data_dir=tmp_path / "data", database_url="sqlite://"))
    )

    def session_override():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[main_module.db_session] = session_override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            preview = await client.post(
                "/api/campaigns/preview",
                json={
                    "template_id": "biryani_craving",
                    "language": "english",
                    "campaign_size": 4,
                    "strategy": "balanced",
                },
            )
            assert preview.status_code == 200
            assert len(preview.json()["reels"]) == 4
            page = await client.get("/")
            assert page.status_code == 200
            assert "Advanced builder" in page.text
            assert 'id="reel-preview"' in page.text
            plan = preview.json()
            created = await client.post(
                "/jobs",
                data={
                    "mode": "generate_still",
                    "campaign_json": json.dumps(plan),
                    "language": "english",
                    "voice": "female_english",
                    "strategy": "balanced",
                    "campaign_size": "4",
                    "aspect_ratio": "portrait_2_3",
                    "duration_preset": "short_25",
                },
            )
            assert created.status_code == 303
            job_id = created.headers["location"].rsplit("/", 1)[-1]
            detail = await client.get(f"/api/jobs/{job_id}")
            assert detail.status_code == 200
            assert detail.json()["campaign_size"] == 4
    finally:
        main_module.job_service = previous_service
        main_module.app.dependency_overrides.clear()
        engine.dispose()
