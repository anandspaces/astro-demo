"""Domain -> chart-slice selection (Part 9). Inject only relevant slices."""
import copy

DOMAIN_CHART_MAP = {
    "career": ["lagna", "planets", "house_lords", "aspects", "D10", "dashas",
               "transits.Saturn", "transits.Jupiter", "special_factors.amatyakaraka", "yogas"],
    "relationship": ["lagna", "planets", "house_lords", "aspects", "D9", "dashas",
                     "transits.Jupiter", "transits.Saturn", "special_factors.darakaraka",
                     "special_factors.upapada_lagna", "yogas"],
    "wealth": ["lagna", "planets", "house_lords", "aspects", "D2", "dashas",
               "transits.Jupiter", "yogas"],
    "health": ["lagna", "planets", "house_lords", "aspects", "dashas", "transits.Saturn"],
    "property": ["lagna", "planets", "house_lords", "D4", "dashas"],
    "children": ["lagna", "planets", "house_lords", "D7", "dashas"],
    "spirituality": ["lagna", "planets", "house_lords", "dashas", "special_factors.atmakaraka"],
    "travel": ["lagna", "planets", "house_lords", "dashas", "transits"],
    "fame": ["lagna", "planets", "house_lords", "aspects", "D10", "dashas", "transits", "yogas"],
    "forecast": ["lagna", "planets", "house_lords", "aspects", "dashas", "transits", "special_factors"],
    "general": ["lagna", "planets", "house_lords", "dashas", "transits"],
}


def _set_nested(dst, path, value):
    keys = path.split(".")
    node = dst
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


def _resolve(chart, path):
    """Resolve a chart path. Divisional keys (D9/D10/...) live under divisional_charts."""
    if path in ("D1", "D2", "D4", "D7", "D9", "D10"):
        return ["divisional_charts", path], chart.get("divisional_charts", {}).get(path)
    keys = path.split(".")
    node = chart
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return keys, None
        node = node[k]
    return keys, node


def get_chart_slice(chart, domain):
    slice_ = {"lagna": chart.get("lagna"), "meta": chart.get("meta")}
    for path in DOMAIN_CHART_MAP.get(domain, DOMAIN_CHART_MAP["general"]):
        keys, value = _resolve(chart, path)
        if value is None:
            continue
        _set_nested(slice_, ".".join(keys), copy.deepcopy(value))
    return slice_


def merge_chart_slices(a, b):
    """Deep-merge two slices (multi-domain queries)."""
    out = copy.deepcopy(a)

    def _merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _merge(dst[k], v)
            else:
                dst.setdefault(k, v)
    _merge(out, b)
    return out
