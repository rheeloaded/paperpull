"""Is this the document we asked for, and not merely a document.

`receipt_pdf.validate_pdf` already asks whether a saved file is a real
PDF from this provider. That is not the same question. It takes an
`expect_tokens` list, satisfied when ANY token appears, and the first
token it is usually given is the provider's own name, which every page of
every statement carries. A file can pass it while being the wrong month.

Nothing checks the other question today. Of the 148 places that call
`validate_pdf`, 129 pass no tokens at all.

WHY IT MATTERS MORE THAN IT LOOKS

The realistic failure in this program is not saving nothing. It is
saving the wrong thing under the right name. A row index off by one, a
candidate selector that matched a neighbor, a modal that did not close
so the next capture re-read the last document. Every one of those writes
a valid PDF to a correct-looking path, the run reports success, and
nobody finds out until a tax year is being reconciled.

That failure is silent by construction, so the check for it has to be
structural rather than something an app remembers to do.

WHAT MAKES A FACT WORTH CHECKING

A fact is discriminating when two documents from the same provider would
disagree about it. An order number, a date, a period, a total. The
provider's name is not discriminating, which is exactly why the existing
check passes on it.

    STRONG      number, date, period, total
    WEAK        kind, and anything else

Only strong facts decide. A weak one is recorded and ignored.

WHAT COMES OUT

A verdict, and never a value. The report this produces goes into a
failure file a tester may attach to a public issue, so it says which
fields were supplied and which were found, as names and booleans. That
a date disagreed is the finding. What the date was is theirs. See
docs/failure-diagnostics.md for why that boundary is drawn where it is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# The outcomes. There are four because collapsing any two of them loses
# the difference between a wrong document and an unreadable one, and
# those want opposite responses.
VERIFIED = "verified"        # a strong fact was found in the text
REFUSED = "refused"          # strong facts were supplied, text was readable, none appeared
UNREADABLE = "unreadable"    # a scan or an image, nothing to check against
UNCHECKED = "unchecked"      # nothing discriminating was supplied to check

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_NOT_ALNUM = re.compile(r"[^0-9A-Za-z]")
_SPACE = re.compile(r"\s+")

# How much extractable text counts as a document rather than a scan with
# a stray character on it. Below this, nothing is concluded.
MIN_TEXT = 40

# A number shorter than this is not a document number, it is a page
# number or a count, and looking for it would match anything.
MIN_NUMBER = 4


def _squash(text: str) -> str:
    """Whitespace removed.

    A warehouse till prints per letter, so the page reads T a r g e t and
    no ordinary search finds anything. Matching is tried against both."""
    return _SPACE.sub("", text or "")


def date_variants(iso: str) -> list:
    """The ways a provider might print one date.

    American orderings only. Adding day-first would make 01/02/2026 match
    both January 2nd and February 1st, and a check that matches the wrong
    document is worse than no check."""
    m = _ISO_DATE.match((iso or "").strip())
    if not m:
        return []
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return []
    name = MONTHS[month - 1]
    short = name[:3]
    yy = year % 100
    out = [
        "%04d-%02d-%02d" % (year, month, day),
        "%04d/%02d/%02d" % (year, month, day),
        "%02d/%02d/%04d" % (month, day, year),
        "%d/%d/%04d" % (month, day, year),
        "%02d/%02d/%02d" % (month, day, yy),
        "%d/%d/%02d" % (month, day, yy),
        "%02d-%02d-%04d" % (month, day, year),
        "%02d.%02d.%04d" % (month, day, year),
        "%s %d, %04d" % (name, day, year),
        "%s %d %04d" % (name, day, year),
        "%s %d, %04d" % (short, day, year),
        "%s. %d, %04d" % (short, day, year),
        "%d %s %04d" % (day, name, year),
        "%d %s %04d" % (day, short, year),
    ]
    return list(dict.fromkeys(out))


def period_variants(iso_month: str) -> list:
    """The ways a provider might print one month, for a statement that is
    dated by period rather than by day."""
    m = _ISO_MONTH.match((iso_month or "").strip())
    if not m:
        return []
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return []
    name = MONTHS[month - 1]
    return list(dict.fromkeys([
        "%04d-%02d" % (year, month),
        "%02d/%04d" % (month, year),
        "%d/%04d" % (month, year),
        "%s %04d" % (name, year),
        "%s %04d" % (name[:3], year),
    ]))


def amount_variants(total) -> list:
    """The ways a provider might print one amount.

    Zero is refused. Every statement with nothing on it shows 0.00, so it
    tells two documents apart exactly never."""
    try:
        value = abs(float(str(total).replace(",", "").replace("$", "").strip()))
    except (TypeError, ValueError):
        return []
    if value < 0.01:
        return []
    plain = "%.2f" % value
    whole, cents = plain.split(".")
    grouped = "{:,}".format(int(whole)) + "." + cents
    return list(dict.fromkeys([plain, grouped, "$" + plain, "$" + grouped]))


def number_variants(number) -> list:
    """A document number as printed, and with its punctuation gone."""
    raw = str(number or "").strip()
    if not raw:
        return []
    bare = _NOT_ALNUM.sub("", raw)
    if len(bare) < MIN_NUMBER:
        return []
    # A run of one repeated character is a placeholder, not an identifier.
    if len(set(bare)) < 2:
        return []
    return list(dict.fromkeys([raw, bare]))


@dataclass(frozen=True)
class Identity:
    """What the app believes it asked the provider for.

    Every field is optional because providers differ in what they show on
    a list. An Identity carrying no strong fact is honest about that and
    verifies as UNCHECKED rather than pretending."""

    date: str = ""        # ISO, the day this document is dated
    period: str = ""      # ISO year and month, where there is no day
    total: str = ""       # the amount as the list showed it
    number: str = ""      # order, document or confirmation number
    kind: str = ""        # what it is called. Recorded, never decisive
    # Words that name this document apart from its neighbours, such as
    # the account a statement belongs to. Useless alone, because every
    # statement of a kind carries the same ones, and decisive against a
    # competing row that carries different ones. Only `distinguish`
    # reads it.
    label: str = ""
    extra: tuple = field(default_factory=tuple)   # app-supplied strong facts

    def strong(self) -> dict:
        """Each strong fact that is usable, and the ways it might print."""
        out = {}
        for name, variants in (("number", number_variants(self.number)),
                               ("date", date_variants(self.date)),
                               ("period", period_variants(self.period)),
                               ("total", amount_variants(self.total))):
            if variants:
                out[name] = variants
        for i, value in enumerate(self.extra or ()):
            variants = number_variants(value)
            if variants:
                out["extra%d" % i] = variants
        return out

    def is_checkable(self) -> bool:
        return bool(self.strong())

    @classmethod
    def from_purchase(cls, purchase) -> "Identity":
        """The receipt apps already carry one of these."""
        return cls(date=getattr(purchase, "purchase_date", "") or "",
                   total=str(getattr(purchase, "total", "") or ""),
                   number=getattr(purchase, "order_number", "") or "")


    def marks(self) -> dict:
        """Every way this document might print, by fact name.

        The strong facts plus the label, which is what `distinguish`
        compares against a competing row."""
        out = dict(self.strong())
        text = str(self.label or "").strip()
        if len(text) >= 3:
            out["label"] = [text]
        return out


@dataclass(frozen=True)
class Verdict:
    outcome: str
    checked: tuple = ()      # the strong fields that were usable
    matched: tuple = ()      # the ones found in the document
    text_chars: int = 0      # how much text there was to look at

    @property
    def ok(self) -> bool:
        """Whether a caller that is not being strict may keep the file."""
        return self.outcome != REFUSED

    def report(self) -> dict:
        """For the failure file. Names and counts, never a value.

        This is the whole reason the module reports rather than returning
        what it saw. A date that disagreed is ours to publish. The date
        is not."""
        return {"outcome": self.outcome,
                "checked": sorted(self.checked),
                "matched": sorted(self.matched),
                "text_chars": min(int(self.text_chars), 1_000_000)}

    def say(self) -> str:
        """One sentence, for a run's own output."""
        if self.outcome == VERIFIED:
            return "the document matches the %s it was listed under" % (
                " and ".join(sorted(self.matched)) or "details")
        if self.outcome == REFUSED:
            return ("the document does not mention the %s it was listed "
                    "under, so it is probably not the right one"
                    % " or ".join(sorted(self.checked)))
        if self.outcome == UNREADABLE:
            return "the document holds no text to check, which a scan does"
        return "nothing was known about this document to check against"


