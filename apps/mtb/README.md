# M&T Bank — mortgage document downloader (READ-ONLY)

Downloads your M&T mortgage **statements and documents** as PDFs from M&T's
online banking (`onlinebanking.mtb.com`). Read-only, delete-safe, part of
[PaperPull](../../README.md).

> **Status: the site layer is not verified yet.** M&T services its mortgages
> inside its own online banking (confirmed), but where the mortgage statements
> and documents live once signed in, and how a PDF is delivered, are not mapped
> yet. There are no guessed document URLs. Run `login.bat`, then `diagnose.bat`,
> and the real routes get written in from what it captures. The safety guard
> applies from the first run.

## Read-only by design (a mortgage can move real money)

This tool only opens the document area and downloads PDFs M&T has already
generated. It **never** pays the mortgage, sets up or edits autopay, moves
money, transfers, sends a wire or Zelle, changes escrow, requests a payoff,
refinances, or changes any setting. A control must pass **two** checks before
it may be clicked: it must look like a document action (`SAFE_DOC_CONTROL_RE`)
*and* match nothing in the blocklist (`FORBIDDEN_CONTROL_RE`), which is tuned
for a mortgage servicer. Every URL the app requests must be on an M&T host.
All of it is covered by tests.

## Setup

```bat
setup.bat                 REM one-time: venv + Playwright
login.bat                 REM opens Chromium on port 9240 — sign in yourself at mtb.com
diagnose.bat              REM read-only look at the document area; downloads nothing
run_pilot.bat             REM download the newest few as a test, then stop
run_all.bat               REM download everything in scope (asks for YES)
```

Sign in at `www.mtb.com/log-in` the way you normally do, get to your mortgage's
documents/statements area, and **leave the browser window open**. The tool
attaches to that already-signed-in browser and reads only what you can see. It
never handles your credentials or 2FA.

## Documents captured

| Folder | Contents |
|---|---|
| `Statements\` | Monthly mortgage statements |
| `Escrow & Insurance\` | Escrow analyses, hazard/flood insurance and property-tax notices |
| `Tax Documents\` | 1098 mortgage interest and any other tax forms |
| `Year-End Summaries\` | Year-end statements |
| `Other Documents\` | Anything else (created on demand) |
| `Manual Review\` | Files that failed PDF validation |

Filenames: `YYYY-MM-DD M&T Bank <Summary>.pdf`. Naming rules are in
`document_rules.json` (plain regex, editable) and are provisional until you
have seen what M&T actually calls things.

## If a site change breaks it

All the site-specific logic lives in `mtb_site.py`. Run `diagnose.bat` after
signing in; it dumps the page structure to `Diagnostics\` so the selectors can
be repaired to match.

## Sensitive files

Mortgage statements show your balance, payment and address, and tax forms
carry your SSN. They are saved to the folder you set as `output_dir` in
`config.json`. Keep it somewhere safe. The index CSV records **no** balances or
amounts, only what is needed to find and verify a file.

## Tests

```
.venv\Scripts\activate
pytest
```
