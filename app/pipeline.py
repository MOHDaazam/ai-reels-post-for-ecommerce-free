"""GPU generation pipeline interface. Implemented in the T4 runner task."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class GpuRunner(Protocol):
    def render(self, job_dir: Path) -> Path:
        """Produce output/result.mp4 from job.json and input assets. Returns the MP4 path."""


class UnimplementedGpuRunner:
    def render(self, job_dir: Path) -> Path:
        raise NotImplementedError("T4 FLUX → LTX runner is not implemented yet.")
