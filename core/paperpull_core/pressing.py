"""A press is made only when the control is the thing on top, and when
anything else is over it the run stops.

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
  3. Playwright presses, unforced, and its own check runs once more at the
     moment of the press. An element of the page that has come over the
     control by then does not get the press. Playwright waits and tries
     again, and the run stops only if it is still there when the press's
     time runs out. Playwright's check cannot see into a frame, so a frame
     of its own, a chat window drawn in one say, that comes over the
     control at that moment can still get the press. So the point is read
     once more right after the press, and a frame on top there stops the
     run, with the press perhaps gone to it, unless it was at the point
     before the press and the control has left the point since.

When something covers the control, the run stops with Covered. When the
control could not be read, it stops with Unread, and when Playwright could
not make the press, with NotPressed. A control that shows with nothing over
it and that the page keeps turned off for as long as Playwright waits for
it is not pressed, and nothing is, with TurnedOff, a NotPressed that an app
catches where it presses a document's own control, to leave that document
for review and the next run and go on. A press that brought nothing it should
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

A control inside a frame is read the same way in a world of this module's
own inside that frame, by the box Playwright reports carried into the
frame's own coordinates. Then the frame has to be the thing on top in the
document around it at the point to be pressed, and that document's frame
in its own, up to the page's main frame, as Playwright checks a frame
before its own press. Anything on top of a frame covers the control inside
it. Right after the press, unless the control heard the browser's own click
at the point pressed, anything on top of a frame there stops the run, since
Playwright watches for its press only in the control's own document. A
frame that cannot be placed on the page, or one drawn at another size than
its own window, stops the run unread. In a frame drawn by a process of its
own, or a frame inside one, the point read is the one Playwright's press
lands on, which is off the middle by the frame's border and padding.

What covered a control is said only through the word list in
paperpull_core.words, never as the page wrote it.

Some apps press with Playwright's own click and, when it raises, press the
element once more through the page, el.click() run inside it. That press
goes to the element whatever is drawn over it, a hidden one included, and
when Playwright's press had already reached the page before it raised,
it is a second press. press_once makes both presses for them. The one
through the page is made only when Playwright says nothing covered the
control, its press never reached it and nothing it should bring came, the
control still has its words and the app's own guard still passes them,
and it is the thing on top in the middle of the window. When any of that
cannot be told, nothing is pressed and the run stops, and a control the
page took away meanwhile is not pressed at all. It is never made twice,
and when it raises, nothing more is pressed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
from typing import Callable, Iterable, NamedTuple, Optional

from .words import shape, shape_label

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
    through the word list. `after_a_press` is true for a stop that came once
    a press had been tried, which may have reached the page or something
    on it, so nothing may take it for a refusal made before any press.

    `list_unread` is true for a stop of a list read again while the
    documents were taken, a list that would not read or no longer holds the
    document once. Every later document would read the same list, and a
    Resume reads no list of its own, so Continue would stop at the same
    place again (#124). stop_run notes the listing as one that stopped,
    says to run Pilot or Run All, which read the list first, and leaves on
    ListNotRead, so the panel offers that rather than Continue. Its lines
    say nothing of Resume or of running this again."""

    def __init__(self, step: str, reason: str, lines: Iterable[str], facts: Optional[dict] = None,
                 after_a_press: bool = False, list_unread: bool = False):
        lines = [str(line) for line in lines]
        # What a stop no main() takes says on its way out. The app's own
        # main() catches it and stops the run through stop_run, with
        # SystemExit(0), or ListNotRead for a stop made with list_unread.
        super().__init__(lines[0] if lines else reason)
        self.step = step
        self.reason = reason
        self.lines = lines
        self.facts = dict(facts or {})
        self.after_a_press = bool(after_a_press)
        self.list_unread = bool(list_unread)


class Covered(Stop):
    """Something on the page sits over the control, so it was not pressed."""


class Unread(Stop):
    """The control could not be read, so it was not pressed."""


class NotPressed(Stop):
    """Playwright did not make the press."""


class TurnedOff(NotPressed):
    """The control shows with nothing over it and the page has turned it
    off, so it was not pressed, and nothing was. The apps find a document's
    control by its role and its name, which finds a turned off one too, and
    a site can turn off the Download of one document it will not hand over
    yet. An app catches this where it presses a document's own control and
    leaves that document for review and the next run, so one such document
    does not stop every run at the same place. Uncaught, it stops the run
    like any NotPressed."""


class NoAnswer(Stop):
    """A press was made and what it should bring did not come."""


class Unsure(Stop):
    """A press raised, and whether it reached the page could not be told,
    so it was not made again."""


class Changed(Stop):
    """The control was no longer the one that was checked, so it was not
    pressed again."""


AGAIN = "Look at the browser window, then press Resume here, or run this again."


def no_answer(step: str, reason: str, said: str) -> NoAnswer:
    """A press that brought nothing, `said` in the app's own words, as a
    stop that presses nothing more."""
    return NoAnswer(step, reason, [
        said,
        "Nothing more was pressed. Pressing it again could do something other "
        "than it did the first time, so the run stops here.",
        AGAIN], after_a_press=True)


def say(stop: Stop) -> None:
    """A stop's own words on the console, the first line marked."""
    print()
    for i, line in enumerate(stop.lines):
        print(("!! " if i == 0 else "   ") + line)


def stop_run(app, stop: Stop) -> None:
    """Stop the run at a press, from the app's main().

    `app` is the run, with its progress, its stats and its write_failure,
    which takes extra=. Progress is saved, the reason is said, the failure
    file is written while the page still shows what stopped the run, and
    the run leaves on SystemExit with the stop in flight, which is what the
    core reports as a run that stopped, never one that finished clean
    (run_reporting.stopped_early). Diagnose and record download nothing and
    write no failure file.

    Diagnose writes its survey here instead. A stop out of Diagnose, at a
    page it could not open, skipped the survey main() writes after it, so
    the one command a tester runs to name the controls wrote nothing at
    all (#27). The survey is of the page the window shows, and an app
    whose write_survey takes `stopped` has it say why Diagnose stopped.

    An app writes one failure file a run, and a run that wrote one for an
    earlier document would write nothing for the stop. The stop is what a
    tester has to send, so it writes a file of its own all the same, the
    newest in the folder, and the run says where.

    A stop made with list_unread leaves the list unread, as
    listing.read_again_stopped does. The listing is noted as one that
    stopped before anything else, so nothing that goes wrong after can
    leave it noted whole, the run says which run reads the list first, and
    it leaves on ListNotRead. Diagnose and record list nothing a download
    reads, so for them it is a stop like any other."""
    stats = getattr(app, "stats", None)
    mode = stats.get("mode") if isinstance(stats, dict) else None
    unread = stop.list_unread and mode not in ("diagnose", "record")
    if unread:
        from . import listing
        listing.started(app)
    try:
        app.progress.save(backup=True)
    except Exception:
        pass
    say(stop)
    leave = listing.say_unread(app) if unread else SystemExit(0)
    if mode == "diagnose":
        write_survey = getattr(app, "write_survey", None)
        if callable(write_survey):
            try:
                import inspect
                if "stopped" in inspect.signature(write_survey).parameters:
                    write_survey(stopped=stop)
                else:
                    write_survey()
            except Exception:
                pass
    elif mode != "record":
        if isinstance(stats, dict):
            stats.pop("failure_files", None)
        app.write_failure(stop.step, stop.reason, extra=stop.facts)
    raise leave


# ---------------------------------------------------------------------------
# What sits on top of a control
# ---------------------------------------------------------------------------

