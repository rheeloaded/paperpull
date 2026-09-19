#!/usr/bin/env python3
"""The transactions inside your statement PDFs, in one spreadsheet.

    python export_transactions.py                        every statement archive
    python export_transactions.py --provider USAA        one provider
    python export_transactions.py --csv                  a .csv instead of .xlsx
    python export_transactions.py --root "D:\\installs"  where the installs are

A statement archive holds PDFs, and the transactions are inside them. This
opens each PDF the archive's index knows about, reads the text line by
line, and keeps the lines that look like a transaction, a date, a
description and an amount. Every provider lays its statement out its own
way, so nothing here is written for one bank. A line is a transaction by
shape, and the statement's own printed balances are what decide whether
the reading is right.

That check is the point. A statement prints a beginning balance and an
ending balance, and the transactions between them have to add up. Where
the statement carries a running balance column, the sign of every amount
is read off the balance itself, which reconciles to the cent by
construction. Where it prints signed amounts, they are summed as printed.
A statement that adds up is marked reconciled. One that does not is still
exported, with the difference shown, so you know which rows to doubt.

Amounts are the effect on the balance. Money in is positive, money out is
negative, for a bank account and a card alike (a card payment is negative,
a purchase positive, which is how the card prints them).

Reading a PDF takes a moment, and an archive can hold hundreds, so every
reading is cached beside the installs by file size and modification time.
The second build is instant. Delete the cache file to read everything
again.

Needs `pdfplumber` to read PDFs and `openpyxl` for .xlsx. Without pdfplumber
the tool stops and says so. Without openpyxl it writes a .csv and says so.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

INDEX_SUFFIX = " Document Index.csv"
CACHE_NAME = ".transactions-cache.json"
CACHE_VERSION = 1

# -- shapes -----------------------------------------------------------------------
_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE_RE = re.compile(
    r"(?P<num>\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)"
    r"|(?P<mdy>" + _MON + r"\s+\d{1,2}(?:,?\s+\d{4})?)"
    r"|(?P<dmy>\d{1,2}\s+" + _MON + r"(?:,?\s+\d{4})?)", re.I)
# The same shapes without group names, for embedding in other patterns.
_DATE_ANY = (r"(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|" + _MON + r"\s+\d{1,2}(?:,?\s+\d{4})?|"
             r"\d{1,2}\s+" + _MON + r"(?:,?\s+\d{4})?)")
DATE_AT_START = re.compile(r"^\s*(" + _DATE_ANY + r")(?:\*|\s|$)", re.I)
# An amount as a statement prints one. 1,234.56 with optional $ and any of the
# ways a negative is shown: -1.00, $-1.00, 1.00-, (1.00), 1.00 CR, 1.00CR.
AMOUNT_TOKEN = re.compile(
    r"^(?P<open>\()?(?P<neg1>-)?\$?\s?(?P<neg2>-)?(?P<num>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})"
    r"(?P<close>\))?(?P<neg3>-)?(?P<cr>\s?CR)?(?P<mark>[⧫*†‡])?$", re.I)
ZERO_TOKEN = re.compile(r"^\$?0(?:\.00)?$")        # a debit/credit column placeholder


def _fuzzy(phrase: str) -> str:
    """A pattern for a phrase that tolerates a stray space inside a word,
    which is how some PDFs come out ("Ending B alance", "Transact ion")."""
    words = [r"\s?".join(re.escape(ch) for ch in w) for w in phrase.split()]
    return r"\s+".join(words)


BALANCE_WORDS = re.compile(
    r"\b(?:" + "|".join(_fuzzy(w) for w in ("beginning", "previous", "opening", "starting", "ending", "new", "closing"))
    + r")\s+" + _fuzzy("balance") + r"\b|\b" + _fuzzy("balance forward") + r"\b", re.I)
NOT_A_TRANSACTION = re.compile(
    r"\b(total|subtotal|" + _fuzzy("balance") + r"|average daily|annual percentage|apr\b|interest rate|"
    r"minimum payment|payment due|due date|statement period|closing date|page \d)\b", re.I)
PERIOD_RE = re.compile(
    r"(?:statement\s+period|billing\s+period|period|for the period|from)\s*:?\s*"
    r"(" + _DATE_ANY + r")\s*(?:to|-|–|—|through|thru)\s*(" + _DATE_ANY + r")", re.I)
CLOSING_RE = re.compile(r"(?:closing\s+date|statement\s+date|statement\s+closing\s+date|as of)\s*:?\s*(" + _DATE_ANY + r")", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_amount_token(tok: str) -> Optional[float]:
    m = AMOUNT_TOKEN.match(tok.strip())
    if not m:
        return None
    v = float(m.group("num").replace(",", ""))
    neg = bool(m.group("neg1") or m.group("neg2") or m.group("neg3") or m.group("cr")
               or (m.group("open") and m.group("close")))
    return -v if neg else v


def parse_date(text: str, year_hint: Optional[int] = None,
               period_end: Optional[Tuple[int, int]] = None) -> Optional[str]:
    """ISO date from the shapes statements use. A date with no year takes
    the statement's year, and the year before it when the month is later
    than the period's end (a January statement listing December 28)."""
    m = DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        if m.group("num"):
            parts = re.split(r"[/-]", m.group("num"))
            month, day = int(parts[0]), int(parts[1])
            year = int(parts[2]) if len(parts) == 3 else None
        elif m.group("mdy"):
            mon, rest = m.group("mdy").split(None, 1)
            month = _MONTHS[mon[:3].lower()]
            bits = re.findall(r"\d+", rest)
            day, year = int(bits[0]), (int(bits[1]) if len(bits) > 1 else None)
        else:
            day_s, mon, *rest = re.split(r"[\s,]+", m.group("dmy").strip())
            month, day = _MONTHS[mon[:3].lower()], int(day_s)
            year = int(rest[0]) if rest and rest[0].isdigit() else None
    except (KeyError, ValueError, IndexError):
        return None
    if year is not None and year < 100:
        year += 2000
    if year is None:
        if year_hint is None:
            return None
        year = year_hint
        if period_end and month > period_end[1]:
            year -= 1
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def split_trailing_amounts(text: str) -> Tuple[str, List[Optional[float]], List[str]]:
    """'DESC 74.99 0 $5,684.49' -> ('DESC', [74.99, 0.0, 5684.49]).
    Amounts are taken from the right while the tokens look like amounts.
    A bare 0 is a placeholder in a debit/credit column and is kept as 0."""
    tokens = text.split()
    amounts: List[Optional[float]] = []
    raw: List[str] = []
    while tokens:
        tok = tokens[-1]
        v = parse_amount_token(tok)
        if v is None and ZERO_TOKEN.match(tok) and amounts:
            v = 0.0
        if v is None and ZERO_TOKEN.match(tok) and not amounts and len(tokens) > 1 \
                and parse_amount_token(tokens[-2]) is not None:
            v = 0.0
        if v is None:
            # "$1,234.56 CR" and "1,689.00 -" arrive as two tokens
            if tok.upper() in ("CR", "-") and len(tokens) > 1 and parse_amount_token(tokens[-2]) is not None:
                v = -abs(parse_amount_token(tokens[-2]))
                tokens.pop()
            else:
                break
        amounts.insert(0, v)
        raw.insert(0, tokens.pop())
    return " ".join(tokens), amounts, raw


