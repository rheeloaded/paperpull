"""A NetBenefits login with several employers and plans, offline.

The page is a spy that answers the way the surveyed site did. A "Choose a
Plan" page lists every plan as a plain link whatever plan the site is
remembering. The Statements address shows the remembered plan's
Statements page, or a "Select Account" page when no plan is remembered.
One plan's address goes to the Fidelity retail sign-in. Every address the
app loads, every look ahead and every statement it makes is written down,
with the plan the site had chosen at the time, so a test can say what was
never done as well as what was."""
import hashlib
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  (binds this provider's AppSpec)
import netbenefits_site as site
import netbenefits_docs as docs
from paperpull_core import intake, listing, receipt_pdf
from paperpull_core.models import State
from paperpull_core.run_reporting import ListNotRead
from paperpull_core.testkit import receipt_app, text_pdf

BARE = site.URLS["documents"]
CHOOSER = site.CHOOSER_URL
LINK = "/mybenefits/DefinedContributions/navigation/dc/OnlineStatement?plan=%s&"
OPTION = "/mybenefits/savings2/navigation/dc/OnlineStatement?&client=%s&plan=%s"
EMP_A, EMP_B = "900000001", "900000002"
P403, P457, PDCP, PXR = "41403", "41457", "41400", "41401"
IDS = (EMP_A, EMP_B, P403, P457, PDCP, PXR)
NAMES = {PXR: "NORTH-STAR MEDICAL GROUP", P403: "ABC 403(B) PLAN", PDCP: "ABC DCP", P457: "ABC 457(B) PLAN"}
CLIENTS = {PXR: EMP_B, P403: EMP_A, PDCP: EMP_A, P457: EMP_A}
NB_LOGIN = "https://nb.fidelity.com/static/mybenefits/netbenefitslogin/"


def plan_of(path):
    ids = site.plan_ids(path)
    return ids[1] if ids else None


class Locator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    def count(self):
        if "client-name" in self.sel:
            return 1 if self.page.header_employer() else 0
        if "password" in self.sel:
            return 1 if self.page.url.startswith(NB_LOGIN) else 0
        if "frmRequest" in self.sel:
            return 1 if self.page.kind in ("statements", "single") else 0
        return 1

    def inner_text(self, timeout=None):
        if "client-name" in self.sel:
            return self.page.header_employer()
        return self.page.body()

    def all_inner_texts(self):
        if self.sel == site.HEADINGS:
            return self.page.headings()
        return [self.page.body()]


class Page:
    """Plans by their number. 'ok' is chosen by the look ahead, 'link' only
    by loading its own address, 'retail' redirects to the retail sign-in
    (as one plan's did on the surveyed login), 'sticky' is never chosen and
    leaves the site on the plan chosen before, 'login' is chosen and then
    the site signs the session out, 'other' answers with another plan's
    page. `links` is what the Choose a Plan page lists (None, no such page),
    `remembered` the plan the site starts on (None, the Select Account
    page)."""

    def __init__(self, behaviors=None, links=None, remembered=None, single_heading=None):
        self.behaviors = dict(behaviors or {})
        self.links = links
        self.in_context = remembered
        self.single_heading = single_heading
        self.signed_in = True
        self.signs_out = False
        self.url, self.kind = BARE, "blank"
        self.gotos, self.probes, self.made = [], [], []
        self.names = dict(NAMES)
        self.bare_probes, self.bare_redirects = 0, False
        self.employer = ""
        # The employer the header names by the plan the site has chosen,
        # for a plan not named here `employer`.
        self.employers = {}
        # Where the Choose a Plan address lands, when not on its own page,
        # and what a Statements page shows besides its heading.
        self.chooser_lands = None
        self.aside = ""

    def header_employer(self):
        return self.employers.get(self.in_context, self.employer)

    def body(self):
        if self.kind == "chooser":
            return "Choose a Plan " + " ".join(t for t, _ in self.links or [])
        if self.kind == "statements":
            return "Home %s (%s) Statements Time period Get statement %s" % (
                self.names[self.in_context], self.in_context, self.aside)
        if self.kind == "single":
            return "%s (12345) Statements Get statement" % self.single_heading
        if self.kind == "select":
            return "Select Account The page you've chosen requires you to select an account."
        return ""

    def headings(self):
        """The page's headings, where a Statements page names its plan."""
        if self.kind == "statements":
            return ["%s (%s)" % (self.names[self.in_context], self.in_context), "Statements"]
        if self.kind == "single":
            return ["%s (12345)" % self.single_heading, "Statements"]
        if self.kind == "chooser":
            return ["Choose a Plan"]
        if self.kind == "select":
            return ["Select Account"]
        return []

    def title(self):
        return "Fidelity NetBenefits"

    def locator(self, sel):
        return Locator(self, sel)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **kw):
        self.gotos.append(url)
        if self.signs_out:
            self.url, self.kind = NB_LOGIN, "login"
            return
        self.url = url
        if url == CHOOSER:
            self.kind = "chooser" if self.links is not None else "single" if self.single_heading else "select"
            self.url = self.chooser_lands or url
            return
        if url == BARE:
            if self.in_context:
                self.kind = "statements"
            else:
                self.kind = "single" if self.single_heading else "select"
            return
        raise AssertionError("a plan's own address was loaded: " + url)

    def evaluate(self, js, arg=None):
        if js == site._READ_CHOOSER_JS:
            if self.kind != "chooser":
                return None
            return [{"text": t, "value": v, "disabled": False} for t, v in self.links]
        if js == site._READ_CHOICES_JS:
            if self.kind != "select":
                return None
            return [{"text": "Select an account", "value": "", "disabled": True}] + [
                {"text": NAMES[p], "value": OPTION % (CLIENTS[p], p), "disabled": False} for p in NAMES]
        if js == site._SIGNED_IN_JS:
            return self.signed_in
        if js == intake.reading(site._MAKE_JS):
            self.made.append(self.in_context)
            return {"status": 200, "isStatement": True, "title": "Statement Details"}
        if js == site._PROBE_JS:
            plan = plan_of(arg["path"])
            if plan is None:                       # the Statements address itself
                self.bare_probes += 1
                return {"kind": "page", "status": 200, "origin": True,
                        "redirected": self.bare_redirects, "password": False}
            self.probes.append(plan)
            how = self.behaviors.get(plan, "ok")
            if how == "retail" or not self.signed_in:
                return {"kind": "redirect"}
            if how == "other":                     # an answer from somewhere else on the site
                return {"kind": "page", "status": 200, "origin": True, "redirected": True,
                        "password": False}
            if how in ("ok", "login"):
                self.in_context = plan
            if how == "login":
                self.signs_out = True
            # As live, a plain 200 at the link itself whose body is only the
            # selector, never the Statements page, whether or not it chose.
            return {"kind": "page", "status": 200, "origin": True, "redirected": False,
                    "password": False}
        raise AssertionError("an unexpected script ran")


def chooser_links(*plans):
    return [(NAMES[p], LINK % p) for p in (plans or NAMES)]


def multi_page(remembered=P457, **behaviors):
    return Page(behaviors, links=chooser_links(), remembered=remembered)


# Which plans have which quarters. A statement belongs to the plan the
# site had chosen when it was made, as on the real site.
HAVE = {P457: {"04/01/2026-06/30/2026", "01/01/2026-03/31/2026"},
        PXR: {"04/01/2026-06/30/2026"}}
# What each plan's statement names, when that is not just its own plan.
STATEMENT_NAMES = {}


def render_text(pg, html, out):
    body = re.sub(r"<[^>]+>", "", html.split("<body>", 1)[-1])
    Path(out).write_bytes(text_pdf(body.split("|")))


PLAN_OF_LABEL = {"ABC 457(b) Plan": P457, "North-Star Medical Group": PXR}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    site._plan_in_use["plan"] = None
    site._employers_seen.clear()
    site._employers_named.clear()
    site._last_navigation["at"] = 0.0
    site.set_private_words([])
    real = site.periods
    monkeypatch.setattr(site, "periods",
                        lambda kind, today=None, first_year=site.FIRST_YEAR: real(kind, date(2026, 9, 18), 2025))
    yield
    site.set_private_words([])


def statements_by_plan(page, calls, single=None, header=None):
    """make_statement for the site. Like the real one it asks the tab for
    the plan in use first, so a statement is never made with another plan
    chosen, and the answer comes from the plan the site has chosen. `header`
    is what the statement's own header names, when not another employer."""
    def make(pg, date_range, want_html=False):
        plan = site._plan_in_use.get("plan")
        if plan and not site._shows_plan(pg, plan):
            reason = site.open_plan(pg, plan)
            if reason != site.OPENED:
                raise site.PlanDidNotOpen(reason)
        chosen = page.in_context if plan else None
        calls.append((chosen, date_range, want_html))
        have = single if chosen is None else HAVE.get(chosen, set())
        if date_range not in have:
            return {"status": 200, "title": "Online Statement error page", "isStatement": False, "html": ""}
        named = STATEMENT_NAMES.get(chosen, [NAMES.get(chosen, "SOME CORP. RETIREMENT SAVINGS PLAN")])
        return {"status": 200, "title": "Statement Details", "isStatement": True,
                # The statement's own header names whichever employer the
                # site remembers, which is never the label.
                "plan": header or "NORTH-STAR MEDICAL GROUP, INC. 401(K) PROFIT SHARING PLAN", "period": date_range,
                "html": "<html><head></head><body>%s|Statement Period %s</body></html>" % (
                    "|".join(named), date_range)}
    return make


def app_on(tmp_path, page):
    app = receipt_app(docs, tmp_path, owner="")
    app.page = lambda: page
    app._on_its_site = lambda: page
    return app


def no_ids_in(text):
    return not any(i in text for i in IDS)


def labels_by_date(app):
    return sorted((r["account"], r["date"]) for r in app.discovery.data.values())


def plans_of(page):
    return {plan_of(p["path"]): p for p in site.read_plan_choices(page)}


# -- the plan's name ----------------------------------------------------------------

def test_a_plan_name_reads_like_one():
    assert site.option_label("ABC 457(B) PLAN") == "ABC 457(b) Plan"
    assert site.option_label("NORTH-STAR MEDICAL GROUP") == "North-Star Medical Group"
    assert site.option_label("ABC DCP") == "ABC DCP"
    assert site.option_label("LAKESIDE COLLEGE OF ARTS 401(K) (12345)") == "Lakeside College of Arts 401(k)"
    assert site.option_label("ACME INC. 401(K) PLAN") == "Acme Inc. 401(k) Plan"
    assert site.option_label("Acme 401(k) Plan") == "Acme 401(k) Plan"
    assert site.option_label("  ") == ""


