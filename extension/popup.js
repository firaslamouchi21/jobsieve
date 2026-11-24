const DEFAULT_URL = "http://localhost:8000";
const LOCAL_HOSTS = ["localhost", "127.0.0.1"];
let captured = null;

const $ = (id) => document.getElementById(id);

function text(el, value, cls) {
  el.textContent = value;
  el.className = cls || "";
}

async function settings() {
  const stored = await chrome.storage.local.get(["apiUrl", "token"]);
  return { apiUrl: (stored.apiUrl || DEFAULT_URL).replace(/\/+$/, ""), token: stored.token || "" };
}

function allowedAddress(address) {
  try {
    const parsed = new URL(address);
    return parsed.protocol === "http:" && LOCAL_HOSTS.includes(parsed.hostname);
  } catch (error) {
    return false;
  }
}

async function readActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https?:/i.test(tab.url || "")) throw new Error("Open a job page in this tab first.");
  const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["extract.js"] });
  if (!result || !result.result) throw new Error("Could not read this page.");
  return result.result;
}

function showPreview(job) {
  const box = $("preview");
  box.textContent = "";
  const title = document.createElement("strong");
  title.textContent = job.title || "(no title found)";
  const meta = document.createElement("div");
  meta.className = "muted";
  meta.textContent = [job.company, job.location, job.salary].filter(Boolean).join(" · ") || "No details found";
  const how = document.createElement("div");
  how.className = "muted";
  how.textContent = job.method === "jobposting" ? "Read from the page's job data" : "Read from the page text; check the result";
  box.append(title, meta, how);
  box.className = "card";
}

async function save() {
  const { apiUrl, token } = await settings();
  const result = $("result");
  if (!allowedAddress(apiUrl)) return text(result, "The address must be http://localhost or http://127.0.0.1.", "bad");
  text(result, "Saving...", "muted");
  try {
    const response = await fetch(`${apiUrl}/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(captured),
    });
    if (response.status === 401) return text(result, "Wrong or missing API token (see Settings).", "bad");
    if (!response.ok) {
      const detail = await response.text();
      return text(result, `Not saved (${response.status}): ${detail.slice(0, 160)}`, "bad");
    }
    const data = await response.json();
    const label = { eligible: "Eligible", unknown: "Unclear", not_eligible: "Not eligible" }[data.eligibility] || "Saved (set up your profile to get a verdict)";
    const cls = { eligible: "good", unknown: "warn", not_eligible: "bad" }[data.eligibility] || "muted";
    text(result, `${data.is_new ? "Saved" : "Updated"}: ${label}${data.reasons.length ? " - " + data.reasons.join("; ") : ""}`, cls);
  } catch (error) {
    text(result, `Cannot reach Jobsieve at ${apiUrl}. Is it running?`, "bad");
  }
}

async function init() {
  const { apiUrl, token } = await settings();
  $("apiUrl").value = apiUrl;
  $("token").value = token;
  $("saveSettings").addEventListener("click", async () => {
    await chrome.storage.local.set({ apiUrl: $("apiUrl").value.trim() || DEFAULT_URL, token: $("token").value });
    text($("result"), "Settings saved.", "muted");
  });
  $("save").addEventListener("click", save);
  try {
    captured = await readActiveTab();
    showPreview(captured);
    $("save").disabled = false;
  } catch (error) {
    text($("preview"), error.message, "card bad");
  }
}

init();
