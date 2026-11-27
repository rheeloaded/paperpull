"""Ubiquiti Store (store.ui.com) order receipt discovery and PDF retrieval.

How the store's order history works, mapped on 2026-11-26 against a
signed-in US account with seventeen orders, one of them on the Canadian
store:

* Order History is a section of ``https://store.ui.com/us/en/account``.
  The page reads its orders from a GraphQL endpoint,
  ``https://ecomm.svc.ui.com/graphql``, operation ``GetCustomerOrders``
  (``storefrontOrders(input: {limit, offset})``), which answers with
  ``pagination.total`` and the orders of every store the account has
  bought from. VERIFIED, limit 50 answered all seventeen at once.
* A second operation, ``GetCustomerHistoricalOrders``
  (``storefrontHistoricalOrders``), lists orders of the store's earlier
  system. It was empty on the account mapped, so how such an order's
  receipt is fetched is unknown, and the app counts them and says so
  rather than guessing.
* Each order's status page (``/us/en/order/<order id>/status``) carries a
  "View Invoice" link to ``https://ecomm.svc.ui.com/invoice/<order id>
  ?locale=en``. With the browser's session it answers ``application/pdf``,
  ``inline; filename=<order number>.pdf``. Without one it answers an HTML
  page. VERIFIED for US and Canadian orders.
* A paid order's PDF is headed "Receipt / Tax Invoice". A cancelled
  order's is headed "Unpaid Invoice" with "Payment status: Failed", which
  is not a receipt, so only orders whose payment shows Completed are
  listed. The others are counted and said.
* The PDF prints "Invoice Date: YYYY/MM/DD" in the store's local time: an
  order made at 00:04 UTC on Dec 12 printed Dec 11. The order's creation
  time is converted to US Eastern time, and the check of a PDF also takes
  the UTC day, so an order made late at night is never refused.
* The invoice route limits requests. Eleven fetched back to back drew
  "Too many requests" (HTTP 429) on the twelfth, so a 429 stops the run
  with what it saved, and the config's delays space the downloads.
* Signed out, ``meCustomer`` answers null and ``storefrontOrders``
  answers a FORBIDDEN error, "Must be logged in to access resource".
  Sign-in itself happens at account.ui.com.

Nothing is clicked. The app asks for the order list and each receipt
with the browser's own session, the same two requests the store's page
makes, and never requests checkout, cart, address, payment or RMA routes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from paperpull_core import identity, intake, pdf_reader, refused, shared_folder
from paperpull_core.characters import whole_json
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows


HOST = "store.ui.com"
SIGN_IN_HOST = "account.ui.com"
API_HOST = "ecomm.svc.ui.com"
BASE = f"https://{HOST}/us/en"
ORDERS_URL = f"{BASE}/account"
GRAPHQL_URL = f"https://{API_HOST}/graphql"
INVOICE_URL = f"https://{API_HOST}/invoice/{{order_id}}"
URLS = {"home": ORDERS_URL, "login": ORDERS_URL, "documents": ORDERS_URL}
ALLOWED_HOSTS = {HOST}
LOGIN_URL_MARKERS = ("/login",)

ORDER_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
ORDER_NUMBER = re.compile(r"^[A-Z]{2}\d{5,12}$")
STORE_ID = re.compile(r"^[a-z]{2}$")
# The store's own words for a paid order. Anything else (Cancelled, a
# payment still pending, a failed one) has no receipt to save.
PAID = "Completed"
# Where each store prints its invoice date. A store not named here is
# read in US Eastern time too, and the check of the PDF also takes the
# UTC day, so a guess wrong by a few hours never refuses a receipt.
STORE_ZONES = {"us": "America/New_York", "ca": "America/Toronto"}
DEFAULT_ZONE = "America/New_York"
PAGE_SIZE = 50
MAX_PAGES = 100
LIST_BYTES = 2_000_000
RECEIPT_HEADING = re.compile(r"receipt\s*/\s*tax\s+invoice", re.I)

FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(?:pay|payment|refund|rma|return|cancel|checkout|cart|buy|purchase|"
    r"subscribe|delete|remove|edit|change|update|save|add|apply|confirm|"
    r"tax\s+exemption|address|notification)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(r"\b(?:invoice|receipt|order history|load more|pdf)\b", re.I)
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)
FALLBACK = {"doc_row": "a[href*='/order/'][href$='/status']"}

ORDERS_QUERY = (
    "query GetCustomerOrders($input: StorefrontOrdersInput!) {"
    " storefrontOrders(input: $input) {"
    " pagination { limit offset total }"
    " items { ... on StorefrontOrder {"
    " id orderNumber createdAt store { id } items { title }"
    " displayStatus { payment } } } } }")
HISTORICAL_QUERY = (
    "query GetCustomerHistoricalOrders($input: StorefrontHistoricalOrdersListInput!) {"
    " storefrontHistoricalOrders(input: $input) { pagination { total } } }")
ME_QUERY = "query GetCustomerId { meCustomer { id isGuest } }"


class SessionExpired(RuntimeError):
    """The store answered as no one signed in."""


class ListStopped(RuntimeError):
    """The order list could not be read to its end."""


@dataclass(frozen=True)
class RawDoc:
    title: str
    date_text: str
    account: str
    document_id: str
    number: str = ""


@dataclass(frozen=True)
class Order:
    order_id: str
    number: str
    date: str
    utc_date: str


_RUN: dict = {}


def is_safe_url(url: str) -> bool:
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_safe_control(name: str) -> bool:
    return bool(SAFE_DOC_CONTROL_RE.search(name) and not any(
        pattern.search(name) for pattern in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)))


def is_invoice_page_url(url: str) -> bool:
    """Any page of the store. The order list is asked of the store's API
    with the session every store page shares, so which page the tab is on
    does not matter, only that it is the store's."""
    u = urlsplit(url or "")
    return (u.scheme, u.hostname) == ("https", HOST)


