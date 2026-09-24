"""Read a recording, so writing the site layer takes an afternoon.

A tester presses Record, clicks their way to a statement once, and sends
`recording.json`. That file is complete and it is JSON, which means four
hundred lines of braces describing fourteen clicks. This reads it back as
what the person did, what the site answered, and the lines to start the
site layer from.

    python tools/read_recording.py path/to/recording.json

It also reads the file the way a tester should before attaching it
anywhere. Redaction runs inside the app with the account holder's name in
hand, so it is at its strongest there and this cannot improve on it. What
this adds is a second pair of eyes over the result, looking for the three
things redaction is known not to catch. A four or five digit number,
because the floor is six so that a year survives. A name standing on its
own, when the app had no owner configured to match it against. Anything
that still looks like an address or an email, which would mean a value
arrived by a route redaction never saw.

Nothing here contacts the network and nothing is written. It prints.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from paperpull_core.recorder import concerns  # noqa: E402,F401

KIND = "paperpull-recording"

# What a locator's `how` means, in the order the recorder prefers them.
# The first three survive a site's next deploy. The last three are a
# warning as much as a locator.
HOW_IS_SOLID = ("role", "testid", "label")
HOW_IS_BRITTLE = ("id", "name", "text")

_CSS_NAME = re.compile(r"^[A-Za-z_][\w-]*$")


# -- reading the file ----------------------------------------------------------

def load(path) -> dict:
    """The report, or a ValueError saying what the file is instead."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as e:
        raise ValueError("could not read %s, %s" % (path, e))
    except ValueError as e:
        raise ValueError("%s is not JSON, %s" % (path, e))
    if not isinstance(data, dict):
        raise ValueError("%s does not hold a recording" % path)
    if data.get("kind") != KIND:
        raise ValueError("%s is a %s, not a recording. A Diagnose file is a "
                         "survey and this reads recordings."
                         % (path, data.get("kind") or "file of some other kind"))
    return data


def steps_of(report: dict) -> list:
    steps = report.get("steps")
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def requests_of(report: dict) -> list:
    reqs = report.get("requests")
    return [r for r in reqs if isinstance(r, dict)] if isinstance(reqs, list) else []


# -- what the person did -------------------------------------------------------

def locator_of(step) -> dict:
    """A step's locator, whatever the file actually holds there.

    A tester is told to delete anything in the file they do not like the
    look of, which means every value here has been through a text editor
    and none of them can be assumed."""
    if not isinstance(step, dict):
        return {}
    loc = step.get("locator")
    return loc if isinstance(loc, dict) else {}


def name_of(step: dict) -> str:
    """A control as a person reads it, for the walkthrough."""
    loc = locator_of(step)
    name = loc.get("name") or loc.get("value") or step.get("label") or ""
    return str(name).strip()


def describe(step: dict) -> str:
    """One line saying what happened, in English."""
    loc = locator_of(step)
    how = loc.get("how")
    role = str(loc.get("role") or "").strip()
    name = name_of(step)
    what = role or {"testid": "control", "label": "field", "id": "control",
                    "name": "field", "text": "control"}.get(how, "control")
    called = ' called "%s"' % name if name else ""
    action = step.get("action")

    if action == "click":
        if how == "unresolved":
            return "clicked a %s with no name the page would answer to" % (
                loc.get("tag") or "control")
        return "clicked the %s%s" % (what, called)
    if action == "select":
        option = step.get("option") or ""
        chose = ' and chose "%s"' % option if option else " and chose an option"
        return "opened the dropdown%s%s" % (called, chose)
    if action == "check":
        return "%s the box%s" % ("ticked" if step.get("checked") else "cleared",
                                 called)
    if action == "fill":
        return "typed into the field%s (the text itself is not recorded)" % called
    if action == "submit":
        return "submitted the form%s" % called
    return "%s%s" % (action or "did something", called)


def effects(step: dict) -> list:
    """What the site did about it."""
    eff = step.get("effect") if isinstance(step, dict) else None
    eff = eff if isinstance(eff, dict) else {}
    out = []
    if eff.get("navigated"):
        landed = eff.get("landed_on") or ""
        out.append("the page moved to %s" % landed if landed else "the page moved")
    if eff.get("new_tab"):
        out.append("a new tab opened%s" % (
            " and it was NOT on the provider's site"
            if eff.get("new_tab_off_host") else ""))
    if eff.get("download"):
        got = eff.get("download_name") or ""
        out.append("a file downloaded%s" % (', called "%s"' % got if got else ""))
    if eff.get("printed"):
        out.append("the page asked the browser to print")
    try:
        n = int(eff.get("requests") or 0)
    except (TypeError, ValueError):
        n = 0
    if n:
        out.append(_plural(n, "request") + " to the provider")
    return out


# -- the lines to start from ---------------------------------------------------

