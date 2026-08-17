# American Express Document Downloader (local, supervised, READ-ONLY)

Downloads your American Express **monthly statements**, **year-end summaries**,
and **tax documents** as PDFs and keeps an index CSV.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses American Express's 2FA / device approval.

## Read-only by design (this is a credit-card account)

The tool only reads the Statements & Activity / documents / tax areas and saves
PDFs American Express already generated. It **never** pays a bill, transfers a
balance, moves money, redeems rewards or points, applies for a card or product,
disputes a charge, books travel, cancels/locks a card, or changes any setting.
A control must pass **two** checks before it can be clicked: it must look like a
document action *and* match nothing in a large money / account blocklist
(`FORBIDDEN_CONTROL_RE` in `amex_site.py`). Covered by tests
(`tests/test_doc_types.py`). There is no code path that submits a form or
confirms a dialog.

## How it connects

American Express has strong bot detection (Akamai) and 2FA, so the tool does
not launch its own browser. `login.bat` opens an ordinary Chromium (debugging
port **9227**) that **you** sign into; the tool connects to that
already-signed-in browser and reads the pages you're authorized to see. No
stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9227 keeps this separate from Walmart (9222), Amazon (9223), Wealthfront
(9224), USAA (9225), and Robinhood (9226), so several signed-in browsers can be
open at once.

## Documents captured

| Folder | Contents |
|---|---|
| `Statements\` | Monthly billing / account statements |
| `Year-End Summaries\` | Annual spending / year-end summary |
| `Tax Documents\` | 1099-INT, 1099-MISC, 1099-C, etc. (if your account has them) |
| `Other Documents\` | Anything else (only if you widen `document_types`) |
| `Manual Review\` | Files that failed PDF validation |

Cardmember agreements, disclosures, privacy notices, benefits guides, and other
boilerplate are **skipped by default** (see `skip_patterns` in
`document_rules.json`).

Filenames: `YYYY-MM-DD American Express <Summary>.pdf`, e.g.
`2025-12-31 American Express Monthly Statement.pdf`,
`2025-12-31 American Express Year-End Summary.pdf`,
`2025-12-31 American Express 1099-INT Tax Form.pdf`.

## If a site change breaks it

All the site-specific logic lives in `amex_site.py`. If American Express
redesigns its pages and discovery or download stops working, run `diagnose.bat`
after signing in — it dumps the current page structure to `Diagnostics\` so the
selectors in `amex_site.py` can be updated to match.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium (port 9227); sign in, open Statements & Activity, **leave open** |
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

## A second account

`login.bat spouse` + `python add_account.py spouse` set up a second Amex login
with its own folders, browser profile, and debugging port - no re-downloading
and no mixing of data.

## Sensitive files

Statements and especially tax forms can contain your SSN and account numbers.
They're saved to the output folder you set as `output_dir` in `config.json`
(the default is this app's own folder). Keep it somewhere safe, and if that
folder syncs to a cloud drive, know these documents go with it. The index CSV
deliberately records **no** account numbers, balances, or SSN — only document
metadata (dates, titles, filenames).

## Tests

```
.venv\Scripts\activate
pytest
```