def test_a_plan_name_carrying_its_number_loses_it():
    plan = site.plan_from_option("ABC PLAN %s" % P457, LINK % P457)
    assert plan["label"] == "ABC Plan" and no_ids_in(plan["label"])
    glued = site.plan_from_option("Employer%sPlan" % P457, OPTION % (EMP_A, P457))
    assert no_ids_in(glued["label"])
    overlap = site.plan_from_option("Employer12345Plan", OPTION % ("123", "12345"))
    assert "123" not in overlap["label"] and "45" not in overlap["label"]


# -- the lists of plans -------------------------------------------------------------

def test_the_choose_a_plan_page_lists_every_plan_whatever_the_site_remembers():
    page = multi_page(remembered=P457)
    plans = site.read_plan_choices(page)
    assert [p["label"] for p in plans] == ["North-Star Medical Group", "ABC 403(b) Plan",
                                           "ABC DCP", "ABC 457(b) Plan"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", p["digest"]) for p in plans)
    assert page.gotos == [CHOOSER, BARE]               # read, nothing pressed, no plan loaded
    assert page.probes == [] and page.made == []
    for p in plans:
        assert no_ids_in(p["label"]) and no_ids_in(p["digest"])


def test_a_choose_a_plan_page_with_one_plan_is_a_login_with_one_plan():
    page = Page(links=chooser_links(P457), single_heading="SOME CORP. RETIREMENT SAVINGS PLAN")
    assert site.read_plan_choices(page) == site.ONE_PLAN


def test_with_no_choose_a_plan_page_the_select_account_page_is_read():
    page = Page(links=None, remembered=None)
    plans = site.read_plan_choices(page)
    assert {p["label"] for p in plans} == {"North-Star Medical Group", "ABC 403(b) Plan",
                                           "ABC DCP", "ABC 457(b) Plan"}


def test_a_plan_keeps_one_key_whichever_list_it_came_from():
    by_link = site.plan_from_option(NAMES[P457], LINK % P457)
    by_option = site.plan_from_option(NAMES[P457], OPTION % (EMP_A, P457))
    assert by_link["digest"] == by_option["digest"]


def test_the_plan_ids_are_private_words():
    site.read_plan_choices(Page(links=None, remembered=None))
    said = site.redact("client %s plan %s and %s" % (EMP_A, P457, PXR))
    assert no_ids_in(said)


def test_a_link_off_the_statements_page_is_never_opened():
    plan = site.plan_from_option("RETAIL PLAN", "https://digital.fidelity.com/x?plan=2")
    assert plan["path"] == "" and plan["review"] == site.LEAVES_THE_SITE
    other = site.plan_from_option("OTHER", "/mybenefits/moneymovement/navigation/dc/loanwith?plan=2")
    assert other["path"] == ""
    page = multi_page()
    assert site.open_plan(page, plan) == site.LEAVES_THE_SITE
    assert page.gotos == [] and page.probes == []
    assert site.plan_from_option("Select an account", "") is None


def test_a_plan_list_read_back_must_still_be_what_this_app_wrote():
    plan = site.plan_from_option(NAMES[P457], LINK % P457)
    assert site.checked_plan(dict(plan)) == dict({k: plan[k] for k in ("label", "digest", "path", "heading")},
                                                 shared_name=False)
    assert site.checked_plan(dict(plan, digest="0" * 64)) is None
    assert site.checked_plan(dict(plan, path="https://digital.fidelity.com" + plan["path"])) is None


# -- choosing a plan ----------------------------------------------------------------

def test_a_plan_that_redirects_off_the_host_is_left_for_the_owner_and_never_loaded():
    page = multi_page(**{P403: "retail"})
    plans = plans_of(page)
    assert site.open_plan(page, plans[P403]) == site.REDIRECTS
    assert page.probes == [P403]
    assert not any(plan_of(u[len(site.WPS):]) == P403 for u in page.gotos if u.startswith(site.WPS))
    assert site._plan_in_use["plan"] is None


def test_a_plan_opens_by_its_look_ahead_and_the_statements_page_must_name_it():
    page = multi_page()
    plans = plans_of(page)
    page.gotos.clear()
    assert site.open_plan(page, plans[PXR]) == site.OPENED
    assert page.gotos == [BARE] and page.in_context == PXR
    assert site._plan_in_use["plan"]["digest"] == plans[PXR]["digest"]


def test_a_plan_the_look_ahead_does_not_choose_is_left_and_its_link_never_loaded():
    page = multi_page(**{PDCP: "link"})
    plans = plans_of(page)
    page.gotos.clear()
    assert site.open_plan(page, plans[PDCP]) == site.DID_NOT_OPEN
    assert page.gotos == [BARE] and page.in_context == P457


def test_a_heading_that_names_another_plan_refuses_the_plan():
    # The site stays on the remembered plan whatever is asked of it.
    page = multi_page(remembered=P457, **{PXR: "sticky"})
    plans = plans_of(page)
    assert site.open_plan(page, plans[PXR]) == site.DID_NOT_OPEN
    assert site._plan_in_use["plan"] is None


def test_two_plans_with_one_name_are_told_apart_by_their_number():
    page = Page({P457: "sticky"}, links=[("ABC 401(K) PLAN", LINK % P403), ("ABC 401(K) PLAN", LINK % P457)],
                remembered=P403)
    page.names.update({P403: "ABC 401(K) PLAN", P457: "ABC 401(K) PLAN"})
    plans = plans_of(page)
    assert all(p["shared_name"] for p in plans.values())
    assert site.open_plan(page, plans[P403]) == site.OPENED
    # The other plan's page is never shown, this one's is, under the same name.
    assert site.open_plan(page, plans[P457]) == site.DID_NOT_OPEN


def test_a_link_that_already_shows_its_number_still_opens():
    page = multi_page()
    plan = site.plan_from_option("ABC 457(B) PLAN (%s)" % P457, LINK % P457)
    plan["shared_name"] = True
    page.kind = "statements"
    assert site.open_plan(page, plan) == site.OPENED


def test_a_plan_address_answered_from_elsewhere_on_the_site_is_left():
    page = multi_page(**{PDCP: "other"})
    plans = plans_of(page)
    page.gotos.clear()
    assert site.open_plan(page, plans[PDCP]) == site.REDIRECTS
    assert page.gotos == []


def test_the_selector_answer_is_not_the_statements_page_and_the_heading_decides():
    # The live shape. The look ahead answers 200 with the selector page and
    # chooses the plan. The plan opens because the Statements page names it.
    page = multi_page(remembered=P457)
    plans = plans_of(page)
    assert site.open_plan(page, plans[P403]) == site.OPENED
    assert page.in_context == P403
    # One that answers the same but is not chosen is refused by the heading.
    page.behaviors[PDCP] = "sticky"
    assert site.open_plan(page, plans[PDCP]) == site.DID_NOT_OPEN


def test_a_sign_in_page_on_a_later_plan_is_session_expired():
    page = multi_page(**{P457: "login"})
    plans = plans_of(page)
    assert site.open_plan(page, plans[PXR]) == site.OPENED
    with pytest.raises(site.SessionExpired):
        site.open_plan(page, plans[P457])


def test_a_redirect_from_a_signed_out_session_is_session_expired_not_a_plan_to_review():
    page = multi_page()
    plans = plans_of(page)
    page.signed_in = False
    with pytest.raises(site.SessionExpired):
        site.open_plan(page, plans[PXR])


def test_the_keep_awake_reload_chooses_the_plan_in_use_again():
    page = multi_page()
    plans = plans_of(page)
    site.open_plan(page, plans[PDCP])
    page.probes.clear()
    site._last_navigation["at"] -= site.KEEP_AWAKE_SECONDS + 1
    site._keep_awake(page)
    assert page.probes == [PDCP] and page.in_context == PDCP


def test_a_statement_is_never_made_while_the_tab_shows_another_plan():
    page = multi_page()
    plans = plans_of(page)
    site.open_plan(page, plans[PDCP])
    page.in_context = PXR                         # chosen elsewhere, the tab reloaded
    page.probes.clear()
    site._last_navigation["at"] = time.monotonic()
    site.make_statement(page, "04/01/2026-06/30/2026")
    assert page.probes == [PDCP] and page.made == [PDCP]


def test_a_plan_that_will_not_open_again_is_its_own_failure_not_a_statement(monkeypatch, tmp_path):
    page = multi_page()
    plans = plans_of(page)
    site.open_plan(page, plans[PDCP])
    page.behaviors[PDCP] = "retail"
    site._last_navigation["at"] -= site.KEEP_AWAKE_SECONDS + 1
    with pytest.raises(site.PlanDidNotOpen) as e:
        site._keep_awake(page)
    assert e.value.reason == site.REDIRECTS
    monkeypatch.setattr(site, "make_statement", lambda *a, **k: (_ for _ in ()).throw(site.PlanDidNotOpen("x")))
    site._plan_in_use["plan"] = plans[PDCP]
    assert not site.download_document(page, "Quarterly Statement", "2026-06-30", tmp_path / "s.pdf",
                                      item_hint="04/01/2026-06/30/2026", plan=plans[PDCP])


def test_a_statement_request_that_is_redirected_is_session_expired(monkeypatch):
    class P:
        url = "https://workplaceservices.fidelity.com/mybenefits/savings2/navigation/dc/OnlineStatement"

        def locator(self, *_):
            return type("L", (), {"count": lambda s: 0})()

        def evaluate(self, js, arg=None):
            if js == site._SIGNED_IN_JS:
                return False                      # the session's own token call is refused too
            return {"status": 0, "stage": "token", "refused": True}
    monkeypatch.setattr(site, "_keep_awake", lambda page: None)
    with pytest.raises(site.SessionExpired):
        site.make_statement(P(), "01/01/2026-03/31/2026")


# -- discovery and download through the app -----------------------------------------

def test_a_remembered_plan_no_longer_names_every_statement(monkeypatch, tmp_path, caplog):
    """The live run that found this. The site remembered one plan, the app
    took the login for one with a single plan, and every statement was
    named after the employer in the statement's own header."""
    caplog.set_level("INFO")
    page = multi_page(remembered=P457, **{P403: "retail"})
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, calls))
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    assert labels_by_date(app) == [("ABC 457(b) Plan", "2026-03-31"), ("ABC 457(b) Plan", "2026-06-30"),
                                   ("North-Star Medical Group", "2026-06-30")]
    recs = list(app.discovery.data.values())
    assert all(r["plan"] for r in recs) and all(r["occurrence"] == 0 for r in recs)
    for rec in recs:                              # made with the plan it is filed under chosen
        assert (PLAN_OF_LABEL[rec["account"]], rec["item_id"], False) in calls
    assert app.stats["manual_review"] == 1        # ABC 403(b), left for the owner
    names = [docs.build_pdf_filename(r["date"], r["summary"], "", record=docs.Document.from_dict(r))
             for r in recs]
    assert "2026-06-30 NetBenefits Quarterly Statement - ABC 457(b) Plan.pdf" in names
    assert "2026-06-30 NetBenefits Quarterly Statement - North-Star Medical Group.pdf" in names
    for text in names + list(app.discovery.data) + [app.paths.discovery_json.read_text(), caplog.text]:
        assert no_ids_in(text)
    held = json.loads((app.paths.root / "plans.json").read_text())
    assert len(held) == 4 and no_ids_in(json.dumps([h["label"] for h in held.values()]))


