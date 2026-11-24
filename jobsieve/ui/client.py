import os

import requests

SCRAPER_URL = os.environ.get("SCRAPER_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN", "").strip()
OFFLINE = {"message": "offline", "progress": 0, "running": False, "added": 0, "paused": False}


def headers() -> dict:
    return {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}


def call(method: str, path: str, payload: dict | None = None, params: dict | None = None, timeout: int = 30):
    try:
        response = requests.request(
            method, f"{SCRAPER_URL}{path}", json=payload, params=params, headers=headers(), timeout=timeout
        )
    except requests.RequestException as error:
        return None, f"Cannot reach the Jobsieve API at {SCRAPER_URL} ({type(error).__name__})."
    if response.status_code >= 400:
        try:
            return None, str(response.json().get("detail") or response.text)
        except ValueError:
            return None, response.text
    return response.json(), ""


def status() -> dict:
    data, error = call("GET", "/status", timeout=5)
    return OFFLINE if error else data


def jobs(statuses=None, eligibility=None, latest_run=False, include_closed=False):
    params = {"limit": 500, "include_closed": include_closed}
    if statuses:
        params["status"] = ",".join(statuses)
    if eligibility:
        params["eligibility"] = ",".join(eligibility)
    if latest_run:
        params["run"] = "latest"
    data, error = call("GET", "/jobs", params=params)
    return (data or {}).get("jobs", []), error


# Tailoring waits on a model, which is allowed 60 seconds (twice, for servers without JSON mode).
def tailor(job_hash: str, provider: str, api_key: str = ""):
    return call("POST", f"/jobs/{job_hash}/tailor", {"provider": provider, "api_key": api_key}, timeout=130)
