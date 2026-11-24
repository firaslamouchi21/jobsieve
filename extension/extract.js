(function () {
  const MAX_TEXT = 30000;
  const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " " };

  function decodeEntities(text) {
    return String(text || "").replace(/&(?:amp|lt|gt|quot|nbsp|#39);/g, (m) => ENTITIES[m]);
  }

  function htmlToText(html) {
    let text = decodeEntities(html);
    for (let i = 0; i < 2 && /<[a-zA-Z/][^>]*>/.test(text); i++) {
      text = decodeEntities(text.replace(/<(?:br|\/p|\/div|\/li|\/h[1-6])[^>]*>/gi, "\n").replace(/<[^>]+>/g, " "));
    }
    return text.replace(/[ \t\r\f\v]+/g, " ").replace(/\s*\n\s*/g, "\n").trim().slice(0, MAX_TEXT);
  }

  function asArray(value) {
    return value === undefined || value === null ? [] : Array.isArray(value) ? value : [value];
  }

  function isJobPosting(node) {
    return node && typeof node === "object" && asArray(node["@type"]).includes("JobPosting");
  }

  function findJobPosting(data) {
    for (const node of asArray(data)) {
      if (isJobPosting(node)) return node;
      const nested = node && typeof node === "object" ? findJobPosting(node["@graph"]) : null;
      if (nested) return nested;
    }
    return null;
  }

  function parseJsonLd(blocks) {
    for (const raw of blocks) {
      try {
        const found = findJobPosting(JSON.parse(raw));
        if (found) return found;
      } catch (error) {
        continue;
      }
    }
    return null;
  }

  function nameOf(value) {
    if (typeof value === "string") return value;
    return value && typeof value === "object" ? String(value.name || "") : "";
  }

  function formatPlace(place) {
    const address = place && place.address;
    if (typeof address === "string") return address;
    if (!address) return nameOf(place);
    const country = nameOf(address.addressCountry);
    return [address.addressLocality, address.addressRegion, country].filter(Boolean).join(", ");
  }

  function formatSalary(base) {
    if (!base || typeof base !== "object") return "";
    const value = base.value && typeof base.value === "object" ? base.value : base;
    const low = value.minValue, high = value.maxValue, single = value.value;
    const amount = low && high ? `${low}-${high}` : String(single || low || high || "");
    if (!amount) return "";
    const unit = String(value.unitText || "").toLowerCase();
    const period = { hour: "/hour", day: "/day", week: "/week", month: "/month", year: "/year" }[unit] || "";
    return [base.currency || value.currency || "", amount].filter(Boolean).join(" ") + period;
  }

  function fromJobPosting(node) {
    const places = asArray(node.jobLocation).map(formatPlace).filter(Boolean);
    const required = asArray(node.applicantLocationRequirements).map(nameOf).filter(Boolean);
    const remote = String(node.jobLocationType || "").toUpperCase() === "TELECOMMUTE" ? true : null;
    return {
      title: String(node.title || "").trim(),
      company: nameOf(node.hiringOrganization).trim(),
      location: places.join(" / "),
      restrictions: required.join(", "),
      remote,
      salary: formatSalary(node.baseSalary),
      posted_at: String(node.datePosted || ""),
      description: htmlToText(node.description),
      method: "jobposting",
    };
  }

  function companyFromTitle(title) {
    const match = /\s+at\s+([^|\u2013\u2014]+?)\s*(?:[|\u2013\u2014]|\s-\s|$)/i.exec(title);
    return match ? match[1].trim() : "";
  }

  function fromPage(page) {
    const title = String(page.ogTitle || page.title || "").trim();
    return {
      title,
      company: companyFromTitle(title) || String(page.siteName || "").trim(),
      location: "",
      restrictions: "",
      remote: null,
      salary: "",
      posted_at: "",
      description: String(page.text || "").replace(/[ \t\r\f\v]+/g, " ").replace(/\s*\n\s*/g, "\n").trim().slice(0, MAX_TEXT),
      method: "page-text",
    };
  }

  function extractJob(page) {
    const posting = parseJsonLd(page.jsonLd || []);
    const record = posting ? fromJobPosting(posting) : fromPage(page);
    if (posting && !record.description) record.description = fromPage(page).description;
    if (posting && !record.title) record.title = fromPage(page).title;
    const host = (() => {
      try { return new URL(page.url).hostname.replace(/^www\./, ""); } catch (error) { return ""; }
    })();
    return { ...record, url: page.url, site: host };
  }

  function readDocument(doc, url) {
    const meta = (name) => {
      const el = doc.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
      return el ? el.getAttribute("content") || "" : "";
    };
    const main = doc.querySelector("main") || doc.body;
    return extractJob({
      url,
      jsonLd: Array.from(doc.querySelectorAll('script[type="application/ld+json"]')).map((s) => s.textContent || ""),
      title: doc.title || "",
      ogTitle: meta("og:title"),
      siteName: meta("og:site_name"),
      text: main ? main.innerText || main.textContent || "" : "",
    });
  }

  const api = { htmlToText, parseJsonLd, fromJobPosting, extractJob, readDocument, formatSalary };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  return typeof document !== "undefined" ? readDocument(document, location.href) : undefined;
})();
