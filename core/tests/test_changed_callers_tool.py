"""tools/changed_callers.py has to find the caller a change broke.

In 0.34.0 the shared deliver() did not take rivals=, which four apps
passed it, and 5,316 tests passed because they called it another way. On
2026-10-02 a hand merge turned a returned list into a pair, and a test
elsewhere still walked the list. Each test here starts from a small git
checkout with a committed base, changes its working tree the way those
changes did, runs the tool against HEAD, and checks what it printed and
how it exited.
"""
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

cc = pytest.importorskip("changed_callers")


DELIVERY = '''
def deliver(page, request, *, rivals=None, timeout=30):
    return page


def rows(found):
    return [r for r in found if r]


def old_helper(x):
    return x


class Journal:
    def __init__(self, path, *, owner=None):
        self.path = path
'''

FETCH = '''
class Fetcher:
    def fetch(self, url):
        return url

    def again(self, url):
        return self.fetch(url)
'''

APP = '''
from lib.delivery import deliver, old_helper, Journal
from lib import delivery
from lib.fetch import Fetcher


class Other:
    def fetch(self, url, mode):
        return url


def run(page, req):
    got = deliver(page, req, rivals=[1])
    for row in delivery.rows([1, 2]):
        print(row)
    old_helper(1)
    Journal("p", owner="me")
    Other().fetch("u", mode="x")
    return got, Fetcher().fetch("u")


def use(thing):
    return thing.fetch("u", mode="x")
'''

SPREAD = '''
from lib.delivery import deliver


def again(page, req, **kw):
    return deliver(page, req, **kw)
'''

BASE = {"lib/__init__.py": "", "lib/delivery.py": DELIVERY, "lib/fetch.py": FETCH,
        "apps/app.py": APP, "apps/spread.py": SPREAD}

# Laid out like the real checkout. A shared package that imports itself
# relatively, and two apps that each import their own storage.py by its
# bare name, one passing the shared function on, one with its own.
LAYERED = {
    "core/pkg/__init__.py": "",
    "core/pkg/storage.py": '''
def now_iso(stamp, zone=None):
    return stamp
''',
    "core/pkg/naming.py": '''
from .storage import now_iso


def name_for(stamp):
    return now_iso(stamp, zone="UTC")
''',
    "apps/one/storage.py": '''
from pkg.storage import now_iso  # noqa: F401  passed on to the app
''',
    "apps/one/one_site.py": '''
from storage import now_iso


def when(stamp):
    return now_iso(stamp, zone="local")
''',
    "apps/two/storage.py": '''
def now_iso(stamp, zone=None):
    return stamp
''',
    "apps/two/two_site.py": '''
from storage import now_iso


def when(stamp):
    return now_iso(stamp, zone="local")
''',
}


def _text(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_text(text), encoding="utf-8")


def _edit(root: Path, rel: str, old: str, new: str) -> None:
    p = root / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new), encoding="utf-8")


def _at(rel: str, text: str, needle: str) -> str:
    """The place the tool names for the first line of one of our files
    that holds `needle`, its path and line number."""
    for n, line in enumerate(_text(text).splitlines(), 1):
        if needle in line:
            return "%s:%d" % (rel, n)
    raise AssertionError("no line holds " + needle)


def _git(root: Path, *args) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture(scope="module")
def committed(tmp_path_factory):
    """A git checkout of each base, committed once and copied for every
    test that starts from it, since a git process can take a second here."""
    made = {}

    def make(files: dict) -> Path:
        key = tuple(sorted(files.items()))
        if key not in made:
            root = tmp_path_factory.mktemp("base")
            for rel, text in files.items():
                _write(root, rel, text)
            _git(root, "init", "-q")
            _git(root, "config", "user.name", "Changed Callers Test")
            _git(root, "config", "user.email", "changed-callers@example.com")
            _git(root, "config", "commit.gpgsign", "false")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "--no-verify", "-m", "base")
            made[key] = root
        return made[key]

    return make