def test_a_plan_whose_heading_does_not_match_gets_no_statement(monkeypatch, tmp_path):
    page = multi_page(remembered=P457, **{PXR: "sticky"})
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, calls))
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    assert "North-Star Medical Group" not in {r["account"] for r in app.discovery.data.values()}
    assert app.stats["manual_review"] == 1


def test_a_login_with_one_plan_is_listed_as_before(monkeypatch, tmp_path):
    page = Page(links=chooser_links(P457), single_heading="SOME CORP. RETIREMENT SAVINGS PLAN")
    calls = []
    monkeypatch.setattr(site, "make_statement",
                        statements_by_plan(page, calls, single={"04/01/2026-06/30/2026"}))
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    assert list(app.discovery.data) == ["Statement:2026-06-30:Quarterly Statement"]
    # The record v0.51.0 wrote, with none of the fields several plans use.
    assert not set(docs.PLAN_FIELDS) & set(app.discovery.data["Statement:2026-06-30:Quarterly Statement"])
    assert page.probes == []
    assert not (app.paths.root / "plans.json").exists() or json.loads(
        (app.paths.root / "plans.json").read_text()) == {}


def test_a_plan_left_for_review_is_written_down_before_a_later_sign_out(monkeypatch, tmp_path):
    page = multi_page(**{P403: "retail", P457: "login"})
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    app = app_on(tmp_path, page)
    with pytest.raises(site.SessionExpired):
        app.cmd_discover(quiet=True)
    held = json.loads((tmp_path / "out" / "plans.json").read_text())
    assert [h.get("last_result") for h in held.values() if h["label"] == "ABC 403(b) Plan"] == [site.REDIRECTS]
    assert [r["account"] for r in app.discovery.data.values()] == ["North-Star Medical Group"]


def test_a_plan_that_stops_opening_partway_is_left_and_the_next_plan_still_listed(monkeypatch, tmp_path):
    page = multi_page()
    good = statements_by_plan(page, [])

    def make(pg, date_range, want_html=False):
        if page.in_context == PXR:
            raise site.PlanDidNotOpen(site.REDIRECTS)
        return good(pg, date_range, want_html)
    monkeypatch.setattr(site, "make_statement", make)
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    assert {r["account"] for r in app.discovery.data.values()} == {"ABC 457(b) Plan"}
    assert app.stats["manual_review"] == 1


def test_a_later_run_without_a_list_uses_the_plans_it_kept(monkeypatch, tmp_path):
    page = multi_page()
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    app_on(tmp_path, page).cmd_discover(quiet=True)
    page.links = None                                # no Choose a Plan page this time
    site._plan_in_use["plan"] = None
    again = app_on(tmp_path, page)
    again.cmd_discover(quiet=True)
    assert len(again.discovery.data) == 3


def test_records_with_plans_and_no_list_stop_rather_than_file_one_plan(monkeypatch, tmp_path):
    page = multi_page()
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    app_on(tmp_path, page).cmd_discover(quiet=True)
    (tmp_path / "out" / "plans.json").unlink()
    page.links = None
    app = app_on(tmp_path, page)
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert app.stats["plans_unlisted"] == 1


def test_each_statement_is_made_with_its_own_plan_chosen(monkeypatch, tmp_path):
    page = multi_page()
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, calls))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app_on(tmp_path, page).cmd_discover(quiet=True)
    # A Resume, in a process that has listed nothing.
    site._plan_in_use["plan"] = None
    app = app_on(tmp_path, page)
    calls.clear()
    app.process(app._select())
    made = [(plan, r) for plan, r, html in calls if html]
    assert sorted(made) == sorted([(P457, "04/01/2026-06/30/2026"), (P457, "01/01/2026-03/31/2026"),
                                   (PXR, "04/01/2026-06/30/2026")])
    saved = sorted(p.name for p in (tmp_path / "out" / "Statements").iterdir())
    assert saved == ["2026-03-31 NetBenefits Quarterly Statement - ABC 457(b) Plan.pdf",
                     "2026-06-30 NetBenefits Quarterly Statement - ABC 457(b) Plan.pdf",
                     "2026-06-30 NetBenefits Quarterly Statement - North-Star Medical Group.pdf"]
    assert app.stats["failed"] == 0 and app.stats["statements"] == 3


def test_a_plan_missing_from_the_list_stops_the_run_and_fails_nothing(monkeypatch, tmp_path):
    page = multi_page()
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    app_on(tmp_path, page).cmd_discover(quiet=True)
    (tmp_path / "out" / "plans.json").unlink()
    page.links = None
    app = app_on(tmp_path, page)
    with pytest.raises(SystemExit) as stop:
        app.process(app._select())
    assert app.stats["plans_unlisted"] == 1 and app.stats["failed"] == 0
    assert not app.progress.data
    # A Resume would read the same plan list for its first document, so
    # the run leaves as one whose list did not end whole (#124).
    assert isinstance(stop.value, ListNotRead)
    assert listing.last(app) == listing.STOPPED


def test_a_plan_the_list_no_longer_shows_is_that_documents_review(monkeypatch, tmp_path):
    """The site listed its plans whole, without one a document was listed
    under. That is the document's own matter, as a record gone is. A stop
    here stopped every later run at the same document, a Run All too,
    since Discover keeps the document's record."""
    page = multi_page()
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app_on(tmp_path, page).cmd_discover(quiet=True)
    gone_plan = plans_of(page)[PXR]["digest"]
    page.links = chooser_links(P457, P403, PDCP)
    site._plan_in_use["plan"] = None
    app = app_on(tmp_path, page)
    listed = app._select()
    gone = [d for d in listed if d.plan == gone_plan]
    assert len(gone) == 1 and len(listed) == 3
    app.process(listed)
    assert app.stats["manual_review"] == 1 and app.stats["failed"] == 0
    assert app.stats["statements"] == 2
    assert app.progress.data[gone[0].key]["state"] == State.NEEDS_MANUAL_REVIEW.value


def test_a_statements_address_that_redirects_is_not_loaded():
    page = multi_page()
    plans = plans_of(page)
    page.gotos.clear()
    page.bare_redirects = True
    assert site.open_plan(page, plans[PXR]) == site.REDIRECTS
    assert page.bare_probes == 1 and page.gotos == []


def test_the_look_ahead_compares_addresses_without_the_pages_url_constructor():
    """The page shadows the global URL, so new URL() there throws, and the
    script once read every plan as redirected because of it."""
    assert "URL(" not in site._PROBE_JS
    assert "here.origin + path" in site._PROBE_JS



# -- a statement that covers several plans ------------------------------------------

SHARED = {P403, PDCP, P457}
Q2 = "04/01/2026-06/30/2026"


def three_plans_one_statement(monkeypatch, tmp_path, employer=""):
    monkeypatch.setitem(HAVE, P403, {Q2})
    monkeypatch.setitem(HAVE, PDCP, {Q2})
    monkeypatch.setitem(HAVE, P457, {Q2})
    combined = ["ABC 403(B) PLAN", "ABC DCP", "ABC 457(B) PLAN", "LAKESIDE COLLEGE OF ARTS"]
    for p in SHARED:
        monkeypatch.setitem(STATEMENT_NAMES, p, combined)
    page = multi_page()
    page.employer = employer
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, calls))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    return app, page, calls


def test_a_combined_statement_is_saved_once_for_the_plans_it_covers(monkeypatch, tmp_path):
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path)
    q2 = [app.discovery.data[k] for k in app.discovery.data if app.discovery.data[k]["date"] == "2026-06-30"]
    assert len(q2) == 4                                   # three ABC plans and North-Star
    calls.clear()
    app.process(app._select())
    saved = sorted(p.name for p in (tmp_path / "out" / "Statements").iterdir())
    assert saved == ["2026-06-30 NetBenefits Quarterly Statement - ABC 403(b), ABC 457(b) and ABC DCP Plans.pdf",
                     "2026-06-30 NetBenefits Quarterly Statement - North-Star Medical Group.pdf"]
    # Each plan's own request is made, and the three ABC plans' requests give
    # one statement, kept once.
    assert sorted(c[0] for c in calls if c[2]) == sorted([P403, PDCP, P457, PXR])
    done = [app.progress.data[k] for k in app.progress.data]
    assert len(done) == 4 and all(r["downloaded_ok"] for r in done)
    covered = [r for r in done if "covered by the combined statement" in (r.get("notes") or "")]
    assert len(covered) == 2 and all(saved[0] in r["notes"] and not r["pdf_path"] for r in covered)
    assert app.stats["manual_review"] == 0 and app.stats["failed"] == 0
    # A later run makes nothing again.
    calls.clear()
    app.process(app._select())
    assert not [c for c in calls if c[2]]


def test_a_combined_statement_takes_the_employers_name_when_the_statement_carries_it(monkeypatch, tmp_path):
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path, employer="LAKESIDE COLLEGE OF ARTS")
    app.process(app._select())
    saved = sorted(p.name for p in (tmp_path / "out" / "Statements").iterdir())
    assert "2026-06-30 NetBenefits Quarterly Statement - Lakeside College of Arts Plans.pdf" in saved


