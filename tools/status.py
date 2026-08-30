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

It also reports periods that look missing from the MIDDLE of a history, which
a "are you up to date" check cannot see. See find_gaps for why that matters and
how false alarms are kept out.

PRIVACY: this reads local state files only, never document contents, and
reports no amounts or balances. It does name which providers you hold accounts
with, and the gap report names the account labels the apps recorded, which can
include an account nickname and its last four digits. status.html is written
beside the archives, where the documents themselves already live, and never
into the source repo.
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
NEVER = "never"


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


def find_gaps(records, kind):
    """Periods that look missing from the MIDDLE of a history.

    This is the failure this project keeps hitting. An archive can look
    perfectly healthy by its newest document while quietly missing whole years
    in the middle: one mortgage archive held a single year of a seven year
    history, and a payroll archive silently defaulted to year to date. Both had
    a recent newest document, so no "are you up to date" check would notice.

    The hard part is not finding gaps, it is not inventing them. Real archives
    contain series that are genuinely irregular, insurance ID cards and policy
    renewals among them, where a long gap means nothing was issued rather than
    something was missed. Flagging those would train you to ignore the report.

    So each series has to earn an opinion first:
      * it is a statement archive, not receipts, whose timing is meaningless
      * at least six documents, so there is a rhythm to compare against
      * a median interval of ten days or more
      * at least 65 percent of its intervals close to that median, which is
        what separates a monthly statement from an occasional notice

    Only then is an interval roughly twice the usual one reported, and it is
    reported as possible rather than certain. A month with no activity can
    legitimately produce no statement.
    """
    if kind == "RECEIPT":
        return []
    series = {}
    for rec in records:
        got = rec.get("downloaded_ok") or str(rec.get("state", "")).lower() == "completed"
        if not got:
            continue
        d = _record_date(rec)
        if not d:
            continue
        key = (str(rec.get("account") or ""), str(rec.get("summary") or "") or "documents")
        series.setdefault(key, []).append(d)

    found = []
    for (account, summary), dates in series.items():
        uniq = sorted(set(dates))
        if len(uniq) < 6:
            continue
        gaps = [(b - a).days for a, b in zip(uniq, uniq[1:])]
        med = statistics.median(gaps)
        if med < 10:
            continue
        regular = sum(1 for g in gaps if abs(g - med) <= med * 0.35) / len(gaps)
        if regular < 0.65:
            continue
        for a, b in zip(uniq, uniq[1:]):
            g = (b - a).days
            if g >= med * 1.9 and g - med >= 10:
                found.append({
                    "account": account, "summary": summary,
                    "after": a, "before": b,
                    "missing": max(1, int(round(g / med)) - 1),
                    "every_days": med,
                })
    found.sort(key=lambda f: f["after"])
    return found


def group_gaps(gaps):
    """Collapse gaps that share a window.

    One account missing a month usually means no activity that month. The SAME
    window missing across several accounts at once is a different thing
    entirely: that is what a failed or partial run looks like, and it is worth
    seeing as one finding rather than as five.
    """
    windows = {}
    for g in gaps:
        key = (g["after"], g["before"], g["missing"])
        windows.setdefault(key, []).append(g)
    out = []
    for (after, before, missing), members in sorted(windows.items()):
        labels = [((m["account"] + " ") if m["account"] else "") + m["summary"]
                  for m in members]
        out.append({"after": after, "before": before, "missing": missing,
                    "count": len(members), "labels": labels})
    return out


def scan_install(install: Path):
    # Nobody holds an account with every provider, so this reports the archives
    # that EXIST rather than the providers that could exist. A folder with no
    # progress.json, or one that has never recorded anything, is a provider
    # this person does not use (or a leftover from a closed account) and is
    # left out entirely rather than listed as missing or overdue.
    progress = _read_json(install / "progress.json")
    if not progress:
        return None
    records = [r for r in progress.values() if isinstance(r, dict)]
    if not records:
        return None
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

    if done == 0:
        # Set up and discovered documents, but never actually downloaded any.
        # That is worth saying out loud rather than calling it unknown, because
        # it is the one state a single run would fix.
        status = NEVER
    elif kind == "RECEIPT":
        status = ONGOING
    elif newest is None or cadence is None:
        status = UNKNOWN
    elif age <= cadence * 1.3:
        status = CURRENT
    elif age <= cadence * 2:
        status = DUE
    else:
        status = OVERDUE

    gaps = find_gaps(records, kind)

    run_at, run_mode = _last_run(install)
    return {
        "folder": install.name, "provider": provider, "kind": kind,
        "documents": done, "newest": newest, "age_days": age,
        "cadence_days": cadence, "status": status,
        "last_download": last_download, "last_run": run_at, "last_run_mode": run_mode,
        "gaps": gaps, "missing": sum(g["missing"] for g in gaps),
    }


