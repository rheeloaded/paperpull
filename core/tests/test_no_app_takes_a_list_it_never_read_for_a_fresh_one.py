"""A list kept with the time it was read, and read again once older than so
many seconds, starts out as never read, its time 0.0. time.monotonic()
counts from the computer's start on Windows, so on a computer up less than
those seconds the age alone passed a list never read for a fresh one. FedEx
then found no link and sent each invoice to the person, and Stripe fetched
the address an older list gave. It failed main's CI on 2026-11-09 on a
runner just started. Every such age check also asks whether the list was
ever read."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# time.monotonic() - <kept>["at"] > <seconds>
AGE = re.compile(r"monotonic\(\)\s*-\s*(\w+)\[[\"']at[\"']\]\s*>")


def age_checks():
    """Each age check in an app's own code, with the whole condition it
    sits in, from its `if` to the colon that ends it."""
    found = []
    for path in sorted((ROOT / "apps").glob("*/*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = AGE.search(line)
            if not m:
                continue
            start = i
            while start > i - 4 and not re.match(r"\s*(el)?if\b|\s*while\b|\s*return\b", lines[start]):
                start -= 1
            end = i
            while end < i + 4 and not lines[end].rstrip().endswith(":"):
                end += 1
            found.append(("%s:%d" % (path.relative_to(ROOT).as_posix(), i + 1), m.group(1),
                          " ".join(s.strip() for s in lines[start:end + 1])))
    return found


CHECKS = age_checks()


def test_the_census_finds_the_age_checks_it_was_written_for():
    places = {where.split(":")[0] for where, _, _ in CHECKS}
    assert {"apps/fedex/fedex_site.py", "apps/stripe/stripe_site.py",
            "apps/ups/ups_site.py", "apps/bofa/bofa_site.py"} <= places, places


@pytest.mark.parametrize("where,kept,condition", CHECKS, ids=[c[0] for c in CHECKS])
def test_a_list_never_read_is_never_taken_for_a_fresh_one(where, kept, condition):
    never = (re.search(r"\bnot\s+%s\[[\"']at[\"']\]" % re.escape(kept), condition)
             or re.search(r"\bis None\b", condition))
    assert never, ("%s reads %s's age alone, so on a computer up less than its seconds a list "
                   "never read passes for a fresh one. Ask `not %s[\"at\"]` too.\n  %s"
                   % (where, kept, kept, condition))
