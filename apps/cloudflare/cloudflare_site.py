"""Cloudflare dashboard invoice discovery and PDF retrieval.

The signed-in Invoices page uses an account-scoped GET for each history page
and a GET for the selected invoice PDF. The connector uses those same routes
with the browser's existing session. It never clicks a dashboard control,
follows a redirect, or requests payment, profile, or subscription routes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from paperpull_core import identity, intake, pdf_reader, refused, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.urls import join as _join


HOST = "dash.cloudflare.com"
BASE = f"https://{HOST}"
BILLING_URL = BASE + "/"
URLS = {"home": BILLING_URL, "login": BILLING_URL, "documents": BILLING_URL}
ALLOWED_HOSTS = {HOST}
LOGIN_URL_MARKERS = ("/login",)
INVOICES_PATH = re.compile(r"^/([0-9a-f]{32})/billing/invoices/?$", re.I)
INVOICE_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
RECEIPT_NUMBER = re.compile(r"^[A-Z0-9]{1,12}(?:[-_][A-Z0-9]{1,16}){1,4}$", re.I)
PAGE_SIZE = 50
MAX_PAGES = 200
LIST_BYTES = 2_000_000

FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(?:pay|payment|refund|subscribe|subscription|upgrade|downgrade|delete|"
    r"edit|change|confirm|update|cancel|create|transfer|purchase|checkout|add card)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(r"\b(?:invoice|download|pdf|next page)\b", re.I)
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)
FALLBACK = {"doc_row": "table tbody tr"}


class SessionExpired(RuntimeError):
    """The dashboard asked the account holder to sign in again."""


class ListStopped(RuntimeError):
    """The selected account's invoice list could not be read to its end."""


@dataclass(frozen=True)
class RawDoc:
    title: str
    date_text: str
    account: str
    document_id: str


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    number: str
    date: str


_RUN: dict = {}


def is_safe_url(url: str) -> bool:
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_safe_control(name: str) -> bool:
    return bool(SAFE_DOC_CONTROL_RE.search(name) and not any(
        pattern.search(name) for pattern in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)))


def _account(url: str) -> str:
    u = urlsplit(url or "")
    if (u.scheme, u.netloc) != ("https", HOST):
        return ""
    match = INVOICES_PATH.fullmatch(u.path)
    return match[1].lower() if match else ""


def is_invoice_page_url(url: str) -> bool:
    return bool(_account(url))


