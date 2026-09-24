"""How many rounds each tester-built provider has taken, from the record.

Run it from the repository root.

    python tools/rounds.py
    python tools/rounds.py --json
    python tools/rounds.py --as-of 2026-09-22

A round is one trip around the loop that adds or repairs a provider. The
maintainer writes code he cannot run, ships it, a volunteer runs it and
writes back. Everything the project is doing to shorten that loop needs a
number to be measured against, and until this existed the number was
whatever somebody remembered.

The record is incomplete in both places it lives, so this counts three
ways and prints all three rather than trusting one.

  shipped   Maintainer comments on the provider's issue that link a
            release newer than any the issue had linked before, and which
            git says changed that app. A link to an older release, or to
            one that carried only other providers' fixes, is a pointer and
            not a round. This misses rounds a tester reported somewhere
            other than the issue.
  grouped   Commits that changed the provider's site layer, grouped by the
            tester comments between them, so a night of five commits
            answering one report is one round. This misses rounds whose
            fix landed outside the site layer.
  named     The highest "round N" a commit subject gave the provider. This
            is what the maintainer called it at the time, which is what
            the anecdotes were built from.

Where the three disagree, that is a finding about the record rather than a
bug to hide, and the disagreement is printed.

A first working Pilot is the first tester comment saying a Pilot saved at
least one document, or saying success. Quoted text and log blocks are
ignored, because a pasted log says "downloaded" in lines that failed.

Needs git and an authenticated gh. Reads only. Nothing is cached.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Every provider that has been through the tester loop, the names commit
# subjects use for it, and its issues. Written by hand because issue
# titles are free text ("Kroeger", "Golden1"). An issue that looks like a
# provider issue but is missing here is reported as unmapped, so this list
# cannot go stale without saying so.
#
# kind is "new" for a provider built blind, and "repair" for a working
# provider that broke, whose clock starts at the issue and not at the
# app's first commit.
PROVIDERS = [
    ("att", ("AT&T",), (26,), "new"),
    ("pge", ("PG&E",), (33,), "repair"),
    ("smud", ("SMUD",), (34,), "new"),
    ("golden1", ("Golden 1", "Golden1"), (35,), "new"),
    ("etrade", ("E*TRADE",), (36,), "new"),
    ("statefarm", ("State Farm",), (37,), "new"),
    ("newrez", ("Newrez",), (38,), "new"),
    ("kroger", ("Kroger",), (41,), "new"),
    ("meijer", ("Meijer",), (42,), "new"),
    ("github", ("GitHub",), (43,), "new"),
    ("ebay", ("eBay",), (44,), "new"),
    ("amfam", ("American Family", "AmFam"), (45,), "new"),
    ("adp", ("ADP",), (46,), "new"),
    ("costco", ("Costco",), (47,), "new"),
    ("wellsfargo", ("Wells Fargo",), (27,), "new"),
    ("sba", ("SBA",), (28,), "new"),
    ("verizonmobile", ("Verizon Mobile",), (31,), "new"),
    ("target", ("Target",), (48,), "repair"),
]

# Issues whose title marks them as about a provider, for the unmapped check.
PROVIDER_TITLE = re.compile(r"^\[(?:provider request|broken)\]", re.I)
# Issues a provider row deliberately does not claim, with the reason.
IGNORED_ISSUES = {
    14: "the original PG&E request, closed with no comments when it shipped",
    30: "Navy Federal, diagnosed and verified by the contributor who "
        "reported it, so no blind round was involved",
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_NUM = r"(\d+|" + "|".join(NUMBER_WORDS) + r")"
_ORDINAL = r"(" + "|".join(w for w in NUMBER_WORDS
                           if w.endswith(("st", "nd", "rd", "th"))) + r")"
# "round three" and "second round". The word must be singular, since
# "Seven rounds from the overnight surveys" and "the rounds four testers'
# files asked for" name no round at all. The second form takes ordinals
# only, because "Golden 1 round three" is not round one.
ROUND_AFTER = re.compile(r"\bround\s+" + _NUM + r"\b", re.I)
ROUND_BEFORE = re.compile(r"\b" + _ORDINAL + r"\s+round\b", re.I)

TAG = re.compile(r"releases/tag/v(\d+(?:\.\d+)+)")

WORKING = re.compile(
    r"\bsuccess\b"
    r"|\bpilot\s+(?:downloaded|pulled|grabbed|got|saved)\s+"
    r"(?!0\b|no\b|nothing\b|none\b|zero\b)",
    re.I)
FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)


# -- parsing, kept pure so the tests can feed it fixtures --------------------

def _num(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word.lower()]


def named_rounds(subject: str, names_by_app: dict[str, tuple[str, ...]]
                 ) -> dict[str, int]:
    """The round number a commit subject gives each provider it names.

    A subject can name several ("PG&E round three and E*TRADE round
    four", "SMUD and State Farm round two"), so each round phrase is
    credited to the providers named between it and the phrase before.
    """
    hits = sorted([(m.start(), m.end(), _num(m.group(1)))
                   for m in ROUND_AFTER.finditer(subject)]
                  + [(m.start(), m.end(), _num(m.group(1)))
                     for m in ROUND_BEFORE.finditer(subject)])
    found: dict[str, int] = {}
    prev_end = 0
    for start, end, n in hits:
        segment = subject[prev_end:start].rstrip(" ,:'s")
        # The clause nearest the phrase is the one it belongs to, so
        # "Add Meijer, ..., Golden 1 round three" credits only Golden 1.
        # When that clause names nobody ("eBay, and why round two") the
        # whole segment is used.
        tail = segment.rsplit(",", 1)[-1]
        owners = _names_in(tail, names_by_app) or _names_in(segment,
                                                            names_by_app)
        for app in owners:
            found[app] = max(found.get(app, 0), n)
        prev_end = end
    return found


def _names_in(text: str, names_by_app: dict[str, tuple[str, ...]]
              ) -> list[str]:
    out = []
    for app, names in names_by_app.items():
        for name in names:
            if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text):
                out.append(app)
                break
    return out


def _version(tag: str) -> tuple[int, ...]:
    return tuple(int(p) for p in tag.split("."))


def says_working(body: str) -> bool:
    """True when a tester's own words say a Pilot saved something."""
    text = FENCE.sub(" ", body or "")
    text = "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith(">"))
    return bool(WORKING.search(text))


@dataclass
class Event:
    at: datetime
    kind: str            # "ship" or "report"
    tag: str = ""
    working: bool = False


def issue_events(issue: dict, owner: str) -> list[Event]:
    """Ships and tester reports on one issue, oldest first.

    The issue body counts as a comment by its author, because a
    maintainer-opened issue often announces the first build in it.
    """
    posts = [{"author": issue.get("author") or {},
              "createdAt": issue["createdAt"],
              "body": issue.get("body") or ""}]
    posts += issue.get("comments") or []
    posts.sort(key=lambda p: p["createdAt"])
    events: list[Event] = []
    newest: tuple[int, ...] = ()
    for p in posts:
        at = _when(p["createdAt"])
        login = (p.get("author") or {}).get("login", "")
        body = p.get("body") or ""
        if login == owner:
            tags = sorted({t for t in TAG.findall(body)}, key=_version)
            if tags and _version(tags[-1]) > newest:
                newest = _version(tags[-1])
                events.append(Event(at, "ship", tag=tags[-1]))
        elif login:
            events.append(Event(at, "report", working=says_working(body)))
    return events


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


@dataclass
class Commit:
    at: datetime
    subject: str
    files: list[str] = field(default_factory=list)


def grouped_rounds(site_commits: list[datetime],
                   reports: list[datetime]) -> int:
    """Site-layer commits, counted once per gap between tester reports.

    Five commits in one night answering one report are one round. A
    commit after the last report still counts, since it is a round the
    tester has not answered yet.
    """
    if not site_commits:
        return 0
    edges = sorted(reports)
    buckets = set()
    for at in site_commits:
        buckets.add(sum(1 for r in edges if r <= at))
    return len(buckets)


@dataclass
class Row:
    app: str
    kind: str
    issues: list[int]
    shipped: int = 0
    shipped_to_working: int | None = None
    grouped: int = 0
    grouped_to_working: int | None = None
    named: int = 0
    named_to_working: int | None = None
    site_commits: int = 0
    reports: int = 0
    first_working: str = ""
    days_to_working: float | None = None
    status: str = ""
    # Who the next move belongs to, "tester" after a ship and
    # "maintainer" after a report, and for how long it has been theirs.
    owed: str = ""
    waiting_days: float | None = None
    disagreement: str = ""


def analyze(app: str, kind: str, issue_numbers: tuple[int, ...],
            issues: dict[int, dict], commits: list[Commit], owner: str,
            names_by_app: dict[str, tuple[str, ...]],
            now: datetime, changed=None) -> Row:
    """One provider's row.

    changed(app, older_tag, newer_tag) says whether a release carried any
    change to the app. A maintainer comment linking a release that did
    not touch the provider is a pointer to where the other fixes are, not
    a round, and counting it made AT&T look like nine rounds when it took
    eight.
    """
    row = Row(app, kind, list(issue_numbers))
    events: list[Event] = []
    for n in issue_numbers:
        if n in issues:
            events += issue_events(issues[n], owner)
    # now doubles as the as-of date, so the record can be read as it
    # stood on any day and a before and after compared honestly.
    events = sorted((e for e in events if e.at <= now), key=lambda e: e.at)
    commits = [c for c in commits if c.at <= now]
    if changed:
        kept, prev = [], None
        for e in events:
            if e.kind == "ship":
                if prev is not None and not changed(app, prev, e.tag):
                    continue
                prev = e.tag
            kept.append(e)
        events = kept
    ships = [e for e in events if e.kind == "ship"]
    reports = [e for e in events if e.kind == "report"]
    row.shipped = len(ships)
    row.reports = len(reports)

    site = f"apps/{app}/{app}_site.py"
    touched = [c for c in commits
               if any(f.startswith(f"apps/{app}/") for f in c.files)]
    site_times = [c.at for c in commits if site in c.files]
    row.site_commits = len(site_times)
    report_times = [e.at for e in reports]
    row.grouped = grouped_rounds(site_times, report_times)
    named = [(c.at, n) for c in commits
             if (n := named_rounds(c.subject, names_by_app).get(app))]
    row.named = max((n for _, n in named), default=0)

    working = next((e for e in reports if e.working), None)
    if working:
        row.first_working = working.at.date().isoformat()
        row.shipped_to_working = sum(1 for s in ships if s.at <= working.at)
        row.grouped_to_working = grouped_rounds(
            [t for t in site_times if t <= working.at],
            [t for t in report_times if t < working.at])
        row.named_to_working = max(
            (n for at, n in named if at <= working.at), default=0)
        if kind == "repair":
            start = min((_when(issues[n]["createdAt"])
                         for n in issue_numbers if n in issues),
                        default=None)
        else:
            start = min((c.at for c in touched), default=None)
        if start:
            row.days_to_working = round(
                (working.at - start).total_seconds() / 86400, 1)
        row.status = "working"
    elif not ships:
        row.status = "not shipped"
    elif not any(r.at > ships[0].at for r in reports):
        row.status = "untested"
    else:
        row.status = "in progress"
    if events and row.status != "working":
        last = events[-1]
        row.owed = "tester" if last.kind == "ship" else "maintainer"
        # Untested counts from the first ship, since every later ship on
        # an unanswered issue is the maintainer talking to himself.
        since = ships[0].at if row.status == "untested" else last.at
        row.waiting_days = round((now - since).total_seconds() / 86400, 1)

    counts = {"shipped": row.shipped, "grouped": row.grouped}
    if row.named:
        counts["named"] = row.named
    if len(set(counts.values())) > 1:
        row.disagreement = ", ".join(f"{k} {v}" for k, v in counts.items())
    return row


def unmapped_issues(issues: dict[int, dict]) -> list[tuple[int, str]]:
    claimed = {n for _, _, ns, _ in PROVIDERS for n in ns}
    return [(n, i["title"]) for n, i in sorted(issues.items())
            if PROVIDER_TITLE.match(i["title"])
            and n not in claimed and n not in IGNORED_ISSUES]


def summary(rows: list[Row]) -> dict:
    """The distribution, so a median and a worst case exist."""
    def stats(values):
        values = [v for v in values if v is not None]
        if not values:
            return None
        return {"n": len(values), "median": statistics.median(values),
                "worst": max(values)}
    working = [r for r in rows if r.status == "working"]
    open_ = [r for r in rows if r.status == "in progress"]
    untested = [r for r in rows if r.status == "untested"]
    return {
        "shipped_to_working": stats([r.shipped_to_working for r in working]),
        "grouped_to_working": stats([r.grouped_to_working for r in working]),
        "days_to_working": stats([r.days_to_working for r in working]),
        "shipped_so_far_unfinished": stats([r.shipped for r in open_]),
        "untested": {"n": len(untested),
                     "apps": [r.app for r in untested],
                     "waiting_days": stats([r.waiting_days
                                            for r in untested])},
    }


# -- the record ---------------------------------------------------------------

def _run(args: list[str]) -> str:
    return subprocess.run(args, cwd=REPO, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def load_commits() -> list[Commit]:
    out = _run(["git", "log", "--no-merges", "--name-only",
                "--format=%x1e%aI%x1f%s"])
    commits = []
    for chunk in out.split("\x1e")[1:]:
        head, _, rest = chunk.partition("\n")
        at, _, subject = head.partition("\x1f")
        files = [f.strip() for f in rest.splitlines() if f.strip()]
        commits.append(Commit(_when(at), subject, files))
    return commits


def release_changed(app: str, older: str, newer: str) -> bool:
    """Whether release newer changed anything of app's since older.

    Tests are left out because a release that only added a test did not
    give the tester anything new to run. A tag missing from this clone
    counts as changed, since dropping a round nobody can check would
    flatter the number.
    """
    try:
        out = _run(["git", "rev-list", "--count", f"v{older}..v{newer}",
                    "--", f"apps/{app}", f":(exclude)apps/{app}/tests"])
    except subprocess.CalledProcessError:
        return True
    return int(out.strip() or 0) > 0


def load_issues() -> tuple[dict[int, dict], str]:
    owner = _run(["gh", "repo", "view", "--json", "owner",
                  "--jq", ".owner.login"]).strip()
    raw = _run(["gh", "issue", "list", "--state", "all", "--limit", "1000",
                "--json", "number,title,author,body,createdAt,comments"])
    return {i["number"]: i for i in json.loads(raw)}, owner


def _fmt(v) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render(rows: list[Row], summ: dict, unmapped) -> str:
    cols = [("app", "app"), ("status", "status"), ("shipped", "shipped"),
            ("grouped", "grouped"), ("named", "named"),
            ("to work s/g/n", "_to_working"),
            ("first working", "first_working"),
            ("days", "days_to_working"), ("owed", "owed"),
            ("waiting", "waiting_days")]
    table = [[h for h, _ in cols]]
    for r in rows:
        line = []
        for _, k in cols:
            if k == "_to_working":
                line.append("-" if r.shipped_to_working is None else
                            f"{r.shipped_to_working}/{r.grouped_to_working}"
                            f"/{r.named_to_working or '-'}")
            else:
                line.append(_fmt(getattr(r, k)))
        table.append(line)
    widths = [max(len(line[i]) for line in table) for i in range(len(cols))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(line, widths)).rstrip()
             for line in table]
    lines.append("")
    lines.append("shipped  releases linked on the issue, newest-first rule")
    lines.append("grouped  site-layer commits grouped by tester reports")
    lines.append("named    highest round a commit subject named")
    lines.append("to work  the same three, up to the first working Pilot")
    lines.append("owed     whose move it is, and waiting for how many days")
    lines.append("")
    for label, key in [("Rounds to a first working Pilot",
                        "shipped_to_working"),
                       ("Same, counted from commits", "grouped_to_working"),
                       ("Days to a first working Pilot", "days_to_working"),
                       ("Rounds so far, still unfinished",
                        "shipped_so_far_unfinished")]:
        s = summ[key]
        lines.append(f"{label}. " + (
            "none" if not s else
            f"{s['n']} providers, median {_fmt(float(s['median']))}, "
            f"worst {s['worst']}"))
    u = summ["untested"]
    lines.append(f"Untested. {u['n']} providers"
                 + (f" ({', '.join(u['apps'])}), waiting a median of "
                    f"{_fmt(float(u['waiting_days']['median']))} days, "
                    f"longest {u['waiting_days']['worst']}"
                    if u["n"] else ""))
    disagree = [r for r in rows if r.disagreement]
    if disagree:
        lines.append("")
        lines.append("Where the counts disagree")
        for r in disagree:
            lines.append(f"  {r.app}  {r.disagreement}")
    if unmapped:
        lines.append("")
        lines.append("Provider issues this tool does not know about")
        for n, title in unmapped:
            lines.append(f"  #{n}  {title}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="print the rows and summary as JSON")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD",
                    help="read the record as it stood at the end of this "
                         "day, local time")
    args = ap.parse_args(argv)
    commits = load_commits()
    issues, owner = load_issues()
    names = {app: names for app, names, _, _ in PROVIDERS}
    now = datetime.now(timezone.utc)
    if args.as_of:
        now = datetime.fromisoformat(args.as_of + "T23:59:59").astimezone()
    rows = [analyze(app, kind, ns, issues, commits, owner, names, now,
                    changed=release_changed)
            for app, _, ns, kind in PROVIDERS]
    summ = summary(rows)
    unmapped = unmapped_issues(issues)
    if args.json:
        print(json.dumps({"rows": [asdict(r) for r in rows],
                          "summary": summ,
                          "unmapped": unmapped}, indent=2, default=str))
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(render(rows, summ, unmapped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
