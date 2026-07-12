"""Basic engine sanity tests. Run: PYTHONPATH=src python -m pytest tests/ (or plain python).

NOTE: These assert internal consistency, NOT astrological accuracy. The mandatory
validation against Jagannatha Hora (≥5 charts: ascendant, planets, nakshatras,
dasha dates) is a manual step — see docs/research/01-chart-engine.md.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from astro import build_natal_chart
from astro.combustion import is_combust
from astro.dasha import mahadashas
from astro.zodiac import DASHA_YEARS

META = {"name": "Test", "dob": "1990-01-15", "tob": "08:30",
        "pob": "Delhi, India", "timezone": "Asia/Kolkata"}


def test_chart_structure():
    c = build_natal_chart(META, target=datetime(2026, 7, 8))
    for key in ("lagna", "planets", "house_lords", "aspects", "divisional_charts",
                "dashas", "transits", "special_factors", "yogas"):
        assert key in c, f"missing {key}"
    assert len(c["planets"]) == 9
    assert set(c["house_lords"].keys()) == {str(i) for i in range(1, 13)}


def test_nodes_always_retrograde():
    c = build_natal_chart(META, target=datetime(2026, 7, 8))
    assert c["planets"]["Rahu"]["retrograde"] is True
    assert c["planets"]["Ketu"]["retrograde"] is True
    assert c["planets"]["Rahu"]["degrees_from_sun"] is None


def test_dasha_total_is_120_years():
    dts = mahadashas(datetime(1990, 1, 15, 8, 30), 130.0)
    span_years = (dts[-1]["end"] - dts[0]["start"]).days / 365.25
    assert abs(span_years - 120) < 0.5
    assert sum(DASHA_YEARS.values()) == 120


def test_combustion_venus_orb():
    # Venus 9° from Sun, direct -> combust (orb 10); retrograde -> not (orb 8).
    assert is_combust("Venus", 9.0, 0.0, is_retrograde=False) is True
    assert is_combust("Venus", 9.0, 0.0, is_retrograde=True) is False
    assert is_combust("Sun", 0.0, 0.0, is_retrograde=False) is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All engine tests passed.")
