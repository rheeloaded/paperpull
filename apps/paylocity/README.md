# Paylocity Pay Statement Downloader (local, supervised, READ-ONLY)

Downloads your **pay statements** from Paylocity as PDFs and keeps an index CSV.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses Paylocity's 2FA.

## Read-only by design (this is a payroll site)

A payroll portal can change where your wages land, your tax withholding, and
your personal details. This tool only reads the Pay History area and downloads
the statement PDFs Paylocity has already generated. It **never** changes a bank
account, routing number, W-4 or withholding, address, beneficiary, benefits
enrolment, or any setting.

In fact nothing on the page is ever clicked. Discovery and download are plain
GETs to the same JSON endpoints Paylocity's own Pay History screen uses, over
your signed-in session. On a site that can move money, not activating a control
at all is the strongest guarantee there is. A hard blocklist
(`FORBIDDEN_CONTROL_RE`) and a document allowlist (`SAFE_DOC_CONTROL_RE`) still
guard the one navigation click, and every URL the app requests must be on
Paylocity's own host. All of it is covered by tests.

## How it connects

`login.bat` opens an ordinary Chromium (debugging port **9239**) at
`access.paylocity.com`. You sign in with your **Company ID**, username and
password, or your company's single sign-on, and complete any MFA yourself. The
tool then attaches to that already-signed-in browser and reads only what you
are authorised to see. The Company ID identifies your employer and is typed by
you at sign-in; this app never handles, stores, or needs it.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9239 is this app's alone, so several signed-in browsers can be open at
once without two apps sharing a profile.

## How the site is built

The signed-in portal spans a few hosts (`go.paylocity.com`,
`login.paylocity.com`). Pay statements live in **Pay > Pay History**, an
Angular screen served from `login.paylocity.com/Escher/`. It is fed by JSON
endpoints, and a statement PDF is generated on demand: the app enqueues a
report, polls until Paylocity returns a download URL, and fetches the PDF. Every
step is a GET carrying your session cookie.

## Documents captured

| Folder | Contents |
|---|---|
| `Pay Statements\` | Your pay statements (regular, off-cycle, bonus), one PDF each |
| `Manual Review\` | Files that failed PDF validation |

Filenames: `YYYY-MM-DD Paylocity Pay Statement.pdf`. A statement sharing a date
with another (a regular plus an off-cycle) is disambiguated by its document
number so nothing collapses into one file.

**Current year only, for now.** Paylocity's Pay History defaults to a
"YTD" (year-to-date) view, and this app reads that default, so a run
collects the current calendar year's statements. Older years sit behind
the page's year filter, which is not wired up yet. Verified: the 2026
run found and downloaded all 12 of that year's statements.

W-2s and other tax forms are **not** fetched yet. The routing and the folder
are in place, so adding them is a change to `paylocity_site.py` alone. Paylocity
returns W-2 data as JSON rather than a PDF, so that path needs its own work.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium (port 9239); sign in, open Pay History, **leave open** |
| 3 | `diagnose.bat` | Read-only look at what the API returns; downloads nothing |
| 4 | `run_pilot.bat` | 3 newest statements, then **stops** for your inspection |
| 5 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 6 | `run_all.bat` | Everything in scope (asks for `YES`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_documents.bat` | Re-validate every saved PDF |

Filters narrow what was discovered (the current year), so `--start-date`
and `--year` only apply within it until the year filter is wired up.

## Sensitive files

Pay statements show your salary, and often your address and a bank last-4. They
are saved to the folder you set as `output_dir` in `config.json`. Keep it
somewhere safe, and if that folder syncs to a cloud drive, know these documents
go with it. The index CSV deliberately records **no** amounts. The download
identity (which carries your employee id) is stored in `discovery.json` and
`progress.json` only, never in the CSV.

## Tests

```
.venv\Scripts\activate
pytest
```
