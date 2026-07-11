"""Compact labelled chart block for the Generator (Part 12).

Canonical name is `format_chart_for_generator` (resolves bug #17's naming drift);
`format_chart_minimal` is the token-pressure variant (Part 14).
"""


def _planet_line(name, p):
    tags = []
    if p.get("retrograde"):
        tags.append("Retro:YES ℞" if name not in ("Rahu", "Ketu") else "Retro:always")
    else:
        tags.append("Retro:No")
    if p.get("combust"):
        tags.append("Combust:YES")
    lords = " ".join(f"{h}H" for h in p.get("lord_of", [])) or "-"
    nak = f"{p.get('nakshatra','')} P{p.get('pada','')}"
    return f"{name:<8}→ {p['sign']:<11} {p['house']}H | {nak:<20} | Lords: {lords:<7} | {' | '.join(tags)}"


def format_chart_for_generator(slice_) -> str:
    lines = []
    meta = slice_.get("meta", {})
    lines.append(
        f"NATAL CHART — {meta.get('name','')} | DOB: {meta.get('dob','')} | "
        f"TOB: {meta.get('tob','')} | POB: {meta.get('pob','')} | Ayanamsa: Lahiri"
    )
    lag = slice_.get("lagna", {})
    if lag:
        lines.append(f"\nLagna: {lag.get('sign')} ({lag.get('degree')}°) | Lagna Lord: {lag.get('lord')}")

    planets = slice_.get("planets")
    if planets:
        lines.append("\nPLANETS:")
        for name in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]:
            if name in planets:
                lines.append(_planet_line(name, planets[name]))

    d = slice_.get("dashas")
    if d:
        md, ad, pd = d.get("current_MD", {}), d.get("current_AD", {}), d.get("current_PD", {})
        lines.append(
            f"\nCURRENT DASHA: {md.get('planet')} MD ({md.get('start')}–{md.get('end')}) → "
            f"{ad.get('planet')} AD ({ad.get('start')}–{ad.get('end')}) → "
            f"{pd.get('planet')} PD ({pd.get('start')}–{pd.get('end')})"
        )
        up = d.get("upcoming_PDs", [])
        if up:
            lines.append("UPCOMING PDs: " + " | ".join(f"{u['planet']} ({u['start']}–{u['end']})" for u in up))

    asp = slice_.get("aspects", {}).get("on_houses") if slice_.get("aspects") else None
    if asp:
        lines.append("\nASPECTS ON HOUSES:")
        for h in ["1", "4", "7", "10"]:
            if asp.get(h):
                lines.append(f"{h}H aspected by: {', '.join(asp[h])}")

    dv = slice_.get("divisional_charts", {})
    for varga in ("D9", "D10", "D2", "D4", "D7"):
        if varga in dv:
            planets_str = ", ".join(f"{n}→{d['sign']} {d['house']}H" for n, d in list(dv[varga]["planets"].items())[:4])
            lines.append(f"{varga}: Lagna {dv[varga]['lagna']} | {planets_str}")

    tr = slice_.get("transits")
    if tr:
        lines.append(f"\nTRANSITS (as of {tr.get('calculated_for')}):")
        for name in ["Jupiter", "Saturn", "Rahu", "Ketu"]:
            if name in tr:
                t = tr[name]
                lines.append(f"{name} → {t['sign']} | {t['house_from_lagna']}H from Lagna | {t['house_from_moon']}H from Moon")

    sf = slice_.get("special_factors")
    if sf:
        bits = [f"{k}: {v}" for k, v in sf.items() if isinstance(v, str)]
        if bits:
            lines.append("\nSPECIAL FACTORS: " + " | ".join(bits))

    yogas = slice_.get("yogas")
    if yogas:
        fresh = [y for y in yogas if not y.get("mentioned_in_session")]
        if fresh:
            lines.append("\nDETECTED YOGAS (not yet mentioned): " + ", ".join(y["name"] for y in fresh))

    return "\n".join(lines)


def format_chart_minimal(slice_) -> str:
    """Trimmed variant for token pressure: lagna, planets, dasha only."""
    lines = []
    lag = slice_.get("lagna", {})
    lines.append(f"Lagna: {lag.get('sign')} | Lord: {lag.get('lord')}")
    planets = slice_.get("planets", {})
    for name, p in planets.items():
        lines.append(f"{name}: {p['sign']} {p['house']}H")
    d = slice_.get("dashas", {})
    if d:
        md, ad, pd = d.get("current_MD", {}), d.get("current_AD", {}), d.get("current_PD", {})
        lines.append(f"Dasha: {md.get('planet')} MD → {ad.get('planet')} AD → {pd.get('planet')} PD")
    return "\n".join(lines)
