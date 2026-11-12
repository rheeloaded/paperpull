"""How much of a document PaperPull takes in, held in one place.

Every way a document reaches an app, a fetch, an answer read off the
network, a download, a ZIP opened, a PDF read for its text, used to take
whatever came, however large, for however long. A provider's answer that
never ended, an archive that unpacks a thousand times over, or a PDF built
to keep its reader busy had nothing to stop them but the computer running
out of memory or the run never finishing.

The limits are here and nowhere else, and every reader looks them up when
it reads, so changing one here changes it everywhere.

MEASURED 2026-10-17 on the maintainer's installs, sizes only. 2,644 PDFs
from 38 providers, the largest 3.9 MB (a TSP statement), 99.9 percent of
them under 2.9 MB, and no ZIP among them. A document may be twenty five
times the largest seen, and anything larger is refused before it is read,
which is generous for a statement and still a bound on a NAS.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import weakref
from pathlib import Path
from typing import Optional

log = logging.getLogger("paperpull.intake")

MiB = 1024 * 1024

# The most one document may be as it arrives, a PDF or a ZIP holding one,
# whichever way it comes.
DOCUMENT_BYTES = 100 * MiB

# A ZIP is opened only when it holds one PDF and nothing else
# (receipt_pdf.open_zip). Its listing is read before any file in it, and an
# archive listing more files than this is kept whole without a look inside.
ZIP_MEMBERS = 1000
# How many times its packed size a file in a ZIP may unpack to. A PDF packs
# poorly, since its pages are compressed already, and a statement printed
# with no compression at all packs to about a tenth. An archive built to
# fill a disk unpacks a thousand times over.
ZIP_RATIO = 100
# A file this small is never refused for its ratio. A PDF written with no
# compression and padded packs a hundred times over (a review made one of
# 2 MB), and below this the size limit alone already bounds what unpacks.
ZIP_RATIO_FROM = 10 * MiB

# How long one PDF may take to be read for its pages and its text, and how
# much memory the reading may use. It happens in a process of its own
# (pdf_reader), which is stopped when either is passed.
#
# MEASURED 2026-10-17 here, a statement of 282 dense pages printed by
# Chromium had all its text read in 5.2 s, and the worker's start costs
# 0.3 s once a run and 2 ms a PDF after. A PDF of 72 KB holding one string
# of 70 MB took pypdf 6.19 175 s and stopped at once against 200 MB of
# memory. Two minutes leaves a slow NAS room for a long statement.
PDF_SECONDS = 120
PDF_MEMORY_BYTES = 1024 * MiB

# How long a download the page started may take to finish once it has
# begun, before it is cancelled. A 100 MB document at a slow 1 MB a second
# takes under two minutes.
DOWNLOAD_SECONDS = 300


class TooLarge(Exception):
    """A document, or an answer that might be one, refused for its size. Its
    words say so in a sentence a person can read."""


def raising(name: str, gives: str) -> str:
    """Which limit a refusal met and where it is raised, said after the
    refusal itself, so a person who sees it on every run knows what to
    change. A document refused for a limit is asked for again on the next
    run, as any refused document is, and comes in once the limit allows it."""
    return "%s in paperpull_core/intake.py is the limit, and raising it %s." % (name, gives)


def _mb(n: int) -> str:
    return "%d MB" % max(1, round(n / MiB)) if n >= MiB else "%d bytes" % n


_refused = 0


def refused_count() -> int:
    """How many refusals this process has said, so a capture can tell
    whether one happened while it ran, whichever reader made it."""
    return _refused


_timed_out = 0


def timed_out_count() -> int:
    """How many downloads this process has cancelled for their time."""
    return _timed_out


def refuse(what: str = "The answer for this document", size: Optional[int] = None,
           limit: Optional[int] = None) -> TooLarge:
    """The refusal for something over the limit, said once on the run's
    output and in the log, ready to raise."""
    global _refused
    _refused += 1
    limit = DOCUMENT_BYTES if limit is None else limit
    sized = " (%s)" % _mb(size) if size else ""
    said = ("%s was larger than the %s PaperPull takes in%s, so it was not read. %s"
            % (what, _mb(limit), sized, raising("DOCUMENT_BYTES", "lets a larger one in")))
    log.warning(said)
    print("  " + said)
    return TooLarge(said)


def declared(resp) -> Optional[int]:
    """The length an answer says its body has, or None when it says none.
    Playwright gives header names in lower case, for a page's answer and
    for one it asked for itself alike."""
    try:
        headers = resp.headers or {}
        value = headers.get("content-length")
    except Exception:
        return None
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def body(resp, limit: Optional[int] = None) -> bytes:
    """An answer's body, refused unread when its declared length is over
    the limit, and refused when what came is. Raises TooLarge.

    For an answer the app asked for itself (context.request), Playwright's
    driver holds the whole body before this can see any of it, and nothing
    in Playwright 1.63 bounds that (coreBundle.js gathers every chunk of
    every request). What this keeps out is the copy into this process, at
    once when the length is declared. MEASURED 2026-10-17 in Chromium 153,
    an answer to the page itself is kept by the browser only up to about
    ten megabytes, and body() then raises that it was evicted, so a page's
    answer is bounded before it gets here."""
    limit = DOCUMENT_BYTES if limit is None else limit
    said = declared(resp)
    if said is not None and said > limit:
        _let_go(resp)
        raise refuse(size=said, limit=limit)
    data = resp.body() or b""
    if len(data) > limit:
        _let_go(resp)
        raise refuse(size=len(data), limit=limit)
    return data


def text_of(resp, limit: Optional[int] = None) -> str:
    """An answer's text, read through body(), so one the app asked for
    itself (context.request) is refused unread when its declared length is
    over the limit and is never copied into this process past it. Raises
    TooLarge. Decoded as Playwright's own text() decodes it."""
    return body(resp, limit).decode()


