"""Every app counts every password field in the page, unless it is named here.

Consorsbank keeps its sign-in window in every page and draws it only when
asked, so counting every password field read each signed-in page as signed
out and refused every recording a tester started (#178). Its site module
sets PASSWORD_FIELD, which has its own looks_signed_out and the core's
recorder count only the fields the page draws. That is right only where a
site is known to keep a window like that, since a field kept out of sight
anywhere else may be the next step of a sign-in. So an app sets
PASSWORD_FIELD, or counts only drawn password fields in a check of its own,
only when it is named below with its reason, and then only to the one value
the core takes.

Nothing finds an app by its name. Every module of every app is read.
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core import recorder  # noqa: E402

NAMED = {
    "consorsbank": "Its sign-in window sits in every page, the bank's own included, inside web "
                   "components that draw it only when it is asked for. A tester's survey of a "
                   "signed-in page counted the one password field the public home page holds, "
                   "which headless Chromium finds with no box (#178).",
    "sparkassepc": "The signed-in Postfach keeps a password field in hidden sign-in UI. "
                   "The contributor's live session had the Postfach form and document rows "
                   "but no visible password field (#216).",
}

MODULES = sorted(p for p in REPO.glob("apps/*/*.py") if not p.name.startswith("test_"))


def _password_field(tree):
    """What a module sets PASSWORD_FIELD to, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PASSWORD_FIELD" for t in node.targets):
            return node.value.value if isinstance(node.value, ast.Constant) else node
    return None


def _counts_only_drawn(tree) -> bool:
    """A password selector that keeps only what the page draws."""
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
               and "password" in n.value.lower() and ":visible" in n.value
               for n in ast.walk(tree))


def census():
    found = {}
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        value = _password_field(tree)
        if value is not None or _counts_only_drawn(tree):
            found.setdefault(path.parent.name, set()).add(path.name)
    return found


def test_only_a_named_app_counts_only_the_password_fields_a_page_draws():
    found = census()
    assert set(found) == set(NAMED), (
        "counting only drawn password fields needs a reason here, as #178 gave Consorsbank. "
        "Found %s, named %s" % (sorted(found), sorted(NAMED)))


def test_a_named_app_sets_the_one_value_the_core_takes():
    for app in NAMED:
        tree = ast.parse((REPO / "apps" / app / ("%s_site.py" % app)).read_text(encoding="utf-8"))
        assert _password_field(tree) == recorder.DRAWN_PASSWORD_FIELD, app


def test_a_named_apps_own_check_counts_the_same_fields_the_recorder_does():
    """Its looks_signed_out reads PASSWORD_FIELD, so the app and the
    recorder never disagree about which fields make a sign-in page."""
    for app in NAMED:
        path = REPO / "apps" / app / ("%s_site.py" % app)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        [fn] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "looks_signed_out"]
        assert any(isinstance(n, ast.Name) and n.id == "PASSWORD_FIELD" for n in ast.walk(fn)), app
        # A selector, not the docstring's words.
        literals = [n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and "password" in n.value and "[type" in n.value]
        assert not literals, "%s counts a password selector of its own: %s" % (app, literals)


def test_the_census_finds_an_app_that_counts_only_drawn_fields():
    tree = ast.parse('def f(page):\n    return page.locator("input[type=\'password\']:visible").count()\n')
    assert _counts_only_drawn(tree)
    assert _password_field(ast.parse('PASSWORD_FIELD = "x"\n')) == "x"
    assert not _counts_only_drawn(ast.parse('S = "input[type=\'password\']"\n'))
