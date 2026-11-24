# Contributing

## Development

- Use Docker Compose to run the full stack. For code changes, a virtualenv is faster: `pip install -e ".[all,dev]" && python -m pytest health_test/`. Tests are offline (`MOCK_SEARCH`, no browser, no network). The browser extension has its own tests: `node --test extension/test/extract.test.js`.
- Keep changes minimal and production-minded.

## Style rules

- The code should explain itself through naming and structure. Add a comment only where the reason behind the code is not obvious; never to restate what the code does.
- Prefer clear naming and small functions.

## Pull requests

- Ensure CI passes. It runs the test suite, builds the package and checks it didn't leak flat modules, installs and runs the `jobsieve` console script, and boots the actual Docker images (scraper, UI, and the combined one) and drives a real scrape against them — a green check means the whole thing works, not just that it compiles.
- Include a clear description of the change and why it is needed.
- Small, focused PRs get reviewed faster than one PR doing five things.
