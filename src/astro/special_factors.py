"""Chara karakas and arudha padas (special_factors block)."""
from .zodiac import SIGNS, degree_in_sign, house_of, sign_to_index


def _karakas(planets):
    """Rank the seven planets (excluding nodes) by degree-within-sign, descending.

    Highest = Atmakaraka, second = Amatyakaraka, lowest = Darakaraka.
    """
    ranked = sorted(
        [p for p in planets if p not in ("Rahu", "Ketu")],
        key=lambda name: degree_in_sign(planets[name]["longitude"]),
        reverse=True,
    )
    return ranked


def _arudha(house_num, house_lords, planets, lagna_sign):
    """Arudha of a house: project the lord's distance from the house, forward again.

    Standard exception: if the arudha lands in the same house or the 7th from it,
    move it 10 houses further.
    """
    lord = house_lords[str(house_num)]
    lord_sign = planets[lord]["sign"]
    house_sign_idx = (sign_to_index(lagna_sign) + house_num - 1) % 12
    lord_sign_idx = sign_to_index(lord_sign)
    distance = (lord_sign_idx - house_sign_idx) % 12          # houses from the house to its lord
    arudha_idx = (lord_sign_idx + distance) % 12
    # Exception: arudha coincident with (1st) or opposite (7th) the source house.
    if (arudha_idx - house_sign_idx) % 12 in (0, 6):
        arudha_idx = (arudha_idx + 9) % 12
    sign = SIGNS[arudha_idx]
    return {"sign": sign, "house": house_of(sign, lagna_sign)}


def special_factors(planets, house_lords, lagna_sign):
    ranked = _karakas(planets)
    return {
        "atmakaraka": ranked[0],
        "amatyakaraka": ranked[1],
        "darakaraka": ranked[-1],
        "upapada_lagna": _arudha(12, house_lords, planets, lagna_sign),
        "arudha_lagna": _arudha(1, house_lords, planets, lagna_sign),
    }
