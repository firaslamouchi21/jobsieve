import json
import logging
import os
import re

import requests

from .util import contains_term

logger = logging.getLogger("jobsieve.ai")

DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-3.6-flash",
    "anthropic": "claude-haiku-5-5",
}
MODEL_ENV_VARS = {
    "groq": "GROQ_MODEL",
    "gemini": "GEMINI_MODEL",
    "anthropic": "ANTHROPIC_MODEL",
}
OPENAI_COMPATIBLE_URLS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}
AI_FAILED_PREFIX = "ai_failed:"
CV_BONUS_CAP = 3
CV_TERMS_PER_BONUS_POINT = 3
MAX_CV_TERMS = 300
STOPWORDS = frozenset(
    "the and for with that this from have has had are was were been will would can could "
    "should may might not but you your our their they them his her its who what when where "
    "which while into over under about also more most other some such than then there these "
    "those very work working worked experience years year team teams role responsible "
    "skills ability strong good great using used use new including include within across "
    "all any both each few per via etc one two three able well like make made help helped".split()
)
TOKEN_PATTERN = re.compile(r"[a-z][a-z0-9+#]*")
AI_TIMEOUT_SECONDS = 60
MAX_REASON_LENGTH = 160
SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "reasoning": {"type": "string"},
    },
    "required": ["score", "reasoning"],
    "additionalProperties": False,
}


class AIError(Exception):
    pass


def model_for(provider: str) -> str:
    override = (os.environ.get(MODEL_ENV_VARS.get(provider, "")) or "").strip()
    return override or DEFAULT_MODELS.get(provider, "")


def is_ai_failure(reasoning: str | None) -> bool:
    return str(reasoning or "").startswith(AI_FAILED_PREFIX)


def short_reason(text: str) -> str:
    return " ".join(str(text or "").split())[:MAX_REASON_LENGTH]


def http_error_reason(response) -> str:
    message = ""
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "")
        elif error:
            message = str(error)
    except Exception:
        message = ""
    return short_reason(f"http {response.status_code} {message}")


def describe_error(error: Exception) -> str:
    if isinstance(error, AIError):
        return short_reason(str(error))
    if isinstance(error, requests.Timeout):
        return "timeout"
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return http_error_reason(error.response)
    if isinstance(error, requests.RequestException):
        return "connection error"
    return short_reason(type(error).__name__)


