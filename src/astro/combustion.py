"""Combustion detection (Part 3). Parashari orbs; Venus is 10°/8°, not 15°."""
from .zodiac import angular_distance

COMBUSTION_ORBS = {
    "Moon": {"direct": 12, "retrograde": 12},
    "Mars": {"direct": 17, "retrograde": 17},
    "Mercury": {"direct": 14, "retrograde": 12},
    "Jupiter": {"direct": 11, "retrograde": 11},
    "Venus": {"direct": 10, "retrograde": 8},
    "Saturn": {"direct": 15, "retrograde": 15},
}


def is_combust(planet_name, planet_longitude, sun_longitude, is_retrograde) -> bool:
    if planet_name in ("Sun", "Rahu", "Ketu"):
        return False
    diff = angular_distance(planet_longitude, sun_longitude)
    orb = COMBUSTION_ORBS[planet_name]["retrograde" if is_retrograde else "direct"]
    return diff <= orb
