from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.kaggle.client import KaggleService, KernelState


class FakeAdapter:
    def __init__(self) -> None:
        self.dataset_present = False
        self.kernel_present = False
        self.dataset_metadata: list[dict] = []
        self.kernel_metadata: list[dict] = []
        self.uploaded_files: set[str] = set()

    def authenticate(self) -> str:
        return "inferred-user"

    def validate_identity(self, username: str) -> None:
        assert username == "inferred-user"

    def dataset_exists(self, dataset_ref: str) -> bool | None:
        return self.dataset_present

    def kernel_exists(self, kernel_ref: str) -> bool | None:
        return self.kernel_present

    def dataset_status(self, dataset_ref: str) -> str:
        return "ready" if self.dataset_present else "not_found"

    def create_dataset(self, folder: Path):
        self.dataset_metadata.append(_json(folder / "dataset-metadata.json"))
        self.dataset_present = True
        return SimpleNamespace(version_number=1)

    def version_dataset(self, folder: Path, notes: str):
        self.dataset_metadata.append(_json(folder / "dataset-metadata.json"))
        self.uploaded_files = {path.name for path in folder.iterdir()}
        return SimpleNamespace(version_number=2)

    def kernel_status(self, kernel_ref: str) -> KernelState:
        return KernelState("complete" if self.kernel_present else "not_found")

    def push_kernel(self, folder: Path):
        self.kernel_metadata.append(_json(folder / "kernel-metadata.json"))
        self.kernel_present = True
        return SimpleNamespace()

    def download_kernel_outputs(self, kernel_ref: str, dest: Path) -> list[Path]:
        return []


class KaggleServiceTests(unittest.TestCase):
    def test_bootstrap_and_submit_reuse_private_resources(self) -> None:
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cfg = Settings(
                root_dir=root,
                data_dir=root / "data",
                database_url=f"sqlite:///{root / 'studio.db'}",
                kaggle_username="configured-user",
                kaggle_api_token="secret",
                kaggle_runner_dir=project / "kaggle_runner",
                kaggle_poll_initial_seconds=0,
                kaggle_poll_max_seconds=0,
            )
            adapter = FakeAdapter()
            client = KaggleService(cfg, adapter=adapter, sleep=lambda _: None)

            boot = client.bootstrap()
            self.assertEqual(boot.username, "inferred-user")
            self.assertEqual(len(adapter.dataset_metadata), 1)
            self.assertEqual(
                adapter.kernel_metadata[0]["title"], "Video Studio Runner"
            )
            self.assertTrue(adapter.kernel_metadata[0]["is_private"])
            self.assertTrue(adapter.kernel_metadata[0]["enable_gpu"])
            self.assertTrue(adapter.kernel_metadata[0]["enable_internet"])
            self.assertEqual(
                adapter.kernel_metadata[0]["machine_shape"], "NvidiaTeslaT4"
            )

            job_dir = root / "job"
            (job_dir / "input").mkdir(parents=True)
            (job_dir / "job.json").write_text('{"id":"job-1"}', encoding="utf-8")
            (job_dir / "input" / "source.png").write_bytes(b"png")
            submission = client.submit_job("job-1", job_dir)

            self.assertEqual(submission.dataset_version, "2")
            self.assertEqual(len(adapter.dataset_metadata), 2)
            self.assertEqual(len(adapter.kernel_metadata), 2)
            self.assertIn("job.json", adapter.uploaded_files)
            self.assertIn("source.png", adapter.uploaded_files)
            self.assertEqual(
                adapter.kernel_metadata[-1]["dataset_sources"],
                ["inferred-user/video-studio-jobs"],
            )


class ForbiddenStatusAdapter(FakeAdapter):
    """Kaggle answers status calls for absent resources with 403, never 404."""

    def dataset_exists(self, dataset_ref: str) -> bool | None:
        return self.dataset_present

    def kernel_exists(self, kernel_ref: str) -> bool | None:
        return self.kernel_present

    def dataset_status(self, dataset_ref: str) -> str:
        raise RuntimeError(
            "403 Client Error: Forbidden for url: "
            "https://api.kaggle.com/v1/datasets.DatasetApiService/GetDatasetStatus"
        )

    def kernel_status(self, kernel_ref: str) -> KernelState:
        raise ValueError(
            f"Cannot access kernel '{kernel_ref}' (Permission 'kernels.get' was denied)."
        )


class ForbiddenStatusTests(unittest.TestCase):
    def test_bootstrap_creates_resources_when_status_is_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            adapter = ForbiddenStatusAdapter()
            client = KaggleService(
                _config(root), adapter=adapter, sleep=lambda _: None
            )

            result = client.bootstrap()

            self.assertEqual(result.dataset_ref, "inferred-user/video-studio-jobs")
            self.assertEqual(len(adapter.dataset_metadata), 1)
            self.assertEqual(len(adapter.kernel_metadata), 1)

    def test_bootstrap_reuses_resources_that_already_exist(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            adapter = ForbiddenStatusAdapter()
            adapter.dataset_present = True
            adapter.kernel_present = True
            client = KaggleService(
                _config(Path(raw)), adapter=adapter, sleep=lambda _: None
            )

            client.bootstrap()

            self.assertEqual(adapter.dataset_metadata, [])
            self.assertEqual(adapter.kernel_metadata, [])


def _config(root: Path) -> Settings:
    return Settings(
        root_dir=root,
        data_dir=root / "data",
        database_url=f"sqlite:///{root / 'studio.db'}",
        kaggle_username="configured-user",
        kaggle_api_token="secret",
        kaggle_runner_dir=Path(__file__).resolve().parents[1] / "kaggle_runner",
        kaggle_poll_initial_seconds=0,
        kaggle_poll_max_seconds=0,
    )


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

