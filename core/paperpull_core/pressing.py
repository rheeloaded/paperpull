"""A press lands on the control, or nothing is pressed and the run stops.

Playwright's force=True turns off its checks before a press, the check that
the element itself would receive the press among them, and then presses the
middle of the element whatever is drawn over it. On a tester's American
Express statements page a chat bubble sat in the lower right corner, over
part of the last Download button that showed. The forced press opened the
chat. Later presses landed on the chat's suggested replies and opened a
window to dispute a charge, and a live agent joined. The run went on from
document to document, pressing again each time.

So a press here takes three steps, and stops the run rather than guess.

  1. The control is brought to the middle of the window, so a bubble or a
     bar pinned to an edge of the window is no longer over it.
  2. The topmost element at the point Playwright will press is read, and it
     has to be the control or something inside it. "The control" is what
     Playwright itself checks against, the element, or the button or link
     around it when there is one. Anything else on top, and nothing is
     pressed. A radio button or a checkbox hidden under its own label is
     pressed through that label, since pressing a label is pressing the
     control it names.
  3. Playwright presses, unforced, so its own check runs once more at the
     moment of the press.

When something covers the control, the run stops with Covered. When the
control could not be read, it stops with Unread, and when Playwright could
not make the press, with NotPressed. A press that brought nothing it should
stops the run with NoAnswer, which the app raises itself. Each is a Stop,
and a Stop is a SystemExit, so no `except Exception` between the press and
the app's main() takes it for an ordinary failure and goes on to the next
document. The app's main() writes the failure file and says why.

Both reads run in a world of this module's own inside the page, made over
the DevTools protocol, the way Playwright keeps a world of its own for its
checks. American Express replaces the page's eval, so page.evaluate and
locator.evaluate fail there, and a world of one's own reads the same
elements without running any of the page's own scripts. Chromium hands the
same world back each time it is asked for one by the same name, until the
page loads a new document.

The control is found in that world by a CSS selector the caller gives and
by the box Playwright reports for its locator. Both have to agree on
exactly one element, so the element read is the element Playwright
presses.

What covered a control is said only through the word list in
paperpull_core.words, never as the page wrote it.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

from .words import shape

log = logging.getLogger("paperpull.pressing")

# The name of this module's own world in a page.
WORLD = "paperpull-press"

# Selectors that find a control by its kind, for a caller whose locator
# finds it by its role. The box picks the one element among them.
BUTTONS = ("button, [role=button], input[type=button], input[type=submit], "
           "input[type=reset], input[type=image], summary")
LINKS = "a[href], [role=link], area[href]"

# How long Playwright is given to make a press once nothing covers it.
PRESS_MS = 8000


class Stop(SystemExit):
    """The run stops at this press.

    `step` and `reason` are this program's own words for the failure file,
    lowercase letters and spaces. `lines` are what the run says, the first
    of them the reason. `facts` go into the failure file as they are, so
    they hold only our own words, counts, yes or no, and words that went
    through the word list."""

    def __init__(self, step: str, reason: str, lines: Iterable[str], facts: Optional[dict] = None):
        super().__init__(0)
        self.step = step
        self.reason = reason
        self.lines = [str(line) for line in lines]
        self.facts = dict(facts or {})


class Covered(Stop):
    """Something on the page sits over the control, so it was not pressed."""


class Unread(Stop):
    """The control could not be read, so it was not pressed."""


class NotPressed(Stop):
    """Playwright did not make the press."""


class NoAnswer(Stop):
    """A press was made and what it should bring did not come."""


AGAIN = "Look at the browser window, then press Resume here, or run this again."


def no_answer(step: str, reason: str, said: str) -> NoAnswer:
    """A press that brought nothing, `said` in the app's own words, as a
    stop that presses nothing more."""
    return NoAnswer(step, reason, [
        said,
        "Nothing more was pressed. Pressing it again could do something other "
        "than it did the first time, so the run stops here.",
        AGAIN])


def stop_run(app, stop: Stop) -> None:
    """Stop the run at a press, from the app's main().

    `app` is the run, with its progress, its stats and its write_failure,
    which takes extra=. Progress is saved, the reason is said, the failure
    file is written while the page still shows what stopped the run, and
    the run leaves on SystemExit with the stop in flight, which is what the
    core reports as a run that stopped, never one that finished clean
    (run_reporting.stopped_early). Diagnose and record download nothing and
    write no failure file."""
    try:
        app.progress.save(backup=True)
    except Exception:
        pass
    print()
    for i, line in enumerate(stop.lines):
        print(("!! " if i == 0 else "   ") + line)
    if (getattr(app, "stats", None) or {}).get("mode") not in ("diagnose", "record"):
        app.write_failure(stop.step, stop.reason, extra=stop.facts)
    raise SystemExit(0)


# ---------------------------------------------------------------------------
# What sits on top of a control
# ---------------------------------------------------------------------------

# Runs in this module's own world. Returns a state, "inside", "label",
# "covered" or "unread", and nothing from the page but what describes a
# covering element, which is shaped before anything else sees it.
LOOK_JS = r"""(args) => {
  const near = (a, b) => Math.abs(a - b) <= 1;
  const parentOrHost = (e) => e.parentElement ||
    (e.parentNode && e.parentNode.nodeType === 11 ? e.parentNode.host : null);
  const rootOf = (e) => {
    let n = e;
    while (n.parentNode) n = n.parentNode;
    return (n.nodeType === 11 || n.nodeType === 9) ? n : null;
  };

  // The control, by the caller's selector, through every open shadow root,
  // and by the box Playwright reported for its locator.
  const found = new Set();
  const visit = (root) => {
    for (const e of root.querySelectorAll(args.css)) found.add(e);
    for (const e of root.querySelectorAll('*')) if (e.shadowRoot) visit(e.shadowRoot);
  };
  try { visit(document); } catch (e) { return {state: 'unread', why: 'selector'}; }
  const b = args.box;
  const same = [...found].filter((e) => {
    const r = e.getBoundingClientRect();
    return near(r.left, b.x) && near(r.top, b.y) && near(r.width, b.width) && near(r.height, b.height);
  });
  if (same.length !== 1)
    return {state: 'unread', why: same.length ? 'several' : 'none', matched: found.size};
  const el = same[0];

  // 1. To the middle of the window, at once rather than smoothly, so what
  // is read next is where it ends up.
  el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});

  // 2. The point Playwright presses, the middle of the first of the
  // element's boxes that shows in the window, cut to the window, to a
  // hundredth of a pixel (Playwright's _clickablePoint and roundPoint).
  const W = innerWidth, H = innerHeight;
  const clamp = (v, hi) => Math.min(Math.max(v, 0), hi);
  let point = null;
  for (const r of el.getClientRects()) {
    const x1 = clamp(r.left, W), x2 = clamp(r.right, W);
    const y1 = clamp(r.top, H), y2 = clamp(r.bottom, H);
    if ((x2 - x1) * (y2 - y1) > 0.99) { point = {x: (x1 + x2) / 2, y: (y1 + y2) / 2}; break; }
  }
  if (!point) return {state: 'unread', why: 'outside the window'};
  point = {x: Math.trunc(point.x * 100) / 100, y: Math.trunc(point.y * 100) / 100};
  const rect = el.getBoundingClientRect();
  const where = {point: point, window: {width: W, height: H},
                 rect: {x: rect.left, y: rect.top, width: rect.width, height: rect.height}};

  // 3. The control as Playwright checks it, the button or link around the
  // element when there is one (retarget), and the topmost element at the
  // point, read root by root through shadow roots the way Playwright reads
  // it before a press (expectHitTarget).
  const target = (el.matches('input, textarea, select') || el.isContentEditable) ? el
    : (el.closest('button, [role=button], a, [role=link]') || el);
  const roots = [];
  for (let p = target; p;) {
    const root = rootOf(p);
    if (!root) break;
    roots.push(root);
    if (root.nodeType === 9) break;
    p = root.host;
  }
  let hit = null;
  for (let i = roots.length - 1; i >= 0; i--) {
    const root = roots[i];
    const all = root.elementsFromPoint(point.x, point.y);
    const single = root.elementFromPoint(point.x, point.y);
    if (single && all[0] && parentOrHost(single) === all[0]) {
      const st = getComputedStyle(single);
      if (st && st.display === 'contents') all.unshift(single);
    }
    if (all[0] && all[0].shadowRoot === root && all[1] === single) all.shift();
    const inner = all[0];
    if (!inner) break;
    hit = inner;
    if (i && inner !== roots[i - 1].host) break;
  }
  if (!hit) return Object.assign({state: 'unread', why: 'nothing at the point'}, where);
  const chain = [];
  let h = hit;
  while (h && h !== target) { chain.push(h); h = h.assignedSlot || parentOrHost(h); }
  if (h === target) return Object.assign({state: 'inside'}, where);

  // A form control under its own label is pressed through the label.
  if (args.labels && target.labels) {
    for (const label of target.labels) {
      if (chain.includes(label))
        return Object.assign({state: 'label', wraps: label.contains(target)}, where);
    }
  }

  // Covered. What is on top, and the widget it belongs to, the outermost
  // element over the point that is not around the control.
  let widget = chain[0];
  for (let t = target; t; t = parentOrHost(t)) {
    const k = chain.indexOf(t);
    if (k !== -1) { widget = chain[Math.max(k - 1, 0)]; break; }
  }
  const upto = chain.indexOf(widget);
  const pinned = chain.slice(0, upto + 1).some((e) => {
    const st = getComputedStyle(e);
    return !!st && (st.position === 'fixed' || st.position === 'sticky');
  });
  const describe = (e) => ({
    tag: e.localName || '',
    role: e.getAttribute('role') || '',
    label: (e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('alt') ||
            (e.innerText || e.textContent || '')).trim().slice(0, 80),
  });
  return Object.assign({state: 'covered', top: describe(chain[0]), widget: describe(widget),
                        pinned: pinned, same: widget === chain[0]}, where);
}"""


def _in_own_world(page, args: dict) -> Optional[dict]:
    """LOOK_JS's answer, run in this module's own world in the page's main
    frame, or None when the page could not be asked."""
    from .failure import error_kind
    session = None
    try:
        session = page.context.new_cdp_session(page)
        frame = session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        world = session.send("Page.createIsolatedWorld", {"frameId": frame, "worldName": WORLD})
        answer = session.send("Runtime.evaluate", {
            "expression": "(%s)(%s)" % (LOOK_JS, json.dumps(args)),
            "contextId": world["executionContextId"],
            "returnByValue": True})
    except Exception as e:
        log.info("the page could not be asked what covers a control (%s)", error_kind(e))
        return None
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass
    if not isinstance(answer, dict) or answer.get("exceptionDetails"):
        log.info("the page could not be asked what covers a control (it raised)")
        return None
    value = (answer.get("result") or {}).get("value")
    return value if isinstance(value, dict) else None


def look(page, locator, css: str, labels: bool = False) -> dict:
    """What sits on top of the control once it is in the middle of the
    window, as a dict whose "state" is "inside", "label", "covered" or
    "unread". Raw words from the page are in it, so it goes through
    described() before it is said or kept anywhere.

    The box is read again when the page did not show exactly one element of
    `css` in it, since a page can move between two reads. Nothing has been
    scrolled or pressed then."""
    seen = {"state": "unread", "why": "no box"}
    for _ in range(3):
        try:
            box = locator.bounding_box(timeout=5000)
        except Exception:
            box = None
        if not box:
            return {"state": "unread", "why": "no box"}
        seen = _in_own_world(page, {"css": css, "box": box, "labels": bool(labels)})
        if seen is None:
            return {"state": "unread", "why": "not read"}
        if seen.get("state") != "unread" or seen.get("why") not in ("none", "several"):
            return seen
    return seen


def described(seen: dict, words) -> dict:
    """What covered a control, every word of the page's written through
    the word list, so only words on it stay and any other is its shape."""
    out = {}
    for part in ("widget", "top"):
        raw = seen.get(part) if isinstance(seen.get(part), dict) else {}
        out[part] = {key: shape(str(raw.get(key) or "")[:80], words)
                     for key in ("tag", "role", "label")}
    out["pinned"] = bool(seen.get("pinned"))
    out["same"] = bool(seen.get("same"))
    return out


def _sentence(part: dict) -> str:
    """One shaped element as words, a div element with the role button
    labeled "aaaa with us", or "an element" when nothing about it could be
    said."""
    tag = part.get("tag") or ""
    said = (("an " if tag[:1] in "aeiou" else "a ") + tag + " element") if tag else "an element"
    if part.get("role") and part.get("role") != tag:
        said += " with the role %s" % part["role"]
    if part.get("label"):
        said += ' labeled "%s"' % part["label"][:60]
    return said


def covering_lines(what: str, cover: dict) -> list:
    """What the run says when something covers `what`, built only from our
    own words and the shaped description."""
    on_top = "On top of it is %s" % _sentence(cover.get("widget") or {})
    if not cover.get("same"):
        on_top += ", where %s is the topmost part" % _sentence(cover.get("top") or {})
    if cover.get("pinned"):
        on_top += ", and it stays in place as the page scrolls"
    return [
        "Something on the page covers %s, so nothing was pressed." % what,
        on_top + ".",
        "A chat window, an offer or a banner is the usual thing. Close it in the "
        "browser window yourself, then press Resume here, or run this again.",
    ]


# Why a control could not be read, in the words of LOOK_JS and look.
_WHY = frozenset(("selector", "several", "none", "no box", "not read", "unknown state",
                  "outside the window", "nothing at the point"))


def judge(seen: dict, what: str, words, step: str = "press a control") -> None:
    """Raise Covered or Unread unless the control itself, or its own label,
    is what is on top."""
    state = seen.get("state")
    if state in ("inside", "label"):
        return
    if state == "covered":
        cover = described(seen, words)
        log.info("refused to press %s, %s", what, covering_lines(what, cover)[1])
        raise Covered(step, "something on the page is over the control",
                      covering_lines(what, cover),
                      {"over_it": cover["widget"], "topmost": cover["top"],
                       "fixed": cover["pinned"]})
    why = str(seen.get("why") or "")
    why = why if why in _WHY else "other"
    log.info("refused to press %s, it could not be read (%s)", what, why)
    raise Unread(step, "the control could not be checked", [
        "%s could not be checked for anything covering it, so nothing was "
        "pressed." % (what[:1].upper() + what[1:]),
        AGAIN], {"why": why})


def _press(action, what: str, step: str) -> None:
    """Playwright's own unforced press. Any error from it means the press
    may not have been made, so the run stops rather than press again."""
    from .failure import error_kind
    try:
        action()
    except Exception as e:
        kind = error_kind(e)
        log.info("the press on %s did not go through (%s)", what, kind)
        raise NotPressed(step, "the press did not go through", [
            "Pressing %s did not go through, so nothing more is pressed." % what,
            AGAIN], {"error": kind})


def click(page, locator, *, css: str, what: str, words, step: str = "press a control",
          timeout: int = PRESS_MS) -> None:
    """Press `locator` once, with nothing on top of it, or stop the run.

    `css` is a selector the control matches, which with the locator's box
    finds it in this module's own world. `what` names it in the run's own
    words, "the Download button for the statement of 2026-01-27". `words`
    is the app's word list, words_for(provider, site)."""
    seen = look(page, locator, css)
    judge(seen, what, words, step)
    _press(lambda: locator.click(timeout=timeout, no_wait_after=True), what, step)


