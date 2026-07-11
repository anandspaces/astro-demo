"""House-based Vedic aspects (Part 4).

Every planet aspects the 7th from itself. Mars adds 4/8, Jupiter 5/9, Saturn 3/10.
Net effective aspects: Mars 4/7/8, Jupiter 5/7/9, Saturn 3/7/10, others 7.
"""
SPECIAL_ASPECTS = {
    "Mars": [4, 8],
    "Jupiter": [5, 9],
    "Saturn": [3, 10],
}


def _house_at_offset(planet_house: int, offset: int) -> int:
    """House `offset`-th from planet_house, counting inclusively (offset=1 is self)."""
    return ((planet_house - 1 + offset - 1) % 12) + 1


def calculate_aspects(planets_dict):
    """Return {house_str: [aspecting planets]} for houses 1-12."""
    on_houses = {str(i): [] for i in range(1, 13)}
    for name, data in planets_dict.items():
        h = data["house"]
        on_houses[str(_house_at_offset(h, 7))].append(name)
        for offset in SPECIAL_ASPECTS.get(name, []):
            on_houses[str(_house_at_offset(h, offset))].append(name)
    return on_houses


def between_planets(planets_dict):
    """Planet-to-planet aspect records (same house = conjunction, excluded)."""
    records = []
    houses = {name: d["house"] for name, d in planets_dict.items()}
    for name, data in planets_dict.items():
        aspected_houses = {7: "7th"}
        for off in SPECIAL_ASPECTS.get(name, []):
            aspected_houses[off] = f"{off}th"
        targets = {_house_at_offset(data["house"], off): label for off, label in aspected_houses.items()}
        for other, other_house in houses.items():
            if other == name:
                continue
            if other_house in targets:
                records.append({
                    "aspecting": name,
                    "aspected_planet": other,
                    "aspect_type": targets[other_house],
                    "from_house": data["house"],
                    "to_house": other_house,
                })
    return records
