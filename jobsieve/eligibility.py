import re

from . import places
from . import profile as prof
from .salary import parse_salary
from .util import contains_term

ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not_eligible"
UNKNOWN = "unknown"
MAX_TEXT_CHARS = 12000

SENIORITY_RULES = (
    ("intern", r"\b(?:intern|internship|apprentice|working student|werkstudent\w*)\b"),
    ("executive", r"\b(?:vp|vice president|chief|cto|ceo|cfo|coo|head of|director)\b"),
    ("principal", r"\b(?:principal|staff|distinguished|architect)\b"),
    ("lead", r"\b(?:lead|manager|supervisor)\b"),
    ("senior", r"\b(?:senior|sr\.?)(?=\W|$)"),
    ("junior", r"\b(?:junior|jr\.?|entry[- ]level|graduate|trainee|associate)(?=\W|$)"),
)
NO_SPONSORSHIP = re.compile(
    r"\b(?:no|without)\s+(?:visa\s+|immigration\s+|work\s+(?:permit\s+|visa\s+))?sponsorship\b"
    r"|\b(?:unable|not able|cannot|can't|can not|won't|will not|do not|don't|does not|doesn't|not in a position)\s+(?:to\s+)?(?:offer\s+|provide\s+)?(?:\w+\s+){0,2}sponsor"
    r"|\bsponsorship\s+(?:is\s+)?not\s+(?:available|offered|provided)\b",
    re.I,
)
YES_SPONSORSHIP = re.compile(
    r"\bvisa\s+sponsorship\s+(?:is\s+)?(?:available|provided|offered|supported|included)\b"
    r"|\b(?:we|company|employer)\s+(?:can|will|do|does|are able to|offer|provide)\s+(?:\w+\s+){0,2}sponsor\w*\s+(?:a\s+)?(?:visa|work|immigration)"
    r"|\b(?:offer|offering|provide|providing)\s+(?:visa\s+)?sponsorship\b",
    re.I,
)
RELOCATION_OFFERED = re.compile(r"\brelocation\s+(?:support|assistance|package|bonus|allowance)\b", re.I)
CITIZENSHIP = re.compile(
    r"\b(?:citizens?|nationals?)\s+only\b|\bmust\s+be\s+a\s+(?:\w+\s+)?citizen\b|\bsecurity\s+clearance\b",
    re.I,
)
def span(low: int, high: int) -> str:
    return r"(?:U\.S\.A\.|U\.S\.|U\.K\.|U\.A\.E\.|[^.;\n]){" + f"{low},{high}" + "}"


RESTRICTION_CUES = (
    re.compile(
        r"\b(?:must|need to|required to|should)\s+(?:currently\s+)?(?:be\s+)?(?:based|located|living|residing|resident|reside|live)\s+(?:in|within)\s+(?P<p>" + span(2, 140) + r")",
        re.I,
    ),
    re.compile(
        r"\b(?:open to|accepting|considering|hiring)\s+(?:candidates|applicants|applications)\s+(?:who are\s+)?(?:based\s+|located\s+|residing\s+|living\s+)?(?:in|from|within)\s+(?P<p>" + span(2, 140) + r")",
        re.I,
    ),
    re.compile(
        r"\b(?:must|need to)\s+(?:be\s+)?(?:legally\s+)?(?:authori[sz]ed|eligible|permitted|entitled)\s+to\s+work\s+in\s+(?P<p>" + span(2, 100) + r")",
        re.I,
    ),
    re.compile(r"\bright\s+to\s+work\s+in\s+(?P<p>" + span(2, 100) + r")", re.I),
    re.compile(r"(?P<p>" + span(2, 45) + r")\s+(?:residents|citizens|candidates|applicants)\s+only\b", re.I),
    re.compile(r"\banywhere\s+in\s+(?!the\s+world)(?P<p>" + span(2, 60) + r")", re.I),
    re.compile(r"(?P<p>" + span(2, 45) + r")\s+only\b", re.I),
)
WEAK_HINT = re.compile(r"relocat|or elsewhere|or other|or nearby|exclud|except|not open", re.I)
OPEN_WORLDWIDE = re.compile(
    r"work(?:ing)?\s+(?:remotely\s+)?from\s+anywhere\s+in\s+the\s+world"
    r"|(?:fully\s+)?remote\s*[-,(]?\s*(?:open\s+)?(?:worldwide|globally|global\b)"
    r"|open\s+to\s+(?:candidates\s+|applicants\s+)?(?:from\s+)?(?:anywhere|worldwide|all\s+countries|around\s+the\s+world)"
    r"|hire\s+(?:talent\s+|people\s+|team\s+members\s+|employees\s+)?(?:globally|worldwide|anywhere)",
    re.I,
)
UTC_OFFSET = re.compile(r"(?:UTC|GMT)\s*([+\-−–])\s*(\d{1,2})(?::(\d{2}))?", re.I)


