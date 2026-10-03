"""--login says a session is signed in only where it saw what a signed-in
page shows.

Walmart's --login printed Success while its own log said the purchase
history never appeared. It threw away what its look at the orders page
found, and said Success whenever one look found neither a check nor a
sign-in page, and a page still blank while a bot check decides has
neither. Ten more receipt apps asked the same way, and every document app
whose documents page did not come said "Connected and signed in" all the
same.

So in every app, a line that says a session is signed in is printed only
in the branch of a test on what the look at the page found, and never in
an else. The lines are found by their words, the claim itself, rather than
by which app they are in or what the function around them is called.
"""
import ast
import io
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Saying a session is signed in, in each of the ways the apps say it.
CLAIM = re.compile(r"success|signed-in session detected|connected and signed in|"
                   r"connected to your signed-in", re.I)
# What the apps call the answer their look at the page gave. The list came,
# the documents page opened, or the page asked for its orders.
EVIDENCE = {"listed", "ok", "request"}

# Still asking the old way. They were left out on 2026-09-29 because
# another session had them open for the 0.41.0 round, and when the rest
# landed on 2026-10-03 they were still to do. test_the_ones_left_are_still_to_do
# keeps this from outliving their repair.
LEFT = {"kroger", "meijer", "target"}


def entries():
    out = []
    for app in sorted((REPO / "apps").iterdir()):
        if not app.is_dir():
            continue
        found = list(app.glob("*_docs.py")) + list(app.glob("*_receipts.py"))
        if found:
            out.append(found[0])
    return out


ENTRIES = entries()
IDS = [p.parent.name for p in ENTRIES]


def printed_words(call):
    """The literal words a print call prints, f-string parts included."""
    words = []
    for node in ast.walk(call):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            words.append(node.value)
    return " ".join(words)


def claims(path):
    """Each line cmd_login prints that says a session is signed in, with the
    test of the if it is printed under and whether it is in that if's else.
    (words, test, in_else), and test is None when no if holds it."""
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    login = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "cmd_login"]
    out = []

    def visit(nodes, under):
        for node in nodes:
            if isinstance(node, ast.If):
                visit(node.body, (node.test, False))
                visit(node.orelse, (node.test, True))
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                visit(node.body, under)
                visit(node.orelse, under)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                visit(node.body, under)
            elif isinstance(node, ast.Try):
                visit(node.body, under)
                for handler in node.handlers:
                    visit(handler.body, under)
                visit(node.orelse, under)
                visit(node.finalbody, under)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            else:
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                            and call.func.id == "print"):
                        words = printed_words(call)
                        if CLAIM.search(words):
                            out.append((words, under[0] if under else None,
                                        under[1] if under else False))

    for fn in login:
        visit(fn.body, None)
    return out, login


def assigned_from_a_look(name, login):
    """The name is set in cmd_login from what a call returned."""
    for fn in login:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                for target in node.targets:
                    names = [t.id for t in ast.walk(target) if isinstance(t, ast.Name)]
                    if name in names:
                        return True
    return False


def breaks_the_rule(path):
    """What in this app's cmd_login claims a session it did not see."""
    found, login = claims(path)
    wrong = []
    for words, test, in_else in found:
        if test is None:
            wrong.append("said with no test around it: %r" % words)
        elif in_else:
            wrong.append("said in an else: %r" % words)
        elif not (isinstance(test, ast.Name) and test.id in EVIDENCE
                  and assigned_from_a_look(test.id, login)):
            wrong.append("said under a test of something other than what the look "
                         "found (%s): %r" % (ast.unparse(test), words))
    return wrong


def test_there_are_apps_to_check():
    assert len(ENTRIES) > 50


def test_the_check_finds_what_it_looks_for():
    """Not a check that passes because it finds nothing to look at. Nearly
    every app says Success somewhere in cmd_login, and each of those lines
    is found."""
    with_a_claim = [p for p in ENTRIES if claims(p)[0]]
    assert len(with_a_claim) > 50, [p.parent.name for p in with_a_claim]


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_login_claims_only_the_session_it_saw(entry):
    if entry.parent.name in LEFT:
        pytest.skip("still asking the old way, see LEFT")
    assert not breaks_the_rule(entry)


@pytest.mark.parametrize("app", sorted(LEFT))
def test_the_ones_left_are_still_to_do(app):
    """An app taken off LEFT once it is repaired, so the list never hides
    one that is fine, or one that went back to the old way."""
    [entry] = [p for p in ENTRIES if p.parent.name == app]
    assert breaks_the_rule(entry), "%s is repaired, so take it off LEFT" % app


def test_the_rule_catches_the_old_way(tmp_path):
    """The shape Walmart shipped, one look and Success in the else."""
    old = '''
class App:
    def cmd_login(self):
        page = self.page()
        site.goto_orders(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}")
        elif site.looks_signed_out(page):
            print("Connected, but it shows the signed-out page.")
        else:
            print("Success: connected to your signed-in session.")
'''
    new = old.replace("        site.goto_orders(page)\n        challenge = site.detect_security_challenge(page)\n",
                      "        listed, challenge = self._look_at_orders(page)\n").replace(
        "        else:\n            print(\"Success", "        elif listed:\n            print(\"Success")
    sample = tmp_path / "sample_receipts.py"
    sample.write_text(old, encoding="utf-8")
    assert breaks_the_rule(sample)
    sample.write_text(new, encoding="utf-8")
    assert not breaks_the_rule(sample), new
