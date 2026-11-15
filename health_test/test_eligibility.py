import pytest

from jobsieve import eligibility as el
from jobsieve import profile as prof

GULF = prof.normalize({"home_country": "AE", "work_authorization": ["GCC"]})
GULF_RELOCATING = prof.normalize(
    {"home_country": "AE", "work_authorization": ["GCC"], "open_to_relocation": ["Germany"], "needs_visa": True}
)
EU_PERSON = prof.normalize({"home_country": "DE", "work_authorization": ["EU"]})


def job(**kw):
    base = dict(title="Software Engineer", company="Acme", location="", restrictions="", remote=None, description="", salary="")
    return {**base, **kw}


def verdict(j, p=GULF):
    return el.evaluate(j, p)["verdict"]


class TestRemoteScope:

    def test_worldwide_is_eligible(self):
        r = el.evaluate(job(remote=True, restrictions="Worldwide"), GULF)
        assert r["verdict"] == "eligible" and "worldwide" in r["reasons"][0]

    @pytest.mark.parametrize("scope", ["USA Only", "Europe", "United States", "Canada, USA", "North America"])
    def test_restricted_elsewhere_is_not_eligible(self, scope):
        r = el.evaluate(job(remote=True, restrictions=scope), GULF)
        assert r["verdict"] == "not_eligible" and "remote only for" in r["reasons"][0]

    @pytest.mark.parametrize("scope", ["GCC", "MENA", "EMEA", "United Arab Emirates", "Middle East", "Dubai"])
    def test_restricted_to_your_region_is_eligible(self, scope):
        assert verdict(job(remote=True, restrictions=scope)) == "eligible"

    def test_europe_is_not_eligible_for_a_gulf_resident_but_is_for_an_eu_resident(self):
        j = job(remote=True, restrictions="Europe")
        assert verdict(j, GULF) == "not_eligible"
        assert verdict(j, EU_PERSON) == "eligible"

    def test_remote_without_any_scope_is_unknown_not_eligible(self):
        r = el.evaluate(job(remote=True, description="Join our friendly team."), GULF)
        assert r["verdict"] == "unknown" and "does not say" in r["reasons"][0]

    def test_remote_restricted_to_a_relocation_target_is_unknown(self):
        r = el.evaluate(job(remote=True, restrictions="Germany"), GULF_RELOCATING)
        assert r["verdict"] == "unknown" and "relocation" in r["reasons"][0]

    def test_exclusion_wording_is_treated_as_unclear(self):
        assert verdict(job(remote=True, restrictions="Worldwide except Europe")) in ("unknown",)

    def test_field_worldwide_but_text_names_limits_is_unknown(self):
        j = job(remote=True, restrictions="Worldwide", description="You must be based in the US to apply.")
        assert verdict(j) == "unknown"


class TestDescriptionRestrictions:

    @pytest.mark.parametrize(
        "text",
        [
            "You must be located in the United States.",
            "Candidates must be based in the UK.",
            "We are only open to applicants from Canada.",
            "Must be authorized to work in the US.",
            "Applicants must have the right to work in the UK.",
            "This position is US only.",
            "UK residents only.",
        ],
    )
    def test_clear_phrases_block_outside_candidates(self, text):
        r = el.evaluate(job(remote=True, description=text), GULF)
        assert r["verdict"] == "not_eligible", text

    def test_restriction_naming_your_country_is_eligible(self):
        assert verdict(job(remote=True, description="Must be based in the UAE or Saudi Arabia.")) == "eligible"

    @pytest.mark.parametrize(
        "text",
        [
            "Must be based in the US or open to relocation.",
            "Our customers are in the US and Canada.",
            "Our offices are in London and New York.",
            "We have a distributed team across the US, EU and APAC.",
            "Full-time only. Remote role.",
            "Tell us about yourself.",
        ],
    )
    def test_ambiguous_or_unrelated_text_never_blocks(self, text):
        assert verdict(job(remote=True, description=text)) != "not_eligible", text

    def test_open_anywhere_in_text_is_eligible(self):
        assert verdict(job(remote=True, description="Fully remote, work from anywhere in the world.")) == "eligible"