def clean(text) -> str:
    return " ".join(str(text or "").split())[:MAX_TEXT_CHARS]


def remote_flag(value):
    if value is None or value == "":
        return None
    return bool(value)


def detect_seniority(title: str) -> str:
    text = clean(title).lower()
    for level, pattern in SENIORITY_RULES:
        if re.search(pattern, text):
            return level
    return ""


def detect_work_mode(job: dict) -> str:
    head = clean(f"{job.get('title')} {job.get('location')} {job.get('restrictions')}").lower()
    body = clean(job.get("description")).lower()
    remote = remote_flag(job.get("remote"))
    if "hybrid" in head:
        return "hybrid"
    if re.search(r"on-?site|in[- ]office|in-person", head):
        return "onsite"
    if remote or re.search(r"\bremote\b|work from home|\bwfh\b|anywhere", head):
        return "remote"
    if remote is False:
        if re.search(r"hybrid (?:work|role|position|model|schedule)|\d days? (?:a|per) week in (?:the )?office", body):
            return "hybrid"
        return "onsite"
    if re.search(r"fully remote|100% remote|remote[- ]first|work(?:ing)? remotely|remote (?:position|role|job)", body):
        return "remote"
    if re.search(r"hybrid (?:work|role|position|model|schedule)|\d days? (?:a|per) week in (?:the )?office", body):
        return "hybrid"
    if re.search(r"on-?site (?:role|position|work)|(?:role|position) is on-?site|in-office", body):
        return "onsite"
    return "onsite" if remote is False else "unknown"


def detect_sponsorship(text: str) -> str:
    if NO_SPONSORSHIP.search(text):
        return "no"
    if YES_SPONSORSHIP.search(text):
        return "yes"
    return ""


def parse_field_restriction(text: str) -> dict:
    found = places.find_places(text)
    return {
        "places": found,
        "worldwide": places.is_worldwide(text) and not found,
        "weak": bool(WEAK_HINT.search(text)),
        "evidence": text[:90],
    }


def parse_text_restriction(text: str) -> dict:
    found: set[str] = set()
    weak = False
    evidence = ""
    for pattern in RESTRICTION_CUES:
        for match in pattern.finditer(text):
            span = match.group("p")
            codes = places.find_places(span)
            if not codes:
                continue
            found |= codes
            evidence = evidence or text[match.start():match.end()][:90]
            sentence = text[max(0, match.start() - 60): match.end() + 80]
            weak = weak or bool(WEAK_HINT.search(sentence))
    return {"places": found, "worldwide": bool(OPEN_WORLDWIDE.search(text)) and not found, "weak": weak, "evidence": evidence}


def utc_offsets(text: str) -> list[float]:
    offsets = []
    for sign, hours, minutes in UTC_OFFSET.findall(text):
        value = int(hours) + (int(minutes) / 60 if minutes else 0)
        offsets.append(-value if sign in "-−–" else value)
    return offsets