@pytest.fixture
def checkout(committed, tmp_path):
    """This test's own copy of a committed base, to change as it likes."""
    def make(files=None) -> Path:
        root = tmp_path / "checkout"
        shutil.copytree(committed(files or BASE), root)
        return root

    return make


def _run(root: Path, capsys, base: str = "HEAD"):
    code = cc.main(["--repo", str(root), "--base", base])
    got = capsys.readouterr()
    return code, got.out.splitlines(), got.err


def _block(lines: list, head: str) -> list:
    """The lines printed for one changed function, up to the blank line."""
    i = lines.index(head)
    end = lines.index("", i)
    return lines[i + 1:end]


def _summary(lines: list) -> str:
    return lines[-1].rsplit(", in ", 1)[0]


# -- the two incidents ---------------------------------------------------------

def test_a_keyword_the_new_signature_refuses_is_an_error(checkout, capsys):
    """The 0.34.0 case. Another module imports deliver() and passes
    rivals=, which the new deliver() does not take."""
    root = checkout()
    _edit(root, "lib/delivery.py", "*, rivals=None, timeout=30", "*, timeout=30")
    code, lines, err = _run(root, capsys)
    assert code == 1, lines + [err]
    assert _block(lines, "lib/delivery.py:1  deliver") == [
        "  signature changed",
        "    was  deliver(page, request, *, rivals=..., timeout=...)",
        "    now  deliver(page, request, *, timeout=...)",
        "  ERROR      %s  passes rivals=, which deliver does not accept"
        % _at("apps/app.py", APP, "rivals=[1]"),
        "  ok         %s" % _at("apps/spread.py", SPREAD, "deliver(page, req, **kw)"),
    ]
    assert _summary(lines) == ("1 error, 0 warnings, 2 call sites (2 resolved, 0 unresolved) "
                               "of 1 changed function, and 0 new functions checked")


def test_the_same_call_is_clean_when_the_new_signature_takes_the_keyword(checkout, capsys):
    root = checkout()
    _edit(root, "lib/delivery.py", "*, rivals=None, timeout=30", "*, rivals=None, timeout=30, settle=0")
    code, lines, err = _run(root, capsys)
    assert code == 0, lines + [err]
    block = _block(lines, "lib/delivery.py:1  deliver")
    assert "  ok         %s" % _at("apps/app.py", APP, "rivals=[1]") in block
    assert not any("ERROR" in ln or "WARNING" in ln for ln in lines)
    assert _summary(lines).startswith("0 errors, 0 warnings, 2 call sites")


def test_a_list_that_became_a_pair_lists_its_callers_to_read(checkout, capsys):
    """The hand merge case. No verdict is possible, so every call is
    listed under a line that says the return changed."""
    root = checkout()
    _edit(root, "lib/delivery.py", "    return [r for r in found if r]\n",
          "    unread = [r for r in found if not r]\n    return (found, unread)\n")
    code, lines, err = _run(root, capsys)
    assert code == 0, lines + [err]
    assert _block(lines, "lib/delivery.py:5  rows") == [
        "  return changed, so read each call below",
        "    was  return [r for r in found if r]",
        "    now  return (found, unread)",
        "  read       %s" % _at("apps/app.py", APP, "delivery.rows("),
    ]


# -- what else is an error -----------------------------------------------------

def test_a_removed_function_with_a_caller_is_an_error(checkout, capsys):
    root = checkout()
    _edit(root, "lib/delivery.py", "def old_helper(x):\n    return x\n", "")
    code, lines, err = _run(root, capsys)
    assert code == 1, lines + [err]
    assert _block(lines, "lib/delivery.py  old_helper  is gone, it was at line 9") == [
        "  ERROR      %s  still calls old_helper" % _at("apps/app.py", APP, "old_helper(1)"),
    ]


