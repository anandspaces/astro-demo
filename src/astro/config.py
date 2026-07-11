"""Swiss Ephemeris configuration. Import side-effect sets Lahiri ayanamsa once."""
import swisseph as swe

AYANAMSA_NAME = "Lahiri"
HOUSE_SYSTEM = b"W"          # Whole Sign
YEAR_DAYS = 365.25           # Vimshottari year length

_INITIALISED = False


def init_ephemeris():
    """Set sidereal (Lahiri) mode. Safe to call multiple times."""
    global _INITIALISED
    if not _INITIALISED:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        _INITIALISED = True


# Swiss Ephemeris planet constants. Rahu = Mean Node; Ketu derived as +180.
SWE_PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE,
}

# Minimal offline city table so charts can be built without a geocoding service.
# lat, lon in decimal degrees (N/E positive). Extend or pass explicit coords.
CITY_COORDS = {
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "bengaluru": (12.9716, 77.5946),
    "bangalore": (12.9716, 77.5946),
    "chennai": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
    "hyderabad": (17.3850, 78.4867),
    "pune": (18.5204, 73.8567),
    "london": (51.5074, -0.1278),
    "new york": (40.7128, -74.0060),
}
