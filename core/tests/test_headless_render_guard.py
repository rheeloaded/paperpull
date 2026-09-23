"""The headless fallback renderer will not open an address the app's own
guard refuses.

It is reached from a URL the page supplied, and only after the ordinary
capture has already failed, which is exactly when that URL is least worth
trusting. Every other fetch in the project is host checked and this one
was not.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import receipt_pdf  # noqa: E402


def only_chase(url: str) -> bool:
    return (url or "").startswith("https://chase.com/")


class ExplodingPlaywright:
    """Launching a browser at all is the failure this test is looking for."""

    class chromium:
        @staticmethod
        def launch(**_kw):
            raise AssertionError("a browser was launched for a refused address")


def test_an_address_the_guard_refuses_is_never_opened(tmp_path):
    for url in ("https://evil.example/receipt.pdf",
                "http://chase.com/receipt.pdf",
                "https://chase.com.evil.example/receipt.pdf",
                ""):
        with pytest.raises(ValueError):
            receipt_pdf.render_url_headless(
                ExplodingPlaywright(), {}, url, tmp_path / "out.pdf",
                is_safe_url=only_chase)
        assert not (tmp_path / "out.pdf").exists()


def test_the_refusal_says_what_it_refused(tmp_path):
    with pytest.raises(ValueError) as e:
        receipt_pdf.render_url_headless(
            ExplodingPlaywright(), {}, "https://evil.example/x",
            tmp_path / "out.pdf", is_safe_url=only_chase)
    assert "evil.example" in str(e.value)


def test_an_address_the_guard_allows_gets_as_far_as_the_browser(tmp_path):
    """Proving the guard is not simply refusing everything."""
    with pytest.raises(AssertionError, match="a browser was launched"):
        receipt_pdf.render_url_headless(
            ExplodingPlaywright(), {}, "https://chase.com/receipt.pdf",
            tmp_path / "out.pdf", is_safe_url=only_chase)


def test_no_app_calls_it_without_its_guard():
    """One caller today. The next one has to pass a guard as well."""
    import re
    repo = Path(__file__).resolve().parents[2]
    callers = []
    for py in repo.glob("apps/*/*.py"):
        src = py.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"render_url_headless\((.*?)\)", src, re.S):
            if "is_safe_url" not in m.group(1):
                callers.append("%s/%s" % (py.parent.name, py.name))
    assert not callers, "these call it with no host guard: %s" % callers
