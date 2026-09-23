"""Build the sample archive.

Every name, account, amount, date and item in it is invented. Nothing is
read from a real install, and no real person or account appears. The point
is that somebody who has just installed PaperPull, or a reviewer who holds
no account anywhere, can see a filled Status tab and build both
spreadsheets without signing in to anything.

The panel calls build() when somebody asks to see the sample, writing it
beside their settings file. This script is the same thing from a terminal.

    python tools/make_sample.py --out DIR

Nothing it writes is committed. A tree of files named and shaped exactly
like real statements is what .gitignore exists to keep out of this
repository, and an archive that can be rebuilt in a second from a fixed
seed does not need to be carried around in git or in the installer.

The statement PDFs are written here rather than rendered by a browser, so
this needs nothing installed. They are single-page, Courier, one text
layer, which is what `pdfplumber` reads in tools/export_transactions.py,
and about three kilobytes each instead of eighteen.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import zlib
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Fixed so a rebuild produces the same archive and the diff stays empty
# unless the shape really changed.
TODAY = date(2026, 9, 1)
OWNER = "Sample"
SEED = 11
rng = random.Random(SEED)


# -- a minimal PDF ------------------------------------------------------------
#
# One page, one font, one text block. Enough structure for a PDF reader to
# find the words, and nothing else. Written by hand because the alternative
# is a browser, and a build tool that needs a browser is a build tool that
# stops working.

def _escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path: Path, lines: list[str], size: float = 8.5, leading: float = 11.5) -> None:
    text = ["BT", "/F1 %.1f Tf" % size, "%.1f TL" % leading, "1 0 0 1 40 752 Tm"]
    for line in lines:
        text.append("(%s) Tj T*" % _escape(line))
    text.append("ET")
    stream = zlib.compress("\n".join(text).encode("latin-1", "replace"))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref))
    path.write_bytes(bytes(out))


# -- the installs -------------------------------------------------------------

def install(root: Path, name: str, slug: str, provider: str, kind: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / ("%s_%s.py" % (slug, "receipts" if kind == "RECEIPT" else "docs"))).write_text(
        '"""Part of the sample archive. The real app is installed separately."""\n', encoding="utf-8")
    (d / "storage.py").write_text(
        'SPEC = AppSpec(\n    provider="%s",\n    kind=%s,\n)\n' % (provider, kind), encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"output_dir": str(d), "owner": OWNER}, indent=1), encoding="utf-8")
    return d


def month_ends(n: int, newest: date) -> list[date]:
    out, y, m = [], newest.year, newest.month
    for _ in range(n):
        last = (date(y, m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)) - timedelta(days=1)
        out.append(last)
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


DESCS = [("ACH DEP PAYROLL NORTHWIND LLC", 1), ("POS DEBIT CORNER MARKET", -1),
         ("RECURRING DEB CARD STREAMING SVC", -1), ("EXTERNAL BILL PAYMENT CITY UTILITIES", -1),
         ("DEPOSIT@MOBILE", 1), ("POS DEBIT FUEL STOP 118", -1), ("ACH DEBIT PHONE CO", -1),
         ("TRANSFER TO SAVINGS", -1), ("POS DEBIT HARDWARE STORE", -1), ("ZELLE FROM R MORGAN", 1),
         ("ACH DEBIT MORTGAGE PMT", -1), ("POS DEBIT WAREHOUSE CLUB", -1), ("INTEREST PAID", 1)]


def statement_lines(provider: str, acct: str, start: date, end: date, opening: float) -> tuple[list[str], float]:
    """The layout export_transactions.py knows how to read, a header with
    the period and the opening balance, a table, then the closing balance."""
    head = ["%s %s account statement" % (provider, acct),
            "Statement Period: %s to %s" % (start.strftime("%m/%d/%Y"), end.strftime("%m/%d/%Y")),
            "Beginning Balance $%s" % format(opening, ",.2f")]
    bal, body, day = opening, [], start
    for _ in range(rng.randint(9, 14)):
        day += timedelta(days=rng.randint(1, 3))
        if day > end:
            break
        desc, sign = rng.choice(DESCS)
        amt = 2153.25 if desc.startswith("ACH DEP PAYROLL") else (
            round(rng.uniform(4, 380), 2) if sign < 0 else round(rng.uniform(25, 2400), 2))
        bal = round(bal + sign * amt, 2)
        deb, cred = ("$%s" % format(amt, ",.2f"), "0") if sign < 0 else ("0", "$%s" % format(amt, ",.2f"))
        body.append("%s %-32s %12s %12s $%s" % (day.strftime("%m/%d"), desc, deb, cred, format(bal, ",.2f")))
    lines = head + ["Ending Balance $%s" % format(bal, ",.2f"),
                    "",
                    "Date  Description                       Debits       Credits      Balance",
                    "%s %-32s %12s %12s $%s" % (start.strftime("%m/%d"), "Beginning Balance", "0", "0", format(opening, ",.2f"))]
    lines += body
    lines += ["%s %-32s %12s %12s $%s" % (end.strftime("%m/%d"), "Ending Balance", "-", "-", format(bal, ",.2f")),
              "",
              "This is a sample document created by PaperPull to demonstrate the program.",
              "It is not a real statement. Every name, amount and date in it is invented."]
    return lines, bal


DOC_COLS = ["Account Holder", "Document Date", "Category", "Document Summary", "Document Title", "Period",
            "PDF Filename", "PDF Full Path", "PDF File Size", "PDF Page Count", "Source URL",
            "Classification Confidence", "Downloaded At", "Verified At", "Processing Status", "Notes"]


def statements(root: Path, name: str, slug: str, provider: str, accounts: list[str],
               n: int, newest: date, skip: tuple = ()) -> None:
    d = install(root, name, slug, provider, "DOCUMENT")
    folder = d / "Statements"
    folder.mkdir()
    progress, rows = {}, []
    for acct in accounts:
        opening = round(rng.uniform(1500, 9000), 2)
        for end in month_ends(n, newest):
            if end.isoformat()[:7] in skip:
                continue
            start = end.replace(day=1)
            label = ("%s %s" % (provider, acct)).strip()
            lines, opening = statement_lines(provider, acct or "Account", start, end, opening)
            pdf = "%s %s Statement.pdf" % (end, label)
            write_pdf(folder / pdf, lines)
            key = "%s:%s:Statement" % (acct or "primary", end)
            progress[key] = {"date": end.isoformat(), "account": acct or "primary", "category": "Statement",
                             "title": "%s statement" % (acct or "Account"), "downloaded_ok": True,
                             "pdf_filename": pdf,
                             "updated_at": (end + timedelta(days=rng.randint(2, 9))).isoformat() + "T07:30:00"}
            rows.append({"Account Holder": OWNER, "Document Date": end.isoformat(), "Category": "Statement",
                         "Document Summary": "Monthly Statement", "Document Title": "%s statement" % (acct or "Account"),
                         "Period": "%s to %s" % (start, end), "PDF Filename": pdf,
                         "PDF Full Path": str(folder / pdf), "PDF File Size": (folder / pdf).stat().st_size,
                         "PDF Page Count": 1, "Source URL": "", "Classification Confidence": "High",
                         "Downloaded At": "", "Verified At": "", "Processing Status": "Completed", "Notes": ""})
    (d / "progress.json").write_text(json.dumps(progress, indent=1), encoding="utf-8")
    with open(d / ("%s Document Index.csv" % provider), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DOC_COLS)
        w.writeheader()
        w.writerows(rows)


ITEMS = {
    "Amazon": [("USB-C Charger 65W", 39.99), ("Cold Brew Coffee, 12 ct", 24.49), ("Cast Iron Skillet 12 in", 34.95),
               ("AA Batteries, 48 pack", 18.72), ("Running Socks, 6 pair", 21.99), ("Water Bottle 20 oz", 14.99),
               ("Paper Towels, 12 rolls", 26.48), ("HDMI Cable 6 ft", 8.99), ("Desk Lamp with USB Port", 29.99),
               ("Air Filter 16x25x1, 4 pack", 31.96), ("Dog Treats, 3 lb", 19.98), ("Bluetooth Tracker Tag", 24.99)],
    "Target": [("Whole Milk 1 gal", 3.99), ("Paper Plates 100 ct", 6.49), ("Kids Tee", 8.00),
               ("Bath Towel", 12.00), ("Laundry Pods 42 ct", 21.99), ("Eggs 12 ct", 4.29),
               ("Hangers 10 pk", 5.00), ("Crackers 12 oz", 4.19), ("Paper Towels 6 rolls", 15.99),
               ("Kids Sneakers", 24.99), ("Building Brick Set", 19.99), ("Birthday Card", 4.99)],
}
CATS = ["Groceries", "Household", "Electronics", "Clothing", "Pet Supplies", "Kids"]
BUY_COLS = ["Account Holder", "Purchase Type", "Purchase Date", "Order or Receipt Number", "Item Name", "Quantity",
            "Unit Price", "Line Item Total", "Order Total", "Purchase Summary", "Order Status", "PDF Filename",
            "Processing Status", "Notes"]


def receipts(root: Path, name: str, slug: str, provider: str, n_orders: int, pdfs: int) -> None:
    d = install(root, name, slug, provider, "RECEIPT")
    rows, progress, made = [], {}, []
    pool = ITEMS[provider]
    for _ in range(n_orders):
        when = TODAY - timedelta(days=rng.randint(1, 700))
        order = "%03d-%07d-%07d" % (rng.randint(100, 120), rng.randint(0, 9999999), rng.randint(0, 9999999))
        total, lines = 0.0, []
        for item, price in rng.sample(pool, rng.randint(1, 4)):
            qty = rng.choice([1, 1, 1, 2])
            total += qty * price
            lines.append((item, qty, price))
        total = round(total * 1.06, 2)
        cat = rng.choice(CATS)
        ptype = "Online" if provider == "Amazon" or rng.random() < 0.6 else "In-Store"
        pdf = "%s %s %s Receipt.pdf" % (when, provider, cat)
        for item, qty, price in lines:
            rows.append({"Account Holder": OWNER, "Purchase Type": ptype, "Purchase Date": when.isoformat(),
                         "Order or Receipt Number": order, "Item Name": item, "Quantity": qty,
                         "Unit Price": "$%.2f" % price, "Line Item Total": "$%.2f" % (qty * price),
                         "Order Total": "$%.2f" % total, "Purchase Summary": cat, "PDF Filename": pdf,
                         "Order Status": "Delivered", "Processing Status": "Completed", "Notes": ""})
        progress["%s:%s" % (ptype, order)] = {"purchase_date": when.isoformat(), "purchase_type": ptype,
                                              "order_number": order, "total": "$%.2f" % total,
                                              "downloaded_ok": True, "state": "Completed", "pdf_filename": pdf,
                                              "updated_at": (when + timedelta(days=1)).isoformat() + "T09:00:00"}
        made.append((when, order, ptype, cat, total, lines, pdf))
    rows.sort(key=lambda r: r["Purchase Date"], reverse=True)
    with open(d / ("%s Order History.csv" % provider), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BUY_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (d / "progress.json").write_text(json.dumps(progress, indent=1), encoding="utf-8")
    # Only the newest few orders get a PDF. The spreadsheet is built from the
    # line items recorded at download time, so the rest cost nothing to leave
    # out, and the folder still shows what a receipt looks like.
    made.sort(reverse=True)
    for when, order, ptype, cat, total, lines, pdf in made[:pdfs]:
        folder = d / ptype
        folder.mkdir(exist_ok=True)
        body = ["%s receipt" % provider, "Order %s" % order, "Placed %s" % when.strftime("%B %d, %Y"), "", "Items"]
        for item, qty, price in lines:
            body.append("  %-34s %2d x %8s %10s" % (item, qty, "$%.2f" % price, "$%.2f" % (qty * price)))
        body += ["", "%-38s %21s" % ("Order total", "$%.2f" % total), "",
                 "This is a sample document created by PaperPull to demonstrate the program.",
                 "It is not a real receipt. Every name, amount and date in it is invented."]
        write_pdf(folder / pdf, body)


def build(out: Path) -> None:
    # Reseeded per call, not once at import, so a second build in the same
    # process gives the same archive as the first. The panel rebuilds the
    # sample whenever somebody has deleted it.
    rng.seed(SEED)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # Two statement archives, so the transactions workbook has something to
    # read, one of them missing two months in the middle so the Status tab
    # shows the gap it is there to find.
    statements(out, "Chase Statements", "chase", "Chase", ["Sapphire", "Freedom"], 12, TODAY - timedelta(days=9))
    statements(out, "Navy Federal Statements", "navyfederal", "Navy Federal", ["Checking"], 14,
               TODAY - timedelta(days=4), skip=("2026-02", "2026-03"))
    # One archive nobody has run for months, so the Status tab has an overdue
    # row to show as well.
    statements(out, "Verizon Statements", "verizon", "Verizon", [""], 6, TODAY - timedelta(days=145))
    receipts(out, "Amazon Receipts", "amazon", "Amazon", 120, pdfs=4)
    receipts(out, "Target Receipts", "target", "Target", 70, pdfs=3)
    (out / "README.txt").write_text(
        "This is PaperPull's sample archive.\n\n"
        "Every document, name, amount and date in it is invented, to show what\n"
        "a real archive looks like without anyone having to sign in anywhere.\n"
        "Nothing here came from a real account.\n\n"
        "Delete this folder whenever you like. The panel makes it again the\n"
        "next time you ask to see the sample.\n", encoding="utf-8")
    pdfs = list(out.rglob("*.pdf"))
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print("sample archive at %s\n  %d installs, %d PDFs, %.0f KB total"
          % (out, sum(1 for d in out.iterdir() if d.is_dir()), len(pdfs), size / 1024))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="folder to build the sample into, replaced if it exists")
    build(Path(ap.parse_args().out))