# What both reads of what sits on top of something share, the read of a
# control and the read of the frame it is in.
#
# topAt is the topmost element at a point, read root by root through the
# shadow roots around `target` the way Playwright reads it before a press
# (expectHitTarget). chainOf is every element from that one up to `target`,
# and whether `target` was reached, so the point is on it or inside it.
# coverOf says what covers `target`, the topmost element and the widget it
# belongs to, the outermost element over the point that is not around
# `target`.
_ON_TOP_JS = r"""const FRAMES = new Set(['iframe', 'frame', 'object', 'embed']);
  const parentOrHost = (e) => e.parentElement ||
    (e.parentNode && e.parentNode.nodeType === 11 ? e.parentNode.host : null);
  const rootOf = (e) => {
    let n = e;
    while (n.parentNode) n = n.parentNode;
    return (n.nodeType === 11 || n.nodeType === 9) ? n : null;
  };
  const topAt = (target, point) => {
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
    return hit;
  };
  const chainOf = (hit, target) => {
    const chain = [];
    let h = hit;
    while (h && h !== target) { chain.push(h); h = h.assignedSlot || parentOrHost(h); }
    return {chain: chain, reached: h === target};
  };
  const describe = (e) => ({
    tag: e.localName || '',
    role: e.getAttribute('role') || '',
    label: (e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('alt') ||
            (e.innerText || e.textContent || '')).trim().slice(0, 80),
  });
  const coverOf = (target, chain) => {
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
    return {state: 'covered', top: describe(chain[0]), widget: describe(widget),
            pinned: pinned, same: widget === chain[0]};
  };"""

# Runs in this module's own world. Returns a state, "inside", "label",
# "covered" or "unread", and nothing from the page but what describes a
# covering element, which is shaped before anything else sees it.
LOOK_JS = r"""(args) => {
  %s
  const near = (a, b) => Math.abs(a - b) <= 1;

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
  try { el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'}); }
  catch (e) { el.scrollIntoView({block: 'center', inline: 'center'}); }

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

  // In a frame drawn by a process of its own, or a frame inside one,
  // Playwright carries its point across from where that frame's element
  // begins, its border included, rather than from its window, so its press
  // lands args.shift away from the middle. That is the point read, and it
  // has to fall on the control.
  if (args.shift) {
    point = {x: point.x + args.shift.x, y: point.y + args.shift.y};
    where.point = point;
    const on = [...target.getClientRects()].some((r) =>
      point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom);
    if (!on) return Object.assign({state: 'unread', why: 'off the control'}, where);
  }
  const hit = topAt(target, point);
  if (!hit) return Object.assign({state: 'unread', why: 'nothing at the point'}, where);
  const {chain, reached} = chainOf(hit, target);

  // Every frame at the point before the press, on top or under it, and the
  // control itself, kept in this world for the read after the press
  // (AFTER_JS), so a frame that was already there and is on top only
  // because the control has left the point is told from one that came over
  // the control.
  const remember = () => {
    const frames = new Set(), roots = new Set();
    const walk = (root) => {
      if (roots.has(root)) return;
      roots.add(root);
      for (const e of root.elementsFromPoint(point.x, point.y)) {
        if (FRAMES.has(e.localName)) frames.add(e);
        if (e.shadowRoot) walk(e.shadowRoot);
      }
    };
    walk(document);
    globalThis.__paperpullBefore = {x: point.x, y: point.y, frames: frames, control: target};
    // For a control in a frame, an ear in this world at the frame's window,
    // ahead of the page's own listeners, for a click the browser itself sends
    // at the point to be pressed, along a path through the control or a label
    // of its own (HEARD_JS). A click anywhere else, the person's say, is not
    // the press. It takes itself away once args.ear milliseconds have passed,
    // or when a control is listened for again.
    if (args.ear) {
      if (typeof globalThis.__paperpullDeaf === 'function') globalThis.__paperpullDeaf();
      globalThis.__paperpullHeard = false;
      const own = new Set([target, ...(target.labels || [])]);
      const at = {x: point.x, y: point.y};
      const ear = (e) => {
        if (!e.isTrusted) return;
        if (Math.abs(e.clientX - at.x) > 2 || Math.abs(e.clientY - at.y) > 2) return;
        let path = [];
        try { path = e.composedPath(); } catch (x) {}
        if (path.some((n) => own.has(n))) globalThis.__paperpullHeard = true;
      };
      addEventListener('click', ear, true);
      const deaf = () => removeEventListener('click', ear, true);
      globalThis.__paperpullDeaf = deaf;
      setTimeout(deaf, args.ear);
    }
  };
  if (reached) { remember(); return Object.assign({state: 'inside'}, where); }

  // A control the page has turned off and drawn to take no pointer, the
  // way Bootstrap and Material UI draw one (pointer-events none), is passed
  // over at its own point, which then finds what holds it. Only for the read
  // of a turned off control (args.off) is what holds it no cover, and
  // nothing is pressed after that read. What an earlier look kept for the
  // read after a press is let go, so that read takes no frame for one that
  // was at this point before.
  if (args.off && getComputedStyle(el).pointerEvents === 'none') {
    for (let p = parentOrHost(el); p; p = parentOrHost(p))
      if (p === hit) {
        globalThis.__paperpullBefore = null;
        return Object.assign({state: 'inside'}, where);
      }
  }

  // A form control under its own label is pressed through the label.
  if (args.labels && target.labels) {
    for (const label of target.labels) {
      if (chain.includes(label)) {
        remember();
        return Object.assign({state: 'label', wraps: label.contains(target)}, where);
      }
    }
  }

  // Covered. What is on top, and the widget it belongs to.
  return Object.assign(coverOf(target, chain), where);
}""" % _ON_TOP_JS

# Runs in this module's own world right after a press, at the point LOOK_JS
# found, without scrolling. Playwright's own check at the press cannot see
# into a frame, so a frame that came over the control as it was pressed can
# have taken the press. A frame on top at the point is said to be covering
# it, unless it was at the point before the press and the control has left
# the point since, so that nothing at the point now is the control or
# inside it. A frame raised over a control still there covers it.
AFTER_JS = r"""(args) => {
  const FRAMES = new Set(['iframe', 'frame', 'object', 'embed']);
  const p = args.point;
  let top = document.elementFromPoint(p.x, p.y);
  while (top && top.shadowRoot) {
    const inner = top.shadowRoot.elementFromPoint(p.x, p.y);
    if (!inner || inner === top) break;
    top = inner;
  }
  if (!top || !FRAMES.has(top.localName)) return {state: 'clear'};
  const before = globalThis.__paperpullBefore;
  const stillThere = () => {
    const roots = new Set();
    const walk = (root) => {
      if (roots.has(root)) return false;
      roots.add(root);
      for (const e of root.elementsFromPoint(p.x, p.y)) {
        if (e === before.control || before.control.contains(e)) return true;
        if (e.shadowRoot && walk(e.shadowRoot)) return true;
      }
      return false;
    };
    return walk(document);
  };
  if (before && before.x === p.x && before.y === p.y && before.frames.has(top)
      && before.control && !stillThere())
    return {state: 'clear'};
  let pinned = false;
  for (let e = top; e; e = e.parentElement || (e.parentNode && e.parentNode.host) || null) {
    const st = getComputedStyle(e);
    if (st && (st.position === 'fixed' || st.position === 'sticky')) { pinned = true; break; }
  }
  const about = {
    tag: top.localName || '',
    role: top.getAttribute('role') || '',
    label: (top.getAttribute('aria-label') || top.getAttribute('title') || '').trim().slice(0, 80),
  };
  return {state: 'covered', top: about, widget: about, pinned: pinned, same: true};
}"""

# Runs in this module's own world in the document that holds a frame, with
# the frame's own element there (`owner`, the iframe say) and the point
# being pressed in that document's own coordinates. The frame has to be the
# topmost element at the point, as Playwright checks it before a press
# (_checkFrameIsHitTarget), or what is on top covers the control inside it.
# The elements at the point and the frame's element are kept in this world
# for the read after the press (FRAME_AFTER_JS).
FRAME_JS = r"""(owner, args) => {
  %s
  const p = args.point;
  if (!owner || !owner.isConnected) return {state: 'unread', why: 'none'};
  const hit = topAt(owner, p);
  if (!hit) return {state: 'unread', why: 'nothing at the point'};
  const {chain, reached} = chainOf(hit, owner);
  if (!reached) return coverOf(owner, chain);
  const all = new Set(), roots = new Set();
  const walk = (root) => {
    if (roots.has(root)) return;
    roots.add(root);
    for (const e of root.elementsFromPoint(p.x, p.y)) {
      all.add(e);
      if (e.shadowRoot) walk(e.shadowRoot);
    }
  };
  walk(document);
  globalThis.__paperpullFrameBefore = {x: p.x, y: p.y, all: all, owner: owner};
  return {state: 'inside'};
}""" % _ON_TOP_JS