class AIService:
    def __init__(self, provider: str | None, api_keys: dict[str, str] | None = None):
        self.provider = (provider or "groq").strip().lower()
        self.api_keys = {
            "groq": "",
            "anthropic": "",
            "gemini": "",
        }
        for k, v in (api_keys or {}).items():
            self.api_keys[str(k).strip().lower()] = (v or "").strip()
        self.model = model_for(self.provider)
        self.failures = 0
        self._anthropic = None

    @property
    def enabled(self) -> bool:
        return self.provider in DEFAULT_MODELS and bool(self.api_keys.get(self.provider))

    def analyze(self, text: str, cv_text: str, keywords: list[str], profile: dict | None = None):
        if not text:
            return 0, ""
        if not self.enabled:
            return self.lite_score(text, keywords, cv_text)
        try:
            raw = self.complete(self.build_prompt(text, cv_text, keywords, profile))
            return self.parse_score_and_reasoning(raw)
        except Exception as error:
            return self.failed(text, keywords, error, cv_text)

    def failed(self, text: str, keywords: list[str], error: Exception, cv_text: str = ""):
        reason = describe_error(error)
        self.failures += 1
        logger.warning(
            "ai scoring failed provider=%s model=%s reason=%s",
            self.provider,
            self.model,
            reason,
        )
        score, lite_reasoning = self.lite_score(text, keywords, cv_text)
        return score, f"{AI_FAILED_PREFIX} {reason} | {lite_reasoning}"

    def complete(self, prompt: str) -> str:
        if self.provider == "anthropic":
            return self.complete_anthropic(prompt)
        return self.complete_openai_compatible(prompt)

    def complete_openai_compatible(self, prompt: str) -> str:
        response = requests.post(
            OPENAI_COMPATIBLE_URLS[self.provider],
            headers={"Authorization": f"Bearer {self.api_keys[self.provider]}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=AI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        choices = response.json().get("choices") or []
        if not choices:
            return ""
        return str(((choices[0] or {}).get("message") or {}).get("content") or "")

    def anthropic_client(self):
        if self._anthropic is None:
            import anthropic

            self._anthropic = anthropic.Anthropic(
                api_key=self.api_keys["anthropic"],
                timeout=AI_TIMEOUT_SECONDS,
                max_retries=1,
            )
        return self._anthropic

    def complete_anthropic(self, prompt: str) -> str:
        try:
            import anthropic
        except ImportError as error:
            raise AIError("anthropic package not installed; pip install jobsieve[ai]") from error
        output_config = {"format": {"type": "json_schema", "schema": SCORE_SCHEMA}}
        effort = os.environ.get("ANTHROPIC_EFFORT", "low").strip().lower()
        if effort:
            output_config["effort"] = effort
        try:
            # max_tokens leaves room for thinking, which current models do by default
            # and which counts against the cap before any answer text is written.
            response = self.anthropic_client().messages.create(
                model=self.model,
                max_tokens=2048,
                output_config=output_config,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as error:
            raise AIError("http 401 invalid api key") from error
        except anthropic.NotFoundError as error:
            raise AIError(f"http 404 unknown model {self.model}") from error
        except anthropic.RateLimitError as error:
            raise AIError("http 429 rate limited") from error
        except anthropic.APIStatusError as error:
            raise AIError(f"http {error.status_code} {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise AIError("connection error") from error
        if response.stop_reason == "refusal":
            raise AIError("request refused by the model")
        if response.stop_reason == "max_tokens":
            raise AIError("response cut off at max_tokens")
        return next(
            (block.text for block in response.content if block.type == "text"),
            "",
        )

    def parse_score_and_reasoning(self, raw: str | None):
        text = str(raw or "").strip()
        if not text:
            raise AIError("empty response")
        obj = None
        try:
            obj = json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    obj = json.loads(m.group(0))
                except Exception:
                    obj = None
        if not isinstance(obj, dict):
            raise AIError("response was not JSON")
        try:
            score = int(float(obj.get("score")))
        except (TypeError, ValueError) as error:
            raise AIError("response had no numeric score") from error
        reasoning = str(obj.get("reasoning") or "")
        return max(0, min(10, score)), reasoning

    def build_prompt(self, text: str, cv_text: str, keywords: list[str], profile: dict | None = None):
        k = ", ".join([x for x in keywords if x])
        return (
            "Score how well this job listing matches the candidate.\n"
            f"CV: {(cv_text or '')[:4000]}\n"
            f"{self.profile_lines(profile)}"
            f"Keywords: {k}\n"
            f"Job listing: {text[:6000]}\n"
            "Return JSON with keys score (integer 0-10, where 10 is an excellent match) "
            "and reasoning (one or two sentences)."
        )

    def cv_terms(self, cv_text: str) -> set[str]:
        terms = {
            token
            for token in TOKEN_PATTERN.findall((cv_text or "").lower())
            if len(token) >= 3 and token not in STOPWORDS
        }
        return set(sorted(terms)[:MAX_CV_TERMS])

    def profile_lines(self, profile: dict | None) -> str:
        if not profile:
            return ""
        from . import places
        from . import profile as prof

        lines = []
        if profile.get("home_country"):
            lines.append(f"Candidate lives in {places.country_name(profile['home_country'])}.")
        allowed = prof.work_countries(profile)
        if allowed:
            lines.append(f"Can work without sponsorship in: {places.names(allowed, limit=8)}.")
        if profile.get("needs_visa"):
            lines.append("Needs visa sponsorship to work anywhere else.")
        if profile.get("open_to_relocation"):
            lines.append(f"Open to relocating to: {', '.join(profile['open_to_relocation'])}.")
        if profile.get("salary_floor"):
            lines.append(f"Minimum salary: {profile['salary_floor']:,.0f} {profile['salary_currency']} a year.")
        if profile.get("dealbreakers"):
            lines.append(f"Dealbreakers: {', '.join(profile['dealbreakers'])}.")
        if lines:
            lines.append("State clearly in the reasoning if the listing conflicts with any of this (location, visa, pay).")
        return "".join(line + "\n" for line in lines)

    def lite_score(self, text: str, keywords: list[str], cv_text: str = ""):
        t = text.lower()
        hits = sum(1 for kw in keywords if contains_term(t, kw))
        cv_terms = self.cv_terms(cv_text)
        if not cv_terms:
            return min(10, max(0, hits)), f"matched_keywords={hits}"
        overlap = len(cv_terms & set(TOKEN_PATTERN.findall(t)))
        bonus = min(CV_BONUS_CAP, overlap // CV_TERMS_PER_BONUS_POINT)
        score = min(10, hits + bonus)
        return score, f"matched_keywords={hits} cv_terms={overlap}"
