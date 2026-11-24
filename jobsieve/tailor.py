import json
import re

from . import db
from . import profile as prof
from .ai_service import AIError, AIService

MAX_JOB_CHARS = 6000
MAX_CV_CHARS = 8000
SCHEMA = {
    "type": "object",
    "properties": {
        "cv_suggestions": {"type": "array", "items": {"type": "string"}},
        "keyword_gaps": {"type": "array", "items": {"type": "string"}},
        "cover_letter": {"type": "string"},
    },
    "required": ["cv_suggestions", "keyword_gaps", "cover_letter"],
    "additionalProperties": False,
}
NUMBER = re.compile(r"\d[\d,.]*%?")


class TailorError(Exception):
    pass


def build_prompt(job: dict, cv_text: str, profile: dict) -> str:
    return (
        "Help this candidate apply for the job below.\\n"
        "Rules: use only facts that appear in the CV. Do not invent employers, titles, degrees, tools, dates or numbers. "
        "If the job asks for something the CV does not show, list it under keyword_gaps instead of claiming it.\\n"
        f"CV:\\n{cv_text[:MAX_CV_CHARS]}\\n\\n"
        f"Job: {job.get('title')} at {job.get('company')} ({job.get('location') or 'location not stated'})\\n"
        f"{(job.get('description') or job.get('snippet') or '')[:MAX_JOB_CHARS]}\\n\\n"
        "Return JSON with: cv_suggestions (3 to 6 specific rewrites or reorderings of existing CV lines that fit this job, "
        "each one sentence), keyword_gaps (skills or requirements in the job that the CV does not show), and "
        "cover_letter (under 250 words, plain and specific, no invented claims)."
    )


def unverified_numbers(output: dict, *sources: str) -> list[str]:
    known = set(NUMBER.findall(" ".join(sources)))
    written = " ".join([output.get("cover_letter", ""), *output.get("cv_suggestions", [])])
    return sorted({n for n in NUMBER.findall(written) if n not in known and len(n.strip(",.")) > 1})


def parse(raw: str) -> dict:
    text = str(raw or "").strip()
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{[\s\S]*\}", text)
        try:
            data = json.loads(match.group(0)) if match else None
        except ValueError:
            data = None
    if not isinstance(data, dict) or not isinstance(data.get("cover_letter"), str):
        raise TailorError("the model did not return the expected JSON")
    return {
        "cv_suggestions": [str(x) for x in data.get("cv_suggestions") or []][:8],
        "keyword_gaps": [str(x) for x in data.get("keyword_gaps") or []][:20],
        "cover_letter": data["cover_letter"].strip(),
    }


def tailor_job(job_hash_value: str, provider: str, api_keys: dict | None = None) -> dict:
    job = db.get_job(job_hash_value)
    if not job:
        raise db.JobNotFound(job_hash_value)
    profile = prof.load()
    if not profile["cv_text"].strip():
        raise TailorError("save your CV in your profile first")
    ai = AIService(provider, api_keys)
    if not ai.enabled:
        raise TailorError(f"no usable key or model for '{ai.provider}'; set its key (or OPENAI_MODEL for a local model)")
    try:
        output = parse(ai.complete(build_prompt(job, profile["cv_text"], profile), SCHEMA))
    except TailorError:
        raise
    except Exception as error:
        raise TailorError(f"model call failed: {type(error).__name__}: {str(error)[:100]}") from error
    output["unverified_numbers"] = unverified_numbers(output, profile["cv_text"], job.get("description") or "")
    output["provider"] = ai.provider
    output["model"] = ai.model
    db.save_tailoring(job_hash_value, output)
    return output


def to_markdown(job: dict, output: dict) -> str:
    lines = [f"# {job.get('title')} at {job.get('company')}", "", f"{job.get('link')}", ""]
    if output.get("unverified_numbers"):
        lines += [f"> Check before sending: these numbers are not in your CV or the listing: {', '.join(output['unverified_numbers'])}", ""]
    lines += ["## CV suggestions", *[f"- {x}" for x in output["cv_suggestions"]], "",
              "## Not shown in your CV", *[f"- {x}" for x in output["keyword_gaps"]], "",
              "## Cover letter draft", "", output["cover_letter"], ""]
    return "\\n".join(lines)
