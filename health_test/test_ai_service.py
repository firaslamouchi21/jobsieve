from jobsieve.ai_service import AIService


class TestLiteScore:

    def setup_method(self):
        self.svc = AIService("groq", {})

    def test_single_keyword_match(self):
        score, reasoning = self.svc.lite_score(
            "We are hiring a Python Developer", ["python"]
        )
        assert score == 1
        assert reasoning == "matched_keywords=1"

    def test_multi_word_keyword_match(self):
        score, _ = self.svc.lite_score(
            "Looking for a Python Developer with Data Engineer experience",
            ["python developer", "data engineer"],
        )
        assert score == 2

    def test_no_match(self):
        score, reasoning = self.svc.lite_score(
            "We are hiring a plumber", ["python", "java"]
        )
        assert score == 0
        assert reasoning == "matched_keywords=0"

    def test_does_not_match_substring_of_a_longer_word(self):
        score, _ = self.svc.lite_score("Senior JavaScript Engineer", ["java"])
        assert score == 0

    def test_score_capped_at_ten(self):
        keywords = [f"kw{i}" for i in range(15)]
        text = " ".join(keywords)
        score, _ = self.svc.lite_score(text, keywords)
        assert score == 10

    def test_empty_and_blank_keywords_ignored(self):
        score, _ = self.svc.lite_score("python developer", ["", "  ", "python"])
        assert score == 1


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def groq_service():
    return AIService("groq", {"groq": "key"})


class TestModelConfig:

    def test_defaults_are_current_models(self, monkeypatch):
        for var in ("GROQ_MODEL", "GEMINI_MODEL", "ANTHROPIC_MODEL"):
            monkeypatch.delenv(var, raising=False)
        assert AIService("groq", {}).model == "llama-3.3-70b-versatile"
        assert AIService("gemini", {}).model == "gemini-3.6-flash"
        assert AIService("anthropic", {}).model == "claude-haiku-5-5"

    def test_env_overrides_model(self, monkeypatch):
        monkeypatch.setenv("GROQ_MODEL", "my-groq-model")
        monkeypatch.setenv("GEMINI_MODEL", "my-gemini-model")
        monkeypatch.setenv("ANTHROPIC_MODEL", "my-claude-model")
        assert AIService("groq", {}).model == "my-groq-model"
        assert AIService("gemini", {}).model == "my-gemini-model"
        assert AIService("anthropic", {}).model == "my-claude-model"

    def test_request_uses_configured_model(self, monkeypatch):
        monkeypatch.setenv("GROQ_MODEL", "custom-model")
        sent = {}

        def fake_post(url, **kwargs):
            sent.update(kwargs["json"])
            body = {"choices": [{"message": {"content": '{"score": 7, "reasoning": "ok"}'}}]}
            return FakeResponse(200, body)

        monkeypatch.setattr("jobsieve.ai_service.requests.post", fake_post)
        score, reasoning = groq_service().analyze("python job", "cv", ["python"])
        assert sent["model"] == "custom-model"
        assert (score, reasoning) == (7, "ok")


class TestVisibleFailures:

    def test_http_error_is_marked_and_counted(self, monkeypatch):
        body = {"error": {"message": "model decommissioned"}}
        monkeypatch.setattr(
            "jobsieve.ai_service.requests.post",
            lambda *a, **k: FakeResponse(400, body),
        )
        svc = groq_service()
        score, reasoning = svc.analyze("python job", "cv", ["python"])
        assert score == 1
        assert reasoning.startswith("ai_failed: http 400 model decommissioned")
        assert "matched_keywords=1" in reasoning
        assert svc.failures == 1

    def test_unparseable_reply_is_marked(self, monkeypatch):
        body = {"choices": [{"message": {"content": "sorry, no json here"}}]}
        monkeypatch.setattr(
            "jobsieve.ai_service.requests.post",
            lambda *a, **k: FakeResponse(200, body),
        )
        svc = groq_service()
        _, reasoning = svc.analyze("python job", "cv", ["python"])
        assert reasoning.startswith("ai_failed: response was not JSON")
        assert svc.failures == 1

    def test_network_error_is_marked(self, monkeypatch):
        import requests

        def boom(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr("jobsieve.ai_service.requests.post", boom)
        _, reasoning = groq_service().analyze("python job", "cv", ["python"])
        assert reasoning.startswith("ai_failed: connection error")

    def test_failure_is_logged(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "jobsieve.ai_service.requests.post",
            lambda *a, **k: FakeResponse(500, {}),
        )
        with caplog.at_level("WARNING", logger="jobsieve.ai"):
            groq_service().analyze("python job", "cv", ["python"])
        assert "ai scoring failed" in caplog.text

    def test_without_key_uses_lite_without_failure_marker(self):
        svc = AIService("groq", {})
        score, reasoning = svc.analyze("python job", "cv", ["python"])
        assert (score, reasoning) == (1, "matched_keywords=1")
        assert svc.failures == 0


class TestLiteScoreUsesCv:

    CV = "Senior backend engineer. Python, Django, PostgreSQL, Docker, Kubernetes, AWS, Redis."

    def setup_method(self):
        self.svc = AIService("groq", {})

    def test_no_cv_keeps_original_scoring_and_format(self):
        assert self.svc.lite_score("python job", ["python"], "") == (1, "matched_keywords=1")

    def test_cv_overlap_raises_score(self):
        text = "We use Python, Django, PostgreSQL, Docker and Kubernetes on AWS"
        plain, _ = self.svc.lite_score(text, ["python"])
        with_cv, reasoning = self.svc.lite_score(text, ["python"], self.CV)
        assert with_cv > plain
        assert "cv_terms=" in reasoning

    def test_listing_unrelated_to_cv_gets_no_bonus(self):
        score, reasoning = self.svc.lite_score("We need a pastry chef", ["python"], self.CV)
        assert score == 0
        assert "cv_terms=0" in reasoning

    def test_cv_bonus_is_capped(self):
        cv = " ".join(f"skill{i}x" for i in range(60))
        text = " ".join(f"skill{i}x" for i in range(60))
        score, _ = self.svc.lite_score(text, [], cv)
        assert score == 3

    def test_total_score_never_exceeds_ten(self):
        keywords = [f"kw{i}" for i in range(10)]
        cv = " ".join(f"term{i}x" for i in range(30))
        text = " ".join(keywords) + " " + cv
        score, _ = self.svc.lite_score(text, keywords, cv)
        assert score == 10

    def test_common_words_do_not_count_as_cv_terms(self):
        score, _ = self.svc.lite_score("the team will have experience", [], "the team will have experience")
        assert score == 0

    def test_analyze_passes_cv_through_in_lite_mode(self):
        text = "We use Python, Django, PostgreSQL, Docker and Kubernetes on AWS"
        score, reasoning = self.svc.analyze(text, self.CV, ["python"])
        assert score > 1 and "cv_terms=" in reasoning


class TestSharedMatcher:

    def test_lite_score_and_feed_filter_agree(self):
        from jobsieve.util import contains_term

        svc = AIService("groq", {})
        for text, kw in [("Senior JavaScript Engineer", "java"), ("C++ developer", "c++"), ("python developers", "python developer")]:
            assert bool(svc.lite_score(text, [kw])[0]) == contains_term(text, kw)
