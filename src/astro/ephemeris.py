"""Swiss Ephemeris wrappers: birth timestamp -> Julian Day, planetary longitudes,
ascendant. Everything sidereal (Lahiri)."""
from datetime import datetime

import pytz
import swisseph as swe

from .config import CITY_COORDS, HOUSE_SYSTEM, SWE_PLANETS, init_ephemeris
from .zodiac import norm360


def resolve_coords(pob: str, lat=None, lon=None):
    """Return (lat, lon). Explicit coords win; otherwise look up the city table."""
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    if pob:
        key = pob.split(",")[0].strip().lower()
        if key in CITY_COORDS:
            return CITY_COORDS[key]
    raise ValueError(
        f"Could not resolve coordinates for place of birth '{pob}'. "
        "Pass explicit lat/lon (a geocoding step is out of scope for the engine)."
    )


def to_julian_day(dob: str, tob: str, timezone: str) -> float:
    """Local birth date/time + IANA timezone -> Julian Day in Universal Time."""
    tz = pytz.timezone(timezone)
    naive = datetime.strptime(f"{dob} {tob}", "%Y-%m-%d %H:%M")
    local = tz.localize(naive)
    utc = local.astimezone(pytz.utc)
    hour = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    return swe.julday(utc.year, utc.month, utc.day, hour, swe.GREG_CAL)


def planet_longitude(jd: float, planet: str):
    """Return (longitude, speed) for a planet name. Handles Rahu/Ketu."""
    init_ephemeris()
    flags = swe.FLG_SIDEREAL | swe.FLG_SPEED
    if planet == "Ketu":
        lon, spd = planet_longitude(jd, "Rahu")
        return norm360(lon + 180.0), spd
    xx, _ = swe.calc_ut(jd, SWE_PLANETS[planet], flags)
    return norm360(xx[0]), xx[3]


def all_planet_longitudes(jd: float):
    """Dict planet -> {'longitude', 'speed', 'retrograde'} for all nine grahas."""
    out = {}
    for name in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]:
        lon, spd = planet_longitude(jd, name)
        # Nodes are always treated as retrograde regardless of computed speed.
        retro = True if name in ("Rahu", "Ketu") else spd < 0
        out[name] = {"longitude": lon, "speed": spd, "retrograde": retro}
    return out


def ascendant_longitude(jd: float, lat: float, lon: float) -> float:
    """Sidereal ascendant longitude using Whole Sign house request."""
    init_ephemeris()
    _, ascmc = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM, swe.FLG_SIDEREAL)
    return norm360(ascmc[0])
