"""Catching the document, whichever way the provider hands it over.

`docs/delivery-architecture.md` counted how many ways there are. Seven,
and the two that no taxonomy built from web delivery standards would
predict are the largest. Thirty three apps ask for the bytes themselves
and trigger nothing, and twelve print a page because the provider never
produces a file at all.

Twenty of the forty eight already try three or more, because which one a
provider uses is not knowable before a live run. Discover says so in its
own source. The chain is already the architecture here. It is written
out forty eight times, in `_catch_pdf` copies between 139 and 155 lines
long, and there are 109 places in the app layer that write bytes to disk.

WHY THIS IS NOT A CHAIN OF ATTEMPTS

The obvious shape is to try each mechanism in turn. That shape is wrong
and the reason matters.

A mechanism that needs a trigger cannot be retried, because the trigger
is a click on somebody's bank. Clicking twice downloads twice, or
navigates away, or trips a rate limit. **The trigger fires once.**

So the mechanisms that need one are all armed before it fires, and the
race is settled afterwards by looking at what arrived. Only the one that
needs no trigger, asking for a URL through the session, is genuinely
attempted in advance, because asking costs nothing and has no effect on
the page.

    ask        a URL, fetched through the signed-in session
    ---- the trigger fires exactly once here ----
    download   Playwright saw a download
    tab        a new tab opened, or this one became the PDF
    folder     the browser saved it itself, into a watched directory

WHY A STAGING FILE

The capture helpers write to the path they are given. If that path is
the final one, a document is in somebody's archive before anything has
asked whether it is the right document. So everything lands on a staging
file beside the destination, gets checked, and is moved into place only
after. A refused document is deleted and never existed.

That ordering is the entire reason identity verification was built first.

THE OTHER HALF, FOR PROVIDERS WITH NO FILE

Twelve providers hand over nothing and are printed from a page, and five
of those also catch real files for other documents, so one app needs
both at once. `render` is that half. It never learns how to print, which
stays in `receipt_pdf` and the app, and it exists only to give a printed
receipt the same ordering. Staged, checked, then moved.

That is why `deliver` and `render` are two functions over one `_finish`
rather than one function with a mode.

WHAT THIS DOES NOT DO

It does not decide what to click. A provider's route navigates, handles
its own intercepts, finds the control and hands over a `DocumentRequest`.
Where a document lives is bespoke. Catching it is not.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import capture
from .identity import Identity, REFUSED, Verdict, distinguish

log = logging.getLogger("paperpull.delivery")

# What produced the bytes. Also the order a settled race is read in, so
# the most direct evidence wins over the most incidental.
ASK = "ask"
DOWNLOAD = "download"
# The bytes read off the answer as it went past, before anything had to
# go and ask for them again. Fairfax Water lost two of five bills on its
# first pilot to a listener attached one beat too late, which is why it
# listens at the context rather than at the tab.
RESPONSE = "response"
TAB = "tab"
FOLDER = "folder"
# Not caught at all. Twelve providers have no file and are printed.
RENDERED = "rendered"
MECHANISMS = (ASK, DOWNLOAD, RESPONSE, TAB, FOLDER, RENDERED)

# How a delivery ended.
SAVED = "saved"
NOTHING = "nothing"        # the trigger fired and nothing arrived
NOT_A_PDF = "not a pdf"    # something arrived and it was an error page
WRONG = "wrong document"   # it arrived, it is a PDF, it is not the one asked for

PDF_MAGIC = b"%PDF-"

# How long to wait after the trigger for something to turn up, and how
# often to look. A download event is immediate. A browser writing a file
# into a folder is not.
SETTLE_MS = 20000
POLL_MS = 250


@dataclass(frozen=True)
class DocumentRequest:
    """What a provider's route hands over at the moment of the request.

    The route's job ends here. It has navigated, dealt with whatever the
    site put in the way, found the control and knows what it expects to
    get. It does not know or care how the bytes will arrive."""

    trigger: Optional[Callable[[], None]] = None
    url: str = ""
    expect: Optional[Identity] = None
    # The other rows this one could be confused with, usually the rest
    # of the list the document was chosen from. Asking whether a file
    # mentions its row's date gets a yes from the wrong document when a
    # provider bills every account on one day, or prints the previous
    # period beside the current one. Asking which row it matches best
    # does not. Empty is allowed and means the plain check.
    rivals: tuple = field(default_factory=tuple)
    # Called on every poll while waiting for the document to turn up.
    # Navy Federal shows an inactivity modal that delays the blob tab
    # from opening, so something has to keep dismissing it or the wait
    # times out on a provider that was about to answer.
    while_waiting: Optional[Callable[[], None]] = None
    # Close tabs this capture opened once it is read. A provider that
    # opens a blob tab per statement leaves one behind every time
    # otherwise, and a full archive is hundreds of them. Off by default
    # because a new tab is sometimes where the app wants to be.
    close_new_tabs: bool = False
    # A route may say its provider is blob-first, or folder-first. It is
    # a preference for reading the race, never a restriction on arming.
    hints: tuple = field(default_factory=tuple)

    def describe(self) -> dict:
        """For the journal. What kind of request this was, never where.

        A hint is reported only when it names a mechanism this module
        knows. `_order` already ignores anything else, so writing an
        unrecognized one down buys nothing and would let a string an app
        built from a page reach a file somebody posts publicly."""
        return {"has_trigger": self.trigger is not None,
                "has_url": bool(self.url),
                "waits_actively": self.while_waiting is not None,
                "closes_tabs": bool(self.close_new_tabs),
                "checkable": bool(self.expect and self.expect.is_checkable()),
                "rivals": min(len(self.rivals or ()), 999),
                "hints": sorted({h for h in (self.hints or ())
                                 if h in MECHANISMS})}


@dataclass(frozen=True)
class Delivery:
    outcome: str
    mechanism: str = ""
    verdict: Optional[Verdict] = None
    armed: tuple = ()
    bytes_len: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome == SAVED

    def report(self) -> dict:
        """Counts, states and words from this file. Never a path, never a
        URL, never anything off the page."""
        out = {"outcome": self.outcome,
               "mechanism": self.mechanism,
               "armed": sorted(self.armed),
               "bytes": min(int(self.bytes_len), 1_000_000_000)}
        if self.verdict is not None:
            out["identity"] = self.verdict.report()
        return out

    def say(self) -> str:
        if self.outcome == SAVED:
            return "the document arrived by %s" % (self.mechanism or "some route")
        if self.outcome == WRONG:
            return ("a document arrived and was refused, because it is not "
                    "the one the list said it would be")
        if self.outcome == NOT_A_PDF:
            return ("something arrived and it was not a PDF, which is what "
                    "an expired link and a signed-out session both look like")
        return ("the request was made and nothing came back, by any of the "
                "ways this provider might have answered")


class _Armed:
    """Every listener a trigger might satisfy, attached before it fires.

    Nothing in here may raise. It is holding callbacks that run inside
    Playwright's own event loop, where an exception takes down the run
    rather than this capture."""

    def __init__(self, page, dl_dir=None, close_new=False, is_safe_url=None):
        self.page = page
        self.dl_dir = dl_dir
        self.close_new = close_new
        self.is_safe_url = is_safe_url or (lambda u: False)
        self.body = b""
        self.download = None
        self.new_pages: list = []
        self.before: set = set()
        self.start_url = ""
        self.armed: list = []
        self._ctx = None

    def __enter__(self):
        try:
            self.start_url = self.page.url or ""
        except Exception:
            self.start_url = ""
        try:
            self.page.on("download", self._on_download)
            self.armed.append(DOWNLOAD)
        except Exception:
            pass
        try:
            self._ctx = self.page.context
            self._ctx.on("page", self._on_page)
            self.armed.append(TAB)
        except Exception:
            self._ctx = None
        if self._ctx is not None:
            # At the context, never at the tab. A tab's first response
            # can land before a listener attached on the page event is
            # in place, and that is how bills get lost.
            try:
                self._ctx.on("response", self._on_response)
                self.armed.append(RESPONSE)
            except Exception:
                pass
        if self.dl_dir:
            try:
                self.before = capture.snapshot(self.dl_dir)
                self.armed.append(FOLDER)
            except Exception:
                pass
        return self

    def __exit__(self, *exc):
        if self.close_new:
            for extra in self.new_pages:
                try:
                    extra.close()
                except Exception:
                    pass
        try:
            self.page.remove_listener("download", self._on_download)
        except Exception:
            pass
        if self._ctx is not None:
            try:
                self._ctx.remove_listener("page", self._on_page)
            except Exception:
                pass
            try:
                self._ctx.remove_listener("response", self._on_response)
            except Exception:
                pass
        return False

    def _on_download(self, download):
        try:
            if self.download is None:
                self.download = download
        except Exception:
            pass

    def _on_page(self, page):
        try:
            self.new_pages.append(page)
        except Exception:
            pass

    def _on_response(self, response):
        """Keep the first PDF the provider sends, whichever tab it is for.

        Guarded whole. This runs inside Playwright's event loop, where
        an exception takes the run down rather than this capture."""
        try:
            if self.body:
                return
            url = response.url or ""
            if not self.is_safe_url(url):
                return
            kind = (response.headers or {}).get("content-type", "")
            if "pdf" not in kind.lower():
                try:
                    if response.request.resource_type != "document":
                        return
                except Exception:
                    return
            body = response.body()
            if body[:5] == PDF_MAGIC:
                self.body = body
        except Exception:
            pass

    @staticmethod
    def _has_address(extra) -> bool:
        """Whether a tab has been given an address yet.

        A tab opens at about:blank and is pointed at the document a
        moment later. Navy Federal's blob tab is there within half a
        second and blank for a while after that, so counting the tab
        itself as the answer meant reading a blank page and reporting
        that nothing came back. Waiting for the address is the whole
        difference, and it cost a live run to find."""
        try:
            url = extra.url or ""
        except Exception:
            return False
        return bool(url) and url != "about:blank"

    def anything(self) -> bool:
        """Whether the race has produced something to look at yet."""
        if self.download is not None or self.body:
            return True
        if any(self._has_address(p) for p in self.new_pages):
            return True
        if self.dl_dir:
            try:
                return bool(set(os.listdir(self.dl_dir)) - self.before)
            except OSError:
                return False
        return False


def _looks_like_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8)[:5] == PDF_MAGIC
    except OSError:
        return False


def _stage(out_path: Path) -> Path:
    """A path beside the destination, so the move at the end is a rename
    on one volume rather than a copy that can half happen."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path.parent / (out_path.name + ".delivering")


