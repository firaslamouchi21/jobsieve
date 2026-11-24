# Sources

Where Jobsieve gets listings, what each source tells it about who may apply, and the terms it was built against. Terms change: check the source's own page before relying on a row, and tell us if one has changed.

Every listing keeps its source name and original link, and the dashboard shows "via ...". Jobsieve stores listings locally for your own search. Do not republish them.

| Source | Endpoint | Location rule it gives | Cached | Terms and notes |
| --- | --- | --- | --- | --- |
| `remoteok` | remoteok.com public API | A company city, not a rule (ignored as a restriction) | 1 h | Link back and name Remote OK as the source. |
| `remotive` | remotive.com/api/remote-jobs | `candidate_required_location`, used as the restriction | 6 h | Link back, name Remotive. At most 4 requests a day. Do not re-post its jobs to other job sites. |
| `arbeitnow` | arbeitnow.com/api/job-board-api | Place and a remote flag | 1 h | Public API, no key. |
| `himalayas` | himalayas.app/jobs/api | `locationRestrictions` list, used as the restriction | 24 h | Data refreshes daily. Keep the link back and name Himalayas. Reported to forbid passing its jobs to other job sites. The official terms page was not read (checked third-party summaries only): read himalayas.app/terms before release. Timezone lists are not used. |
| `jobicy` | jobicy.com/api/v2/remote-jobs | `jobGeo`, used as the restriction | 1 h | Credit Jobicy with a direct link, and send applicants to the original job URL. |
| `workingnomads` | workingnomads.com/api/exposed_jobs | `location` region, used as the restriction | 1 h | Public feed. Keep the link back. |
| `boards` | Greenhouse, Lever, Ashby, SmartRecruiters public job-board APIs, for companies on your watchlist | Place of the job, plus remote flag where given (Lever, Ashby, SmartRecruiters) | 6 h per company | Official public posting APIs, meant for showing a company's own jobs. SmartRecruiters returns no description. |
| `web` | Pages you list (`jobsieve watch add-page`) | Whatever the page's schema.org JobPosting data says | 12 h per page | Follows robots.txt, 2 s or more between requests, stops at a bot check, same site only, public addresses only. LinkedIn, Indeed and Glassdoor are refused. robots.txt is not permission to scrape: you must check the site's terms. |
| `ddg` | DuckDuckGo search, `site:` queries | None (title and snippet only) | none | Search results, not a feed. Results that point at a company board add that company to your watchlist. |
| Browser extension | Your own browser, on a page you open, when you click | Read from the page (structured data if the page has it, otherwise the text) | none | Sends only to your own Jobsieve. You are responsible for following each site's terms. See [extension/README.md](../extension/README.md). |

## Not scraped

LinkedIn and Indeed are not scraped. Use the browser extension on a page you have open yourself.

Bayt, GulfTalent, Naukri/Naukrigulf, Wuzzuf and Seek have no source of their own. In a live test (23 Nov) Bayt and GulfTalent answered the polite crawler with 403, so it stopped as designed: for those, use the browser extension on a page you open yourself. Wuzzuf, Naukrigulf and Seek were not tried. The crawler never uses proxies, disguises itself or solves CAPTCHAs.

## Company boards

A company's board name is the part of its job-board address after the site: `boards.greenhouse.io/careem` is Greenhouse, `careem`. Add companies with `jobsieve watch add`, find them from a careers page with `jobsieve watch from-page`, or let `jobsieve discover` search for them. Discovered companies are marked and can be removed.

## Limits worth knowing

- Feeds are downloaded whole and filtered on your machine, so a feed that only publishes its newest jobs (Himalayas: the newest 200 per run by default) only shows those.
- Jobs without a location are never merged as duplicates.
- A source's location field says where the job is, or who may apply, in the source's own words. Jobsieve turns that into a verdict only where the wording is clear, and shows "unclear" otherwise.
