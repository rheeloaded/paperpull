"""AliExpress order receipts, seller tax invoices and credit notes.

How AliExpress keeps an order's papers, mapped on 2026-11-26 against a
signed-in US account with 27 orders reaching back to 2020:

* Orders are listed at ``https://www.aliexpress.com/p/order/index.html``
  (a US account lands on www.aliexpress.us). The page reads them from
  ``mtop.aliexpress.trade.buyer.order.list``, ten at a time, each order a
  component ``pc_om_list_order_<order id>`` with ``orderId``,
  ``orderDateText`` ("Nov 8, 2026"), ``statusText``, ``totalPriceText``,
  ``storeName`` and ``orderLines``. A ``pc_om_list_body`` component holds
  ``hasMore``, and the page's "View orders" button asks for the next ten
  with a signed blob of the list's own state, so the app presses that
  button and reads what comes back rather than forging the blob. VERIFIED,
  three pages for 27 orders.
* An order's "Receipt" is ``https://www.aliexpress.com/p/tax-ui/index.html
  ?orderId=<id>``, a page drawn from ``mtop.global.finance.taxation.invoice
  .queryOrderReceiptInfo``: the order id and time, subtotal, discounts,
  shipping, tax, total, the shipping address, the masked card, the items
  and the seller. AliExpress's own Download button turns it into a PNG in
  the browser, so the app prints the page to PDF instead. An order too old
  for that API (one from 2020 answered no data) has no receipt.
* "Download invoice" lists the seller's US sales-tax papers through
  ``getInvoiceInfoListByType`` (``invoiceType: INVOICE``): an Invoice, and
  for a cancelled or expired order a Credit note too, each with
  ``invoiceId``, ``invoiceNo`` and ``invoiceStatus``. One whose status is
  ``GENERATED_SUCCESS`` is fetched with ``getInvoiceFileContent``, which
  answers the PDF as base64 (``content``) and a ``fileName`` naming the
  order. Amounts are in CNY. The PDF is headed "Invoice" or "Credit Memo"
  and prints its invoice number, not the order's.
* ``applyInvoiceToSeller`` asks a seller for an invoice. It is a request
  made of someone, so the app never calls it and saves only what exists.
* The mtop calls are made through the page's own ``lib.mtop`` on an
  AliExpress page, which signs them with the session's token, exactly as
  the tax pages do.
* Signed out, the order page sends the browser to login.aliexpress.com,
  and an mtop call answers ``FAIL_SYS_SESSION_EXPIRED`` or a token error.
  A bot check answers ``FAIL_SYS_USER_VALIDATE`` (or ``RGV587``), and the
  run stops for the person to clear it in the browser.

Nothing is bought, paid, confirmed, deleted, reviewed or sent. The only
control pressed is "View orders", which loads more of the list.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from paperpull_core import identity, pdf_reader, receipt_pdf, refused, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows


HOSTS = {"www.aliexpress.com", "www.aliexpress.us"}
ALLOWED_HOSTS = HOSTS
SIGN_IN_HOSTS = {"login.aliexpress.com", "login.aliexpress.us"}
BASE = "https://www.aliexpress.com"
ORDERS_URL = f"{BASE}/p/order/index.html"
RECEIPT_URL = f"{BASE}/p/tax-ui/index.html?orderId={{order_id}}"
# A page that loads the tax module's own lib.mtop, for the invoice calls.
TAX_PAGE_URL = f"{BASE}/p/tax-ui/invoice.html?orderId={{order_id}}"
URLS = {"home": ORDERS_URL, "login": ORDERS_URL, "documents": ORDERS_URL}
LOGIN_URL_MARKERS = ("/login",)

ORDER_ID = re.compile(r"^\d{12,20}$")
LIST_API = "mtop.aliexpress.trade.buyer.order.list"
RECEIPT_API = "mtop.global.finance.taxation.invoice.queryOrderReceiptInfo"
INVOICE_LIST_API = "mtop.global.finance.taxation.invoice.getInvoiceInfoListByType"
INVOICE_FILE_API = "mtop.global.finance.taxation.invoice.getInvoiceFileContent"
READ_APIS = (RECEIPT_API, INVOICE_LIST_API, INVOICE_FILE_API)
GENERATED = "GENERATED_SUCCESS"
# The seller's paper kinds, by what the list calls them.
INVOICE_KINDS = {"invoice": "Invoice", "credit note": "Credit Note"}
MAX_LIST_PAGES = 200
LIST_WAIT_MS = 20000

RECEIPT = "receipt"
SIGNED_OUT_RET = re.compile(r"SESSION_EXPIRED|TOKEN_EMPTY|TOKEN_EXOIRED|TOKEN_EXPIRED|NOT_LOGIN|LOGIN", re.I)
CHALLENGE_RET = re.compile(r"USER_VALIDATE|RGV587|ANTI|DENIED|PUNISH", re.I)
# Throttling, in an mtop answer's ret or a page's title.
RATE_LIMIT_MARKERS = re.compile(r"FLOW_LIMIT|TOO_MANY|SERVICE_BUSY|LIMIT|too many requests|rate limit", re.I)

FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(?:pay(?:\s+now)?|buy|add\s+to\s+cart|cart|confirm(?:\s+received)?|delete|remove|"
    r"cancel|refund|return|dispute|review|feedback|contact|message|send(?:\s+email)?|"
    r"email|apply|submit|track|coupon|redeem|follow|subscribe|edit|change|update)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(r"\b(?:view\s+orders|receipt|invoice|download|details)\b", re.I)
FALLBACK = {"doc_row": "a[href*='/p/order/detail.html']", "more": "button:has-text('View orders')"}


class SessionExpired(RuntimeError):
    """AliExpress answered as no one signed in."""


class ListStopped(RuntimeError):
    """The order list, or an order's papers, could not be read to the end."""