def transaction_line(line: str) -> Optional[dict]:
    """A date at the start, at least one amount at the end, something in
    between. Returns the raw pieces, or None."""
    m = DATE_AT_START.match(line)
    if not m:
        return None
    rest = line[m.end():].strip()
    # a second date (posting date) right after the first is common on cards
    m2 = DATE_AT_START.match(rest)
    if m2:
        rest = rest[m2.end():].strip()
    desc, amounts, raw = split_trailing_amounts(rest)
    if not amounts or not desc.strip():
        return None
    return {"date_text": m.group(1), "description": re.sub(r"\s+", " ", desc).strip(),
            "amounts": amounts, "tokens": raw}


def balance_line(line: str) -> Optional[Tuple[str, float]]:
    """('beginning'|'ending', value) when the line carries a balance label
    and an amount after it, else None. A card statement prints several of
    each, and a bank statement with two accounts prints a pair per account,
    so the caller decides which ones matter."""
    m = BALANCE_WORDS.search(line)
    if not m:
        return None
    after = line[m.end(): m.end() + 40].replace(":", " ").replace("=", " ")
    for tok in after.split():
        v = parse_amount_token(tok)
        if v is not None:
            word = re.sub(r"\s+", "", m.group(0).lower())
            kind = "beginning" if word.startswith(("beginning", "previous", "opening", "starting", "balanceforward")) else "ending"
            return kind, v
    return None


