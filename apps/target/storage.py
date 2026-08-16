"""Filesystem, filename, CSV, and progress storage for the Target receipt downloader.

All writes are local. JSON files are written atomically (temp file + replace)
and CSV/JSON files are backed up with a timestamp before being rewritten.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# Paths / configuration
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = Path(r"C:\Users\YOU\Downloads\Target Receipts")

ORDER_HISTORY_COLUMNS = [
    "Account Holder",
    "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Status",
    "Item Name", "Quantity", "Unit Price", "Line Item Total", "Order Total",
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


def load_config(path: Optional[Path] = None) -> dict:
    path = path or (PROJECT_DIR / "config.json")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("output_dir", str(DEFAULT_OUTPUT_DIR))
    cfg.setdefault("min_pdf_bytes", 3000)
    cfg.setdefault("max_path_length", 240)
    cfg.setdefault("include_invoices", False)
    cfg.setdefault("delay_min_seconds", 2.0)
    cfg.setdefault("delay_max_seconds", 4.0)
    cfg.setdefault("pilot_online", 5)
    cfg.setdefault("pilot_instore", 3)
    cfg.setdefault("profile_dir", str(PROJECT_DIR / "target-browser-profile"))
    cfg.setdefault("owner", "")
    cfg.setdefault("owner_in_filename", False)
    return cfg


_FILENAME_OWNER = ""


def set_filename_owner(name: str) -> None:
    """Name that build_pdf_filename prepends (only when owner_in_filename is on;
    the app passes '' otherwise)."""
    global _FILENAME_OWNER
    _FILENAME_OWNER = (name or "").strip()


def ensure_owner(config: dict, config_path) -> dict:
    """If the account holder's name isn't set, ask once on an interactive
    console and save it back to the config, so every document this account
    downloads is associated with that person. Skipped when non-interactive."""
    if config.get("owner"):
        return config
    if not sys.stdin or not sys.stdin.isatty():
        return config
    try:
        name = input("Whose account is this? Enter the account holder's name: ").strip()
    except (EOFError, KeyboardInterrupt):
        name = ""
    if not name:
        return config
    config["owner"] = name
    try:
        existing = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
        existing["owner"] = name
        Path(config_path).write_text(json.dumps(existing, indent=2), encoding="utf-8")
        print(f"Saved. Documents will be associated with: {name}\n")
    except Exception:
        pass
    return config


class Paths:
    """All well-known output paths, derived from the configured output dir."""

    def __init__(self, output_dir: Path):
        self.root = Path(output_dir)
        self.online = self.root / "Online"
        self.instore = self.root / "In-Store"
        self.invoices = self.root / "Invoices"
        self.manual_review = self.root / "Manual Review"
        self.logs = self.root / "Logs"
        self.diagnostics = self.root / "Diagnostics"
        self.backups = self.root / "Backups"
        self.order_history_csv = self.root / "Target Order History.csv"
        self.receipt_index_csv = self.root / "Target Receipt Index.csv"
        self.progress_json = self.root / "progress.json"
        self.discovery_json = self.root / "discovery.json"
        self.run_summary = self.root / "run-summary.txt"

    def all_dirs(self) -> List[Path]:
        return [self.root, self.online, self.instore, self.invoices,
                self.manual_review, self.logs, self.diagnostics, self.backups]

    def ensure(self) -> None:
        for d in self.all_dirs():
            d.mkdir(parents=True, exist_ok=True)
        # verify writability
        probe = self.root / f".write-probe-{os.getpid()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()

    def folder_for(self, purchase_type: str, document_type: str = "Receipt") -> Path:
        if document_type == "Invoice":
            return self.invoices
        return self.online if purchase_type == "Online" else self.instore


# ---------------------------------------------------------------------------
# Windows-safe filenames
# ---------------------------------------------------------------------------

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_component(name: str, max_len: int = 120) -> str:
    """Make a single filename component safe for Windows.

    Removes forbidden characters, control characters, trailing spaces and
    periods, guards against reserved device names and empty names.
    Apostrophes (e.g. Children's Clothing) are preserved.
    """
    name = _INVALID_CHARS.sub("", name or "")
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(" .")
    if not name:
        name = "Unnamed"
    stem = name.split(".")[0].strip().upper()
    if stem in _RESERVED:
        name = f"{name} File"
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
        if not name:
            name = "Unnamed"
    return name


def build_pdf_filename(purchase_date: str, summary: str,
                       document_type: str = "Receipt",
                       part: Optional[tuple] = None, owner=None) -> str:
    """YYYY-MM-DD Target <Summary> <Receipt|Invoice>[ (i of n)].pdf"""
    date = (purchase_date or "0000-00-00").strip()
    summary = title_case(summary or "Purchase")
    who_name = _FILENAME_OWNER if owner is None else owner
    who = f"{who_name.strip()} " if who_name and who_name.strip() else ""
    base = f"{date} {who}Target {summary} {document_type}"
    if part and part[1] > 1:
        base += f" ({part[0]} of {part[1]})"
    return sanitize_component(base) + ".pdf"


_SMALL_WORDS = {"and", "of", "the", "a", "an", "or", "for", "in", "on", "to"}


def title_case(text: str) -> str:
    """Title-case a summary, keeping small words lowercase (except first/last)
    and preserving apostrophe forms like Children's."""
    words = (text or "").split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if 0 < i < len(words) - 1 and lw in _SMALL_WORDS:
            out.append(lw)
        elif "'" in w:
            # Children's -> Children's (capitalize first letter only)
            out.append(w[0].upper() + w[1:])
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def unique_path(directory: Path, filename: str, max_path_length: int = 240) -> Path:
    """Return a path in *directory* that does not collide with any existing
    file, case-insensitively. Collisions get ' (2)', ' (3)', ... suffixes.
    Never returns a path to an existing file."""
    directory = Path(directory)
    existing = {p.name.lower() for p in directory.iterdir()} if directory.exists() else set()
    stem, ext = os.path.splitext(filename)

    def fits(name: str) -> bool:
        return len(str(directory / name)) <= max_path_length

    candidate = filename
    if not fits(candidate):
        overhead = len(str(directory)) + 1 + len(ext)
        stem = stem[: max(10, max_path_length - overhead)].rstrip(" .")
        candidate = stem + ext

    n = 1
    while candidate.lower() in existing:
        n += 1
        candidate = f"{stem} ({n}){ext}"
        if not fits(candidate):
            trim = len(str(directory / candidate)) - max_path_length
            stem2 = stem[: max(10, len(stem) - trim)].rstrip(" .")
            candidate = f"{stem2} ({n}){ext}"
    return directory / candidate


# ---------------------------------------------------------------------------
# Atomic writes and backups
# ---------------------------------------------------------------------------

def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # Windows: os.replace fails while the target is open in Excel etc.
        # Retry with a message instead of crashing mid-run.
        for attempt in range(30):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 0:
                    print(f"  ! {path.name} is locked (open in Excel?). "
                          f"Close it - retrying for up to 60s...")
                time.sleep(2)
        else:
            raise PermissionError(
                f"{path} stayed locked. Close the program using it and re-run; "
                f"the pending update was not lost (progress is tracked).")
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def atomic_write_json(path: Path, data) -> None:
    atomic_write_text(Path(path), json.dumps(data, indent=2, ensure_ascii=False))


def backup_file(path: Path, backups_dir: Path) -> Optional[Path]:
    """Copy *path* into Backups with a timestamp. No-op if it doesn't exist."""
    path = Path(path)
    if not path.exists():
        return None
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"{path.stem}.{stamp}{path.suffix}.bak"
    n = 1
    while dest.exists():
        n += 1
        dest = backups_dir / f"{path.stem}.{stamp}-{n}{path.suffix}.bak"
    shutil.copy2(path, dest)
    return dest


# ---------------------------------------------------------------------------
# CSV files (UTF-8 with BOM for Excel)
# ---------------------------------------------------------------------------

class CsvFile:
    def __init__(self, path: Path, columns: List[str], backups_dir: Optional[Path] = None):
        self.path = Path(path)
        self.columns = columns
        self.backups_dir = backups_dir

    def _ensure_header(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, fieldnames=self.columns, quoting=csv.QUOTE_MINIMAL).writeheader()

    def append_rows(self, rows: Iterable[dict]) -> None:
        self._ensure_header()
        with open(self.path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.columns, extrasaction="ignore",
                               quoting=csv.QUOTE_MINIMAL)
            for row in rows:
                w.writerow({c: row.get(c, "") for c in self.columns})

    def read_all(self) -> List[dict]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def rewrite(self, rows: List[dict]) -> None:
        """Backup then atomically rewrite the whole file."""
        if self.backups_dir is not None:
            backup_file(self.path, self.backups_dir)
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=self.columns, extrasaction="ignore",
                           quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in self.columns})
        # utf-8-sig: prepend BOM manually since we write text atomically
        atomic_write_text(self.path, "﻿" + buf.getvalue())


