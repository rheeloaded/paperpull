"""A download the last press asked for is never saved as this document.

Pointed at a folder, the browser saves the only copy of a download there
and the download event's own file is empty, so the capture takes the
browser's file by the event's name. A download event is not tied to the
press that caused it, which is why this capture already let only an
answer to its own request win over one. A review of the download folder
fix found the event taken ahead of that answer, so the last document's
late download was saved under this one's name. The event's file is taken
now only when it is the one document that arrived, and otherwise this
attempt's own answer decides. Time here is invented and passes only when
the page is asked to wait."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import etrade_site as site  # noqa: E402

BASE = "https://us.etrade.com/docs/"
AUGUST = b"%PDF-1.4\nAUGUST BROKERAGE STATEMENT" + b"0" * 2000
SEPTEMBER = b"%PDF-1.4\nSEPTEMBER BROKERAGE STATEMENT" + b"0" * 2000


class Clock:
    def __init__(self):
        self.t = 0.0
        self.due: list = []

    def later(self, seconds, fn):
        self.due.append((self.t + seconds, fn))

    def advance(self, seconds):
        end = self.t + seconds
        while True:
            ready = sorted((d for d in self.due if d[0] <= end), key=lambda d: d[0])
            if not ready:
                break
            self.due.remove(ready[0])
            self.t = max(self.t, ready[0][0])
            ready[0][1]()
        self.t = end


class Request:
    def __init__(self, url):
        self.url, self.redirected_from, self.resource_type = url, None, "document"


class Response:
    """An attachment, whose body the browser keeps to itself."""

    def __init__(self, request):
        self.request, self.url, self.status = request, request.url, 200
        self.headers = {"content-type": "application/pdf"}

    def body(self):
        raise RuntimeError("a download's body cannot be read")


class Provider:
    """What asking for a document again through the session gets."""

    def __init__(self):
        self.asked: list = []

    def get(self, url, timeout=0):
        self.asked.append(url)
        data = SEPTEMBER if url.endswith("september.pdf") else AUGUST
        return type("Answer", (), {"ok": True, "body": lambda self: data})()


class Context:
    def __init__(self):
        self.pages: list = []
        self.handlers: dict = {}
        self.request = Provider()

    def on(self, event, fn):
        self.handlers.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        if fn in self.handlers.get(event, []):
            self.handlers[event].remove(fn)

    def fire(self, event, obj):
        for fn in list(self.handlers.get(event, [])):
            fn(obj)


class Page:
    def __init__(self, clock):
        self.url = BASE + "list"
        self.context = Context()
        self.clock = clock
        self.listeners: list = []

    def on(self, event, fn):
        if event == "download":
            self.listeners.append(fn)

    def remove_listener(self, event, fn):
        if event == "download" and fn in self.listeners:
            self.listeners.remove(fn)

    def downloads(self, download):
        for fn in list(self.listeners):
            fn(download)

    def wait_for_timeout(self, ms):
        self.clock.advance(ms / 1000)


class Control:
    def __init__(self, on_click):
        self.on_click = on_click

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def click(self, timeout=0):
        self.on_click()


class Download:
    """Pointed at a folder, save_as waits for the download to finish and
    then writes an empty file."""

    def __init__(self, clock, url, name, done_at):
        self.clock, self.url, self.suggested_filename, self.done_at = clock, url, name, done_at

    def save_as(self, path):
        if self.clock.t < self.done_at:
            self.clock.advance(self.done_at - self.clock.t)
        Path(path).write_bytes(b"")


def _september(tmp_path, monkeypatch, late_too):
    """A September press. With `late_too`, the August download the last
    press started raises the first event and lands last."""
    monkeypatch.setattr(site, "is_safe_url", lambda u: (u or "").startswith(BASE))
    clock = Clock()
    page = Page(clock)
    dl = tmp_path / ".etrade-downloads"
    dl.mkdir()
    out = tmp_path / "Statements" / "2026-09-30 Brokerage Statement.pdf"
    out.parent.mkdir()
    earlier = Request(BASE + "august.pdf")          # the last press asked for this
    this = Request(BASE + "september.pdf")
    late = Download(clock, earlier.url, "Brokerage Statement August 2026.pdf", 5)
    mine = Download(clock, this.url, "Brokerage Statement September 2026.pdf", 4)

    def begins(request, download, part):
        page.context.fire("response", Response(request))
        page.downloads(download)
        (dl / part).write_bytes(b"%PDF-1.4 part")

    def lands(part, download, data):
        (dl / part).unlink()
        (dl / download.suggested_filename).write_bytes(data)

    def press():
        page.context.fire("request", this)
        if late_too:
            clock.later(1, lambda: begins(earlier, late, "Unconfirmed 1.crdownload"))
            clock.later(5, lambda: lands("Unconfirmed 1.crdownload", late, AUGUST))
        clock.later(2, lambda: begins(this, mine, "Unconfirmed 2.crdownload"))
        clock.later(4, lambda: lands("Unconfirmed 2.crdownload", mine, SEPTEMBER))

    trace: list = []
    got = site._catch_pdf(page, Control(press), "Brokerage Statement", out, trace, dl)
    clock.advance(10)
    return got, out, dl, page.context.request.asked, trace


def test_this_press_statement_is_taken_from_the_folder_and_asked_for_once(tmp_path, monkeypatch):
    got, out, dl, asked, trace = _september(tmp_path, monkeypatch, late_too=False)
    assert got and out.read_bytes() == SEPTEMBER, trace
    assert asked == [], "the browser already had it"
    assert list(dl.iterdir()) == [], "and moved, so no copy is left"


def test_the_last_press_late_download_is_not_this_statement(tmp_path, monkeypatch):
    got, out, dl, asked, trace = _september(tmp_path, monkeypatch, late_too=True)
    assert got and out.read_bytes() == SEPTEMBER, "saved the last press's statement under this one's name"
    assert asked == [BASE + "september.pdf"], "this attempt's own answer decided"
    assert sorted(p.name for p in dl.iterdir()) == ["Brokerage Statement August 2026.pdf"], \
        "the other is left alone, and September's own file went as an exact copy"
