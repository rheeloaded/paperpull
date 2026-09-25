"""File names from a pattern of named fields (#50).

    {date:yyyymmdd}[ - {provider}][ -- {number|kind}]

A pattern is text with fields in it. What it can say is deliberately
small, because the people writing one are not programmers and a pattern
must never be able to run anything.

    {field}             the field's value
    {date:yyyy-mm-dd}   a date written that way. The pieces are yyyy, yy,
                        mm, m, dd, d, mmm (Jan) and mmmm (January), and
                        anything else in the format is written as it is
    {a|b|c}             the first of these fields that has a value
    [ ... ]             an optional section. If any field inside it is
                        empty the whole section is left out, separators
                        and all, which is what stops a provider with no
                        order number leaving "Amazon -- " with nothing after
    \\[ \\] \\{ \\}           a bracket or a brace written as itself

Everything else is written as it stands. The caller makes the result safe
for the file system, so this only ever assembles text.

The fields are the ones docs/file-naming.md settled on from an audit of
every app, and a pattern naming anything else is refused with a message
saying which field and where, so a typo is caught when the pattern is set
and not discovered as a folder of oddly named files.

A pattern that starts with {{ or {% is refused for now. Those are kept
free for a Jinja mode, if one is ever needed, so a pattern written today
can never mean something different tomorrow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Union

# Every field a pattern may name. year and month come from date.
FIELDS = ("date", "year", "month", "provider", "owner", "kind", "summary",
          "number", "account", "total", "store", "type", "part")

DATE_FIELDS = ("date",)

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

# The patterns that reproduce every name as it was before patterns
# existed, to the character, and a test renders each app's names both
# ways. They are the same for both kinds. Statements carried the kind the
# call passed too, which is usually nothing and sometimes Tax Document,
# and a statements default without it renamed those.
DEFAULT_RECEIPTS = "{date:yyyy-mm-dd}[ {owner}] {provider} {summary}[ {kind}][ ({part})]"
DEFAULT_STATEMENTS = DEFAULT_RECEIPTS

_DATE_TOKEN = re.compile(r"yyyy|yy|mmmm|mmm|mm|m|dd|d")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


class PatternError(ValueError):
    """A pattern that cannot be used, with where and why."""

    def __init__(self, message: str, position: int):
        super().__init__("%s (at character %d)" % (message, position + 1))
        self.position = position
        self.reason = message


@dataclass
class _Text:
    text: str


@dataclass
class _Field:
    names: List[str]
    fmt: str = ""


@dataclass
class _Optional:
    parts: list = field(default_factory=list)


_Node = Union[_Text, _Field, _Optional]


def parse(pattern: str) -> List[_Node]:
    """The pattern as parts, or a PatternError saying what is wrong."""
    if not isinstance(pattern, str) or not pattern.strip():
        raise PatternError("the pattern is empty", 0)
    if pattern.lstrip().startswith(("{{", "{%")):
        raise PatternError("a pattern starting {{ or {% is kept for a later "
                           "template mode and is not understood yet", 0)
    stack: List[list] = [[]]
    opened: List[int] = []
    text = []
    i = 0

    def flush():
        if text:
            stack[-1].append(_Text("".join(text)))
            text.clear()

    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern) and pattern[i + 1] in "[]{}\\":
            text.append(pattern[i + 1])
            i += 2
            continue
        if ch == "{":
            end = pattern.find("}", i)
            if end < 0:
                raise PatternError("a { is never closed", i)
            flush()
            stack[-1].append(_field(pattern[i + 1:end], i))
            i = end + 1
            continue
        if ch == "}":
            raise PatternError("a } with no { before it", i)
        if ch == "[":
            flush()
            node = _Optional()
            stack[-1].append(node)
            stack.append(node.parts)
            opened.append(i)
            i += 1
            continue
        if ch == "]":
            if len(stack) == 1:
                raise PatternError("a ] with no [ before it", i)
            flush()
            stack.pop()
            opened.pop()
            i += 1
            continue
        text.append(ch)
        i += 1
    if opened:
        raise PatternError("a [ is never closed", opened[-1])
    flush()
    parts = stack[0]
    if not any(isinstance(n, (_Field, _Optional)) for n in parts):
        raise PatternError("the pattern names no field, so every file would "
                           "get the same name", 0)
    return parts


def _field(body: str, position: int) -> _Field:
    head, _, fmt = body.partition(":")
    names = [n.strip() for n in head.split("|")]
    if not all(names):
        raise PatternError("a field with no name", position)
    for name in names:
        if name not in FIELDS:
            raise PatternError('there is no field called "%s". The fields '
                               'are %s' % (name, ", ".join(FIELDS)), position)
    if fmt:
        if any(n not in DATE_FIELDS for n in names):
            raise PatternError("only a date can have a format, as in "
                               "{date:yyyy-mm-dd}", position)
        if not _DATE_TOKEN.search(fmt):
            raise PatternError('the date format "%s" has none of yyyy, yy, '
                               'mm, m, dd, d, mmm or mmmm in it' % fmt, position)
    return _Field(names, fmt)


def format_date(value: str, fmt: str) -> str:
    """An ISO date written in `fmt`. A value that is not a date is written
    as it is, since a record from before dates were checked may hold one,
    and a name with its old text in it beats a run that stops."""
    m = _ISO.match(value or "")
    if not m or not fmt:
        return value or ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12):
        return value
    table = {"yyyy": "%04d" % y, "yy": "%02d" % (y % 100),
             "mmmm": MONTHS[mo - 1], "mmm": MONTHS[mo - 1][:3],
             "mm": "%02d" % mo, "m": str(mo), "dd": "%02d" % d, "d": str(d)}
    return _DATE_TOKEN.sub(lambda t: table[t.group(0)], fmt)


def _value(node: _Field, fields: dict) -> str:
    for name in node.names:
        raw = fields.get(name)
        text = "" if raw is None else str(raw).strip()
        if text:
            return format_date(text, node.fmt) if node.fmt else text
    return ""


def _render(parts: list, fields: dict) -> Optional[str]:
    """The parts as text, or None when a field directly in them is empty,
    which is what makes an optional section drop out."""
    out = []
    for node in parts:
        if isinstance(node, _Text):
            out.append(node.text)
        elif isinstance(node, _Field):
            v = _value(node, fields)
            if not v:
                return None
            out.append(v)
        else:
            inner = _render(node.parts, fields)
            out.append(inner or "")
    return "".join(out)


def render(pattern: str, fields: dict) -> str:
    """The pattern filled in from `fields`. A field that is empty outside
    any optional section is left empty, so the words around it stay, and
    the caller's cleanup closes the gap."""
    parts = parse(pattern)
    out = []
    for node in parts:
        if isinstance(node, _Text):
            out.append(node.text)
        elif isinstance(node, _Field):
            out.append(_value(node, fields))
        else:
            out.append(_render(node.parts, fields) or "")
    return "".join(out)