def test_a_remembered_employer_the_statement_does_not_carry_is_not_believed(monkeypatch, tmp_path):
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path, employer="NORTH-STAR MEDICAL GROUP, INC.")
    app.process(app._select())
    saved = sorted(p.name for p in (tmp_path / "out" / "Statements").iterdir())
    assert "2026-06-30 NetBenefits Quarterly Statement - ABC 403(b), ABC 457(b) and ABC DCP Plans.pdf" in saved


def test_a_statement_for_one_plan_is_filed_under_that_plan_as_before(monkeypatch, tmp_path):
    page = multi_page()
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    app.process(app._select())
    rec = next(r for r in app.progress.data.values() if r["account"] == "North-Star Medical Group")
    assert rec["pdf_filename"] == "2026-06-30 NetBenefits Quarterly Statement - North-Star Medical Group.pdf"
    assert not rec.get("covers")


def test_a_statement_naming_only_another_plan_is_refused(monkeypatch, tmp_path):
    monkeypatch.setitem(STATEMENT_NAMES, P457, ["NORTH-STAR MEDICAL GROUP"])
    page = multi_page()
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    app.process(app._select())
    saved = sorted(p.name for p in (tmp_path / "out" / "Statements").iterdir())
    assert not any("ABC 457(b)" in n for n in saved)
    refused = [r for r in app.progress.data.values() if r["account"] == "ABC 457(b) Plan"]
    assert refused and all(r["state"] == State.NEEDS_MANUAL_REVIEW.value for r in refused)
    assert app.stats["wrong_document"] == 2


def test_plan_names_are_found_however_the_pdf_spaced_them():
    plans = [site.plan_from_option(NAMES[p], LINK % p) for p in (P403, PDCP, P457, PXR)]
    named = site.plans_named("Your plans: ABC403(B)  and abc dcp\nABC 457(B) Plan", plans)
    assert [p["label"] for p in named] == ["ABC 403(b) Plan", "ABC DCP", "ABC 457(b) Plan"]


def test_a_later_process_finds_the_combined_statement_and_keeps_no_second_copy(monkeypatch, tmp_path):
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path)
    app.process(app._select())
    saved = sorted(p.name for p in (tmp_path / "out" / "Statements").iterdir())
    # The covered plans' records are gone, as for plans listed after the
    # statement was saved, and a new process is started.
    for key in [k for k, r in app.progress.data.items() if "covered by" in (r.get("notes") or "")]:
        del app.progress.data[key]
    app.progress.save()
    site._plan_in_use["plan"] = None
    again = app_on(tmp_path, page)
    calls.clear()
    again.process(again._select())
    # Their own requests are made, give the saved statement, and nothing is kept twice.
    assert len([c for c in calls if c[2]]) == 2
    assert sorted(p.name for p in (tmp_path / "out" / "Statements").iterdir()) == saved
    assert sum("covered by" in (r.get("notes") or "") for r in again.progress.data.values()) == 2


# -- a statement's digest, whatever pypdf read its text ----------------------------------

def test_a_statements_digest_holds_however_its_lines_were_broken():
    """pypdf 6.20 reads some statements with a line break fewer than 6.19
    did, sometimes with nothing left between two words."""
    one = site.statement_digest("Balance as of\n09/30/2031 Total\n12.34")
    assert one == site.statement_digest("Balance as of09/30/2031  Total 12.34")
    assert one == site.statement_digest(" Balance as of 09/30/2031\n\nTotal 12.34 ")
    assert one != site.statement_digest("Balance as of 09/30/2032 Total 12.34")
    # The older form, as 0.52.0 to 0.56.3 kept it, each run of whitespace one space.
    new, older = site.statement_digests("Balance as of\n09/30/2031 Total\n12.34")
    assert new == one
    assert older == hashlib.sha256(b"Balance as of 09/30/2031 Total 12.34").hexdigest()


def a_combined_statement_whose_covered_plans_are_listed_later(monkeypatch, tmp_path):
    """A combined statement saved, the plans it covers written down after
    it, as for plans listed later, and the saved record and file handed
    back to be aged."""
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path)
    app.process(app._select())
    for key in [k for k, r in app.progress.data.items() if "covered by" in (r.get("notes") or "")]:
        del app.progress.data[key]
    combined = next(r for r in app.progress.data.values() if r.get("covers"))
    return app, page, calls, combined, Path(combined["pdf_path"])


def process_again(app, page, calls, tmp_path):
    app.progress.save()
    site._plan_in_use["plan"] = None
    again = app_on(tmp_path, page)
    calls.clear()
    again.process(again._select())
    return again


def test_a_combined_statement_kept_by_an_older_version_still_covers_its_plans(monkeypatch, tmp_path):
    """A record of 0.52.0 to 0.56.3 holds the older digest, and its file
    may be gone, deleted after it was imported elsewhere."""
    app, page, calls, combined, saved = a_combined_statement_whose_covered_plans_are_listed_later(
        monkeypatch, tmp_path)
    combined["text_sha256"] = site.statement_digests(receipt_pdf.pdf_text(saved))[1]
    saved.unlink()
    names = saved_names(tmp_path)
    again = process_again(app, page, calls, tmp_path)
    assert len([c for c in calls if c[2]]) == 2
    assert saved_names(tmp_path) == names                    # no second copy kept
    assert sum("covered by" in (r.get("notes") or "") for r in again.progress.data.values()) == 2


def test_a_combined_statement_read_by_another_pypdf_still_covers_its_plans(monkeypatch, tmp_path):
    """The record kept the digest of the text an older pypdf read, a line
    break where this one reads none, and the file is still there."""
    app, page, calls, combined, saved = a_combined_statement_whose_covered_plans_are_listed_later(
        monkeypatch, tmp_path)
    text = receipt_pdf.pdf_text(saved)
    k = next(i for i in range(1, len(text)) if text[i - 1].isalpha() and text[i].isalpha())
    combined["text_sha256"] = site.statement_digests(text[:k] + "\n" + text[k:])[1]
    assert combined["text_sha256"] not in site.statement_digests(text)
    names = saved_names(tmp_path)
    again = process_again(app, page, calls, tmp_path)
    assert len([c for c in calls if c[2]]) == 2
    assert saved_names(tmp_path) == names                    # no second copy kept
    assert sum("covered by" in (r.get("notes") or "") for r in again.progress.data.values()) == 2


def test_a_statement_another_plan_saved_is_not_taken_for_a_different_one(monkeypatch, tmp_path):
    """Reading the saved file again covers a plan only with the very same
    text, here the file holds another statement."""
    app, page, calls, combined, saved = a_combined_statement_whose_covered_plans_are_listed_later(
        monkeypatch, tmp_path)
    combined["text_sha256"] = "0" * 64
    saved.write_bytes(text_pdf(["ABC 403(B) PLAN", "ABC DCP", "ABC 457(B) PLAN", "another quarter"]))
    names = saved_names(tmp_path)
    again = process_again(app, page, calls, tmp_path)
    by_it = "covered by the combined statement " + combined["pdf_filename"]
    assert not any((r.get("notes") or "").endswith(by_it) for r in again.progress.data.values())
    assert len(saved_names(tmp_path)) == len(names) + 1     # the next plan's own copy is kept


def test_download_again_makes_the_combined_statement_again(monkeypatch, tmp_path):
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path)
    app.process(app._select())
    site._plan_in_use["plan"] = None
    again = app_on(tmp_path, page)
    again.args.redownload = True
    calls.clear()
    again.process(again._select())
    assert len([c for c in calls if c[2]]) == 4          # each plan's own request once
    covered = [r for r in again.progress.data.values() if "covered by" in (r.get("notes") or "")]
    assert len(covered) == 2 and not any(r["pdf_path"] for r in covered)


def test_download_again_rebuilds_a_deleted_combined_statement_for_a_covered_plan(monkeypatch, tmp_path):
    """A file saved on an earlier run may be the one the person deleted, so
    under Download again only a file this run saved covers a plan."""
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path)
    app.process(app._select())
    for p in (tmp_path / "out" / "Statements").iterdir():
        p.unlink()
    site._plan_in_use["plan"] = None
    again = app_on(tmp_path, page)
    again.args.redownload = True
    one = [d for d in again._select() if d.plan == site.plan_digest(P403)]
    again.process(one)
    assert saved_names(tmp_path) == [
        "2026-06-30 NetBenefits Quarterly Statement - ABC 403(b), ABC 457(b) and ABC DCP Plans.pdf"]


def test_two_plans_with_one_name_never_cover_each_other():
    twins = [site.plan_from_option("ABC 401(K) PLAN", LINK % P403),
             site.plan_from_option("ABC 401(K) PLAN", LINK % P457),
             site.plan_from_option("ABC DCP", LINK % PDCP)]
    named = site.plans_named("ABC 401(K) PLAN statement", twins, chosen=twins[0]["digest"])
    assert [p["digest"] for p in named] == [twins[0]["digest"]]


# -- a Choose a Plan page that is not one plan's link alone ---------------------------

Q1 = "01/01/2026-03/31/2026"
NAV = "/mybenefits/savings2/navigation/dc/Summary?plan=%s"


def saved_names(tmp_path):
    folder = tmp_path / "out" / "Statements"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def one_plan_listed(monkeypatch, tmp_path, links, header="ABC 457(B) PLAN", have=(Q2,)):
    """An app on a page whose Choose a Plan page shows `links` and whose
    Statements page is its one plan's own, named `header`."""
    page = Page(links=links, single_heading=header)
    calls = []
    monkeypatch.setattr(site, "make_statement",
                        statements_by_plan(page, calls, single=set(have), header=header))
    return app_on(tmp_path, page), page, calls


def test_one_plan_link_beside_other_plan_links_stops_and_keeps_no_list(monkeypatch, tmp_path, capsys):
    app, page, calls = one_plan_listed(monkeypatch, tmp_path,
                                       [(NAMES[P457], LINK % P457), ("Plan Summary", NAV % P457)])
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert app.stats["plans_unlisted"] == 1
    assert "cannot tell whether this login has one" in capsys.readouterr().out
    assert not (tmp_path / "out" / "plans.json").exists()
    assert not app.discovery.data and not calls and page.probes == []


@pytest.mark.parametrize("address", [site.WPS + LINK % P457,
                                     "/mybenefits/savings2/navigation/dc/OnlineStatement?plan=%s" % P457],
                         ids=["absolute", "savings2-without-client"])