def _lit(value) -> str:
    """A Python string literal. json.dumps escapes what Python escapes."""
    return json.dumps(str(value))


def locator_code(step: dict) -> str:
    """The Playwright expression for a step's control, or a comment saying
    why there is not one."""
    loc = locator_of(step)
    how = loc.get("how")
    value = loc.get("value") or ""
    if how == "role":
        return "page.get_by_role(%s, name=%s)" % (_lit(loc.get("role") or ""),
                                                  _lit(loc.get("name") or ""))
    if how == "testid":
        return "page.get_by_test_id(%s)" % _lit(value)
    if how == "label":
        return "page.get_by_label(%s)" % _lit(value)
    if how == "id":
        if _CSS_NAME.match(str(value)):
            return "page.locator(%s)" % _lit("#" + str(value))
        return "page.locator(%s)" % _lit("[id=%s]" % json.dumps(str(value)))
    if how == "name":
        return "page.locator(%s)" % _lit("[name=%s]" % json.dumps(str(value)))
    if how == "text":
        return "page.get_by_text(%s)" % _lit(value)
    return "# no stable locator, the control was a bare <%s>" % (loc.get("tag") or "?")


def step_code(step: dict) -> str:
    """The whole line, locator and act."""
    base = locator_code(step)
    if base.startswith("#"):
        return base
    action = step.get("action") if isinstance(step, dict) else None
    if action == "select":
        option = step.get("option") or ""
        return "%s.select_option(label=%s)" % (base, _lit(option))
    if action == "check":
        return "%s.%s()" % (base, "check" if step.get("checked") else "uncheck")
    if action == "fill":
        return '%s.fill(...)  # the tester typed here, the text was not recorded' % base
    if action == "submit":
        return '%s.press("Enter")' % base
    return "%s.click()" % base


# -- what to look at before this goes anywhere ---------------------------------

# -- what the maintainer is told ----------------------------------------------

def notes(report: dict) -> list:
    """What the recording says about itself, for the maintainer."""
    out = []
    steps, reqs = steps_of(report), requests_of(report)
    if not steps:
        out.append("No steps. The page was probably replaced between Record "
                   "and the first click, so the capture script went with it. "
                   "Ask for another recording.")
    brittle = [s for s in steps if locator_of(s).get("how") in HOW_IS_BRITTLE]
    unresolved = [s for s in steps if locator_of(s).get("how") == "unresolved"]
    if unresolved:
        out.append("%s landed on a control with no name the page would "
                   "answer to. This provider needs a different approach for "
                   "those, a container and a position within it, or a request "
                   "made directly." % _plural(len(unresolved), "step"))
    if brittle:
        out.append("%s rests on an id, a name attribute or visible text. "
                   "Those break on the site's next deploy, so prefer a role "
                   "or a label where the page offers one."
                   % _plural(len(brittle), "step"))
    blocked = [s for s in steps if s.get("guard_allows") is False]
    if blocked:
        out.append("%s would be refused by this app's control guard as it "
                   "stands. Either the guard needs the control's name adding, "
                   "or the tester clicked something the app should not. Read "
                   "those names before changing anything."
                   % _plural(len(blocked), "step"))
    # The locator and the label only. Every `fill` step carries the word
    # [REDACTED] where a value would be, and that is the recorder keeping
    # its promise, not a name that came through masked.
    def masked(s):
        return "[REDACTED]" in json.dumps([locator_of(s), s.get("label")],
                                          default=str)

    if any(masked(s) for s in steps):
        out.append("Some control names came through masked. The real page text "
                   "differs from what is printed here, so match on the part "
                   "that is not masked.")
    dropped = report.get("dropped") or {}
    if isinstance(dropped, dict):
        if dropped.get("malformed"):
            out.append("%s arrived in a shape the recorder does not accept "
                       "and was thrown away. One or two is a page's own "
                       "scripts. A lot of them is worth asking about."
                       % _plural(dropped["malformed"], "event"))
        if dropped.get("off_host_request"):
            out.append("%s went somewhere other than the provider and were "
                       "counted, not described."
                       % _plural(dropped["off_host_request"], "request"))
    if any((s.get("effect") or {}).get("printed") for s in steps):
        out.append("A step made the page call window.print(). The receipt "
                   "here is printed, not downloaded, so render it with CDP "
                   "printToPDF and never press the site's own Print button. "
                   "Note which control did it.")
    if not reqs and steps:
        out.append("No JSON or PDF came back from the provider on any step, so "
                   "this site is likely rendered on the server. Read the page, "
                   "do not look for an API.")
    return out


# -- printing ------------------------------------------------------------------

def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _wrap(text: str, width: int = 74, indent: str = "  ") -> list:
    words, line, out = text.split(), "", []
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            out.append(indent + line)
            line = w
        else:
            line = (line + " " + w) if line else w
    if line:
        out.append(indent + line)
    return out


