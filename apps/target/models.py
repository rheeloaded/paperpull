"""Data models for the Target receipt downloader.

Everything here is plain dataclasses + an explicit processing-state machine.
No network or browser logic lives in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional

ONLINE = "Online"
IN_STORE = "In-Store"
PURCHASE_TYPES = (ONLINE, IN_STORE)


class State(str, Enum):
    """Processing states a purchase moves through (see spec section 20)."""

    DISCOVERED = "Discovered"
    DETAILS_EXTRACTED = "Details Extracted"
    RECEIPT_LOCATED = "Receipt Located"
    PDF_SAVED = "PDF Saved"
    PDF_VERIFIED = "PDF Verified"
    COMPLETED = "Completed"
    NEEDS_MANUAL_REVIEW = "Needs Manual Review"
    NO_RECEIPT_AVAILABLE = "No Receipt Available"
    CANCELED = "Canceled"
    FAILED = "Failed"


# States that mean "do not reprocess" (provided the PDF also checks out).
DONE_STATES = {
    State.COMPLETED.value,
    State.NO_RECEIPT_AVAILABLE.value,
    State.CANCELED.value,
}


@dataclass
class Item:
    """One purchased line item."""

    name: str = ""
    quantity: str = ""
    unit_price: str = ""
    line_total: str = ""
    status: str = ""
    return_status: str = ""
    fulfillment: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class Purchase:
    """One Online order or In-store transaction."""

    purchase_type: str = ONLINE
    purchase_date: str = ""  # YYYY-MM-DD (order-placed / transaction date)
    order_number: str = ""  # Target order / receipt / transaction identifier
    total: str = ""
    status: str = ""
    details_url: str = ""
    receipt_url: str = ""
    store_info: str = ""
    fulfillment: str = ""
    items: List[Item] = field(default_factory=list)
    discovered_at: str = ""
    state: str = State.DISCOVERED.value
    summary: str = ""
    confidence: str = ""
    pdf_filename: str = ""
    pdf_path: str = ""
    document_type: str = "Receipt"  # Receipt | Invoice
    receipt_count: int = 1
    notes: str = ""

    @property
    def key(self) -> str:
        """Unique internal key: Purchase Type + Target identifier."""
        return f"{self.purchase_type}:{self.order_number}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["items"] = [i if isinstance(i, dict) else asdict_item(i) for i in d["items"]]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Purchase":
        items = [Item.from_dict(i) for i in d.get("items", [])]
        kwargs = {
            k: d.get(k, cls.__dataclass_fields__[k].default)
            for k in cls.__dataclass_fields__
            if k != "items"
        }
        # receipt_count default handling (field default is 1)
        kwargs["receipt_count"] = d.get("receipt_count", 1)
        return cls(items=items, **kwargs)


def asdict_item(i) -> dict:
    return i if isinstance(i, dict) else asdict(i)


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    size_bytes: int = 0
    page_count: int = 0
    text_token_found: bool = False


@dataclass
class Classification:
    summary: str
    confidence: str  # High | Medium | Low
    notes: str = ""
