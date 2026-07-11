"""Divisional (varga) charts from sidereal longitude: D1, D2, D4, D7, D9, D10.

Classical Parashari rules. These are the most error-prone part of the engine —
validate the sign outputs against Jagannatha Hora before trusting predictions.
"""
from .zodiac import SIGNS, degree_in_sign, house_of, sign_index

FIRE = {"Aries", "Leo", "Sagittarius"}
EARTH = {"Taurus", "Virgo", "Capricorn"}
AIR = {"Gemini", "Libra", "Aquarius"}
WATER = {"Cancer", "Scorpio", "Pisces"}


def _sign(idx: int) -> str:
    return SIGNS[idx % 12]


def _is_odd_sign(idx: int) -> bool:
    """Aries (index 0) is the 1st sign = odd. Odd = even index."""
    return idx % 2 == 0


def d1_sign(longitude: float) -> str:
    return _sign(sign_index(longitude))


def d9_sign(longitude: float) -> str:
    """Navamsa: 9 parts of 3°20'. Continuous formula equals the element rule."""
    return _sign(int(longitude // (30.0 / 9.0)))


def d10_sign(longitude: float) -> str:
    """Dashamsa: 10 parts of 3°. Odd sign -> from itself; even -> from 9th."""
    idx = sign_index(longitude)
    part = int(degree_in_sign(longitude) // 3.0)
    start = idx if _is_odd_sign(idx) else (idx + 8)
    return _sign(start + part)


def d2_sign(longitude: float) -> str:
    """Hora: two halves. Odd sign -> Leo then Cancer; even -> Cancer then Leo."""
    idx = sign_index(longitude)
    first_half = degree_in_sign(longitude) < 15.0
    if _is_odd_sign(idx):
        return "Leo" if first_half else "Cancer"
    return "Cancer" if first_half else "Leo"


def d4_sign(longitude: float) -> str:
    """Chaturthamsa: 4 parts of 7°30', running through the kendras (1,4,7,10)."""
    idx = sign_index(longitude)
    part = int(degree_in_sign(longitude) // 7.5)
    return _sign(idx + [0, 3, 6, 9][part])


def d7_sign(longitude: float) -> str:
    """Saptamsa: 7 parts. Odd sign -> from itself; even -> from 7th."""
    idx = sign_index(longitude)
    part = int(degree_in_sign(longitude) // (30.0 / 7.0))
    start = idx if _is_odd_sign(idx) else (idx + 6)
    return _sign(start + part)


_VARGA_FN = {"D1": d1_sign, "D2": d2_sign, "D4": d4_sign, "D7": d7_sign, "D9": d9_sign, "D10": d10_sign}


def divisional_chart(varga: str, planet_longitudes: dict, asc_longitude: float):
    """Build one divisional chart {lagna, planets:{name:{sign,house}}}.

    `planet_longitudes` maps planet name -> longitude (D1 longitude).
    House numbers are whole-sign from the divisional lagna.
    """
    fn = _VARGA_FN[varga]
    lagna = fn(asc_longitude)
    planets = {}
    for name, lon in planet_longitudes.items():
        sign = fn(lon)
        planets[name] = {"sign": sign, "house": house_of(sign, lagna)}
    return {"lagna": lagna, "planets": planets}
