import pytest

from jobsieve.salary import parse_salary


class TestParseSalary:

    @pytest.mark.parametrize(
        "text,low,high,currency",
        [
            ("$80k - $120k", 80000, 120000, "USD"),
            ("80000-120000", 80000, 120000, ""),
            ("£50,000 - £65,000", 50000, 65000, "GBP"),
            ("AED 25,000 per month", 300000, 300000, "AED"),
            ("$45/hr", 93600, 93600, "USD"),
            ("80-120k", 80000, 120000, ""),
            ("SAR 18000 - 24000 monthly", 216000, 288000, "SAR"),
            ("$1.2M", 1200000, 1200000, "USD"),
        ],
    )
    def test_ranges_symbols_and_periods(self, text, low, high, currency):
        result = parse_salary(text)
        assert (result["min"], result["max"], result["currency"]) == (low, high, currency)

    @pytest.mark.parametrize("text", ["", None, "competitive", "negotiable", "up to 10% bonus", "35", "EUR 70.000", "₹12,00,000"])
    def test_unusable_values_give_none(self, text):
        assert parse_salary(text) is None

    def test_absurd_values_are_rejected(self):
        assert parse_salary("99999999999") is None

    def test_reversed_range_is_ordered(self):
        result = parse_salary("$120k - $80k")
        assert (result["min"], result["max"]) == (80000, 120000)