def check_location(job, facts, profile, outcome):
    user = prof.work_countries(profile)
    relocate = prof.relocation_countries(profile)
    if not user:
        outcome["unresolved"].append("add your country to the profile so location can be checked")
        return
    mode = facts["work_mode"]
    if mode == "remote":
        check_remote_scope(job, facts, user, relocate, outcome)
    else:
        check_physical_location(job, facts, profile, user, relocate, outcome)


def check_remote_scope(job, facts, user, relocate, outcome):
    field_text = clean(job.get("restrictions"))
    field = parse_field_restriction(field_text) if field_text else None
    location = clean(job.get("location"))
    text = parse_text_restriction(clean(f"{job.get('description')} {location}"))
    hint = places.find_places(location)
    scope, evidence = None, ""
    if field and field["places"] and not field["weak"]:
        scope, evidence = field["places"], field["evidence"]
    elif field and field["worldwide"] and text["places"] and not text["weak"]:
        outcome["unresolved"].append("listing says worldwide but its text names location limits")
        return
    elif field and field["worldwide"]:
        outcome["confirms"].append("remote and open worldwide")
        return
    elif field and field["places"]:
        outcome["unresolved"].append("listing hints at location limits; check the exact wording")
        return
    elif text["places"] and not text["weak"]:
        scope, evidence = text["places"], text["evidence"]
    elif text["places"]:
        outcome["unresolved"].append("listing text hints at location limits; check the exact wording")
        return
    elif not hint and (places.is_worldwide(location) or text["worldwide"]):
        outcome["confirms"].append("remote and open to candidates anywhere")
        return
    elif hint:
        if user & hint:
            outcome["confirms"].append(f"remote, tied to {places.names(user & hint)}, where you can work")
        else:
            outcome["unresolved"].append(
                f"remote but tied to {places.names(hint)}; unclear whether other countries can apply"
            )
        return
    else:
        outcome["unresolved"].append("remote, but the listing does not say which countries can apply")
        return
    quote = f' ("{evidence}")' if evidence else ""
    overlap = user & scope
    if overlap:
        outcome["confirms"].append(f"remote and open to {places.names(overlap)}{quote}")
    elif relocate & scope:
        outcome["unresolved"].append(
            f"remote but requires living in {places.names(scope)}, which you listed for relocation{quote}"
        )
    else:
        outcome["blockers"].append(
            f"remote only for {places.names(scope)}{quote}; you can work in {places.names(user)}"
        )


def check_physical_location(job, facts, profile, user, relocate, outcome):
    mode = facts["work_mode"]
    shown = "" if mode == "unknown" else f"{mode} "
    found = places.find_places(clean(job.get("location")), regions=False)
    if not found:
        found = places.find_places(clean(job.get("title")), regions=False)
    if not found:
        outcome["unresolved"].append("the listing has no recognisable location")
        return
    if user & found:
        outcome["confirms"].append(f"{shown}in {places.names(user & found)}, where you can work")
        return
    if mode == "unknown":
        outcome["unresolved"].append(f"located in {places.names(found)}; unclear whether it can be done remotely")
        return
    if relocate & found:
        target = places.names(relocate & found)
        sponsorship = facts["sponsorship"]
        if sponsorship == "no":
            outcome["blockers"].append(f"{shown}in {target}, and the employer says it does not sponsor visas")
        elif sponsorship == "yes" or facts["relocation_offered"]:
            outcome["confirms"].append(f"{shown}in {target}, a relocation target; employer offers sponsorship or relocation")
        elif not profile["needs_visa"]:
            outcome["confirms"].append(f"{shown}in {target}, a relocation target; you do not need a visa")
        else:
            outcome["unresolved"].append(f"{shown}in {target}, a relocation target; the listing does not mention sponsorship")
        return
    outcome["blockers"].append(
        f"{shown}in {places.names(found)}, outside your work authorization and relocation list"
    )


