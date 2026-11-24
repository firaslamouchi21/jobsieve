import re

LEGAL_SUFFIXES = {"inc", "ltd", "llc", "llp", "limited", "corp", "corporation", "gmbh", "fz", "fze", "pjsc", "co", "company", "plc", "ag", "sa"}
BOARD_SOURCES = {"greenhouse", "lever", "ashby", "smartrecruiters"}


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", str(text or "").lower())


def duplicate_key(company, title, location, source) -> str | None:
    if source == "ddg":
        return None
    name = [w for w in words(company) if w not in LEGAL_SUFFIXES]
    role = words(title)
    place = words(str(location or "").split(",")[0])
    if not name or not role or not place:
        return None
    return "|".join((" ".join(name), " ".join(role), " ".join(place)))


def preference(source: str, description: str, updated_at: str) -> tuple:
    return (
        0 if source in BOARD_SOURCES else 1,
        -len(description or ""),
        str(updated_at or ""),
    )
