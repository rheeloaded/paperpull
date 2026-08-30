# M&T Bank — mortgage document downloader (READ-ONLY)

Downloads your M&T mortgage **statements and documents** as PDFs from M&T's
online banking (`onlinebanking.mtb.com`). Read-only, delete-safe, part of
[PaperPull](../../README.md).

> **Status: verified end to end against a live account (2026-08-23).**
> Statements and year-end statements download directly. 1098 tax forms are
> included when the Tax Documents page is open (see below).

## Read-only by design (a mortgage can move real money)

This tool only reads the document area and downloads PDFs M&T has already
generated. It **never** pays the mortgage, sets up or edits autopay, moves
money, transfers, sends a wire or Zelle, changes escrow, requests a payoff,
refinances, or changes any setting.

Concretely, and stated as what the code actually does:

- **Exactly one thing is ever clicked**: a collapsed year section on the
  statements page, so the older years can be read. Its label is checked against
  the blocklist (`FORBIDDEN_CONTROL_RE`) first, and the click is skipped if
  anything about it reads like a payment or settings control.
- **Only pages served by M&T are touched.** This attaches to your ordinary
  browser, so every frame is host-checked before it is read or clicked. Other
  tabs you have open are ignored entirely.
- **Downloads are checked twice**: the host must be M&T's *and* the URL path
  must be one of the two real document endpoints. A link that merely mentions
  those endpoint names in a query string is refused, redirects are capped, and
  the final URL is re-checked before anything is written to disk.
- **No form is ever submitted and no dialog is ever confirmed.**
- If M&T hands back a sign-in page instead of a document, the run **stops and
  says so** rather than filing everything as "needs manual review" and exiting
  as though it worked.

All of it is covered by tests, including regression tests for each of the
weaknesses a security review of this app actually found.

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

## Listing your statements first

M&T only shows your statements after you pick the mortgage account and click
**View**, which is a form submit this app deliberately does not perform (see
the read-only note above). So you do that once, and the app reads the result:

1. Open **Statements & Notices**, select the mortgage account, click **View**.
2. Leave that tab open. The app then expands every year section itself (each
   is a read-only request that lists that year) so the whole history is read,
   not just the current year.
3. For 1098 tax forms, also open **Statements > View Tax Documents** in another
   tab and leave it open. The app reads the 1098s from there.

The app scans whatever tabs you have open, so the order does not matter and it
never navigates or resets those pages.

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
