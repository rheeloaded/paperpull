# Ziply Fiber bills

Downloads the monthly internet bills of your Ziply Fiber account from
`ziplyfiber.com` as PDFs, every bill My Account's Billing page lists. This
reads from a browser where you sign in yourself, with your password and any
verification code, on the port named in `config.json` (see
`config.example.json`, port 9303). Passwords and verification codes are
never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull ziply diagnose`, then `paperpull ziply pilot` (one bill).
5. Check the downloaded bill before using `paperpull ziply all`.

## How it works

Nothing is ever clicked. The app opens My Account's Billing page,
`/myaccount/billing`, by its address, in your ziplyfiber.com tab or, with
none open, in a tab of its own. A tab of another site is never used.

- **The account.** On load the page asks the account API, `POST /myapi`,
  for `billingDetails`, naming the account it shows. The app takes the
  account number and the page's own `authorization` and `requestid`
  headers from that request. Those header values stay in memory for the
  run and are never written, logged or printed.
- **The list.** The app asks the page's own Past bills query,
  `billStatements`, word for word, from inside the page with those
  headers, for 100 bills rather than the page's 5. Each bill comes with
  its date and invoice id, and its address must be that invoice's own PDF.
- **Whole or stopped.** The list stops rather than be called whole when
  the API answers with errors or a status other than 200, when it lists
  no bills, when it lists all 100 asked for, since there may be more, and
  on a bill whose id, date or address cannot be read or an id given twice.
  The failure file says the list stopped partway.
- **Identity.** A bill is known by its account's last four digits and its
  invoice id, `bill-1234-70000001`, and its file name carries the account
  as `XXXX-1234`.
- **The PDF.** Each bill is a plain GET of
  `/api/myacc/billinginvoice?invoiceId=<id>` from inside the page with the
  session's cookies, no redirect followed, and kept only when it is a PDF.
  A JSON answer fails that bill alone, and the next run tries it again.
- **Once a run.** The list is read once and kept in memory. It is read
  again only when a bill is not in it.
- **One account at a time.** A page that asks about more than one account
  stops the list, and nothing is listed. A bill is fetched only when the
  page asks about the account it was listed under. When it asks about
  another, the run stops and names the last four digits of the account it
  wants. Choose that account on the site and run Resume.
- **Signing out.** A 401, a 403, a redirect, a sign-in page where a bill
  was asked for, or an API answer that says the session has ended stops
  the run and keeps what it saved. Sign in again and run Resume.

## Validation status

Built from a signed-in survey of one account on 2026-10-30. Discover listed
17 bills, 2025-06 to 2026-10, a Pilot saved the newest, a second Pilot
skipped it, and a full run saved the rest. One bill came back cut short in
that run, failed its PDF check, and saved on Resume. These have not been
seen yet.

- More than one account on one sign-in. How My Account switches between
  accounts is not known. A page that asks about two stops the list.
- A history with no bills, which stops the list until one has been seen.
- A history of 100 bills or more, which stops the list. A server that
  gives fewer than were asked for and no more would be read as whole.
- An answer from the account API with a message or a status other than
  200, which stops the list.

Never touched are payments, autopay, paperless, plan changes, equipment
returns, service visits and trouble tickets, notifications, and the account
profile. Your account number and the page's authorization are kept out of
every log and diagnostic file.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. The browser test starts PaperPull's bundled Chromium on a
made-up host name, so nothing reaches Ziply Fiber.