def test_one_plan_link_of_another_shape_is_a_login_with_one_plan(monkeypatch, tmp_path, address):
    app, page, calls = one_plan_listed(monkeypatch, tmp_path, [(NAMES[P457], address)])
    app.cmd_discover(quiet=True)
    assert list(app.discovery.data) == ["Statement:2026-06-30:Quarterly Statement"]
    assert not (tmp_path / "out" / "plans.json").exists()
    assert page.probes == [] and app.stats["manual_review"] == 0


def test_a_one_plan_chooser_lets_go_of_plans_kept_before(monkeypatch, tmp_path):
    """plans.json as a run that took this page for several plans left it.
    The page shows one plan, so the login has one plan, and a later run
    with no list page at all does not go back to what was kept."""
    app, page, calls = one_plan_listed(monkeypatch, tmp_path, chooser_links(P457))
    for p in (P457, PXR):
        kept = site.plan_from_option(NAMES[p], LINK % p)
        app.plans.update(kept["digest"], kept, save=False)
    app.plans.save()
    app.cmd_discover(quiet=True)
    assert list(app.discovery.data) == ["Statement:2026-06-30:Quarterly Statement"]
    assert json.loads((tmp_path / "out" / "plans.json").read_text()) == {}
    page.links = None                                  # no Choose a Plan page now
    again = app_on(tmp_path, page)
    again.cmd_discover(quiet=True)
    assert list(again.discovery.data) == ["Statement:2026-06-30:Quarterly Statement"]
    assert page.probes == []


def test_a_choose_a_plan_page_off_the_statements_site_is_not_read():
    page = multi_page(remembered=P457)
    page.chooser_lands = "https://nb.fidelity.com/public/nb/default/home"
    assert site.read_plan_choices(page) is None


def test_no_plan_list_is_read_from_a_tab_off_the_statements_site():
    page = multi_page(remembered=P457)
    page.url = "https://nb.fidelity.com/public/nb/default/home"
    assert site.read_plan_choices(page) is None
    assert page.gotos == []


# -- a login with one plan that gains another -----------------------------------------

def gains_a_second_plan(monkeypatch, tmp_path, header):
    """A login with one plan saves two quarters, then gains North-Star's
    plan, and a Discover and a Run All follow. The statements made after."""
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app, one, _calls = one_plan_listed(monkeypatch, tmp_path, chooser_links(P457), header=header,
                                       have=(Q2, Q1))
    app.cmd_discover(quiet=True)
    app.process(app._select())
    assert len(saved_names(tmp_path)) == 2
    site._plan_in_use["plan"] = None
    two = Page(links=chooser_links(P457, PXR), remembered=P457)
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(two, calls))
    again = app_on(tmp_path, two)
    again.cmd_discover(quiet=True)
    again.process(again._select())
    return again, [(c[0], c[1]) for c in calls if c[2]]


def test_a_login_with_one_plan_that_gains_a_second_does_not_make_its_history_again(monkeypatch, tmp_path):
    # The statement named the plan as the list does, in its own case.
    app, made = gains_a_second_plan(monkeypatch, tmp_path, header="ABC 457(B) PLAN")
    assert made == [(PXR, Q2)]
    assert saved_names(tmp_path) == [
        "2026-03-31 NetBenefits Quarterly Statement - Abc 457(B) Plan.pdf",
        "2026-06-30 NetBenefits Quarterly Statement - Abc 457(B) Plan.pdf",
        "2026-06-30 NetBenefits Quarterly Statement - North-Star Medical Group.pdf"]
    mine = [r for r in app.progress.data.values() if r.get("plan") == site.plan_digest(P457)]
    assert len(mine) == 2 and all(r["downloaded_ok"] and not r["pdf_path"] for r in mine)
    assert all("saved before this login had several plans" in r["notes"] for r in mine)


def test_a_record_saved_under_another_plans_name_does_not_count_for_this_plan(monkeypatch, tmp_path):
    app, made = gains_a_second_plan(monkeypatch, tmp_path, header="SOME CORP. RETIREMENT SAVINGS PLAN")
    assert sorted(made) == sorted([(P457, Q2), (P457, Q1), (PXR, Q2)])


# -- a record with no plan on a login with several -------------------------------------

def test_a_record_with_no_plan_is_left_for_review_once_the_login_has_several(monkeypatch, tmp_path):
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app, one, _calls = one_plan_listed(monkeypatch, tmp_path, chooser_links(P457),
                                       header="SOME CORP. RETIREMENT SAVINGS PLAN")
    app.cmd_discover(quiet=True)                       # listed, never downloaded
    site._plan_in_use["plan"] = None
    page = multi_page()
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, calls, single={Q2}))
    again = app_on(tmp_path, page)
    again.cmd_discover(quiet=True)
    again.process(again._select())
    rec = again.progress.data["Statement:2026-06-30:Quarterly Statement"]
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value and not rec.get("downloaded_ok")
    assert "its plan is not known" in rec["notes"] and not rec["pdf_path"]
    assert len([c for c in calls if c[2]]) == 3          # the plans' own three, and no other
    # A Resume in a new process, with plans.json alone, leaves it too.
    site._plan_in_use["plan"] = None
    resume = app_on(tmp_path, page)
    calls.clear()
    resume.process(resume._select())
    assert not [c for c in calls if c[2]]
    assert resume.progress.data["Statement:2026-06-30:Quarterly Statement"]["state"] == \
        State.NEEDS_MANUAL_REVIEW.value


# -- a plan counted covered only by its own statement ----------------------------------

def test_a_plan_with_a_common_name_is_not_covered_by_another_plans_statement(monkeypatch, tmp_path):
    """'Retirement Savings Plan' is in any statement that speaks of your
    retirement savings plan. Its own statement is another one, and saved."""
    acme, rsp = PXR, P457                              # ACME's statement is made first
    page = Page(links=[("ACME 401(K) PLAN", LINK % acme), ("RETIREMENT SAVINGS PLAN", LINK % rsp)],
                remembered=acme)
    page.names.update({acme: "ACME 401(K) PLAN", rsp: "RETIREMENT SAVINGS PLAN"})
    monkeypatch.setitem(HAVE, acme, {Q2})
    monkeypatch.setitem(HAVE, rsp, {Q2})
    monkeypatch.setitem(STATEMENT_NAMES, acme, ["ACME 401(K) PLAN",
                                                "Your retirement savings plan grew this quarter"])
    monkeypatch.setitem(STATEMENT_NAMES, rsp, ["RETIREMENT SAVINGS PLAN", "Balance 100.00"])
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, calls))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    chosen = app._select()
    assert [d.account for d in chosen] == ["Acme 401(k) Plan", "Retirement Savings Plan"]
    app.process(chosen)
    assert sorted(c[0] for c in calls if c[2]) == sorted([acme, rsp])
    own = next(r for r in app.progress.data.values() if r["account"] == "Retirement Savings Plan")
    assert own["downloaded_ok"] and "covered by" not in (own.get("notes") or "")
    assert "Balance 100.00" in receipt_pdf.pdf_text(Path(own["pdf_path"]))


# -- a combined statement named from the record written down for it ---------------------

def test_a_combined_statement_that_cannot_be_renamed_keeps_the_summary_its_name_came_from(
        monkeypatch, tmp_path):
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path)
    real = Path.replace

    def held(self, target):
        if str(target).endswith(" Plans.pdf"):
            raise OSError("another program has it open")
        return real(self, target)
    monkeypatch.setattr(Path, "replace", held)
    app.process(app._select())
    files = [r for r in app.progress.data.values() if r.get("pdf_path")]
    assert files
    for rec in files:
        name = docs.build_pdf_filename(rec["date"], rec["summary"], "", record=docs.Document.from_dict(rec))
        assert name == Path(rec["pdf_path"]).name == rec["pdf_filename"]


def test_rename_offers_nothing_after_a_combined_statement(monkeypatch, tmp_path, capsys):
    app, page, calls = three_plans_one_statement(monkeypatch, tmp_path)
    app.process(app._select())
    capsys.readouterr()
    app.cmd_rename()
    assert "Every file is already named the way this app names them." in capsys.readouterr().out


# -- the heading names the plan --------------------------------------------------------

def test_a_plan_is_not_found_inside_a_longer_plans_heading():
    page = Page({P457: "sticky"}, links=[("ACME RETIREMENT SAVINGS PLAN", LINK % P403),
                                         ("RETIREMENT SAVINGS PLAN", LINK % P457)], remembered=P403)
    page.names.update({P403: "ACME RETIREMENT SAVINGS PLAN", P457: "RETIREMENT SAVINGS PLAN"})
    plans = plans_of(page)
    # The site stays on ACME's plan, whose heading carries the other's name.
    assert site.open_plan(page, plans[P457]) == site.DID_NOT_OPEN
    assert site.open_plan(page, plans[P403]) == site.OPENED


def test_a_plan_named_elsewhere_on_the_page_is_not_the_plan_it_shows():
    page = multi_page(remembered=P403)
    plans = plans_of(page)
    page.aside = "Your other plans ABC 457(B) PLAN (%s)" % P457
    assert not site._shows_plan(page, plans[P457])
    assert site._shows_plan(page, plans[P403])


# -- from the 0.52.0 safety review -------------------------------------------------

def test_a_select_account_page_with_one_plan_is_a_login_with_one_plan(monkeypatch):
    """With no Choose a Plan page and one plan on the Select Account page,
    the login goes on as one with one plan, keeping v0.51.0's keys, rather
    than taking the several-plans path for a list of one."""
    import sys
    monkeypatch.setattr(sys.modules[__name__], "NAMES", {P457: NAMES[P457]})
    page = Page(links=None, remembered=None)
    assert site.read_plan_choices(page) == site.ONE_PLAN


def test_two_plans_of_one_name_never_count_a_one_plan_record_for_either(monkeypatch, tmp_path):
    """A login with one plan saves two quarters, then gains a second plan of
    the very same name. A record saved before names the plan only by that
    name, which fits both, so neither plan counts it done, and the second
    plan's own statement is made rather than skipped."""
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app, one, _calls = one_plan_listed(monkeypatch, tmp_path, chooser_links(P457),
                                       header="ABC 457(B) PLAN", have=(Q2, Q1))
    app.cmd_discover(quiet=True)
    app.process(app._select())
    site._plan_in_use["plan"] = None
    two = Page(links=[(NAMES[P457], LINK % P457), (NAMES[P457], LINK % PXR)], remembered=P457)
    two.names[PXR] = NAMES[P457]
    monkeypatch.setitem(STATEMENT_NAMES, PXR, [NAMES[P457]])
    calls = []
    monkeypatch.setattr(site, "make_statement", statements_by_plan(two, calls))
    again = app_on(tmp_path, two)
    again.cmd_discover(quiet=True)
    again.process(again._select())
    made = [(c[0], c[1]) for c in calls if c[2]]
    assert (PXR, Q2) in made
    assert not [r for r in again.progress.data.values()
                if "saved before this login had several plans" in (r.get("notes") or "")]