def test_a_removed_class_is_an_error_where_it_is_still_made(checkout, capsys):
    root = checkout()
    _edit(root, "lib/delivery.py",
          "class Journal:\n    def __init__(self, path, *, owner=None):\n        self.path = path\n", "")
    code, lines, err = _run(root, capsys)
    assert code == 1, lines + [err]
    assert _block(lines, "lib/delivery.py  class Journal  is gone, it was at line 13") == [
        "  ERROR      %s  still calls Journal" % _at("apps/app.py", APP, 'Journal("p"'),
    ]


def test_a_constructor_call_is_checked_against_init(checkout, capsys):
    root = checkout()
    _edit(root, "lib/delivery.py", "def __init__(self, path, *, owner=None):", "def __init__(self, path):")
    code, lines, err = _run(root, capsys)
    assert code == 1, lines + [err]
    assert _block(lines, "lib/delivery.py:14  Journal.__init__") == [
        "  signature changed",
        "    was  __init__(self, path, *, owner=...)",
        "    now  __init__(self, path)",
        "  ERROR      %s  passes owner=, which Journal.__init__ does not accept"
        % _at("apps/app.py", APP, 'Journal("p"'),
    ]


def test_a_required_parameter_left_out_is_a_warning_and_kwargs_cannot_be_checked(checkout, capsys):
    root = checkout()
    _edit(root, "lib/delivery.py", "*, rivals=None, timeout=30", "*, label, rivals=None, timeout=30")
    code, lines, err = _run(root, capsys)
    assert code == 0, lines + [err]
    block = _block(lines, "lib/delivery.py:1  deliver")
    assert block[-2:] == [
        "  WARNING    %s  does not pass label, which deliver requires" % _at("apps/app.py", APP, "rivals=[1]"),
        "  unchecked  %s  passes *args or **kwargs, so it cannot be checked for label"
        % _at("apps/spread.py", SPREAD, "deliver(page, req, **kw)"),
    ]
    assert _summary(lines).startswith("0 errors, 1 warning, 2 call sites")


# -- what is never an error ----------------------------------------------------

def test_a_same_named_method_of_another_class_is_unresolved_and_never_an_error(checkout, capsys):
    """thing.fetch() may be Fetcher.fetch or Other.fetch, and nothing
    here can say which. It is listed, with what would not fit, and the run
    still passes. Other().fetch() plainly is Other's, and is only counted."""
    root = checkout()
    _edit(root, "lib/fetch.py", "def fetch(self, url):", "def fetch(self, url, *, retries=3):")
    code, lines, err = _run(root, capsys)
    assert code == 0, lines + [err]
    assert _block(lines, "lib/fetch.py:2  Fetcher.fetch") == [
        "  signature changed",
        "    was  fetch(self, url)",
        "    now  fetch(self, url, *, retries=...)",
        "  ok         %s" % _at("apps/app.py", APP, 'Fetcher().fetch("u")'),
        "  ok         %s" % _at("lib/fetch.py", FETCH, "self.fetch(url)"),
        "  unresolved %s  if it is this one, it passes mode=, which Fetcher.fetch does not accept"
        % _at("apps/app.py", APP, "thing.fetch("),
        "  1 call named fetch reaches another definition and is not listed",
    ]
    assert _summary(lines).startswith("0 errors, 0 warnings, 3 call sites (2 resolved, 1 unresolved)")


def test_a_function_moved_away_and_imported_back_is_not_an_error(checkout, capsys):
    """Its old module still passes the name on, so the old import works,
    and the calls are checked against where it went."""
    root = checkout()
    _edit(root, "lib/delivery.py", "def old_helper(x):\n    return x\n",
          "from lib.helpers import old_helper  # noqa: E402,F401\n")
    _write(root, "lib/helpers.py", "def old_helper(x, *, strict=False):\n    return x\n")
    code, lines, err = _run(root, capsys)
    assert code == 0, lines + [err]
    assert _block(lines, "lib/delivery.py  old_helper  is gone, it was at line 9") == [
        "  the module still binds the name another way, by an import or an",
        "  assignment, so its callers reach that and are checked there",
    ]
    assert _summary(lines).endswith("and 1 new function checked")


