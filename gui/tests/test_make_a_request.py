"""Make a request starts a GitHub issue form in the person's own browser,
with nothing private in its address, on forms GitHub can read.

The link to the form carries its answers in its address, and GitHub has
that address as soon as the page opens, before anything is sent. So of a
sign-in address only its site goes, never a path, query or fragment, where
a sign-in page can carry a username, an email or a token. And the page's
script runs at all, which one name declared twice at its top stops.
"""
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
yaml = pytest.importorskip("yaml")

GUI = Path(__file__).resolve().parents[1]
FORMS = GUI.parent / ".github" / "ISSUE_TEMPLATE"


@pytest.fixture()
def panel():
    """The panel's own page, served from an invented address with nothing
    else answered, in Playwright's own Chromium. Errors the page's script
    throws are kept on it."""
    sync_api = pytest.importorskip("playwright.sync_api")
    html = (app_module.HTML.replace("__FOOTER__", "").replace("__VERSION__", "0.0.0")
            .replace("__SERVER_BAR__", "").replace("__SERVER__", "false"))
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--disable-extensions", "--disable-sync",
                                                "--disable-background-networking", "--no-first-run"])
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s" % str(e).strip().splitlines()[0])
        tab = chromium.new_page()
        tab.thrown = []
        tab.on("pageerror", lambda e: tab.thrown.append(str(e)))

        def answer(route):
            if route.request.url == "http://panel.test/":
                route.fulfill(status=200, content_type="text/html", body=html)
            else:
                route.abort()
        tab.route("**/*", answer)
        tab.goto("http://panel.test/")
        yield tab
        chromium.close()


def _ask(panel, values):
    """A provider request with these answers, its link as the sheet leaves
    it and what it said."""
    return panel.evaluate("""async values => {
        document.addEventListener('click', e => { if (e.target.id === 'rq-go') e.preventDefault(); }, true);
        await openRequest('provider');
        const all = Object.assign({'rq-provider': 'Acme Water', 'rq-category': 'Utility', 'rq-documents': 'monthly bills'}, values);
        for (const [id, v] of Object.entries(all)) $(id).value = v;
        $('rq-go').click();
        await new Promise(f => setTimeout(f, 30));
        return {href: $('rq-go').href, err: $('rq-err').hidden ? '' : $('rq-err').textContent, done: !$('rq-done').hidden};
    }""", values)


def test_the_page_script_runs(panel):
    assert panel.thrown == []
    assert panel.evaluate("typeof openRequest === 'function' && typeof reportLink === 'function'")


def test_the_page_script_declares_each_name_once():
    """Two pieces of the panel each declaring the same name at the top of
    the one script stop the whole page, every button with it."""
    script = (GUI / "static" / "app.js").read_text(encoding="utf-8")
    names = re.findall(r"^(?:async\s+)?(?:const|let|var|function\*?|class)\s+([A-Za-z_$][\w$]*)", script, re.M)
    twice = sorted({n for n in names if names.count(n) > 1})
    assert names and not twice, twice


@pytest.mark.parametrize("typed, site", [
    ("https://secure.acme-water.com/login?login_hint=pat.doe%40example.com&state=a1b2#step2", "https://secure.acme-water.com"),
    ("www.acme-water.com/account/12345678", "https://www.acme-water.com"),
    ("http://acme-water.com:8443/sso/USERNAME", "http://acme-water.com"),
])
def test_only_the_site_of_a_sign_in_address_goes(panel, typed, site):
    got = _ask(panel, {"rq-url": typed})
    assert got["done"] and not got["err"]
    query = parse_qs(urlsplit(got["href"]).query)
    assert query["url"] == [site]
    assert "%40" not in got["href"] and "@" not in got["href"] and "#" not in got["href"]
    said = " ".join(v for values in query.values() for v in values)
    for private in ("login", "pat.doe", "example.com", "a1b2", "step2", "12345678", "USERNAME", "8443", "sso"):
        assert private not in said, private


@pytest.mark.parametrize("typed", ["https://pat@acme-water.com", "pat.doe@example.com", "acme water",
                                   "ftp://acme-water.com", "javascript:alert(1)", "https://localhost"])
def test_a_sign_in_address_that_is_not_a_site_is_refused(panel, typed):
    got = _ask(panel, {"rq-url": typed})
    assert not got["done"] and "Never a username" in got["err"]
    assert got["href"].endswith("/issues/new/choose"), "the link is left as it was"


# -- the forms GitHub reads --------------------------------------------------------
#
# GitHub's issue form syntax: a name, a description and a body of elements,
# each a markdown, input, textarea, dropdown or checkboxes. Every element but
# markdown has a label, ids are letters, digits, - and _, unique, and so are
# labels, and a dropdown's options are unique, with None reserved.

KINDS = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def _forms():
    return sorted(p for p in FORMS.glob("*.yml") if p.name != "config.yml")


@pytest.mark.parametrize("path", _forms(), ids=lambda p: p.name)
def test_every_issue_form_is_one_github_reads(path):
    form = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(form, dict)
    assert set(form) <= {"name", "description", "title", "labels", "assignees", "projects", "type", "body"}, set(form)
    assert isinstance(form.get("name"), str) and form["name"].strip()
    assert isinstance(form.get("description"), str) and form["description"].strip()
    assert isinstance(form.get("body"), list) and form["body"]
    assert any(e.get("type") != "markdown" for e in form["body"]), "a form needs a field"
    ids, labels = [], []
    for element in form["body"]:
        kind = element.get("type")
        assert kind in KINDS, kind
        assert set(element) <= {"type", "id", "attributes", "validations"}, set(element)
        attrs = element.get("attributes") or {}
        if kind == "markdown":
            assert isinstance(attrs.get("value"), str) and attrs["value"].strip()
            assert "id" not in element and "validations" not in element
            continue
        assert isinstance(attrs.get("label"), str) and attrs["label"].strip()
        labels.append(attrs["label"].strip())
        if "id" in element:
            assert re.fullmatch(r"[A-Za-z0-9_-]+", str(element["id"])), element["id"]
            ids.append(element["id"])
        if "validations" in element:
            assert set(element["validations"]) <= {"required"}
            assert isinstance(element["validations"]["required"], bool)
        if kind == "dropdown":
            options = attrs.get("options")
            assert isinstance(options, list) and options
            assert all(isinstance(o, str) and o.strip() for o in options)
            assert len(set(options)) == len(options)
            assert not any(o.strip().lower() == "none" for o in options), "None is reserved"
        if kind == "checkboxes":
            options = attrs.get("options")
            assert isinstance(options, list) and options
            for option in options:
                assert isinstance(option, dict) and isinstance(option.get("label"), str) and option["label"].strip()
                assert set(option) <= {"label", "required"}
    assert len(set(ids)) == len(ids), ids
    assert len(set(labels)) == len(labels), labels


def test_each_answer_the_sheet_sends_is_a_field_of_its_form():
    """GitHub fills a field from the address only by that field's id, so
    an answer sent under any other name is lost."""
    sent = {"provider-request.yml": ("provider", "category", "url", "documents"),
            "feature-request.yml": ("area", "what", "why", "importance", "version", "computer")}
    for name, keys in sent.items():
        form = yaml.safe_load((FORMS / name).read_text(encoding="utf-8"))
        ids = {e.get("id") for e in form["body"]}
        assert set(keys) <= ids, set(keys) - ids