# ---------------------------------------------------------------------------
# Progress / discovery stores
# ---------------------------------------------------------------------------

class JsonStore:
    """A dict-of-records JSON file with atomic writes, backups, and
    corrupt-file recovery."""

    def __init__(self, path: Path, backups_dir: Optional[Path] = None):
        self.path = Path(path)
        self.backups_dir = backups_dir
        self.data: Dict[str, dict] = {}
        self._loaded = False

    def load(self) -> Dict[str, dict]:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self.data = raw
            except (json.JSONDecodeError, OSError):
                # Corrupt file: preserve it for inspection, start fresh,
                # try latest backup.
                if self.backups_dir is not None:
                    backup_file(self.path, self.backups_dir)
                recovered = self._recover_from_backup()
                self.data = recovered if recovered is not None else {}
        self._loaded = True
        return self.data

    def _recover_from_backup(self) -> Optional[Dict[str, dict]]:
        if self.backups_dir is None or not Path(self.backups_dir).exists():
            return None
        candidates = sorted(Path(self.backups_dir).glob(f"{self.path.stem}.*.bak"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        for c in candidates:
            try:
                with open(c, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    return raw
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def save(self, backup: bool = False) -> None:
        if backup and self.backups_dir is not None:
            backup_file(self.path, self.backups_dir)
        atomic_write_json(self.path, self.data)

    def get(self, key: str) -> Optional[dict]:
        if not self._loaded:
            self.load()
        return self.data.get(key)

    def update(self, key: str, record: dict, save: bool = True) -> None:
        if not self._loaded:
            self.load()
        existing = self.data.get(key, {})
        existing.update(record)
        existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.data[key] = existing
        if save:
            self.save()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