# The size of a frame's own window, read in its own world.
WINDOW_JS = r"""() => ({width: innerWidth, height: innerHeight})"""

# Whether the control LOOK_JS last read in this world heard a click the
# browser itself sent, read in the control's own frame after the press.
HEARD_JS = r"""() => ({heard: globalThis.__paperpullHeard === true})"""

# How long the ear of a control in a frame listens, longer than any press.
EAR_MS = 60000

# Runs in this module's own world in a document that holds the control's
# frame, right after a press the control did not hear (HEARD_JS), at the
# point FRAME_JS read, without scrolling. Playwright watches for the press
# only in the control's own document, and it takes a press that never came
# there for one that went through, so anything on top of the frame here can
# have taken it. So
# whatever is on top at the point stops the run unless it is the frame's
# own element, or it was at the point before the press and the frame has
# left the point since.
FRAME_AFTER_JS = r"""(owner, args) => {
  %s
  const p = args.point;
  let top = document.elementFromPoint(p.x, p.y);
  while (top && top.shadowRoot) {
    const inner = top.shadowRoot.elementFromPoint(p.x, p.y);
    if (!inner || inner === top) break;
    top = inner;
  }
  if (!top || top === owner) return {state: 'clear'};
  const before = globalThis.__paperpullFrameBefore;
  const stillThere = () => {
    const roots = new Set();
    const walk = (root) => {
      if (roots.has(root)) return false;
      roots.add(root);
      for (const e of root.elementsFromPoint(p.x, p.y)) {
        if (e === owner) return true;
        if (e.shadowRoot && walk(e.shadowRoot)) return true;
      }
      return false;
    };
    return walk(document);
  };
  if (before && before.x === p.x && before.y === p.y && before.owner === owner
      && before.all.has(top) && !stillThere())
    return {state: 'clear'};
  return coverOf(owner, chainOf(top, owner).chain);
}""" % _ON_TOP_JS


def _in_world(session, frame_id: str, js: str, args: dict, element=None) -> Optional[dict]:
    """What `js` answers, run in this module's own world in the frame
    `frame_id` that `session` reaches, or None when it could not be asked.
    With `element`, the backend node id of an element of that frame, `js`
    is handed the element first and `args` second."""
    from .failure import error_kind
    found = None
    try:
        world = session.send("Page.createIsolatedWorld",
                             {"frameId": frame_id, "worldName": WORLD})
        if element is None:
            answer = session.send("Runtime.evaluate", {
                "expression": "(%s)(%s)" % (js, json.dumps(args)),
                "contextId": world["executionContextId"],
                "returnByValue": True})
        else:
            found = session.send("DOM.resolveNode", {
                "backendNodeId": element,
                "executionContextId": world["executionContextId"]})["object"]["objectId"]
            answer = session.send("Runtime.callFunctionOn", {
                "functionDeclaration": js,
                "objectId": found,
                "arguments": [{"objectId": found}, {"value": args}],
                "returnByValue": True})
    except Exception as e:
        log.info("the page could not be asked what covers a control (%s)", error_kind(e))
        return None
    finally:
        if found is not None:
            try:
                session.send("Runtime.releaseObject", {"objectId": found})
            except Exception:
                pass
    if not isinstance(answer, dict) or answer.get("exceptionDetails"):
        log.info("the page could not be asked what covers a control (it raised)")
        return None
    value = (answer.get("result") or {}).get("value")
    return value if isinstance(value, dict) else None


def _in_own_world(page, js: str, args: dict) -> Optional[dict]:
    """What `js` answers, run in this module's own world in the page's main
    frame, or None when the page could not be asked."""
    from .failure import error_kind
    session = None
    try:
        session = page.context.new_cdp_session(page)
        frame = session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
    except Exception as e:
        log.info("the page could not be asked what covers a control (%s)", error_kind(e))
        _detach([session])
        return None
    try:
        return _in_world(session, frame, js, args)
    finally:
        _detach([session])


def _detach(sessions) -> None:
    for session in sessions:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# A control inside a frame
# ---------------------------------------------------------------------------

class _Level:
    """One frame on the way from a page's main frame down to a control's
    frame. `session` is the DevTools session that reaches it and `node` its
    entry in that session's frame tree. `owner` is the backend node id of
    its element in its parent, None for the main frame, and `own` is true
    for a frame drawn by a process of its own, which has a session of its
    own.

    Each session places what it draws from the top left of the window of
    the frame it began at, its root. `origin` is where this frame's window
    begins on the page's window, and `pw` where Playwright takes it to
    begin when it reports a box, which for a frame of its own is where the
    frame's element begins, its border included (crPage _framePosition).
    `root_origin` and `root_pw` are the same for the root of this frame's
    session, and `size` is the size its parent draws its window at."""

    def __init__(self, frame, session, node, owner=None, own=False):
        self.frame = frame
        self.session = session
        self.node = node
        self.owner = owner
        self.own = own
        self.origin = self.pw = self.root_origin = self.root_pw = (0.0, 0.0)
        self.size = None

    @property
    def id(self) -> str:
        return self.node["frame"]["id"]


def _address(frame_entry: dict) -> str:
    """A frame's address as Playwright says it, its fragment included."""
    return str(frame_entry.get("url") or "") + str(frame_entry.get("urlFragment") or "")


def _same_box(a, b: dict) -> bool:
    """Whether (x, y, width, height) and a box Playwright reports agree to
    a pixel."""
    try:
        return all(abs(float(u) - float(v)) <= 1 for u, v in zip(
            a, (b["x"], b["y"], b["width"], b["height"])))
    except (KeyError, TypeError, ValueError):
        return False


def _child_of(parent, child) -> Optional[dict]:
    """Which of the frames `parent`'s process draws inside it `child` is,
    as its entry in the frame tree. The one whose element sits where
    Playwright says the child's element does, and when several do, the one
    of those with the child's address and name. None unless that is
    exactly one. Where the element sits is what tells it, since a frame's
    own script can rename it, and a frame its parent wrote into keeps an
    address in Playwright that the frame tree no longer gives."""
    try:
        element = child.frame_element()
    except Exception:
        return None
    try:
        box = element.bounding_box()
    except Exception:
        box = None
    finally:
        try:
            element.dispose()
        except Exception:
            pass
    if not box:
        return None
    px, py = parent.root_pw
    found = []
    for node in parent.node.get("childFrames") or []:
        try:
            owner = parent.session.send("DOM.getFrameOwner", {"frameId": node["frame"]["id"]})
            model = parent.session.send("DOM.getBoxModel",
                                        {"backendNodeId": owner["backendNodeId"]})["model"]
        except Exception:
            continue
        border = _rectangle(model.get("border"))
        if border is not None and _same_box(
                (border[0] + px, border[1] + py, border[2], border[3]), box):
            found.append(node)
    if len(found) > 1:
        found = [n for n in found if _address(n["frame"]) == child.url
                 and str(n["frame"].get("name") or "") == (child.name or "")]
    return found[0] if len(found) == 1 else None


