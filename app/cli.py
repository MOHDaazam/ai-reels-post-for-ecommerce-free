from __future__ import annotations

import argparse

from app.credentials import CredentialStore
from app.database import init_db
from app.kaggle.client import CredentialState, KaggleService


def main() -> None:
    parser = argparse.ArgumentParser(prog="kaggle-video-studio")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="start the local FastAPI studio")
    subparsers.add_parser(
        "bootstrap",
        help="validate credentials and create/reuse private Kaggle resources",
    )
    subparsers.add_parser(
        "share",
        help="publish the running studio on a free Cloudflare quick tunnel",
    )
    args = parser.parse_args()
    if args.command in {None, "serve"}:
        from app.main import run

        run()
        return
    if args.command == "share":
        from app.share import run_quick_tunnel

        raise SystemExit(run_quick_tunnel())

    init_db()
    # Credentials saved through the setup page live in the project store, so the
    # CLI has to load them the same way the running app does.
    store = CredentialStore()
    store.configure_environment()
    client = KaggleService(store.runtime_settings())
    status = client.credential_status(validate=True)
    if status.state is not CredentialState.present:
        parser.error(status.detail)
    result = client.bootstrap()
    print(f"Kaggle user: {result.username}")
    print(f"Private dataset: {result.dataset_ref}")
    print(f"Private kernel: {result.kernel_ref}")