def _tag(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _post(page, operation: str, query: str, variables: dict) -> dict:
    """One GraphQL request with the browser's session, its answer's JSON."""
    response = None
    try:
        response = page.context.request.post(
            GRAPHQL_URL, max_redirects=0, timeout=20000,
            data=json.dumps({"operationName": operation, "variables": variables, "query": query}),
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        if response.status == 429:
            raise ListStopped("The Ubiquiti Store is limiting requests. Try again later.")
        if response.status in (401, 403):
            raise SessionExpired()
        if response.status != 200:
            raise ListStopped("The Ubiquiti Store did not answer the order list request")
        data = whole_json(json.loads(intake.text_of(response, limit=LIST_BYTES)))
        if not isinstance(data, dict):
            raise ListStopped("The Ubiquiti Store did not return a readable order list")
        return data
    except (SessionExpired, ListStopped):
        raise
    except Exception:
        raise ListStopped("The Ubiquiti Store did not return a readable order list") from None
    finally:
        if response is not None:
            response.dispose()


def _refused_as_signed_out(data: dict) -> bool:
    errors = data.get("errors")
    return isinstance(errors, list) and any(
        isinstance(e, dict) and isinstance(e.get("extensions"), dict)
        and e["extensions"].get("code") in ("FORBIDDEN", "UNAUTHENTICATED")
        for e in errors)


def account_tag(page, fresh: bool = False) -> str:
    """A hash of the signed-in customer's id, or "" when the tab is not the
    store's or no one is signed in. Kept for the page it was read on, so
    choosing a tab and listing do not ask twice."""
    if not is_invoice_page_url(getattr(page, "url", "")):
        return ""
    cached = _RUN.get("tag_for")
    if cached and cached[0] is page and not fresh:
        return cached[1]
    try:
        tag = _customer_tag(page)
    except (SessionExpired, ListStopped):
        return ""
    _RUN["tag_for"] = (page, tag)
    return tag


def _customer_tag(page) -> str:
    """The signed-in customer's hash. Raises SessionExpired when no one is
    signed in and ListStopped when the store did not answer, so a list
    that is limited says so rather than reading as signed out."""
    data = _post(page, "GetCustomerId", ME_QUERY, {})
    me = (data.get("data") or {}).get("meCustomer") if isinstance(data.get("data"), dict) else None
    if not isinstance(me, dict) or me.get("isGuest") or not isinstance(me.get("id"), str) or not me["id"]:
        raise SessionExpired()
    return _tag(me["id"])


def invoice_list_look(page) -> tuple[bool, str]:
    """(True, "ready") when the first page of orders is readable, (False,
    "signed out") when the store answers as no one signed in, else (False,
    "stopped")."""
    if not is_invoice_page_url(page.url):
        return False, "stopped"
    try:
        _orders_page(page, 0)
    except SessionExpired:
        return False, "signed out"
    except ListStopped:
        return False, "stopped"
    return True, "ready"


def invoice_list_ready(page) -> bool:
    return invoice_list_look(page)[0]


def looks_signed_out(page) -> bool:
    u = urlsplit(page.url or "")
    if u.scheme != "https":
        return False
    if u.hostname == SIGN_IN_HOST:
        return any(u.path.startswith(m) for m in LOGIN_URL_MARKERS) or u.path in ("", "/")
    return False


def detect_security_challenge(page):
    if not is_safe_url(page.url):
        return None
    try:
        title = page.title()
        if RATE_LIMIT_MARKERS.search(title):
            return "The Ubiquiti Store is limiting requests. Try again later."
        if re.search(r"just a moment|verify you are human|security check|access denied", title, re.I):
            return "The Ubiquiti Store is asking for verification in the browser."
    except Exception:
        pass
    return None


def _orders_page(page, offset: int) -> tuple[list, int]:
    data = _post(page, "GetCustomerOrders", ORDERS_QUERY,
                 {"input": {"limit": PAGE_SIZE, "offset": offset}})
    if _refused_as_signed_out(data):
        raise SessionExpired()
    block = (data.get("data") or {}).get("storefrontOrders") if isinstance(data.get("data"), dict) else None
    if not isinstance(block, dict):
        raise ListStopped("The Ubiquiti Store did not return a readable order list")
    info, items = block.get("pagination"), block.get("items")
    if not isinstance(info, dict) or not isinstance(items, list) or type(info.get("total")) is not int:
        raise ListStopped("The Ubiquiti Store did not return a readable order list")
    if type(info.get("offset")) is int and info["offset"] != offset:
        raise ListStopped("The Ubiquiti Store returned a different page of orders")
    return items, info["total"]


def _historical_total(page) -> int:
    """How many orders of the store's earlier system the account has. Not
    saved (see the module's notes), only counted. Nought when the store
    does not answer, since this is a note and not the list."""
    try:
        data = _post(page, "GetCustomerHistoricalOrders", HISTORICAL_QUERY,
                     {"input": {"limit": 1, "offset": 0}})
        block = data["data"]["storefrontHistoricalOrders"]["pagination"]["total"]
        return block if type(block) is int and block > 0 else 0
    except Exception:
        return 0


def _dates(created: str, store: str) -> tuple[str, str]:
    """(local, utc) dates of an order's creation time."""
    moment = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(ZoneInfo(STORE_ZONES.get(store, DEFAULT_ZONE)))
    return local.date().isoformat(), moment.astimezone(timezone.utc).date().isoformat()


def _summary_of(items) -> str:
    titles = [i.get("title").strip() for i in items or []
              if isinstance(i, dict) and isinstance(i.get("title"), str) and i.get("title").strip()]
    if not titles:
        return ""
    more = len(titles) - 1
    return titles[0] + (f" and {more} more" if more else "")


def _orders(page) -> tuple[str, dict[str, Order], list]:
    if not is_invoice_page_url(page.url):
        raise ListStopped("Open the Ubiquiti Store in the PaperPull browser.")
    tag = _customer_tag(page)
    _RUN["tag_for"] = (page, tag)
    orders: dict[str, Order] = {}
    docs: list = []
    unpaid: dict[str, int] = {}
    for stale in ("page", "account", "orders", "unpaid", "historical"):
        _RUN.pop(stale, None)
    offset, total = 0, None
    for _ in range(MAX_PAGES):
        items, total_now = _orders_page(page, offset)
        if total is None:
            total = total_now
        elif total_now != total:
            raise ListStopped("The Ubiquiti Store's order count changed while it was being read")
        for item in items:
            if not isinstance(item, dict):
                raise ListStopped("The Ubiquiti Store returned an unrecognized order")
            order_id, number, created = (item.get(k) for k in ("id", "orderNumber", "createdAt"))
            store = (item.get("store") or {}).get("id") if isinstance(item.get("store"), dict) else None
            payment = (item.get("displayStatus") or {}).get("payment") if isinstance(item.get("displayStatus"), dict) else None
            if (not isinstance(order_id, str) or not ORDER_ID.fullmatch(order_id)
                    or not isinstance(number, str) or not ORDER_NUMBER.fullmatch(number)
                    or not isinstance(created, str) or not isinstance(store, str)
                    or not STORE_ID.fullmatch(store) or not isinstance(payment, str)):
                raise ListStopped("The Ubiquiti Store returned an unrecognized order")
            try:
                date, utc_date = _dates(created, store)
            except (ValueError, KeyError):
                raise ListStopped("The Ubiquiti Store returned an unrecognized order date") from None
            key = _tag(f"{tag}:{order_id.lower()}")
            if key in orders:
                if orders[key].number != number:
                    raise ListStopped("The Ubiquiti Store returned conflicting records for an order")
                continue
            if payment != PAID:
                unpaid[payment] = unpaid.get(payment, 0) + 1
                orders[key] = Order(order_id.lower(), number, "", "")  # seen, not saved
                continue
            orders[key] = Order(order_id.lower(), number, date, utc_date)
            summary = _summary_of(item.get("items"))
            title = f"Ubiquiti Store Receipt {number}" + (f": {summary}" if summary else "")
            docs.append(RawDoc(title, date, tag, key, number))
        offset += len(items)
        if not items or offset >= total:
            break
        page.wait_for_timeout(350)
    else:
        raise ListStopped("The Ubiquiti Store's order list exceeded the page limit")
    if offset < total:
        raise ListStopped("The Ubiquiti Store's order list ended before its count")
    if _customer_tag(page) != tag:
        raise ListStopped("The signed-in Ubiquiti account changed.")
    _RUN.update(page=page, account=tag, orders={k: v for k, v in orders.items() if v.date},
                unpaid=unpaid, historical=_historical_total(page))
    return tag, _RUN["orders"], docs


def collect_download_docs(page) -> list[RawDoc]:
    return _orders(page)[2]


def unpaid_counts() -> dict:
    """The orders of the last whole list that have no receipt, by the
    store's word for their payment (Cancelled, most often)."""
    return dict(_RUN.get("unpaid", {}))


def legacy_count() -> int:
    """How many orders of the store's earlier system the last whole list
    found, none of which this app saves."""
    return int(_RUN.get("historical", 0))


def _printed_number(text: str, number: str) -> bool:
    return bool(re.search(rf"(?<![A-Z0-9]){re.escape(number)}(?![A-Z0-9])", text, re.I))


def _printed_date(text: str, *dates: str) -> bool:
    low = (text or "").lower()
    return any(identity.on_its_own(v, low) for d in dates if d for v in identity.date_variants(d))


def _fetch_invoice(page, order_id: str) -> bytes:
    response = None
    try:
        response = page.context.request.get(
            INVOICE_URL.format(order_id=order_id), max_redirects=0, timeout=30000,
            params={"locale": "en"}, headers={"Accept": "application/pdf"})
        if response.status == 429:
            raise ListStopped("The Ubiquiti Store is limiting receipt requests. "
                              "Wait a few minutes, then Resume.")
        if response.status in (401, 403):
            raise SessionExpired()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
        if response.status != 200 or content_type != "application/pdf":
            # Signed out, the route answers an HTML page with 200.
            raise SessionExpired()
        data = intake.body(response)
        if not data.startswith(b"%PDF-"):
            raise SessionExpired()
        return data
    except (ListStopped, SessionExpired):
        raise
    except Exception:
        raise SessionExpired() from None
    finally:
        if response is not None:
            response.dispose()


# Why the last download_bill saved nothing, one of REFUSALS.
REFUSALS = ("gone", "refused", "unreadable", "wrong")
_REFUSAL = {"why": ""}


def last_refusal() -> str:
    return _REFUSAL["why"]


def _refuse(why: str) -> bool:
    _REFUSAL["why"] = why
    return False


def download_bill(page, date: str, out_path: Path, *, account: str, document_id: str) -> bool:
    _REFUSAL["why"] = ""
    if not account or account_tag(page) != account:
        raise ListStopped("Sign in to the Ubiquiti account that owns this order.")
    if _RUN.get("page") is not page or _RUN.get("account") != account:
        _orders(page)
    order = _RUN["orders"].get(document_id)
    if order is None or order.date != date:
        return _refuse("gone")
    try:
        data = _fetch_invoice(page, order.order_id)
    except SessionExpired:
        refused.list_again(lambda: collect_download_docs(page), SessionExpired, ListStopped)
        return _refuse("refused")
    try:
        text = " ".join(pdf_reader.page_texts(data, pages=2))
    except Exception:
        return _refuse("unreadable")
    if (not RECEIPT_HEADING.search(text) or not _printed_number(text, order.number)
            or not _printed_date(text, order.date, order.utc_date)):
        return _refuse("wrong")
    shared_folder.write_bytes(out_path, data)
    return True
