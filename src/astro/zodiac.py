"""Zodiac reference data and pure helpers shared across the engine.

All longitudes are sidereal (Lahiri) degrees in [0, 360).
"""

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
    "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
    "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
    "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
}

# Signs each planet rules (used for lord_of computation).
PLANET_OWN_SIGNS = {
    "Sun": ["Leo"],
    "Moon": ["Cancer"],
    "Mars": ["Aries", "Scorpio"],
    "Mercury": ["Gemini", "Virgo"],
    "Jupiter": ["Sagittarius", "Pisces"],
    "Venus": ["Taurus", "Libra"],
    "Saturn": ["Capricorn", "Aquarius"],
}

EXALTATION = {
    "Sun": "Aries", "Moon": "Taurus", "Mars": "Capricorn",
    "Mercury": "Virgo", "Jupiter": "Cancer", "Venus": "Pisces",
    "Saturn": "Libra",
}

DEBILITATION = {
    "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer",
    "Mercury": "Pisces", "Jupiter": "Capricorn", "Venus": "Virgo",
    "Saturn": "Aries",
}

# 27 nakshatras with their Vimshottari dasha lord (9-lord cycle repeats 3x).
NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

# Vimshottari lord order and mahadasha lengths in years (total 120).
DASHA_SEQUENCE = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}

NAKSHATRA_SPAN = 360.0 / 27.0          # 13.333... degrees
PADA_SPAN = NAKSHATRA_SPAN / 4.0       # 3.333... degrees

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
NODES = ["Rahu", "Ketu"]


def norm360(deg: float) -> float:
    """Normalise a longitude into [0, 360)."""
    return deg % 360.0


def sign_index(longitude: float) -> int:
    """0-based sign index (Aries=0) from a longitude."""
    return int(norm360(longitude) // 30)


def longitude_to_sign(longitude: float) -> str:
    return SIGNS[sign_index(longitude)]


def degree_in_sign(longitude: float) -> float:
    return norm360(longitude) % 30.0


def sign_to_index(sign: str) -> int:
    return SIGNS.index(sign)


def house_of(sign: str, lagna_sign: str) -> int:
    """Whole-sign house number (1-12) of `sign` given the ascendant sign."""
    return ((sign_to_index(sign) - sign_to_index(lagna_sign)) % 12) + 1


def sign_to_house(sign: str, reference_sign: str) -> int:
    """House number of `sign` counted from `reference_sign` (whole sign)."""
    return house_of(sign, reference_sign)


def nakshatra_of(longitude: float):
    """Return (nakshatra_name, pada 1-4, index 0-26) for a longitude."""
    lon = norm360(longitude)
    idx = int(lon // NAKSHATRA_SPAN)
    within = lon - idx * NAKSHATRA_SPAN
    pada = int(within // PADA_SPAN) + 1
    return NAKSHATRAS[idx], pada, idx


def nakshatra_lord(nak_index: int) -> str:
    """Vimshottari dasha lord for a nakshatra index (0-26)."""
    return DASHA_SEQUENCE[nak_index % 9]


def lords_of_houses(planet: str, lagna_sign: str):
    """House numbers this planet rules for the given ascendant."""
    return [house_of(sign, lagna_sign) for sign in PLANET_OWN_SIGNS.get(planet, [])]


def angular_distance(a: float, b: float) -> float:
    """Shortest arc between two longitudes, 0-180."""
    d = abs(norm360(a) - norm360(b))
    return 360.0 - d if d > 180.0 else d