def _levels(page, frame, opened: list) -> Optional[list]:
    """Every frame from the page's main frame down to `frame`, as _Level,
    or None when any of them could not be told. A frame its parent's
    process draws is found among its parent's children by where its
    element sits (_child_of). Every session opened is put in `opened`, for
    the caller to detach."""
    chain = []
    f = frame
    try:
        while f is not None:
            chain.append(f)
            f = f.parent_frame
    except Exception:
        return None
    chain.reverse()
    if chain[0] != page.main_frame:
        return None
    session = page.context.new_cdp_session(page)
    opened.append(session)
    levels = [_Level(chain[0], session, session.send("Page.getFrameTree")["frameTree"])]
    for child in chain[1:]:
        parent = levels[-1]
        try:
            own = page.context.new_cdp_session(child)
        except Exception:
            # Playwright has a session only for a frame drawn by a process
            # of its own, and says so for any other.
            own = None
        if own is not None:
            opened.append(own)
            node = own.send("Page.getFrameTree")["frameTree"]
        else:
            # Where every frame so far sits, for where its children do.
            if not _place(levels):
                return None
            node = _child_of(parent, child)
            if node is None:
                return None
        owner = parent.session.send("DOM.getFrameOwner", {"frameId": node["frame"]["id"]})
        levels.append(_Level(child, own or parent.session, node, owner["backendNodeId"],
                             own is not None))
    return levels


def _rectangle(quad) -> Optional[tuple]:
    """A box the DevTools protocol gives as four corners, as (x, y, width,
    height), or None when it is not drawn square to the window, a frame
    turned or skewed, whose points cannot be carried across."""
    if not isinstance(quad, list) or len(quad) != 8:
        return None
    x1, y1, x2, y2, x3, y3, x4, y4 = (float(v) for v in quad)
    flat = (abs(y1 - y2) < 0.01 and abs(y3 - y4) < 0.01
            and abs(x1 - x4) < 0.01 and abs(x2 - x3) < 0.01)
    return (x1, y1, x2 - x1, y4 - y1) if flat and x2 > x1 and y4 > y1 else None


def _place(levels) -> bool:
    """Where each frame's window begins on the page's window, read now, the
    page's scrolling included. False when a frame's element could not be
    read or is not drawn square to the window."""
    for parent, level in zip(levels, levels[1:]):
        try:
            model = parent.session.send("DOM.getBoxModel", {"backendNodeId": level.owner})["model"]
        except Exception:
            return False
        content, border = _rectangle(model.get("content")), _rectangle(model.get("border"))
        if content is None or border is None:
            return False
        ox, oy = parent.root_origin
        px, py = parent.root_pw
        level.origin = (ox + content[0], oy + content[1])
        level.size = (content[2], content[3])
        if level.own:
            level.pw = (px + border[0], py + border[1])
            level.root_origin, level.root_pw = level.origin, level.pw
        else:
            level.pw = (px + content[0], py + content[1])
            level.root_origin, level.root_pw = parent.root_origin, parent.root_pw
    return True


def _drawn_as(level) -> bool:
    """Whether a frame's window is the size its parent draws it at, so
    that a point carries across between them. A frame scaled by its parent
    is not."""
    window = _in_world(level.session, level.id, WINDOW_JS, {})
    if level.size is None or not isinstance(window, dict):
        return False
    try:
        return (abs(float(window["width"]) - level.size[0]) <= 1
                and abs(float(window["height"]) - level.size[1]) <= 1)
    except (KeyError, TypeError, ValueError):
        return False


def _look_in_frame(page, locator, css: str, labels: bool, frame) -> dict:
    """look() for a control inside a frame. The control is read in the
    frame's own world as look reads one in the page's main frame, by the
    caller's selector and Playwright's box for it, which is carried into
    the frame's own coordinates, then brought to the middle of the window,
    which scrolls the frames around it too. Then each frame on the way up
    has to be the thing on top in its parent at the point that will be
    pressed, read in its parent's own world. What covers a frame covers
    the control. The points read in each parent go back with the answer as
    "frame_points", for after().

    The point is where Playwright's press will land. In a frame drawn by a
    process of its own, or a frame inside one, Playwright carries its point
    across from where that frame's element begins rather than its window,
    so the press lands off the middle by the frame's border and padding,
    and that point is the one read, in the frame and in each frame around
    it. An ear for the press is set on the control, and the ids of the
    frames found go back as "frame_ids", both for after()."""
    opened: list = []
    try:
        try:
            levels = _levels(page, frame, opened)
        except Exception:
            levels = None
        if not levels or not _place(levels):
            return {"state": "unread", "why": "frame"}
        if not all(_drawn_as(level) for level in levels[1:]):
            return {"state": "unread", "why": "frame drawn at another size"}
        mine = levels[-1]
        seen = {"state": "unread", "why": "no box"}
        for _ in range(3):
            box = _box(locator)
            if not box:
                return {"state": "unread", "why": "no box"}
            if not _place(levels):
                return {"state": "unread", "why": "frame"}
            inside = {"x": box["x"] - mine.pw[0], "y": box["y"] - mine.pw[1],
                      "width": box["width"], "height": box["height"]}
            args = {"css": css, "box": inside, "labels": bool(labels), "ear": EAR_MS}
            shift = (mine.pw[0] - mine.origin[0], mine.pw[1] - mine.origin[1])
            if shift != (0, 0):
                args["shift"] = {"x": shift[0], "y": shift[1]}
            seen = _in_world(mine.session, mine.id, LOOK_JS, args)
            if seen is None:
                return {"state": "unread", "why": "not read"}
            if seen.get("state") != "unread" or seen.get("why") not in ("none", "several"):
                break
        if seen.get("state") not in ("inside", "label"):
            return seen
        # Where the frame is once the control was brought to the middle.
        if not _place(levels):
            return {"state": "unread", "why": "frame"}
        point = seen.get("point") or {}
        try:
            x, y = float(point["x"]) + mine.origin[0], float(point["y"]) + mine.origin[1]
        except (KeyError, TypeError, ValueError):
            return {"state": "unread", "why": "not read"}
        points = []
        for parent, child in reversed(list(zip(levels, levels[1:]))):
            at = {"x": x - parent.origin[0], "y": y - parent.origin[1]}
            on = _in_world(parent.session, parent.id, FRAME_JS, {"point": at},
                           element=child.owner)
            if on is None:
                return {"state": "unread", "why": "not read"}
            if on.get("state") != "inside":
                return dict(on, over_the_frame=True)
            points.append(at)
        return dict(seen, frame_points=points,
                    frame_ids=[[level.id, level.owner, level.own] for level in levels])
    finally:
        _detach(opened)


def _levels_again(page, frame, ids, opened: list) -> Optional[list]:
    """The frames _look_in_frame found, from the page's main frame down to
    `frame`, reached again by the ids it kept ("frame_ids"), so that a
    frame hidden or turned since the look is still read where it was. None
    when the frames on the way are no longer the ones the look found."""
    chain = []
    f = frame
    while f is not None:
        chain.append(f)
        f = f.parent_frame
    chain.reverse()
    if not isinstance(ids, list) or len(ids) != len(chain) or chain[0] != page.main_frame:
        return None
    levels = []
    for f, (frame_id, owner, own) in zip(chain, ids):
        if not levels or own:
            session = page.context.new_cdp_session(f if levels else page)
            opened.append(session)
        else:
            session = levels[-1].session
        levels.append(_Level(f, session, {"frame": {"id": frame_id}}, owner, own))
    return levels


def _after_in_frame(page, seen: dict, frame) -> Optional[dict]:
    """after() for a control inside a frame. When the control heard the
    browser's own click at the point pressed, the press was the control's,
    and nothing that came over it afterwards, a loading cover say, took it.
    Otherwise what the point now shows in the control's own frame is read
    as for one in the page's main frame, and then in each frame around it,
    where anything on top of the frame stops the run. The frames are those
    the look found, by their ids, wherever they are drawn now. A cover as
    AFTER_JS or FRAME_AFTER_JS says it, or None."""
    opened: list = []
    try:
        try:
            levels = _levels_again(page, frame, seen.get("frame_ids"), opened)
        except Exception:
            levels = None
        if not levels:
            return None
        mine = levels[-1]
        heard = _in_world(mine.session, mine.id, HEARD_JS, {})
        if heard and heard.get("heard") is True:
            return None
        now = _in_world(mine.session, mine.id, AFTER_JS, {"point": seen.get("point")})
        if now and now.get("state") == "covered":
            return now
        ups = list(reversed(list(zip(levels, levels[1:]))))
        for (parent, child), at in zip(ups, seen.get("frame_points") or []):
            now = _in_world(parent.session, parent.id, FRAME_AFTER_JS, {"point": at},
                            element=child.owner)
            if now and now.get("state") == "covered":
                return dict(now, over_the_frame=True)
        return None
    finally:
        _detach(opened)


