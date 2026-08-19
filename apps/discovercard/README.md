# Discover — credit-card statement downloader

Downloads your Discover **credit-card** statements as PDFs from
`card.discover.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

Verified end to end against a live account on 2026-08-19: `--discover` found
24 statements (2024-08-19 … 2026-07-19), `--pilot` downloaded valid PDFs each
containing its own closing date, a re-run after deleting one skipped it, and
`--verify` reported it missing without re-fetching it.

**Scope:** Discover credit-card **statements** only — Discover it, Discover it
Miles / Chrome / Cash Back / Student, Discover More. Discover Bank deposit
accounts, personal loans, student loans and home loans are separate portals and
are not covered. Tax documents are not collected: `document_types` lists
`Statement` alone, so a stray 1099 is classified and then skipped rather than
half-filed.

## Setup

```bash
./setup.command           # one-time: venv + Playwright
./login.command           # opens Edge/Chrome on port 9237 — sign in yourself
./diagnose.command        # a safe look: reads the page, downloads nothing
./run_pilot.command       # download the newest few as a test
./run_all.command         # download everything available
```

(Windows: the matching `setup.bat` / `login.bat` / … . `setup` does not create
`config.json` — copy it once with `cp config.example.json config.json`.)

## A real browser, always

`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), like the
Walmart, Verizon and Chase apps — never the bundled Playwright Chromium.

Discover's bot-detection posture has not been measured, and that is the reason.
A tripped check on a card account can mean a step-up verification loop or a
temporary lock, so the first contact is not from an obviously automated
browser. Please don't "just try" Chromium to find out.

## How it works — simpler than it looks

Discover turned out to be the easiest of the bank-style providers, and this app
is correspondingly small.

- **You sign in.** The tool attaches over CDP to the window you signed into and
  only reads. It never sees a password and never touches 2FA.
- **The page** is *Activity & Statements* at
  `/cardmembersvcs/statements/app/activity`, hash-routed (`#/recent`,
  `#/current`, `#/stmt_YYYYMMDD`). `page.goto` works and keeps the session, so
  this app pastes the URL — the opposite of the Ally and Chase apps, where only
  clicking the site's own nav worked.
- **Discovery is one read.** Every statement period's row, each with its own PDF
  link, is already in the DOM on plain page load. Verified: 24 links before any
  interaction, the same 24 after opening the period chooser. So nothing is
  clicked, no accordion is expanded and no year is swept — all of which the
  Chase app needs, because its rows only exist while one card's accordion is
  open on one year.
- **There is no `<select>` on the page.** The "Show me" period chooser is a
  link-based dropdown, which is why a select-based lookup finds nothing here.
- **Download is a direct fetch.** Discover serves each statement at
  `/cardmembersvcs/statements/app/stmtPDF?view=true&date=YYYYMMDD` (the closing
  date) as `application/pdf`. The bytes are fetched with the signed-in context's
  own cookies, using the href **read from the page** — not a URL built from a
  template, so a change to the query string cannot silently fetch the wrong
  period. Before fetching, the stored URL is re-checked and must still name the
  requested date. Bytes must start with `%PDF-` before anything is written.
- **Nothing is clicked**, which also keeps the app clear of the neighbouring
  **Download** control: that opens a *modal dialog* (a transactions export, not
  the statement PDF), and answering a dialog is what this project never does.
  "Print" opens a popup and is likewise unused.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, transfers,
  redeems Cashback Bonus or Miles, takes a cash advance or balance transfer,
  freezes/locks/replaces a card, requests a credit-line increase, disputes,
  applies, or changes a setting; a control must *also* look like a document
  action before it may be clicked.
- **Session timeouts.** Discover shows an inactivity "stay logged in?" modal;
  only its keep-alive control is ever clicked. On a real sign-out the app stops
  and hands control back to you.

## History available

24 statements — about two years. Older ones are not reachable from this page and
are not guessed at. Statements are named by **closing date**, and the human
period label ("May 20 - Jun 19, 2026") goes in the index CSV's Period column.

## What the read-only guard learned here

Two defects were found by running this app against the live site, and both are
now covered by tests:

- **A control on a SIGN-IN form was interrogated.** During the first probe every
  guessed URL missed, the app landed on Discover's public 404, and the
  account-picker lookup matched the *marketing site's* "what do you want to log
  into" dropdown — then tried to set it. Nothing was submitted and no credential
  was touched, but selecting inside a login form is not read-only. A control is
  now refused for any of three independent reasons — money widget, sign-in or
  registration form, or options that describe products rather than documents —
  and the check still fails closed when an identity cannot be read.
  `--diagnose` will not inspect *any* control unless the page is a signed-in
  application page.
- **A signed-out session was not recognised.** Discover signs out to
  `portal.discover.com/customersvcs/universalLogin/logoff_confirmed`, which
  matched none of the URL markers — "universalLogin" does not contain "/login".
  `--discover` ran for five minutes with an empty log instead of saying the
  session had ended. It now stops in about a second and tells you to sign in.

## Repairing it when Discover changes the site

Everything provider-specific is in
[`discovercard_site.py`](discovercard_site.py). Sign in, open Activity &
Statements, run `./diagnose.command` (it downloads nothing) and read
`Diagnostics/diagnose-documents.json`:

| Field | Tells you |
|---|---|
| `url`, `documents_page_found` | whether the statements route still lands |
| `statements_api` | how many statement PDF links the page publishes, their date range, the period labels, and the href shape |
| `statement_links` | the same count, as discovery sees it |
| `api_candidates` | any JSON endpoint the page calls that looks like a document list — reading one would be an upgrade, but none is needed today |
| `selects`, `selects_skipped` | dropdowns and the guard's verdict, with the reason for any refusal |
| `controls` | every button/link with its `safe` verdict |

If statements stop being found, look at `STMT_PDF_SEL` and `STMT_PDF_RE`; if the
period labels go missing, at `PERIOD_LABEL_RE`.

## Known limitation

**A login with more than one Discover card is unverified.** The account this was
built against has one card, so the page names none and no card chooser exists to
code against. If you have two, the card's last four arrives only *with the
download* (Discover puts it in the served filename), not from the page — so two
same-dated statements would share a filename and be numbered apart by
`unique_path` rather than overwriting each other. Visible, not silent. If you
hit this, please open an issue with `--diagnose` output.

## Notes

- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `add_account.py`). Deleting a downloaded PDF does not make the next run fetch
  it again; identity lives in `progress.json`, not in the file's presence. Use
  `--all --redownload --start-date X --end-date X` to rebuild one deliberately.
- **Why the app slug is `discovercard`, not `discover`:** `--discover` is the
  CLI's own verb for enumeration, and the control panel has a **Discover**
  button. An app named `discover` would read as "run discover on discover". The
  `redcard` app sets the precedent of naming by the card product.
