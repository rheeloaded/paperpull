"""An invented PayPal business account, shared by the business tests.

One tester's recording showed where a business account's statements are,
/reports/accountStatements, a page that asks for its own list as it loads,
a POST answered by a list of one object holding "reports" and "hasMore",
and draws a table of six cells a row, the last holding a Download button
whose press makes a hidden link with a download mark and clicks it a fifth
of a second later. What the recording did not keep, the values, the
link's address and any header the page sends, is invented here, both ways
the link could go, a blob the page builds and an address of PayPal's own.

Every value is invented. The ids and the name are made of letters and
digits in the shape the tester's were, and none is his. Whatever serves
these pages, the browser's router or a server on this machine, reads the
state of one Business and records each press and each flag in it.
"""
import base64
import json
from pathlib import Path

from paperpull_core.testkit import text_pdf

APP_DIR = Path(__file__).resolve().parents[1]
WWW = "https://www.paypal.com"
STATEMENTS_PATH = "/myaccount/statements/monthly"
STATEMENTS = WWW + STATEMENTS_PATH
SETTINGS = "/businessmanage/account/accountAccess"
REPORTS = "/reports/accountStatements"
LIST = "/reports/apis/rux/reports/list"
FILES = "/reports/apis/rux/reports/download/"
PRESSED = "/reports/apis/pressed"
FLAG = "/reports/apis/flag"

# None of these may reach a file the app writes.
ACCOUNT_ID = "QZ4XKRWPT7MVN"
OTHER_ID = "QZXKRWPTKMVNB"
HOLDER = "Zorvexquill"
CANARIES = (ACCOUNT_ID, OTHER_ID, HOLDER)


def statement(first: str, last: str, before: str, moved: tuple, due: str,
               kind: str = "Monthly account statement") -> bytes:
    """A statement's text the way a real one carries dates, its own first
    and last day, the day the period before it closed, a few transactions
    inside it and a payment due after it. Each date is MM/DD/YYYY, and
    every one but the first and the last is another statement's to find."""
    return text_pdf(["PayPal", kind,
                     "Statement period %s to %s" % (first, last),
                     "Beginning balance as of %s" % before]
                    + ["%s %s" % pair for pair in moved]
                    + ["Ending balance as of %s" % last, "Payment due %s" % due])


AUGUST = statement("08/01/2031", "08/31/2031", "07/31/2031",
                   (("08/03/2031", "Payment received"), ("08/17/2031", "Transfer to bank"),
                    ("08/29/2031", "Fee")), "09/25/2031")
JULY = statement("07/01/2031", "07/31/2031", "06/30/2031",
                 (("07/03/2031", "Payment received"), ("07/17/2031", "Transfer to bank"),
                  ("07/29/2031", "Fee")), "08/25/2031")
JUNE = statement("06/01/2031", "06/30/2031", "05/31/2031",
                 (("06/03/2031", "Payment received"), ("06/17/2031", "Transfer to bank")),
                 "07/25/2031")
MAY = statement("05/01/2031", "05/31/2031", "04/30/2031",
                (("05/03/2031", "Payment received"), ("05/17/2031", "Transfer to bank")),
                "06/25/2031")
# A statement asked for over two months, July and August. Its text names
# July's last day among its transactions and August's last day as its own.
CUSTOM = statement("07/01/2031", "08/31/2031", "06/30/2031",
                   (("07/17/2031", "Transfer to bank"), ("07/31/2031", "Payment received"),
                    ("08/12/2031", "Fee")), "09/25/2031",
                   kind="Custom account statement")
# The same custom statement with a payment on the first day of its second
# month. Its text names its own first day and August's both, and its last
# day is August's too, so beside August's statement it names each as
# plainly as the other.
CUSTOM_TIES = statement("07/01/2031", "08/31/2031", "06/30/2031",
                        (("07/17/2031", "Transfer to bank"), ("08/01/2031", "Payment received"),
                         ("08/12/2031", "Fee")), "09/25/2031",
                        kind="Custom account statement")


def row(rid, duration, status="COMPLETED", kind="PDF", created="2031-09-02T10:15:00Z"):
    return {"id": rid, "createdOn": created, "duration": duration, "fileFormat": kind,
            "action": "DOWNLOAD", "type": "MONTHLY_STATEMENT", "reportStatus": status}


def shown(period, created, kind, status, control):
    """What one row of the drawn table says, and which control it ends in,
    "download", "csv", "generate" or "none"."""
    return {"period": period, "created": created, "kind": kind, "status": status,
            "control": control}


