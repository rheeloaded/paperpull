"""Tests for development environment info in the PaperPull GUI."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")


def test_dev_info_in_git_checkout():
    """When running in a git checkout, _dev_info returns branch, commit, root, and clean status."""
    repo = Path(app_module.HERE).parent
    if not (repo / ".git").exists() or subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True).returncode != 0:
        pytest.skip("not run from a git checkout with git on the PATH")
    info = app_module._dev_info(force_refresh=True)
    assert info is not None
    assert isinstance(info.get("branch"), str) and len(info["branch"]) > 0
    assert isinstance(info.get("commit"), str) and len(info["commit"]) > 0
    assert isinstance(info.get("root"), str) and Path(info["root"]).is_dir()
    assert isinstance(info.get("clean"), bool)


def test_dev_info_none_when_server_mode(monkeypatch):
    """In PaperPull Server mode, dev info is never returned."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    assert app_module._dev_info(force_refresh=True) is None


def test_dev_info_none_when_packaged(monkeypatch):
    """Inside a packaged application, dev info is never returned."""
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    assert app_module._dev_info(force_refresh=True) is None


def test_dev_info_none_when_not_git(monkeypatch, tmp_path):
    """Outside a git repository, dev info returns None."""
    fake_here = tmp_path / "gui"
    fake_here.mkdir()
    monkeypatch.setattr(app_module, "HERE", fake_here)
    assert app_module._dev_info(force_refresh=True) is None


def test_dev_info_handles_git_failure_gracefully(monkeypatch):
    """If git command fails or raises an exception, _dev_info safely returns None."""
    def raise_err(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", raise_err)
    assert app_module._dev_info(force_refresh=True) is None


def test_index_renders_dev_badge_clean(monkeypatch):
    """index() renders a visible dev badge with clean status and details in About."""
    fake_info = {
        "branch": "feature/my-branch",
        "commit": "1a2b3c4d",
        "root": "/path/to/paperpull",
        "clean": True,
    }
    monkeypatch.setattr(app_module, "_dev_info", lambda **kwargs: fake_info)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    html = app_module.index()

    # Brand badge is visible with branch name, and its details are in a card
    # shown on hover, not a native title tooltip, which Chrome on macOS only
    # shows after the pointer rests still and cancels on any movement.
    assert 'id="devbadge"' in html
    assert 'class="badge dev-badge"' in html
    assert "dev: feature/my-branch" in html
    assert "dev: feature/my-branch*" not in html
    badge = html[html.index('id="devbadge"'):]
    badge = badge[:badge.index("</span></span>")]
    assert "title=" not in badge
    assert 'class="dev-card" role="tooltip"' in badge
    for label, value in (("Branch", "feature/my-branch"), ("Commit", "1a2b3c4d"),
                         ("Folder", "/path/to/paperpull"), ("Status", "clean")):
        assert "<dt>%s</dt><dd>%s</dd>" % (label, value) in badge

    # About section has full dev details
    assert 'id="g-dev-info"' in html
    assert "<b>Development branch:</b> feature/my-branch (clean)" in html
    assert "<code>/path/to/paperpull</code>" in html
    assert "<code>1a2b3c4d</code>" in html


def test_index_renders_dev_badge_modified(monkeypatch):
    """When the working tree has uncommitted edits, badge displays an asterisk."""
    fake_info = {
        "branch": "fix/quick-fix",
        "commit": "9f8e7d6c",
        "root": "/path/to/paperpull",
        "clean": False,
    }
    monkeypatch.setattr(app_module, "_dev_info", lambda **kwargs: fake_info)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    html = app_module.index()

    assert "dev: fix/quick-fix*" in html
    assert "<dt>Status</dt><dd>modified</dd>" in html
    assert "<b>Development branch:</b> fix/quick-fix (modified)" in html


def test_the_card_escapes_what_git_says(monkeypatch):
    """A branch name is the person's own text and goes into the page escaped."""
    fake_info = {"branch": "x<script>", "commit": "abc", "root": "/a&b", "clean": True}
    monkeypatch.setattr(app_module, "_dev_info", lambda **kwargs: fake_info)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    html = app_module.index()
    assert "x<script>" not in html
    assert "<dd>x&lt;script&gt;</dd>" in html and "<dd>/a&amp;b</dd>" in html


def test_index_omits_dev_badge_in_server_mode(monkeypatch):
    """When in server mode, devbadge and g-dev-info remain hidden."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    html = app_module.index()
    assert '<span id="devbadge" class="badge dev-badge" hidden></span>' in html
    assert '<p class="muted small" id="g-dev-info" hidden style="margin-top: 8px;"></p>' in html