class SecurityCheck(ListStopped):
    """AliExpress asked for a check (a slider or a puzzle) the person must clear."""


@dataclass(frozen=True)
class RawDoc:
    title: str
    date_text: str
    account: str
    document_id: str
    number: str = ""


@dataclass(frozen=True)
class Paper:
    order_id: str
    kind: str          # RECEIPT, or "Invoice" / "Credit Note"
    date: str
    invoice_id: str = ""
    invoice_no: str = ""


_RUN: dict = {}


def is_safe_url(url: str) -> bool:
    return _host_allows(url, HOSTS, subdomains=False)


def is_safe_control(name: str) -> bool:
    return bool(SAFE_DOC_CONTROL_RE.search(name) and not any(
        pattern.search(name) for pattern in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)))


def is_invoice_page_url(url: str) -> bool:
    """Any AliExpress page. The papers are read with the session every
    AliExpress page shares, so which page the tab is on does not matter."""
    u = urlsplit(url or "")
    return u.scheme == "https" and u.hostname in HOSTS


def _tag(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def account_tag(page) -> str:
    """A hash of the signed-in member's id (``x_alimid`` in the
    ``aep_usuc_f`` cookie), or "" when the tab is not AliExpress's or
    nobody is signed in."""
    if not is_invoice_page_url(getattr(page, "url", "")):
        return ""
    try:
        cookies = page.context.cookies([BASE, "https://www.aliexpress.us"])
    except Exception:
        return ""
    for cookie in cookies:
        if cookie.get("name") != "aep_usuc_f":
            continue
        match = re.search(r"(?:^|&)x_alimid=(\d{4,20})(?:&|$)", unquote(cookie.get("value") or ""))
        if match:
            return _tag(match[1])
    return ""


def invoice_list_look(page) -> tuple[bool, str]:
    """(True, "ready") when an AliExpress tab has a signed-in member and the
    order list answers, (False, "signed out") when it has none or the list
    asks for a sign-in, else (False, "stopped"). Reads the first page of the
    list only, in the tab it is given. A blank tab (the run's own, new) is
    sent to the order list first."""
    if (getattr(page, "url", "") or "about:blank") == "about:blank":
        try:
            page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            return False, "stopped"
    if not is_invoice_page_url(getattr(page, "url", "")):
        return (False, "signed out") if looks_signed_out(page) else (False, "stopped")
    if not account_tag(page):
        return False, "signed out"
    answers: list = []

    def keep(response):
        if LIST_API in response.url:
            answers.append(response)

    page.on("response", keep)
    try:
        page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
        waited = 0
        while waited < LIST_WAIT_MS:
            if looks_signed_out(page):
                return False, "signed out"
            for answer in answers:
                try:
                    _list_page(answer)
                    return True, "ready"
                except SessionExpired:
                    return False, "signed out"
                except Exception:
                    continue
            page.wait_for_timeout(250)
            waited += 250
        return False, "stopped"
    except SessionExpired:
        return False, "signed out"
    except Exception:
        return False, "stopped"
    finally:
        try:
            page.remove_listener("response", keep)
        except Exception:
            pass


def invoice_list_ready(page) -> bool:
    return invoice_list_look(page)[0]


def looks_signed_out(page) -> bool:
    u = urlsplit(page.url or "")
    if u.scheme != "https":
        return False
    if u.hostname in SIGN_IN_HOSTS:
        return True
    return u.hostname in HOSTS and any(u.path.startswith(m) for m in LOGIN_URL_MARKERS)


def detect_security_challenge(page):
    if not is_safe_url(page.url):
        return None
    try:
        title = page.title()
        if RATE_LIMIT_MARKERS.search(title):
            return "AliExpress is limiting requests. Try again later."
        if re.search(r"captcha|verify|slide to|security check|access denied|unusual traffic", title, re.I):
            return "AliExpress is asking for a check in the browser."
    except Exception:
        pass
    return None


def _ret_problem(ret) -> None:
    """Raise for an mtop answer that is not a success."""
    words = " ".join(str(r) for r in ret) if isinstance(ret, list) else str(ret or "")
    if not words or words.upper().startswith("SUCCESS"):
        return
    if SIGNED_OUT_RET.search(words):
        raise SessionExpired()
    if CHALLENGE_RET.search(words):
        raise SecurityCheck("AliExpress asked for a check. Clear it in the browser, then Resume.")
    if RATE_LIMIT_MARKERS.search(words):
        raise ListStopped("AliExpress is limiting requests. Wait a few minutes, then Resume.")
    raise ListStopped("AliExpress did not answer a request for an order's papers")


_CALL_JS = """async ([api, data]) => {
  const m = window.lib && window.lib.mtop;
  if (!m || !m.request) return {missing: true};
  if (!data.timeZone) {
    const z = (new Date()).toString().match(/([A-Z]+[+-][0-9]+)/);
    if (z) data.timeZone = z[1];
  }
  try {
    const r = await m.request({needLogin: true, api, type: 'POST', v: '1.0', ecode: 1, data});
    return {ret: r && r.ret, data: r && r.data};
  } catch (e) {
    return {ret: (e && e.ret) || ['ERROR::' + String(e).slice(0, 80)]};
  }
}"""


def _region(page) -> str:
    """The country the account ships to, as the tax pages send it, from the
    ``region`` of the ``aep_usuc_f`` cookie. US when it is not there."""
    try:
        for cookie in page.context.cookies([BASE, "https://www.aliexpress.us"]):
            if cookie.get("name") == "aep_usuc_f":
                match = re.search(r"(?:^|&)region=([A-Z]{2})(?:&|$)", unquote(cookie.get("value") or ""))
                if match:
                    return match[1]
    except Exception:
        pass
    return "US"


def _base_data(page, order_id: str) -> dict:
    return {"orderId": order_id, "shipToCountry": _region(page), "_lang": "en_US",
            "clientPlatform": "pc"}


def _mtop(page, api: str, order_id: str, extra: dict | None = None) -> dict:
    """One read of the tax module's API, signed by the page's lib.mtop."""
    if api not in READ_APIS:
        raise ValueError("not a read this app makes")
    data = dict(_base_data(page, order_id), **(extra or {}))
    try:
        answer = page.evaluate(_CALL_JS, [api, data])
    except Exception:
        raise ListStopped("AliExpress did not answer a request for an order's papers") from None
    if not isinstance(answer, dict) or answer.get("missing"):
        raise ListStopped("The AliExpress tax page did not load its request library")
    _ret_problem(answer.get("ret"))
    body = answer.get("data")
    if not isinstance(body, dict):
        raise ListStopped("AliExpress did not answer a request for an order's papers")
    return body


def _open_tax_page(page, order_id: str) -> None:
    page.goto(TAX_PAGE_URL.format(order_id=order_id), wait_until="domcontentloaded", timeout=60000)
    if looks_signed_out(page):
        raise SessionExpired()
    try:
        page.wait_for_function("() => !!(window.lib && window.lib.mtop && window.lib.mtop.request)",
                               timeout=30000)
    except Exception:
        raise ListStopped("The AliExpress tax page did not load its request library") from None


def _jsonp(text: str):
    text = (text or "").strip()
    match = re.match(r"^[\w$.]+\((.*)\)\s*;?$", text, re.S)
    return json.loads(match[1] if match else text)


def _list_page(response) -> tuple[list, dict]:
    """(orders, body fields) of one answer of the order list."""
    try:
        answer = _jsonp(response.text())
    except Exception:
        raise ListStopped("AliExpress did not return a readable order list") from None
    _ret_problem(answer.get("ret"))
    comps = ((answer.get("data") or {}).get("data")) if isinstance(answer.get("data"), dict) else None
    if not isinstance(comps, dict):
        raise ListStopped("AliExpress did not return a readable order list")
    orders, body = [], None
    for key, comp in comps.items():
        fields = comp.get("fields") if isinstance(comp, dict) else None
        if key.startswith("pc_om_list_order_") and isinstance(fields, dict):
            orders.append(fields)
        elif key.startswith("pc_om_list_body") and isinstance(fields, dict):
            body = fields
    if body is None or type(body.get("hasMore")) is not bool:
        raise ListStopped("AliExpress did not return a readable order list")
    return orders, body


def _order_date(text) -> str:
    try:
        return datetime.strptime((text or "").strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        raise ListStopped("AliExpress returned an unrecognized order date") from None


def _list_orders(page) -> list:
    """Every order the list holds, pressing "View orders" until it has no more."""
    answers: list = []

    def keep(response):
        if LIST_API in response.url:
            answers.append(response)

    # From a blank page, so no answer of an earlier load of the list (the
    # run's tab may have been on it already) arrives while this one is read.
    page.goto("about:blank")
    page.on("response", keep)
    try:
        page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
        if looks_signed_out(page):
            raise SessionExpired()
        orders: dict = {}
        read = 0
        expected = 1
        for _ in range(MAX_LIST_PAGES):
            waited = 0
            while read >= len(answers) and waited < LIST_WAIT_MS:
                page.wait_for_timeout(250)
                waited += 250
                if looks_signed_out(page):
                    raise SessionExpired()
            if read >= len(answers):
                raise ListStopped("AliExpress did not send the next page of orders")
            page.wait_for_timeout(300)
            answer = answers[read]
            read += 1
            try:
                answer.text()
            except Exception:
                # An answer to a load of the list the page has since left
                # (the tab was on the list already), whose body the
                # browser no longer holds. The current load's answer follows.
                continue
            rows, body = _list_page(answer)
            # Each answer names its page. One that is not the page asked
            # for next is an answer to some other load, and is passed over.
            index = body.get("pageIndex")
            if type(index) is int and index != expected:
                continue
            expected += 1
            for row in rows:
                order_id = str(row.get("orderId") or "")
                if not ORDER_ID.fullmatch(order_id):
                    raise ListStopped("AliExpress returned an unrecognized order")
                orders[order_id] = row
            if not body["hasMore"]:
                return list(orders.values())
            more = page.get_by_role("button", name="View orders", exact=True)
            if not more.count():
                raise ListStopped("The order list says it has more, but shows no View orders button")
            label = re.sub(r"\s+", " ", more.first.inner_text() or "").strip()
            if not is_safe_control(label):
                raise ListStopped("The order list's more button is not one PaperPull may press")
            more.first.click()
        raise ListStopped("The AliExpress order list exceeded the page limit")
    finally:
        try:
            page.remove_listener("response", keep)
        except Exception:
            pass


def _summary_of(row) -> str:
    lines = row.get("orderLines") or []
    titles = [str(line.get("itemTitle") or "").strip() for line in lines if isinstance(line, dict)]
    titles = [t for t in titles if t]
    if not titles:
        return ""
    first = titles[0] if len(titles[0]) <= 60 else titles[0][:57].rstrip() + "..."
    return first + (f" and {len(titles) - 1} more" if len(titles) > 1 else "")


def _papers(page) -> tuple[str, dict, list]:
    if not is_invoice_page_url(page.url):
        raise ListStopped("Open AliExpress in the PaperPull browser.")
    tag = account_tag(page)
    if not tag:
        raise SessionExpired()
    for stale in ("page", "account", "papers", "no_receipt", "pending_invoices"):
        _RUN.pop(stale, None)
    rows = _list_orders(page)
    if account_tag(page) != tag:
        raise ListStopped("The signed-in AliExpress account changed.")
    papers: dict = {}
    docs: list = []
    no_receipt = pending = 0
    if rows:
        _open_tax_page(page, str(rows[0]["orderId"]))
    for row in rows:
        order_id = str(row["orderId"])
        date = _order_date(row.get("orderDateText"))
        status = str(row.get("statusText") or "").strip()
        about = _summary_of(row)
        receipt = _mtop(page, RECEIPT_API, order_id)
        info = receipt.get("data") if receipt.get("succeeded") is True else None
        if isinstance(info, dict) and str(info.get("orderId") or "") == order_id:
            key = _tag(f"{tag}:{order_id}:{RECEIPT}")
            papers[key] = Paper(order_id, RECEIPT, date)
            note = f" ({status})" if status and status.lower() not in ("completed", "awaiting delivery") else ""
            docs.append(RawDoc(f"AliExpress Receipt {order_id}{note}" + (f": {about}" if about else ""),
                               date, tag, key, order_id))
        else:
            no_receipt += 1
        listed = _mtop(page, INVOICE_LIST_API, order_id, {"invoiceType": "INVOICE"})
        entries = ((listed.get("data") or {}).get("invoiceInfoDTOList")
                   if isinstance(listed.get("data"), dict) else None) or []
        if not isinstance(entries, list):
            raise ListStopped("AliExpress returned an unrecognized invoice list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ListStopped("AliExpress returned an unrecognized invoice list")
            kind = INVOICE_KINDS.get(str(entry.get("invoiceType") or "").strip().lower())
            invoice_id, invoice_no = str(entry.get("invoiceId") or ""), str(entry.get("invoiceNo") or "")
            if kind is None or str(entry.get("orderId") or order_id) != order_id:
                continue
            if entry.get("invoiceStatus") != GENERATED or not invoice_id or not invoice_no:
                pending += 1
                continue
            key = _tag(f"{tag}:{order_id}:{invoice_id}")
            papers[key] = Paper(order_id, kind, date, invoice_id, invoice_no)
            docs.append(RawDoc(f"AliExpress Seller Tax {kind} {order_id}" + (f": {about}" if about else ""),
                               date, tag, key, order_id))
        page.wait_for_timeout(400)
    _RUN.update(page=page, account=tag, papers=papers, no_receipt=no_receipt,
                pending_invoices=pending)
    return tag, papers, docs


def collect_download_docs(page) -> list[RawDoc]:
    return _papers(page)[2]


def listing_notes() -> list[str]:
    """What the last whole list found and does not save, said on every listing."""
    notes = []
    n = int(_RUN.get("no_receipt", 0))
    if n:
        notes.append(f"{n} order{'s' if n != 1 else ''} too old for AliExpress's receipt "
                     f"{'have' if n != 1 else 'has'} no receipt to save.")
    n = int(_RUN.get("pending_invoices", 0))
    if n:
        notes.append(f"{n} seller invoice{'s' if n != 1 else ''} not yet issued "
                     f"{'are' if n != 1 else 'is'} listed but not saved.")
    return notes


def _printed(text: str, value: str) -> bool:
    return bool(value) and bool(re.search(rf"(?<![A-Z0-9]){re.escape(value)}(?![A-Z0-9])", text or "", re.I))


def _printed_date(text: str, date: str) -> bool:
    low = (text or "").lower()
    return any(identity.on_its_own(v, low) for v in identity.date_variants(date))


def _receipt_pdf(page, paper: Paper, out_path: Path) -> bool:
    page.goto(RECEIPT_URL.format(order_id=paper.order_id), wait_until="domcontentloaded", timeout=60000)
    if looks_signed_out(page):
        raise SessionExpired()
    try:
        page.wait_for_function(
            "id => (document.body && document.body.innerText || '').includes(id)"
            " && /Total/.test(document.body.innerText)", arg=paper.order_id, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        if detect_security_challenge(page):
            raise SecurityCheck("AliExpress asked for a check. Clear it in the browser, then Resume.")
        return _refuse("refused")
    receipt_pdf.print_page_to_pdf(page, out_path)
    try:
        text = " ".join(pdf_reader.page_texts(out_path.read_bytes(), pages=2))
    except Exception:
        out_path.unlink(missing_ok=True)
        return _refuse("unreadable")
    if not (re.search(r"order\s+id", text, re.I) and _printed(text, paper.order_id)
            and _printed_date(text, paper.date) and re.search(r"\btotal\b", text, re.I)):
        out_path.unlink(missing_ok=True)
        return _refuse("wrong")
    return True


def _invoice_pdf(page, paper: Paper, out_path: Path) -> bool:
    if not (is_invoice_page_url(page.url) and "/p/tax-ui/" in urlsplit(page.url).path):
        _open_tax_page(page, paper.order_id)
    body = _mtop(page, INVOICE_FILE_API, paper.order_id,
                 {"invoiceId": paper.invoice_id, "invoiceNo": paper.invoice_no})
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    content, name = data.get("content"), str(data.get("fileName") or "")
    if not isinstance(content, str) or not content:
        return _refuse("refused")
    try:
        pdf = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        return _refuse("unreadable")
    if not pdf.startswith(b"%PDF-"):
        return _refuse("unreadable")
    try:
        text = " ".join(pdf_reader.page_texts(pdf, pages=2))
    except Exception:
        return _refuse("unreadable")
    # A credit memo prints "Invoice No." too, so an invoice is one headed
    # Invoice that is not a credit memo.
    credit = bool(re.search(r"credit\s+(?:memo|note)", text, re.I))
    right_kind = credit if paper.kind == "Credit Note" else (
        not credit and re.match(r"\s*invoice\b", text, re.I) is not None)
    if not right_kind or not _printed(text, paper.invoice_no) or paper.order_id not in name:
        return _refuse("wrong")
    shared_folder.write_bytes(out_path, pdf)
    return True


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
        raise ListStopped("Sign in to the AliExpress account that owns this order.")
    if _RUN.get("page") is not page or _RUN.get("account") != account:
        _papers(page)
    paper = _RUN["papers"].get(document_id)
    if paper is None or paper.date != date:
        return _refuse("gone")
    try:
        if paper.kind == RECEIPT:
            return _receipt_pdf(page, paper, out_path)
        return _invoice_pdf(page, paper, out_path)
    except SessionExpired:
        refused.list_again(lambda: collect_download_docs(page), SessionExpired, ListStopped)
        return _refuse("refused")
