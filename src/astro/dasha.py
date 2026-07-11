"""Vimshottari Dasha: Mahadasha / Antardasha / Pratyantardasha with exact dates.

Anchored to the Moon's exact nakshatra position at birth. A one-day error here
corrupts every predictive response, so year length is fixed at 365.25 days and
every sub-period is derived proportionally (lord_years / 120).
"""
from datetime import datetime, timedelta

from .config import YEAR_DAYS
from .zodiac import (
    DASHA_SEQUENCE, DASHA_YEARS, NAKSHATRA_SPAN, nakshatra_of, nakshatra_lord, norm360,
)


def _years_to_delta(years: float) -> timedelta:
    return timedelta(days=years * YEAR_DAYS)


def _sequence_from(lord: str):
    """The 9-lord Vimshottari cycle starting at `lord`."""
    start = DASHA_SEQUENCE.index(lord)
    return [DASHA_SEQUENCE[(start + i) % 9] for i in range(9)]


def _subperiods(parent_lord: str, parent_start: datetime, parent_years: float):
    """Split a period ruled by parent_lord into its nine sub-periods.

    Sub-period length = parent_years * sub_lord_years / 120.
    Returns list of {planet, start, end} (datetimes).
    """
    periods = []
    cursor = parent_start
    for sub_lord in _sequence_from(parent_lord):
        span_years = parent_years * DASHA_YEARS[sub_lord] / 120.0
        end = cursor + _years_to_delta(span_years)
        periods.append({"planet": sub_lord, "start": cursor, "end": end, "years": span_years})
        cursor = end
    return periods


def mahadashas(birth_dt: datetime, moon_longitude: float):
    """Full Mahadasha timeline covering ~120 years from birth.

    The first MD is the Moon's birth-nakshatra lord, entered partway through:
    its start is projected *before* birth so that the elapsed fraction matches
    how far the Moon has traversed its nakshatra.
    """
    _, _, nak_idx = nakshatra_of(moon_longitude)
    first_lord = nakshatra_lord(nak_idx)

    within = norm360(moon_longitude) - nak_idx * NAKSHATRA_SPAN
    elapsed_fraction = within / NAKSHATRA_SPAN            # portion of first MD already gone

    first_years = DASHA_YEARS[first_lord]
    md_start = birth_dt - _years_to_delta(first_years * elapsed_fraction)

    timeline = []
    cursor = md_start
    for lord in _sequence_from(first_lord):
        years = DASHA_YEARS[lord]
        end = cursor + _years_to_delta(years)
        timeline.append({"planet": lord, "start": cursor, "end": end, "years": years})
        cursor = end
    return timeline


def _find_active(periods, target: datetime):
    for p in periods:
        if p["start"] <= target < p["end"]:
            return p
    return None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def current_dashas(birth_dt: datetime, moon_longitude: float, target: datetime, upcoming_pd: int = 3):
    """Return the MD/AD/PD active at `target`, plus the next `upcoming_pd` PDs.

    Output shape matches natal_chart['dashas'] in the spec.
    """
    mds = mahadashas(birth_dt, moon_longitude)
    md = _find_active(mds, target) or mds[-1]

    ads = _subperiods(md["planet"], md["start"], md["years"])
    ad = _find_active(ads, target) or ads[-1]

    pds = _subperiods(ad["planet"], ad["start"], ad["years"])
    pd = _find_active(pds, target) or pds[-1]

    pd_idx = pds.index(pd)
    upcoming = pds[pd_idx + 1: pd_idx + 1 + upcoming_pd]
    # If this AD runs out of PDs, roll into the next AD's PDs.
    if len(upcoming) < upcoming_pd:
        ad_idx = ads.index(ad)
        next_ads = ads[ad_idx + 1:]
        for nad in next_ads:
            for np_ in _subperiods(nad["planet"], nad["start"], nad["years"]):
                upcoming.append(np_)
                if len(upcoming) >= upcoming_pd:
                    break
            if len(upcoming) >= upcoming_pd:
                break

    def rec(p):
        return {"planet": p["planet"], "start": _fmt(p["start"]), "end": _fmt(p["end"])}

    return {
        "current_MD": rec(md),
        "current_AD": rec(ad),
        "current_PD": rec(pd),
        "upcoming_PDs": [rec(p) for p in upcoming],
    }
