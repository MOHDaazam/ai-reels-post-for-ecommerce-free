from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.localtime as localtime
from app.estimates import estimate, modelled_duration, planned_shots
from app.models import Base, Job, JobStatus


@pytest.fixture
def kolkata(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(localtime, "local_zone", lambda: ZoneInfo("Asia/Kolkata"))


def test_display_converts_utc_to_local(kolkata) -> None:
    moment = datetime(2026, 9, 10, 21, 51, 33, tzinfo=timezone.utc)

    assert localtime.display(moment) == "2026-09-11 03:21"


def test_naive_database_values_are_treated_as_utc(kolkata) -> None:
    assert localtime.display(datetime(2026, 9, 10, 21, 51, 33)) == "2026-09-11 03:21"


def test_parses_both_legacy_utc_and_local_log_stamps(kolkata) -> None:
    legacy = localtime.parse_log_stamp("[2026-09-10 21:51:33 UTC] kernel running")
    assert legacy == datetime(2026, 9, 10, 21, 51, 33, tzinfo=timezone.utc)

    local = localtime.parse_log_stamp("[2026-09-11 03:21:33 IST] kernel running")
    assert local is not None
    assert local.utcoffset() == timedelta(hours=5, minutes=30)
    assert local == legacy

    assert localtime.parse_log_stamp("no timestamp here") is None


def test_new_log_lines_are_written_in_local_time(kolkata) -> None:
    written = localtime.stamp(datetime(2026, 9, 10, 21, 51, 33, tzinfo=timezone.utc))

    assert written.startswith("2026-09-11 03:21:33")
    assert "UTC" not in written


@pytest.mark.parametrize(
    ("strategy", "size", "expected"),
    [
        ("credit_saver", 5, 3),
        ("balanced", 3, 4),
        ("unique_visuals", 4, 6),
        # A legacy single-image job has no campaign, so it animates one shot.
        ("credit_saver", None, 1),
    ],
)
def test_planned_shots_follow_the_credit_mode(strategy, size, expected) -> None:
    assert planned_shots(strategy, size) == expected


def test_estimate_prefers_history_over_the_cost_model(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'estimates.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    started = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)

    def make(job_id: str, status: str, minutes: int | None) -> Job:
        return Job(
            id=job_id,
            status=status,
            mode="generate_still",
            prompt="p",
            negative_prompt="",
            aspect_ratio="square",
            duration_preset="short_25",
            width=512,
            height=512,
            num_frames=25,
            strategy="credit_saver",
            campaign_size=3,
            started_at=started if minutes else None,
            finished_at=started + timedelta(minutes=minutes) if minutes else None,
        )

    with factory() as session:
        pending = make("a" * 8, JobStatus.queued.value, None)
        session.add_all(
            [
                pending,
                make("b" * 8, JobStatus.completed.value, 20),
                make("c" * 8, JobStatus.completed.value, 30),
            ]
        )
        session.commit()

        prediction = estimate(session, pending, started_at=started)

        assert prediction.minutes == 25
        assert "similar runs" in prediction.basis
        assert prediction.finish_at == localtime.to_local(started + timedelta(minutes=25))

    with factory() as session:
        # A run recovered across app downtime keeps its original started_at.
        session.add(make("e" * 8, JobStatus.completed.value, 1005))
        session.commit()
        stale = session.get(Job, "a" * 8)
        assert stale is not None

        prediction = estimate(session, stale, started_at=started)

        assert prediction.minutes == 25
        assert "last 2 similar runs" in prediction.basis

    with factory() as session:
        fresh = make("d" * 8, JobStatus.queued.value, None)
        fresh.strategy = "unique_visuals"
        session.add(fresh)
        session.commit()

        prediction = estimate(session, fresh, started_at=started)

        assert prediction.duration == modelled_duration(fresh)
        assert "first run" in prediction.basis
        assert "Estimated completion around" in prediction.describe()

    engine.dispose()
