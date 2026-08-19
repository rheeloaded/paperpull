# U.S. Bank — credit-card statement downloader

Downloads your U.S. Bank **credit-card** statements as PDFs from
`onlinebanking.usbank.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

**Scope:** U.S. Bank credit-card **statements** only. `document_types` lists
`Statement` alone, so a stray tax form is skipped rather than half-filed.
"Letters & notices" has its own nav entry and is not collected. Checking,
savings, money market, CDs, mortgages, auto loans and U.S. Bancorp
Investments accounts are not covered.

Verified against a live account on 2026-08-19: discovery across the full
2019–2026 range the year filter offers, both available statements downloaded,
and each filename checked against the **closing date and account number
printed inside the PDF**; delete-safe re-run confirmed, including after
deleting a downloaded PDF.

## A real browser, always

`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), like
the Chase, Walmart and Verizon apps. Chase was observed to fingerprint and
block the bundled Playwright Chromium; whether U.S. Bank does is untested,
and this app does not intend to find out — a tripped bot check on a bank can
mean a step-up verification loop or a temporary lock on a real account.

## Setup

```bash
./setup.command           # one-time: venv + Playwright
./login.command           # opens Edge/Chrome on port 9238 — sign in yourself
./diagnose.command        # a safe look: reads the page, downloads nothing
./run_pilot.command       # download the newest few as a test
./run_all.command         # download everything available
```

(Windows: the matching `setup.bat` / `login.bat` / … .)

## How it works

- **You sign in.** The tool attaches over CDP to the window you signed into and
  only reads. It never sees a password and never touches 2FA.
- **Discovery** clicks the portal's own **Statements** nav, then walks every
  year the "Document year" filter offers, reading each row's Download control.
- **Download** re-finds the row by that control's own accessible name and
  clicks it, keeping the browser's download event. The bytes must start with
  `%PDF-` before a file is written.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, transfers,
  redeems rewards or FlexPoints, takes a cash advance, orders a convenience
  check, starts an ExtendPay plan or a Simple Loan, requests a credit-line
  increase, disputes, locks or replaces a card, or changes a setting; a
  control must *also* look like a document action before it may be clicked.
- **Dropdowns are controls too.** The account and year pickers are
  identity-checked against `MONEY_CONTROL_RE` before being read *or* written,
  and the check fails closed when an identity cannot be read. This exists
  because on Ally the account picker discovery first matched turned out to
  belong to a money-transfer widget.

## How the page is actually built

Signed in, the whole portal is one hash-routed SPA under
`/digital/servicing/shellapp/`. The documents area is
`#/highvolume/edocs/statements`, titled **E-statements**, and it has **no
`<table>`, no `[role=row]` and no `<select>` anywhere** — it is a
`data-testid` component tree:

```
[data-testid="document-view"]
  [data-testid="account-dropdown"]    "Account / Credit Card ...4321"
  [data-testid="year-filter"]         button#exp_button_year-filter-select
  [data-testid="list-of-statements"]
    div.document-list
      h3  "Credit Card ...4321 statements"     <- the account lives HERE
      ul > li.download-items                   <- the row
          a       aria "View <date> statement in a new window."
          button  aria "Download <date> statement."
    div.document-list
      h3  "E-statement disclosures"            <- NOT statements
      ul > li.download-items                   "Electronic document agreement"
```

Four things here cost real data before they were fixed, and every one of them
fails **silently** — "no rows found" looks exactly like "no statements this
year":

- **Each row has two controls naming the same statement.** The View link and
  the Download button both carry the date, so reading both counts every
  statement twice. The Download button alone is authoritative.
- **The account is on the section heading, not the row.** A row's label is
  only `Download March 15, 2026 statement.` Requiring the account name in it
  matched nothing at all; the heading `Credit Card ...4321 statements` is
  where attribution comes from.
- **There is a second section with identical row markup.** "E-statement
  disclosures" holds the Electronic document agreement. Its controls carry no
  aria-label and no date, but only sections whose heading ends in
  "statements" are read, so it cannot be filed as one.
- **An empty year is a working page.** 2019–2025 render "You have no
  statements for the selected year." `on_documents_page()` keys on the page's
  container rather than on "did we read any rows", because the row-count
  version made `ensure_statements` navigate away mid-run; and
  `select_period()` treats "no picker at all" as success, because returning
  False there fails every download before it is attempted.

One more, which is a Playwright quirk rather than a U.S. Bank one:
`row_label_re()` contains `/` for the `MM/DD/YYYY` form, and passing it to
`get_by_role(name=…)` ends the regex literal early inside Playwright's own
selector syntax (`InvalidSelectorError`). Row labels are read and matched in
**Python** instead — which also means discovery and download walk the same
rows and cannot disagree about what exists.

## Repairing it when U.S. Bank changes the site

Everything provider-specific is in [`usbank_site.py`](usbank_site.py), most of
it in the `SEL` map. Sign in, run `./diagnose.command` (it downloads nothing)
and read `Diagnostics/diagnose-documents.json`:

| Field | Tells you |
|---|---|
| `documents_page_found`, `url` | whether the **Statements** nav still reaches the documents area |
| `account`, `period_reset_to` | whether the account label and year filter still read |
| `statements_read` | what the real reader sees — **this is the number that matters** |
| `collected_generic` | the fallback scraper; expected to be low, it is not how this page is read |
| `cards`, `period_options` | the account selector's options and the years offered |
| `selects` | every dropdown with the guard's verdict, so a genuine picker wrongly refused is visible |
| `controls` | every button/link with its `safe` verdict from the read-only guard |
| `api_candidates` | JSON endpoints the page called (U.S. Bank drives this area through a GraphQL endpoint; the app reads the DOM, not that API) |

If rows stop being read, look at `SEL["list"]`/`SEL["row"]` and
`ROW_DOWNLOAD_ARIA_RE`; if the account goes missing, `SEL["account"]` and
`account_in_heading()`; if years stop being offered, `SEL["year_button"]`.

## Notes

- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `add_account.py`). Deleting a downloaded PDF does not make the next run
  fetch it again; identity lives in `progress.json`, not in the file's
  presence. Confirmed live.
- **Only the single-account case has been seen.** `account_options()` opens a
  real dropdown if a multi-account login has one, and otherwise reports the
  one account; it never invents a list it cannot see.
- The year filter is **browser state** and survives between runs, so anything
  that *reports* what the page holds resets to the newest year first
  (`reset_to_newest_period`). Without it, `--diagnose` describes whichever
  year the last run left on screen.
