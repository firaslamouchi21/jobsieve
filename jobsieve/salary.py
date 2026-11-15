import re

CURRENCY_CODES = {
    "USD", "EUR", "GBP", "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "EGP", "JOD", "MAD", "TND",
    "INR", "PKR", "BDT", "LKR", "CAD", "AUD", "NZD", "SGD", "HKD", "CHF", "SEK", "NOK", "DKK",
    "PLN", "CZK", "HUF", "RON", "ZAR", "NGN", "KES", "GHS", "BRL", "MXN", "ARS", "COP", "CLP",
    "JPY", "CNY", "KRW", "MYR", "IDR", "PHP", "THB", "VND", "TRY", "ILS", "UAH", "RUB",
}
SYMBOLS = {"€": "EUR", "£": "GBP", "₹": "INR", "$": "USD", "¥": "JPY", "₦": "NGN", "₺": "TRY"}
PERIODS = (
    (re.compile(r"/\s*h(?:ou)?r\b|per\s+hour|hourly|an\s+hour", re.I), 2080),
    (re.compile(r"/\s*day\b|per\s+day|daily", re.I), 260),
    (re.compile(r"/\s*week\b|per\s+week|weekly", re.I), 52),
    (re.compile(r"/\s*mo(?:nth)?\b|per\s+month|monthly|a\s+month|\bpm\b", re.I), 12),
    (re.compile(r"/\s*y(?:ea)?r\b|per\s+(?:year|annum)|annual|yearly|p\.a\.|\bpa\b", re.I), 1),
)
NUMBER = re.compile(r"(\d{1,3}(?:[,\s]\d{3})+|\d+(?:\.\d+)?)\s*([kKmM])?(?![\w%])")
SCALE = {"k": 1_000, "m": 1_000_000}
MAX_SANE_ANNUAL = 10_000_000


def detect_currency(text: str) -> str:
    for token in re.findall(r"\b[A-Za-z]{3}\b", text):
        if token.upper() in CURRENCY_CODES:
            return token.upper()
    for symbol, code in SYMBOLS.items():
        if symbol in text:
            return code
    return ""


def detect_multiplier(text: str) -> tuple[int, bool]:
    for pattern, factor in PERIODS:
        if pattern.search(text):
            return factor, True
    return 1, False


def parse_salary(text: str | None) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    found = []
    for match in NUMBER.finditer(raw):
        digits = re.sub(r"[,\s]", "", match.group(1))
        suffix = (match.group(2) or "").lower()
        found.append((float(digits), suffix))
        if len(found) == 2:
            break
    if not found:
        return None
    if len(found) == 2 and not found[0][1] and found[1][1] and found[0][0] < 1000:
        found[0] = (found[0][0], found[1][1])
    values = [number * SCALE.get(suffix, 1) for number, suffix in found]
    factor, explicit_period = detect_multiplier(raw)
    annual = sorted(v * factor for v in values)
    if not explicit_period and annual[-1] < 1000:
        return None
    if annual[-1] > MAX_SANE_ANNUAL:
        return None
    return {"min": annual[0], "max": annual[-1], "currency": detect_currency(raw)}