def json_of(resp, limit: Optional[int] = None):
    """An answer's JSON, read as text_of reads its text, made whole as every
    app's parse is (characters.whole_json). Raises TooLarge, and ValueError
    for an answer that is not JSON, as Playwright's own json() does."""
    import json as _json
    from .characters import whole_json
    return whole_json(_json.loads(text_of(resp, limit)))


def _let_go(resp) -> None:
    """Have Playwright's driver drop an answer it asked for itself, which it
    otherwise holds whole until its context closes. A page's answer has
    nothing to drop."""
    try:
        dispose = getattr(resp, "dispose", None)
        if callable(dispose):
            dispose()
    except Exception:
        pass


def decode(text, *, validate: bool = False, limit: Optional[int] = None) -> bytes:
    """Base64 a page or the browser handed back, decoded, refused before it
    is decoded when it holds more than the limit. Raises TooLarge."""
    if not text:
        return b""
    limit = DOCUMENT_BYTES if limit is None else limit
    # Four characters carry three bytes, and the padding carries none.
    if len(text) > (limit // 3 + 1) * 4:
        raise refuse(size=len(text) // 4 * 3, limit=limit)
    data = base64.b64decode(text, validate=validate)
    if len(data) > limit:
        raise refuse(size=len(data), limit=limit)
    return data


def inflate(data: bytes, wbits: int = 15, limit: Optional[int] = None) -> bytes:
    """zlib.decompress(data, wbits), refused once it unpacks past the limit
    rather than after. Raises TooLarge, and zlib.error for data that is
    not whole, as zlib.decompress does."""
    import zlib
    limit = DOCUMENT_BYTES if limit is None else limit
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, limit + 1)
    if len(out) > limit or d.unconsumed_tail:
        raise refuse("The packed document", limit=limit)
    # Everything was read, so what is left to come is at most one copy.
    out += d.flush()
    if len(out) > limit:
        raise refuse("The packed document", size=len(out), limit=limit)
    if not d.eof:
        raise zlib.error("incomplete or truncated stream")
    return out


def size_of(path) -> int:
    """The size of a file, 0 when it cannot be read."""
    try:
        return os.stat(path).st_size
    except (OSError, ValueError, TypeError):
        return 0


def over(path, limit: Optional[int] = None) -> bool:
    """Whether a file on disk is larger than a document may be."""
    limit = DOCUMENT_BYTES if limit is None else limit
    return size_of(path) > limit


def read_file(path, what: str = "The downloaded file", limit: Optional[int] = None) -> bytes:
    """A file's bytes, refused unread when it is larger than a document may
    be. Raises TooLarge, and whatever reading it raises."""
    check_file(path, what, limit)
    with open(path, "rb") as f:
        data = f.read((DOCUMENT_BYTES if limit is None else limit) + 1)
    if len(data) > (DOCUMENT_BYTES if limit is None else limit):
        raise refuse(what, size=len(data), limit=limit)
    return data


def check_file(path, what: str = "The downloaded file", limit: Optional[int] = None) -> None:
    """Refuse a file on disk over the limit, before anything reads it.
    Raises TooLarge. The file is left where it is."""
    limit = DOCUMENT_BYTES if limit is None else limit
    size = size_of(path)
    if size > limit:
        raise refuse(what, size=size, limit=limit)


# -- reading an answer inside the page ----------------------------------------
#
# A page fetches a document with the session's cookies and hands it back as
# base64, and Response.arrayBuffer() holds the whole answer before a single
# byte can be counted. These read it a piece at a time instead and stop at
# the limit. An answer a page's own fetch gives with no body stream at all,
# as Anthem's member portal does, offers no way to read it in pieces, so it
# alone is read whole and then held to the limit. A snippet that reads a
# body calls ppRead(response) or ppBlob(blob) in place of arrayBuffer(), and
# ppText(response) or ppJson(response) in place of text() and json() where
# the text is the document, a page an app prints or the letters it renders.
# ppRefused(e) says whether an error a snippet caught is one of these
# refusing, which it throws on rather than taking for an answer that did not
# parse. A snippet that reads any of them is run through evaluate() below,
# which puts these in front of it with the limit of the moment.
#
# A page's own scripts can change fetch and every reader under it, so a
# provider's page that meant to could still hand back more. decode() then
# refuses it before it is decoded, and V8 holds no string past about 512
# million characters, which bounds what can come back at all.

READ_MARK = "PaperPull refused an answer over its limit"

_READ_JS = r"""
  const ppLimit = %(limit)d;
  const ppOver = (n) => new Error("%(mark)s of " + ppLimit + " bytes, " + n);
  const ppRead = async (r) => {
    const said = Number(r.headers.get("content-length"));
    if (said > ppLimit) {
      try { if (r.body) await r.body.cancel(); } catch (e) {}
      throw ppOver(said);
    }
    // A page's own fetch can answer with no body stream at all (undefined,
    // where an answer with no body has null). That answer is read whole and
    // then held to the limit, since it offers no way to read it in pieces.
    if (r.body === undefined) {
      const whole = new Uint8Array(await r.arrayBuffer());
      if (whole.byteLength > ppLimit) throw ppOver(whole.byteLength);
      return whole;
    }
    if (!r.body) return new Uint8Array(0);
    const reader = r.body.getReader();
    const parts = [];
    let got = 0;
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      got += value.byteLength;
      if (got > ppLimit) {
        try { await reader.cancel(); } catch (e) {}
        throw ppOver(got);
      }
      parts.push(value);
    }
    const out = new Uint8Array(got);
    let at = 0;
    for (const p of parts) { out.set(p, at); at += p.byteLength; }
    return out;
  };
  const ppBlob = async (b) => {
    if (!b) return new Uint8Array(0);
    if (b.size > ppLimit) throw ppOver(b.size);
    return new Uint8Array(await b.arrayBuffer());
  };
  const ppText = async (r) => new TextDecoder().decode(await ppRead(r));
  const ppJson = async (r) => JSON.parse(await ppText(r));
  const ppRefused = (e) => String((e && e.message) || e).startsWith("%(mark)s");
"""

_OPENER = "=> {"
_built: dict = {}


def reading(js: str, limit: Optional[int] = None) -> str:
    """A snippet with ppRead and ppBlob put at the top of its body, reading
    no more than `limit`. The snippet is an arrow function, and they go in
    right after the first "=> {". ValueError when it has none."""
    limit = DOCUMENT_BYTES if limit is None else int(limit)
    key = (js, limit)
    if key not in _built:
        at = js.find(_OPENER)
        if at < 0:
            raise ValueError("a snippet that reads a body must be an arrow function with a body")
        at += len(_OPENER)
        _built[key] = js[:at] + _READ_JS % {"limit": limit, "mark": READ_MARK} + js[at:]
    return _built[key]


_NO_ARG = object()


def evaluate(target, js: str, arg=_NO_ARG, limit: Optional[int] = None):
    """target.evaluate(js, arg), with js reading no more than the limit
    (reading). An answer refused in the page is said once and raised as
    TooLarge, and anything else the page raised is raised as it was."""
    limit = DOCUMENT_BYTES if limit is None else limit
    try:
        if arg is _NO_ARG:
            return target.evaluate(reading(js, limit))
        return target.evaluate(reading(js, limit), arg)
    except Exception as e:
        text = str(e)
        if READ_MARK not in text:
            raise
        size = None
        try:
            size = int(text.split(READ_MARK, 1)[1].split(",", 1)[1].split()[0])
        except (IndexError, ValueError):
            pass
        raise refuse(size=size, limit=limit) from None


def page_said_too_large(error) -> bool:
    """Whether an error a page raised is an answer refused in it."""
    return READ_MARK in str(error)


# -- a download the browser wrote ---------------------------------------------
#
# A download's own file, a copy of it, why it failed and deleting it all
# wait in Playwright until it has finished, for as long as the provider
# keeps sending. So whatever asks for any of them goes through finish()
# first, which has the download followed in a fiber of its own and waits
# for that only DOWNLOAD_SECONDS, a moment at a time on the page so the
# browser goes on meanwhile, and cancels a download that did not finish.

class TooSlow(TooLarge):
    """A download cancelled for its time. Caught wherever a refusal for size
    is, since a document refused for any limit is handled the same way, and
    asked for again on the next run."""


class _Following:
    """Whether a followed download has finished, and the refusal it met when
    it was cancelled unfinished, raised again each time it is asked for."""
    __slots__ = ("done", "refused")

    def __init__(self):
        self.done = False
        self.refused: Optional[TooLarge] = None


# Keyed by the download itself, so a record goes when its download does.
_followed: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def follow(download) -> None:
    """Start following a download the page started, without waiting for it.

    A listener that hears the download can call this so the download is
    already being followed when something saves it. Nothing has to, since
    finish() starts it on first asking."""
    _follow(download)


def _follow(download) -> Optional[_Following]:
    """The record of a download being followed, started on first asking.

    Download.path() returns once the download has finished, so it is asked
    in a fiber of its own, started by Playwright's loop the way Playwright
    starts a fiber for each listener, and while it waits there the run goes
    on. None for a stand-in a test made, or where Playwright's loop is not
    there to start it, and such a download is not waited on."""
    try:
        from playwright.sync_api import Download
        import greenlet
    except ImportError:
        return None
    if not isinstance(download, Download):
        return None
    state = _followed.get(download)
    if state is not None:
        return state
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    state = _Following()

    def wait() -> None:
        # Playwright raises a listener's own error at whichever call comes
        # next, which can be this one, and the download has not finished
        # then. One cancelled, failed or with its browser gone says so again
        # at once, so it is asked three times before it counts as finished
        # (review).
        for _ in range(3):
            try:
                download.path()
                break
            except Exception:
                continue
        state.done = True

    fiber = greenlet.greenlet(wait)

    def start() -> None:
        # Run by the loop, so the fiber running it is the one that runs
        # the loop. The follower hands back to it while it waits and when
        # it ends, as a listener's fiber does.
        try:
            fiber.parent = greenlet.getcurrent()
            fiber.switch()
        except Exception as e:
            log.info("following a download could not start: %s", type(e).__name__)
            state.done = True

    loop.call_soon(start)
    _followed[download] = state
    return state


class _Pages:
    """Pauses on the page a download is waited from, else the page it came
    on, else any open page of its context, else the context itself. A tab
    that opened only to start the download and closed again does not end
    the wait, nor does every page of the browser having closed while the
    context is still open."""

    def __init__(self, download, page=None):
        self.download = download
        self.page = page

    def _candidates(self) -> list:
        out = [self.page]
        try:
            own = self.download.page
            out.append(own)
            out.extend(own.context.pages)
        except Exception:
            pass
        return [p for p in out if p is not None]

    def wait_for_timeout(self, ms) -> None:
        for p in self._candidates():
            try:
                if p.is_closed():
                    continue
                p.wait_for_timeout(ms)
                return
            except Exception:
                continue
        # No page is open. The context's own close is waited for instead,
        # which runs Playwright's loop for the pause and so lets the
        # follower see a download that had already finished (review).
        try:
            context = self.download.page.context
        except Exception:
            context = None
        if context is not None:
            try:
                context.wait_for_event("close", timeout=max(1, ms))
            except Exception as e:
                if type(e).__name__ == "TimeoutError":
                    return
        raise RuntimeError("no open page or context to wait on")


def finish(download, page=None, seconds: Optional[float] = None, *, partial=None) -> bool:
    """Whether a download finished within `seconds` (DOWNLOAD_SECONDS), so
    its own file, a copy of it or its failure can be asked for at once.

    One that did not, or whose file grew past the limit while it arrived
    (`partial`, as waits_for takes it), is cancelled, said once, and stays
    refused for the rest of the run (refusal). A stand-in a test made is
    taken as finished, as it always was."""
    state = _follow(download)
    if state is None:
        return True
    if state.refused is not None:
        return False
    if state.done:
        return True
    said = (_refused, _timed_out)
    if waits_for(download, _Pages(download, page), seconds,
                 finished=lambda d: state.done, partial=partial, start_ms=5):
        return True
    _cancel(download)
    if _refused > said[0]:
        state.refused = TooLarge("The download for this document grew larger than the %s "
                                 "PaperPull takes in, so it was cancelled. %s"
                                 % (_mb(DOCUMENT_BYTES),
                                    raising("DOCUMENT_BYTES", "lets a larger one in")))
    elif _timed_out > said[1]:
        state.refused = TooSlow(_slow_words(seconds=seconds))
    else:
        # Neither limit was met. No page of its browser was open to wait
        # on, so the browser went away with the download unfinished.
        log.info("a download was cancelled unfinished, with no page left to wait on")
        state.refused = TooSlow("The download for this document was cancelled unfinished, "
                                "with its browser gone.")
    return False


def refusal(download) -> Optional[TooLarge]:
    """The refusal a download met in finish(), ready to raise, or None."""
    try:
        state = _followed.get(download)
    except TypeError:
        # A stand-in a test made, which no record can be kept for.
        return None
    return state.refused if state is not None else None


def _slow_words(what: str = "The download for this document",
                seconds: Optional[float] = None) -> str:
    # A wait an app gives of its own is not this module's limit, and raising
    # DOWNLOAD_SECONDS would not change it, so only the time is said.
    if seconds is not None:
        return "%s did not finish in %d seconds, so it was cancelled." % (what, seconds)
    return ("%s did not finish in %d seconds, so it was cancelled. %s"
            % (what, DOWNLOAD_SECONDS, raising("DOWNLOAD_SECONDS", "gives a download longer")))


def failure(download, page=None, *, partial=None) -> str:
    """download.failure() within DOWNLOAD_SECONDS, and within the limit in
    the folder the browser writes it to (`partial`, as finish takes it).
    "" when the download finished whole, the browser's word for why it did
    not, or the refusal it met in finish()."""
    if not finish(download, page, partial=partial):
        return str(refusal(download) or "cancelled unfinished")
    return download.failure() or ""


def discard(download, page=None) -> None:
    """Cancel a download nobody wants and delete the browser's copy of it.

    Deleting waits until the download has finished, which once it is
    cancelled is at once. Where cancelling raised, it waits only as long as
    finish() allows. Nothing here raises."""
    try:
        download.cancel()
        cancelled = True
    except Exception:
        cancelled = False
    try:
        if cancelled or finish(download, page):
            download.delete()
    except Exception:
        pass


def save_download_as(download, out_path, *, partial=None) -> None:
    """download.save_as(out_path), within the limits.

    It is waited for only as long as finish() allows, and a download that
    did not finish in time is cancelled and raises TooSlow. The browser's
    own copy is measured once it has finished, and one larger than a
    document may be is never copied. Where Playwright cannot say where its
    copy is, the copy is made beside `out_path` and measured before it
    takes its place, so a file already at `out_path` is never written over
    by one that is then refused. Raises TooLarge, and whatever save_as
    raises."""
    out_path = Path(out_path)
    if not finish(download, partial=partial):
        raise refusal(download) or TooSlow(_slow_words())
    try:
        own = download.path()
    except Exception:
        own = None
    if own:
        check_file(own, "The download for this document")
    side = out_path.with_name(out_path.name + ".saving")
    try:
        download.save_as(str(side))
        size = size_of(side)
        if size > DOCUMENT_BYTES:
            raise refuse("The download for this document", size=size)
        os.replace(side, out_path)
    finally:
        try:
            side.unlink(missing_ok=True)
        except OSError:
            pass


def waits_for(download, page, seconds: Optional[float] = None, *, finished=None,
              partial=None, poll_ms: int = 250, start_ms: Optional[int] = None) -> bool:
    """Whether a download finished within `seconds`, cancelled when it did
    not or when the file it is writing grew past the limit.

    `finished(download)` answers whether it has finished, and is the record
    kept by whatever asks download.path() in a fiber of its own, where a
    wait for it holds nothing else (finish).
    `partial` is the file the browser writes it to while it arrives, when
    the app knows it. The wait is page.wait_for_timeout, so that fiber runs
    meanwhile. With `start_ms` the first pause is that long and each one
    after twice the last, up to `poll_ms`, so a download that has already
    finished costs a moment and not a quarter second."""
    global _timed_out
    given = seconds
    seconds = DOWNLOAD_SECONDS if seconds is None else seconds
    waited = 0
    pause = poll_ms if start_ms is None else max(1, min(start_ms, poll_ms))
    while True:
        try:
            if finished is not None and finished(download):
                return True
        except Exception:
            pass
        if partial is not None:
            for path in (partial() if callable(partial) else partial) or ():
                if over(path):
                    refuse("The download for this document", size=size_of(path))
                    _cancel(download)
                    return False
        if waited >= seconds * 1000:
            _timed_out += 1
            log.warning("a download did not finish in %d seconds and was cancelled", seconds)
            print("  " + _slow_words("The download", given))
            _cancel(download)
            return False
        try:
            page.wait_for_timeout(pause)
        except Exception:
            return False
        waited += pause
        pause = min(poll_ms, pause * 2)


def _cancel(download) -> None:
    try:
        download.cancel()
    except Exception:
        pass


def partials(dl_dir) -> list:
    """The files a browser is still writing in `dl_dir`."""
    from .capture import UNFINISHED
    if not dl_dir:
        return []
    try:
        return [Path(dl_dir) / n for n in os.listdir(dl_dir)
                if n.lower().endswith(UNFINISHED)]
    except OSError:
        return []
