"""What makes the Kroger app different - everything else is paperpull_core.

This file used to be a full copy of the storage logic every other app carried.
That logic now lives in `paperpull_core`; what remains here is Kroger's own
facts: the folders it files into, how a document routes to one, its CSV
columns, and its config defaults.

To repair Kroger's *page* behavior, edit `kroger_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, RECEIPT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

ORDER_HISTORY_COLUMNS = [
    "Account Holder",
    "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Status",
    "Item Name", "Quantity", "Pricing Quantity", "Pricing Unit", "Unit Price", "Line Item Total", "Order Total",
    "Fulfillment Method", "Return Status", "Purchase Summary", "PDF Filename",
    "Purchase Details URL", "Receipt URL", "Processing Status", "Notes",
]

RECEIPT_INDEX_COLUMNS = [
    "Account Holder",
    "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Total",
    "Purchase Summary", "PDF Filename", "PDF Full Path", "Document Type",
    "Receipt Status", "Receipt Count", "Classification Confidence", "Receipt URL",
    "PDF File Size", "PDF Page Count", "Downloaded At", "Verified At",
    "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Kroger",
    countries=("US",),
    project_dir=Path(__file__).resolve().parent,
    kind=RECEIPT,
    folders=[
        Folder("online", "Online"),
        Folder("instore", "In-Store"),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Online": "online",
        "In-Store": "instore",
    },
    default_route="online",
    csv_files=[
        CsvSpec("order_history_csv", "Kroger Order History.csv", ORDER_HISTORY_COLUMNS),
        CsvSpec("receipt_index_csv", "Kroger Receipt Index.csv", RECEIPT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_online": 5,
        "pilot_instore": 3,
    },
    base_url="https://www.kroger.com/",
    rules_filename="category_rules.json",
)

_core.bind(SPEC)

PROJECT_DIR = SPEC.project_dir

# The shared API, re-exported so the orchestrator's imports read as they always did.
from paperpull_core.storage import (  # noqa: E402  (must follow bind)
    CsvFile, JsonStore, Paths, atomic_write_json, atomic_write_text,
    backup_file, build_pdf_filename, ensure_owner, load_config, now_iso,
    sanitize_component, set_filename_owner, title_case, unique_path,
)

import csv  # noqa: E402
import io  # noqa: E402
from typing import Optional  # noqa: E402

from paperpull_core import shared_folder  # noqa: E402
from paperpull_core.sheets import read_stored_row, store_value  # noqa: E402


# The two columns 0.71.0 added to the order history, after Quantity (#247).
PRICING_COLUMNS = ("Pricing Quantity", "Pricing Unit")


class HeaderNotUpgraded(OSError):
    """The order history still has an earlier version's header. An OSError,
    so a row that would go under it is kept beside the file, as a row is
    while Excel holds it (CsvFile), and goes in once the header is
    upgraded, never under columns it does not belong to."""


class UnknownHeader(HeaderNotUpgraded):
    """The order history's header is neither this version's nor the one
    before it, so it is never upgraded, written over or appended to."""


class PricingCsvFile(CsvFile):
    """Kroger's order history, whose header gained the two pricing columns
    (#247). A history with the earlier header is copied into Backups and
    written again with the new header, every row and value kept, before a
    row is appended, read or written. A row written into it before then
    would have gone under the wrong columns.

    Rows kept beside the file, from a run while Excel held it, are carried
    across. They go in after the upgrade under their own column names. A
    write of them that stopped part way left the place it began, which
    names bytes of the earlier file, so the rows found there are counted as
    in already, by the earlier columns, and the rest are kept again without
    that place before the file is written over. A run stopped between the
    two then finds the earlier file and only the rows not in it.

    When the upgrade cannot be made now, the file held by Excel say, the
    rows are kept beside the file and the next run upgrades it. A header
    this app never wrote is left as it is, and so is the file."""

    _said_unknown = False

    def _earlier_columns(self) -> list:
        return [c for c in self.columns if c not in PRICING_COLUMNS]

    def _decoded(self) -> str:
        data = shared_folder.read_plain(self.path)
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Saved again from Excel in the code page of Windows.
            return data.decode("cp1252")

    def _header(self) -> Optional[list]:
        """The file's header, trailing empty names Excel adds left off, or
        None when there is no file or it is empty."""
        try:
            text = self._decoded()
        except FileNotFoundError:
            return None
        except UnicodeDecodeError as e:
            raise UnknownHeader("%s could not be read as text" % self.path.name) from e
        first = next(csv.reader(io.StringIO(text, newline="")), None)
        if first is None:
            return None
        while first and not first[-1].strip():
            first.pop()
        return first

    def _upgrade(self) -> None:
        """Upgrade an earlier header, as the class says. OSError when it
        could not be done now, UnknownHeader for a header it never wrote."""
        header = self._header()
        if header is None or header == self.columns:
            return
        if header != self._earlier_columns():
            raise UnknownHeader(
                "%s has columns this version of the Kroger app never wrote" % self.path.name)
        columns = self.columns
        self.columns = self._earlier_columns()
        try:
            rows = [{k: v for k, v in read_stored_row(r).items() if isinstance(k, str)}
                    for r in csv.DictReader(io.StringIO(self._decoded(), newline=""))]
            kept = self._kept()
            left = self._not_written(kept) if kept and kept["rows"] else None
        finally:
            self.columns = columns
        if left is not None and kept["from"] is not None:
            if left:
                self._keep(left)
            else:
                self._forget_kept()
        if self.backups_dir is not None:
            backup_file(self.path, self.backups_dir)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=self.columns, extrasaction="ignore",
                           quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in rows:
            w.writerow({c: store_value(row.get(c) or "") for c in self.columns})
        atomic_write_text(self.path, "﻿" + buf.getvalue())

    def _say_unknown(self) -> None:
        if not self._said_unknown:
            self._said_unknown = True
            print("  ! %s has columns this version of the Kroger app never wrote, so it is left "
                  "as it is and new rows are kept beside it, in %s. Put back its header from "
                  "a copy in Backups, or move the file away, and they go in on the next run."
                  % (self.path.name, self.waiting_path.name), flush=True)

    def _try_upgrade(self) -> None:
        try:
            self._upgrade()
        except UnknownHeader:
            self._say_unknown()
        except OSError:
            # Kept beside the file by _ensure_header below, and upgraded on
            # the next run.
            pass

    def _ensure_header(self) -> None:
        super()._ensure_header()
        header = self._header()
        if header is not None and header != self.columns:
            raise HeaderNotUpgraded("%s still has the earlier header" % self.path.name)

    def append_rows(self, rows) -> None:
        self._try_upgrade()
        super().append_rows(rows)

    def read_all(self) -> list:
        self._try_upgrade()
        return super().read_all()

    def rewrite(self, rows, backup: bool = True) -> None:
        # Written over only once upgraded, so a header this app never wrote
        # and the rows kept beside an earlier one are never lost here.
        self._upgrade()
        super().rewrite(rows, backup=backup)