def _tag(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def account_tag(page) -> str:
    account = _account(page.url)
    return _tag(account) if account else ""


def invoice_list_ready(page) -> bool:
    """Require a readable first page before reporting a ready session."""
    account = _account(page.url)
    if not account:
        return False
    try:
        _history_page(page, account, 1)
    except (ListStopped, SessionExpired):
        return False
    return True


def looks_signed_out(page) -> bool:
    u = urlsplit(page.url or "")
    if (u.scheme, u.netloc) != ("https", HOST):
        return False
    if u.path.rstrip("/") in LOGIN_URL_MARKERS:
        return True
    try:
        return bool(page.locator("input[type='password']").count())
    except Exception:
        return False


def detect_security_challenge(page):
    if not is_safe_url(page.url):
        return None
    try:
        title = page.title()
        if RATE_LIMIT_MARKERS.search(title):
            return "Cloudflare is limiting requests. Try again later."
        if re.search(r"just a moment|verify you are human|security check", title, re.I):
            return "Cloudflare is asking for verification in the browser."
    except Exception:
        pass
    return None


def _to_sign_in(response) -> bool:
    """Whether an answer is a redirect to the Dashboard's own sign-in page.
    Redirects are never followed, so the 3xx itself comes back."""
    if response.status not in (301, 302, 303, 307, 308):
        return False
    try:
        u = urlsplit(_join(BILLING_URL, response.headers.get("location", "") or ""))
    except ValueError:
        return False
    return (u.scheme, u.netloc) == ("https", HOST) and u.path.rstrip("/") in LOGIN_URL_MARKERS


def _history_page(page, account: str, page_number: int) -> tuple[list, bool]:
    if _account(page.url) != account:
        raise ListStopped("The selected Cloudflare account changed.")
    response = None
    endpoint = f"{BASE}/api/v4/accounts/{account}/billing/history"
    try:
        response = page.context.request.get(endpoint, max_redirects=0, timeout=20000,
                                            params={"page": page_number, "per_page": PAGE_SIZE},
                                            headers={"Accept": "application/json"})
        if response.status == 401 or _to_sign_in(response):
            raise SessionExpired()
        if response.status == 429:
            raise ListStopped("Cloudflare is limiting invoice requests. Try again later.")
        if response.status == 403:
            raise ListStopped("Cloudflare refused the invoice history. The signed-in user may "
                              "not have billing access to this account")
        if response.status != 200:
            raise ListStopped("Cloudflare did not answer the invoice history request")
        data = json.loads(intake.text_of(response, limit=LIST_BYTES))
        rows, info = data.get("result"), data.get("result_info")
        if (data.get("success") is not True or not isinstance(rows, list)
                or not isinstance(info, dict) or type(info.get("next_page")) is not bool):
            raise ListStopped("Cloudflare did not return a readable invoice history")
        returned_page = info.get("page")
        # The dashboard can omit pagination metadata on its empty first page.
        empty_history = page_number == 1 and not rows and not info["next_page"]
        if ((type(returned_page) is not int or returned_page != page_number)
                and not (empty_history and returned_page is None)):
            raise ListStopped("Cloudflare returned a different or incomplete invoice history page")
        if not rows and info["next_page"]:
            raise ListStopped("Cloudflare returned a different or incomplete invoice history page")
        return rows, info["next_page"]
    except (SessionExpired, ListStopped):
        raise
    except Exception:
        raise ListStopped("Cloudflare did not return a readable invoice history") from None
    finally:
        if response is not None:
            response.dispose()


def _invoices(page) -> tuple[str, dict[str, Invoice]]:
    account = _account(page.url)
    if not account:
        raise ListStopped("Open Invoices and documents for your Cloudflare account.")
    tag = _tag(account)
    invoices = {}
    seen = []
    legacy = 0
    _RUN.clear()
    for n in range(1, MAX_PAGES + 1):
        rows, has_next = _history_page(page, account, n)
        added = 0
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("type"), str):
                raise ListStopped("Cloudflare returned an unrecognized billing row")
            if row["type"] != "invoice":
                continue
            source = row.get("source")
            if source == "legacy":
                # An invoice of Cloudflare's older billing, whose PDF this
                # app does not ask for. Counted, so the run says how many
                # it left, rather than reading as the whole history saved.
                legacy += 1
                continue
            if source != "stripe":
                raise ListStopped("Cloudflare returned an invoice with an unrecognized billing source")
            invoice_id, number, occurred = (row.get(k) or "" for k in ("invoice_id", "receipt_id", "occurred_at"))
            if (not isinstance(invoice_id, str) or not INVOICE_ID.fullmatch(invoice_id)
                    or not isinstance(number, str)
                    or not RECEIPT_NUMBER.fullmatch(number) or not isinstance(occurred, str)):
                raise ListStopped("Cloudflare returned an unrecognized invoice")
            try:
                date = datetime.fromisoformat(occurred.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                raise ListStopped("Cloudflare returned an unrecognized invoice date") from None
            key = _tag(f"{tag}:{invoice_id.lower()}")
            invoice = Invoice(invoice_id.lower(), number, date)
            if key in invoices and invoices[key] != invoice:
                raise ListStopped("Cloudflare returned conflicting records for an invoice")
            if key not in invoices:
                invoices[key] = invoice
                added += 1
        # Detect the API returning the previous page again even if it claims
        # to be the last one, before treating the archive as fully listed.
        if rows and not added and rows in seen:
            raise ListStopped("Cloudflare repeated an invoice history page")
        if not has_next:
            if _account(page.url) != account:
                raise ListStopped("The selected Cloudflare account changed.")
            _RUN.update(page=page, account=tag, invoices=invoices, legacy=legacy)
            return tag, invoices
        seen.append(rows)
        page.wait_for_timeout(350)
    raise ListStopped("Cloudflare invoice history exceeded the page limit")


def collect_download_docs(page) -> list[RawDoc]:
    tag, invoices = _invoices(page)
    return [RawDoc("Cloudflare Invoice", invoice.date, tag, key)
            for key, invoice in invoices.items()]


def legacy_count() -> int:
    """How many invoices of Cloudflare's older billing the last whole list
    held, none of which this app saves. Nought after a list that stopped."""
    return int(_RUN.get("legacy", 0))


def _printed_number(text: str, number: str) -> bool:
    parts = re.findall(r"[A-Z0-9]+", number, re.I)
    pattern = r"[^A-Z0-9]*".join(map(re.escape, parts))
    return bool(pattern and re.search(rf"(?<![A-Z0-9]){pattern}(?![A-Z0-9])", text, re.I))


def _fetch_invoice(page, selected: str, invoice_id: str) -> bytes:
    endpoint = f"{BASE}/api/v4/accounts/{selected}/billing/receipts/{invoice_id}/pdf"
    response = None
    try:
        response = page.context.request.get(endpoint, max_redirects=0, timeout=25000,
                                            params={"doctype": "invoice", "isLegacy": "false"},
                                            headers={"Accept": "application/pdf"})
        if response.status in (401, 403):
            raise SessionExpired()
        if response.status == 429:
            raise ListStopped("Cloudflare is limiting invoice requests. Try again later.")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
        if response.status != 200 or content_type != "application/pdf":
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


# Why the last download_bill saved nothing, one of REFUSALS, so the run
# records and says it rather than calling every refusal a capture failure.
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
        raise ListStopped("Reopen the Cloudflare account that owns this invoice.")
    if _RUN.get("page") is not page or _RUN.get("account") != account:
        _invoices(page)
    invoice = _RUN["invoices"].get(document_id)
    if invoice is None or invoice.date != date:
        return _refuse("gone")
    selected = _account(page.url)
    if not selected or _tag(selected) != account:
        raise ListStopped("The selected Cloudflare account changed.")
    try:
        data = _fetch_invoice(page, selected, invoice.invoice_id)
    except SessionExpired:
        refused.list_again(lambda: collect_download_docs(page), SessionExpired, ListStopped)
        return _refuse("refused")
    try:
        text = " ".join(pdf_reader.page_texts(data, pages=2))
    except Exception:
        return _refuse("unreadable")
    if (not _printed_number(text, invoice.number)
            or not identity.contains(text, identity.date_variants(date), "date")):
        return _refuse("wrong")
    shared_folder.write_bytes(out_path, data)
    return True
