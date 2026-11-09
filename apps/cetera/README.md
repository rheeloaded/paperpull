# Cetera statements (AdviceWorks)

Downloads the account statements and quarterly performance reports of your
Cetera accounts from the AdviceWorks client portal, `client.adviceworks.net`,
as PDFs: every account the portal lists, every quarter it keeps.
This reads from a browser where you sign in yourself, with your password
and any verification code, on the port named in `config.json` (see
`config.example.json`, port 9304). Passwords and verification codes are
never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself at adviceworks.net.
   Leave the window open.
4. Run `paperpull cetera diagnose`, then `paperpull cetera pilot` (one statement).
5. Check the downloaded statement before using `paperpull cetera all`.

## How it works

Nothing is ever clicked. The app opens My Documents' Statements & Notices
by its address, in your client.adviceworks.net tab or, with none open, in
a tab of its own, and takes the account list and the two headers
(`authorization`, `x-session-id`) the page's own statements request
carries. It then asks the page's own two lists from inside the page:
statements for every account, quarter and year, page by page, and the
quarterly performance reports. Each PDF is fetched the way the page's own
download fetches it, no redirect followed, and kept only when it is a PDF.
Before each document both lists are asked again and the document is
fetched only when exactly one row still carries its id and date. The
header values stay in memory for the run and are never written.

A statement is known by its account's last four digits and its date, and
its file name carries the account as the portal masks it, for example
`2026-09-30 Cetera Brokerage Statement XXXX-1234.pdf`. A report is known by
its report id. A list that holds fewer rows than it says, or that the app
cannot read, stops rather than being called whole. If the portal answers
as signed out, the run stops and keeps what it saved. Sign in again and
run Resume.

## Validation status

Built from a survey of a signed-in account on 2026-10-30, with four
brokerage accounts, which listed 56 statements (2025 to 2026) and 5
quarterly performance reports. Not yet seen:

- An account with no statements, or a portal with no reports.
- Advisory (RIA) reports, which are asked with the flag the list gives.
- Confirmations, tax documents, shareholder communications and client
  letters, which this app does not read.

Never touched are trading, transfers, deposits, linked banks, eDelivery,
alerts, messages to your financial professional, and every setting. Your
account numbers are kept out of every log and diagnostic file.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only.
