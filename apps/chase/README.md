# Chase — credit-card statement downloader

Downloads your Chase **credit-card** statements as PDFs from
`secure.chase.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

**Scope:** Chase credit-card **statements** only. Tax documents and year-end
summaries have their own tabs in Chase and are deliberately not collected —
`document_types` lists `Statement` alone, so a stray one is skipped rather
than half-filed. Deposit accounts, mortgages, auto loans and J.P. Morgan
investment accounts are not covered either.

Verified end to end against a live account on 2026-08-18
and 2019–2026, downloaded and checked against the account number printed
inside each PDF; delete-safe re-run confirmed, from the launchers and from
the control panel.

## A real browser, always

Chase runs bot protection that fingerprints the Playwright Chromium build, so
`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), like the
Walmart and Verizon apps.

This is not only about whether a page loads. A tripped bot check on a bank can
mean a step-up verification loop or a temporary lock on a real account — so
this app never touches Chase from an obviously-automated browser, not even to
find out whether it could.

## Setup

```bash
./setup.command           # one-time: venv + Playwright
./login.command           # opens Edge/Chrome on port 9236 — sign in yourself
./diagnose.command        # a safe look: reads the page, downloads nothing
./run_pilot.command       # download the newest few as a test
./run_all.command         # download everything available
```

(Windows: the matching `setup.bat` / `login.bat` / … .)

## How it works

- **You sign in.** The tool attaches over CDP to the window you signed into and
  only reads. It never sees a password and never touches 2FA.
- **Discovery** drives the page the way you would — every card's accordion,
  every year the "View:" picker offers — and reads the rows Chase renders
  (see *How documents are found*). Identity is card + date + type, which is
  exactly what a row says about itself.
- **Download** re-finds the row by its full accessible name (date, type,
  card, action) and clicks its "Saves document" link, keeping the browser's
  download event; if Chase opens the PDF in a tab instead, its bytes are
  fetched from there. The bytes must start with `%PDF-` before a file is
  written.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, transfers,
  redeems rewards, takes a cash advance or My Chase Loan, requests a credit
  line increase, disputes, locks or replaces a card, or changes a setting; a
  control must *also* look like a document action before it may be clicked.
- **Dropdowns are controls too.** Every `<select>` is identity-checked against
  `MONEY_CONTROL_RE` before being read *or* written, and the check fails closed
  when an identity cannot be read. This exists because on Ally the account
  picker that discovery first matched turned out to belong to a money-transfer
  widget; a card dashboard has the same hazard in its "pay from" picker.

## How documents are found

Chase's document centre is **one accordion per card**. Opening one makes the
page fetch that card's documents; the year comes from the "View:" picker
(2019–2026 here), which is a styled `<input>`, not a `<select>` — a
select-based lookup finds nothing.

Three things here were learned the hard way, and each one silently lost or
corrupted data before it was fixed:

- **A card that is already expanded never re-fetches.** It must be collapsed
  before being opened, or its documents are missed entirely — five of six
  cards were collected this way, with a plausible-looking total.
- **Attribution comes from the row, not the API reply.** Every row names
  itself in full (`Aug 09, 2026 Statement SAPPHIRE RESERVE (...1234) Saves
  document`), so a document can only be filed under the card printed on it.
  Correlating asynchronous replies instead filed one card's statements under
  another: collapsing, expanding and changing the year all hit the same
  endpoint, so "the next reply" is not the reply to this click.
- **The picker's options are not named by year alone.** The last one reads
  "2019, you've reached the end of the list" and the current one "2020,
  current selection". Matching the whole name against the year silently
  reported the oldest year as "not offered", so a whole year was missed with
  no error. Only the start of the name is matched now.
- **Identical content is not identical bytes.** Chase regenerates a PDF per
  request, so the same statement fetched twice differs by a few bytes. A
  hash comparison will not catch a duplicate; the card-and-date check will.

The app never synthesises a request. Driving the year picker is what makes
Chase send `idalDateFilterType=CURRENT_YEAR_MINUS_n`; no filter value is
invented.

## Repairing it when Chase changes the site

Everything provider-specific is in [`chase_site.py`](chase_site.py). Sign in,
open the statements area, run `./diagnose.command` (it downloads nothing) and
read `Diagnostics/diagnose-documents.json`:

| Field | Tells you |
|---|---|
| `url`, `documents_page_found` | whether the app can still reach the document centre by clicking its nav |
| `statements_api` | the fields Chase's own `docref/list` replies carry, and how many rows the page shows per card — the two should agree for the year on screen |
| `api_candidates` | every JSON endpoint the page called that looks like a document list |
| `selects`, `year_options` | whether the year picker or a card picker changed shape |
| `controls` | every button/link with its `safe` verdict from the read-only guard |

If cards stop being found, look at `CARD_RE` (the "(...1234)" header
pattern); if years stop being found, at `YEAR_PICKER_SEL`; if rows stop being
read, at `ROW_NAME_RE`.

## Notes

- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `add_account.py`). Deleting a downloaded PDF does not make the next run
  fetch it again; identity lives in `progress.json`, not in the file's
  presence.
- The year picker only offers years Chase still holds; anything older is not
  reachable from the page and is not guessed at.
