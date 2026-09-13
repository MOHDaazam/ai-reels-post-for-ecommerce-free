# Deploy on [FastAPI Cloud](https://fastapicloud.com)

This studio is a normal FastAPI app (`app.main:app`) with a background job worker. GPU rendering still runs on **Kaggle**; FastAPI Cloud hosts the **UI + queue**. Use **MySQL** on Cloud so job history survives redeploys (not ephemeral SQLite).

Official refs: [Existing project](https://fastapicloud.com/docs/getting-started/existing-project/) · [Environment variables](https://fastapicloud.com/docs/builds-and-deployments/environment-variables/) · [Install dependencies](https://fastapicloud.com/docs/builds-and-deployments/install-dependencies/)

---

## 1. Project configuration (repo)

Already in `pyproject.toml`:

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "fastapi[standard]>=0.115.0",
    # … kaggle, sqlalchemy, etc.
]

[tool.fastapi]
entrypoint = "app.main:app"
```

Optional pin for Cloud:

```bash
echo "3.12" > .python-version
```

Upload rules: `.gitignore` applies; `.fastapicloudignore` can exclude `tests/`, local `data/`, and the 12 MB sample MP4.

---

## 2. Local checks before deploy

```bash
cd video-generator-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
fastapi dev          # must start without passing a file path
pytest -q            # optional
```

Login to FastAPI Cloud (browser once):

```bash
fastapi login
# or: fastapi cloud login — use whichever your CLI version documents
```

---

## 3. Environment variables (FastAPI Cloud dashboard or CLI)

Set these on the app (**use Secrets** for credentials). Names match `.env.example` / `app/config.py`.

### Required for Kaggle (secrets)

| Variable | Secret | Description |
| --- | --- | --- |
| `KAGGLE_USERNAME` | yes | Kaggle account username |
| `KAGGLE_API_TOKEN` | yes | Kaggle API token (current format) |

Legacy `~/.kaggle/kaggle.json` is **not** uploaded; env vars are the cloud path.

### App / data (non-secret unless you prefer)

| Variable | Default | Description |
| --- | --- | --- |
| `DATA_DIR` | `./data` | Jobs, SQLite, secrets dir, profile JSON |
| `MYSQL_HOST` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | — | Same as **automatiom-napps**; auto-selected when `MYSQL_HOST` is set (creates table `jobs`). |
| `DATABASE_URL` | `sqlite:///./data/studio.db` | Optional override; ignored when `MYSQL_HOST` is set unless this is a non-default URL. |
| `APP_TIMEZONE` | machine TZ | e.g. `Asia/Kolkata` for IST labels |
| `MAX_IMAGE_BYTES` | `15728640` | Upload limit (bytes) |
| `MAX_AUDIO_BYTES` | `20971520` | Music/voice upload limit |

Do **not** set `APP_HOST` / `APP_PORT` on FastAPI Cloud unless their docs say so—the platform sets the listen port.

### Kaggle resources (same as local)

| Variable | Default | Description |
| --- | --- | --- |
| `KAGGLE_DATASET_SLUG` | `video-studio-jobs` | Private dataset for job payloads |
| `KAGGLE_KERNEL_SLUG` | `video-studio-runner` | Private GPU kernel |
| `KAGGLE_RUNNER_DIR` | `./kaggle_runner` | Runner scripts (deployed with app) |
| `STILL_MODEL` | `stabilityai/stable-diffusion-xl-base-1.0` | SDXL base on T4 |
| `STUDIO_AUTO_BOOTSTRAP` | `0` | Set `1` on Cloud so the app creates/reuses the private dataset and kernel on startup (no localhost `/setup`). |
| `STUDIO_BASIC_AUTH` | `0` | Set `1` to require HTTP Basic Auth on the whole app (UI + API). |
| `STUDIO_BASIC_AUTH_USER` | `napps` | Basic-auth username when `STUDIO_BASIC_AUTH=1`. |
| `STUDIO_BASIC_AUTH_PASSWORD` | `napps` | Basic-auth password (**use a secret** on Cloud). |

### Kaggle polling (optional tuning)

| Variable | Default |
| --- | --- |
| `KAGGLE_POLL_INITIAL_SECONDS` | `10` |
| `KAGGLE_POLL_MAX_SECONDS` | `60` |
| `KAGGLE_DATASET_READY_TIMEOUT_SECONDS` | `600` |
| `KAGGLE_UNKNOWN_STATUS_TIMEOUT_SECONDS` | `900` |

