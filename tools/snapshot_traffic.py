"""Keep a permanent record of this repo's GitHub traffic.

GitHub throws traffic data away after 14 days. There is no way to ask for last
month, so the only way to have a history is to have been writing it down.

This appends to a CSV, keyed by date, and rewrites any day it already holds.
Rewriting matters because GitHub revises recent days as more data lands, so the
newest row is the least trustworthy and should be overwritten rather than
duplicated.

    python tools/snapshot_traffic.py --out "C:/path/traffic.csv"

Missing a run is cheap. Anything short of a 14 day gap loses nothing, because
the next run backfills every day GitHub still holds.

Needs the gh CLI, signed in as someone with push access, since the traffic
endpoints are not public. It writes no repository data anywhere and reads
nothing but counts.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = "rheeloaded/paperpull"
COLUMNS = ["date", "clones", "clones_unique", "views", "views_unique",
           "stars", "forks", "recorded_at"]


def _gh() -> str:
    found = shutil.which("gh")
    if found:
        return found
    for guess in (r"C:\Program Files\GitHub CLI\gh.exe",
                  r"C:\Program Files (x86)\GitHub CLI\gh.exe",
                  "/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"):
        if Path(guess).exists():
            return guess
    raise SystemExit("gh was not found. Install the GitHub CLI, or put it on PATH.")


def _api(path: str):
    out = subprocess.run([_gh(), "api", path], capture_output=True, text=True)
    if out.returncode != 0:
        err = (out.stderr or "").strip().splitlines()
        raise SystemExit("gh api " + path + " failed: " + (err[-1] if err else "unknown"))
    return json.loads(out.stdout)


def collect(repo: str) -> dict:
    """One row per day, merged from the clone and view series."""
    clones = _api(f"repos/{repo}/traffic/clones")
    views = _api(f"repos/{repo}/traffic/views")
    meta = _api(f"repos/{repo}")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows: dict = {}
    for item in clones.get("clones", []):
        day = item["timestamp"][:10]
        rows.setdefault(day, {"date": day})
        rows[day]["clones"] = item["count"]
        rows[day]["clones_unique"] = item["uniques"]
    for item in views.get("views", []):
        day = item["timestamp"][:10]
        rows.setdefault(day, {"date": day})
        rows[day]["views"] = item["count"]
        rows[day]["views_unique"] = item["uniques"]

    # Stars and forks are a running total, not a per-day figure. They are
    # stamped onto every row this run touches so the shape of the growth is
    # still visible later, but they are NOT a daily count.
    for row in rows.values():
        row.setdefault("clones", 0)
        row.setdefault("clones_unique", 0)
        row.setdefault("views", 0)
        row.setdefault("views_unique", 0)
        row["stars"] = meta.get("stargazers_count", "")
        row["forks"] = meta.get("forks_count", "")
        row["recorded_at"] = stamp
    return rows


def merge(path: Path, fresh: dict) -> tuple:
    existing: dict = {}
    if path.exists():
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("date"):
                    existing[row["date"]] = row
    added = [d for d in fresh if d not in existing]
    updated = [d for d in fresh if d in existing]
    existing.update(fresh)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for day in sorted(existing):
            w.writerow({c: existing[day].get(c, "") for c in COLUMNS})
    os.replace(tmp, path)
    return added, updated, len(existing)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="CSV to append to")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rows = collect(args.repo)
    if not rows:
        print("GitHub returned no traffic data.")
        return 1
    added, updated, total = merge(Path(args.out), rows)
    if not args.quiet:
        print(f"{args.repo}: {len(added)} new day(s), {len(updated)} revised, "
              f"{total} day(s) on record")
        if added:
            print("  new: " + ", ".join(sorted(added)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
