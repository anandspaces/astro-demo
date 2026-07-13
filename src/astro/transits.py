"""Transit positions (Part 6). Fixes bug #5: sign_to_house takes reference SIGNS,
not house numbers."""
from datetime import datetime

from .ephemeris import all_planet_longitudes, to_julian_day
from .zodiac import longitude_to_sign, sign_to_house

SLOW_PLANETS = ["Jupiter", "Saturn", "Rahu", "Ketu"]

# Sade Sati phase by Saturn's house counted from the natal Moon (12/1/2 = the 7.5-year
# transit); Ashtama Sani is Saturn transiting the 8th from the natal Moon.
_SADE_SATI_PHASE = {12: "rising", 1: "peak", 2: "setting"}


def _jd_for_date(dt: datetime) -> float:
    return to_julian_day(dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), "UTC")


def saturn_transit_flags(saturn_house_from_moon: int) -> dict:
    """Sade Sati / Ashtama Sani status from Saturn's whole-sign house from natal Moon."""
    phase = _SADE_SATI_PHASE.get(saturn_house_from_moon)
    return {
        "sade_sati": phase is not None,
        "sade_sati_phase": phase,
        "ashtama_sani": saturn_house_from_moon == 8,
    }


def current_transits(target: datetime, lagna_sign: str, moon_sign: str):
    """Transit block for natal_chart['transits'] (all nine grahas), including the
    pre-computed Saturn transit_flags (Sade Sati / Ashtama Sani)."""
    jd = _jd_for_date(target)
    longs = all_planet_longitudes(jd)
    out = {"calculated_for": target.strftime("%Y-%m-%d")}
    for name, data in longs.items():
        sign = longitude_to_sign(data["longitude"])
        out[name] = {
            "sign": sign,
            "house_from_lagna": sign_to_house(sign, lagna_sign),
            "house_from_moon": sign_to_house(sign, moon_sign),
        }
    out["transit_flags"] = saturn_transit_flags(out["Saturn"]["house_from_moon"])
    return out


def get_transits_for_dasha_window(start_date: datetime, end_date: datetime, lagna_sign: str, moon_sign: str):
    """Slow-planet transits at the midpoint of a dasha window."""
    mid = start_date + (end_date - start_date) / 2
    jd = _jd_for_date(mid)
    longs = all_planet_longitudes(jd)
    out = {}
    for name in SLOW_PLANETS:
        sign = longitude_to_sign(longs[name]["longitude"])
        out[name] = {
            "sign": sign,
            "house_from_lagna": sign_to_house(sign, lagna_sign),
            "house_from_moon": sign_to_house(sign, moon_sign),
        }
    return out


def calculate_timing_confidence(dasha_support, transit_support, divisional_support):
    score = sum([bool(dasha_support), bool(transit_support), bool(divisional_support)])
    if score == 3:
        return "high"
    if score == 2:
        return "medium"
    if score == 1:
        return "low"
    return "none"
