# Jobsieve

![CI](https://github.com/firaslamouchi21/Job-Scraper02/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-Apache--2.0-blue)
![Docker](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED?logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)

Self-hosted job search that scores every listing against your CV, AI optional. Paste your CV and a few keywords, hit Start, and it searches job boards and ranks results 0-10 by how well they match you, instead of you skimming ten tabs every morning.

Built it for myself while job hunting. It found the job. Now I'm making it good enough for other people to use too.

![Jobsieve dashboard](docs/screenshots/dashboard.png)

## Why this one

- **AI scoring is optional.** Bring a Groq, Anthropic, or Gemini key for AI-scored relevance, or run free in Lite Mode (keyword and CV-term matching, no key, no signup).
- **Your data stays yours.** Everything lands in a local SQLite file you own. Nothing leaves your machine unless you configure an AI key or a notification webhook.
- **Run it your way.** Docker Compose gives you a dashboard, a REST API and a database in one command. Or `pip install jobsieve` and use the CLI, no server needed.
- **Scriptable.** Everything the UI does is also a REST endpoint and a CLI command.

## What you get

- Paste your CV and keywords into the web UI
- Search the web or pull from Remote OK, Remotive and Arbeitnow
- Every job scored 0-10 (AI, or Lite Mode)
- Re-running updates scores instead of ignoring repeats, and the dashboard shows the latest run by default
- Pause, resume, or restart runs from the dashboard
- Export results as JSON or CSV
- Optional webhook and email alerts for high-scoring jobs

![Sidebar: sites, keywords, CV, and run controls](docs/screenshots/controls.png)

## How to run it

### Option A: Docker (full stack)

You need Docker Engine 24+ or Docker Desktop, and about 2 GB of RAM (4 GB recommended).

```bash
cp .env.example .env
docker compose up --build
```

- **scraper** (REST API) at `http://localhost:8000`
- **UI** at `http://localhost:8501`

Edit `.env` first if you have AI keys. Without any, Lite Mode works fine. The optional n8n automation engine lives under a separate profile: `docker compose --profile automation up`.

Then open `http://localhost:8501`, paste your CV, add keywords such as `senior python remote`, pick a provider (or stay in Lite Mode) and hit Start.

### Option B: Python package

The base install is small (requests, BeautifulSoup, ddgs) and gives you the CLI and all sources. Add extras for the rest:

| Install | Adds |
| --- | --- |
| `pip install jobsieve` | CLI, sources, SQLite, keyword scoring |
| `pip install "jobsieve[ai]"` | AI scoring with Anthropic (Groq and Gemini need no extra) |
| `pip install "jobsieve[api]"` | REST API (FastAPI, uvicorn) |
| `pip install "jobsieve[ui]"` | Streamlit dashboard |
| `pip install "jobsieve[browser]"` | Playwright, for fetching full pages |
| `pip install "jobsieve[all]"` | everything above |

```bash
pip install jobsieve
jobsieve run --lite --sources remoteok remotive arbeitnow --keywords "python developer" --cv-file my_cv.txt
jobsieve export --format csv --out jobs.csv
```

Useful flags for `run`: `--sources` (see below), `--sites` (domains for web search), `--keywords`, `--cv-file`, `--lite`, `--provider groq|anthropic|gemini`. Keys come from the environment (`GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) or flags. If another run is already in progress the command says so and exits with code 1.

With the extras installed:

```bash
python -m uvicorn jobsieve.api:api --port 8000
streamlit run "$(python -c 'import jobsieve.app as a; print(a.__file__)')"
```

Fetching full job pages with a headless browser needs `[browser]` and `playwright install chromium`. Without it, set `USE_PLAYWRIGHT=false` and the scraper uses plain HTTP requests.

Works on Python 3.10 to 3.12. Tested on Linux and in Docker; macOS and Windows have not been tested natively, so use Docker there.

### Fetch listings without any server (for scripts and AI agents)

```bash
jobsieve fetch --source remoteok remotive arbeitnow --keyword python "remote backend" --limit 20 --json
```

This downloads the feeds (cached on disk, see below), keeps listings matching your keywords, saves them to SQLite and prints a JSON array on stdout. Each record has `title`, `company`, `location`, `remote`, `salary`, `posted_at`, `url`, `description`, `source`, `attribution`, `job_hash` and `is_new`. Messages and errors go to stderr, so stdout is always valid JSON. Add `--no-store` to skip the database. Exit code: 0 on success (even if one source failed; its error is on stderr), 2 for an unknown source, 3 if every source failed. `jobsieve sources` lists the available sources. A caller that scores listings itself can write the result back with `jobsieve.db.set_score(job_hash, score, reasoning)`.

### Save a job from any website (browser extension)

The `extension/` folder holds a small browser extension. Open a job page on any site, click the button, and the job is saved to your own Jobsieve with the same eligibility check. It reads a page only when you click, sends it only to your local Jobsieve, and never fetches pages itself. See [extension/README.md](extension/README.md) for what it can read and how to install it.

## How scoring works

**AI mode.** When a key is set for the selected provider (in the sidebar, the CLI, or `.env`) the listing text, your CV and your keywords go to that provider and it returns a score and a short reason. Models are configurable with `GROQ_MODEL`, `GEMINI_MODEL` and `ANTHROPIC_MODEL`; check each provider's docs for current names, because providers retire models.

**If AI scoring fails** (bad key, retired model, rate limit, unparseable reply) the listing falls back to the Lite score, the reasoning starts with `ai_failed: <reason>`, the failure is logged, and the dashboard shows a warning with the count. A failed re-run never overwrites a score that AI already gave.

**Lite Mode.** Free and offline. The score is the number of your keywords found in the listing, plus up to 3 bonus points when several distinct terms from your CV (skills, tools) also appear in it, capped at 10. The reasoning shows `matched_keywords=N cv_terms=M`. Limits: it is word matching, not understanding, so it cannot judge seniority, location or context, and it only sees the search result snippet unless full-page fetching is on.

## Sources

| Source | What it is | Notes |
| --- | --- | --- |
| `ddg` (default) | DuckDuckGo `site:` search for each site and keyword | Gives title, link and a snippet. With no sites it searches a built-in list of job boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, We Work Remotely, RemoteOK, Wellfound); override with `config/sites.txt` or `DEFAULT_SITES`. |
| `remoteok` | [Remote OK](https://remoteok.com) public API | Full descriptions, remote jobs |
| `remotive` | [Remotive](https://remotive.com) public API | Full descriptions, remote jobs. Remotive asks for at most 4 requests a day, so its feed is cached for 6 hours. |
| `arbeitnow` | [Arbeitnow](https://www.arbeitnow.com) public API | Full descriptions, mostly Europe, remote flag |

Feed sources are downloaded whole, cached in `DATA_DIR/cache` (1 hour, Remotive 6 hours, change with `SOURCE_CACHE_TTL_SECONDS`) and filtered by your keywords on your machine, so repeated runs make few requests. If a feed is unreachable the last cached copy is used. A source that fails is reported and skipped; the run continues. Select sources with `--sources`, the dashboard's Sources box, or `"sources": ["remoteok", "remotive"]` in `POST /run`.

**Attribution and terms.** Remote OK and Remotive require a link back and naming them as the source; every listing keeps its `source` and original URL and the dashboard shows "via Remote OK" and so on. Remotive also forbids submitting its jobs to other job sites. This tool stores listings locally for your own search, so do not republish them. LinkedIn and Indeed are not scraped.

Copy the `config/*.txt.example` files to set default sites, keywords and CV.

## Environment variables

| Variable | What it does | Default |
| --- | --- | --- |
| `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | AI scoring keys | empty |
| `GROQ_MODEL` | Groq model | `llama-3.3-70b-versatile` |
| `GEMINI_MODEL` | Gemini model | `gemini-3.6-flash` |
| `ANTHROPIC_MODEL` | Claude model | `claude-haiku-5-5` |
| `API_TOKEN` | If set, every API endpoint except `/health` requires `Authorization: Bearer <token>` | empty (open) |
| `DATA_DIR` | Where SQLite, status and logs live | `./data` |
| `CONFIG_DIR` | Where `sites.txt`, `keywords.txt`, `cv.txt` are read from | `./config` |
| `SCRAPER_URL` | API address the UI talks to | `http://localhost:8000` |
| `DEFAULT_SITES` | Comma-separated domains used when no sites are given | built-in list |
| `SOURCE_CACHE_TTL_SECONDS` | Override how long downloaded feeds are cached | per source (1h, Remotive 6h) |
| `SOURCE_FETCH_LIMIT` | Maximum listings taken from each feed per run | `100` |
| `REQUEST_DELAY_SECONDS` | Politeness delay between requests | `2.0` |
| `RETRY_MAX_ATTEMPTS` | Retries for a failed search or fetch | `5` |
| `RETRY_BASE_SECONDS` / `RETRY_MAX_SECONDS` | Retry backoff start and ceiling | `2.0` / `16` |
| `USE_PLAYWRIGHT` | Fetch full pages with a headless browser | `true` |
| `LOCK_STALE_SECONDS` | A run with no heartbeat for this long is treated as dead | `900` |
| `MIN_SCORE_NOTIFY` | Minimum score (0-10) that triggers an alert | `7` |
| `NOTIFICATION_WEBHOOK` | Webhook URL for alerts | empty |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USER`, `EMAIL_PASS`, `EMAIL_TO` | SMTP settings for email alerts (port default `587`) | empty |

`.env.example` lists the same variables with the same defaults.

## API for power users

The scraper exposes a FastAPI server. The UI talks to it, and you can too. If you set `API_TOKEN`, add `-H "Authorization: Bearer $API_TOKEN"` to every call except `/health`.

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"provider":"groq","lite_mode":true,"sources":["ddg","remoteok"],"sites":["example.com"],"keywords":["python"],"cv_text":"developer"}'

curl http://localhost:8000/status
curl "http://localhost:8000/jobs?limit=50&run=latest"
curl http://localhost:8000/export/csv > jobs.csv
curl -X POST http://localhost:8000/pause
curl -X POST http://localhost:8000/resume
curl -X POST http://localhost:8000/stop
```

`/jobs` and the export endpoints return the all-time top results by default; add `run=latest` for just the most recent run. `GET /config` reports which provider keys the server has (never the keys themselves). A run that crashed is detected: the lock expires, `/status` reports `interrupted`, and the next `/run` starts normally.

## Security: read this before putting it on the internet

By default the API has **no authentication**, which is fine on `localhost`. If it is reachable from anywhere else, anyone who can reach it can start runs that use your AI keys and read your results.

- Set a long random `API_TOKEN`.
- `render.yaml` and `railway.json` deploy one service (the combined image) with the API bound to `127.0.0.1`, so only the UI can reach it. The Streamlit UI itself has no login, so put it behind your platform's access controls or a proxy with auth. These two files are untested on the real platforms; check them on your own account.
- Never commit `.env`. It is gitignored. If a key was ever pushed, rotate it.
- Report vulnerabilities privately, see [SECURITY.md](SECURITY.md).

## Makefile shortcuts

```bash
make build
make up
make down
make logs
```

## Contributing

Issues and PRs are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). If you use this and hit something, opening an issue is the single most useful thing you can do; this is a solo project so far and every report helps.

If you find it useful, a star helps other people find it too.