def scan_all(root: Path):
    rows = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        row = scan_install(child)
        if row:
            rows.append(row)
    order = {OVERDUE: 0, NEVER: 1, DUE: 2, UNKNOWN: 3, CURRENT: 4, ONGOING: 5}
    rows.sort(key=lambda r: (order.get(r["status"], 9), -(r["age_days"] or 0)))
    return rows


# -- rendering ---------------------------------------------------------------

LABEL = {CURRENT: "current", DUE: "due", OVERDUE: "OVERDUE",
         UNKNOWN: "unknown", ONGOING: "ongoing", NEVER: "never downloaded"}


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
    shown = [r for r in rows if not quiet or r["status"] in (DUE, OVERDUE, NEVER)]
    if not shown:
        print("Nothing needs attention. Every provider is current." if quiet
              else "No installs found.")
        return
    print()
    print("%-30s %5s %5s  %-12s %6s  %-9s %s" % (
        "PROVIDER", "DOCS", "GAPS", "NEWEST", "AGE", "ISSUES", "STATUS"))
    print("-" * 88)
    for r in shown:
        age = ("%d d" % r["age_days"]) if r["age_days"] is not None else "-"
        mark = "!!" if r["status"] == OVERDUE else (
            "*" if r["status"] in (DUE, NEVER) else "  ")
        print("%-30s %5d %5s  %-12s %6s  %-9s %s %s" % (
            r["folder"][:30], r["documents"],
            (str(r["missing"]) if r["missing"] else "-"),
            r["newest"].isoformat() if r["newest"] else "-",
            age, _fmt_cadence(r["cadence_days"]), mark, LABEL[r["status"]]))
    print()
    due = [r for r in rows if r["status"] in (DUE, OVERDUE, NEVER)]
    if due:
        print("Probably worth running: " + ", ".join(r["folder"] for r in due))
    else:
        print("Everything with a predictable schedule looks current.")
    unknown = [r for r in rows if r["status"] == UNKNOWN]
    if unknown:
        print("Not enough history to judge: " + ", ".join(r["folder"] for r in unknown))
    holed = [r for r in rows if r["missing"]]
    if holed:
        print()
        print("Possible gaps. A run that looks current can still be missing")
        print("periods in the middle, so these are worth a look.")
        for r in holed:
            print("  %s" % r["folder"])
            groups = group_gaps(r["gaps"])
            for g in groups[:8]:
                if g["count"] > 1:
                    who = "%d series, including %s" % (g["count"], g["labels"][0][:34])
                else:
                    who = g["labels"][0][:52]
                print("     %s to %s   %d missing   %s" % (
                    g["after"], g["before"], g["missing"], who))
            if len(groups) > 8:
                print("     ... and %d more windows" % (len(groups) - 8))


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
  .s-unknown,.s-ongoing{color:var(--mut)} .s-never{color:var(--due)}
  .muted { color:var(--mut); }
  footer { color:var(--mut); font-size:.8rem; margin-top:1.5rem; }
</style>
<main>
"""


def write_html(rows, out: Path):
    from html import escape
    due = [r for r in rows if r["status"] in (DUE, OVERDUE, NEVER)]
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
    holed = [r for r in rows if r["missing"]]
    if holed:
        parts.append("<h2>Possible gaps</h2>")
        parts.append('<p class="sub">An archive can look current and still be '
                     "missing periods in the middle. The same window missing "
                     "across several series at once is usually a run that "
                     "failed part way rather than a quiet month.</p>")
        parts.append("<table><thead><tr><th>Provider</th><th>Window</th>"
                     "<th class='num'>Missing</th><th>Series</th></tr>"
                     "</thead><tbody>")
        for r in holed:
            for g in group_gaps(r["gaps"])[:12]:
                who = ("%d series, including %s" % (g["count"], g["labels"][0])
                       if g["count"] > 1 else g["labels"][0])
                parts.append(
                    "<tr><td>%s</td><td>%s to %s</td><td class='num'>%d</td>"
                    "<td class='muted'>%s</td></tr>" % (
                        escape(r["folder"]), g["after"], g["before"],
                        g["missing"], escape(who)))
        parts.append("</tbody></table>")
    parts.append("<footer>Receipt archives are shown as ongoing rather than due, "
                 "because purchases arrive irregularly, and a series has to keep a "
                 "steady rhythm before a gap in it is reported at all.<br><br>"
                 "<strong>What is in this file.</strong> Which providers you hold "
                 "accounts with, the account labels those apps recorded (which can "
                 "include an account nickname and its last four digits), document "
                 "dates and counts. No amounts, no balances and no document "
                 "contents. It is written beside your archives, where the documents "
                 "themselves already live, and is never copied into the source "
                 "repository.</footer></main>")
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
        print("No PaperPull archives found under %s" % root)
        print("This reports the archives you actually have, so it looks for")
        print("install folders holding a progress.json. Point it at the folder")
        print("that contains them with --root.")
        return 2
    print_table(rows, quiet=args.quiet)
    if args.html:
        out = root / "status.html"
        write_html(rows, out)
        print("\nWrote %s" % out)
    return 1 if any(r["status"] == OVERDUE for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
