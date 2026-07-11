"""Yoga detection (Part 5), with the spec's bugs fixed:

  #1  Raj Yoga exchange branch: implemented properly via sign lords.
  #2  Neechabhanga exaltation lords corrected (Jupiter->Moon, Saturn->Venus).
  #3  Neechabhanga D9 cancellation implemented using the passed navamsa chart.
  #4  fame 'connected' heuristic kept but documented.

Detection is programmatic; the AI only interprets.
"""
from .zodiac import (
    DEBILITATION, EXALTATION, PLANET_OWN_SIGNS, SIGN_LORDS,
)

KENDRA = [1, 4, 7, 10]
TRINE = [1, 5, 9]


def _kendra_diff(a_house, b_house):
    return (a_house - b_house) % 12


def detect_gajakesari(planets):
    moon_h = planets["Moon"]["house"]
    jup_h = planets["Jupiter"]["house"]
    diff = _kendra_diff(jup_h, moon_h)
    if diff in (0, 3, 6, 9):
        return [{
            "name": "Gajakesari",
            "formed_by": f"Jupiter in {jup_h}H is in kendra from Moon in {moon_h}H",
            "strength": "strong" if diff in (0, 6) else "moderate",
            "houses_activated": [jup_h],
            "relevant_domains": ["career", "relationship", "wealth", "spirituality"],
            "mentioned_in_session": False,
        }]
    return []


def detect_kemadruma(planets):
    moon_h = planets["Moon"]["house"]
    second = (moon_h % 12) + 1
    twelfth = ((moon_h - 2) % 12) + 1
    flanking = [
        n for n, p in planets.items()
        if n not in ("Moon", "Sun", "Rahu", "Ketu") and p["house"] in (second, twelfth)
    ]
    if not flanking:
        return [{
            "name": "Kemadruma",
            "formed_by": f"No planets in 2nd ({second}H) or 12th ({twelfth}H) from Moon",
            "strength": "strong",
            "houses_activated": [moon_h],
            "relevant_domains": ["health", "relationship", "wealth"],
            "mentioned_in_session": False,
        }]
    return []


def _in_exchange(a, b, planets):
    """True if planets a and b occupy each other's owned signs (parivartana)."""
    a_signs = PLANET_OWN_SIGNS.get(a, [])
    b_signs = PLANET_OWN_SIGNS.get(b, [])
    return planets[a]["sign"] in b_signs and planets[b]["sign"] in a_signs


def detect_raj_yoga(planets, house_lords):
    yogas = []
    for th in TRINE:
        tl = house_lords[str(th)]
        for kh in KENDRA:
            if th == kh:
                continue
            kl = house_lords[str(kh)]
            if tl == kl:
                continue
            tlh, klh = planets[tl]["house"], planets[kl]["house"]
            if tlh == klh:
                yogas.append({
                    "name": "Raj_Yoga",
                    "formed_by": f"{tl} (lord {th}H) conjunct {kl} (lord {kh}H) in {tlh}H",
                    "strength": "strong",
                    "houses_activated": [tlh],
                    "relevant_domains": ["career", "wealth", "status"],
                    "mentioned_in_session": False,
                })
            elif _in_exchange(tl, kl, planets):
                yogas.append({
                    "name": "Raj_Yoga",
                    "formed_by": f"{tl} (lord {th}H) and {kl} (lord {kh}H) in mutual sign exchange",
                    "strength": "strong",
                    "houses_activated": [tlh, klh],
                    "relevant_domains": ["career", "wealth", "status"],
                    "mentioned_in_session": False,
                })
    return yogas


def detect_full_trine_raja_yoga(planets, house_lords):
    l1, l5, l9 = house_lords["1"], house_lords["5"], house_lords["9"]
    h1, h5, h9 = planets[l1]["house"], planets[l5]["house"], planets[l9]["house"]
    if h1 == h5 == h9:
        return [{
            "name": "Full_Trine_Raja_Yoga",
            "formed_by": f"Lords of 1H ({l1}), 5H ({l5}), 9H ({l9}) all conjunct in {h1}H",
            "strength": "strongest",
            "houses_activated": [h1],
            "relevant_domains": ["career", "wealth", "fame", "status"],
            "mentioned_in_session": False,
        }]
    yogas = []
    for a, b, ha, hb in [(l1, l5, 1, 5), (l1, l9, 1, 9), (l5, l9, 5, 9)]:
        if planets[a]["house"] == planets[b]["house"]:
            yogas.append({
                "name": "Partial_Trine_Connection",
                "formed_by": f"Lords of {ha}H ({a}) and {hb}H ({b}) conjunct in {planets[a]['house']}H",
                "strength": "strong",
                "houses_activated": [planets[a]["house"]],
                "relevant_domains": ["career", "wealth"],
                "mentioned_in_session": False,
            })
    return yogas