def contains(text: str, variants: Iterable[str]) -> bool:
    """Whether any way of printing a fact appears in the text."""
    if not text:
        return False
    low = text.lower()
    squashed = _squash(low)
    for variant in variants:
        needle = str(variant).lower()
        if needle and (needle in low or _squash(needle) in squashed):
            return True
    return False


def verify(path, expect: Optional[Identity], *, text: Optional[str] = None,
           pages: int = 5) -> Verdict:
    """Whether the saved PDF is the document `expect` describes.

    `text` is for callers that already extracted it, and for tests. Never
    raises. A check that can take a run down is worse than no check."""
    if expect is None:
        return Verdict(UNCHECKED)
    strong = expect.strong()
    if not strong:
        return Verdict(UNCHECKED)

    if text is None:
        text = _text_of(path, pages)
    chars = len(text or "")
    if chars < MIN_TEXT:
        # A scan, or a PDF whose text is drawn rather than written. There
        # is nothing to disagree with, which is not the same as agreeing.
        return Verdict(UNREADABLE, tuple(strong), (), chars)

    matched = tuple(name for name, variants in strong.items()
                    if contains(text, variants))
    outcome = VERIFIED if matched else REFUSED
    return Verdict(outcome, tuple(strong), matched, chars)


def rivals_for(rows, index: int, *, span: int = 3) -> tuple:
    """The rows this one could actually be confused with.

    Not the whole list, and the reason is measurable. A fact a competing
    row shares stops counting, so every extra rival takes evidence out of
    play. Against all sixty four Navy Federal statements at once, sixteen
    of them ended up placeable by nothing. Against their neighbours, far
    fewer do.

    Three things go wrong in practice and this covers all of them.

        an index off by one          the rows either side
        two documents on one date    every row sharing that date
        a dialog that never closed   the row before, already included

    `rows` is the whole ordered list as Identity objects, `index` is the
    position of the one being captured."""
    rows = list(rows or ())
    if not (0 <= index < len(rows)):
        return ()
    mine = rows[index]
    span = max(1, int(span))
    near = set(range(max(0, index - span), min(len(rows), index + span + 1)))
    date = str(getattr(mine, "date", "") or "")
    if date:
        near.update(n for n, r in enumerate(rows)
                    if str(getattr(r, "date", "") or "") == date)
    near.discard(index)
    return tuple(rows[n] for n in sorted(near))


