# Ally Bank — statement downloader

Downloads your Ally **Bank** account statements and tax forms as PDFs from the
online banking portal (`secure.ally.com`). Read-only, delete-safe, part of
[PaperPull](../../README.md).

**Scope:** Ally *Bank* only — checking, savings, money market, CDs, IRAs.
Ally Invest and Ally Auto are separate portals and are not covered.

Verified end to end against a live account on 2026-08-18: discovery (198
statements over 7 years, 12 tax forms), download, per-document verification,
content-based naming, and a delete-safe re-run.

## Setup

```bash
./setup.command           # one-time: venv + Playwright
./login.command           # opens Chromium on port 9235 — sign in yourself
./diagnose.command        # a safe look: reads the page, downloads nothing
./run_pilot.command       # download the newest 5 statements as a test
./run_all.command         # download every available statement
```

(Windows: the matching `setup.bat` / `login.bat` / … .)

The first run asks *"Whose account is this?"* — the name is saved to
`config.json` and stamped on every document (the **Account Holder** index
column).

## How it works

- **You sign in.** `login.command` opens a normal Chromium on port **9235**;
  you complete sign-in and 2FA. The tool attaches over CDP and **reuses your
  signed-in tab** — it never sees a password.
- **Discovery reads Ally's own JSON API**, not the table:

      GET https://secure.ally.com/acs/v1/bank-statements
      {"statements":[{iraType, documentId, trustName, documentName, uploadDate}]}

  The app walks the year picker (2020–2026) so the full history is seen
  whichever way Ally filters, then de-duplicates by `documentId`. That id is a
  durable identity, so the delete-safe state survives a redesign of the page.
  Row scraping remains as a fallback if the API ever answers nothing.
- **Several statements share a date**, one per account grouping plus a copy of
  each joint statement addressed to each accountholder — and Ally's metadata
  does not say which is which. See *How statements are named* below.
- **Download** clicks the row's control and captures the PDF that opens in a
  new tab. (Fetching Ally's own `/acs/v1/bank-statements/<documentId>` endpoint
  directly does **not** work: it needs the `Authorization` header the SPA adds
  in JavaScript, and a cookie-only request comes back empty.)
- **Every download is verified.** Because several rows look identical, the row
  clicked is an inference — so the app watches which `documentId` Ally actually
  serves and **discards the file** if it isn't the one that was asked for. The
  bytes must also start with `%PDF-` before anything is written.
- **Session timeouts.** Ally shows an inactivity modal; the tool clicks only
  its keep-alive ("I'm still here" / "Stay signed in"). On a real sign-out it
  stops and hands control back to you.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that transfers, pays,
  deposits, opens or closes an account, renews or rolls over a CD, creates a
  bucket, or changes a setting; a control must *also* look like a document
  action (`SAFE_DOC_CONTROL_RE`) before it may be clicked.

## Repairing it when Ally changes the site

Everything provider-specific is in [`ally_site.py`](ally_site.py). Sign in,
run `./diagnose.command`, and read `Diagnostics/diagnose-documents.json`:

| Field | Tells you |
|---|---|
| `url`, `documents_page_found` | whether a `DOCUMENT_URL_CANDIDATES` entry still lands on the statements list |
| `row_counts`, `collected`, `samples` | whether the row scraper still recognises statement rows |
| `account_options`, `year_options` | whether the history is split behind dropdowns |
| `api_candidates` | JSON endpoints the SPA itself calls — reading one of these is usually more robust than scraping (see the `usaa` app) |
| `controls` | every button/link with its `safe` verdict from the read-only guard |

## How statements are named

Ally posts **several statements per date** — one per account grouping, plus a
separate copy of a joint statement addressed to each accountholder — and its
API describes them *identically*: same `documentName`, same row label, no
account information. Only `documentId` differs.

So the name comes from the **PDF itself**. Its first page carries an
account-summary table and the addressee block, both of which are parsed
structurally — by Ally's own template text (`Account Name  Account Number` …
`Total Account Balances:`) and the masked account-number column, never by a
list of expected account nicknames. A one-account customer yields one row; a
five-account customer yields five. Nothing about any particular customer is
baked in.

```
2026-08-16 Ally Account Statement - Everyday Checking + Rainy Day Savings (Pat Sample).pdf
```

- The parsing is plain regex: deterministic, offline, no model, no network.
- If the layout is not recognised, the file **keeps the name discovery gave
  it** and a note is written — nothing is guessed.
- Set `"addressee_in_filename": false` to leave the addressee out. Two copies
  of one statement then differ by a short `documentId` suffix instead.
- Account nicknames come from the statement, so **renaming an account in Ally
  changes later filenames**. The masked account number is the stable handle;
  identity is `documentId`, so re-labelling never re-downloads anything.

## Ally-specific quirks (found during the live probe)

- **The dashboard is hash-routed and ignores a pasted fragment.** Opening
  `secure.ally.com/dashboard/#/statements` leaves you on Snapshot. The app
  therefore reaches the documents area by clicking the SPA's own **Documents**
  nav control, and only falls back to URLs. The real page is
  `secure.ally.com/bank/statements-and-forms`.
- **Tax forms** come from the page's own **Tax Forms** tab, served by the same
  endpoint with `docType=TAXFORMS` (no year parameter — it returns every year
  at once). The app opens the tab and captures whichever request that makes
  rather than assuming the parameter, and reads the list tolerantly.
  - Forms file by **tax year, not posting date**: the 2025 1099-INT is issued
    on 2026-01-10 and belongs under 2025.
  - A **corrected** form is flagged in its filename so it cannot be confused
    with, or overwrite, the original.
  - **Ally's tax year picker starts at 2020** while its API returns a 2019
    form. That one cannot be reached from the page; the app reports it instead
    of downloading a different year.
- **The dashboard carries a transfer widget whose account dropdown looks
  exactly like a statements picker** (`<select id="fromAccount">`, options are
  your accounts). The first probe matched it and tried to set it — nothing was
  submitted, but that is not read-only behaviour. Dropdowns are now
  identity-checked against `MONEY_CONTROL_RE` before being read *or* written,
  and the check **fails closed** when a control's identity can't be read.
  `--diagnose` lists every dropdown with its verdict under `selects`.
- **An account nicknamed "…- 1099" trips the document allowlist.** Harmless
  (the allowlist only permits; the blocklist is checked first, and rows still
  need a date), but worth knowing when reading `controls` in the diagnostics.

## Notes

- **Tax documents:** Ally posts 1099-INT (and 1099-MISC for bonuses)
  seasonally — outside tax season there may be none to download.
- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `add_account.py`).
