"""Show, across every installed PaperPull app, how current your archive is.

The question this answers is not "when did I last run it" but "is there
probably something new waiting". Those are different: a run that only verified
existing files, or that found nothing new, still updates a run timestamp while
telling you nothing about whether a new statement has been issued.

So the primary signal is the date of the NEWEST DOCUMENT you actually hold,
compared against how often that provider issues them. The cadence is measured
from your own history (the median gap between consecutive statements), so
nothing has to be configured per provider, and a provider that switches from
monthly to quarterly corrects itself.

Receipt apps (Amazon, Target, Walmart, Gap) are reported without a due date.
Purchases arrive irregularly, so "you are 40 days overdue" would be noise
rather than information.

Usage:
    python status.py                 table for every install under this folder
    python status.py --root PATH     look somewhere else
    python status.py --html          also write status.html next to the installs
    python status.py --quiet         only show what needs attention

PRIVACY: this reads your local install folders and reports which providers you
hold accounts with, plus dates. It writes status.html into the SAME folder as
the installs, never into the source repo. It reads no document contents and
reports no amounts, account numbers or names.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
KIND_RE = re.compile(r"kind\s*=\s*([A-Z_]+)")
PROVIDER_RE = re.compile(r"provider\s*=\s*[\"']([^\"']+)[\"']")

CURRENT, DUE, OVERDUE, UNKNOWN, ONGOING = "current", "due", "overdue", "unknown", "ongoing"


def _iso(value):
    m = DATE_RE.match(str(value or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _kind_and_provider(install: Path, records=None):
    """DOCUMENT or RECEIPT, plus the provider string, from the app's own spec.

    A second-account folder (driven by --config from the main install) holds
    only data and no code, so there is no spec to read. Those fall back to the
    records themselves: a receipt app dates its records with purchase_date, a
    statement app with date. Guessing from the folder name would be fragile,
    and getting this wrong would report a receipt archive as overdue.
    """
    src = ""
    try:
        src = (install / "storage.py").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    k = KIND_RE.search(src)
    p = PROVIDER_RE.search(src)
    if k:
        kind = k.group(1)
    else:
        purchases = sum(1 for r in (records or []) if r.get("purchase_date"))
        dated = sum(1 for r in (records or []) if r.get("date"))
        kind = "RECEIPT" if purchases > dated else "DOCUMENT"
    return kind, (p.group(1) if p else install.name)


def _record_date(rec):
    """Statement apps store `date`, receipt apps store `purchase_date`."""
    return _iso(rec.get("date")) or _iso(rec.get("purchase_date"))


def _last_run(install: Path):
    """When the tool last ran at all, from its run summary. Secondary signal:
    a verify run counts here but tells you nothing about new documents."""
    try:
        txt = (install / "run-summary.txt").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, ""
    end = re.search(r"Run end:\s*(\S+)", txt)
    mode = re.search(r"Mode:\s*(\S+)", txt)
    stamp = None
    if end:
        try:
            stamp = datetime.fromisoformat(end.group(1))
        except ValueError:
            stamp = None
    return stamp, (mode.group(1) if mode else "")


def _gap_median(dates):
    uniq = sorted(set(dates))
    if len(uniq) < 3:
        return None
    gaps = [(b - a).days for a, b in zip(uniq, uniq[1:]) if 0 < (b - a).days <= 400]
    if len(gaps) < 2:
        return None
    return statistics.median(gaps[-24:])


def _cadence_days(dates_by_account):
    """How often this provider issues a document, from your own history.

    Measured PER ACCOUNT and then combined, which matters more than it sounds.
    A bank install can cover many accounts at once, each billed monthly.
    Pooling their dates makes the gaps look weekly, and the archive then
    reports itself overdue a week after a statement arrives. Per account it
    reads monthly, which is the truth.

    The median gap is used rather than the mean, so one unusual gap (a late
    statement, or a year that was never downloaded) cannot distort it.
    """
    per = [c for c in (_gap_median(v) for v in dates_by_account.values()) if c]
    if not per:
        # single unnamed account, or too little history in every group
        pooled = [d for v in dates_by_account.values() for d in v]
        return _gap_median(pooled)
    return statistics.median(per)


def scan_install(install: Path):
    progress = _read_json(install / "progress.json")
    if not progress:
        return None
    records = [r for r in progress.values() if isinstance(r, dict)]
    kind, provider = _kind_and_provider(install, records)

    done, doc_dates, last_download = 0, [], None
    by_account = {}
    for rec in records:
        got = rec.get("downloaded_ok") or str(rec.get("state", "")).lower() == "completed"
        if not got:
            continue
        done += 1
        d = _record_date(rec)
        if d:
            doc_dates.append(d)
            by_account.setdefault(str(rec.get("account") or ""), []).append(d)
        try:
            stamp = datetime.fromisoformat(str(rec.get("updated_at") or ""))
            if last_download is None or stamp > last_download:
                last_download = stamp
        except ValueError:
            pass

    newest = max(doc_dates) if doc_dates else None
    cadence = _cadence_days(by_account) if kind == "DOCUMENT" else None
    age = (date.today() - newest).days if newest else None

    if kind == "RECEIPT":
        status = ONGOING
    elif newest is None or cadence is None:
        status = UNKNOWN
    elif age <= cadence * 1.3:
        status = CURRENT
    elif age <= cadence * 2:
        status = DUE
    else:
        status = OVERDUE

    run_at, run_mode = _last_run(install)
    return {
        "folder": install.name, "provider": provider, "kind": kind,
        "documents": done, "newest": newest, "age_days": age,
        "cadence_days": cadence, "status": status,
        "last_download": last_download, "last_run": run_at, "last_run_mode": run_mode,
    }


def scan_all(root: Path):
    rows = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        row = scan_install(child)
        if row:
            rows.append(row)
    order = {OVERDUE: 0, DUE: 1, UNKNOWN: 2, CURRENT: 3, ONGOING: 4}
    rows.sort(key=lambda r: (order.get(r["status"], 9), -(r["age_days"] or 0)))
    return rows


# -- rendering ---------------------------------------------------------------

LABEL = {CURRENT: "current", DUE: "due", OVERDUE: "OVERDUE",
         UNKNOWN: "unknown", ONGOING: "ongoing"}


def _fmt_cadence(days):
    if not days:
        return "-"
    if days <= 10:
        return "weekly"
    if days <= 20:
        return "2x month"
    if days <= 45:
        return "monthly"
    if days <= 100:
        return "quarterly"
    if days <= 200:
        return "2x year"
    return "yearly"


def print_table(rows, quiet=False):
    shown = [r for r in rows if not quiet or r["status"] in (DUE, OVERDUE)]
    if not shown:
        print("Nothing needs attention. Every provider is current." if quiet
              else "No installs found.")
        return
    print()
    print("%-32s %5s  %-12s %6s  %-10s %s" % (
        "PROVIDER", "DOCS", "NEWEST", "AGE", "ISSUES", "STATUS"))
    print("-" * 84)
    for r in shown:
        age = ("%d d" % r["age_days"]) if r["age_days"] is not None else "-"
        mark = "!!" if r["status"] == OVERDUE else ("*" if r["status"] == DUE else "  ")
        print("%-32s %5d  %-12s %6s  %-10s %s %s" % (
            r["folder"][:32], r["documents"],
            r["newest"].isoformat() if r["newest"] else "-",
            age, _fmt_cadence(r["cadence_days"]), mark, LABEL[r["status"]]))
    print()
    due = [r for r in rows if r["status"] in (DUE, OVERDUE)]
    if due:
        print("Probably worth running: " + ", ".join(r["folder"] for r in due))
    else:
        print("Everything with a predictable schedule looks current.")
    unknown = [r for r in rows if r["status"] == UNKNOWN]
    if unknown:
        print("Not enough history to judge: " + ", ".join(r["folder"] for r in unknown))


HTML_HEAD = """<!doctype html>
<meta charset="utf-8">
<title>PaperPull status</title>
<style>
  :root { color-scheme: light dark;
          --bg:#fbfbfa; --fg:#1a1a19; --mut:#6b6b68; --line:#e3e3e0; --card:#fff;
          --ok:#2f7d4f; --due:#a06a00; --over:#b3261e; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#191918; --fg:#eeeeec; --mut:#9a9a96; --line:#333330; --card:#232321;
            --ok:#6fcf97; --due:#e0b060; --over:#f2837a; } }
  body { margin:0; padding:2.5rem 1.5rem; background:var(--bg); color:var(--fg);
         font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif; }
  main { max-width:60rem; margin:0 auto; }
  h1 { font-size:1.5rem; margin:0 0 .25rem; letter-spacing:-.01em; }
  .sub { color:var(--mut); margin:0 0 1.75rem; font-size:.9rem; }
  .banner { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--ok);
            border-radius:8px; padding:.85rem 1rem; margin-bottom:1.5rem; }
  .banner.act { border-left-color:var(--over); }
  table { width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); border-radius:8px; overflow:hidden; }
  th { text-align:left; font-size:.72rem; letter-spacing:.06em; text-transform:uppercase;
       color:var(--mut); font-weight:600; padding:.7rem .9rem; border-bottom:1px solid var(--line); }
  td { padding:.7rem .9rem; border-bottom:1px solid var(--line); }
  tr:last-child td { border-bottom:none; }
  .num { text-align:right; font-variant-numeric:tabular-nums; }
  .pill { display:inline-block; padding:.12rem .5rem; border-radius:999px;
          font-size:.75rem; font-weight:600; }
  .s-current{color:var(--ok)} .s-due{color:var(--due)} .s-overdue{color:var(--over)}
  .s-unknown,.s-ongoing{color:var(--mut)}
  .muted { color:var(--mut); }
  footer { color:var(--mut); font-size:.8rem; margin-top:1.5rem; }