# -- a statement that names its plan by its type and employer (#123) -------------------

H457, H401, PVOL, P401K, X457, W457 = "41501", "41502", "41503", "41504", "41505", "41506"
HARBOR, PINE = "Harbor City Schools", "PINE RIDGE HEALTH, INC."
TITLE_457 = "457b Deferred Compensation Plan Retirement Savings Statement"
# Four plans at two employers, as on #123's login, all names invented, each
# plan's name on the list and the employer the header names on its page.
# Pine Ridge's voluntary plan never opens, its statements being in the
# employer's combined one.
TYPED = {H457: ("HARBOR 457B", HARBOR), H401: ("HARBOR 401A", HARBOR),
         PVOL: ("PINE RIDGE VOLUNTARY 403B", PINE), P401K: ("PINE RIDGE 401K", PINE)}
OPENS = (H457, H401, P401K)


def typed_page(plans=TYPED, behaviors=None, addresses=None):
    page = Page({PVOL: "sticky"} if behaviors is None else behaviors,
                links=[(name, (addresses or {}).get(p, LINK % p)) for p, (name, _) in plans.items()],
                remembered=next(iter(plans)))
    page.names = {p: name for p, (name, _) in plans.items()}
    page.employers = {p: employer for p, (_, employer) in plans.items()}
    return page


def typed_plans(page, shown):
    """The plans as listed, with the header read on the page of each plan
    in `shown`, as opening it reads it."""
    plans = plans_of(page)
    for p in shown:
        page.in_context = p
        site._note_employer(page, plans[p])
    return list(plans.values())


def typed_login(monkeypatch, tmp_path, statements, plans=TYPED, behaviors=None, headers=None,
                addresses=None):
    """The login after Discover, every plan with the second quarter.
    `statements` is what a plan's statement reads, line by line, when not
    just its own name, and `headers` what the header names on a plan's
    page, when not its employer."""
    page = typed_page(plans, behaviors, addresses)
    page.employers.update(headers or {})
    for p, (name, _) in plans.items():
        monkeypatch.setitem(HAVE, p, {Q2})
        monkeypatch.setitem(STATEMENT_NAMES, p, statements.get(p, [name, "Statement Details"]))
    monkeypatch.setattr(site, "make_statement", statements_by_plan(page, []))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render_text)
    app = app_on(tmp_path, page)
    app.cmd_discover(quiet=True)
    return app, page


def record_of(app, plan):
    return next(r for r in app.progress.data.values() if r["plan"] == site.plan_digest(plan))


def test_a_plans_type_comes_from_its_name_on_the_list():
    def kind(name):
        return site.plan_type({"heading": name, "label": site.option_label(name)})
    assert kind("HARBOR 457B") == "457B"
    assert kind("ABC 457(B) PLAN") == "457B"
    assert kind("ACME 401(K) PROFIT SHARING PLAN (41401)") == "401K"
    assert kind("Lakeside 403 (b) Plan") == "403B"
    # Glued to the words before it, as #123's "EMPLOYER MEM401K".
    assert kind("HARBOR MEM401K") == "401K"
    assert kind("HARBOR457B") == "457B"
    # No type, or two, is no type.
    for name in ("ABC DCP", "NORTH-STAR MEDICAL GROUP", "ABC 403(B) AND 457(B) PLAN",
                 "SUITE 403 BENEFITS", "ABC PLAN (457)", "ABC 2457B PLAN"):
        assert kind(name) == "", name


def test_a_statement_that_names_its_plan_by_type_and_employer_alone_is_saved(monkeypatch, tmp_path, caplog):
    """#123. A 457(b)'s statements print a line naming the employer, then a
    title of the plan's type, and never the name the list gives it."""
    caplog.set_level("INFO")
    app, page = typed_login(monkeypatch, tmp_path,
                            {H457: [HARBOR.upper(), TITLE_457, "Your Account Summary"]})
    app.process(app._select())
    own = record_of(app, H457)
    assert own["state"] == State.COMPLETED.value and own["downloaded_ok"]
    assert own["pdf_filename"] == own["date"] + " NetBenefits Quarterly Statement - Harbor 457b.pdf"
    assert Path(own["pdf_path"]).is_file() and not own.get("covers")
    for p in (H401, P401K):                               # named by name, as before
        assert record_of(app, p)["state"] == State.COMPLETED.value
    assert app.stats.get("wrong_document", 0) == 0
    assert app.stats["manual_review"] == 1                # the voluntary plan, left for the owner
    assert "names its plan by its type and employer" in caplog.text
    assert "plan Pine Ridge Voluntary 403b left for you: " + site.DID_NOT_OPEN in caplog.text


def test_the_type_and_employer_are_found_however_pypdf_broke_the_lines():
    plans = typed_plans(typed_page(), OPENS)
    for text in ("HARBOR CITY SCHOOLS\n" + TITLE_457,
                 "Statement Details Harbor City Schools457b Deferred Compensation\n"
                 "Plan Retirement SavingsStatement",
                 "Harbor  City\nSchools 457(b) Deferred Compensation Plan Retirement Savings Statement\n"
                 "Balance 1,457.00 Beginning 2,401 Accounts"):
        assert site.named_by_type(text, plans, site.plan_digest(H457)) == (True, ""), text


def test_a_second_plan_of_the_type_at_the_employer_is_still_refused(monkeypatch, tmp_path):
    plans = {**TYPED, X457: ("HARBOR EXECUTIVE 457B", HARBOR)}
    statements = {p: [HARBOR, TITLE_457] for p in (H457, X457)}
    app, page = typed_login(monkeypatch, tmp_path, statements, plans=plans)
    app.process(app._select())
    for p in (H457, X457):
        rec = record_of(app, p)
        assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value and not rec.get("downloaded_ok")
        assert "does not name the plan it was made for" in rec["notes"]
    assert app.stats["wrong_document"] == 2
    assert not any("457b" in p.name for p in (tmp_path / "out" / "Statements").iterdir())


@pytest.mark.parametrize("lines", [
    # It names the employer's other plan, as #123's combined statements do.
    [HARBOR, TITLE_457, "HARBOR 401A", "Your Account Summary"],
    # Or it gives each plan a title by its type alone.
    [HARBOR, TITLE_457, HARBOR, "401(a) Money Purchase Plan Retirement Savings Statement"],
    # Or one title, and the other plan by its type alone.
    [HARBOR, TITLE_457, "401(a) Money Purchase Plan balance 200.00"],
    # Or a title of no type over both plans.
    [HARBOR, "Retirement Savings Statement", "457b Deferred Compensation Plan", "401a Plan"],
])
def test_the_employers_combined_statement_is_not_taken_by_type(monkeypatch, tmp_path, lines):
    app, page = typed_login(monkeypatch, tmp_path, {H457: lines, H401: lines})
    app.process(app._select())
    refused = record_of(app, H457)
    assert refused["state"] == State.NEEDS_MANUAL_REVIEW.value and not refused.get("downloaded_ok")
    assert not refused.get("covers")


@pytest.mark.parametrize("lines, kept", [([HARBOR, TITLE_457], True), ([PINE, TITLE_457], False)])
def test_another_employers_statement_of_the_type_is_refused(monkeypatch, tmp_path, lines, kept):
    """Two employers' 457(b) plans. Each one's own statement is saved, and
    one made for Harbor's that is Pine Ridge's is not."""
    plans = {H457: ("HARBOR 457B", HARBOR), H401: ("HARBOR 401A", HARBOR), W457: ("PINE RIDGE 457B", PINE)}
    app, page = typed_login(monkeypatch, tmp_path, {H457: lines, W457: [PINE, TITLE_457]},
                            plans=plans, behaviors={})
    app.process(app._select())
    assert record_of(app, W457)["state"] == State.COMPLETED.value
    harbor = record_of(app, H457)
    assert harbor["state"] == (State.COMPLETED if kept else State.NEEDS_MANUAL_REVIEW).value
    assert app.stats.get("wrong_document", 0) == (0 if kept else 1)


def test_an_employer_whose_name_ends_in_another_employers_is_told_from_it_only_one_way():
    """With the line breaks gone, West Lakeside's name is Lakeside's after a
    line ending "Midwest", so only Lakeside's statements can be told."""
    plans = {H457: ("LAKESIDE 457B", "Lakeside Schools"), W457: ("WEST LAKESIDE 457B", "West Lakeside Schools")}
    listed = typed_plans(typed_page(plans, behaviors={}), plans)
    ours, theirs = site.plan_digest(H457), site.plan_digest(W457)
    west = "WEST LAKESIDE SCHOOLS\n" + TITLE_457
    assert site.named_by_type("LAKESIDE SCHOOLS\n" + TITLE_457, listed, ours) == (True, "")
    assert site.named_by_type(west, listed, ours) == \
        (False, "no title of its type follows its employer's name")
    for text in (west, "100 Midwest\nLakeside Schools\n" + TITLE_457):
        assert site.named_by_type(text, listed, theirs) == \
            (False, "another employer's name ends its employer's name")


@pytest.mark.parametrize("plans, shown, why", [
    # A plan whose name gives no type, at the same employer.
    ({**TYPED, X457: ("HARBOR DCP", HARBOR)}, OPENS + (X457,), site.SAME_EMPLOYER + " (Harbor DCP)"),
    # A plan of the type that no page showed, so its employer is not known.
    ({**TYPED, PVOL: ("PINE RIDGE VOLUNTARY 457B", PINE)}, OPENS,
     site.EMPLOYER_NOT_KNOWN + " (Pine Ridge Voluntary 457b)"),
    # A header that names one employer for every plan.
    ({H457: ("HARBOR 457B", HARBOR), W457: ("PINE RIDGE 457B", HARBOR)}, (H457, W457),
     site.SAME_EMPLOYER + " (Pine Ridge 457b)"),
])
def test_a_plan_that_may_be_of_the_type_at_the_employer_refuses_it(plans, shown, why):
    listed = typed_plans(typed_page(plans), shown)
    assert site.named_by_type(HARBOR + "\n" + TITLE_457, listed, site.plan_digest(H457)) == (False, why)


