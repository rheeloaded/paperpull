"""A stand-in Trade Republic tab and a real App over it, for the tests.

Every value here is invented. The tab answers each in-page fetch by the
month its fromDate names, and records what it was asked."""
import base64
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import traderepublic_docs as app_mod  # noqa: E402
import traderepublic_site as site  # noqa: E402
from paperpull_core.testkit import text_pdf  # noqa: E402

READY = "https://app.traderepublic.com/boards"
CANARY_TEXT = "PPCANARYTEXT"
CANARY_ACCOUNT = "DE00 1234 5678 9012 3456 78"


def statement(period: str, *, days=None, extra=()) -> bytes:
    """An invented statement PDF printing its month's two German days."""
    m = site.month_of(period)
    first, last = days or site.days_of(m)
    return text_pdf(["Invented Broker GmbH", "Kontoauszug " + CANARY_TEXT,
                     "Zeitraum %s - %s" % (first, last),
                     "Konto " + CANARY_ACCOUNT, "Buchungen ohne echte Werte",
                     *extra])


def pdf_answer(data: bytes, ct="application/pdf") -> dict:
    return {"status": 200, "ct": ct, "b64": base64.b64encode(data).decode()}


def status(code: int, ct="text/html") -> dict:
    return {"status": code, "ct": ct, "b64": ""}


def body(raw: bytes, ct="text/html") -> dict:
    return {"status": 200, "ct": ct, "b64": base64.b64encode(raw).decode()}


class _Count:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n


class FakeTab:
    """The person's tab. `answers` maps YYYY-MM to an answer dict, an
    exception to raise, or a callable taking the tab. A month not named
    answers 404."""

    def __init__(self, answers=None, url=READY, password_fields=0):
        self.url = url
        self.answers = dict(answers or {})
        self.asked = []
        self.queries = []
        self.closed = False
        self.password_fields = password_fields
        self.navigated = 0

    def is_closed(self):
        return self.closed

    def evaluate(self, js, arg=None):
        url = arg["url"]
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.queries.append((parts.hostname, parts.path, query))
        period = query["fromDate"][0][:7]
        self.asked.append(period)
        answer = self.answers.get(period, status(404))
        if callable(answer):
            return answer(self)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def locator(self, selector):
        return _Count(self.password_fields if "password" in selector else 0)

    def title(self):
        return "Trade Republic"

    def goto(self, *a, **kw):
        self.navigated += 1
        raise AssertionError("the app loaded a page")

    def wait_for_timeout(self, ms):
        pass


def make_app(tmp_path, tab, *argv, **config):
    cfg = {"owner": "Invented Person", "output_dir": str(tmp_path / "out"),
           "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
           "delay_min_seconds": 0, "delay_max_seconds": 0,
           "min_pdf_bytes": 2000, "document_types": ["Statement"],
           "pilot_count": 3}
    cfg.update(config)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(path), *argv])
    app = app_mod.App(args)
    app.page = lambda: tab
    app._work_page = tab
    app._delay = lambda *a, **kw: None
    app.close = lambda: None
    return app


def every_file(root: Path) -> list:
    return [p for p in Path(root).rglob("*") if p.is_file()]


def all_text(root: Path) -> str:
    out = []
    for p in every_file(root):
        if p.suffix.lower() == ".pdf":
            continue
        try:
            out.append(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    return "\n".join(out)
