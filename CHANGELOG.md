# Changelog

## 2.0.0 (unreleased)

Version 0.4.0 was prepared but never released; its changes are part of 2.0.0.

### Breaking changes

- **Renamed to Jobsieve.** The PyPI package is `jobsieve` (the old `job-scraper02` stops at 0.3.0), the Python import is `jobsieve` (was `job_scraper`) and the command is `jobsieve`; `job-scraper` still works as an alias. Start commands must now use `jobsieve.api:api`.
- **Licence changed from MIT to Apache 2.0.** Versions up to 0.3.0 remain MIT.

- **The base install is now light.** `pip install jobsieve` no longer installs Streamlit, FastAPI, uvicorn, Playwright or the Anthropic SDK. Install what you need with extras: `[ui]`, `[api]`, `[browser]`, `[ai]`, or `[all]` for the old behaviour.
- The API app moved to `jobsieve.api:api`. `jobsieve.scraper:api` still works, so existing start commands keep running.
- Jobs are now identified by their normalized URL, so the same listing found through different searches is one row. The database migrates automatically and merges existing duplicates.
- `requirements.txt` is gone; use `pip install ".[all,dev]"`.
- Log events now go to stderr instead of stdout.

### Added

- `jobsieve.sources`: one interface and one normalized record (title, company, location, remote, salary, posted date, URL, description, source). Sources: DuckDuckGo search, Remote OK, Remotive, Arbeitnow. Feeds are cached on disk and filtered locally.
- `jobsieve fetch --source ... --keyword ... --json` fetches and stores listings with no API server, for scripts and AI agents. `jobsieve sources` lists sources. `jobsieve.db.set_score` writes a score and reasons back.
- `sources` option in `POST /run`, `jobsieve run --sources`, and a Sources picker in the dashboard.
- Optional `API_TOKEN` (bearer token) for the REST API, and `GET /config`.
- Lite Mode counts terms from your CV (up to 3 bonus points).
- `GROQ_MODEL`, `GEMINI_MODEL`, `ANTHROPIC_MODEL`, `DEFAULT_SITES`, `LOCK_STALE_SECONDS`, `SOURCE_CACHE_TTL_SECONDS`, `SOURCE_FETCH_LIMIT`.
- `jobsieve run` flags `--sites`, `--keywords`, `--cv-file`; `/jobs` and the exports accept `run=latest`; the dashboard shows the latest run by default.
- Python 3.10 and 3.12 support.

### Fixed

- AI scoring was broken for all three providers: the default Groq and Gemini models are retired and the Anthropic call was rejected by current models. Defaults are updated and configurable.
- AI errors no longer fall back silently: the reasoning starts with `ai_failed: <reason>`, the failure is logged, counted in the run status and shown in the dashboard. A failed re-run never overwrites a real AI score.
- Re-running now updates scores instead of ignoring repeat listings.
- A crashed run no longer blocks later runs: the lock holds a PID and heartbeat and expires, startup clears it, and `/status` no longer reports a dead run as running.
- The dashboard crashed when progress went above 100%.
- Keys set in `.env` were ignored by the dashboard, which forced Lite Mode.
- Alert, retry and model settings were never passed to the Docker containers.
- Webhook HTTP errors counted as success and lost alerts.
- `jobsieve run` exited 0 silently when another run held the lock.
- `render.yaml` and `railway.json` did not produce a working deployment; both now deploy the combined image with the API bound to localhost.
- `.dockerignore` added so `.env` and local data cannot end up in an image.
- Search moved from the renamed `duckduckgo-search` package to `ddgs`; with no sites configured it now searches a default job-board list instead of the open web.
- Eight unused dependencies removed.