def _clear(path: Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def deliver(page, request: DocumentRequest, out_path, *, is_safe_url,
            dl_dir=None, journal=None, strict: bool = True,
            settle_ms: int = SETTLE_MS) -> Delivery:
    """Get the document `request` describes into `out_path`.

    `is_safe_url` is the app's own guard and is never derived here. A
    document is not always on the provider's host, since Fairfax Water
    serves from docsight.net and Golden 1 from a vendor, so the allowlist
    has to come from the app that knows. It stays in compiled Python.

    With `strict`, a document that arrives and is not the one that was
    asked for is deleted rather than written. That is the whole point of
    the ordering here and it defaults on.
    """
    out_path = Path(out_path)
    staged = _stage(out_path)
    _clear(staged)

    def note(phase, **facts):
        if journal is not None:
            try:
                journal.op(phase, "deliver", **facts)
            except Exception:
                pass

    note("download", **request.describe())

    mechanism, armed, rejected = _acquire(page, request, staged, is_safe_url,
                                          dl_dir, settle_ms, note)
    if not mechanism:
        _clear(staged)
        # Something can arrive, be discarded for not being a PDF, and then
        # no other mechanism produce anything. Reporting that as nothing
        # would lose the difference between a provider that answered with
        # an expired-link page and one that never answered, and those are
        # different bugs on different days.
        outcome = NOT_A_PDF if rejected else NOTHING
        note("verify", outcome=outcome)
        return Delivery(outcome, rejected[0] if rejected else "",
                        armed=tuple(armed))

    return _finish(staged, out_path, request.expect, strict, mechanism,
                   armed, note, request.rivals)


def _finish(staged: Path, out_path: Path, expect, strict: bool,
            mechanism: str, armed, note, rivals=()) -> Delivery:
    """Check what was staged and either put it in place or destroy it.

    The one part that is the same whether the bytes were caught off a
    network or printed from a page, and the only part worth having. A
    document reaches the archive after it has been checked and never
    before."""
    if not _looks_like_pdf(staged):
        # A site that answers an expired link with an HTML error page
        # still produces a file, and it still has a plausible size.
        size = _size(staged)
        _clear(staged)
        note("verify", outcome="not_a_pdf", mechanism=mechanism)
        return Delivery(NOT_A_PDF, mechanism, armed=tuple(armed),
                        bytes_len=size)

    verdict = distinguish(staged, expect, rivals)
    size = _size(staged)
    note("verify", outcome=verdict.outcome, mechanism=mechanism,
         checked=len(verdict.checked), matched=len(verdict.matched))

    if strict and verdict.outcome == REFUSED:
        # Refused before it ever reaches the archive. A wrong document
        # written under a right name is the one failure nobody notices.
        _clear(staged)
        return Delivery(WRONG, mechanism, verdict, tuple(armed), size)

    try:
        _clear(out_path)
        os.replace(str(staged), str(out_path))
    except OSError as e:
        log.info("could not put the document in place: %s", e)
        _clear(staged)
        return Delivery(NOTHING, mechanism, verdict, tuple(armed), size)

    return Delivery(SAVED, mechanism, verdict, tuple(armed), size)


def place(data: bytes, out_path, *, expect: Optional[Identity] = None,
          rivals=(), journal=None, strict: bool = True) -> Delivery:
    """For the apps that already have the bytes.

    Thirty three of the forty eight ask the provider for a document
    themselves and trigger nothing, and most do it from inside the page
    with headers only that app knows, or decode something only that app
    understands. TSP's 1099-R arrives with a print-stream line in front
    of the PDF and has to be trimmed before it is one.

    None of that can move into a shared fetch, and none of it should.
    What those apps were missing is the other half, the part that has
    nothing to do with how the bytes were obtained. Staged, checked
    against what was asked for, and moved into place only if it is that
    document.

    So this is `deliver` with the racing removed, over the same
    `_finish`, which is all those apps ever needed from it."""
    out_path = Path(out_path)
    staged = _stage(out_path)
    _clear(staged)

    def note(phase, **facts):
        if journal is not None:
            try:
                journal.op(phase, "place", **facts)
            except Exception:
                pass

    if not data:
        note("verify", outcome=NOTHING, mechanism=ASK)
        return Delivery(NOTHING, ASK, armed=(ASK,))
    try:
        staged.write_bytes(data)
    except OSError as e:
        log.info("could not stage the answer the app already had: %s", e)
        return Delivery(NOTHING, ASK, armed=(ASK,))

    note("download", mechanism=ASK, got=True,
         checkable=bool(expect and expect.is_checkable()))
    return _finish(staged, out_path, expect, strict, ASK, (ASK,), note,
                   rivals)


def render(page, draw, out_path, *, expect: Optional[Identity] = None,
           rivals=(), journal=None, strict: bool = True) -> Delivery:
    """For the twelve providers where there is no file to catch.

    Costco, Gap, Amazon, Walmart, eBay, Kroger, Target, Affirm, Anthem,
    NetBenefits, Meijer and GitHub show a receipt as a web page and it is
    printed. Nothing is intercepted, so this is not `deliver` with a
    different mechanism. It is the other half of the same discipline.

    `draw(path)` does the printing and this module never learns how.
    That knowledge is `receipt_pdf`'s and the app's, and keeping it there
    is why rendering is a sibling rather than a mode.

    What it adds is the ordering. A rendered receipt is staged, checked
    and moved, so the second receipt of a run coming out blank because a
    dialog never closed, or carrying the first receipt because a page
    never changed, is caught here rather than filed."""
    out_path = Path(out_path)
    staged = _stage(out_path)
    _clear(staged)

    def note(phase, **facts):
        if journal is not None:
            try:
                journal.op(phase, "render", **facts)
            except Exception:
                pass

    note("render_item", checkable=bool(expect and expect.is_checkable()))
    try:
        draw(staged)
    except Exception as e:
        log.info("rendering the document failed: %s", e)
        _clear(staged)
        note("verify", outcome=NOTHING, mechanism=RENDERED)
        return Delivery(NOTHING, RENDERED, armed=(RENDERED,))

    if not staged.exists():
        note("verify", outcome=NOTHING, mechanism=RENDERED)
        return Delivery(NOTHING, RENDERED, armed=(RENDERED,))

    return _finish(staged, out_path, expect, strict, RENDERED,
                   (RENDERED,), note, rivals)


def _size(path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _acquire(page, request, staged: Path, is_safe_url, dl_dir, settle_ms,
             note) -> tuple:
    """Which mechanism produced bytes at `staged`, what was armed, and
    what arrived but was not a PDF.

    Returns ("", armed, rejected) when nothing produced a document."""
    armed: list = []
    rejected: list = []

    # Asking costs nothing and changes nothing, so it happens before the
    # trigger rather than as a fallback after it.
    if request.url:
        armed.append(ASK)
        try:
            body = capture.fetch_pdf(page, request.url, is_safe_url)
        except Exception as e:
            log.info("asking for the document failed: %s", e)
            body = None
        if body:
            try:
                staged.write_bytes(body)
                note("download", mechanism=ASK, got=True)
                return ASK, armed, rejected
            except OSError as e:
                log.info("could not stage the answer: %s", e)
        note("download", mechanism=ASK, got=False)

    if request.trigger is None:
        return "", armed, rejected

    with _Armed(page, dl_dir, request.close_new_tabs, is_safe_url) as watch:
        armed.extend(watch.armed)
        try:
            request.trigger()
        except Exception as e:
            log.info("the request could not be made: %s", e)
            note("download", mechanism="trigger", got=False)
            return "", armed, rejected

        # The wait has to happen inside a Playwright call. A sleep here
        # dispatches no events, so the download listener above would
        # never fire and every provider would look like it answered
        # nothing. This has been shipped wrong before.
        waited = 0
        while waited < max(POLL_MS, int(settle_ms)):
            if watch.anything():
                break
            if request.while_waiting is not None:
                # Guarded, and never a reason to stop waiting. A provider
                # whose modal handler throws is still a provider that
                # might be about to answer.
                try:
                    request.while_waiting()
                except Exception as e:
                    log.info("waiting-work raised, still waiting: %s", e)
            try:
                page.wait_for_timeout(POLL_MS)
            except Exception:
                break
            waited += POLL_MS

        for mechanism in _read_race(page, watch, staged, is_safe_url,
                                    request, rejected):
            note("download", mechanism=mechanism, got=True)
            return mechanism, armed, rejected

    note("download", mechanism="", got=False, rejected=len(rejected))
    return "", armed, rejected


def _read_race(page, watch, staged: Path, is_safe_url, request, rejected):
    """Whatever arrived, read in order of how direct the evidence is.

    A generator so the first one that produces a file wins and the rest
    are never attempted, which matters because reading a tab costs a
    round trip."""
    order = _order(request.hints)
    for mechanism in order:
        if mechanism == DOWNLOAD and watch.download is not None:
            try:
                watch.download.save_as(str(staged))
                if _looks_like_pdf(staged):
                    yield DOWNLOAD
                    return
                # Discarded so a later mechanism can still try, and
                # remembered so the run can say what did arrive.
                rejected.append(DOWNLOAD)
                _clear(staged)
            except Exception as e:
                log.info("saving the download failed: %s", e)
        elif mechanism == RESPONSE and watch.body:
            # Already in hand. No second request, which matters where the
            # address was signed for one use.
            try:
                staged.write_bytes(watch.body)
                yield RESPONSE
                return
            except OSError as e:
                log.info("could not stage the answer read in flight: %s", e)
        elif mechanism == TAB:
            if watch.new_pages:
                try:
                    if capture.take_new_tab(page, list(watch.new_pages),
                                            staged, is_safe_url):
                        yield TAB
                        return
                except Exception as e:
                    log.info("reading the new tab failed: %s", e)
            # This tab may have become the document rather than opening
            # one, which is a thing PG&E does and which looks from
            # outside exactly like nothing happening.
            try:
                if capture.take_same_tab(page, watch.start_url, staged,
                                         None, is_safe_url):
                    yield TAB
                    return
            except Exception as e:
                log.info("reading this tab failed: %s", e)
        elif mechanism == FOLDER and watch.dl_dir:
            try:
                if capture.take_new_pdf(watch.dl_dir, watch.before, staged):
                    yield FOLDER
                    return
            except Exception as e:
                log.info("taking the saved file failed: %s", e)


def _order(hints) -> list:
    """The reading order, with a route's preference moved to the front.

    A hint never removes a mechanism. An app that believes it is
    folder-first and is wrong still gets its document."""
    order = [DOWNLOAD, RESPONSE, TAB, FOLDER]
    for hint in reversed([h for h in (hints or ()) if h in order]):
        order.remove(hint)
        order.insert(0, hint)
    return order


def summarize(report) -> list:
    """What a reader of a failure file should notice."""
    said = []
    if not isinstance(report, dict):
        return said
    outcome = report.get("outcome")
    armed = report.get("armed") or []
    mechanism = report.get("mechanism") or ""
    if outcome == WRONG:
        said.append("A document arrived by %s and was refused, because it is "
                    "not the one the list said it would be. Something is "
                    "capturing the wrong document." % (mechanism or "some route"))
    elif outcome == NOT_A_PDF:
        said.append("Something arrived by %s and was not a PDF. An expired "
                    "link and a signed-out session both look like this."
                    % (mechanism or "some route"))
    elif outcome == NOTHING:
        said.append("The request was made and nothing came back. %s"
                    % (("These were watched, %s." % ", ".join(sorted(armed)))
                       if armed else "Nothing was watched for, which is the "
                                     "bug rather than a symptom of one."))
    return said


def render_needed(request: DocumentRequest) -> bool:
    """Whether this provider has no file and wants receipt_pdf instead.

    Here so a route can ask one question rather than knowing about both
    modules, and because five apps need each at different moments."""
    return request.trigger is None and not request.url
