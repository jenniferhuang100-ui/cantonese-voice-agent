import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "racquets.json"


def search_racquets(budget_max_hkd=None, level=None, play_style=None):
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        racquets = json.load(f)

    results = []
    for r in racquets:
        if not r.get("in_stock"):
            continue
        if budget_max_hkd is not None and r["price_hkd"] > budget_max_hkd:
            continue
        if level is not None and level not in r["best_for"]:
            continue
        if play_style is not None and play_style not in r["best_for"]:
            continue
        results.append(r)

    return results