class TestPhysicalJobs:

    def test_onsite_in_your_country_is_eligible(self):
        assert verdict(job(location="Dubai, UAE", remote=False)) == "eligible"

    def test_hybrid_in_a_gcc_neighbour_is_eligible(self):
        assert verdict(job(title="Hybrid Engineer", location="Riyadh")) == "eligible"

    def test_onsite_far_away_is_not_eligible(self):
        r = el.evaluate(job(location="Austin, TX", remote=False), GULF)
        assert r["verdict"] == "not_eligible" and "outside your work authorization" in r["reasons"][0]

    def test_unknown_mode_far_away_is_only_unknown(self):
        assert verdict(job(location="Austin, TX")) == "unknown"

    def test_relocation_target_with_sponsorship_is_eligible(self):
        assert verdict(job(location="Berlin", remote=False, description="Visa sponsorship is available."), GULF_RELOCATING) == "eligible"

    def test_relocation_target_with_relocation_package_is_eligible(self):
        assert verdict(job(location="Munich", remote=False, description="We offer a relocation package."), GULF_RELOCATING) == "eligible"

    def test_relocation_target_that_refuses_sponsorship_is_not_eligible(self):
        j = job(location="Berlin", remote=False, description="Unfortunately we cannot sponsor visas.")
        assert verdict(j, GULF_RELOCATING) == "not_eligible"

    def test_relocation_target_silent_about_sponsorship_is_unknown_when_visa_needed(self):
        assert verdict(job(location="Berlin", remote=False), GULF_RELOCATING) == "unknown"

    def test_relocation_target_when_no_visa_needed_is_eligible(self):
        p = prof.normalize({"home_country": "EG", "open_to_relocation": ["Germany"], "needs_visa": False})
        assert verdict(job(location="Berlin", remote=False), p) == "eligible"

    def test_any_location_in_a_multi_city_listing_counts(self):
        assert verdict(job(location="London, Dubai", remote=False)) == "eligible"

    def test_unrecognised_location_is_unknown(self):
        assert verdict(job(location="Somewhere nice", remote=False)) == "unknown"


class TestYourRules:

    def test_dealbreaker_blocks_even_without_a_location(self):
        p = prof.normalize({"dealbreakers": ["security clearance"]})
        r = el.evaluate(job(description="Requires security clearance."), p)
        assert r["verdict"] == "not_eligible" and "dealbreaker" in r["reasons"][0]

    def test_dealbreaker_is_whole_word(self):
        p = prof.normalize({"home_country": "AE", "dealbreakers": ["java"]})
        assert verdict(job(remote=True, restrictions="Worldwide", description="We use JavaScript."), p) == "eligible"

    def test_excluded_company(self):
        p = prof.normalize({"home_country": "AE", "excluded_companies": ["acme"]})
        assert verdict(job(remote=True, restrictions="Worldwide"), p) == "not_eligible"

    def test_work_mode_exclusion(self):
        p = prof.normalize({"home_country": "AE", "work_modes": ["remote"]})
        assert verdict(job(location="Dubai", remote=False), p) == "not_eligible"
        assert verdict(job(remote=True, restrictions="Worldwide"), p) == "eligible"

    def test_salary_below_floor_when_currency_matches(self):
        p = prof.normalize({"home_country": "AE", "salary_floor": 60000, "salary_currency": "USD"})
        j = job(location="Dubai", remote=False, salary="$30k - $40k")
        r = el.evaluate(j, p)
        assert r["verdict"] == "not_eligible" and "below your floor" in r["reasons"][0]

    def test_salary_in_another_currency_or_unknown_currency_is_ignored(self):
        p = prof.normalize({"home_country": "AE", "salary_floor": 60000, "salary_currency": "USD"})
        assert verdict(job(location="Dubai", remote=False, salary="AED 20,000 per month"), p) == "eligible"
        assert verdict(job(location="Dubai", remote=False, salary="30000-40000"), p) == "eligible"

    def test_salary_is_parsed_and_returned(self):
        r = el.evaluate(job(salary="$80k - $120k"), GULF)
        assert (r["salary_min"], r["salary_max"], r["salary_currency"]) == (80000, 120000, "USD")

    def test_timezone_outside_your_tolerance(self):
        p = prof.normalize({"home_country": "AE", "timezone_offset": 4, "max_timezone_diff": 3})
        assert verdict(job(remote=True, restrictions="Worldwide", location="UTC-8 to UTC-5"), p) == "not_eligible"
        assert verdict(job(remote=True, restrictions="Worldwide", location="UTC+1 to UTC+3"), p) == "eligible"

    def test_timezone_ignored_without_a_tolerance(self):
        assert verdict(job(remote=True, restrictions="Worldwide", location="UTC-8")) == "eligible"


class TestMissingProfile:

    def test_no_country_means_unknown_with_a_clear_prompt(self):
        r = el.evaluate(job(remote=True, restrictions="Worldwide"), prof.normalize({}))
        assert r["verdict"] == "unknown" and "add your country" in r["reasons"][0]

    def test_citizenship_requirement_is_unknown_not_eligible(self):
        r = el.evaluate(job(location="Dubai", remote=False, description="US citizens only. Security clearance required."), GULF)
        assert r["verdict"] == "unknown"

    def test_every_verdict_has_a_reason(self):
        cases = [job(), job(remote=True, restrictions="Worldwide"), job(location="Austin", remote=False)]
        for c in cases:
            assert el.evaluate(c, GULF)["reasons"]