# One account's list. Two ready PDF statements, the CSV of one of them, and
# the next month's PDF still being made.
ROWS = [
    row(ACCOUNT_ID + "1", "Aug 1, 2031 - Aug 31, 2031"),
    row(ACCOUNT_ID + "2", "Aug 1, 2031 - Aug 31, 2031", kind="CSV"),
    row(ACCOUNT_ID + "3", "Sep 1, 2031 - Sep 30, 2031", status="IN_PROGRESS"),
    row(ACCOUNT_ID + "4", "Jul 1, 2031 - Jul 31, 2031", created="2031-08-02T09:00:00Z"),
]
SHOWN = {
    ACCOUNT_ID + "1": shown("Aug 1, 2031 - Aug 31, 2031", "Sep 2, 2031", "PDF", "Ready",
                            "download"),
    ACCOUNT_ID + "2": shown("Aug 1, 2031 - Aug 31, 2031", "Sep 2, 2031", "CSV", "Ready", "csv"),
    ACCOUNT_ID + "3": shown("Sep 1, 2031 - Sep 30, 2031", "Oct 1, 2031", "PDF", "In progress",
                            "generate"),
    ACCOUNT_ID + "4": shown("Jul 1, 2031 - Jul 31, 2031", "Aug 2, 2031", "PDF", "Ready",
                            "download"),
}
SERVED = {ACCOUNT_ID + "1": AUGUST, ACCOUNT_ID + "4": JULY}
# A custom statement over July and August, ready, its row as the list and
# the table give it.
CUSTOM_ID = OTHER_ID + "7"
CUSTOM_ROW = row(CUSTOM_ID, "Jul 1, 2031 - Aug 31, 2031", created="2031-09-03T10:00:00Z")
CUSTOM_SHOWN = shown("Jul 1, 2031 - Aug 31, 2031", "Sep 3, 2031", "PDF", "Ready", "download")
CUSTOM_FILED = "2031-08-31 PayPal Statement.pdf"
# The name a download is given, shaped like the tester's, an account's id
# and two stamps of the period.
SAVED_NAME = ACCOUNT_ID + "-MSR-20310801000000-20310831235959.PDF"
# The two statements the list holds as ready, as the app files them.
FILED = {"2031-08-31 PayPal Monthly Statement.pdf": AUGUST,
         "2031-07-31 PayPal Monthly Statement.pdf": JULY}

REPORTS_HTML = """<!doctype html><html><head><title>%(title)s</title></head><body>
<main><h1>%(heading)s</h1>
<div class="actions"><button id="create" type="button">Create statement</button>
<button id="request" type="button">Request statement</button></div>
<div data-testid="reportsTable"><table aria-label="Statements" data-testid="statementsTable">
<thead><tr><th></th><th>Statement period</th><th>Requested</th><th>Format</th>
<th>Status</th><th></th></tr></thead>
<tbody id="rows"></tbody><tfoot><tr><td colspan="6" id="foot"></td></tr></tfoot></table></div>
%(extra)s</main>
<script>
const K = %(knobs)s;
let pageNo = 1;
const tell = (path) => fetch(path, {method: 'POST', keepalive: true});
const flag = (what) => tell('%(flag)s?what=' + what);
document.getElementById('create').onclick = () => flag('create');
document.getElementById('request').onclick = () => flag('request');
function bytes(b64) {
  const s = atob(b64); const a = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
  return a;
}
function save(id) {
  const a = document.createElement('a');
  a.style.display = 'none';
  if (K.variant === 'blob') {
    a.href = URL.createObjectURL(new Blob([bytes(K.files[id])], {type: 'application/pdf'}));
  } else {
    a.href = '%(files)s' + id;
  }
  a.setAttribute('download', K.name);
  document.body.appendChild(a);
  a.click();
  setTimeout(() => a.remove(), 100);
}
function cell(html) { const td = document.createElement('td'); td.innerHTML = html; return td; }
function control(id, kind) {
  if (kind === 'download') return '<button type="button" class="dl" data-row="' + id + '">Download' +
    '<span role="img" aria-label="download" class="icon"><svg width="8" height="8"></svg></span></button>';
  if (kind === 'csv') return '<button type="button" class="flag" data-what="csv">Download CSV</button>';
  if (kind === 'generate') return '<button type="button" class="flag" data-what="generate">' +
    'Generate statement</button>';
  return '';
}
function draw(list) {
  const body = document.getElementById('rows');
  body.innerHTML = '';
  for (const row of (K.reverse ? [...list.reports].reverse() : list.reports)) {
    const s = K.shown[row.id];
    const tr = document.createElement('tr');
    tr.appendChild(cell('<span class="icon"><svg width="8" height="8"></svg></span>'));
    tr.appendChild(cell('<div>Monthly statement</div><div>' + s.period + '</div>'));
    tr.appendChild(cell(s.created));
    tr.appendChild(cell(s.kind));
    tr.appendChild(cell(s.status));
    tr.appendChild(cell(control(row.id, s.control)));
    body.appendChild(tr);
  }
  document.getElementById('foot').innerHTML = (list.hasMore && K.next)
    ? '<button type="button" class="next" aria-label="Next page">&gt;</button>' : '';
  for (const b of document.querySelectorAll('button.dl')) b.onclick = () => {
    tell('%(pressed)s?row=' + b.dataset.row);
    setTimeout(() => save(b.dataset.row), 200);
  };
  for (const b of document.querySelectorAll('button.flag')) b.onclick = () => flag(b.dataset.what);
  for (const b of document.querySelectorAll('button.next')) b.onclick = () => { pageNo += 1; load(); };
}
async function load() {
  const r = await fetch('%(list)s', {method: 'POST',
    headers: {'content-type': 'application/json', 'x-csrf-token': 'invented-token'},
    body: JSON.stringify({filters: {}, page: pageNo, reportType: 'STATEMENT', sortBy: 'createdOn'})});
  draw((await r.json())[0]);
}
load();
</script></body></html>"""

