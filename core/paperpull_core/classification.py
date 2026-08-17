"""Local, deterministic purchase classification.

Item names never leave this machine. Classification is driven by the
editable keyword rules in category_rules.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import Classification, Item

DEFAULT_RULES_FILENAME = "category_rules.json"


def _rules_path() -> Path:
    """The rules file lives in the APP's folder, not the package - each
    provider tunes its own keywords and ships them alongside its code."""
    from .storage import spec
    return spec().rules_path or (spec().project_dir / DEFAULT_RULES_FILENAME)

HIGH = "High"
MEDIUM = "Medium"
LOW = "Low"
MIXED = "Mixed Purchases"


def load_rules(path: Optional[Path] = None) -> dict:
    with open(path or _rules_path(), "r", encoding="utf-8") as f:
        rules = json.load(f)
    rules.setdefault("categories", {})
    rules.setdefault("significant_items", {})
    rules.setdefault("combined", {})
    return rules


def _parse_money(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"-?\$?\s*([\d,]+(?:\.\d{1,2})?)", str(text))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_qty(text: str) -> float:
    if not text:
        return 1.0
    m = re.search(r"(\d+(?:\.\d+)?)", str(text))
    try:
        return max(1.0, float(m.group(1))) if m else 1.0
    except ValueError:
        return 1.0


def _item_weight(item: Item) -> float:
    """Weight an item by its dollar contribution when known, else quantity."""
    total = _parse_money(item.line_total)
    if total is not None and total > 0:
        return total
    unit = _parse_money(item.unit_price)
    qty = _parse_qty(item.quantity)
    if unit is not None and unit > 0:
        return unit * qty
    return qty  # fall back to quantity as a weak weight


def _keyword_matches(name_lower: str, keyword: str) -> bool:
    kw = keyword.lower().strip()
    if not kw:
        return False
    if " " in kw or len(kw) > 4:
        return kw in name_lower
    # short single words: require word boundaries to avoid e.g. "pen" in "opened"
    return re.search(rf"\b{re.escape(kw)}\b", name_lower) is not None


def match_category(name: str, rules: dict) -> Optional[str]:
    """Return the best-matching category for a single item name.
    Longest matching keyword wins across all categories."""
    name_lower = (name or "").lower()
    best: Tuple[int, Optional[str]] = (0, None)
    for category, keywords in rules["categories"].items():
        for kw in keywords:
            if _keyword_matches(name_lower, kw) and len(kw) > best[0]:
                best = (len(kw), category)
    return best[1]


def match_significant_item(name: str, rules: dict) -> Optional[str]:
    """If the item is a recognizable major product (Vacuum Cleaner, TV...),
    return its short ordinary description."""
    name_lower = (name or "").lower()
    best: Tuple[int, Optional[str]] = (0, None)
    for label, keywords in rules["significant_items"].items():
        for kw in keywords:
            if _keyword_matches(name_lower, kw) and len(kw) > best[0]:
                best = (len(kw), label)
    return best[1]


def _combined_label(cat_a: str, cat_b: str, rules: dict) -> Optional[str]:
    for key, label in rules["combined"].items():
        parts = {p.strip() for p in key.split("|")}
        if parts == {cat_a, cat_b}:
            return label
    return None


def classify_items(items: List[Item], rules: Optional[dict] = None) -> Classification:
    """Classify a purchase from its items. Returns summary + confidence.

    Considers keyword matches, dollar/quantity weights, whether one item is
    clearly primary, and the proportion of each category.
    """
    rules = rules or load_rules()
    items = [i for i in items if (i.name or "").strip()]
    if not items:
        return Classification(MIXED, LOW, "No item names extracted")

    weights = [_item_weight(i) for i in items]
    total_weight = sum(weights) or 1.0

    # --- primary-product detection -------------------------------------
    # If one item dominates the purchase value, describe the purchase by it.
    if len(items) == 1:
        sig = match_significant_item(items[0].name, rules)
        if sig:
            return Classification(sig, HIGH, "Single significant item")
    else:
        top_idx = max(range(len(items)), key=lambda i: weights[i])
        if weights[top_idx] / total_weight >= 0.6:
            sig = match_significant_item(items[top_idx].name, rules)
            if sig:
                return Classification(
                    sig, HIGH, "Primary product with minor accessories")

    # --- category proportions ------------------------------------------
    cat_weight: Dict[str, float] = {}
    matched_weight = 0.0
    for item, w in zip(items, weights):
        cat = match_category(item.name, rules)
        if cat:
            cat_weight[cat] = cat_weight.get(cat, 0.0) + w
            matched_weight += w

    if not cat_weight:
        return Classification(MIXED, LOW, "No keyword matches")

    ranked = sorted(cat_weight.items(), key=lambda kv: kv[1], reverse=True)
    top_cat, top_w = ranked[0]
    top_share = top_w / total_weight
    matched_share = matched_weight / total_weight

    # dominant category
    if top_share >= 0.7:
        conf = HIGH if matched_share >= 0.7 else MEDIUM
        return Classification(top_cat, conf, f"Dominant category ({top_share:.0%})")
    if top_share >= 0.5:
        return Classification(top_cat, MEDIUM, f"Majority category ({top_share:.0%})")

    # two important related categories -> combined summary
    if len(ranked) >= 2:
        second_cat, second_w = ranked[1]
        second_share = second_w / total_weight
        if top_share >= 0.3 and second_share >= 0.25 and (top_share + second_share) >= 0.7:
            label = _combined_label(top_cat, second_cat, rules)
            if label is None and len(f"{top_cat} and {second_cat}".split()) <= 4:
                label = f"{top_cat} and {second_cat}"
            if label:
                return Classification(label, MEDIUM, "Two important categories")

    # weak plurality
    if matched_share >= 0.5:
        return Classification(top_cat, LOW, f"Weak plurality ({top_share:.0%})")
    return Classification(MIXED, LOW, "No meaningful dominant category")