# -- where it looks ------------------------------------------------------------

def test_untracked_files_are_read_as_callers_and_as_definitions(checkout, capsys):
    """A file nobody has added to git yet is part of the change. A caller
    in one is checked, and a function new in one has its callers checked.
    A virtual environment holds somebody else's code and is left alone."""
    root = checkout()
    _edit(root, "lib/delivery.py", "*, rivals=None, timeout=30", "*, timeout=30")
    extra = '''
from lib.delivery import deliver


def helper(a, *, b=1):
    return a


def go(page, req):
    helper(1, c=2)
    return deliver(page, req, rivals=[])
'''
    _write(root, "apps/extra.py", extra)
    _write(root, ".venv/Lib/site-packages/thing.py",
           "from lib.delivery import deliver\n\ndeliver(1, 2, rivals=3)\n")
    code, lines, err = _run(root, capsys)
    assert code == 1, lines + [err]
    assert lines[0].endswith(", in 2 changed Python files, 1 of them untracked.")
    assert "  ERROR      %s  passes rivals=, which deliver does not accept" \
        % _at("apps/extra.py", extra, "rivals=[]") in _block(lines, "lib/delivery.py:1  deliver")
    assert _block(lines, "apps/extra.py:4  helper  is new") == [
        "    now  helper(a, *, b=...)",
        "  ERROR      %s  passes c=, which helper does not accept" % _at("apps/extra.py", extra, "c=2"),
    ]
    assert not any(".venv" in ln for ln in lines)
    assert _summary(lines).startswith("3 errors")


def test_imports_are_followed_the_way_python_would(checkout, capsys):
    """A relative import, and a bare `storage` that means the app's own
    storage.py, which passes the shared function on. The other app's
    storage.py has a now_iso of its own, so its call is not this one."""
    root = checkout(LAYERED)
    _edit(root, "core/pkg/storage.py", "def now_iso(stamp, zone=None):", "def now_iso(stamp):")
    code, lines, err = _run(root, capsys)
    assert code == 1, lines + [err]
    assert _block(lines, "core/pkg/storage.py:1  now_iso") == [
        "  signature changed",
        "    was  now_iso(stamp, zone=...)",
        "    now  now_iso(stamp)",
        "  ERROR      apps/one/one_site.py:5  passes zone=, which now_iso does not accept",
        "  ERROR      core/pkg/naming.py:5  passes zone=, which now_iso does not accept",
        "  1 call named now_iso reaches another definition and is not listed",
    ]


def test_a_file_it_cannot_parse_is_named_not_passed_over(checkout, capsys):
    """Half an edit is not a file with no functions in it."""
    root = checkout()
    _write(root, "apps/broken.py", "def half(:\n")
    code, lines, err = _run(root, capsys)
    assert code == 0, lines + [err]
    assert ("Could not parse apps/broken.py on disk (SyntaxError at line 1), "
            "so its functions were not compared.") in lines
    assert "No function changed since HEAD." in lines


def test_a_base_that_cannot_be_read_exits_2(checkout, capsys):
    root = checkout()
    code, lines, err = _run(root, capsys, base="no-such-ref")
    assert code == 2
    assert lines == []
    assert "cannot read the base 'no-such-ref'" in err


def test_what_it_prints_names_no_folder_of_the_machine(checkout, capsys):
    """Paths are relative to the checkout, with forward slashes, so the
    report can be pasted anywhere."""
    root = checkout()
    _edit(root, "lib/delivery.py", "*, rivals=None, timeout=30", "*, timeout=30")
    _, lines, _ = _run(root, capsys)
    text = "\n".join(lines)
    assert str(root).lower() not in text.lower() and "\\" not in text
