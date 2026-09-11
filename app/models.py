from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    queued = "queued"
    submitting = "submitting"
    running = "running"
    cancel_requested = "cancel_requested"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class JobMode(str, enum.Enum):
    generate_still = "generate_still"
    uploaded_image = "uploaded_image"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.queued.value, index=True)
    mode: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(String(32))
    duration_preset: Mapped[str] = mapped_column(String(32))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    num_frames: Mapped[int] = mapped_column(Integer)
    image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    audio_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trending_audio_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    logo_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    voice_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    campaign_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voice: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    campaign_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    kaggle_kernel_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kaggle_dataset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