def check_timezone(job, profile, outcome):
    allowed = profile["max_timezone_diff"]
    own = profile["timezone_offset"]
    if allowed is None or own is None:
        return
    offsets = utc_offsets(clean(f"{job.get('title')} {job.get('location')} {job.get('restrictions')}"))
    if not offsets:
        return
    low, high = min(offsets), max(offsets)
    if not (low - allowed <= own <= high + allowed):
        window = f"UTC{low:+g}" if low == high else f"UTC{low:+g} to UTC{high:+g}"
        outcome["blockers"].append(f"timezone {window} is more than {allowed:g}h from yours (UTC{own:+g})")


def check_rules(job, facts, profile, outcome):
    company = clean(job.get("company")).lower()
    for name in profile["excluded_companies"]:
        if name.lower() in company:
            outcome["blockers"].append(f"company excluded in your profile: {name}")
    text = clean(f"{job.get('title')} {job.get('description')}")
    for word in profile["dealbreakers"]:
        if contains_term(text, word):
            outcome["blockers"].append(f"contains your dealbreaker: {word}")
    mode = facts["work_mode"]
    if mode in ("remote", "hybrid", "onsite") and mode not in profile["work_modes"]:
        outcome["blockers"].append(f"{mode} work, which your profile excludes")
    floor = profile["salary_floor"]
    salary = facts["salary"]
    if floor and salary and salary["currency"] == profile["salary_currency"] and salary["max"] < floor:
        outcome["blockers"].append(
            f"pay up to {salary['max']:,.0f} {salary['currency']} a year is below your floor of {floor:,.0f}"
        )
    if CITIZENSHIP.search(clean(job.get("description"))):
        outcome["unresolved"].append("listing mentions citizenship or security clearance requirements")


def extract_facts(job: dict) -> dict:
    text = clean(job.get("description"))
    return {
        "work_mode": detect_work_mode(job),
        "seniority": detect_seniority(job.get("title") or ""),
        "sponsorship": detect_sponsorship(text),
        "relocation_offered": bool(RELOCATION_OFFERED.search(text)),
        "salary": parse_salary(job.get("salary")),
    }


def evaluate(job: dict, profile: dict | None = None) -> dict:
    profile = profile or prof.normalize({})
    facts = extract_facts(job)
    outcome = {"blockers": [], "confirms": [], "unresolved": []}
    check_rules(job, facts, profile, outcome)
    check_location(job, facts, profile, outcome)
    check_timezone(job, profile, outcome)
    if outcome["blockers"]:
        verdict, reasons = NOT_ELIGIBLE, outcome["blockers"]
    elif outcome["confirms"] and not outcome["unresolved"]:
        verdict, reasons = ELIGIBLE, outcome["confirms"]
    else:
        verdict, reasons = UNKNOWN, outcome["unresolved"] or outcome["confirms"]
    salary = facts["salary"] or {}
    return {
        "verdict": verdict,
        "reasons": reasons,
        "work_mode": facts["work_mode"],
        "seniority": facts["seniority"],
        "sponsorship": facts["sponsorship"],
        "salary_min": salary.get("min"),
        "salary_max": salary.get("max"),
        "salary_currency": salary.get("currency") or None,
    }


def job_from_record(record, text: str | None = None) -> dict:
    return {
        "title": record.title,
        "company": record.company,
        "location": record.location,
        "restrictions": record.restrictions,
        "remote": record.remote,
        "description": text if text is not None else record.description,
        "salary": record.salary,
    }


def reevaluate_stored(profile: dict) -> dict:
    from . import db

    fingerprint = prof.fingerprint(profile)
    counts = {ELIGIBLE: 0, NOT_ELIGIBLE: 0, UNKNOWN: 0}
    for row in db.jobs_for_evaluation():
        result = evaluate(row, profile)
        db.save_evaluation(row["job_hash"], result, fingerprint)
        counts[result["verdict"]] += 1
    return counts
