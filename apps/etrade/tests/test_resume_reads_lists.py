"""Resume reads the lists before it downloads.

The download chooses a document's row by what the lists the page loaded
said, how many documents each date held and their titles. Discovery reads
them. Resume ran no discovery, so every row that did not name its
document was refused, and the app tells a user to press Resume after a
stopped run (#36, review). These drive the command alone, with its
discovery and its downloads stood in for.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_docs


def _app(remaining):
    app = etrade_docs.App.__new__(etrade_docs.App)
    app.stats = {}
    app.args = SimpleNamespace(dry_run=False)
    calls: list = []
    app._select = lambda limit=None: list(remaining)
    app._already_done = lambda doc: False
    app.cmd_discover = lambda quiet=False: calls.append(("discover", quiet))
    app.process = lambda docs, dry_run=False: calls.append(("process", len(docs)))
    return app, calls


def test_resume_reads_the_lists_before_it_downloads():
    doc = etrade_docs.Document(title="Invented Statement", category="Statements", date="2025-10-31")
    app, calls = _app([doc])
    app.cmd_resume()
    assert calls == [("discover", True), ("process", 1)]


def test_resume_with_nothing_left_touches_nothing():
    app, calls = _app([])
    app.cmd_resume()
    assert calls == []