def check(pattern: str) -> Optional[str]:
    """Why a pattern cannot be used, or None. For the settings page."""
    try:
        parse(pattern)
    except PatternError as e:
        return str(e)
    return None


def fields_of(record, *, date: str = "", summary: str = "", kind: str = "",
              provider: str = "", owner: str = "", part=None,
              receipts: bool = False) -> dict:
    """The naming fields for one document.

    `record` is the app's own record, an object or a dict, and anything it
    does not have is simply empty. The arguments are what the app passes
    today, and they win, because they are what today's names are built
    from and the defaults must not change a single one."""
    def get(*names):
        for name in names:
            if isinstance(record, dict):
                v = record.get(name)
            else:
                v = getattr(record, name, None)
            if v not in (None, ""):
                return str(v)
        return ""

    d = date or get("date", "purchase_date")
    iso = _ISO.match(d or "")
    out = {
        "date": d,
        "year": iso.group(1) if iso else "",
        "month": iso.group(2) if iso else "",
        "provider": provider,
        "owner": owner,
        # A statement's kind is its category, Statement or Tax Document.
        # A receipt's is its document type, Receipt or Invoice.
        "kind": kind or (get("document_type", "category") if receipts
                         else get("category", "document_type")),
        "summary": summary or get("summary"),
        "number": get("order_number", "document_id"),
        "account": get("account"),
        "total": get("total"),
        "store": get("store_info"),
        "type": get("purchase_type"),
        "part": "%d of %d" % part if part and part[1] > 1 else "",
    }
    return out



def preview(pattern: str, record, *, provider: str, owner: str = "",
            receipts: bool = False, document_type: str = "") -> str:
    """A document's name under `pattern`, the way a run would build it,
    without binding an app. For the control panel's preview.

    Only for a pattern somebody wrote. Under the default the kind is what
    the app passed at the time, which is not in the record, and the name
    already on disk is the preview."""
    from .storage import sanitize_component, title_case
    date = ""
    summary = ""
    if isinstance(record, dict):
        date = str(record.get("date") or record.get("purchase_date") or "")
        summary = str(record.get("summary") or "")
    fields = fields_of(record, date=(date or "0000-00-00").strip(),
                       summary=title_case(summary or "Purchase"),
                       kind=document_type, provider=provider,
                       owner=(owner or "").strip(), receipts=receipts)
    return sanitize_component(render(pattern, fields)) + ".pdf"


def fill_rates(records, receipts: bool = False) -> dict:
    """How many records fill each field, for the settings page. Counts
    only, the page shows them beside each field so nobody builds a
    pattern on one this provider never fills."""
    counts = dict.fromkeys(FIELDS, 0)
    n = 0
    for r in records or ():
        if not isinstance(r, dict):
            continue
        n += 1
        f = fields_of(r, receipts=receipts, provider="x")
        for name in FIELDS:
            if name == "owner":
                continue
            if str(f.get(name) or "").strip():
                counts[name] += 1
    counts["provider"] = n
    return {"records": n, "filled": counts}
