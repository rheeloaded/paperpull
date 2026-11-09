# Cetera statements (AdviceWorks)

Downloads the account statements and quarterly performance reports of your
Cetera accounts from the AdviceWorks client portal, `client.adviceworks.net`,
as PDFs, for every account the portal lists and every quarter it keeps.
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
a tab of its own. A tab of another site is never used.

- **The lists.** The app takes the account list and the two headers
  (`authorization`, `x-session-id`) the page's own statements request
  carries, then asks the page's own two lists from inside the page, the
  statements for every account, quarter and year, page by page, and the
  quarterly performance reports. The header values stay in memory for the
  run and are never written.
- **Whole or stopped.** A list that holds fewer rows than it says, a row
  the app cannot read, a statement of an account the page did not ask
  about, a report whose advisory flag is not true or false, or a history
  with no statements at all stops the list rather than be called whole.
  The failure file says the list stopped partway.
- **Identity.** A statement is known by its account's last four digits
  and its date, and its file name carries the account as the portal masks
  it, for example `2026-09-30 Cetera Brokerage Statement XXXX-1234.pdf`. A
  report is known by its report id. Two statements of one account and date
  are both listed, Discover names the date, and neither is fetched, since
  nothing tells them apart. Every other document is read.
- **The PDF.** Each PDF is fetched the way the page's own download fetches
  it, no redirect followed, and kept only when it is a PDF. Any other
  answer fails that document alone, and the next run tries it again.
- **Once a run.** Both lists are read once and kept in memory. They are
  read again only when a document is not in them, or when a PDF is
  refused with the headers kept from that reading, since the page's token
  does not last.
- **Signing out.** A 401, a 403 or a redirect on a list just read stops the
  run and keeps what it saved. Sign in again and run Resume.

## Validation status

Built from a survey of a signed-in account on 2026-10-30, with four
brokerage accounts, which listed 56 statements (2025 to 2026) and 5
quarterly performance reports. These have not been seen yet.

- An account with no statements, or a portal with no reports. A history
  with no statements stops the list until one has been seen.
- Advisory (RIA) reports, which are asked with the flag the list gives.
- Whether the page's own first request names every account, closed ones
  included. An account it leaves out is not listed.
- Two accounts whose masked numbers end in the same four digits, or a
  corrected statement beside the first. Neither statement of that date is
  fetched.
- Confirmations, tax documents, shareholder communications and client
  letters, which this app does not read.

Never touched are trading, transfers, deposits, linked banks, eDelivery,
alerts, messages to your financial professional, and every setting. Your
account ids and the page's headers are kept out of every log and
diagnostic file.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. The browser test starts PaperPull's bundled Chromium on a
made-up host name, so nothing reaches Cetera.
