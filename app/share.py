"""Publish the local studio on a free Cloudflare quick tunnel.

A quick tunnel needs no Cloudflare account, no dashboard, and no DNS: the
`cloudflared` binary dials out and prints a public HTTPS URL. That makes it the
only genuinely free, CLI-only way to reach this studio from a phone, so it is
the supported sharing path.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import settings

INSTALL_HINT = (
    "Install it with:\n"
    "  mkdir -p ~/.local/bin && curl -fsSL -o ~/.local/bin/cloudflared \\\n"
    "    https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-amd64 \\\n"
    "  && chmod +x ~/.local/bin/cloudflared"
)
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def cloudflared_path() -> Path | None:
    """Find cloudflared on PATH or in the per-user bin directory."""
    found = shutil.which("cloudflared")
    if found:
        return Path(found)
    local = Path.home() / ".local" / "bin" / "cloudflared"
    return local if local.is_file() else None


def extract_tunnel_url(text: str) -> str | None:
    match = TUNNEL_URL_RE.search(text)
    return match.group(0) if match else None


def preflight() -> list[str]:
    """Report every reason sharing would be impossible."""
    if cloudflared_path() is None:
        return [f"cloudflared was not found. {INSTALL_HINT}"]
    return []


def run_quick_tunnel() -> int:
    """Run cloudflared in the foreground, surfacing the public URL first."""
    problems = preflight()
    if problems:
        for problem in problems:
            print(f"Cannot share: {problem}", file=sys.stderr)
        return 2
    binary = cloudflared_path()
    assert binary is not None
    target = f"http://127.0.0.1:{settings.port}"
    print(f"Publishing {target} on a Cloudflare quick tunnel. Ctrl+C stops it.")
    process = subprocess.Popen(
        [str(binary), "tunnel", "--no-autoupdate", "--url", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    announced = False
    try:
        assert process.stdout is not None
        for line in process.stdout:
            url = None if announced else extract_tunnel_url(line)
            if url:
                announced = True
                print(f"\nStudio is live at {url}")
                print("Open it with no login. The URL changes every time you restart the tunnel.")
                print("Kaggle credential changes stay localhost-only.\n")
            else:
                print(line.rstrip(), flush=True)
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()
