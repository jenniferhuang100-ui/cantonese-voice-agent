import json
import os

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "racquets.json")

# Map Cantonese filter values to the English tags used in racquets.json's best_for lists
LEVEL_MAP = {"初": "beginner", "中": "intermediate", "高": "advanced"}
STYLE_MAP = {"底線": "baseliner", "上網": "net-rush", "雙打": "doubles"}


def _filter(racquets, budget_max_hkd, level, play_style):
    out = []
    for r in racquets:
        if not r.get("in_stock", True):
            continue
        if budget_max_hkd and r.get("price_hkd", 0) > budget_max_hkd:
            continue
        if level:
            mapped_lvl = LEVEL_MAP.get(level[0], level)
            if not any(mapped_lvl in b for b in r.get("best_for", [])):
                continue
        if play_style:
            mapped_style = STYLE_MAP.get(play_style, play_style)
            if not any(mapped_style in b for b in r.get("best_for", [])):
                continue
        out.append(r)
    return out


def load_catalog():
    """Full catalog as-is from racquets.json — the single source of truth,
    also served to the storefront grid via the backend's /catalog endpoint."""
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def search_racquets(budget_max_hkd=None, level=None, play_style=None):
    if not os.path.exists(DATA_PATH):
        return {"error": "Catalog data file missing."}

    racquets = load_catalog()

    # Exact filters first; if that's empty, relax play_style, then level, then
    # budget, in that order, so the catalog never hands the model a dead end
    # (e.g. today every "beginner" pick has zero results for any play style,
    # since neither beginner racquet is tagged baseliner/net-rush/doubles).
    for b, l, s in [
        (budget_max_hkd, level, play_style),
        (budget_max_hkd, level, None),
        (budget_max_hkd, None, None),
        (None, None, None),
    ]:
        results = _filter(racquets, b, l, s)
        if results:
            return results
    return []
