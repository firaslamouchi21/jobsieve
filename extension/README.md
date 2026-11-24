# Jobsieve Capture

A small browser extension that saves the job page you are looking at to your own local Jobsieve app, where it gets the same eligibility check, score and tracking as every other job.

## How it works

1. Open a job page in your normal browser, logged in as yourself.
2. Click the Jobsieve button. The popup reads that one page and shows what it found.
3. Click **Save to Jobsieve**. The job is sent to your Jobsieve address and shows up in the dashboard marked "captured from <site>", with an Eligible, Unclear or Not eligible badge.

It reads a page only when you open the popup (it uses the `activeTab` permission, so it has no standing access to any site), makes no requests of its own to job sites, never logs in for you and never loads pages in bulk. It talks only to `http://localhost` or `http://127.0.0.1`.

## What it can read

- **Job data the page publishes** (schema.org `JobPosting`, which some job boards add for Google; Remotive does, GulfTalent and Greenhouse pages did not when I tried). This gives title, company, location, pay, posted date and any country restrictions.
- **Plain page text**, when there is no job data. The title and visible text are sent; if no location was found, Jobsieve reads it from the top of the text (for example "Dubai, UAE"). The popup says which method was used. The company field stays empty on this path.

It has not been tested against logged-in pages of LinkedIn, Indeed, Glassdoor, Bayt, GulfTalent, Naukri, Wuzzuf or Seek, and it has no site-specific readers, because those would be guesses I could not verify. If a site's page gives poor results, the plain-text fallback still works and a site reader can be added once someone confirms the page layout.

You are responsible for following each site's terms of use when you save pages from it.

## Install (development)

1. Start Jobsieve (`jobsieve` API on port 8000, for example with Docker Compose or `uvicorn jobsieve.api:api`).
2. Chrome or Edge: open `chrome://extensions`, turn on Developer mode, choose **Load unpacked** and select this `extension` folder.
   Firefox 115 or later: open `about:debugging`, choose **Load Temporary Add-on** and select `manifest.json`. Firefox support is untested.
3. In the popup's Settings, set the address if it is not `http://localhost:8000`, and the API token if you set `API_TOKEN`.

## Tests

`node --test extension/test/extract.test.js` runs the extraction tests. They also run as part of `pytest` when Node is installed.
