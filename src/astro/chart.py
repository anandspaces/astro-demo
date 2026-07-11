"""Full natal chart assembly (Part 2 structure). Entry point: build_natal_chart."""
from datetime import datetime

from .aspects import between_planets, calculate_aspects
from .combustion import is_combust
from .dasha import current_dashas
from .divisional import divisional_chart
from .ephemeris import all_planet_longitudes, ascendant_longitude, resolve_coords, to_julian_day
from .special_factors import special_factors
from .transits import current_transits
from .yogas import detect_all_yogas
from .zodiac import (
    SIGN_LORDS, SIGNS, degree_in_sign, house_of, lords_of_houses,
    longitude_to_sign, nakshatra_of, sign_to_index,
)

DIVISIONALS = ["D9", "D10", "D2", "D4", "D7"]


def _house_lords(lagna_sign: str):
    """Map each house 1-12 (by its sign from the lagna) to that sign's ruler."""
    start = sign_to_index(lagna_sign)
    return {str(h + 1): SIGN_LORDS[SIGNS[(start + h) % 12]] for h in range(12)}


def build_natal_chart(meta: dict, target: datetime = None, lat=None, lon=None) -> dict:
    """Build the complete natal chart dict.

    meta must contain: name, dob (YYYY-MM-DD), tob (HH:MM), pob, timezone.
    Optional lat/lon override the offline city lookup.
    target defaults to now-ish for dashas/transits (pass explicitly for determinism).
    """
    target = target or datetime.utcnow()
    lat, lon = resolve_coords(meta.get("pob"), lat if lat is not None else meta.get("lat"),
                              lon if lon is not None else meta.get("lon"))

    jd = to_julian_day(meta["dob"], meta["tob"], meta["timezone"])
    asc_lon = ascendant_longitude(jd, lat, lon)
    lagna_sign = longitude_to_sign(asc_lon)

    raw = all_planet_longitudes(jd)
    sun_lon = raw["Sun"]["longitude"]

    planets = {}
    longitudes = {}
    for name, data in raw.items():
        lon_p = data["longitude"]
        longitudes[name] = lon_p
        sign = longitude_to_sign(lon_p)
        nak, pada, _ = nakshatra_of(lon_p)
        combust = is_combust(name, lon_p, sun_lon, data["retrograde"])
        planets[name] = {
            "sign": sign,
            "house": house_of(sign, lagna_sign),
            "degree": round(degree_in_sign(lon_p), 2),
            "longitude": round(lon_p, 4),
            "nakshatra": nak,
            "pada": pada,
            "retrograde": data["retrograde"],
            "combust": combust,
            "degrees_from_sun": None if name in ("Rahu", "Ketu") else round((lon_p - sun_lon) % 360.0, 2),
            "lord_of": lords_of_houses(name, lagna_sign),
        }

    house_lords = _house_lords(lagna_sign)

    divisionals = {}
    for varga in DIVISIONALS:
        divisionals[varga] = divisional_chart(varga, longitudes, asc_lon)

    aspects = {
        "on_houses": calculate_aspects(planets),
        "between_planets": between_planets(planets),
    }

    dashas = current_dashas(
        birth_dt=datetime.strptime(f"{meta['dob']} {meta['tob']}", "%Y-%m-%d %H:%M"),
        moon_longitude=raw["Moon"]["longitude"],
        target=target,
    )

    factors = special_factors(planets, house_lords, lagna_sign)
    yogas = detect_all_yogas(planets, house_lords, d9=divisionals.get("D9"))
    transits = current_transits(target, lagna_sign, planets["Moon"]["sign"])

    return {
        "meta": {**meta, "ayanamsa": "Lahiri"},
        "lagna": {
            "sign": lagna_sign,
            "degree": round(degree_in_sign(asc_lon), 2),
            "lord": SIGN_LORDS[lagna_sign],
        },
        "planets": planets,
        "house_lords": house_lords,
        "aspects": aspects,
        "divisional_charts": divisionals,
        "dashas": dashas,
        "transits": transits,
        "special_factors": factors,
        "yogas": yogas,
    }