class TestFacts:

    @pytest.mark.parametrize(
        "title,level",
        [
            ("Senior Backend Engineer", "senior"), ("Sr. Data Scientist", "senior"), ("Junior Developer", "junior"),
            ("Software Engineering Intern", "intern"), ("Engineering Manager", "lead"), ("Staff Engineer", "principal"),
            ("Director of Engineering", "executive"), ("Backend Engineer", ""), ("Seniority Coach", ""),
        ],
    )
    def test_seniority(self, title, level):
        assert el.detect_seniority(title) == level

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Visa sponsorship is available for this role.", "yes"),
            ("We can sponsor a work visa.", "yes"),
            ("No visa sponsorship.", "no"),
            ("We are unable to sponsor visas at this time.", "no"),
            ("We do not provide visa sponsorship, but relocation support is offered.", "no"),
            ("Great benefits.", ""),
        ],
    )
    def test_sponsorship(self, text, expected):
        assert el.detect_sponsorship(text) == expected

    @pytest.mark.parametrize(
        "j,mode",
        [
            (dict(title="Hybrid Engineer - Dubai"), "hybrid"),
            (dict(title="Engineer", location="On-site, Doha"), "onsite"),
            (dict(title="Engineer", remote=True), "remote"),
            (dict(title="Engineer", remote=False, location="Berlin"), "onsite"),
            (dict(title="Engineer", description="This is a fully remote position."), "remote"),
            (dict(title="Engineer", description="Hybrid role with 3 days a week in the office."), "hybrid"),
            (dict(title="Engineer"), "unknown"),
        ],
    )
    def test_work_mode(self, j, mode):
        assert el.detect_work_mode(job(**j)) == mode

    def test_remote_flag_false_from_database_is_understood(self):
        assert el.detect_work_mode(job(remote=0, location="Berlin")) == "onsite"
        assert el.detect_work_mode(job(remote=1)) == "remote"


class TestRealListingRegressions:

    def test_work_from_anywhere_in_a_country_is_a_restriction_not_worldwide(self):
        j = job(remote=True, description="Fully Remote: Work from anywhere in the U.S. Malpractice insurance included.")
        r = el.evaluate(j, GULF)
        assert r["verdict"] == "not_eligible" and "United States" in r["reasons"][0]

    def test_anywhere_in_two_countries(self):
        j = job(remote=True, description="Benefits include: work from anywhere in Canada and USA.")
        assert verdict(j) == "not_eligible"

    def test_company_mission_text_does_not_confirm_eligibility(self):
        j = job(remote=True, description="We help travelers book the best place, anywhere in the world. Join us.")
        assert verdict(j) == "unknown"

    def test_work_from_anywhere_as_a_perk_does_not_confirm_eligibility(self):
        assert verdict(job(remote=True, description="Perks: remote work from anywhere and unlimited PTO.")) == "unknown"

    def test_explicit_global_hiring_still_confirms(self):
        assert verdict(job(remote=True, description="We hire globally and are fully remote.")) == "eligible"

    def test_unrecognised_city_never_borrows_a_region_from_the_title(self):
        j = job(title="Sales Solutions Engineer - EMEA", location="Bochum", remote=False)
        assert verdict(j, GULF) != "eligible"

    def test_unrecognised_city_with_a_region_title_is_unknown_not_a_guess(self):
        j = job(title="Account Manager EMEA", location="Smallville", remote=False)
        assert verdict(j) == "unknown"

    def test_explicit_not_remote_flag_beats_remote_wording_in_the_description(self):
        j = job(location="United Kingdom", remote=False, description="This is a fully remote position within the UK.")
        r = el.evaluate(j, GULF)
        assert r["work_mode"] == "onsite" and r["verdict"] == "not_eligible"

    def test_remote_with_only_a_city_hint_is_unclear_for_outsiders(self):
        r = el.evaluate(job(remote=True, location="Paris"), GULF)
        assert r["verdict"] == "unknown" and "tied to France" in r["reasons"][0]

    def test_remote_with_a_city_hint_matching_your_country_is_eligible(self):
        assert verdict(job(remote=True, location="Berlin"), EU_PERSON) == "eligible"

    def test_company_city_on_a_worldwide_remote_board_does_not_block(self):
        assert verdict(job(remote=True, location="Menlo Park")) != "not_eligible"

    def test_reasons_quote_the_listing(self):
        r = el.evaluate(job(remote=True, description="Candidates must be based in North America or Europe."), GULF)
        assert "must be based in North America or Europe" in r["reasons"][0]

    def test_german_language_locations_are_recognised(self):
        j = job(location="Zürich, Zürich, Schweiz", remote=False)
        assert "Switzerland" in el.evaluate(j, GULF)["reasons"][0]
        assert verdict(job(location="Rostock", remote=False)) == "not_eligible"