def outline(structure) -> list:
    """A step's page shape as an indented outline, one element a line.

    Everything in a shape is a word off the recorder's lists, a count or
    a yes or no, so this prints it all. The control that was pressed is
    marked with an arrow, so the path down to it and the neighbors at
    each level read the way a selector gets written."""
    if not isinstance(structure, dict) or not isinstance(
            structure.get("root"), dict):
        return []
    lines = []

    def walk(node, depth):
        bits = [str(node.get("tag") or "other")]
        if node.get("role"):
            bits.append("role=%s" % node["role"])
        if node.get("attrs"):
            bits.append("[%s]" % " ".join(str(a) for a in node["attrs"]))
        if node.get("data_other"):
            bits.append("+%d data-*" % node["data_other"])
        if node.get("other_attrs"):
            bits.append("+%d other" % node["other_attrs"])
        bits.append("%d child%s" % (node.get("child_count", 0),
                                    "" if node.get("child_count") == 1
                                    else "ren"))
        if node.get("shadow"):
            bits.append("shadow root")
        if node.get("text"):
            bits.append("has text")
        if not node.get("visible"):
            bits.append("hidden")
        mark = "-> " if node.get("target") else "   "
        lines.append("%s%s%s" % (mark, "  " * depth, " ".join(bits)))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, depth + 1)
        if node.get("more"):
            lines.append("   %s... %d more not shown" % ("  " * (depth + 1),
                                                         node["more"]))

    walk(structure["root"], 0)
    if structure.get("truncated"):
        lines.append("   (cut short at %s elements, the page had more)"
                     % structure.get("nodes", "?"))
    return lines


def render(report: dict) -> str:
    steps, reqs = steps_of(report), requests_of(report)
    by_step = {}
    for r in reqs:
        by_step.setdefault(r.get("step"), []).append(r)

    L = []
    L.append("%s, recorded %s" % (report.get("provider") or "an unnamed provider",
                                  report.get("recorded_at") or "at an unknown time"))
    L.append("%d step(s), %d provider request(s)" % (len(steps), len(reqs)))
    L.append("")

    L.append("WHAT THE PERSON DID")
    L.append("")
    if not steps:
        L.append("  Nothing was recorded.")
    for s in steps:
        L.append("  %3s  %s" % (s.get("i", ""), describe(s)))
        for e in effects(s):
            L.append("       %s" % e)
    L.append("")

    if reqs:
        L.append("WHAT THE SITE ANSWERED")
        L.append("")
        for i in sorted(by_step, key=lambda k: -1 if not isinstance(k, int) else k):
            for r in by_step[i]:
                L.append("  step %s  %s %s  ->  %s" % (
                    "?" if not isinstance(i, int) else i,
                    r.get("method") or "GET", r.get("url") or "",
                    r.get("status")))
                if r.get("query"):
                    L.append("          query  %s" % r["query"])
                if r.get("post_keys"):
                    L.append("          sent   %s" % ", ".join(r["post_keys"]))
                if r.get("shape"):
                    L.append("          shape  %s" % json.dumps(r["shape"]))
        L.append("")

    if steps:
        L.append("LINES TO START THE SITE LAYER FROM")
        L.append("")
        for s in steps:
            L.append("  %s" % step_code(s))
        L.append("")

    shaped = [s for s in steps if isinstance(s, dict) and s.get("structure")]
    if shaped:
        L.append("THE PAGE AROUND EACH STEP")
        L.append("")
        L.append("  Element kinds, attribute names and counts only, never a")
        L.append("  word or a value. The arrow is the control that was used.")
        L.append("")
        for s in shaped:
            L.append("  step %s  %s" % (s.get("i", "?"), describe(s)))
            L.extend("  " + line for line in outline(s["structure"]))
            L.append("")

    told = notes(report)
    if told:
        L.append("WORTH KNOWING BEFORE YOU WRITE IT")
        L.append("")
        for n in told:
            L.extend(_wrap(n))
            L.append("")

    worry = concerns(report)
    L.append("READ THESE BEFORE THE FILE GOES ANYWHERE PUBLIC")
    L.append("")
    if worry:
        L.append("  Each line below quotes what it found, so that you can go")
        L.append("  and look at it. That makes this section the one part of")
        L.append("  this output that must not be pasted anywhere.")
        L.append("")
        for w in worry:
            L.extend(_wrap(w))
            L.append("")
    else:
        L.append("  Nothing here matched the three things redaction is known")
        L.append("  not to catch. That is not the same as the file being")
        L.append("  clean, so read it through yourself as well.")
        L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    try:
        report = load(argv[0])
    except ValueError as e:
        print("%s" % e)
        return 1
    text = render(report)
    try:
        print(text)
    except UnicodeEncodeError:
        # An old Windows console cannot print what a provider named a button.
        sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
