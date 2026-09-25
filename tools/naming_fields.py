"""Which naming fields each app can fill, from its code and from real archives.

Run it from the repository root.

    python tools/naming_fields.py
    python tools/naming_fields.py --installs PATH     also measure real archives
    python tools/naming_fields.py --markdown          the table for the docs

A file naming template can only use what an app knows when it names a
file. Two things say what that is. The record each app keeps, read from
its source, says which fields exist at all. The records in real archives,
read from progress.json, say how often each one is actually filled,
because a field that exists and is always empty is a trap for anybody
who builds a pattern around it.

Reads only. From an archive it takes field names and counts and nothing
else, so no value from anybody's records is printed or written.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The naming fields a template could offer, and the record keys that fill
# each. The first key with a value wins. Written by hand because the two
# record shapes, receipts and documents, name the same idea differently.
FIELDS = [
    ("date", ("date", "purchase_date")),
    ("kind", ("document_type", "category")),
    ("summary", ("summary",)),
    ("title", ("title",)),
    ("number", ("order_number", "document_id")),
    ("account", ("account",)),
    ("period", ("period",)),
    ("total", ("total",)),
    ("store", ("store_info",)),
    ("purchase type", ("purchase_type",)),
    ("fulfillment", ("fulfillment",)),
]


def entry_of(app: Path):
    found = list(app.glob("*_docs.py")) + list(app.glob("*_receipts.py"))
    return found[0] if found else None


def record_keys(entry: Path) -> set:
    """The attributes an app's record carries.

    A documents app defines class Document in its entry module. A receipts
    app uses paperpull_core.models.Purchase, read from the core."""
    tree = ast.parse(entry.read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Document":
            keys = set()
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self" and isinstance(sub.ctx, ast.Store)):
                    keys.add(sub.attr)
            return keys
    models = REPO / "core" / "paperpull_core" / "models.py"
    tree = ast.parse(models.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Purchase":
            return {s.target.id for s in node.body
                    if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
    return set()


def filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def measure(progress: Path) -> tuple:
    """(records, {naming field: records that fill it}). Counts only."""
    try:
        data = json.loads(progress.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return 0, {}
    records = [r for r in (data.values() if isinstance(data, dict) else data)
               if isinstance(r, dict)]
    counts = {}
    for name, keys in FIELDS:
        counts[name] = sum(1 for r in records if any(filled(r.get(k)) for k in keys))
    return len(records), counts


def app_of_install(install: Path):
    """Which app an install runs, from the entry module it holds."""
    for f in install.glob("*.py"):
        stem = f.stem
        if stem.endswith("_docs") or stem.endswith("_receipts"):
            return stem.rsplit("_", 1)[0]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--installs", help="a folder of installs to measure")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args(argv)

    apps = sorted(p for p in (REPO / "apps").iterdir() if p.is_dir() and entry_of(p))
    code = {}
    for app in apps:
        keys = record_keys(entry_of(app))
        code[app.name] = {name for name, ks in FIELDS if keys & set(ks)}

    real = {}
    if args.installs:
        for install in sorted(Path(args.installs).iterdir()):
            if not install.is_dir():
                continue
            app = app_of_install(install)
            progress = install / "progress.json"
            if not app or not progress.exists():
                continue
            n, counts = measure(progress)
            if n:
                total, agg = real.get(app, (0, {}))
                real[app] = (total + n, {k: agg.get(k, 0) + v for k, v in counts.items()})

    names = [name for name, _ in FIELDS]
    rows = []
    for app in [a.name for a in apps]:
        cells = []
        for name in names:
            if name not in code[app]:
                cells.append("")
            elif app in real:
                n, counts = real[app]
                cells.append("%d%%" % round(100 * counts.get(name, 0) / n))
            else:
                cells.append("yes")
        records = real[app][0] if app in real else ""
        rows.append([app, str(records)] + cells)

    header = ["app", "records"] + names
    if args.markdown:
        print("| " + " | ".join(header) + " |")
        print("|" + "---|" * len(header))
        for r in rows:
            print("| " + " | ".join(r) + " |")
    else:
        widths = [max(len(x) for x in col) for col in zip(header, *rows)]
        for line in [header] + rows:
            print("  ".join(c.ljust(w) for c, w in zip(line, widths)).rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