def distinguish(path, expect: Optional[Identity], others=(), *,
                text: Optional[str] = None, pages: int = 5) -> Verdict:
    """Whether the saved PDF is `expect` rather than one of `others`.

    The better question, and the one three real archives said `verify`
    was answering badly.

    A Navy Federal date carries a statement for every account, because
    they are all billed on the same day. A Fairfax bill prints the
    previous bill's date beside its own. In both, asking whether the
    document mentions the row's date gets a yes from the wrong document.

    So this asks which row the document matches BEST, not whether it
    matches one at all. Only facts no competing row shares can count,
    and then it is a matter of how many.

        this row matches more of its own than any rival     verified
        a rival matches more of its own than this row does  refused
        nobody matches anything of their own                unchecked

    Counting rather than requiring is what keeps it honest. The July
    Fairfax bill carries April's date, so April scores one, but it also
    carries July's amount, so July scores two and April is refused. A
    TSP statement that prints neither date leaves everybody at zero and
    is placed by nothing, which is not the same as belonging elsewhere.

    It never refuses a document for failing to print something it never
    prints, which is how a check starts throwing away good documents.

    With no competitors this is `verify`, because then nothing is shared
    and every fact is its own."""
    if expect is None:
        return Verdict(UNCHECKED)
    rivals = [o for o in others if isinstance(o, Identity) and o is not expect]
    if not rivals:
        return verify(path, expect, text=text, pages=pages)

    everyone = [expect] + rivals
    marks = [i.marks() for i in everyone]
    if not marks[0]:
        return Verdict(UNCHECKED)

    def pool(skip: int) -> set:
        out = set()
        for n, m in enumerate(marks):
            if n == skip:
                continue
            for variants in m.values():
                out.update(str(v).lower() for v in variants)
        return out

    # A variant somebody else also prints proves nothing about which of
    # us this is, so it is taken away from both sides.
    own = []
    for n, m in enumerate(marks):
        shared = pool(n)
        kept = {name: [v for v in variants if str(v).lower() not in shared]
                for name, variants in m.items()}
        own.append({k: v for k, v in kept.items() if v})

    mine = own[0]
    if not mine and not any(own[1:]):
        return Verdict(UNCHECKED, tuple(marks[0]), (), 0)

    if text is None:
        text = _text_of(path, pages)
    chars = len(text or "")
    if chars < MIN_TEXT:
        return Verdict(UNREADABLE, tuple(mine), (), chars)

    def score(kept) -> tuple:
        hit = tuple(name for name, variants in kept.items()
                    if contains(text, variants))
        return len(hit), hit

    my_count, matched = score(mine)
    best = max((score(k)[0] for k in own[1:]), default=0)

    if my_count and my_count >= best:
        return Verdict(VERIFIED, tuple(mine), matched, chars)
    if best > my_count:
        # Somebody else's document, by their own marks rather than by
        # the absence of ours.
        return Verdict(REFUSED, tuple(mine), matched, chars)
    return Verdict(UNCHECKED, tuple(mine), (), chars)


def _text_of(path, pages: int) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(Path(path)))
        return "\n".join((pg.extract_text() or "")
                         for pg in reader.pages[:max(1, pages)])
    except Exception:
        return ""


def summarize(report) -> list:
    """What a reader of a failure file should notice."""
    said = []
    if not isinstance(report, dict):
        return said
    outcome = report.get("outcome")
    checked = report.get("checked") or []
    if outcome == REFUSED:
        said.append("A document was saved and then refused, because its text "
                    "mentions none of the %s it was listed under. Something "
                    "captured the wrong document."
                    % " or ".join(str(c) for c in checked))
    elif outcome == UNREADABLE:
        said.append("A document held no text, so which document it is could "
                    "not be checked. That is what a scan looks like, and also "
                    "what a blank render looks like.")
    elif outcome == UNCHECKED and not checked:
        said.append("Nothing was known about this document to check it "
                    "against, so a wrong one would not have been noticed.")
    return said
