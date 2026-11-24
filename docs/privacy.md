# What leaves your machine

Jobsieve keeps your CV, profile, jobs, notes and drafts in files under `DATA_DIR` (`./data` by default). Nothing is sent to a Jobsieve server, because there isn't one: no accounts, no telemetry, no analytics.

Here is everything that can go out, and when.

| What | Where it goes | When | What it carries |
| --- | --- | --- | --- |
| Feed and board downloads (Remote OK, Remotive, Arbeitnow, Himalayas, Jobicy, Working Nomads, Greenhouse, Lever, Ashby, SmartRecruiters) | That service's public API | When you run a search or fetch and its cache (1 to 24 hours) is out of date | Only a request for the public list. Your IP address and a user agent naming Jobsieve and its GitHub address. Your keywords are applied on your machine, not sent. |
| Web search (the `ddg` source and `jobsieve discover`) | DuckDuckGo | When that source is selected | Your search words and the site names. |
| Pages you list or give to `watch from-page` | That website | When you add or refresh them | A normal page request with the same user agent. Public addresses only. |
| Full-page fetching for AI scoring | The job's own website, through a headless browser | When AI scoring is on and `USE_PLAYWRIGHT` is true | A page request for that job. |
| AI scoring and application drafts | The provider you chose (Groq, Google, Anthropic, OpenAI or another address you set) | Only when a key (or a model address) is set and AI is on, for jobs not already marked not eligible and not unchanged | The job text, your CV text, your keywords and a few profile lines (country, where you can work, visa need, pay floor, dealbreakers). With a local model on your own machine, none of it leaves it. |
| Alerts and digests | Your webhook, email server or Telegram | Only when you configure one | Job titles, companies, links, scores and verdicts. Not your CV. |
| Browser extension | Your own Jobsieve at `localhost` | Only when you click its button on a page | The page's title, address and text. The extension has no other network access and no content scripts. |
| MCP server | The AI agent you connected | When that agent calls a tool | Whatever the tool returns, including your CV text from `get_profile`. Use an agent you trust. |

## Things worth knowing

- **API keys** you type in the dashboard are used for that run and not saved to disk. Keys in `.env` stay on your machine.
- **The API has no login by default.** That is fine on `localhost`. If anyone else can reach it, set `API_TOKEN` (see the security section of the README).
- **Alerts** go to whatever address you configured, so use a channel you control.
- **Deleting your data** means deleting `DATA_DIR`. There is nothing else to remove.
