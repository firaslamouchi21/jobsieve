---
name: jobsieve
description: Search for jobs, check which ones the user can actually apply for from where they live, and track applications, using the user's local Jobsieve. Use when the user asks to find, rank, shortlist or track jobs, or to draft a CV tweak or cover letter for a listing.
---

# Jobsieve

Jobsieve runs on the user's machine and keeps everything in a local SQLite file. You reach it through its MCP server (`jobsieve mcp`, installed with `pip install "jobsieve[mcp]"`). If the tools are missing, tell the user how to add the server instead of guessing.

## Flow

1. **Profile first.** Call `get_profile`. If `exists` is false, ask the user for their country, where they can work without sponsorship, work modes, salary floor and keywords before searching. Never invent these.
2. **Search.** `search_jobs` with the user's keywords. It saves listings and checks each against the profile. Use `watch_company` for employers the user names (Greenhouse, Lever, Ashby or SmartRecruiters board names).
3. **Shortlist.** `list_jobs` returns the best first: eligible, then unclear, then the rest. Read `eligibility_reasons` for each. For the promising ones call `get_job` and read the full description.
4. **Score with your own judgment.** `set_score` (0-10) with a one-sentence reason. Your score is kept when later searches refresh the job.
5. **Track.** `set_status` as the user decides: saved, applied, interviewing, offer, rejected, hidden. Add a note when it helps.
6. **Applications.** Draft CV suggestions and a cover letter from the user's CV only, then `save_application_draft`. List requirements the CV does not show as gaps. Do not invent employers, titles, degrees, tools or numbers. Tell the user to read the draft before sending anything.

## Rules

- Say "unclear" when the verdict is `unknown`. Never present an unclear job as eligible, and do not hide not-eligible jobs from the user without saying you did.
- Freshness is a signal, not a verdict: report the facts (posted N days ago, closing date) and do not call a job fake.
- Do not apply on the user's behalf. Do not scrape LinkedIn or Indeed; for a page the user has open, they can use the Jobsieve browser extension.
- Everything stays local. Do not send the user's CV anywhere else.