### CLI: set secrets (example)

```bash
fastapi cloud env set --secret KAGGLE_USERNAME "your-kaggle-user"
fastapi cloud env set --secret KAGGLE_API_TOKEN "your-kaggle-token"
fastapi cloud env set KAGGLE_DATASET_SLUG "video-studio-jobs"
fastapi cloud env set KAGGLE_KERNEL_SLUG "video-studio-runner"
fastapi cloud env set APP_TIMEZONE "Asia/Kolkata"
```

Or **Import** a block in the dashboard (paste from `.env`, mark secrets manually):

```env
KAGGLE_USERNAME=your-kaggle-user
KAGGLE_API_TOKEN=your-kaggle-token
KAGGLE_DATASET_SLUG=video-studio-jobs
KAGGLE_KERNEL_SLUG=video-studio-runner
DATA_DIR=./data
DATABASE_URL=sqlite:///./data/studio.db
APP_TIMEZONE=Asia/Kolkata
```

---

## 4. Kaggle bootstrap

**Hosted (recommended):** set `STUDIO_AUTO_BOOTSTRAP=1` with `KAGGLE_USERNAME` and `KAGGLE_API_TOKEN` in Cloud env. On each deploy/restart the app runs the same bootstrap as local **Bootstrap / Connect**. Check `/api/health` → **Kaggle bootstrap**.

**Local alternative:** saving credentials and **Bootstrap / Connect** on `/setup` are **localhost-only** (403 from the public Cloud URL).

**One-time on laptop** (only if you do not use auto-bootstrap):

1. Local `.env` with `KAGGLE_USERNAME` + `KAGGLE_API_TOKEN`
2. Run `kaggle-video-studio` → http://127.0.0.1:8000/setup → **Bootstrap / Connect**

That creates/reuses the private dataset and kernel on Kaggle. After that, Cloud only needs the same env vars; it does not need to call bootstrap again unless you change slugs or account.

---

## 5. Deploy

From repo root:

```bash
fastapi deploy
```

Expected: build installs `pyproject.toml` deps, imports `app.main:app`, runs with lifespan (DB init + **job worker**).

Your URL will look like: `https://<app>.fastapicloud.dev`

---

## 6. Cloud limitations (know before production)

| Topic | Behavior |
| --- | --- |
| **Setup UI** | View `/setup` works; **POST** credentials/bootstrap from the public site → **403** (by design). Use env + local bootstrap. |
| **Database** | Run `./scripts/sync-cloud-mysql-env.sh` (reads `../automatiom-napps/.env`) to wire Hostinger MySQL. Job **files** under `data/jobs/` are still ephemeral on Cloud unless you add object storage later. |
| **Security** | Public URL = anyone can queue jobs if they find the link. No built-in login. |
| **Share tunnel** | `kaggle-video-studio share` is for local use only; not needed on Cloud. |
| **Cost** | FastAPI Cloud hosting + **Kaggle GPU quota** (still $0 within Kaggle limits). |

---

## 7. Post-deploy smoke test

1. Open `https://<your-app>.fastapicloud.dev/` — studio home loads.
2. `/setup` — health shows credentials from env (username hint, not token).
3. Queue **Quick queue** or a festival reel — job appears in Recent jobs.
4. Open job detail — status moves to `running` / `completed`; download reel when done.

If jobs stay `queued`/`failed`, check Cloud logs and Kaggle token, bootstrap, and internet on the kernel.

---

## 8. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `fastapi dev` can’t find app | Confirm `[tool.fastapi] entrypoint = "app.main:app"` |
| Build missing templates/static | `package-data` includes `app/templates`, `app/static`, `app/resources` |
| 403 on Setup save | Expected on Cloud; set `KAGGLE_*` secrets |
| Kaggle “not configured” | Secrets missing or wrong; redeploy after **Save and Redeploy** |
| Jobs vanish after redeploy | Ephemeral disk; export reels or add external DB/storage later |

---

## 9. Minimal command cheat sheet

```bash
pip install -e .
fastapi login
fastapi cloud env set --secret KAGGLE_USERNAME "..."
fastapi cloud env set --secret KAGGLE_API_TOKEN "..."
# bootstrap once locally, then:
fastapi deploy
```