def detect_dhana_yoga(planets, house_lords):
    houses = [2, 5, 9, 11]
    pos = {h: planets[house_lords[str(h)]]["house"] for h in houses}
    yogas = []
    for i, h1 in enumerate(houses):
        for h2 in houses[i + 1:]:
            if pos[h1] == pos[h2]:
                yogas.append({
                    "name": "Dhana_Yoga",
                    "formed_by": f"Lords of {h1}H and {h2}H conjunct in {pos[h1]}H",
                    "strength": "strong",
                    "houses_activated": [pos[h1]],
                    "relevant_domains": ["wealth", "income"],
                    "mentioned_in_session": False,
                })
    return yogas


def detect_neechabhanga(planets, house_lords, d9=None):
    yogas = []
    for planet, deb_sign in DEBILITATION.items():
        if planets[planet]["sign"] != deb_sign:
            continue
        sign_lord = SIGN_LORDS[deb_sign]
        exalt_lord = SIGN_LORDS[EXALTATION[planet]]     # correct: Jupiter->Moon, Saturn->Venus
        ph = planets[planet]["house"]
        triggers = []
        for lord in {sign_lord, exalt_lord}:
            if lord in planets:
                lh = planets[lord]["house"]
                if lh in KENDRA:
                    triggers.append(f"{lord} in kendra ({lh}H)")
                if lh == ph:
                    triggers.append(f"{lord} conjunct {planet} in {ph}H")
        # #3 D9 cancellation: debilitated planet exalted in navamsa.
        if d9 and d9["planets"].get(planet, {}).get("sign") == EXALTATION[planet]:
            triggers.append(f"{planet} exalted in Navamsa (D9)")
        if triggers:
            yogas.append({
                "name": "Neechabhanga_Raja_Yoga",
                "formed_by": f"{planet} debilitated in {deb_sign}; cancelled by: {'; '.join(triggers)}",
                "strength": "strong" if len(triggers) > 1 else "moderate",
                "houses_activated": [ph],
                "relevant_domains": ["career", "wealth", "status"],
                "mentioned_in_session": False,
            })
    return yogas


def detect_parivartana(planets, house_lords):
    yogas = []
    checked = set()
    for name, data in planets.items():
        if name in ("Rahu", "Ketu"):
            continue
        lord = SIGN_LORDS[data["sign"]]
        if lord == name or lord in ("Rahu", "Ketu"):
            continue
        pair = frozenset((name, lord))
        if pair in checked:
            continue
        if data["sign"] in PLANET_OWN_SIGNS.get(lord, []) and planets[lord]["sign"] in PLANET_OWN_SIGNS.get(name, []):
            checked.add(pair)
            h1, h2 = data["house"], planets[lord]["house"]
            yogas.append({
                "name": "Parivartana_Yoga",
                "formed_by": f"{name} in {data['sign']} (ruled by {lord}); {lord} in {planets[lord]['sign']} (ruled by {name})",
                "houses_exchanged": [h1, h2],
                "houses_activated": [h1, h2],
                "combined_meaning": f"{h1}H and {h2}H themes merge and mutually support each other",
                "strength": "strong",
                "relevant_domains": [],
                "mentioned_in_session": False,
            })
    return yogas


def detect_viparita_raja_yoga(planets, house_lords):
    dusthana = [6, 8, 12]
    yogas = []
    for h in dusthana:
        lord = house_lords[str(h)]
        lh = planets[lord]["house"]
        if lh in dusthana and lh != h:
            yogas.append({
                "name": "Viparita_Raja_Yoga",
                "formed_by": f"Lord of {h}H ({lord}) placed in {lh}H (another dusthana)",
                "strength": "moderate",
                "houses_activated": [lh],
                "relevant_domains": ["career", "wealth", "transformation"],
                "mentioned_in_session": False,
            })
    return yogas