def find_period(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """The statement period. The label and the dates are sometimes on
    separate lines, so each line is also tried joined with the next."""
    joined = [lines[i] + " " + (lines[i + 1] if i + 1 < len(lines) else "") for i in range(len(lines))]
    for line in joined:
        m = PERIOD_RE.search(line)
        if m:
            a, b = parse_date(m.group(1)), parse_date(m.group(2))
            if a and b:
                return a, b
    for line in joined:
        m = CLOSING_RE.search(line)
        if m:
            d = parse_date(m.group(1))
            if d:
                return None, d
    return None, None


def read_transactions(lines: List[str], year_hint: Optional[int] = None,
                      period_end: Optional[Tuple[int, int]] = None) -> List[dict]:
    """Every line that has the shape of a transaction, with its line index."""
    out = []
    for i, line in enumerate(lines):
        t = transaction_line(line)
        if not t:
            continue
        if NOT_A_TRANSACTION.search(t["description"]):
            continue
        d = parse_date(t["date_text"], year_hint, period_end)
        if not d:
            continue
        t["date"] = d
        t["line"] = i
        out.append(t)
    return out


def _signs_from_balance(txns: List[dict], beginning: Optional[float]) -> Optional[List[float]]:
    """When the last amount on every line is a running balance, each
    transaction's signed amount is the change in that balance. Returns the
    signed amounts, or None when the column does not behave like a balance,
    which is decided by every delta matching an amount printed on its line."""
    if not txns or any(len(t["amounts"]) < 2 for t in txns):
        return None
    prev = beginning
    signed = []
    for t in txns:
        bal = t["amounts"][-1]
        others = [abs(a) for a in t["amounts"][:-1] if a is not None and abs(a) > 0]
        if prev is None:
            if not others:
                return None
            amt = others[0]
        else:
            amt = round(bal - prev, 2)
            printed_zero = any(a == 0 for a in t["amounts"][:-1])
            if amt == 0 and printed_zero:
                pass                                    # a $0.00 line, a prenote say
            elif not others or not any(abs(abs(amt) - o) < 0.005 for o in others):
                return None
        signed.append(amt)
        prev = bal
    return signed


def _one_amount(amounts: List[Optional[float]], tokens: Optional[List[str]] = None) -> float:
    """Several amounts and no balance column. A debit/credit pair with a 0
    placeholder is the non-zero one, with the debit made negative when it
    is the first of the two. A last amount that carries the currency sign
    or a minus is the amount and the earlier ones are part of the
    description (a foreign charge prints "1,981.45 -$1,981.45"). With three
    or more, quantity and price come before the amount. Otherwise the first."""
    real = [a for a in amounts if a]
    first_two = amounts[:2]
    if len(amounts) >= 2 and sum(1 for a in first_two if a) == 1 and any(a == 0 for a in first_two):
        v = next(a for a in first_two if a)
        return -abs(v) if first_two[0] else abs(v)
    if tokens and len(tokens) >= 2 and re.search(r"[$(-]|CR$", tokens[-1], re.I)             and not re.search(r"[$(-]|CR$", tokens[0], re.I):
        return amounts[-1] or 0.0
    if tokens and len(tokens) >= 2 and all("$" in tok for tok in tokens):
        return amounts[-1] or 0.0       # price and amount both in dollars, the amount is last
    if len(amounts) >= 3:
        return amounts[-1] or 0.0
    return real[0] if real else 0.0


def _reconcile(txns: List[dict], begins: List[float], ends: List[float]) -> dict:
    """Signed amounts for these transactions and whether they add up, from
    the candidate balances. Tries a running balance column first, then the
    amounts as printed against every begin/end pair."""
    if not txns:
        if begins and ends and any(abs(b - e) < 0.005 for b in begins for e in ends):
            return {"signed": [], "beginning": begins[0], "ending": ends[-1], "balances": [],
                    "status": "reconciled, no transactions"}
        return {"signed": [], "beginning": begins[0] if begins else None,
                "ending": ends[-1] if ends else None, "balances": [],
                "status": "no transactions found" if (begins or ends) else "no balances printed"}
    for b in (begins or [None]):
        s = _signs_from_balance(txns, b)
        if s is not None:
            last = txns[-1]["amounts"][-1]
            if not ends or any(abs(last - e) < 0.005 for e in ends):
                return {"signed": s, "beginning": b, "ending": last,
                        "balances": [t["amounts"][-1] for t in txns], "status": "reconciled, balance column"}
    printed = [t["amounts"][0] if len(t["amounts"]) == 1 else _one_amount(t["amounts"], t.get("tokens")) for t in txns]
    total = round(sum(printed), 2)
    for b in begins:
        for e in ends:
            if abs(round(b + total, 2) - e) < 0.005:
                return {"signed": printed, "beginning": b, "ending": e, "balances": [],
                        "status": "reconciled, signed amounts"}
    out = {"signed": printed, "beginning": None, "ending": None, "balances": []}
    if begins and ends:
        out["beginning"], out["ending"] = begins[-1], ends[-1]
        out["status"] = "not reconciled, off by %s" % format(round(ends[-1] - (begins[-1] + total), 2), ",.2f")
    elif ends:
        out["ending"], out["status"] = ends[-1], "no beginning balance printed"
    elif begins:
        out["beginning"], out["status"] = begins[0], "no ending balance printed"
    else:
        out["status"] = "no balances printed"
    return out


def parse_statement(lines: List[str]) -> dict:
    """Everything the export needs from one statement's text lines.

    A statement is read as sections first. A bank statement that covers a
    checking and a savings account prints a beginning balance, the
    transactions, and an ending balance for each in turn, and each has to
    add up on its own. When the balance lines do not bracket the
    transactions that way, which is how a card statement prints its
    summary up front, the whole statement is one section and every printed
    balance is a candidate.
    """
    start, end = find_period(lines)
    year_hint = int(end[:4]) if end else None
    end_ym = (int(end[:4]), int(end[5:7])) if end else None
    txns = read_transactions(lines, year_hint, end_ym)
    marks = []                               # (line index, kind, value)
    for i, line in enumerate(lines):
        b = balance_line(line)
        if b:
            marks.append((i, b[0], b[1]))

    sections = _bracketed_sections(txns, marks)
    if sections is None:
        begins = [v for _, k, v in marks if k == "beginning"]
        ends = [v for _, k, v in marks if k == "ending"]
        sections = [dict(_reconcile(txns, begins, ends), txns=txns)]

    all_txns = []
    for n, sec in enumerate(sections, start=1):
        for t, amt in zip(sec["txns"], sec["signed"]):
            t["amount"] = amt
            t["section"] = n
        for t, bal in zip(sec["txns"], sec.get("balances") or []):
            t["balance"] = bal
        for t in sec["txns"]:
            t.setdefault("balance", None)
            all_txns.append(t)
    statuses = [s["status"] for s in sections]
    outside = [s for s in statuses if s.endswith("outside the balance brackets")]
    proper = [s for s in statuses if not s.endswith("outside the balance brackets")]
    if len(sections) == 1:
        status = statuses[0]
    elif all(s.startswith("reconciled") for s in proper):
        status = "reconciled, %d section%s" % (len(proper), "" if len(proper) == 1 else "s")
        if outside:
            status += ", " + outside[0]
    else:
        bad = [f"section {i}: {s}" for i, s in enumerate(statuses, start=1) if not s.startswith("reconciled")]
        status = "; ".join(bad)
    return {"period_start": start, "period_end": end,
            "beginning": next((s["beginning"] for s in sections if s["beginning"] is not None), None),
            "ending": next((s["ending"] for s in reversed(sections) if s["ending"] is not None), None),
            "sections": [{"beginning": s["beginning"], "ending": s["ending"], "status": s["status"],
                          "transactions": len(s["txns"]),
                          "sum": round(sum(s["signed"]), 2)} for s in sections],
            "transactions": all_txns, "status": status,
            "sum": round(sum(t["amount"] for t in all_txns), 2)}


def _bracketed_sections(txns: List[dict], marks: List[tuple]) -> Optional[List[dict]]:
    """Sections where a beginning balance line comes before the transactions
    and an ending balance line after them. None when the statement is not
    laid out that way, or when any section fails to reconcile on its own,
    since a wrong split is worse than no split."""
    begins = [(i, v) for i, k, v in marks if k == "beginning"]
    if not begins:
        return None
    ends = [(i, v) for i, k, v in marks if k == "ending"]
    sections = []
    for n, (bi, bv) in enumerate(begins):
        next_b = begins[n + 1][0] if n + 1 < len(begins) else float("inf")
        e = next(((ei, ev) for ei, ev in ends if bi < ei < next_b), None)
        if e is None:
            return None
        inside = [t for t in txns if bi < t["line"] < e[0]]
        r = _reconcile(inside, [bv], [e[1]])
        if not r["status"].startswith("reconciled"):
            return None
        sections.append(dict(r, txns=inside))
    placed = {id(t) for s in sections for t in s["txns"]}
    leftovers = [t for t in txns if id(t) not in placed]
    if leftovers:
        # A dated line between the sections, a check-image caption or a
        # note, is kept as a row but takes no part in any reconciliation.
        r = _reconcile(leftovers, [], [])
        r["status"] = "%d line(s) outside the balance brackets" % len(leftovers)
        sections.append(dict(r, txns=leftovers))
    return sections


# -- PDFs, the index, the cache --------------------------------------------------

def pdf_lines(path: Path) -> List[str]:
    import logging
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    import pdfplumber
    lines: List[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            try:
                for tl in page.extract_text_lines(layout=False, strip=True, return_chars=False):
                    lines.append(tl["text"])
            except Exception:
                text = page.extract_text() or ""
                lines.extend(text.splitlines())
    return [l for l in lines if l.strip()]


def find_indexes(root: Path) -> List[Tuple[str, Path]]:
    found = []
    if not root.is_dir():
        return found
    for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        for f in sorted(folder.glob("*" + INDEX_SUFFIX)):
            found.append((f.name[:-len(INDEX_SUFFIX)], f))
    return found


def providers(root: Path) -> List[dict]:
    """Statement archives with at least one PDF on disk."""
    out: "OrderedDict[str, dict]" = OrderedDict()
    for prov, f in find_indexes(root):
        rows = _index_rows(f)
        on_disk = sum(1 for r in rows if Path(r.get("PDF Full Path") or "").is_file())
        if not on_disk:
            continue
        e = out.setdefault(prov, {"provider": prov, "folders": [], "pdfs": 0})
        e["folders"].append(f.parent.name)
        e["pdfs"] += on_disk
    return list(out.values())


def _index_rows(path: Path) -> List[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class Cache:
    def __init__(self, root: Path):
        self.path = root / CACHE_NAME
        self.data: dict = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") == CACHE_VERSION:
                self.data = raw.get("files", {})
        except Exception:
            self.data = {}
        self.dirty = False

    def key(self, p: Path) -> str:
        st = p.stat()
        return f"{p}|{st.st_size}|{int(st.st_mtime)}"

    def get(self, p: Path):
        return self.data.get(self.key(p))

    def put(self, p: Path, value) -> None:
        self.data[self.key(p)] = value
        self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": CACHE_VERSION, "files": self.data}), encoding="utf-8")
        os.replace(tmp, self.path)


# -- the export -------------------------------------------------------------------

TXN_COLUMNS = ["Provider", "Account", "Date", "Description", "Amount", "Balance",
               "Statement Date", "Statement", "Reconciled"]
STMT_COLUMNS = ["Provider", "Account", "Statement Date", "Statement", "Period Start", "Period End",
                "Beginning Balance", "Ending Balance", "Transactions", "Sum of Amounts", "Status"]


def export(root: Path, out: Optional[Path] = None, provider: Optional[str] = None,
           as_csv: bool = False, log=print) -> dict:
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        raise RuntimeError("pdfplumber is not installed. `pip install pdfplumber` in the panel's "
                           "environment, then build again.")
    indexes = find_indexes(root)
    if provider:
        indexes = [(p, f) for p, f in indexes if p.lower() == provider.lower()]
        if indexes:
            provider = indexes[0][0]
    cache = Cache(root)
    txn_rows: List[dict] = []
    stmt_rows: List[dict] = []
    per_provider: Dict[str, int] = {}
    read = missing = 0
    for prov, index in indexes:
        for row in _index_rows(index):
            p = Path(row.get("PDF Full Path") or "")
            if not p.is_file():
                missing += 1
                continue
            parsed = cache.get(p)
            if parsed is None:
                try:
                    parsed = parse_statement(pdf_lines(p))
                except Exception as e:
                    parsed = {"period_start": None, "period_end": None, "beginning": None, "ending": None,
                              "transactions": [], "status": "could not read, %s" % str(e).splitlines()[0][:80],
                              "sum": 0.0}
                cache.put(p, parsed)
                read += 1
                if read % 25 == 0:
                    log(f"  read {read} statement(s)...")
            account = row.get("Document Title") or row.get("Document Summary") or ""
            if row.get("Account Holder"):
                account = f"{row['Account Holder']}, {account}" if account else row["Account Holder"]
            stmt_date = row.get("Document Date") or parsed.get("period_end") or ""
            name = p.name
            reconciled = parsed["status"].startswith("reconciled")
            for t in parsed["transactions"]:
                txn_rows.append({"Provider": prov, "Account": account, "Date": t["date"],
                                 "Description": t["description"], "Amount": t.get("amount"),
                                 "Balance": t.get("balance"), "Statement Date": stmt_date,
                                 "Statement": name, "Reconciled": "yes" if reconciled else "no"})
            stmt_rows.append({"Provider": prov, "Account": account, "Statement Date": stmt_date,
                              "Statement": name, "Period Start": parsed.get("period_start"),
                              "Period End": parsed.get("period_end"),
                              "Beginning Balance": parsed.get("beginning"), "Ending Balance": parsed.get("ending"),
                              "Transactions": len(parsed["transactions"]), "Sum of Amounts": parsed.get("sum"),
                              "Status": parsed["status"]})
            per_provider[prov] = per_provider.get(prov, 0) + len(parsed["transactions"])
    cache.save()
    txn_rows.sort(key=lambda r: (r["Date"] or "", r["Provider"], r["Statement"]), reverse=True)
    stmt_rows.sort(key=lambda r: (r["Statement Date"] or "", r["Provider"]), reverse=True)

    have_openpyxl = True
    if not as_csv:
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            have_openpyxl = False
            as_csv = True
    stem = (provider or "All") + " Transactions"
    if out is None:
        out = root / (stem + (".csv" if as_csv else ".xlsx"))
    elif as_csv and out.suffix.lower() == ".xlsx":
        out = out.with_suffix(".csv")
    try:
        if as_csv:
            _write_csv(out, txn_rows)
        else:
            _write_xlsx(out, txn_rows, stmt_rows)
    except PermissionError:
        raise PermissionError(f"{out.name} is open in another program, Excel most likely. "
                              "Close it and build again.") from None
    reconciled = sum(1 for s in stmt_rows if s["Status"].startswith("reconciled"))
    return {"path": str(out), "format": "csv" if as_csv else "xlsx", "transactions": len(txn_rows),
            "statements": len(stmt_rows), "reconciled": reconciled, "providers": per_provider,
            "read": read, "cached": len(stmt_rows) - read, "missing": missing,
            "openpyxl_missing": not have_openpyxl,
            "written_at": datetime.now().isoformat(timespec="seconds")}


def _write_csv(path: Path, rows: List[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=TXN_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})


def _write_xlsx(path: Path, txns: List[dict], stmts: List[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    def sheet(ws, columns, rows, widths, money):
        ws.append(columns)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([r.get(c) for c in columns])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, col in enumerate(columns, start=1):
            letter = get_column_letter(i)
            ws.column_dimensions[letter].width = widths.get(col, 14)
            if col in money:
                for cell in ws[letter][1:]:
                    cell.number_format = "#,##0.00;[Red]-#,##0.00"

    sheet(wb.active, TXN_COLUMNS, txns,
          {"Description": 58, "Account": 34, "Statement": 60, "Provider": 16, "Date": 11},
          {"Amount", "Balance"})
    wb.active.title = "Transactions"
    sheet(wb.create_sheet("Statements"), STMT_COLUMNS, stmts,
          {"Account": 34, "Statement": 60, "Status": 34, "Provider": 16},
          {"Beginning Balance", "Ending Balance", "Sum of Amounts"})
    wb.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The transactions inside your statement PDFs, in one spreadsheet.")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent),
                    help="folder holding the installs (default: this file's folder)")
    ap.add_argument("--out", help="where to write (default: '<root>/All Transactions.xlsx')")
    ap.add_argument("--provider", help="one provider only, e.g. USAA")
    ap.add_argument("--csv", action="store_true", help="write a .csv instead of .xlsx")
    args = ap.parse_args(argv)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"Not a folder: {root}", file=sys.stderr)
        return 2
    try:
        r = export(root, Path(args.out) if args.out else None, args.provider, args.csv)
    except (PermissionError, RuntimeError) as e:
        print(e, file=sys.stderr)
        return 2
    if not r["statements"]:
        print("No statement PDFs found under", root)
        print("A statement archive's PDFs have to be on disk to read. Receipt archives are not part of this.")
        return 1
    for prov, n in sorted(r["providers"].items()):
        print(f"  {prov:28} {n:6} transactions")
    print(f"\n{r['transactions']} transactions from {r['statements']} statements, "
          f"{r['reconciled']} of which reconcile to the cent. "
          f"{r['read']} read now, {r['cached']} from the cache, {r['missing']} PDF(s) not on disk.")
    if r["openpyxl_missing"]:
        print("openpyxl is not installed, so this is a .csv. `pip install openpyxl` for .xlsx.")
    print("Wrote", r["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
