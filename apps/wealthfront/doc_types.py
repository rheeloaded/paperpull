"""Deterministic local classification of Wealthfront documents.

Unlike the shopping projects, nothing has to be guessed from item keywords:
Wealthfront labels every document ("Monthly Statement", "1099-B", ...), so we
map that label to a clean, searchable filename summary. Rules live in the
editable document_rules.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Tuple

RULES_PATH = Path(__file__).resolve().parent / "document_rules.json"

STATEMENT = "Statement"
TAX = "Tax Document"
OTHER = "Other Document"

HIGH = "High"
MEDIUM = "Medium"
LOW = "Low"


def load_rules(path: Optional[Path] = None) -> dict:
    with open(path or RULES_PATH, "r", encoding="utf-8") as f:
        rules = json.load(f)
    rules.setdefault("statement_rules", [])
    rules.setdefault("tax_rules", [])
    rules.setdefault("skip_patterns", [])
    return rules


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text or "", re.I) is not None


def classify_document(title: str, rules: Optional[dict] = None) -> Tuple[str, str, str]:
    """Map a document's displayed title to (category, summary, confidence).

    category: Statement | Tax Document | Other Document
    summary : the filename phrase, e.g. "Monthly Statement", "1099-B"
    """
    rules = rules or load_rules()
    text = re.sub(r"\s+", " ", title or "").strip()
    if not text:
        return OTHER, "Document", LOW

    for rule in rules["tax_rules"]:
        if _matches(rule["pattern"], text):
            return TAX, rule["summary"], HIGH
    for rule in rules["statement_rules"]:
        if _matches(rule["pattern"], text):
            return STATEMENT, rule["summary"], HIGH

    # Unlabeled but clearly statement/tax-ish
    if _matches(r"\bstatement\b", text):
        return STATEMENT, "Account Statement", MEDIUM
    if _matches(r"\b(1099|1042|5498|tax)\b", text):
        return TAX, "Tax Document", MEDIUM
    return OTHER, "Document", LOW


def wanted(category: str, config: dict) -> bool:
    """Is this category in scope for the configured run?"""
    types = config.get("document_types") or [STATEMENT, TAX]
    return category in types


def should_skip(title: str, rules: Optional[dict] = None) -> bool:
    """Documents explicitly out of scope (e.g. trade confirmations)."""
    rules = rules or load_rules()
    for pattern in rules["skip_patterns"]:
        if _matches(pattern, title or ""):
            return True
    return False