def test_a_plan_the_header_named_no_one_employer_for_is_not_taken_by_type():
    page = typed_page()
    listed = typed_plans(page, (H401, P401K))
    text, ours = HARBOR + "\n" + TITLE_457, site.plan_digest(H457)
    assert site.named_by_type(text, listed, ours) == (False, "the header did not name one employer for it")
    page.in_context, page.employers[H457] = H457, ""
    site._note_employer(page, next(p for p in listed if p["digest"] == ours))
    assert site.named_by_type(text, listed, ours)[0] is False
    for employer in (HARBOR, "Harbor City Schools District", HARBOR):
        page.employers[H457] = employer
        site._note_employer(page, next(p for p in listed if p["digest"] == ours))
    assert site.named_by_type(text, listed, ours) == (False, "the header did not name one employer for it")
    site._employers_seen[ours] = {site._bare(HARBOR)}
    assert site.named_by_type(text, listed, ours) == (True, "")


def test_the_employers_read_before_the_plan_list_are_let_go():
    page = typed_page()
    listed = typed_plans(page, OPENS)
    ours = {"digest": site.plan_digest(H457)}
    site.note_combined("\n".join([PINE, "PINE RIDGE 401K", "PINE RIDGE VOLUNTARY 403B"]),
                       site.plan_digest(P401K), listed)
    assert site.employer_of(ours) == site._bare(HARBOR)
    assert site.placed_employer({"digest": site.plan_digest(PVOL)}) == site._bare(PINE)
    plans_of(page)
    assert site.employer_of(ours) == ""
    assert site.placed_employer({"digest": site.plan_digest(PVOL)}) == ""
    # Its plan shown again, a statement read before the list was read still
    # places nothing.
    page.in_context = P401K
    site._note_employer(page, next(p for p in listed if p["digest"] == site.plan_digest(P401K)))
    assert site.placed_employer({"digest": site.plan_digest(PVOL)}) == ""


@pytest.mark.parametrize("text, why", [
    (HARBOR + "\n401(k) Plan Retirement Savings Statement", "a title in it is not of its type"),
    (HARBOR + "\nRetirement Savings Statement", "a title in it is not of its type"),
    (HARBOR + "\n" + TITLE_457 + "\nPage 2 Retirement Savings Statement", "a title in it is not of its type"),
    (TITLE_457, "no title of its type follows its employer's name"),
    (PINE + "\n" + TITLE_457, "no title of its type follows its employer's name"),
    (HARBOR + " 2\n" + TITLE_457, "a title in it is not of its type"),
    (HARBOR + "\n457b Deferred Compensation Plan", "it has no title of its type"),
    (HARBOR + "\n" + TITLE_457 + "\nYour Harbor 401(a) balance", "it names another plan of the list"),
    # The type of the plan beside it at the employer, or of one whose
    # employer no page showed, as a combined statement under one title.
    (HARBOR + "\n" + TITLE_457 + "\n401(a) Money Purchase Plan balance 200.00",
     "it gives the type of another plan at its employer"),
    (HARBOR + "\n" + TITLE_457 + "\nYour 401a Plan", "it gives the type of another plan at its employer"),
    (HARBOR + "\n" + TITLE_457 + "\nVoluntary 403 (b) balance", "it gives the type of another plan at its employer"),
    (HARBOR + "\n" + TITLE_457 + "\nMEM401A balance 2,000.00", "it gives the type of another plan at its employer"),
])
def test_a_statement_not_titled_for_its_type_after_its_employer_is_refused(text, why):
    listed = typed_plans(typed_page(), OPENS)
    assert site.named_by_type(text, listed, site.plan_digest(H457)) == (False, why)


def test_a_type_only_another_employers_plan_has_or_a_number_is_not_another_plan_named():
    listed = typed_plans(typed_page(), OPENS)
    for line in ("Roll over a former employer's 401(k)", "Balance $401 Account 1,403 Bonds 2457 Bills",
                 "Plan 401 Accounts"):
        text = HARBOR + "\n" + TITLE_457 + "\n" + line
        assert site.named_by_type(text, listed, site.plan_digest(H457)) == (True, ""), line


def test_a_plan_whose_name_gives_no_type_is_never_named_by_type():
    plans = {X457: ("HARBOR DCP", HARBOR), H401: ("HARBOR 401A", HARBOR)}
    listed = typed_plans(typed_page(plans, behaviors={}), plans)
    assert site.named_by_type(HARBOR + "\n" + TITLE_457, listed, site.plan_digest(X457)) == \
        (False, "its name on the list gives no plan type")


# -- a plan placed at its employer by that employer's combined statement (#123) ---------

D457, DMEM, DRET, DVOL = "41511", "41512", "41513", "41514"
# #123's login as its owner gave it, all names invented. The 457(b) and a
# 401(k) at one employer. At the other, a retirement plan whose name gives
# no type and whose page opens, and a voluntary plan whose name gives no
# type and whose page never opens, both in that employer's combined
# statement, which the retirement plan's request gives.
HIS = {D457: ("HARBOR 457B", HARBOR), DMEM: ("HARBOR MEM401K", HARBOR),
       DRET: ("PINE RIDGE RETIREMENT PLAN", PINE), DVOL: ("PINE RIDGE VOLUNTARY PLAN", PINE)}
HIS_457 = [HARBOR.upper(), TITLE_457, "Your Account Summary"]
PINES = [PINE, "Retirement Savings Statement", "PINE RIDGE RETIREMENT PLAN", "PINE RIDGE VOLUNTARY PLAN"]


def his_login(monkeypatch, tmp_path, combined=PINES, headers=None, addresses=None):
    return typed_login(monkeypatch, tmp_path, {D457: HIS_457, DRET: combined}, plans=HIS,
                       behaviors={DVOL: "sticky"}, headers=headers, addresses=addresses)


def his_457_first(app):
    """The run's statements with the 457(b)'s first, so it is judged before
    the combined statement that places the voluntary plan is read."""
    return sorted(app._select(), key=lambda d: d.plan != site.plan_digest(D457))


@pytest.mark.parametrize("first", [D457, DRET])
def test_his_login_files_the_457b_in_a_full_run_whichever_statement_comes_first(
        monkeypatch, tmp_path, caplog, first):
    caplog.set_level("INFO")
    app, page = his_login(monkeypatch, tmp_path)
    app.process(sorted(app._select(), key=lambda d: d.plan != site.plan_digest(first)))
    assert_his_457_filed(app, tmp_path)
    assert ("waits for a statement that places another plan" in caplog.text) == (first == D457)
    assert record_of(app, DRET)["covers"] == [site.plan_digest(DVOL)]
    assert record_of(app, DMEM)["state"] == State.COMPLETED.value
    assert app.stats.get("wrong_document", 0) == 0
    assert app.stats["manual_review"] == 1                # the voluntary plan, left for the owner
    assert not list(app.paths.manual_review.glob("*.pdf"))
    assert "plan Pine Ridge Retirement Plan: the header names the employer " + PINE in caplog.text


def test_his_voluntary_plan_is_placed_when_its_link_has_no_statements_address(monkeypatch, tmp_path):
    """A plan whose link leaves the statements page has no address, is never
    asked for, and is still placed by the combined statement naming it."""
    app, page = his_login(monkeypatch, tmp_path, addresses={DVOL: "/mybenefits/elsewhere?plan=41514"})
    assert not next(p for p in app._plans_by_digest.values() if p["label"] == "Pine Ridge Voluntary Plan")["path"]
    app.process(his_457_first(app))
    assert_his_457_filed(app, tmp_path)


def assert_his_457_filed(app, tmp_path):
    own = record_of(app, D457)
    assert own["state"] == State.COMPLETED.value and own["downloaded_ok"] and not own["held"]
    assert Path(own["pdf_path"]).parent == tmp_path / "out" / "Statements"
    assert Path(own["pdf_path"]).is_file() and docs.HELD not in (own.get("notes") or "")