SETTINGS_HTML = ("<!doctype html><html><head><title>PayPal</title></head><body><main>"
                 "<h1>Account access</h1><a href='/businessmanage/users'>Manage users</a>"
                 "</main></body></html>")


class Business:
    """What the invented account shows, set by each test, and what it saw.

    `pages` is the list, one answer a page. `variant` is how a press hands
    its statement over, "blob" or "direct". `next` puts a next-page control
    under a list with more to come, and `reverse` draws the table in the
    opposite order to the answer. `list_answers` and `reports_page` say
    whether the list request and the statements page are answered at all.
    `served` is the PDF each row's download gives. `pressed` holds each
    press on a Download button by its row, and `flags` each press on a
    control the app must never press."""

    def __init__(self, variant="blob"):
        self.variant = variant
        self.pages = [list(ROWS)]
        self.next = False
        self.reverse = False
        self.list_answers = True
        self.reports_page = True
        self.served = dict(SERVED)
        self.shown = dict(SHOWN)
        self.title = "Statements"
        self.heading = "Statements"
        self.extra = ""
        self.lists = 0
        # List requests without the page's own mark, which only the app
        # asking for the list itself would send.
        self.unmarked = 0
        self.pressed, self.flags = [], []

    def page_html(self) -> str:
        knobs = {"variant": self.variant, "next": self.next, "reverse": self.reverse,
                 "name": SAVED_NAME, "shown": self.shown,
                 "files": {rid: base64.b64encode(pdf).decode() for rid, pdf in self.served.items()}}
        return REPORTS_HTML % {"title": self.title, "heading": self.heading, "extra": self.extra,
                               "knobs": json.dumps(knobs), "files": FILES, "list": LIST,
                               "flag": FLAG, "pressed": PRESSED}

    def list_answer(self, asked: str) -> str:
        """The answer to the list request whose body was `asked`, the page it
        names, in the shape the tester's answer had."""
        try:
            page = int(json.loads(asked or "{}").get("page", 1))
        except (TypeError, ValueError):
            page = 1
        index = max(0, min(page - 1, len(self.pages) - 1))
        self.lists += 1
        return json.dumps([{"reports": self.pages[index],
                            "hasMore": index < len(self.pages) - 1}])

    def file(self, path: str):
        """The PDF a direct address of a row's statement answers, or None."""
        return self.served.get(path[len(FILES):]) if path.startswith(FILES) else None


def config(tmp_path, **more) -> Path:
    cfg = json.loads((APP_DIR / "config.example.json").read_text(encoding="utf-8"))
    cfg.update({"owner": "Tester", "output_dir": str(tmp_path / "out"),
                "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg.update(more)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def result_of(out: str):
    """The run result line a run printed last, or None."""
    found = [json.loads(line.split(" ", 1)[1]) for line in out.splitlines()
             if line.startswith("PAPERPULL_RUN_RESULT ")]
    return found[-1] if found else None


def statements(tmp_path, folder: str = "Statements") -> dict:
    """The PDFs a run left in one of its folders, by name. The archive's
    Statements folder unless another is named, Manual Review say."""
    where = tmp_path / "out" / folder
    return {p.name: p.read_bytes() for p in sorted(where.glob("*.pdf"))} if where.is_dir() else {}


def everything_written(root: Path) -> str:
    """Every file a run wrote under its folder, names and text, as one
    string, so a value is looked for wherever it could have gone."""
    parts = []
    for p in sorted(root.rglob("*")):
        parts.append(str(p.relative_to(root)))
        if p.is_file() and p.suffix.lower() != ".pdf":
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)
