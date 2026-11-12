"""Every credit in PROVIDERS.md is a sentence of its own.

The website's provider directory is built from PROVIDERS.md, and a
visitor's note there leaves out who contributed an app by removing exactly
"Contributed by @name." (paperpull-site, site/tools/gen_providers.py). A
credit that runs on into the rest of its sentence leaves that rest behind
as a note, so the site said "whose full run saved 21 statements" of Optum
Bank, ", whose" of Discover Bank in 0.62.0, and "and run on the
contributor's own account" of ING in 0.63.0. A credit ends with its full
stop, or ends the cell.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# A credit, then what follows it in its cell.
CREDIT = re.compile(r"Contributed by @[\w-]+(?P<after>[^|]*)")


def credits_that_run_on(text: str) -> list:
    """Each credit in these table rows that is not followed by a full stop
    or by the end of its cell, with what follows it."""
    bad = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            continue
        for m in CREDIT.finditer(line):
            after = m.group("after")
            if after.startswith(".") or not after.strip():
                continue
            bad.append("PROVIDERS.md:%d %s" % (n, m.group(0)[:80]))
    return bad


def test_every_credit_in_providers_is_a_sentence_of_its_own():
    bad = credits_that_run_on((REPO / "PROVIDERS.md").read_text(encoding="utf-8"))
    assert not bad, (
        "End each credit with a full stop and start the rest as a sentence of "
        "its own, \"Contributed by @name. Their run saved...\", since the "
        "website removes the credit and keeps what follows:\n  " + "\n  ".join(bad))


def test_the_census_finds_a_credit_that_runs_on():
    row = "| `x` | X | Bills. Contributed by @{0}{1} | Bank |"
    for after in (", whose run saved 3 bills.", " and run on the contributor's own account.",
                  " (#1). One more."):
        assert credits_that_run_on(row.format("someone", after)), after
    for after in (". Run on the contributor's own account.", ".", "", " "):
        assert not credits_that_run_on(row.format("someone", after)), after
