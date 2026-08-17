"""Deterministic local classification of provider documents.

the provider labels every document, so we map that label to a clean, searchable
filename summary. Rules live in the editable document_rules.json.

Categories: Statement, Year-End Summary, Tax Document, Insurance Document,
Other. Order of checks matters: tax before year-end before insurance before
statement, because a year-end summary or insurance billing statement can
contain the word "statement" but belongs under its own category.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_RULES_FILENAME = "document_rules.json"


def _rules_path() -> Path:
    """The rules file lives in the APP's folder, not the package - each
    provider tunes its own keywords and ships them alongside its code."""
    from .storage import spec
    return spec().rules_path or (spec().project_dir / DEFAULT_RULES_FILENAME)

STATEMENT = "Statement"
YEAR_END = "Year-End Summary"
TAX = "Tax Document"
INSURANCE = "Insurance Document"
OTHER = "Other Document"

HIGH = "High"
MEDIUM = "Medium"
LOW = "Low"


def load_rules(path: Optional[Path] = None) -> dict:
    with open(path or _rules_path(), "r", encoding="utf-8") as f:
        rules = json.load(f)
    rules.setdefault("tax_rules", [])
    rules.setdefault("year_end_rules", [])
    rules.setdefault("insurance_rules", [])
    rules.setdefault("statement_rules", [])
    rules.setdefault("skip_patterns", [])
    return rules


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text or "", re.I) is not None


def classify_document(title: str, rules: Optional[dict] = None) -> Tuple[str, str, str]:
    """Map a document's displayed title to (category, summary, confidence)."""
    rules = rules or load_rules()
    text = re.sub(r"\s+", " ", title or "").strip()
    if not text:
        return OTHER, "Document", LOW

    for rule in rules["tax_rules"]:
        if _matches(rule["pattern"], text):
            return TAX, rule["summary"], HIGH
    for rule in rules["year_end_rules"]:
        if _matches(rule["pattern"], text):
            return YEAR_END, rule["summary"], HIGH
    for rule in rules["insurance_rules"]:
        if _matches(rule["pattern"], text):
            return INSURANCE, rule["summary"], HIGH
    for rule in rules["statement_rules"]:
        if _matches(rule["pattern"], text):
            return STATEMENT, rule["summary"], HIGH

    # Unlabeled but recognizable
    if _matches(r"\b(1099|1098|1042|5498|w-?2|tax)\b", text):
        return TAX, "Tax Document", MEDIUM
    if _matches(r"year.?end\s+summary|annual\s+summary|year\s+in\s+review", text):
        return YEAR_END, "Year-End Summary", MEDIUM
    if _matches(r"\b(policy|declaration|dec\s*page|insurance|coverage|"
                r"auto|homeowner|renter)\b", text):
        return INSURANCE, "Insurance Document", MEDIUM
    if _matches(r"\bstatement\b", text):
        return STATEMENT, "Account Statement", MEDIUM
    return OTHER, "Document", LOW


def wanted(category: str, config: dict) -> bool:
    """Is this category in scope for the configured run?"""
    types = config.get("document_types") or [STATEMENT, TAX, INSURANCE]
    return category in types


def should_skip(title: str, rules: Optional[dict] = None) -> bool:
    """Documents explicitly out of scope (marketing, disclosures, etc.)."""
    rules = rules or load_rules()
    for pattern in rules["skip_patterns"]:
        if _matches(pattern, title or ""):
            return True
    return False
