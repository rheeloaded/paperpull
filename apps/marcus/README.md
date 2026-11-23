# Marcus by Goldman Sachs statement downloader

Downloads your **Marcus by Goldman Sachs** (US) **account statements** as PDFs
and keeps an index CSV. Read-only, delete-safe, part of
[PaperPull](../../README.md).

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses the site's 2FA / verification.

## Read-only by design (this is a savings account)

The tool only reads the Documents page and saves the statement PDFs Marcus
already generated. It **never** moves money, makes a transfer, deposit or
withdrawal, links a bank, opens or closes an account, enrolls in anything, or
changes any setting. A control must pass **two** checks before it can be
clicked: it must look like a document action *and* match nothing in a large
money / account blocklist (`FORBIDDEN_CONTROL_RE` in `marcus_site.py`).
Covered by tests (`tests/test_doc_types.py`). There is no code path that
submits a form or confirms a dialog.

## How it connects

`login.bat` opens an ordinary browser (debugging port **9327**) that **you**
sign into; the tool connects to that already-signed-in browser and reads the
pages you're authorized to see. No stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

## How it works

- Statements live at `www.marcus.com/us/en/documents` under the **Account
  Statements** tab as a single **table**: masked account | product | the
  statement's date (MM/DD/YYYY), which is the download link.
- A **year picker** reloads the table one year at a time. Discovery reads the
  year on show, then selects each other year and reads those rows too. A year
  the table will not show stops the run, so a list is never called whole when
  it is not.
- Each row's date link fires a real browser download event that Playwright
  captures directly, which is saved to `Statements/` as
  `YYYY-MM-DD Marcus Online Savings Statement X1234.pdf` (the last digits of
  the account, so two accounts' statements of one day are two files).
- A statement's link is pressed **once**. One that did not arrive is tried
  again by the next run, never by a second press in the same run.

## Not covered yet

- The **wrong-document check** (`refuse_wrong_documents`) stays off. A row is
  dated the day after the period its statement prints (a row of 11/01 holds
  "Statement Period 10/01 to 10/31"), so a file never names its row's date.
  Files are named by the row's date, as the page shows it.
- The **Tax Forms** tab (1099-INT). Only Account Statements are read.
- Any **Account Type** other than the one the Documents page opens on. Built
  and tested against an account with Online Savings only.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf |
| 2 | `login.bat` | Opens a browser (port 9327); sign in, open Documents, **leave open** |
| 3 | `paperpull marcus pilot` | 5 newest statements, then **stops** for your inspection |
| 4 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 5 | `paperpull marcus all` | Every statement in scope (asks for `YES`) |
| any time | `paperpull marcus resume` | Continue after an interruption; never redoes finished work |
| any time | `paperpull marcus verify` | Re-validate every saved PDF |
| any time | `paperpull marcus diagnose` | Read-only dump of the page structure; downloads nothing |

## Delete-safe (paperless-ngx workflow)

Once a statement downloads successfully it is remembered as done for good, you
can delete the PDF (e.g. after importing into paperless-ngx) and it will NOT be
re-downloaded. Each run writes `new-this-run.txt` listing exactly what was
downloaded that run. To rebuild deleted files, add `--redownload`.

## A second login

`paperpull marcus add-account spouse` + `login.bat spouse` set up a second
Marcus login with its own folders, browser profile, and debugging port, no
re-downloading and no mixing of data.

## Tests

```
.venv\Scripts\activate
pytest
```
