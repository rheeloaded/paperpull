"""Can the wrong-document check be trusted for this provider.

Run it against an install that already holds documents, before turning
refuse_wrong_documents on for that provider.

    python tools/identity_fit.py "C:\\...\\TSP Statements"
    python tools/identity_fit.py "C:\\...\\Costco Receipts" --quiet

WHY THIS EXISTS

The check asks whether a saved PDF mentions the facts its row carried.
Whether that works at all is a property of the provider, and there are
three outcomes, all of them found in one afternoon against real
archives.

  Costco, T-Mobile, Navy Federal, Target RedCard
      The date prints on the document. Every document verifies against
      its own row and refuses every other. The check works.

  Fairfax Water
      Every bill prints the PREVIOUS bill's date beside its own, so the
      July bill passes a check for the April bill. Ten of twelve
      cross-checks refuse correctly and the two that do not are
      adjacent quarters, which is the case the check exists for.

  TSP
      Eight of twenty five documents do not mention their own date at
      all, because a mailbox row is dated when the document was
      delivered rather than by anything printed on it. Switching the
      check on would refuse a third of the archive.

That last one is why the default is off and why this tool exists. A
guard that refuses good documents is worse than no guard, and the only
way to know which provider you have is to measure.

WHAT IT READS

Saved PDFs and the dates in their filenames. Nothing is downloaded,
nothing is written, and no value from any document is printed.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Enough documents for a cross-check to mean anything. Below this the
# answer is "not enough to say" rather than a verdict.
ENOUGH = 4


def core_from(install: Path):
    """The installed copy of the core, so this measures what that
    install would actually do rather than what the repository does."""
    for rel in ("Lib/site-packages", "lib/site-packages"):
        d = install / ".venv" / rel
        if d.is_dir():
            sys.path.insert(0, str(d))
            break
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
    from paperpull_core import identity
    return identity


def documents(install: Path):
    out = []
    for p in sorted(install.rglob("*.pdf")):
        if "Backups" in p.parts or "Manual Review" in p.parts:
            continue
        m = DATE_IN_NAME.search(p.name)
        if m:
            out.append((m.group(1), p))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("install", help="a provider folder holding saved PDFs")
    ap.add_argument("--quiet", action="store_true",
                    help="the verdict only, no per-document lines")
    args = ap.parse_args()

    install = Path(args.install)
    if not install.is_dir():
        print("not a folder: %s" % install)
        return 2

    I = core_from(install)
    docs = documents(install)
    if len(docs) < ENOUGH:
        print("Only %d document(s) with a date in the filename." % len(docs))
        print("Not enough to say. Run the provider first, or keep the")
        print("check off until there are a few to compare.")
        return 1

    print("%d document(s) in %s\n" % (len(docs), install.name))

    texts = {}
    for iso, p in docs:
        texts[p] = I._text_of(p, 5)

    own = []
    for iso, p in docs:
        v = I.verify(p, I.Identity(date=iso), text=texts[p])
        own.append((iso, p, v.outcome))
    verified = [x for x in own if x[2] == I.VERIFIED]
    if not args.quiet:
        for iso, p, outcome in own:
            if outcome != I.VERIFIED:
                print("  does not mention its own date  %s" % p.name[:52])
    print("verify against their own row: %d of %d"
          % (len(verified), len(docs)))

    missed = []
    total = 0
    for iso_a, pa in docs:
        for iso_b, pb in docs:
            if iso_a == iso_b:
                continue
            total += 1
            if I.verify(pa, I.Identity(date=iso_b),
                        text=texts[pa]).outcome != I.REFUSED:
                missed.append((pa.name, iso_b))
    if not args.quiet:
        for name, iso in missed[:6]:
            print("  also matches another row's date %s" % name[:52])
    print("refuse another row's date:    %d of %d" % (total - len(missed), total))

    print()
    if len(verified) < len(docs):
        print("VERDICT  keep refuse_wrong_documents OFF.")
        print("         %d document(s) would be refused and lost, because a"
              % (len(docs) - len(verified)))
        print("         row here is dated by something the document does not")
        print("         print. That is worse than having no check.")
        return 1
    if missed:
        print("VERDICT  keep refuse_wrong_documents OFF, or accept a partial")
        print("         check. Nothing good would be refused, but %d pair(s)"
              % len(missed))
        print("         of documents cannot be told apart, which is usually")
        print("         a document that prints the previous period's date.")
        return 1
    print("VERDICT  refuse_wrong_documents can be turned ON.")
    print("         Every document verifies against its own row and refuses")
    print("         every other one, across %d comparison(s)." % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