def _box(locator) -> Optional[dict]:
    """The box Playwright reports for a locator or an element handle, or
    None. A Locator takes a timeout and an ElementHandle does not, and
    asking one the other's way raises TypeError."""
    try:
        return locator.bounding_box(timeout=5000)
    except TypeError:
        pass
    except Exception:
        return None
    try:
        return locator.bounding_box()
    except Exception:
        return None


def look(page, locator, css: str, labels: bool = False, off: bool = False, frame=None) -> dict:
    """What sits on top of the control once it is in the middle of the
    window, as a dict whose "state" is "inside", "label", "covered" or
    "unread". Raw words from the page are in it, so it goes through
    described() before it is said or kept anywhere. `off` is for a control
    read as turned off, which nothing will press, and then what holds a
    control that takes no pointer is not taken for something over it.

    The box is read again when the page did not show exactly one element of
    `css` in it, since a page can move between two reads. Nothing has been
    scrolled or pressed then.

    `frame` is the Playwright frame the control is in, when that is not
    the page's main frame. The control is then read in that frame, and
    each frame around it has to be on top in its own parent at the point
    (_look_in_frame)."""
    if frame is not None and frame.parent_frame is not None:
        return _look_in_frame(page, locator, css, labels, frame)
    seen = {"state": "unread", "why": "no box"}
    for _ in range(3):
        box = _box(locator)
        if not box:
            return {"state": "unread", "why": "no box"}
        seen = _in_own_world(page, LOOK_JS, {"css": css, "box": box, "labels": bool(labels),
                                             "off": bool(off)})
        if seen is None:
            return {"state": "unread", "why": "not read"}
        if seen.get("state") != "unread" or seen.get("why") not in ("none", "several"):
            return seen
    return seen


def described(seen: dict, words) -> dict:
    """What covered a control, every word of the page's written through
    the word list, so only words on it stay and any other is its shape. Its
    label keeps only the words a name may keep, since an offer over the
    page can name a card in words that are all on the list (#103)."""
    out = {}
    for part in ("widget", "top"):
        raw = seen.get(part) if isinstance(seen.get(part), dict) else {}
        out[part] = {key: (shape_label if key == "label" else shape)(
            str(raw.get(key) or "")[:80], words) for key in ("tag", "role", "label")}
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


# Why a control could not be read, in the words of LOOK_JS, FRAME_JS and
# look. "frame" is a frame that could not be found or placed on the page,
# "frame drawn at another size" one drawn at another size than its own
# window, and "off the control" a press Playwright would land beside the
# control, in a frame drawn by a process of its own or a frame inside one.
# Every word of them is on paperpull_core.words's list, so they leave whole.
_WHY = frozenset(("selector", "several", "none", "no box", "not read", "unknown state",
                  "outside the window", "nothing at the point", "frame",
                  "frame drawn at another size", "off the control"))


def judge(seen: dict, what: str, words, step: str = "press a control") -> None:
    """Raise Covered or Unread unless the control itself, or its own label,
    is what is on top."""
    state = seen.get("state")
    if state in ("inside", "label"):
        return
    if state == "covered":
        cover = described(seen, words)
        log.info("refused to press %s, %s", what, covering_lines(what, cover)[1])
        facts = {"over_it": cover["widget"], "topmost": cover["top"], "fixed": cover["pinned"]}
        if seen.get("over_the_frame"):
            facts["over_the_frame"] = True
        raise Covered(step, "something on the page is over the control",
                      covering_lines(what, cover), facts)
    why = str(seen.get("why") or "")
    why = why if why in _WHY else "other"
    log.info("refused to press %s, it could not be read (%s)", what, why)
    raise Unread(step, "the control could not be checked", [
        "%s could not be checked for anything covering it, so nothing was "
        "pressed." % (what[:1].upper() + what[1:]),
        AGAIN], {"why": why})


def _stop_loading(page) -> None:
    """Stop a load the page started and has not finished, as the browser's
    own Stop does, over the DevTools protocol. While a tab waits on an
    answer that never comes, Playwright answers no read of it, and the run
    could not even write why it stopped. Nothing on the page is pressed."""
    session = None
    try:
        session = page.context.new_cdp_session(page)
        session.send("Page.stopLoading")
    except Exception:
        pass
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


def _shown_and_off(el) -> Optional[bool]:
    """Whether `el` shows and is turned off, read the way Playwright reads
    both before a press (is_visible, is_enabled), so it reads turned off
    exactly when Playwright's press would wait for it to turn on. False when
    it is turned on or does not show, None when either cannot be read. A
    Locator takes a timeout and an element handle does not."""
    try:
        if not el.is_visible():
            return False
    except Exception:
        return None
    for ask in (lambda: el.is_enabled(timeout=1000), lambda: el.is_enabled()):
        try:
            return not ask()
        except TypeError:
            continue
        except Exception:
            return None
    return None


def _only_turned_off(error) -> bool:
    """Whether Playwright's account of a press that raised says only that
    it waited for the control and found it turned off, every line one of
    _BEFORE_A_PRESS and one of them that the element is not enabled. Such a
    press never began."""
    lines = _account(str(error or ""))
    return bool(lines) and "element is not enabled" in lines and all(
        any(p.match(line) for p in _BEFORE_A_PRESS) for line in lines)


def _leave_if_turned_off(page, el, css: str, what: str, words, step: str, facts: dict,
                         after_a_press: bool, frame=None) -> None:
    """Raise TurnedOff when `el` shows and is turned off with nothing over
    it in the middle of the window, read the way click reads it (look,
    judge). Something over it, or a control that cannot be read there,
    stops the run as it does for any press (Covered, Unread). Returns when
    it does not read as showing and turned off, a control no longer on the
    page among them, for the caller to go on its own way. `frame` is the
    frame the control is in, as click takes it."""
    if _shown_and_off(el) is not True:
        return
    seen = look(page, el, css, off=True, frame=frame) if css else {"state": "unread", "why": "not read"}
    try:
        judge(seen, what, words, step)
    except Stop as stop:
        stop.after_a_press = stop.after_a_press or after_a_press
        raise
    log.info("%s is turned off on the page, so nothing was pressed", what)
    raise TurnedOff(step, "the control is turned off", [
        "%s is turned off on the page, so nothing was pressed." % (what[:1].upper() + what[1:]),
        AGAIN], {**facts, "verdict": "off"}, after_a_press=after_a_press)


def turned_off_after_a_press(page, el, error, *, css: str, what: str, words,
                             step: str = "press a control") -> None:
    """For an app's own press that raised, made after an earlier press for
    the same document. When Playwright's account says only that it waited
    for the control and found it turned off, nothing was pressed, and what
    the earlier press began may still bring its document, so this raises
    TurnedOff after a press, which stops the run, once the control is read
    as showing and turned off with nothing over it (_leave_if_turned_off).
    It returns for any other error, for the caller to treat the press as
    one that may have been made, as it would have."""
    from .failure import error_kind
    if _only_turned_off(error):
        _leave_if_turned_off(page, el, css, what, words, step, {"error": error_kind(error)},
                             after_a_press=True)


