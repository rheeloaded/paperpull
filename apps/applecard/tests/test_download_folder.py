"""A file Apple named for another statement is never taken for this one.

The browser writes a finished file of the same name over the old one in
place, so the download folder now counts a file written again as having
arrived. Apple names every file for its own statement, and a file named
for another is refused before anything is taken. A review of the download
folder fix found that screen still reading new names only, so an August
file left in the folder and written again during September's capture,
from another tab with no event on this page, was saved as September. The
screen reads everything that arrived now. Time here is invented and passes
only when the page is asked to wait."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import applecard_site as site  # noqa: E402

AUGUST_NAME = "Apple Card Statement - August 2026.pdf"
SEPTEMBER_NAME = "Apple Card Statement - September 2026.pdf"
LEFT = b"%PDF-1.4\nAUGUST 2026, left from an earlier run" + b"0" * 2000
AUGUST = b"%PDF-1.4\nAUGUST 2026" + b"0" * 2000
SEPTEMBER = b"%PDF-1.4\nSEPTEMBER 2026" + b"0" * 2000


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


class Context:
    def __init__(self):
        self.pages: list = []

    def on(self, *a):
        pass

    def remove_listener(self, *a):
        pass


class Page:
    url = "https://card.apple.com/statements"

    def __init__(self, clock):
        self.context = Context()
        self.clock = clock

    def on(self, *a):
        pass

    def remove_listener(self, *a):
        pass

    def wait_for_timeout(self, ms):
        self.clock.advance(ms / 1000)


class Control:
    def __init__(self, on_click):
        self.on_click = on_click

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def click(self, timeout=0):
        self.on_click()


def test_a_file_named_for_another_statement_written_again_is_refused(tmp_path):
    clock = Clock()
    dl = tmp_path / ".applecard-downloads"
    dl.mkdir()
    (dl / AUGUST_NAME).write_bytes(LEFT)
    out = tmp_path / "Statements" / "2026-09-30 Apple Card Statement.pdf"
    out.parent.mkdir()

    def august_again():
        (dl / "Unconfirmed 7.crdownload").unlink()
        (dl / AUGUST_NAME).write_bytes(AUGUST)
        st = (dl / AUGUST_NAME).stat()
        os.utime(dl / AUGUST_NAME, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))

    def press():
        clock.later(1, lambda: (dl / "Unconfirmed 7.crdownload").write_bytes(b"%PDF-1.4 part"))
        clock.later(2, august_again)
        clock.later(3, lambda: (dl / SEPTEMBER_NAME).write_bytes(SEPTEMBER))

    trace: list = []
    got = site._catch_pdf(Page(clock), Control(press), "Apple Card Statement - September 2026",
                          out, trace, dl, expect=(site.CARD, "2026-09-30"))
    saved = out.read_bytes() if out.exists() else b""
    assert saved not in (AUGUST, LEFT), "saved August as September"
    assert not got and saved == b"", "a file named for another statement stops the capture"
    assert any(t.get("note") == "apple named the file for another document" for t in trace), trace
