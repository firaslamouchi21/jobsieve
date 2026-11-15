import json
import os

import pytest

from jobsieve import profile as prof


class TestDefaults:

    def test_missing_file_gives_defaults(self):
        p = prof.load()
        assert p["home_country"] == "" and p["needs_visa"] is False
        assert p["work_modes"] == ["remote", "hybrid", "onsite"]
        assert not prof.exists() and not prof.has_location(p)


class TestSaveAndLoad:

    def test_round_trip(self):
        prof.save({"home_country": "Saudi Arabia", "keywords": "python, data engineer", "salary_floor": "60000"})
        p = prof.load()
        assert p["home_country"] == "SA"
        assert p["keywords"] == ["python", "data engineer"]
        assert p["salary_floor"] == 60000.0
        assert prof.exists()

    def test_update_changes_only_given_fields(self):
        prof.save({"home_country": "AE", "dealbreakers": ["clearance"]})
        prof.update({"needs_visa": True})
        p = prof.load()
        assert p["home_country"] == "AE" and p["dealbreakers"] == ["clearance"] and p["needs_visa"] is True

    def test_write_is_atomic(self):
        prof.save({"home_country": "AE"})
        assert "profile.json.tmp" not in os.listdir(os.environ["DATA_DIR"])

    def test_corrupt_file_is_reported_not_ignored(self):
        with open(prof.profile_path(), "w") as f:
            f.write("{nope")
        with pytest.raises(prof.ProfileError, match="unreadable"):
            prof.load()


class TestValidation:

    def test_unknown_field_is_rejected(self):
        with pytest.raises(prof.ProfileError, match="unknown profile field"):
            prof.normalize({"hobby": "x"})

    def test_unknown_place_is_rejected_with_its_name(self):
        with pytest.raises(prof.ProfileError, match="Atlantis"):
            prof.normalize({"work_authorization": ["EU", "Atlantis"]})

    def test_home_country_must_be_one_country(self):
        with pytest.raises(prof.ProfileError, match="single country"):
            prof.normalize({"home_country": "GCC"})

    @pytest.mark.parametrize("field,value", [("timezone_offset", 20), ("max_timezone_diff", -1), ("salary_floor", "abc")])
    def test_numbers_are_checked(self, field, value):
        with pytest.raises(prof.ProfileError):
            prof.normalize({field: value})

    def test_bad_currency_and_choices(self):
        with pytest.raises(prof.ProfileError):
            prof.normalize({"salary_currency": "dollars"})
        with pytest.raises(prof.ProfileError, match="not allowed"):
            prof.normalize({"seniority": ["wizard"]})
        with pytest.raises(prof.ProfileError, match="not allowed"):
            prof.normalize({"work_modes": ["beach"]})

    def test_lists_are_cleaned_and_deduplicated(self):
        p = prof.normalize({"dealbreakers": " Clearance ;clearance, relocation  required\n"})
        assert p["dealbreakers"] == ["Clearance", "relocation required"]

    def test_cv_length_limit(self):
        with pytest.raises(prof.ProfileError, match="longer than"):
            prof.normalize({"cv_text": "x" * (prof.MAX_CV_CHARS + 1)})


class TestCountrySets:

    def test_work_countries_combine_home_and_authorization_regions(self):
        p = prof.normalize({"home_country": "EG", "work_authorization": ["GCC"]})
        assert prof.work_countries(p) == {"EG", "AE", "SA", "QA", "KW", "BH", "OM"}

    def test_relocation_excludes_countries_already_allowed(self):
        p = prof.normalize({"home_country": "AE", "open_to_relocation": ["AE", "Germany"]})
        assert prof.relocation_countries(p) == {"DE"}

    def test_fingerprint_ignores_search_settings_but_not_eligibility(self):
        base = prof.normalize({"home_country": "AE"})
        assert prof.fingerprint(base) == prof.fingerprint(prof.normalize({"home_country": "AE", "keywords": ["python"]}))
        assert prof.fingerprint(base) != prof.fingerprint(prof.normalize({"home_country": "SA"}))