def assert_his_457_held(app, tmp_path):
    """Waiting in Manual Review, never filed and never set aside."""
    own = record_of(app, D457)
    assert own["state"] == State.NEEDS_MANUAL_REVIEW.value and own["held"] is True
    assert not own.get("downloaded_ok") and own["notes"].endswith(docs.HELD)
    assert Path(own["pdf_path"]).parent == app.paths.manual_review and Path(own["pdf_path"]).is_file()
    assert app.stats.get("wrong_document", 0) == 0
    assert not any("457b" in p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf"))


def next_run(tmp_path, page):
    """A later run of the same install, Discover and then every statement
    left, as a full run makes it."""
    site._plan_in_use["plan"] = None
    again = app_on(tmp_path, page)
    again.cmd_discover(quiet=True)
    again.process(again._select())
    return again


@pytest.mark.parametrize("combined, headers", [
    # The combined statement names the voluntary plan, and the header named
    # no employer on the retirement plan's page, so its employer is not
    # settled.
    (PINES, {DRET: ""}),
    # It names two employers.
    (PINES + [HARBOR], None),
    # The header names an employer the statement does not carry.
    (PINES, {DRET: "Lake County"}),
])
def test_a_combined_statement_that_does_not_settle_its_employer_places_no_plan(
        monkeypatch, tmp_path, caplog, combined, headers):
    caplog.set_level("INFO")
    app, page = his_login(monkeypatch, tmp_path, combined=combined, headers=headers)
    app.process(his_457_first(app))
    assert_his_457_held(app, tmp_path)
    assert "still waits: " + site.EMPLOYER_NOT_KNOWN + " (" in caplog.text
    assert "Pine Ridge Voluntary Plan)" in caplog.text
    assert app.stats["manual_review"] == 2                # the voluntary plan, and the one held


def test_a_statement_held_when_its_run_ended_is_judged_by_a_later_run_that_places_the_plan(
        monkeypatch, tmp_path, capsys):
    """The first run gets only the 457(b)'s statement, so nothing places the
    voluntary plan, and the statement waits. The next full run reads the
    combined statement and files it."""
    app, page = his_login(monkeypatch, tmp_path)
    app.process([d for d in app._select() if d.plan == site.plan_digest(D457)])
    assert_his_457_held(app, tmp_path)
    capsys.readouterr()
    again = next_run(tmp_path, page)
    assert_his_457_filed(again, tmp_path)
    assert "Held in Manual Review, and judged again at the end of the run." in capsys.readouterr().out
    assert again.stats["skipped_completed"] == 0 and again.stats["statements"] == 3


def test_a_resume_that_never_shows_its_plan_leaves_a_held_statement_waiting(monkeypatch, tmp_path):
    """A Resume opens only the plans it has statements left for, so the
    header never names the 457(b)'s employer that run, and the statement
    waits rather than be judged without it."""
    app, page = his_login(monkeypatch, tmp_path)
    docs_ = app._select()
    app.process([d for d in docs_ if d.plan == site.plan_digest(D457)])
    site._plan_in_use["plan"] = None
    resume = app_on(tmp_path, page)
    resume.process([d for d in docs_ if d.plan == site.plan_digest(DRET)])
    assert record_of(resume, DRET)["covers"] == [site.plan_digest(DVOL)]
    assert_his_457_held(resume, tmp_path)
    assert_his_457_filed(next_run(tmp_path, page), tmp_path)


def test_a_saved_combined_statement_counts_only_while_its_plans_header_names_its_employer(
        monkeypatch, tmp_path):
    """The combined statement saved by a Resume is read again by a later run,
    and places the voluntary plan only while the header on its own plan's
    page still names the employer it named when the statement was made,
    even where the statement carries the other name too."""
    app, page = his_login(monkeypatch, tmp_path, combined=PINES + ["Lake County Credit Union"])
    docs_ = app._select()
    app.process([d for d in docs_ if d.plan == site.plan_digest(D457)])
    site._plan_in_use["plan"] = None
    app_on(tmp_path, page).process([d for d in docs_ if d.plan == site.plan_digest(DRET)])
    page.employers[DRET] = "Lake County"
    later = next_run(tmp_path, page)
    assert record_of(later, DRET)["employer"] == site._bare(PINE)
    assert_his_457_held(later, tmp_path)
    page.employers[DRET] = PINE
    assert_his_457_filed(next_run(tmp_path, page), tmp_path)


def test_a_held_statement_moved_with_a_minimal_history_is_never_filed_unjudged(monkeypatch, tmp_path):
    """tools/migrate.py --minimal leaves out held and a combined statement's
    employer. A statement held when its history moved is then set aside like
    any other in Manual Review, and once its file there is gone it is made
    and judged again."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "tools"))
    import migrate
    app, page = his_login(monkeypatch, tmp_path)
    app.process([d for d in app._select() if d.plan == site.plan_digest(D457)])
    assert_his_457_held(app, tmp_path)
    for key, rec in list(app.progress.data.items()):
        app.progress.data[key] = migrate._skip_fields(rec, "NetBenefits")
    app.progress.save()
    moved = next_run(tmp_path, page)
    own = record_of(moved, D457)
    assert "held" not in own and own["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert not own.get("downloaded_ok") and Path(own["pdf_path"]).parent == moved.paths.manual_review
    assert not any("457b" in p.name for p in (tmp_path / "out" / "Statements").glob("*.pdf"))
    Path(own["pdf_path"]).unlink()
    assert_his_457_filed(next_run(tmp_path, page), tmp_path)


def test_a_held_statement_the_later_run_can_tell_is_not_its_plans_is_set_aside_for_good(
        monkeypatch, tmp_path):
    """Once the voluntary plan is placed, a statement printing the other
    employer is seen to be another employer's, set aside and never held or
    judged again."""
    app, page = his_login(monkeypatch, tmp_path)
    monkeypatch.setitem(STATEMENT_NAMES, D457, [PINE, TITLE_457])
    app.process([d for d in app._select() if d.plan == site.plan_digest(D457)])
    assert_his_457_held(app, tmp_path)
    again = next_run(tmp_path, page)
    own = record_of(again, D457)
    assert own["state"] == State.NEEDS_MANUAL_REVIEW.value and own["held"] is False
    assert own["notes"] == "the statement does not name the plan it was made for"
    assert again.stats["wrong_document"] == 1
    last = next_run(tmp_path, page)
    assert record_of(last, D457)["notes"] == own["notes"] and record_of(last, D457)["held"] is False
    assert last.stats.get("wrong_document", 0) == 0


def test_a_run_stopped_from_outside_leaves_its_held_statement_for_the_next(monkeypatch, tmp_path):
    """The panel's Stop ends the process, and the judging at the end of the
    run never happens. The statement still waits, and the next run files it."""
    app, page = his_login(monkeypatch, tmp_path)
    app._process_each([d for d in his_457_first(app) if d.plan == site.plan_digest(D457)])
    assert_his_457_held(app, tmp_path)
    assert_his_457_filed(next_run(tmp_path, page), tmp_path)


def test_a_run_that_stops_still_judges_what_it_held_and_the_next_one_files_it(monkeypatch, tmp_path):
    app, page = his_login(monkeypatch, tmp_path)
    made = site.make_statement

    def signed_out_on_the_combined_one(pg, date_range, want_html=False):
        if want_html and page.in_context == DRET:
            raise site.SessionExpired("NetBenefits signed this session out")
        return made(pg, date_range, want_html)
    monkeypatch.setattr(site, "make_statement", signed_out_on_the_combined_one)
    with pytest.raises(SystemExit):
        app.process(his_457_first(app))
    assert app.stats["session_expired"] == 1
    assert_his_457_held(app, tmp_path)
    monkeypatch.setattr(site, "make_statement", made)
    assert_his_457_filed(next_run(tmp_path, page), tmp_path)


@pytest.mark.parametrize("snag", ["open elsewhere", "text not read"])
def test_a_held_statement_that_cannot_be_judged_or_filed_now_waits_for_the_next_run(
        monkeypatch, tmp_path, snag):
    app, page = his_login(monkeypatch, tmp_path)
    real_replace, real_text = Path.replace, receipt_pdf.pdf_text

    def held_open(self, target):
        if self.parent == app.paths.manual_review and Path(target).parent != app.paths.manual_review:
            raise OSError("another program has it open")
        return real_replace(self, target)

    def unread(path, *a, **kw):
        return "" if Path(path).parent == app.paths.manual_review else real_text(path, *a, **kw)
    if snag == "open elsewhere":
        monkeypatch.setattr(Path, "replace", held_open)
    else:
        monkeypatch.setattr(receipt_pdf, "pdf_text", unread)
    app.process(his_457_first(app))
    assert_his_457_held(app, tmp_path)
    assert app.stats["failed"] == 0
    monkeypatch.setattr(Path, "replace", real_replace)
    monkeypatch.setattr(receipt_pdf, "pdf_text", real_text)
    assert_his_457_filed(next_run(tmp_path, page), tmp_path)


def test_download_again_sets_aside_a_copy_it_cannot_hold(monkeypatch, tmp_path, capsys):
    """Download again keeps the record of the copy saved before while it has
    saved none of its own (saved_copy), so a new copy that would wait is set
    aside instead, and nothing is left held that no run would judge."""
    app, page = his_login(monkeypatch, tmp_path)
    app.process(sorted(app._select(), key=lambda d: d.plan != site.plan_digest(DRET)))
    assert_his_457_filed(app, tmp_path)
    saved = record_of(app, D457)["pdf_path"]
    site._plan_in_use["plan"] = None
    again = app_on(tmp_path, page)
    again.args.redownload = True
    again.cmd_discover(quiet=True)
    again.process(his_457_first(again))
    own = record_of(again, D457)
    assert own["state"] == State.COMPLETED.value and own["pdf_path"] == saved and Path(saved).is_file()
    assert not any(r.get("held") for r in again.progress.data.values())
    assert again.stats["wrong_document"] == 1


def test_a_statement_that_cannot_be_moved_to_wait_is_set_aside(monkeypatch, tmp_path):
    app, page = his_login(monkeypatch, tmp_path)
    real = Path.replace

    def held_open(self, target):
        if Path(target).parent == app.paths.manual_review:
            raise OSError("another program has it open")
        return real(self, target)
    monkeypatch.setattr(Path, "replace", held_open)
    app.process(his_457_first(app))
    own = record_of(app, D457)
    assert own["state"] == State.NEEDS_MANUAL_REVIEW.value and own["held"] is False
    assert own["notes"] == "the statement does not name the plan it was made for"
    assert app.stats["wrong_document"] == 1


def test_a_combined_statement_places_a_plan_only_while_its_employer_is_settled():
    page = typed_page(HIS, behaviors={DVOL: "sticky"})
    listed = typed_plans(page, (D457, DMEM, DRET))
    by = {p["digest"]: p for p in listed}
    ret, vol, mem, own = (by[site.plan_digest(p)] for p in (DRET, DVOL, DMEM, D457))
    pines = "\n".join(PINES)

    def placed(text, chosen=ret):
        site._employers_named.clear()
        site.note_combined(text, chosen["digest"], listed)
        return site.placed_employer(vol)
    assert placed(pines) == site._bare(PINE)
    assert placed(pines.replace(PINE, "PINE RIDGE")) == ""                       # not its employer
    assert placed(pines + "\n" + HARBOR) == ""                                    # two employers
    assert placed(pines.replace("PINE RIDGE VOLUNTARY PLAN", "")) == ""           # not the plan
    assert placed(pines.replace("PINE RIDGE RETIREMENT PLAN", "")) == ""          # not its own plan
    # Never over what the header named for a plan.
    site.note_combined(pines + "\nHARBOR MEM401K", ret["digest"], listed)
    assert site.placed_employer(mem) == site._bare(HARBOR)
    # Two statements placing it at two employers place it at neither.
    assert placed(pines) == site._bare(PINE)
    site.note_combined("\n".join([HARBOR, "HARBOR 457B", "PINE RIDGE VOLUNTARY PLAN"]), own["digest"], listed)
    assert site.placed_employer(vol) == ""
    # A statement read before another employer's plan showed counts only
    # while what the header has named since still lets it.
    site._employers_seen.pop(own["digest"])
    site._employers_seen.pop(mem["digest"])
    assert placed(pines + "\n" + HARBOR) == site._bare(PINE)
    page.in_context = D457
    site._note_employer(page, own)
    assert site.placed_employer(vol) == ""
    # The header naming two employers for the plan it was made for.
    page.in_context, page.employers[DRET] = DRET, "Lake County"
    site._note_employer(page, ret)
    assert placed(pines) == ""
