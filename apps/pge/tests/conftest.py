"""No test here asks a real host for anything.

The capture asks for a bill through the signed-in session with
page.request, which is Playwright's own client. context.route never
reaches it, so every browser test that let the capture ask through the
session sent a real request to myaccount.pge.com, nine of them a run
(third review of round eight). Each of those is answered here instead,
from what the test put in `session.answers`, and anything else is refused
before it leaves.

A download started by a link is not routed either, nor is the address a
routed redirect sends the browser on to. So every browser a test starts
can resolve no host but this machine. A page the test routes is answered
before any name is looked up, a local test server still answers, and
anything that slips past the routes fails to find its host instead of
reaching it.
"""
import pytest

NO_HOST_BUT_THIS_ONE = ("--host-resolver-rules=MAP * ~NOTFOUND , "
                        "EXCLUDE 127.0.0.1 , EXCLUDE localhost")


class _Answer:
    def __init__(self, body: bytes):
        self._body = body
        self.status = 200
        self.ok = True
        self.headers = {"content-type": "application/octet-stream"}

    def body(self):
        return self._body

    def text(self):
        return self._body.decode("latin-1")


class _Session:
    def __init__(self):
        self.answers = {}
        self.asked = []


@pytest.fixture(autouse=True)
def session(monkeypatch):
    got = _Session()
    try:
        from playwright.sync_api import APIRequestContext, BrowserType
    except Exception:
        yield got
        return

    def ask(method):
        def call(self, url, *args, **kwargs):
            got.asked.append((method, url))
            if method == "get" and url in got.answers:
                return _Answer(got.answers[url])
            raise RuntimeError("a test asked a real host, and it was refused")
        return call

    for method in ("get", "post", "fetch", "head", "put", "patch", "delete"):
        if hasattr(APIRequestContext, method):
            monkeypatch.setattr(APIRequestContext, method, ask(method))

    real_launch = BrowserType.launch

    def launch(self, *args, **kwargs):
        kwargs["args"] = list(kwargs.get("args") or []) + [NO_HOST_BUT_THIS_ONE]
        return real_launch(self, *args, **kwargs)

    monkeypatch.setattr(BrowserType, "launch", launch)
    yield got