def _is_checked(locator) -> Optional[bool]:
    try:
        return bool(locator.is_checked(timeout=3000))
    except Exception:
        return None


def _quoted(text: str) -> str:
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def _own_label(page, locator, wraps: bool):
    """The label a form control is pressed through, found by Playwright,
    the one around it or the one naming its id."""
    if wraps:
        return locator.locator("xpath=ancestor::label[1]")
    try:
        ident = locator.get_attribute("id", timeout=3000) or ""
    except Exception:
        ident = ""
    if not ident:
        return None
    return page.locator("label[for=%s]" % _quoted(ident)).first


def _visible_label(page, locator):
    """For a form control with no box of its own, a label of its own that
    shows, or None."""
    for wraps in (True, False):
        label = _own_label(page, locator, wraps)
        if label is None:
            continue
        try:
            if label.count() and label.first.is_visible():
                return label.first
        except Exception:
            continue
    return None


def check(page, locator, *, css: str, what: str, words, step: str = "choose an option",
          timeout: int = PRESS_MS) -> None:
    """Check a radio button or a checkbox once, or stop the run.

    Nothing is pressed when it is checked already, or when whether it is
    could not be read, since pressing a checkbox that is checked unchecks
    it. A control that shows is checked by Playwright when nothing covers
    it, and through its own label when that label is what sits over it. A
    control that does not show at all is checked through a label of its own
    that does. Either way it has to read as checked afterwards."""
    state = _is_checked(locator)
    if state is None:
        judge({"state": "unread", "why": "unknown state"}, what, words, step)
    if state:
        return
    try:
        has_box = bool(locator.bounding_box(timeout=5000))
    except Exception:
        has_box = False
    if has_box:
        seen = look(page, locator, css, labels=True)
        judge(seen, what, words, step)
        if seen.get("state") == "inside":
            _press(lambda: locator.check(timeout=timeout), what, step)
        else:
            label = _own_label(page, locator, bool(seen.get("wraps")))
            if label is None:
                judge({"state": "unread", "why": "none"}, what, words, step)
            click(page, label, css="label", what="the label of %s" % what,
                  words=words, step=step, timeout=timeout)
    else:
        label = _visible_label(page, locator)
        if label is None:
            judge({"state": "unread", "why": "no box"}, what, words, step)
        click(page, label, css="label", what="the label of %s" % what,
              words=words, step=step, timeout=timeout)
    if not _is_checked(locator):
        log.info("%s did not read as checked after it was pressed", what)
        raise NoAnswer(step, "the option did not take", [
            "%s was pressed and did not read as chosen afterwards, so nothing more "
            "is pressed." % (what[:1].upper() + what[1:]),
            AGAIN])