def _press(page, action, what: str, step: str, off: Optional[Callable[[str], None]] = None) -> None:
    """Playwright's own unforced press. Any error from it stops the run, and
    nothing is pressed again. That includes Playwright's own verdict that
    something else got the press, which it gives only when it is waited
    for, so the press is never made with no_wait_after.

    When Playwright says only that it waited for a control that stayed
    turned off, `off` is handed the error's kind first, and it may raise
    TurnedOff.

    The same wait also covers what a press starts, a page loading or a
    download beginning, so an error can come after the press was made.
    Playwright's own account of the call says "click action done" once it
    has pressed, and then the stop says the press was made and the page did
    not answer in time (NoAnswer), and otherwise that the press did not go
    through (NotPressed). Only that phrase is looked for, since the account
    also quotes the page. Either way any load the press started is stopped
    first, so the page can be read for the failure file, even should a later
    Playwright word its account some other way."""
    from .failure import error_kind
    try:
        action()
    except Exception as e:
        kind = error_kind(e)
        _stop_loading(page)
        if "click action done" in str(e):
            log.info("the press on %s was made and the page did not answer in time (%s)",
                     what, kind)
            raise NoAnswer(step, "the press was made and the page did not answer", [
                "%s was pressed, and the page did not answer in time, so nothing more "
                "is pressed." % (what[:1].upper() + what[1:]),
                AGAIN], {"error": kind, "made": True}, after_a_press=True)
        if off is not None and _only_turned_off(e):
            off(kind)
        log.info("the press on %s did not go through (%s)", what, kind)
        raise NotPressed(step, "the press did not go through", [
            "Pressing %s did not go through, so nothing more is pressed." % what,
            AGAIN], {"error": kind}, after_a_press=True)


def after(page, seen: dict, what: str, words, step: str = "press a control",
          frame=None) -> None:
    """Right after a press, the point it was made at is read once more,
    without scrolling, and a frame on top there stops the run (Covered),
    unless it was at the point before the press and the control has left the
    point since. Playwright's own check cannot see into a frame, so such a
    frame can have taken the press. When the point cannot be read now,
    nothing stops. A press that took the tab to a new document is read in
    that document, where nothing from before the press is kept, so any frame
    on top there stops the run.

    For a control inside `frame`, nothing stops when the control heard the
    browser's own click at the point pressed. Otherwise the point is read
    in that frame the same way, and then in each frame around it, where
    anything at all on top of the frame stops the run (_after_in_frame),
    since Playwright watches for its press only in the control's own
    document."""
    point = seen.get("point") if isinstance(seen, dict) else None
    if not isinstance(point, dict):
        return
    if frame is not None and frame.parent_frame is not None:
        now = _after_in_frame(page, seen, frame)
    else:
        now = _in_own_world(page, AFTER_JS, {"point": point})
    if not now or now.get("state") != "covered":
        return
    cover = described(now, words)
    lines = covering_lines(what, cover)
    lines[0] = ("Something came over %s as it was pressed, and the press may have gone "
                "to it, so nothing more is pressed." % what)
    log.info("something came over %s as it was pressed, %s", what, lines[1])
    facts = {"over_it": cover["widget"], "fixed": cover["pinned"], "after_the_press": True}
    if now.get("over_the_frame"):
        facts["over_the_frame"] = True
    raise Covered(step, "something on the page came over the control", lines, facts,
                  after_a_press=True)


def click(page, locator, *, css: str, what: str, words, step: str = "press a control",
          timeout: Optional[int] = None, frame=None) -> None:
    """Press `locator` once, with nothing on top of it, or stop the run.

    `css` is a selector the control matches, which with the locator's box
    finds it in this module's own world. `what` names it in the run's own
    words, "the Download button for the statement of 2026-01-27". `words`
    is the app's word list, words_for(provider, site). `timeout` is
    Playwright's time for the press, PRESS_MS when not given. `frame` is the
    Playwright frame the control is in, when it is not in the page's main
    frame, and then the control and every frame around it are read.

    Playwright waits for a control that is turned off for as long as it
    always did. When the control stayed turned off that whole time, and
    shows with nothing over it, nothing was pressed (TurnedOff). A control
    that reads turned off as it is first read is read the way look reads
    one (off), so what holds a control drawn to take no pointer is not
    taken for something over it, and Playwright's own check at the press
    still keeps the press from anything that is."""
    timeout = timeout or PRESS_MS
    seen = look(page, locator, css, off=_shown_and_off(locator) is True, frame=frame)
    judge(seen, what, words, step)
    _press(page, lambda: locator.click(timeout=timeout), what, step,
           off=lambda kind: _leave_if_turned_off(page, locator, css, what, words, step,
                                                 {"error": kind}, after_a_press=True,
                                                 frame=frame))
    after(page, seen, what, words, step, frame=frame)


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
          timeout: Optional[int] = None) -> None:
    """Check a radio button or a checkbox once, or stop the run.

    Nothing is pressed when it is checked already, or when whether it is
    could not be read, since pressing a checkbox that is checked unchecks
    it. A control that shows is checked by Playwright when nothing covers
    it, and through its own label when that label is what sits over it. A
    control that does not show at all is checked through a label of its own
    that does. Either way it has to read as checked afterwards."""
    timeout = timeout or PRESS_MS
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
            _press(page, lambda: locator.check(timeout=timeout), what, step)
            after(page, seen, what, words, step)
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
            AGAIN], after_a_press=True)


# ---------------------------------------------------------------------------
# Playwright's press, and once, only when it is safe, a press through the page
# ---------------------------------------------------------------------------

# What press_once says happened, for the app's own trace.
PRESSED = "pressed"
MADE = "made"
THROUGH_THE_PAGE = "through the page"
GONE = "gone"


class Pressed(NamedTuple):
    """How press_once pressed. `how` is PRESSED when Playwright's own press
    went through, MADE when it raised once it had reached the page, so that
    nothing was pressed again, THROUGH_THE_PAGE when the control was pressed
    once through the page instead, and GONE when the control left the page
    before Playwright's press began, so nothing was pressed at all and the
    document is left for another run. `error` is what Playwright's press
    raised, None when it went through, and `page_error` what the press
    through the page raised. The press may have been made then, and nothing
    more is pressed."""
    how: str
    error: Optional[BaseException] = None
    page_error: Optional[BaseException] = None


# A control's words the way controls.control_labels reads them, its text,
# its aria-label and its title, each tidied, and the same words only once.
_WORDS_OF_JS = r"""const wordsOf = (el) => {
    const out = [];
    for (const s of [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title')]) {
      const t = String(s || '').trim().replace(/\s+/g, ' ');
      if (t && !out.includes(t)) out.push(t);
    }
    return out;
  };"""

# The name a control's note is kept under in the page, random for each run,
# so nothing on the control names this program to the page's own scripts.
_KEY = "_" + secrets.token_hex(8)

# Run in the page just before Playwright presses. The control's words and
# its kind for a selector, and from then on an ear at the window, ahead of
# the page's own listeners on the control, for a press the browser itself
# sends (isTrusted) along a path through the control. Such a press is noted
# on the control under the run's key. The ear takes itself away once the
# time given has passed, or when the control is listened for again, since
# taking it away from here would mean asking a page that may be loading,
# and Playwright answers no read of such a page until it is done.
_HEAR_JS = r"""(el, args) => {
  %s
  const key = args.key;
  const kinds = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click', 'touchstart', 'touchend'];
  const ear = (e) => {
    if (!e.isTrusted) return;
    let path = [];
    try { path = e.composedPath(); } catch (x) {}
    if (path.includes(el)) el[key] = true;
  };
  if (typeof el[key + 'x'] === 'function') el[key + 'x']();
  el[key] = false;
  for (const k of kinds) window.addEventListener(k, ear, true);
  const deaf = () => { for (const k of kinds) window.removeEventListener(k, ear, true); };
  el[key + 'x'] = deaf;
  setTimeout(deaf, args.ms);
  return {words: wordsOf(el), css: CSS.escape(el.localName || '')};
}""" % _WORDS_OF_JS

# Whether the control heard a press and whether it is still on the page,
# read in one step, so a press heard is never taken for a control gone.
_STATE_JS = "(el, key) => ({heard: el[key] === true, connected: el.isConnected})"

_WORDS_JS = r"""el => {
  %s
  return wordsOf(el);
}""" % _WORDS_OF_JS

