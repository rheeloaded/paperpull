"""How does each provider's document actually reach the disk.

Run it from the repository root.

    python tools/delivery_census.py
    python tools/delivery_census.py --markdown

Reads call sites, never imports, because half the apps import a helper
they do not use and the other half hand-roll the same thing under their
own names. An app that names nothing recognizable is listed at the
bottom as unclassified, which is the honest answer and also the finding,
since a bespoke implementation is exactly what this census exists to
count.

The table this produces is in docs/delivery-architecture.md. Regenerate
it there rather than editing it by hand.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Each mechanism, and what a call site of it looks like. Order matters
# only for how the columns print.
MECHANISMS = [
    ("attachment/event", "A",
     r"\bexpect_download\b|\[[\"']download[\"']\]\.save_as|"
     r"save_download\(",
     "The provider sent Content-Disposition: attachment, or the markup "
     "carried a download attribute, and Playwright saw the download."),

    ("attachment/dir", "B",
     r"take_new_pdf|_take_new_pdf\(|set_download_dir\(",
     "The same thing, against a browser the user launched. Playwright's "
     "download event never fires there, so the browser saves the file "
     "itself and the app watches the folder."),

    ("inline/tab", "C",
     r"take_new_tab|take_same_tab|_catch_pdf|expect_popup|"
     r"on\([\"']popup[\"']",
     "Content-Disposition: inline, or none, so the browser's own viewer "
     "rendered it and the app has to go and get the bytes."),

    ("anchor", "D",
     r"(?:has|get)Attribute\(\s*[\"']download[\"']\s*\)",
     "The front end forced a save with an <a download> attribute. Only "
     "counted where the app reads the attribute, because a selector "
     "mentioning a[download] is a place the app looks, not proof of how "
     "the file arrived. At capture time this is indistinguishable from "
     "column A, since both produce a download event."),

    ("blob", "E",
     r"blob:",
     "The page built the file in its own memory and handed over a blob: "
     "or data: URL."),

    ("session/fetch", "F",
     r"fetch_pdf|fetch_as_b64|fetch_with_status|_FETCH_AS_B64|"
     r"context\.request\.|page\.request\.|arrayBuffer\(\)",
     "Nothing was triggered. The app asked for the bytes itself through "
     "the signed-in session, either from inside the page or beside it."),

    ("rendered", "G",
     r"print_page_to_pdf|print_html_to_pdf|print_frame_to_pdf|"
     r"render_url_headless|Page\.printToPDF",
     "There was no file. The provider showed a page and the app printed "
     "it."),
]


def entry_files(app: Path):
    out = []
    for pattern in ("*_site.py", "*_docs.py", "*_receipts.py"):
        out += sorted(app.glob(pattern))
    return out


def call_sites(path: Path) -> str:
    """The file with its imports and comments taken out.

    An import proves an app was generated from a scaffold. Only a call
    proves it does the thing."""
    kept = []
    for line in io.open(path, encoding="utf-8", errors="ignore"):
        stripped = line.lstrip()
        if stripped.startswith(("import ", "from ", "#")):
            continue
        kept.append(line)
    return "".join(kept)


def census() -> list:
    rows = []
    apps = REPO / "apps"
    for app in sorted(p for p in apps.iterdir() if p.is_dir()):
        files = entry_files(app)
        if not files:
            continue
        text = "".join(call_sites(f) for f in files)
        found = [short for name, short, rx, _ in MECHANISMS
                 if re.search(rx, text)]
        rows.append((app.name, found))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markdown", action="store_true",
                    help="print the table as markdown for the design note")
    args = ap.parse_args()

    rows = census()
    if not rows:
        print("no apps found, run this from the repository root")
        return 1

    shorts = [m[1] for m in MECHANISMS]

    if args.markdown:
        print("| provider | " + " | ".join(shorts) + " |")
        print("|---|" + "---|" * len(shorts))
        for app, found in rows:
            marks = " | ".join("x" if s in found else "" for s in shorts)
            print("| %s | %s |" % (app, marks))
    else:
        head = "  ".join(s.rjust(4) for s in shorts)
        print("%-16s %s" % ("provider", head))
        for app, found in rows:
            marks = "  ".join(("x" if s in found else ".").rjust(4)
                              for s in shorts)
            print("%-16s %s" % (app, marks))

    print()
    print("-- what each column means --")
    for name, short, _, why in MECHANISMS:
        hit = [a for a, f in rows if short in f]
        print("%s  %-16s %2d app(s)" % (short, name, len(hit)))
        print("    %s" % why)

    print()
    print("-- how many mechanisms one app carries --")
    for count, many in sorted(Counter(len(f) for _, f in rows).items()):
        print("   %d mechanism(s)  %2d app(s)" % (count, many))
    mixed = sum(1 for _, f in rows if len(f) >= 3)
    print("   %d of %d apps already try three or more, because which one a"
          % (mixed, len(rows)))
    print("   provider uses is not knowable before a live run.")

    unclassified = [a for a, f in rows if not f]
    if unclassified:
        print()
        print("-- nothing recognized, so read these by hand --")
        for app in unclassified:
            print("   %s" % app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
