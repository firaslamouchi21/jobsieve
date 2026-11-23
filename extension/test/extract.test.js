const test = require("node:test");
const assert = require("node:assert");
const core = require("../extract.js");

const posting = {
  "@context": "https://schema.org",
  "@type": "JobPosting",
  title: "Senior Data Engineer",
  description: "<p>Build <b>pipelines</b> &amp; dashboards.</p><ul><li>Python</li><li>SQL</li></ul>",
  datePosted: "2026-11-10",
  jobLocationType: "TELECOMMUTE",
  applicantLocationRequirements: [{ "@type": "Country", name: "United Arab Emirates" }, { "@type": "Country", name: "Saudi Arabia" }],
  hiringOrganization: { "@type": "Organization", name: "Acme Corp" },
  jobLocation: { "@type": "Place", address: { addressLocality: "Dubai", addressCountry: "AE" } },
  baseSalary: { "@type": "MonetaryAmount", currency: "AED", value: { "@type": "QuantitativeValue", minValue: 20000, maxValue: 28000, unitText: "MONTH" } },
};

test("reads schema.org JobPosting data", () => {
  const job = core.extractJob({ url: "https://www.bayt.com/en/uae/jobs/x-123/", jsonLd: [JSON.stringify(posting)], title: "ignored" });
  assert.strictEqual(job.title, "Senior Data Engineer");
  assert.strictEqual(job.company, "Acme Corp");
  assert.strictEqual(job.location, "Dubai, AE");
  assert.strictEqual(job.restrictions, "United Arab Emirates, Saudi Arabia");
  assert.strictEqual(job.remote, true);
  assert.strictEqual(job.salary, "AED 20000-28000/month");
  assert.strictEqual(job.posted_at, "2026-11-10");
  assert.strictEqual(job.method, "jobposting");
  assert.strictEqual(job.site, "bayt.com");
  assert.ok(job.description.includes("Build pipelines & dashboards."));
  assert.ok(!/[<>]/.test(job.description));
});

test("finds JobPosting inside @graph and arrays", () => {
  const graph = { "@graph": [{ "@type": "WebSite" }, { ...posting, "@type": ["Thing", "JobPosting"] }] };
  assert.strictEqual(core.parseJsonLd([JSON.stringify([graph])]).title, "Senior Data Engineer");
});

test("ignores broken JSON and non-job blocks", () => {
  assert.strictEqual(core.parseJsonLd(["{nope", JSON.stringify({ "@type": "Organization" })]), null);
});

test("falls back to page text when there is no job data", () => {
  const job = core.extractJob({ url: "https://example.com/job/1", jsonLd: [], title: "Doc title", ogTitle: "Backend Developer - Acme", siteName: "Acme", text: "  We are hiring.\n\n\n  Remote in UAE.  " });
  assert.strictEqual(job.title, "Backend Developer - Acme");
  assert.strictEqual(job.company, "Acme");
  assert.strictEqual(job.method, "page-text");
  assert.strictEqual(job.description, "We are hiring.\nRemote in UAE.");
});

test("uses the page title when og:title is missing", () => {
  assert.strictEqual(core.extractJob({ url: "https://example.com/j", jsonLd: [], title: "Dev role", text: "x" }).title, "Dev role");
});

test("fills missing job data fields from the page", () => {
  const sparse = { "@type": "JobPosting", hiringOrganization: "Acme" };
  const job = core.extractJob({ url: "https://example.com/j", jsonLd: [JSON.stringify(sparse)], title: "Page title", text: "Full page text" });
  assert.strictEqual(job.title, "Page title");
  assert.strictEqual(job.description, "Full page text");
  assert.strictEqual(job.company, "Acme");
});

test("handles entity-encoded html", () => {
  assert.strictEqual(core.htmlToText("&lt;p&gt;Hello &amp;lt;b&amp;gt;&lt;/p&gt;"), "Hello");
});

test("salary formats", () => {
  assert.strictEqual(core.formatSalary({ currency: "USD", value: { value: 90000, unitText: "YEAR" } }), "USD 90000/year");
  assert.strictEqual(core.formatSalary({ value: {} }), "");
  assert.strictEqual(core.formatSalary(null), "");
});

test("description is capped", () => {
  assert.ok(core.htmlToText("x".repeat(100000)).length <= 30000);
});

test("readDocument reads scripts, meta and main text from a document-like object", () => {
  const doc = {
    title: "T",
    querySelectorAll: () => [{ textContent: JSON.stringify(posting) }],
    querySelector: (sel) => (sel === "main" ? { innerText: "main text" } : null),
    body: { innerText: "body" },
  };
  const job = core.readDocument(doc, "https://jobs.example.com/1");
  assert.strictEqual(job.title, "Senior Data Engineer");
  assert.strictEqual(job.site, "jobs.example.com");
});
