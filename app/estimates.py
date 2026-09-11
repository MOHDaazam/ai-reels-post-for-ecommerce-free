"""Completion estimates for queued and running Kaggle jobs.

Kaggle reports no progress or queue position, so the studio predicts from its
own history and falls back to the cost model of the render strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.localtime import display as local_display
from app.localtime import now_local, to_local
from app.models import Job, JobStatus

# Session startup, dependency install, and the first weight download dominate a
# cold run; these are deliberately conservative.
SESSION_OVERHEAD = timedelta(minutes=9)
PER_ANIMATION = timedelta(minutes=7)
PER_STILL = timedelta(minutes=2)
POST_PRODUCTION_PER_REEL = timedelta(seconds=40)
# The runner delivers one reel, and the credit mode buys shots for it. Keep
# this in step with STRATEGY_SHOT_COUNTS in kaggle_runner/run.py.
STRATEGY_SHOT_COUNTS = {"credit_saver": 3, "balanced": 4, "unique_visuals": 6}
HISTORY_LIMIT = 10
# Kaggle stops a GPU session at 12 hours, so no genuine run lasts longer.
MAX_CREDIBLE_RUN = timedelta(hours=12)


@dataclass(frozen=True)
class Estimate:
    duration: timedelta
    finish_at: datetime
    basis: str

    @property
    def minutes(self) -> int:
        return max(1, round(self.duration.total_seconds() / 60))

    def describe(self) -> str:
        return (
            f"Estimated completion around {local_display(self.finish_at)} "
            f"(about {self.minutes} min, {self.basis})."
        )


def planned_shots(strategy: str | None, campaign_size: int | None) -> int:
    if not campaign_size:
        return 1
    return STRATEGY_SHOT_COUNTS.get(strategy or "", 3)


def modelled_duration(job: Job) -> timedelta:
    shots = planned_shots(job.strategy, job.campaign_size)
    stills = shots if job.mode == "generate_still" else 0
    return (
        SESSION_OVERHEAD
        + PER_ANIMATION * shots
        + PER_STILL * stills
        + POST_PRODUCTION_PER_REEL
    )


def _observed_duration(session: Session, job: Job) -> tuple[timedelta, int] | None:
    """Average recent runs that used the same strategy and campaign size."""
    stmt = (
        select(Job)
        .where(
            Job.status == JobStatus.completed.value,
            Job.strategy == job.strategy,
            Job.campaign_size == job.campaign_size,
            Job.started_at.is_not(None),
            Job.finished_at.is_not(None),
        )
        .order_by(Job.finished_at.desc())
        .limit(HISTORY_LIMIT)
    )
    samples = [
        (item.finished_at - item.started_at).total_seconds()
        for item in session.scalars(stmt)
        if item.started_at and item.finished_at
    ]
    # A job recovered across app downtime keeps its original started_at, so its
    # wall clock can exceed anything Kaggle could have run and predicts nothing.
    usable = [value for value in samples if 0 < value <= MAX_CREDIBLE_RUN.total_seconds()]
    if not usable:
        return None
    return timedelta(seconds=sum(usable) / len(usable)), len(usable)


def estimate(session: Session, job: Job, *, started_at: datetime | None = None) -> Estimate:
    observed = _observed_duration(session, job)
    if observed is not None:
        duration, count = observed
        basis = (
            "average of your last similar run"
            if count == 1
            else f"average of your last {count} similar runs"
        )
    else:
        duration = modelled_duration(job)
        basis = "first run of this shape, so weights still need downloading"
    anchor = to_local(started_at) if started_at else now_local()
    return Estimate(duration=duration, finish_at=anchor + duration, basis=basis)
