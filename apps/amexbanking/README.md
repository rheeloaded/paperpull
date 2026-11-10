# American Express Banking statement downloader

Downloads your American Express deposit account statements and tax documents as PDFs from
`americanexpress.com` / `business.americanexpress.com`. Read-only, delete-safe, part of
[PaperPull](../../README.md).

For American Express credit cards, use the [`amex`](../amex) app instead.

**Scope:** American Express National Bank (AENB) CASA accounts:
- **Business Checking** (verified in production)
- **Personal Checking / Rewards Checking** (*needs testing with active accounts*)
- **Savings / High-Yield Savings Accounts (HYSA)** (*needs testing with active accounts*)

> [!NOTE]
> Designed to support American Express National Bank CASA accounts using the unified Banking API (`ReadBankingAccountDocumentList.v1` and `ReadBankingDocument.v1`). Business Checking is verified; testing with active personal checking and savings accounts is needed to confirm document categories and metadata across all account types.

## Setup

```bash
./setup.command                  # one-time: venv + Playwright
./login.command                  # opens Edge/Chrome on port 9307, sign in yourself
paperpull amexbanking diagnose   # a safe look: reads the page, downloads nothing
paperpull amexbanking pilot      # download the newest few as a test
paperpull amexbanking all        # download everything available
```

(Windows: the matching `setup.bat` / `login.bat`. Copy `config.example.json` to `config.json`.)

## A real browser, always

`login` asks for an installed **Edge or Chrome** (`prefer_real=True`), never the bundled Playwright Chromium, to maintain a trusted session without tripping bot checks.

## How it works

- **You sign in.** The tool attaches over CDP to the browser session where you signed in. It never sees credentials or handles 2FA.
- **Discovery via API.** Statements and tax forms are enumerated by intercepting Amex Banking's internal servicing API (`ReadBankingAccountDocumentList.v1`).
- **Binary Download via API.** Document payloads are fetched directly through `ReadBankingDocument.v1` and written atomically to disk as validated PDFs.
