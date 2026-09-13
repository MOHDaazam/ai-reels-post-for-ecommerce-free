#!/usr/bin/env bash
# Point AI Reels Cloud at persistent Hostinger MySQL (reads automatiom-napps/.env).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${STUDIO_MYSQL_ENV:-$ROOT/../automatiom-napps/.env}"
APP_ID="${FASTAPI_CLOUD_APP_ID:-ffff18b6-5846-4bfb-b81d-935652e3e239}"
FASTAPI="${FASTAPI_CLI:-$ROOT/.venv/bin/fastapi}"

if [[ ! -f "$SOURCE" ]]; then
  echo "Missing $SOURCE — set STUDIO_MYSQL_ENV or copy MYSQL_* into Cloud env." >&2
  exit 1
fi
if [[ ! -x "$FASTAPI" ]]; then
  FASTAPI="$(command -v fastapi || true)"
fi
if [[ -z "$FASTAPI" ]]; then
  echo "fastapi CLI not found" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$SOURCE"
set +a

for key in MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_DATABASE; do
  val="${!key:-}"
  if [[ -z "$val" ]]; then
    echo "Missing $key in $SOURCE" >&2
    exit 1
  fi
  "$FASTAPI" cloud env set "$key" "$val" --app-id "$APP_ID"
done
"$FASTAPI" cloud env set --secret MYSQL_PASSWORD "${MYSQL_PASSWORD}" --app-id "$APP_ID"
"$FASTAPI" cloud env unset DATABASE_URL --app-id "$APP_ID" 2>/dev/null || true
"$FASTAPI" cloud env unset STUDIO_USE_MYSQL --app-id "$APP_ID" 2>/dev/null || true
echo "Cloud app $APP_ID will use MySQL at ${MYSQL_HOST}/${MYSQL_DATABASE} (table: jobs)."
