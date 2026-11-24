import json
import os
import re

from .util import data_dir

BOARDS = ("greenhouse", "lever", "ashby", "smartrecruiters")
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_ENTRIES = 500


class WatchlistError(ValueError):
    pass


def watchlist_path() -> str:
    return os.path.join(data_dir(), "watchlist.json")


def load() -> list[dict]:
    try:
        with open(watchlist_path(), "r", encoding="utf-8") as f:
            rows = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        raise WatchlistError(f"watchlist file is unreadable: {error}") from error
    return [r for r in rows if isinstance(r, dict) and r.get("board") in BOARDS and SLUG.match(str(r.get("slug", "")))]


def save(rows: list[dict]) -> None:
    os.makedirs(data_dir(), exist_ok=True)
    tmp_path = watchlist_path() + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, watchlist_path())


def add(board: str, slug: str, added_by: str = "manual") -> bool:
    board, slug = (board or "").strip().lower(), (slug or "").strip()
    if board not in BOARDS:
        raise WatchlistError(f"unknown board '{board}'; choose from {', '.join(BOARDS)}")
    if not SLUG.match(slug):
        raise WatchlistError(f"invalid company name '{slug}'")
    rows = load()
    if any(r["board"] == board and r["slug"].lower() == slug.lower() for r in rows):
        return False
    if len(rows) >= MAX_ENTRIES:
        raise WatchlistError(f"watchlist is full ({MAX_ENTRIES} companies)")
    rows.append({"board": board, "slug": slug, "added_by": added_by})
    save(rows)
    return True


def remove(board: str, slug: str) -> bool:
    rows = load()
    kept = [r for r in rows if not (r["board"] == (board or "").lower() and r["slug"].lower() == (slug or "").lower())]
    if len(kept) == len(rows):
        return False
    save(kept)
    return True


def pages_path() -> str:
    return os.path.join(data_dir(), "pages.json")


def load_pages() -> list[str]:
    try:
        with open(pages_path(), "r", encoding="utf-8") as f:
            rows = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        raise WatchlistError(f"page list is unreadable: {error}") from error
    return [r for r in rows if isinstance(r, str)]


def add_page(url: str) -> bool:
    url = (url or "").strip()
    if not re.match(r"^https?://[^\s]{4,500}$", url):
        raise WatchlistError("enter a full web address starting with http:// or https://")
    from .crawler import refused_site

    if refused_site(url):
        raise WatchlistError("that site's terms forbid automated reading; use the browser extension on a page you open yourself")
    pages = load_pages()
    if url in pages:
        return False
    if len(pages) >= 100:
        raise WatchlistError("page list is full (100 pages)")
    os.makedirs(data_dir(), exist_ok=True)
    with open(pages_path(), "w", encoding="utf-8") as f:
        json.dump(pages + [url], f, indent=2)
    return True


def remove_page(url: str) -> bool:
    pages = load_pages()
    if url not in pages:
        return False
    with open(pages_path(), "w", encoding="utf-8") as f:
        json.dump([p for p in pages if p != url], f, indent=2)
    return True


def starter_lists() -> dict[str, dict]:
    from importlib import resources

    lists = {}
    for entry in resources.files("jobsieve").joinpath("data/watchlists").iterdir():
        if entry.name.endswith(".json"):
            with entry.open("r", encoding="utf-8") as f:
                lists[entry.name[:-5]] = json.load(f)
    return lists


def add_starter(name: str) -> int:
    lists = starter_lists()
    if name not in lists:
        raise WatchlistError(f"unknown starter list '{name}'; available: {', '.join(lists) or 'none'}")
    return sum(add(c["board"], c["slug"], added_by=f"starter:{name}") for c in lists[name]["companies"])
