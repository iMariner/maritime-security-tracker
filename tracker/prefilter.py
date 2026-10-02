"""Keyword pre-filter: only items that look like a ship attack go to the AI step."""
from __future__ import annotations

import re
from functools import lru_cache

from .common import load_yaml


@lru_cache(maxsize=1)
def _patterns() -> dict:
    cfg = load_yaml("keywords.yaml")
    # Match at the start of a word only, so "port" does not hit "report" and "mine" does not hit "determine".
    return {
        key: re.compile(r"\b(?:" + "|".join(re.escape(t.lower()) for t in cfg.get(key, [])) + ")", re.I)
        for key in ("vessel_terms", "attack_terms", "region_terms")
    }


def is_candidate(item: dict) -> bool:
    text = f"{item.get('title', '')}\n{item.get('text', '')}".lower()
    p = _patterns()
    if not (p["vessel_terms"].search(text) and p["attack_terms"].search(text)):
        return False
    if item.get("require_region_term") and not p["region_terms"].search(text):
        return False
    return True