# The press through the page, made only while the control is on the page,
# has heard no press since it was listened to, and has the words it had
# before Playwright pressed, all read and pressed in one step so nothing
# can change in between.
_PRESS_JS = r"""(el, args) => {
  %s
  const want = args.want;
  if (el[args.key] === true) return 'heard';
  if (!el.isConnected) return 'gone';
  const now = wordsOf(el);
  if (now.length !== want.length || now.some((w, i) => w !== want[i])) return 'changed';
  el.click();
  return 'pressed';
}""" % _WORDS_OF_JS

# Each line of Playwright's account of a press that says only that it
# waited for the control or found it not yet ready to press. Nothing in such
# an account comes after a press began.
_BEFORE_A_PRESS = tuple(re.compile(p) for p in (
    r"waiting for (locator|frame_locator|get_by_[a-z_]+)\(", r"locator resolved to ",
    r"attempting click action$",
    r"retrying click action$", r"waiting \d+ ?ms$",
    r"waiting for element to be visible(, enabled)? and stable$",
    r"element is not (visible|stable|enabled)$", r"element is outside of the viewport$",
    r"element was detached from the dom, retrying$"))


def _account(text: str) -> Optional[list]:
    """The lines of Playwright's call log, each without its dash and its
    count of repeats, in lowercase, or None when there is no call log."""
    if "Call log:" not in text:
        return None
    out = []
    for line in text.split("Call log:", 1)[1].splitlines():
        line = re.sub(r"^\s*(\d+\s*\S\s+)?-?\s*", "", line).strip().lower()
        if line:
            out.append(line)
    return out


def playwrights_word(error) -> str:
    """What Playwright's own account of a press that raised says, in one of
    our words. "made" once it says the press was done, "covered" when it
    names something that intercepts the press, "unsure" when it began the
    press and says neither, "off" when it says the control is not enabled,
    and "not made" only when every line of the account says it waited for
    the control or found it not yet ready to press. Anything else, an
    account in words not known here, or no account at all, is "unsure", so
    a Playwright that words its account some other way presses nothing more.

    The account also quotes the page, and whatever the page wrote can only
    make this answer one that presses nothing more."""
    text = str(error or "")
    if "click action done" in text:
        return "made"
    if "intercepts pointer events" in text:
        return "covered"
    if "performing click action" in text:
        return "unsure"
    if "element is not enabled" in text:
        return "off"
    lines = _account(text)
    if not lines or not all(any(p.match(line) for p in _BEFORE_A_PRESS) for line in lines):
        return "unsure"
    return "not made"


def _handle(el):
    """The element `el` is, as an element handle, so every read and the
    press through the page reach that one element and no other. A Locator
    finds it again each time it is used, and a list drawn anew could give
    another row's control. None when it cannot be found as one."""
    find = getattr(el, "element_handle", None)
    if not callable(find):
        return el
    try:
        return find(timeout=3000)
    except Exception:
        return None


def _ask(handle, js: str, arg=None):
    """What `js` answers about the element, in the page's own world, or
    None when the page could not be asked."""
    if handle is None:
        return None
    try:
        return handle.evaluate(js, arg)
    except Exception:
        return None


def _folder_moved(dl_dir, before) -> bool:
    """A file in the download folder that was not there before the press,
    one still being written included, or one written again since."""
    from .capture import arrived
    if not dl_dir or before is None:
        return False
    try:
        names = set(os.listdir(dl_dir))
    except OSError:
        return False
    return bool(names - set(before)) or bool(arrived(dl_dir, before))


