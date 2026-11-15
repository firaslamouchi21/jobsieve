import pytest

from jobsieve import places


class TestFindPlaces:

    def test_countries_and_cities(self):
        assert places.find_places("Based in Dubai or Riyadh") == {"AE", "SA"}

    def test_aliases(self):
        assert places.find_places("UAE only") == {"AE"}
        assert places.find_places("open to candidates in the UK") == {"GB"}

    def test_uppercase_us_is_the_country_but_lowercase_us_is_not(self):
        assert places.find_places("US only") == {"US"}
        assert places.find_places("U.S. based") == {"US"}
        assert places.find_places("tell us about yourself") == set()

    def test_regions_expand_to_countries(self):
        found = places.find_places("remote within the GCC")
        assert {"AE", "SA", "QA", "KW", "BH", "OM"} == found

    def test_europe_excludes_the_middle_east(self):
        found = places.find_places("Europe only")
        assert "DE" in found and "GB" in found
        assert "AE" not in found and "EG" not in found

    def test_longest_match_wins(self):
        assert places.find_places("North America") == {"US", "CA", "MX"}
        assert "BR" not in places.find_places("North America")

    def test_emea_covers_gulf_and_europe_but_not_us(self):
        found = places.find_places("EMEA")
        assert {"AE", "DE", "ZA", "EG"} <= found and "US" not in found

    def test_ambiguous_names_are_not_matched(self):
        assert places.find_places("Georgia") == set()
        assert places.find_places("Atlanta, Georgia") == {"US"}
        assert places.find_places("Birmingham, Alabama") == set()
        assert places.find_places("a nice team") == set()

    def test_word_boundaries(self):
        assert places.find_places("Indiana") == set()
        assert places.find_places("Omani nationals") == set()


class TestWorldwide:

    @pytest.mark.parametrize("text", ["Worldwide", "Work from anywhere", "Anywhere in the world", "Global"])
    def test_detected(self, text):
        assert places.is_worldwide(text)

    def test_not_detected_in_restricted_text(self):
        assert not places.is_worldwide("United States only")


class TestExpand:

    def test_codes_names_and_regions(self):
        assert places.expand(["ae", "Saudi Arabia", "GCC"]) >= {"AE", "SA", "QA"}

    def test_region_with_spaces(self):
        assert "FR" in places.expand(["european union"]) and "FR" in places.expand(["EU"])

    def test_empty_and_unknown(self):
        assert places.expand([]) == set() and places.expand(["", "Atlantis"]) == set()

    def test_names_helper(self):
        assert places.names({"AE", "SA"}) == "Saudi Arabia, United Arab Emirates"
        assert places.names(places.region_countries("EU")).endswith("more")


class TestRegionsCanBeSwitchedOff:

    def test_regions_are_skipped_when_asked(self):
        assert places.find_places("EMEA", regions=False) == set()
        assert places.find_places("Dubai or EMEA", regions=False) == {"AE"}

    def test_native_names_and_small_cities(self):
        assert places.find_places("Deutschland") == {"DE"}
        assert places.find_places("Schweiz") == {"CH"}
        assert places.find_places("Rostock") == {"DE"}
        assert places.find_places("York") == {"GB"}