</style>
<main>
"""


def write_html(rows, out: Path):
    from html import escape
    due = [r for r in rows if r["status"] in (DUE, OVERDUE)]
    parts = [HTML_HEAD]
    parts.append("<h1>PaperPull status</h1>")
    parts.append('<p class="sub">Generated %s. Shows how current each archive is, '
                 "based on the newest document you hold and how often that provider "
                 "issues them.</p>" % date.today().isoformat())
    if due:
        parts.append('<div class="banner act"><strong>%d worth running:</strong> %s</div>'
                     % (len(due), escape(", ".join(r["folder"] for r in due))))
    else:
        parts.append('<div class="banner">Everything with a predictable schedule '
                     "looks current.</div>")
    parts.append("<table><thead><tr><th>Provider</th><th class='num'>Docs</th>"
                 "<th>Newest document</th><th class='num'>Age</th><th>Issues</th>"
                 "<th>Status</th><th>Last downloaded</th></tr></thead><tbody>")
    for r in rows:
        age = ("%d days" % r["age_days"]) if r["age_days"] is not None else "-"
        last = r["last_download"].strftime("%Y-%m-%d") if r["last_download"] else "-"
        parts.append(
            "<tr><td>%s</td><td class='num'>%d</td><td>%s</td><td class='num'>%s</td>"
            "<td class='muted'>%s</td><td class='pill s-%s'>%s</td>"
            "<td class='muted'>%s</td></tr>" % (
                escape(r["folder"]), r["documents"],
                r["newest"].isoformat() if r["newest"] else "-", age,
                _fmt_cadence(r["cadence_days"]), r["status"], LABEL[r["status"]],
                last))
    parts.append("</tbody></table>")
    parts.append("<footer>Receipt archives are shown as ongoing rather than due, "
                 "because purchases arrive irregularly. A provider with fewer than "
                 "three documents has too little history to judge.<br>"
                 "This file lists which providers you hold accounts with. It stays "
                 "in this folder and is never copied into the source repository."
                 "</footer></main>")
    out.write_text("\n".join(parts), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="How current is each PaperPull archive?")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent),
                    help="folder containing the install folders (default: this one)")
    ap.add_argument("--html", action="store_true", help="also write status.html")
    ap.add_argument("--quiet", action="store_true", help="only show what needs attention")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print("Not a folder: %s" % root)
        return 2
    rows = scan_all(root)
    if not rows:
        print("No PaperPull installs found under %s" % root)
        print("Point it at the folder that holds them with --root.")
        return 2
    print_table(rows, quiet=args.quiet)
    if args.html:
        out = root / "status.html"
        write_html(rows, out)
        print("\nWrote %s" % out)
    return 1 if any(r["status"] == OVERDUE for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
