"""A form Ally lists and its own page cannot open is said once, and left.

Ally's tax forms API lists a 2019 Form 1099-INT while the Tax Forms year
picker starts at 2020, so nothing on the page opens it (#152). The download
saw that and said so in the log, and then the run took it for a capture that
failed. It was recorded as Needs Manual Review and counted with the two
outcomes that really put a file in the Manual Review folder, so the run said
one document needed review while that folder was empty. A review record
counts as done only while its file is there, and this one had none, so every
run opened the Tax Forms tab for it again, wrote a new failure file, and
added the same row to the document index once more. The reporter had seven.

A capture that fails for any other reason saved nothing either, so it is a
failure, tried again on the next run, and its row is written once however
many runs it fails.

Each run here is the app's own process and run summary over what it has
listed, with Ally's page invented in the shape of its Statements and Tax
Forms page and the browser refused the network. Every date, form and id is
made up.
"""
import base64
import csv
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import testkit
from paperpull_core.models import State

ROOT = Path(__file__).resolve().parents[3]
ALLY = ROOT / "apps" / "ally"

# The page's tax picker starts at 2020, as Ally's does.
TAX_YEARS = ["2025", "2024", "2023", "2022", "2021", "2020"]


def _rename_census():
    """The harness that builds an app as it is at home."""
    import importlib.util
    path = ROOT / "core" / "tests" / "test_every_app_renames_each_file_for_its_own_record.py"
    spec = importlib.util.spec_from_file_location("rename_census_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _rename_census()


def _pdf(words: str) -> str:
    return base64.b64encode(testkit.text_pdf(["invented " + words])).decode()


# Every tax year has its own 1099-INT row, except 2021, whose list is empty.
LISTS = {
    "statements": {"2025": ["September 06, 2025"]},
    "tax": {y: ([] if y == "2021" else ["January 10, %d" % (int(y) + 1)]) for y in TAX_YEARS},
}
PDFS = {y: _pdf(y + " 1099-INT") for y in TAX_YEARS}

PAGE = """<!doctype html><html><head><style>
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
</style></head><body>
<main>
 <h1>Statements and Tax Forms</h1>
 <div role="tablist">
  <button role="tab" data-tab="statements" aria-selected="true">Statements</button>
  <button role="tab" data-tab="tax" aria-selected="false">Tax Forms</button>
 </div>
 <div id="picker"></div>
 <table>
  <thead><tr><th>Date Posted</th><th>Document</th></tr></thead>
  <tbody id="rows"></tbody>
 </table>
</main>
<script>
const LISTS = %(lists)s;
const PDFS = %(pdfs)s;
// Another dropdown of years on the Tax Forms tab, hidden before the picker
// the list follows, or shown after it, offering other years.
const ANOTHER = %(another)s;
window.__pressed = [];

function save(year) {
  const bytes = Uint8Array.from(atob(PDFS[year]), c => c.charCodeAt(0));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
  a.download = 'document.pdf';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function draw(tab, year) {
  const tax = tab === 'tax';
  const body = document.getElementById('rows');
  body.innerHTML = LISTS[tab][year].map(posted =>
    '<tr><td>' + posted + '</td><td><span class="sr-only">Download ' +
    (tax ? 'tax form' : 'statement') + ' for: </span><button type="button">' +
    (tax ? '1099-INT' : 'Statement') + '</button></td></tr>').join('');
  for (const b of body.querySelectorAll('button')) {
    b.addEventListener('click', () => {
      window.__pressed.push(year);
      save(year);
    });
  }
}

function options(id, years) {
  return years.map(y => '<option data-guid="' + id + '-' + y + '">' + y + '</option>').join('');
}

function open(tab) {
  for (const t of document.querySelectorAll('[role=tab]'))
    t.setAttribute('aria-selected', String(t.dataset.tab === tab));
  const years = Object.keys(LISTS[tab]).sort().reverse();
  let shown = years[0];
  const id = tab === 'tax' ? 'taxYear' : 'statementYear';
  const other = '<label for="otherYear">Other year</label><select id="otherYear" data-guid="otherYear"' +
    (ANOTHER === 'hidden before' ? ' style="display:none"' : '') + '>' +
    options('otherYear', ANOTHER === 'hidden before' ? ['2025', '2024', '2023']
                                                     : ['2025', '2024', '2023', '2022', '2021', '2020', '2019', '2018']) +
    '</select>';
  const picker = '<label for="' + id + '">Year</label><select id="' +
    id + '" data-guid="' + id + '">' + options(id, years) + '</select>';
  document.getElementById('picker').innerHTML = tab !== 'tax' || !ANOTHER ? picker
    : ANOTHER === 'hidden before' ? other + picker : picker + other;
  const sel = document.getElementById(id);
  sel.value = shown;
  sel.addEventListener('change', () => { shown = sel.value; draw(tab, shown); });
  draw(tab, shown);
}
window.__open = open;
for (const t of document.querySelectorAll('[role=tab]'))
  t.addEventListener('click', () => open(t.dataset.tab));
open('statements');
</script></body></html>"""


@pytest.fixture()
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        launched = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield launched
    launched.close()
    driver.stop()


class Ally:
    """The app at home and Ally's page in a browser refused the network."""

    def __init__(self, browser, tmp_path, monkeypatch, capsys, another=""):
        # The browser is up before the harness stands in for Playwright.
        self.home = census.Home(ALLY, tmp_path, monkeypatch, capsys)
        self.home.config["min_pdf_bytes"] = 100
        self.home._write_config()
        self.site = self.home.mod.site
        ctx = browser.new_context(accept_downloads=True)
        ctx.route("**/*", lambda route: route.abort())
        self.page = ctx.new_page()
        self.page.set_content(PAGE % {"lists": json.dumps(LISTS), "pdfs": json.dumps(PDFS),
                                      "another": json.dumps(another)})
        # The pauses a run takes for Ally's own page are cut short, as the
        # other page tests here cut them.
        wait = self.page.wait_for_timeout
        self.page.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        # Reaching the page is tested elsewhere, and a goto would name
        # Ally's real host. The page above is the documents page.
        monkeypatch.setattr(self.site, "goto_documents", lambda page: True)
        self.asked = []
        download = self.site.ally_download

        def counted(page, ctx, account, date, *args, **kwargs):
            self.asked.append(date[:4])
            return download(page, ctx, account, date, *args, **kwargs)
        monkeypatch.setattr(self.site, "ally_download", counted)

    def lists(self, *years):
        """The forms Ally's API lists, filed by tax year as discovery files them."""
        app = self.home.build()
        for y in years:
            app._record_ally_doc({"documentId": "INVENTED%s1099" % y, "date": "%s-12-31" % y,
                                  "title": "Form 1099-INT", "account": "", "kind": "tax",
                                  "label": "", "occurrence": 0, "ambiguous": False})
        app.discovery.save()

    def run(self):
        """One Run All over what is listed, as the app's main ends it, and
        what it said, its run summary and its result for the panel."""
        app = self.home.build()
        app.check_session = lambda *_a, **_k: None
        app._on_its_site = lambda: self.page
        app.stats["mode"] = "all"
        self.home.capsys.readouterr()
        self.asked.clear()
        try:
            app.process(app._select())
        finally:
            app.progress.save(leaving=True)
            app.discovery.save(leaving=True)
            app.write_run_summary()
        said = self.home.capsys.readouterr().out
        line = [x for x in said.splitlines() if x.startswith("PAPERPULL_RUN_RESULT ")]
        assert len(line) == 1, said
        return SimpleNamespace(
            app=app, said=said, result=json.loads(line[0].split(" ", 1)[1]),
            summary=app.paths.run_summary.read_text(encoding="utf-8"), asked=list(self.asked))

    def record(self, year):
        app = self.home.build()
        return next(v for v in app.progress.data.values() if v.get("date", "").startswith(year))

    def rows(self, year):
        path = self.home.build().paths.document_index_csv
        if not path.exists():
            return []
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [r for r in csv.DictReader(f) if r["Document Date"].startswith(year)]

    def manual_review(self):
        return sorted(p.name for p in self.home.build().paths.manual_review.rglob("*") if p.is_file())

    def failure_files(self):
        return sorted(p.name for p in self.home.build().paths.diagnostics.glob("failure-*"))

    def pressed(self):
        return self.page.evaluate("window.__pressed")


def _summary_line(summary: str, start: str) -> str:
    return next((x for x in summary.splitlines() if x.startswith(start)), "")


def test_a_form_older_than_the_picker_is_said_once_and_left(browser, tmp_path, monkeypatch, capsys):
    """The 2019 form is not counted for Manual Review, which holds nothing,
    is not tried again by the next run, writes no failure file, and has one
    row in the index however many runs see it. 2024's form, which the
    picker reaches, is saved as before."""
    ally = Ally(browser, tmp_path, monkeypatch, capsys)
    ally.lists("2024", "2019")
    first = ally.run()
    second = ally.run()

    # The three things #152 saw, gathered so a failure names each of them.
    wrong = []
    if first.result["manual_review"] or second.result["manual_review"]:
        wrong.append("Manual Review holds %s and the runs counted %d and %d there" % (
            ally.manual_review() or "nothing", first.result["manual_review"],
            second.result["manual_review"]))
    if second.asked:
        wrong.append("the next run tried %s again" % second.asked)
    if ally.failure_files():
        wrong.append("%d failure files were written for a known limit" % len(ally.failure_files()))
    if len(ally.rows("2019")) != 1:
        wrong.append("the index holds %d rows for the form" % len(ally.rows("2019")))
    assert not wrong, wrong

    assert first.asked == ["2024", "2019"], first.asked
    assert ally.pressed() == ["2024"], "only the form the picker reaches is pressed"
    assert first.result["failed"] == 0 and second.result["failed"] == 0, (first.result, second.result)
    assert first.result["new_files"] == 1, first.result
    assert _summary_line(first.summary, "Needs manual review:").endswith(" 0"), first.summary
    for run in (first, second):
        reach = _summary_line(run.summary, "Not reachable on Ally's page:")
        assert reach.endswith(" 1"), "the summary does not say the form is out of reach\n" + run.summary
    assert re.search(r"2019.*year picker starts at 2020", first.said), first.said
    assert ally.record("2019")["state"] == State.NO_RECEIPT_AVAILABLE.value, ally.record("2019")
    assert _summary_line(second.summary, "Skipped (already done):").endswith(" 1"), (
        "only 2024's form was already done\n" + second.summary)
    assert ally.rows("2019")[0]["Processing Status"] == State.NO_RECEIPT_AVAILABLE.value
    assert len(ally.rows("2024")) == 1


def test_a_capture_that_failed_is_a_failure_tried_again_with_one_row(
        browser, tmp_path, monkeypatch, capsys):
    """2021 is in the picker, and its list holds no form, so nothing is
    pressed and nothing saved. That is a failure the next run tries again,
    never one counted for an empty Manual Review folder, and its row is
    written once."""
    ally = Ally(browser, tmp_path, monkeypatch, capsys)
    ally.lists("2021")

    first = ally.run()
    assert first.asked == ["2021"] and ally.pressed() == []
    assert first.result["manual_review"] == 0, first.result
    assert first.result["failed"] == 1, first.result
    assert ally.record("2021")["state"] == State.FAILED.value, ally.record("2021")
    assert _summary_line(first.summary, "Not reachable on Ally's page:").endswith(" 0"), first.summary

    second = ally.run()
    assert second.asked == ["2021"], "a capture that failed is tried again"
    assert second.result["failed"] == 1 and second.result["manual_review"] == 0, second.result
    assert len(ally.rows("2021")) == 1, ally.rows("2021")
    assert ally.manual_review() == []


def test_a_form_newer_than_the_picker_is_tried_again(browser, tmp_path, monkeypatch, capsys):
    """A picker that does not yet show a year has not reached it yet, as in
    the days after a new year, so only a year older than its first is out
    of reach. 2026 is a failure the next run tries again."""
    ally = Ally(browser, tmp_path, monkeypatch, capsys)
    ally.lists("2026")
    first = ally.run()
    assert first.result["failed"] == 1 and first.result["manual_review"] == 0, first.result
    assert ally.record("2026")["state"] == State.FAILED.value
    assert ally.run().asked == ["2026"]


def test_a_picker_whose_years_arrive_late_still_reaches_them(browser, tmp_path, monkeypatch, capsys):
    """A picker read before the rest of its years arrived, offering only its
    newest, would have made 2022 look out of reach for good. It is read
    again before that is decided, and 2022's form is saved. The first read
    is stood in, so no timer decides what it sees."""
    ally = Ally(browser, tmp_path, monkeypatch, capsys)
    ally.lists("2022")
    picker, reads = ally.site._year_picker, []

    def early(page):
        sel, years, unread = picker(page)
        reads.append(years)
        return (sel, years[:1], unread) if len(reads) == 1 else (sel, years, unread)
    monkeypatch.setattr(ally.site, "_year_picker", early)
    first = ally.run()
    assert reads[0] == TAX_YEARS and len(reads) > 1, reads
    assert ally.pressed() == ["2022"], ally.pressed()
    assert first.result["new_files"] == 1, first.result
    assert ally.record("2022")["state"] == State.COMPLETED.value


def test_a_picker_that_could_not_be_read_decides_nothing_for_good(
        browser, tmp_path, monkeypatch, capsys):
    """A dropdown before the year picker could not be read, so the picker
    found may not be the one the list follows, and what it offers says
    nothing for good. The form is a failure tried again."""
    ally = Ally(browser, tmp_path, monkeypatch, capsys)
    ally.lists("2019")
    picker = ally.site._year_picker
    monkeypatch.setattr(ally.site, "_year_picker",
                        lambda page: (lambda s, y, _u: (s, y, True))(*picker(page)))
    first = ally.run()
    assert first.result["failed"] == 1 and first.result["manual_review"] == 0, first.result
    assert ally.record("2019")["state"] == State.FAILED.value
    assert ally.run().asked == ["2019"]


@pytest.mark.parametrize("another, year", [("hidden before", "2022"), ("shown after", "2019")])
def test_a_page_with_another_dropdown_of_years_decides_nothing_for_good(
        browser, tmp_path, monkeypatch, capsys, another, year):
    """The year picker is taken as the first dropdown of years on the page,
    shown or not. A hidden one of another list before it, offering 2023 on,
    made 2022's form, which the picker on screen reaches, look out of reach
    for good. A second one shown after it, offering 2019, leaves which
    picker the list follows in doubt. Either way the form is a failure
    tried again, never left for good."""
    ally = Ally(browser, tmp_path, monkeypatch, capsys, another=another)
    ally.lists(year)
    first = ally.run()
    assert ally.record(year)["state"] != State.NO_RECEIPT_AVAILABLE.value, ally.record(year)
    assert first.result["manual_review"] == 0, first.result
    if not first.result["new_files"]:
        assert first.result["failed"] == 1, first.result
        assert ally.run().asked == [year], "a form not known to be out of reach is tried again"


def test_redownload_asks_for_a_form_out_of_reach_again(browser, tmp_path, monkeypatch, capsys):
    """Out of reach is final for the runs that follow, and --redownload, which
    asks for everything in scope again, asks for it too, in case Ally's
    picker has come to reach it."""
    ally = Ally(browser, tmp_path, monkeypatch, capsys)
    ally.lists("2019")
    ally.run()
    app_args = ally.home.mod.build_parser().parse_args(["--config", str(ally.home.cfg), "--redownload"])
    monkeypatch.setattr(ally.home, "build", lambda: ally.home.mod.App(app_args))
    again = ally.run()
    assert again.asked == ["2019"], again.asked
    assert len(ally.rows("2019")) == 1, ally.rows("2019")
