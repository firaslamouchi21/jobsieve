# Changelog

## 2.0.1 (2026-11-24)

### Fixed

- Application drafts (`jobsieve tailor`) had literal `\n` text instead of line breaks, in the Markdown and in the prompt sent to the model.
- Saving the profile in the dashboard erased languages, sites and sources set elsewhere.
- Re-checking saved jobs after a profile change was slow enough to time out with a few thousand jobs. It is now many times faster.
- The README's links and images work on PyPI.

### Changed

- **New dashboard design:** separate Jobs, Search, Profile and Watchlist pages, compact job cards with verdict badges, paging, notes, and a phone layout. It talks only to the API, so it no longer needs the database folder. Listing text is shown as plain text. "Restart Run" and the "All except hidden" view are gone. Needs Streamlit 1.56 or newer.
- **Eligibility:** a job in a country where you cannot work or relocate, with no stated work mode and no mention of remote work, is now not eligible instead of unclear.
- Removed `render.yaml` and `railway.json`. They were never tested, and Jobsieve is meant to run on your own machine.
- New endpoints `GET /summary` and `POST /visit`.

## 2.0.0 (2026-11-24)

Version 0.4.0 was prepared but never released; its changes are part of 2.0.0.

### Upgrading from 0.3.0

- `pip install jobsieve` (a new package name; `job-scraper02` stays at 0.3.0). Add extras for what you use, for example `pip install "jobsieve[api,ui]"` or `"jobsieve[all]"`.
- Your database upgrades itself on first start (schema v8) and keeps every row. Listings that point to the same address are merged, and nothing else is deleted.
- Replace `job_scraper` with `jobsieve` in any imports (the old import name no longer exists) and use `jobsieve.api:api` in start commands (`jobsieve.scraper:api` still works). The `job-scraper` command still works as an alias.
- The old `last_check.txt` marker is ignored: the first alert after upgrading may repeat recent matches once.
- Docker users: image names follow the repository name once it is renamed.

### Breaking changes

- **Renamed to Jobsieve.** The PyPI package is `jobsieve` (the old `job-scraper02` stops at 0.3.0), the Python import is `jobsieve` (was `job_scraper`) and the command is `jobsieve`; `job-scraper` still works as an alias. Start commands must now use `jobsieve.api:api`.
- **Licence changed from MIT to Apache 2.0.** Versions up to 0.3.0 remain MIT.

- **The base install is now light.** `pip install jobsieve` no longer installs Streamlit, FastAPI, uvicorn, Playwright or the Anthropic SDK. Install what you need with extras: `[ui]`, `[api]`, `[browser]`, `[ai]`, or `[all]` for the old behaviour.
- The API app moved to `jobsieve.api:api`. `jobsieve.scraper:api` still works, so existing start commands keep running.
- Jobs are now identified by their normalized URL, so the same listing found through different searches is one row. The database migrates automatically and merges existing duplicates.
- `requirements.txt` is gone; use `pip install ".[all,dev]"`.
- Log events now go to stderr instead of stdout.

### Added

- **Browser capture extension** (`extension/`) and `POST /ingest`: save the job page you are viewing, on any site, to your local Jobsieve with an eligibility verdict. Reads a page only on click.
- **Profile and eligibility:** a saved profile (country, work rights, visa needs, relocation, salary floor, dealbreakers) and a verdict of Eligible, Unclear or Not eligible with reasons for every job, in the dashboard, API and CLI.
- **Sources:** one interface and one normalized record (title, company, location, remote, salary, posted date, closing date, URL, description, source). DuckDuckGo search, Remote OK, Remotive, Arbeitnow, Himalayas, Jobicy and Working Nomads, cached on disk and filtered on your machine. See [docs/sources.md](docs/sources.md).
- **Company career boards:** Greenhouse, Lever, Ashby and SmartRecruiters, read from a watchlist (`jobsieve watch add|list|remove|check|starter`, API, dashboard tab). Companies found by web search are added as "discovered" (`jobsieve discover`). `jobsieve watch from-page` finds the board behind a careers page. A `gulf-mena` starter list.
- **Polite page reader:** the `web` source reads schema.org job data from pages you list (`jobsieve watch add-page`). robots.txt respected, slow, same site, public addresses only, stops at a bot check, refuses LinkedIn, Indeed and Glassdoor.
- **Duplicates:** the same job from several sources is shown once with the others listed ("also on").
- **Freshness:** age, repost count, closing date, and "closed" when a watched board drops a job. Jobs are ordered eligible first, then score, then newest.
- **Tracking:** statuses, notes and history. `jobsieve mark|jobs`, `PATCH /jobs/{hash}`, `GET /stats`, dashboard views and buttons. Alerts skip applied, hidden, duplicate, closed and not-eligible jobs. CSV cells are made spreadsheet-safe.
- **Schedule and digest:** `RUN_EVERY_HOURS`, `jobsieve schedule`, `jobsieve run` with no flags uses your profile, watchlist and listed pages. Digests to Slack, Discord, Telegram, email or webhook with eligibility labels (`jobsieve digest`), and a "new since your last visit" strip.
- **AI with any model:** provider `openai` for any OpenAI-compatible server or local model. Cost controls (skip ineligible and unchanged jobs, `AI_MAX_PER_RUN`). Per-job CV suggestions and a cover letter draft (`jobsieve tailor`, dashboard box, `POST /jobs/{hash}/tailor`) with a check for numbers not in your CV.
- **AI agents:** an MCP server (`jobsieve mcp`, extra `[mcp]`) and a ready-made agent skill in `skills/jobsieve/`.
- **Easy start:** `jobsieve start` (API and dashboard together, no Docker), `--demo` mode, and a first-run guide in the dashboard.
- Documentation: [docs/eligibility.md](docs/eligibility.md) (how verdicts are made and how accurate they are) and [docs/privacy.md](docs/privacy.md) (what leaves your machine).
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
