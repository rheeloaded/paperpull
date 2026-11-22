#!/usr/bin/env python3
"""Every purchase from every receipt archive, in one spreadsheet.

    python export_purchases.py                    one workbook beside the installs
    python export_purchases.py --provider Amazon  just one provider
    python export_purchases.py --csv              a .csv instead of .xlsx
    python export_purchases.py --root "D:\\path\\to\\installs" --out purchases.xlsx

The receipt apps (Amazon, Target, Walmart, Gap) already record every line
item they saw while downloading, one row per item, in an `<Provider> Order
History.csv` beside the PDFs. Legacy Meijer summary rows are recovered
locally from their saved PDFs when possible. This walks the
installs folder, finds those files, including the ones in second-account
folders, and writes them out as one long table with a Provider column, plus
an Orders sheet with one row per order and a Summary sheet with a total per
provider per year.

The workbook is rebuilt from the CSVs every time, so it is never the copy
you edit. Amounts are written as numbers, so Excel can sum them. Item
names and every other text are written as text, never as a formula, since
a seller chooses an item's name (paperpull_core.sheets).

Needs `openpyxl` for .xlsx. Without it the tool writes a .csv and says so.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# The core beside this tool comes first, as tools/migrate.py takes it, so
# the rule for what a cell may hold is the one shipped with this copy.
_CORE = Path(__file__).resolve().parents[1] / "core"
if (_CORE / "paperpull_core").is_dir() and str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
try:
    from paperpull_core import shared_folder  # noqa: E402
    from paperpull_core.sheets import csv_value, keep_text, read_stored, xlsx_value  # noqa: E402
except ImportError as e:
    raise ImportError("export_purchases.py needs PaperPull's core folder beside its tools folder") from e

HISTORY_SUFFIX = " Order History.csv"
# The apps write money in one canonical form, an optional minus, the store's
# symbol ($, £, €, kr, zł) and a dot for the decimal, so this reads that.
_MONEY = re.compile(r"(-)?\s*(?:\$|£|€|kr|zł)?\s*(-)?([\d,]*\.?\d+)")

# Output columns, in order. Each maps to the CSV column it comes from, or to
# None when it is computed here.
COLUMNS = [
    ("Provider", None),
    ("Account", "Account Holder"),
    ("Date", "Purchase Date"),
    ("Order Number", "Order or Receipt Number"),
    ("Item", "Item Name"),
    ("Quantity", "Quantity"),
    ("Pricing Quantity", "Pricing Quantity"),
    ("Pricing Unit", "Pricing Unit"),
    ("Unit Price", "Unit Price"),
    ("Line Total", "Line Item Total"),
    ("Order Total", "Order Total"),
    ("Type", "Purchase Type"),
    ("Fulfillment", "Fulfillment Method"),
    ("Order Status", "Order Status"),
    ("Return Status", "Return Status"),
    ("Category", "Purchase Summary"),
    ("Receipt PDF", "PDF Filename"),
    ("Processing", "Processing Status"),
    ("Notes", "Notes"),
]
NUMERIC = {"Pricing Quantity", "Quantity", "Unit Price", "Line Total", "Order Total"}
MONEY = {"Unit Price", "Line Total", "Order Total"}

ORDER_COLUMNS = ["Provider", "Account", "Date", "Order Number", "Items", "Order Total",
                 "Type", "Fulfillment", "Order Status", "Category", "Receipt PDF"]


def money(text) -> Optional[float]:
    """'$1,234.56' -> 1234.56, '-$5.00' -> -5.0, '' -> None."""
    if text is None:
        return None
    m = _MONEY.search(str(text))
    if not m:
        return None
    value = float(m.group(3).replace(",", ""))
    return -value if (m.group(1) or m.group(2)) else value


def quantity(text) -> Optional[float]:
    if text is None or not str(text).strip():
        return None
    try:
        v = float(str(text).strip())
    except ValueError:
        return None
    return int(v) if v.is_integer() else v


def find_histories(root: Path) -> List[Tuple[str, Path]]:
    """(provider, csv path) for every order-history file one level down.
    Second-account folders hold their own copy and are found the same way."""
    found = []
    if not root.is_dir():
        return found
    for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        for f in sorted(folder.glob("*" + HISTORY_SUFFIX)):
            found.append((f.name[:-len(HISTORY_SUFFIX)], f))
    return found


def providers(root: Path) -> List[dict]:
    """The providers a spreadsheet makes sense for, which is the ones with an
    order history, each with the folders it would draw from. A statement
    archive has documents, not line items, and is not listed."""
    out: "OrderedDict[str, dict]" = OrderedDict()
    for prov, f in find_histories(root):
        entry = out.setdefault(prov, {"provider": prov, "folders": []})
        entry["folders"].append(f.parent.name)
    return list(out.values())


def load_purchases(provider: str, path: Path) -> List[dict]:
    """One dict per line item, keyed by the output column names."""
    rows = []
    # The rows whose purchase had a receipt link (Meijer's placeholder rule).
    linked = set()
    # A plain file of its own, never a pipe, which held the panel, where this
    # export runs, for good, and on PaperPull Server never through a link.
    with io.StringIO(shared_folder.read_text(path, "utf-8-sig"), newline="") as fh:
        for raw in csv.DictReader(fh):
            row = {}
            for out, src in COLUMNS:
                # The app put a quote in front of a value that starts like a
                # formula, and it comes off here as it does in the app.
                value = provider if src is None else (read_stored(raw.get(src)) or "").strip()
                if out in MONEY:
                    value = money(value)
                elif out in {"Quantity", "Pricing Quantity"}:
                    value = quantity(value)
                elif out == "Pricing Unit" and not value:
                    value = None
                row[out] = value
            if not row["Date"] and not row["Item"] and not row["Order Number"]:
                continue
            rows.append(row)
            if (read_stored(raw.get("Receipt URL")) or "").strip():
                linked.add(id(row))
    return recover_meijer_items(provider, path, without_unsaved_writes(rows), linked)


# The names a Meijer list row gave its one item before 0.70.0, "In-Store:"
# and, for a row with no store line, "Meijer order".
_MEIJER_PLACEHOLDER = re.compile(r"in[ -]?store\s*:?|meijer order", re.I)
# Where a Meijer receipt is filed, by its purchase type (apps/meijer/storage.py).
_MEIJER_FOLDERS = {"In-Store": "In-Store", "Online": "Online"}
_RECOVERED = ("Recovered locally from the Meijer receipt PDF. Review weights and coupons, "
              "a blank price is unknown.")
_UNRECOVERED = "Meijer product details unavailable. Review the original receipt PDF."


def _meijer_placeholder(row: dict, linked: bool = False) -> bool:
    """Whether a Meijer history row is the order list's words priced at the
    receipt's whole total rather than a product. Before 0.70.0 that row was
    named "In-Store:" or "Meijer order". 0.70.0 names it after the store's
    address line (#236), an in-store purchase's row with no receipt link,
    quantity 1, no unit price and the whole total as its line total. The
    receipt reader prices every counted item, so it never writes that
    shape, and a purchase with no receipt link was never read from a
    receipt page (meijer_site.extract_items), whose one-product rows look
    the same. A row with no item, a canceled order's, is not one."""
    name = (row.get("Item") or "").strip()
    if not name:
        return False
    if _MEIJER_PLACEHOLDER.fullmatch(name):
        return True
    return (not linked and row.get("Type") == "In-Store"
            and row.get("Quantity") == 1 and row.get("Unit Price") is None
            and row.get("Line Total") is not None
            and row.get("Line Total") == row.get("Order Total"))


def _saved_meijer_receipt(history: Path, row: dict) -> Optional[Path]:
    """The saved receipt a Meijer row names, a plain file inside the
    history's own folder, or None. A row names its file by name alone, so
    anything else it holds, a folder, "..", a drive or a full path, names no
    receipt here, and so does a name a link or a junction leads out of the
    folder from. Asked so it never raises, a folder the export may not
    search counting as no receipt."""
    name = row.get("Receipt PDF") or ""
    if not name:
        return None
    try:
        ref = Path(name)
        if ref.anchor or len(ref.parts) != 1 or ref.name in (".", ".."):
            return None
        base = history.parent.resolve()
        folders = [_MEIJER_FOLDERS.get(row.get("Type") or "", "In-Store"), "In-Store", "Online", ""]
        for folder in dict.fromkeys(folders):
            candidate = base / folder / ref if folder else base / ref
            if shared_folder.linked(candidate) or not candidate.resolve().is_relative_to(base):
                continue
            if candidate.is_file():
                return candidate
    except (OSError, ValueError, RuntimeError):
        return None
    return None


def _noted(row: dict, note: str) -> str:
    return "; ".join(x for x in (row.get("Notes") or "", note) if x)


def recover_meijer_items(provider: str, history: Path, rows: List[dict],
                         linked=frozenset()) -> List[dict]:
    """Meijer histories written before the app read its receipts hold the
    order list's words as the one item, priced at the receipt's total. Such
    a row is read again from its saved receipt, when that receipt's date and
    total match the row's and its items, discounts and tax add up
    (paperpull_core.meijer_items), and otherwise shows no product and no
    price and asks for review. The history and the receipts are only read,
    never written.

    An order has at most one such row in the export. When the order has
    products written down as well, from a later Download again, those are
    its rows and its placeholders are left out, and an order written down
    twice is read once, so no item is listed twice and no total counted as
    a product. `linked` holds the ids of the rows whose purchase had a
    receipt link (load_purchases)."""
    if provider.lower() != "meijer":
        return rows

    def key_of(row):
        return (row.get("Account"), row.get("Order Number")) if row.get("Order Number") else id(row)

    from paperpull_core.meijer_items import read_items
    placeholder = {id(r) for r in rows if _meijer_placeholder(r, id(r) in linked)}
    with_products = {key_of(r) for r in rows
                     if id(r) not in placeholder and (r.get("Item") or "").strip()}
    recovered, done = [], set()
    for row in rows:
        if id(row) not in placeholder:
            recovered.append(row)
            continue
        key = key_of(row)
        if key in with_products or key in done:
            continue
        done.add(key)
        items = []
        receipt = None
        if row.get("Date") and row.get("Order Total"):
            receipt = _saved_meijer_receipt(history, row)
        if receipt is not None:
            items = read_items(receipt, row["Date"], row["Order Total"])
        if items:
            for item in items:
                recovered.append({**row, "Item": item.name, "Quantity": quantity(item.quantity),
                                  "Pricing Quantity": quantity(item.pricing_quantity),
                                  "Pricing Unit": item.pricing_unit or None,
                                  "Unit Price": money(item.unit_price),
                                  "Line Total": money(item.line_total),
                                  "Processing": "Review Needed", "Notes": _noted(row, _RECOVERED)})
        else:
            recovered.append({**row, "Item": "", "Quantity": None, "Pricing Quantity": None,
                              "Pricing Unit": None, "Unit Price": None, "Line Total": None,
                              "Processing": "Review Needed", "Notes": _noted(row, _UNRECOVERED)})
    return recovered


def without_unsaved_writes(rows: List[dict]) -> List[dict]:
    """An order's rows from a write that saved no receipt, when a later
    write of the same order saved one. An app writes an order down again
    when a later run saves it, an older version's write for a receipt page
    that did not show its receipt (#70) among them, and the history only
    ever takes rows on the end. Kept, each item was listed twice and the
    order's Receipt PDF was the empty one of its first row."""
    saved = {(r["Account"], r["Order Number"]) for r in rows
             if r["Order Number"] and r["Receipt PDF"]}
    return [r for r in rows if r["Receipt PDF"] or not r["Order Number"]
            or (r["Account"], r["Order Number"]) not in saved]


def orders_from(purchases: List[dict]) -> List[dict]:
    """One row per order. The order total repeats on every line item in the
    history, so it is taken once, and Items counts the lines."""
    by_key: "OrderedDict[tuple, dict]" = OrderedDict()
    for p in purchases:
        key = (p["Provider"], p["Account"], p["Order Number"] or p["Date"] + "|" + (p["Receipt PDF"] or ""))
        o = by_key.get(key)
        if o is None:
            o = {c: p.get(c) for c in ORDER_COLUMNS if c != "Items"}
            o["Items"] = 0
            by_key[key] = o
        o["Items"] += 1
        if o.get("Order Total") is None and p.get("Order Total") is not None:
            o["Order Total"] = p["Order Total"]
    return list(by_key.values())


def summary_from(orders: List[dict]) -> List[dict]:
    """Spend per provider per year, from the Orders sheet so each order counts once."""
    totals: Dict[Tuple[str, str], List[float]] = {}
    for o in orders:
        year = (o.get("Date") or "")[:4] or "unknown"
        cell = totals.setdefault((o["Provider"], year), [0, 0.0])
        cell[0] += 1
        cell[1] += o.get("Order Total") or 0.0
    rows = [{"Provider": p, "Year": y, "Orders": n, "Total": round(t, 2)}
            for (p, y), (n, t) in totals.items()]
    rows.sort(key=lambda r: (r["Provider"], r["Year"]), reverse=False)
    return rows


def sort_newest_first(rows: List[dict]) -> List[dict]:
    return sorted(rows, key=lambda r: ((r.get("Date") or ""), r.get("Provider") or "",
                                       r.get("Order Number") or ""), reverse=True)


def write_csv(path: Path, purchases: List[dict]) -> None:
    """Item names, notes and the rest are written as text a spreadsheet will
    not take for a formula (paperpull_core.sheets). Amounts are numbers."""
    # On PaperPull Server never written through a link left at its name.
    with shared_folder.open_to_write(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[c for c, _ in COLUMNS])
        w.writeheader()
        for p in purchases:
            w.writerow({k: csv_value(v) for k, v in p.items()})


def write_xlsx(path: Path, purchases: List[dict], orders: List[dict], summary: List[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    def sheet(ws, columns, rows, widths):
        ws.append(columns)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([xlsx_value(r.get(c)) for c in columns])
        # Every text cell a string cell, never a formula, on every sheet.
        for line in ws.iter_rows():
            for cell in line:
                keep_text(cell)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, col in enumerate(columns, start=1):
            letter = get_column_letter(i)
            ws.column_dimensions[letter].width = widths.get(col, 14)
            if col in MONEY or col == "Total":
                for cell in ws[letter][1:]:
                    cell.number_format = "#,##0.00"

    sheet(wb.active, [c for c, _ in COLUMNS], purchases,
          {"Item": 60, "Order Number": 22, "Category": 26, "Receipt PDF": 44, "Notes": 30,
           "Provider": 11, "Date": 11, "Quantity": 9, "Pricing Quantity": 18, "Pricing Unit": 14, "Fulfillment": 14})
    wb.active.title = "Purchases"
    sheet(wb.create_sheet("Orders"), ORDER_COLUMNS, orders,
          {"Order Number": 22, "Category": 26, "Receipt PDF": 44, "Provider": 11, "Date": 11})
    sheet(wb.create_sheet("Summary"), ["Provider", "Year", "Orders", "Total"], summary, {})
    with shared_folder.open_to_write(path, "wb") as fh:
        wb.save(fh)


def export(root: Path, out: Optional[Path] = None, provider: Optional[str] = None,
           as_csv: bool = False) -> dict:
    """Build the workbook. Returns what was written, for the panel and the
    CLI, with path None when no order history was found to write from."""
    histories = find_histories(root)
    if provider:
        histories = [(p, f) for p, f in histories if p.lower() == provider.lower()]
        if histories:
            provider = histories[0][0]      # the archive's own spelling
    purchases: List[dict] = []
    per_provider: Dict[str, int] = {}
    for prov, f in histories:
        rows = load_purchases(prov, f)
        per_provider[prov] = per_provider.get(prov, 0) + len(rows)
        purchases.extend(rows)
    purchases = sort_newest_first(purchases)
    orders = sort_newest_first(orders_from(purchases))
    summary = summary_from(orders)

    have_openpyxl = True
    if not as_csv:
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            have_openpyxl = False
            as_csv = True
    stem = (provider or "All") + " Purchases"
    if out is None:
        out = root / (stem + (".csv" if as_csv else ".xlsx"))
    elif as_csv and out.suffix.lower() == ".xlsx":
        out = out.with_suffix(".csv")
    # With no order history there is nothing to build, so nothing is
    # written. An empty spreadsheet was left behind every time the answer
    # was that there was nothing to export, in place of the last one built.
    written = None
    if histories:
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if as_csv:
                write_csv(out, purchases)
            else:
                write_xlsx(out, purchases, orders, summary)
        except PermissionError:
            # Excel holds the file open with an exclusive lock, and this is the
            # one error a person can fix in a second, so say exactly that.
            raise PermissionError(f"{out.name} is open in another program, Excel most likely. "
                                  "Close it and build again.") from None
        written = str(out)
    return {
        "path": written,
        "format": "csv" if as_csv else "xlsx",
        "purchases": len(purchases),
        "orders": len(orders),
        "providers": per_provider,
        "sources": [str(f) for _p, f in histories],
        "openpyxl_missing": not have_openpyxl,
        "written_at": datetime.now().isoformat(timespec="seconds"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Every purchase from every receipt archive, in one spreadsheet.")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent),
                    help="folder holding the installs (default: this file's folder)")
    ap.add_argument("--out", help="where to write (default: '<root>/All Purchases.xlsx')")
    ap.add_argument("--provider", help="one provider only, e.g. Amazon")
    ap.add_argument("--csv", action="store_true", help="write a .csv instead of .xlsx")
    args = ap.parse_args(argv)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"Not a folder: {root}", file=sys.stderr)
        return 2
    try:
        result = export(root, Path(args.out) if args.out else None, args.provider, args.csv)
    except PermissionError as e:
        print(e, file=sys.stderr)
        return 2
    if not result["sources"]:
        print("No '<Provider> Order History.csv' found under", root)
        print("Receipt apps write one after a run. Statement apps have no line items to export.")
        return 1
    for prov, n in sorted(result["providers"].items()):
        print(f"  {prov:12} {n:6} line items")
    print(f"\n{result['purchases']} purchases across {result['orders']} orders")
    if result["openpyxl_missing"]:
        print("openpyxl is not installed, so this is a .csv. `pip install openpyxl` for .xlsx.")
    print("Wrote", result["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
