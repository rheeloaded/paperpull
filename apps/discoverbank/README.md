# Discover Bank statement downloader

Downloads your Discover Bank **checking and savings** account statements as PDFs from
`bank.discover.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

**Scope:** Discover Bank deposit accounts (Checking, Savings).
Credit card servicing has migrated to Capital One (`apps/capitalone`).
Loan accounts (personal, student, home) and tax documents are not covered.

## Setup

```bash
./setup.command                   # one-time: venv + Playwright
./login.command                   # opens Edge/Chrome on port 9306, sign in yourself
paperpull discoverbank diagnose   # a safe look: reads the page, downloads nothing
paperpull discoverbank pilot      # download the newest few as a test
paperpull discoverbank all        # download everything available
```

(Windows: the matching `setup.bat` / `login.bat` / … . `setup` does not create
`config.json`, copy it once with `cp config.example.json config.json`.)

## A real browser, always

`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), like the
Walmart, Verizon and Chase apps, never the bundled Playwright Chromium.

## How it works

- **You sign in.** The tool attaches over CDP to the window you signed into and
  only reads. It never sees a password and never touches 2FA.
- **The page** is *Statements* at `https://bank.discover.com/web/deposits/documents/statements`.
- **Discovery via API.** Statements are enumerated by capturing Discover Bank's internal servicing
  API (`/bank/deposits/servicing/documents/v1/accounts/{accountId}/statements`) across all deposit accounts.
- **Download is an authenticated in-page fetch.** Discover serves each statement at
  `/bank/deposits/servicing/documents/v1/accounts/{accountId}/statements/{id}` as `application/pdf`.
  Bytes must start with `%PDF-` before anything is written to disk.
- **Read-only.** Strict safety guards reject any transfers, wires, Zelle, payments, or profile updates.
- **Forbidden Hosts.** `card.discover.com` and `cards.discover.com` are strictly rejected.

## Repairing it when Discover changes the site

Everything provider-specific is in
[`discoverbank_site.py`](discoverbank_site.py). Sign in, open Statements,
run `paperpull discoverbank diagnose` (it downloads nothing) and read
`Diagnostics/diagnose-documents.json`.

## Notes

- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `paperpull discoverbank add-account NAME`). Identity lives in `progress.json`.
- **App slug:** `discoverbank` is distinct from the deprecated credit card app.
