# Discover — credit-card statement downloader

Downloads your Discover **credit-card** statements as PDFs from
`card.discover.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

> ⚠️ **NOT YET VERIFIED against the live site.** This app is scaffolding: the
> engine, safety guards, filing and delete-safe state are the same code every
> other PaperPull app runs, but every Discover URL, selector and download
> mechanism in [`discovercard_site.py`](discovercard_site.py) is an **informed
> guess** until someone runs `--diagnose` on a signed-in account and repairs
> it. Nothing guesses silently: an unrecognised page yields **no** documents
> rather than the wrong ones. See *First probe* below — that is the work left.

**Scope:** Discover credit-card **statements** only — Discover it, Discover it
Miles / Chrome / Cash Back / Student, Discover More. Discover Bank deposit
accounts, personal loans, student loans and home loans are separate portals and
are not covered. Tax documents are not collected: `document_types` lists
`Statement` alone, so a stray 1099 is classified and then skipped rather than
half-filed.

## A real browser, always

`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), like the
Walmart, Verizon and Chase apps — never the bundled Playwright Chromium.

Discover's bot-detection posture has **not** been measured, and that is exactly
the reason. A tripped check on a card account can mean a step-up verification
loop or a temporary lock, so the first contact is not from an obviously
automated browser. Please don't "just try" Chromium to find out.

## Setup

```bash
./setup.command           # one-time: venv + Playwright
./login.command           # opens Edge/Chrome on port 9237 — sign in yourself
./diagnose.command        # a safe look: reads the page, downloads nothing
./run_pilot.command       # download the newest few as a test
./run_all.command         # download everything available
```

(Windows: the matching `setup.bat` / `login.bat` / … .)

## First probe — what to establish

`--diagnose` downloads nothing. It reads the DOM of the page you are already
on, lists every control with the guard's verdict, and listens to the JSON the
page fetches on its own. Sign in, open your statements area, leave the window
open, then run it and read `Diagnostics/diagnose-documents.json`:

| Question | Where the answer shows up |
|---|---|
| Did a `DOCUMENT_URL_CANDIDATES` entry land on the list, or did nav-clicking? | `url`, `documents_page_found` |
| Does the generic row scraper recognise statement rows? | `row_counts`, `collected`, `samples` |
| Is the history behind a period chooser, and of which kind? | `selects`, `year_options` |
| Does this login show more than one card? | `cards` (0 = single-card, normal) |
| **Is there a JSON API behind the list?** | `api_candidates`, `statements_api` |
| Which controls does the read-only guard allow? | `controls` (each with `safe`) |
| Are any dropdowns refused as money controls? | `selects[].refused_as_money_control` |

Then repair `discovercard_site.py` from what it reports, and update the
"verified" line in its docstring **and the warning at the top of this file**.

## How it is meant to work

- **You sign in.** The tool attaches over CDP to the window you signed into and
  only reads. It never sees a password and never touches 2FA.
- **Discovery** sweeps each period the page offers and, within it, each
  per-card group if the page has any — then reads the rows on screen. A
  single-card login with one plain list is the expected shape and needs
  neither.
- **Download** re-finds the row by its accessible name (date, plus the card and
  action word when the row prints them), then tries a real download event and
  falls back to a PDF opened in a new tab. Bytes must start with `%PDF-` before
  a file is written.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, transfers,
  redeems Cashback Bonus or Miles, takes a cash advance or balance transfer,
  freezes/locks/replaces a card, requests a credit-line increase, disputes,
  applies, or changes a setting; a control must *also* look like a document
  action (`SAFE_DOC_CONTROL_RE`) before it may be clicked.
- **Dropdowns are controls too.** Every `<select>` is identity-checked against
  `MONEY_CONTROL_RE` before being read *or* written, and the check fails closed
  when an identity can't be read. This exists because on Ally the account
  picker discovery first matched belonged to a money-transfer widget; a card
  dashboard has the same hazard in its "pay from" picker.

## Two traps inherited from building the Ally and Chase apps

Both cost real debugging time there, and both are pre-empted here:

- **Attribute a document from its row, not from position or an API reply.** If
  a login ever shows two cards, "the card I just clicked" and "the card this
  document belongs to" can differ — asynchronous replies arrive out of order,
  and one card's statements were filed under another. `read_rows()` takes the
  card from the row whenever the row prints one. Harmless when there is only
  one card; do not remove it to find out.
- **A group that is already expanded may never re-fetch.** On Chase, a card
  whose accordion happened to be open returned nothing, and five of six cards
  were collected with a plausible-looking total. `expand_only_group()` always
  collapses first.

## Discover-specific wrinkle already handled

Discover names its cards **"Discover it Miles"** and **"Discover it Cash
Back"** — and the read-only blocklist forbids `miles` and `cashback`, because
"Redeem Miles" is a rewards action. Reusing the blocklist to vet a card header
would therefore refuse the card's own name and the app could never open that
card's documents. So a card header is vetted against `CARD_ACTION_RE` instead:
a header is a noun phrase, and what makes a look-alike dangerous is a verb
("Pay …1234", "Freeze it …1234"). Tests cover both directions.

## Notes

- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `add_account.py`). Deleting a downloaded PDF does not make the next run fetch
  it again; identity lives in `progress.json`, not in the file's presence.
- **Why the app slug is `discovercard`, not `discover`:** `--discover` is the
  CLI's own verb for enumeration, and the control panel has a **Discover**
  button. An app named `discover` would read as "run discover on discover".
  The `redcard` app sets the precedent of naming by the card product.
