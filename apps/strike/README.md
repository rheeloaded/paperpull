# Strike (strike.me) statement downloader

Downloads your own **monthly account statements**, as a PDF with Strike's
CSV of the same month beside it, each year's **annual transactions** CSV,
and any **tax forms** Strike issues, for your records. Read-only,
delete-safe, and part of [PaperPull](../../README.md).

Mapped on 2026-11-27 against a real personal account, where Discover
listed all 13 statements, twelve months and one year. Tax forms are read
from the page's own code, since that account had none yet. If you have
one, run Diagnose and attach the file to #258.

## How it reads the site

You sign in yourself at `auth.strike.me`, and the browser lands on the
dashboard at `dashboard.strike.me`. Its Documents page (user menu, then
Documents) has Taxes and Statements tabs, and each tab reads a small JSON
API on the dashboard's own host. The app asks that same API, from inside
your signed-in tab, for the list and then for each file, sending the same
`Accept` header the page's own Export as PDF / Export as CSV menu sends.
Nothing on the page is clicked, and nothing is asked of any other host.

## What it checks before filing

- A statement **PDF** must be a PDF and must print its month's closing day
  ("October 31 2026"). One that names another month is destroyed, not filed.
- A statement **CSV** must have Strike's twelve-column header, and every row
  must be dated within that month. A month with no transactions is a header
  alone, which is accepted.
- The **annual transactions** entry is saved as its CSV only, with every row
  dated within that year. Strike's own page disables Export as PDF for it,
  and the PDF the server returns anyway did not add up, so the app never
  asks for it.

When a PDF saved and its CSV did not, the PDF is kept and the next run asks
for the CSV alone. Set `"save_statement_csv": false` in `config.json` to
save the PDFs only.

## What it will never do

Strike can buy, sell, send and receive bitcoin, deposit and withdraw
dollars, set up recurring purchases and target orders, open a loan and link
bank accounts. The app presses no control at all. Every request goes
through an allowlist of the four documents API paths on
`dashboard.strike.me` and follows no redirect. The blocklist in
`strike_site.py` still guards the one thing that can press, the survey
`diagnose` runs, which follows only a link whose whole text is a document
word. Tests pin each of those.

## Setup

```bat
setup.bat                         REM one-time: create the venv + install Playwright
login.bat                         REM opens a browser on port 9327, sign in yourself
paperpull strike diagnose         REM read-only survey, downloads nothing
paperpull strike pilot            REM download the newest 5 as a test
paperpull strike all              REM download every statement in scope
```

`diagnose` writes `Diagnostics/diagnose-documents.json`, a survey of the
page rather than a screenshot, since the dashboard shows balances. Any word
that is not on PaperPull's fixed list is written as its shape, and JSON is
recorded as shape only, never values.

## What it files

| Folder | What |
|---|---|
| `Statements/` | `YYYY-MM-DD Strike Account Statement.pdf` and `.csv` beside it, dated by the month's last day, and `YYYY-12-31 Strike Annual Transactions.csv` |
| `Tax Documents/` | Tax forms (1099s), as Strike issues them |

A Rename moves each statement's CSV with its PDF.

## When the site changes

The API paths, what each answers and what is taken are in the STATUS block
at the top of `strike_site.py`. The command flow is `strike_docs.py`. If a
list comes back in a shape the app does not know, the run stops and writes
a failure file rather than file part of it as the whole.