def press_once(page, el, *, what: str, words, guard: Callable[[str], bool],
               check: Optional[Callable[[], str]] = None,
               brought: Optional[Callable[[], bool]] = None, dl_dir=None,
               timeout: Optional[int] = None, step: str = "press a control") -> Pressed:
    """Press `el` once with Playwright's own unforced click, and when that
    raises, once through the page, the element's own click run inside it,
    only when that is safe, or stop the run.

    The press through the page is made only when all of this holds, checked
    in this order, and a stop says which did not.

      1. Every line of Playwright's account of its press says only that it
         waited for the control or found it not yet ready to press. A press
         it says was done is never made again (MADE). One it says something
         intercepts, one it began without saying how that ended, a control
         it says is not enabled, and an account in other words or none at
         all each stop the run. A control it waited for and found turned
         off the whole time is not pressed through the page either, and when
         nothing that could be a document came, it heard no press and it
         still shows, turned off, with nothing over it, nothing was pressed
         at all (TurnedOff).
      2. Nothing came that a press brings. No tab opened, no download
         began, the tab began loading nothing new and stands at the same
         address, no file came into `dl_dir`, and the app's own `brought`
         says nothing it should bring came. Anything of that, and nothing
         is pressed again (MADE).
      3. The control did not hear a press. Before Playwright pressed, the
         page was asked to note a press the browser itself sends along a
         path through the control, so one Playwright made, or the person
         made, is known, and is never made again (MADE). When that could
         not be asked, or not read afterwards, the run stops.
      4. The control is still on the page, read in the same step as
         whether it heard a press. One the page took away, a list drawn
         anew say, is not pressed at all, and the run goes on with the
         document left for another run (GONE).
      5. The app's own `guard` passes the control's words read now, joined
         the way controls.control_label joins them, and the app's own
         `check`, when given, says nothing. Otherwise the run stops.
      6. The control is in the middle of the window with nothing over it,
         read the way click reads it (look, judge). Otherwise the run stops.
      7. Nothing has come since, and in the same step as the press the
         control has heard no press, is still on the page, and has the
         words it had before Playwright pressed. A press heard or anything
         come by then is never made again (MADE), a control gone is not
         pressed (GONE), and other words stop the run.

    When the press through the page itself raises, it may have been made,
    and nothing more is pressed (page_error).

    What a press brings is looked at before the page is read again, since
    Playwright answers no read of a tab that is loading until the load ends,
    and a press that began one has been made.

    The listening, the reads of the control's words and the press through
    the page run in the page's own world, as the press through the page
    always did, so this is for a page that lets a script run there. Where
    a page replaces its eval, as American Express does, nothing can be
    listened to, and a press of Playwright's that raises stops the run.
    What is on top is read in this module's own world, as for click.

    `what` names the control in the run's own words, and `words` is the
    app's word list, for saying what covered it. `check` returns the app's
    own fixed words for why the control is no longer the one it checked,
    or "" while it still is. `timeout` is Playwright's time for its press,
    PRESS_MS when not given. Every read is made on the one element `el` is
    when this begins."""
    from .failure import error_kind
    came: list = []

    def on_arrival(_thing):
        came.append("arrived")

    def on_request(request):
        # A load of the tab itself, or of a frame inside it.
        try:
            if request.is_navigation_request():
                came.append("frame" if request.frame != page.main_frame else "tab")
        except Exception:
            came.append("tab")

    handle = _handle(el)
    own_handle = handle is not None and handle is not el
    try:
        tabs_before = set(page.context.pages)
    except Exception:
        tabs_before = None
    try:
        address_before = page.url or ""
    except Exception:
        address_before = None
    folder_before = None
    if dl_dir:
        from .capture import snapshot
        folder_before = snapshot(dl_dir)
    press_ms = timeout or PRESS_MS
    # The ear lives through Playwright's press and the checks after it.
    armed = _ask(handle, _HEAR_JS, {"key": _KEY, "ms": press_ms + 30000})
    before = armed.get("words") if isinstance(armed, dict) else None
    css = str(armed.get("css") or "") if isinstance(armed, dict) else ""
    listening = []

    def anything_came() -> bool:
        """What a press brings, from what was heard while Playwright pressed
        and without reading the page itself."""
        moved = bool(came)
        try:
            moved = moved or (tabs_before is not None
                              and bool([p for p in page.context.pages if p not in tabs_before]))
            moved = moved or address_before is None or (page.url or "") != address_before
            moved = moved or _folder_moved(dl_dir, folder_before)
        except Exception:
            moved = True
        return moved or bool(came)

    def a_document_could_have_come() -> bool:
        """For a control Playwright waited on and never pressed, whether
        anything that could be a document came meanwhile. That is a
        download or a tab, a file in the download folder, the tab loading,
        or its address changing other than after its #. A frame inside the
        page loading, a fetch, or a part of the page drawn anew is none of
        them."""
        if any(c != "frame" for c in came):
            return True
        try:
            if tabs_before is not None and [p for p in page.context.pages if p not in tabs_before]:
                return True
            if address_before is None or \
                    (page.url or "").split("#")[0] != address_before.split("#")[0]:
                return True
            return _folder_moved(dl_dir, folder_before)
        except Exception:
            return True

    for event, fn in (("download", on_arrival), ("popup", on_arrival), ("request", on_request)):
        try:
            page.on(event, fn)
            listening.append((event, fn))
        except Exception:
            pass
    named = what[:1].upper() + what[1:]
    try:
        try:
            el.click(timeout=press_ms)
            return Pressed(PRESSED)
        except Exception as e:
            first = e
        kind = error_kind(first)
        said = playwrights_word(first)
        if said == "made":
            log.info("the press on %s raised once it was made (%s), so it is not made again",
                     what, kind)
            return Pressed(MADE, first)
        if said != "not made":
            _stop_loading(page)
        if said == "covered":
            _covered_while_pressed(page, handle, css, what, words, step, kind)
        if said == "unsure":
            log.info("the press on %s raised and whether it was made is not known (%s)",
                     what, kind)
            raise Unsure(step, "whether the press was made is not known", [
                "Pressing %s raised before Playwright said whether the press was made, "
                "so it is not pressed again." % what,
                "Pressing it a second time could do twice what it does once, so the run "
                "stops here.",
                AGAIN], {"verdict": "unsure", "error": kind}, after_a_press=True)
        if said == "off":
            # Turned off for the press's whole time. It is left as it is,
            # with nothing pressed, only when Playwright never began the
            # press, nothing that could be a document came, and the control
            # heard no press and still shows, turned off, with nothing over
            # it (TurnedOff). Anything else stops the run.
            if _only_turned_off(first) and before is not None \
                    and not a_document_could_have_come():
                state = _ask(handle, _STATE_JS, _KEY)
                if isinstance(state, dict) and state.get("heard") is False:
                    _leave_if_turned_off(page, handle, css, what, words, step,
                                         {"error": kind}, after_a_press=True)
            log.info("%s is not enabled on the page, so it is not pressed through the page", what)
            raise NotPressed(step, "the control is turned off", [
                "%s is turned off on the page, so it was not pressed through the page "
                "either." % named,
                AGAIN], {"verdict": "off", "error": kind}, after_a_press=True)

        # 2. Whatever a press brings, from what was heard while Playwright
        # pressed and before the page is read again.
        moved = anything_came()
        if not moved and brought is not None:
            try:
                moved = bool(brought())
            except Exception:
                moved = True
        if moved:
            log.info("something came after the press on %s raised (%s), so it is not made "
                     "again", what, kind)
            return Pressed(MADE, first)

        # 3. Whether the control heard a press, Playwright's or the person's,
        # read in one step with whether it is still on the page.
        state = _ask(handle, _STATE_JS, _KEY)
        noted = state.get("heard") if isinstance(state, dict) else None
        if came or noted is True:
            log.info("%s heard the press that raised (%s), so it is not made again", what, kind)
            return Pressed(MADE, first)
        if before is None or noted is None:
            _stop_loading(page)
            log.info("whether a press reached %s could not be read (%s)", what, kind)
            raise Unsure(step, "whether the press reached the control is not known", [
                "Pressing %s raised, and whether the press reached it could not be "
                "read, so it is not pressed again." % what,
                AGAIN], {"verdict": "unheard", "error": kind}, after_a_press=True)

        # 4. Still on the page. One the page took away is not pressed, and
        # nothing about it is unsure, so the run goes on.
        if state.get("connected") is False:
            log.info("%s left the page before Playwright's press began (%s), so nothing is "
                     "pressed", what, kind)
            return Pressed(GONE, first)

        # 5. The app's own guard on the words the control has now, and its
        # own check.
        now = _ask(handle, _WORDS_JS)
        why = ""
        if not isinstance(now, list) or not now:
            why = "its words could not be read"
        else:
            try:
                passes = bool(guard(" | ".join(str(w) for w in now)))
            except Exception:
                passes = False
            if not passes:
                why = "the guard refuses its words"
            elif check is not None:
                try:
                    why = str(check() or "")
                except Exception:
                    why = "its words could not be read"
        if why:
            _changed(page, what, step, kind, why)

        # 6. Shows, in the middle of the window, with nothing over it. A
        # stop here comes after Playwright's press was tried, like the rest.
        seen = look(page, handle, css) if css else {"state": "unread", "why": "not read"}
        try:
            judge(seen, what, words, step)
        except Stop as stop:
            stop.after_a_press = True
            raise

        # 7. Nothing has come in the time those checks took, and in the same
        # step as the press the control has heard no press, the person's
        # included, is on the page, and has its words.
        if anything_came():
            log.info("something came while %s was checked (%s), so it is not pressed again",
                     what, kind)
            return Pressed(MADE, first)
        try:
            done = handle.evaluate(_PRESS_JS, {"want": before, "key": _KEY})
        except Exception as e2:
            log.info("the press through the page on %s raised (%s), so nothing more is "
                     "pressed", what, error_kind(e2))
            return Pressed(THROUGH_THE_PAGE, first, e2)
        if done == "heard":
            log.info("%s heard a press while it was checked (%s), so it is not pressed again",
                     what, kind)
            return Pressed(MADE, first)
        if done == "gone":
            log.info("%s left the page as it was to be pressed (%s), so nothing is pressed",
                     what, kind)
            return Pressed(GONE, first)
        if done != "pressed":
            _changed(page, what, step, kind, "its words changed")
        log.info("%s was pressed through the page once, after Playwright's press raised (%s)",
                 what, kind)
        return Pressed(THROUGH_THE_PAGE, first)
    finally:
        for event, fn in listening:
            try:
                page.remove_listener(event, fn)
            except Exception:
                pass
        if own_handle:
            try:
                handle.dispose()
            except Exception:
                pass


# Why a control was not pressed through the page, in press_once's words.
_CHANGED = frozenset(("its words could not be read", "the guard refuses its words",
                      "it left the page", "its words changed"))


def _changed(page, what: str, step: str, kind: str, why: str) -> None:
    """Stop the run, the control no longer the one that was checked. `why`
    is press_once's own words or the app's check's, which are fixed words
    of the app's own as well, and only press_once's go into the file."""
    _stop_loading(page)
    log.info("%s was not pressed through the page, %s", what, why)
    raise Changed(step, "the control changed", [
        "%s was not pressed through the page once Playwright's press raised, because "
        "it is no longer the control that was checked." % (what[:1].upper() + what[1:]),
        AGAIN], {"verdict": "changed", "why": why if why in _CHANGED else "the app's check",
                 "error": kind}, after_a_press=True)


def _covered_while_pressed(page, handle, css: str, what: str, words, step: str,
                           kind: str) -> None:
    """Stop the run, Playwright having said something intercepts its press.
    What covers the control now is read the way click reads it, to say it,
    and when nothing does any more the stop says what Playwright said."""
    seen = look(page, handle, css) if css else {"state": "unread"}
    facts = {"verdict": "covered", "error": kind}
    if seen.get("state") == "covered":
        cover = described(seen, words)
        lines = covering_lines(what, cover)
        facts.update({"over_it": cover["widget"], "topmost": cover["top"],
                      "fixed": cover["pinned"]})
    else:
        lines = [
            "Something on the page was over %s while Playwright pressed it, so nothing "
            "was pressed." % what,
            "A chat window, an offer or a banner is the usual thing. Close it in the "
            "browser window yourself, then press Resume here, or run this again."]
    lines[0] = lines[0][:-1] + ", and it is not pressed through the page either."
    log.info("refused to press %s through the page, Playwright says something covered it (%s)",
             what, kind)
    raise Covered(step, "something on the page was over the control", lines, facts,
                  after_a_press=True)
