"""The panel's typefaces are the computer's own.

San Francisco on a Mac and Segoe UI on Windows, as each system's own apps
use, so the page ships no font file and never fetches one, from the web or
from the panel. Code and file names use the system's monospaced face.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

GUI = Path(__file__).resolve().parents[1]
REPO = GUI.parent
CSS = (GUI / "static" / "app.css").read_text(encoding="utf-8")


def _token(name: str) -> str:
    m = re.search(r"--%s:\s*([^;]+);" % name, CSS)
    assert m, "app.css defines no --%s" % name
    return m.group(1)


def test_the_page_loads_no_font_file():
    assert "@font-face" not in CSS
    assert "/fonts/" not in CSS
    assert not (GUI / "static" / "fonts").exists()
    # Never from the web either, which the house privacy promise rules out.
    assert "fonts.googleapis" not in app_module.HTML and "fonts.gstatic" not in app_module.HTML


def test_text_is_set_in_the_systems_own_faces():
    sans = _token("sans")
    assert sans.startswith("-apple-system") and "Segoe UI" in sans and sans.rstrip().endswith("sans-serif")
    mono = _token("mono")
    assert mono.startswith("ui-monospace") and mono.rstrip().endswith("monospace")


def test_no_route_serves_fonts_any_more():
    assert not hasattr(app_module, "FONTS")
    paths = {getattr(r, "path", "") for r in app_module.app.routes}
    assert not any(p.startswith("/fonts") for p in paths)
    # Nothing under /fonts/ is kept by a browser as the same for everyone.
    assert not any(p.startswith("/fonts") for p in app_module._ANYONES_UNDER)


def test_notice_no_longer_lists_bundled_typefaces():
    notice = (REPO / "NOTICE.md").read_text(encoding="utf-8")
    assert "Atkinson Hyperlegible" not in notice
