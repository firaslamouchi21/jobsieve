import json
import re
from functools import lru_cache
from importlib import resources

US_UPPERCASE = re.compile(r"(?<![\w.])(?:USA|U\.S\.A\.|U\.S\.|US)(?![\w])")


@lru_cache(maxsize=1)
def table() -> dict:
    with resources.files("jobsieve").joinpath("data/regions.json").open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def lookups():
    data = table()
    country_names: dict[str, str] = {}
    region_names: dict[str, str] = {}
    for code, info in data["countries"].items():
        names = [info["name"], *info["aliases"], *info.get("cities", [])]
        for name in names:
            country_names[name.lower()] = code
    for key, info in data["regions"].items():
        for name in [key.replace("_", " "), *info["aliases"]]:
            region_names[name.lower()] = key
    every = sorted([*country_names, *region_names], key=len, reverse=True)
    pattern = re.compile(
        r"(?<![\w])(?:" + "|".join(re.escape(n) for n in every) + r")(?![\w])",
        re.IGNORECASE,
    )
    worldwide = re.compile(
        r"(?<![\w])(?:" + "|".join(re.escape(w) for w in sorted(data["worldwide"], key=len, reverse=True)) + r")(?![\w])",
        re.IGNORECASE,
    )
    return country_names, region_names, pattern, worldwide


def region_countries(key: str) -> set[str]:
    return set(table()["regions"][key]["countries"])


def find_places(text: str, regions: bool = True) -> set[str]:
    country_names, region_names, pattern, _ = lookups()
    found: set[str] = set()
    for match in pattern.finditer(text or ""):
        name = match.group(0).lower()
        if name in country_names:
            found.add(country_names[name])
        elif regions and name in region_names:
            found |= region_countries(region_names[name])
    if US_UPPERCASE.search(text or ""):
        found.add("US")
    return found


def is_worldwide(text: str) -> bool:
    return lookups()[3].search(text or "") is not None


def expand(values) -> set[str]:
    codes: set[str] = set()
    countries = table()["countries"]
    for raw in values or []:
        token = str(raw).strip()
        if not token:
            continue
        if token.upper() in countries:
            codes.add(token.upper())
            continue
        key = token.upper().replace(" ", "_")
        if key in table()["regions"]:
            codes |= region_countries(key)
            continue
        codes |= find_places(token)
    return codes


def country_name(code: str) -> str:
    info = table()["countries"].get(code)
    return info["name"] if info else code


def names(codes, limit: int = 4) -> str:
    ordered = sorted(country_name(c) for c in codes)
    shown = ordered[:limit]
    extra = len(ordered) - len(shown)
    return ", ".join(shown) + (f" and {extra} more" if extra > 0 else "")


def place_phrases(text: str, limit: int = 3) -> list[str]:
    _, _, pattern, _ = lookups()
    found: list[str] = []
    for match in pattern.finditer(text or ""):
        phrase = match.group(0)
        if find_places(phrase, regions=False) and phrase.lower() not in (f.lower() for f in found):
            found.append(phrase)
        if len(found) >= limit:
            break
    return found
