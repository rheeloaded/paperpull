# Robinhood Document Downloader (local, supervised, READ-ONLY)

Downloads your Robinhood **account statements** and **tax documents** as PDFs
and keeps an index CSV.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses Robinhood's 2FA / device approval.

## Read-only by design (this is a brokerage / crypto account)

The tool only reads the reports/statements/tax areas and saves PDFs Robinhood
already generated. It **never** buys, sells, trades, places or cancels
orders, transfers/withdraws/deposits money, moves or converts crypto,
exercises options, closes positions, stakes, applies for products, or changes
any setting. A control must pass **two** checks before it can be clicked: it
must look like a document action *and* match nothing in a large trading /
money blocklist (`FORBIDDEN_CONTROL_RE` in `robinhood_site.py`). Covered by
tests (`tests/test_doc_types.py`). There is no code path that submits a form
or confirms a dialog.

## How it connects

Robinhood has strong bot detection and 2FA, so the tool does not launch its
own browser. `login.bat` opens an ordinary Chromium (debugging port **9226**)
that **you** sign into; the tool connects to that already-signed-in browser
and reads the pages you're authorized to see. No stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9226 keeps this separate from Walmart (9222), Amazon (9223), Wealthfront
(9224), and USAA (9225), so several signed-in browsers can be open at once.

## Documents captured

| Folder | Contents |
|---|---|
| `Statements\` | Monthly / account statements |
| `Tax Documents\` | Consolidated 1099, crypto 1099, 1099-B/DIV/INT, 1042-S, etc. |
| `Other Documents\` | Anything else (only if you widen `document_types`) |
| `Manual Review\` | Files that failed PDF validation |

Trade confirmations are **skipped by default** (they can number in the
thousands). To include them, edit `skip_patterns` in `document_rules.json` and
add "Trade Confirmation" to `document_types` in `config.json`.

Filenames: `YYYY-MM-DD Robinhood <Summary>.pdf`, e.g.
`2025-12-31 Robinhood Monthly Statement.pdf`,
`2025-12-31 Robinhood Consolidated 1099 Tax Form.pdf`.

## First run needs a repair pass

Like the USAA project, Robinhood's pages could not be inspected while this was
built (it's behind a login). `robinhood_site.py` ships with best-guess
selectors, a generic document-list scraper, and a JSON-API capture. **Run
`diagnose.bat` after signing in** - it writes the real page structure to
`Diagnostics\` - then the selectors get adjusted to match before the pilot.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium (port 9226); sign in, open your documents area, **leave open** |
| 3 | `diagnose.bat` | Read-only look at the page structure; downloads nothing |
| 4 | `run_pilot.bat` | 5 newest documents, then **stops** for your inspection |
| 5 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 6 | `run_all.bat` | Everything in scope (asks for `YES`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_documents.bat` | Re-validate every saved PDF |

## Delete-safe (paperless-ngx workflow)

Once a document downloads successfully it is remembered as done for good - you
can delete the PDF (e.g. after importing into paperless-ngx) and it will NOT
be re-downloaded. Each run writes `new-this-run.txt` listing exactly what was
downloaded that run. To rebuild deleted files, add `--redownload`.

## Sensitive files

These live in OneDrive, so they sync to Microsoft's cloud. Tax forms may
contain your SSN. The index CSV records no account numbers, balances, or SSN.

## Tests

```
.venv\Scripts\activate
pytest
```
