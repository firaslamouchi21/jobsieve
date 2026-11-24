import hashlib
import json
import os

from . import places
from .util import data_dir

WORK_MODES = ("remote", "hybrid", "onsite")
SENIORITY_LEVELS = ("intern", "junior", "mid", "senior", "lead", "principal", "executive")
MAX_CV_CHARS = 20000
MAX_LIST_ITEMS = 60

DEFAULTS = {
    "cv_text": "",
    "keywords": [],
    "home_country": "",
    "work_authorization": [],
    "needs_visa": False,
    "open_to_relocation": [],
    "work_modes": list(WORK_MODES),
    "timezone_offset": None,
    "max_timezone_diff": None,
    "salary_floor": None,
    "salary_currency": "USD",
    "seniority": [],
    "languages": ["en"],
    "dealbreakers": [],
    "excluded_companies": [],
    "sites": [],
    "sources": [],
}


class ProfileError(ValueError):
    pass


def profile_path() -> str:
    return os.path.join(data_dir(), "profile.json")


def clean_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part for part in value.replace(";", ",").replace("\n", ",").split(",")]
    if not isinstance(value, (list, tuple)):
        raise ProfileError(f"{field} must be a list")
    seen, out = set(), []
    for item in value:
        text = " ".join(str(item).split())
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out[:MAX_LIST_ITEMS]


def clean_number(value, field: str, low: float, high: float):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ProfileError(f"{field} must be a number") from None
    if not low <= number <= high:
        raise ProfileError(f"{field} must be between {low:g} and {high:g}")
    return number


def clean_places(value, field: str) -> list[str]:
    entries = clean_list(value, field)
    unknown = [e for e in entries if not places.expand([e])]
    if unknown:
        raise ProfileError(f"{field}: unknown place(s): {', '.join(unknown)}")
    return entries


def clean_choices(value, field: str, allowed) -> list[str]:
    entries = [e.lower() for e in clean_list(value, field)]
    bad = [e for e in entries if e not in allowed]
    if bad:
        raise ProfileError(f"{field}: {', '.join(bad)} not allowed; choose from {', '.join(allowed)}")
    return entries


def normalize(data: dict) -> dict:
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        raise ProfileError(f"unknown profile field(s): {', '.join(unknown)}")
    merged = {**json.loads(json.dumps(DEFAULTS)), **data}
    home = str(merged["home_country"] or "").strip()
    if home:
        codes = places.expand([home])
        if len(codes) != 1:
            raise ProfileError("home_country must be a single country")
        home = next(iter(codes))
    currency = str(merged["salary_currency"] or "USD").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ProfileError("salary_currency must be a 3-letter code such as USD")
    cv_text = str(merged["cv_text"] or "")
    if len(cv_text) > MAX_CV_CHARS:
        raise ProfileError(f"cv_text is longer than {MAX_CV_CHARS} characters")
    return {
        "cv_text": cv_text,
        "keywords": clean_list(merged["keywords"], "keywords"),
        "home_country": home,
        "work_authorization": clean_places(merged["work_authorization"], "work_authorization"),
        "needs_visa": bool(merged["needs_visa"]),
        "open_to_relocation": clean_places(merged["open_to_relocation"], "open_to_relocation"),
        "work_modes": clean_choices(merged["work_modes"], "work_modes", WORK_MODES) or list(WORK_MODES),
        "timezone_offset": clean_number(merged["timezone_offset"], "timezone_offset", -12, 14),
        "max_timezone_diff": clean_number(merged["max_timezone_diff"], "max_timezone_diff", 0, 12),
        "salary_floor": clean_number(merged["salary_floor"], "salary_floor", 0, 10**9),
        "salary_currency": currency,
        "seniority": clean_choices(merged["seniority"], "seniority", SENIORITY_LEVELS),
        "languages": [x.lower() for x in clean_list(merged["languages"], "languages")],
        "dealbreakers": clean_list(merged["dealbreakers"], "dealbreakers"),
        "excluded_companies": clean_list(merged["excluded_companies"], "excluded_companies"),
        "sites": clean_list(merged["sites"], "sites"),
        "sources": [x.lower() for x in clean_list(merged["sources"], "sources")],
    }


def load() -> dict:
    try:
        with open(profile_path(), "r", encoding="utf-8") as f:
            stored = json.load(f)
    except FileNotFoundError:
        return normalize({})
    except (OSError, ValueError) as error:
        raise ProfileError(f"profile file is unreadable: {error}") from error
    return normalize({k: v for k, v in stored.items() if k in DEFAULTS})


def save(data: dict) -> dict:
    profile = normalize(data)
    os.makedirs(data_dir(), exist_ok=True)
    tmp_path = profile_path() + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, profile_path())
    return profile


def update(changes: dict) -> dict:
    return save({**load(), **changes})


def exists() -> bool:
    return os.path.exists(profile_path())


def work_countries(profile: dict) -> set[str]:
    codes = places.expand(profile["work_authorization"])
    if profile["home_country"]:
        codes.add(profile["home_country"])
    return codes


def relocation_countries(profile: dict) -> set[str]:
    return places.expand(profile["open_to_relocation"]) - work_countries(profile)


def has_location(profile: dict) -> bool:
    return bool(work_countries(profile))


def fingerprint(profile: dict) -> str:
    relevant = {k: v for k, v in profile.items() if k not in ("cv_text", "keywords", "sites", "sources")}
    return hashlib.sha1(json.dumps(relevant, sort_keys=True).encode("utf-8")).hexdigest()[:12]
