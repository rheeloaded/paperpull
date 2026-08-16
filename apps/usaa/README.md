# USAA Document Downloader (local, supervised, READ-ONLY)

Downloads your USAA **bank statements**, **tax documents**, and **insurance
documents** as PDFs and keeps an index CSV.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses USAA's 2FA or security checks.

## Read-only by design (this is a bank)

The tool only reads the document areas and saves PDFs USAA already generated.
It **never** transfers money, pays bills, uses Zelle/wire, deposits,
withdraws, trades, disputes charges, files insurance claims, opens/applies
for products, locks/activates cards, or changes any setting. A control must
pass **two** checks before it can be clicked: it must look like a document
action *and* match nothing in a large transactional blocklist
(`FORBIDDEN_CONTROL_RE` in `usaa_site.py`). This is covered by tests
(`tests/test_doc_types.py`). There is no code path that submits a form or
confirms a dialog.

## How it connects

USAA has strong bot detection and 2FA, so the tool does not launch its own
browser. `login.bat` opens an ordinary Chromium (debugging port **9225**)
that **you** sign into; the tool then connects to that already-signed-in
browser and reads the pages you're authorized to see. No stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9225 keeps this separate from Walmart (9222), Amazon (9223), and
Wealthfront (9224), so several signed-in browsers can be open at once.

## Documents captured

| Folder | Contents |
|---|---|
| `Statements\` | Checking, savings, credit-card statements |
| `Tax Documents\` | 1099-INT, 1098, 5498, etc. (contain your SSN) |
| `Insurance Documents\` | Auto/home/renters policies, declarations, ID cards, insurance billing |
| `Other Documents\` | Anything else (only if you widen `document_types`) |
| `Manual Review\` | Files that failed PDF validation |

Filenames: `YYYY-MM-DD USAA <Summary>.pdf`, e.g.
`2025-12-31 USAA Checking Statement.pdf`,
`2025-12-31 USAA 1099-INT Tax Form.pdf`,
`2025-06-30 USAA Auto Insurance Policy.pdf`.

Naming rules are in `document_rules.json` (plain regex -> summary, editable,
no code changes needed).

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium (port 9225); sign in, open your Documents area, **leave open** |
| 3 | `diagnose.bat` | Read-only look at the page structure; downloads nothing |
| 4 | `run_pilot.bat` | 5 newest documents, then **stops** for your inspection |
| 5 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 6 | `run_all.bat` | Everything in scope (asks for `YES`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_documents.bat` | Re-validate every saved PDF |

Filters: `--type "Insurance Document"`, `--year 2025`,
`--start-date 2025-01-01`.

## First run needs a repair pass

Unlike the other projects, USAA's pages could not be inspected while this was
built (it's behind a login). `usaa_site.py` ships with best-guess selectors
and a generic document-list collector. **Run `diagnose.bat` after signing
in** — it writes the real page structure to `Diagnostics\` — then the
selectors in `usaa_site.py` get adjusted to match before the pilot.

## Sensitive files

These are inside OneDrive, so they sync to Microsoft's cloud (a deliberate
choice for this consolidated folder). Tax forms contain your SSN. The index
CSV records no account numbers, balances, or SSN - only what's needed to
find and verify a file.

## Tests

```
.venv\Scripts\activate
pytest
```
