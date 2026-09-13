"""Optional automatic Kaggle bootstrap for hosted deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.kaggle.client import BootstrapResult

BootstrapStatus = Literal["skipped", "pending", "ready", "failed"]


@dataclass
class BootstrapRuntime:
    status: BootstrapStatus = "skipped"
    detail: str = "Automatic bootstrap is disabled."
    result: BootstrapResult | None = None


_runtime = BootstrapRuntime()


def bootstrap_runtime() -> BootstrapRuntime:
    return _runtime


def set_bootstrap_runtime(state: BootstrapRuntime) -> None:
    global _runtime
    _runtime = state