def detect_pancha_mahapurusha(planets):
    configs = {
        "Jupiter": {"name": "Hamsa", "own": ["Sagittarius", "Pisces"], "exalt": "Cancer"},
        "Venus": {"name": "Malavya", "own": ["Taurus", "Libra"], "exalt": "Pisces"},
        "Mars": {"name": "Ruchaka", "own": ["Aries", "Scorpio"], "exalt": "Capricorn"},
        "Mercury": {"name": "Bhadra", "own": ["Gemini", "Virgo"], "exalt": "Virgo"},
        "Saturn": {"name": "Shasha", "own": ["Capricorn", "Aquarius"], "exalt": "Libra"},
    }
    yogas = []
    for planet, cfg in configs.items():
        p = planets[planet]
        if p["house"] in KENDRA and (p["sign"] in cfg["own"] or p["sign"] == cfg["exalt"]):
            cond = "exalted" if p["sign"] == cfg["exalt"] else "in own sign"
            yogas.append({
                "name": f"Pancha_Mahapurusha_{cfg['name']}",
                "formed_by": f"{planet} {cond} in {p['sign']} ({p['house']}H — kendra)",
                "strength": "strong",
                "houses_activated": [p["house"]],
                "relevant_domains": ["career", "fame", "status", "wealth"],
                "mentioned_in_session": False,
            })
    return yogas


def detect_budhaditya(planets):
    if planets["Sun"]["house"] == planets["Mercury"]["house"]:
        combust = planets["Mercury"]["combust"]
        note = " (Mercury combust — results modified but yoga still active)" if combust else ""
        return [{
            "name": "Budhaditya_Yoga",
            "formed_by": f"Sun and Mercury conjunct in {planets['Sun']['house']}H{note}",
            "strength": "moderate" if combust else "strong",
            "houses_activated": [planets["Sun"]["house"]],
            "relevant_domains": ["career", "communication", "intellect"],
            "mentioned_in_session": False,
        }]
    return []


def detect_vesi(planets):
    sun_h = planets["Sun"]["house"]
    second = (sun_h % 12) + 1
    qualifying = [
        n for n, p in planets.items()
        if n not in ("Sun", "Moon", "Rahu", "Ketu") and p["house"] == second
    ]
    if qualifying:
        return [{
            "name": "Vesi_Yoga",
            "formed_by": f"{', '.join(qualifying)} in 2nd from Sun ({second}H)",
            "strength": "moderate",
            "houses_activated": [second],
            "relevant_domains": ["career", "communication"],
            "mentioned_in_session": False,
        }]
    return []


def detect_fame_combination(planets, house_lords):
    fame_houses = [5, 7, 10, 11]
    positions = [planets[house_lords[str(h)]]["house"] for h in fame_houses]
    rahu_h = planets["Rahu"]["house"]
    connected = len(set(positions)) < len(positions)     # #4: any two fame lords share a house
    if connected and rahu_h in (7, 10, 11):
        return [{
            "name": "Fame_Combination",
            "formed_by": f"5th/7th/10th/11th lords interconnected; Rahu in {rahu_h}H",
            "strength": "strong",
            "houses_activated": sorted(set(positions)),
            "relevant_domains": ["fame", "career", "social_media"],
            "mentioned_in_session": False,
        }]
    return []


def detect_all_yogas(planets, house_lords, d9=None):
    yogas = []
    yogas += detect_gajakesari(planets)
    yogas += detect_kemadruma(planets)
    yogas += detect_raj_yoga(planets, house_lords)
    yogas += detect_full_trine_raja_yoga(planets, house_lords)
    yogas += detect_dhana_yoga(planets, house_lords)
    yogas += detect_neechabhanga(planets, house_lords, d9)
    yogas += detect_parivartana(planets, house_lords)
    yogas += detect_viparita_raja_yoga(planets, house_lords)
    yogas += detect_pancha_mahapurusha(planets)
    yogas += detect_budhaditya(planets)
    yogas += detect_vesi(planets)
    yogas += detect_fame_combination(planets, house_lords)
    return yogas
