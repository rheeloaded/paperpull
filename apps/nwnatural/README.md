# NW Natural bills

Bills are read from NW Natural's Paymentus payment portal, from inside the tab you signed in with; nothing is clicked. See the notes at the top of `nwnatural_site.py`.

Downloads the monthly gas bills of your NW Natural account from its
Paymentus payment portal, `ipn2.paymentus.com`, as PDFs, about eight years
of them. You sign in yourself on `www.nwnatural.com`, with your password
and any verification code, in a browser on the port named in
`config.json` (see `config.example.json`, port 9301), and go on to the
portal from there. Passwords and verification codes are never handled by
the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat`, sign in yourself, and go on to your
   bills on the payment portal. Leave that window open.
4. Run `paperpull nwnatural diagnose`, then `paperpull nwnatural pilot` (one bill).
5. Check the downloaded bill before using `paperpull nwnatural all`.

## How it works

Nothing is ever clicked, and the tab is never moved. The portal keeps its
session in a cookie and a `CSRF_TOKEN` that every one of its links carries,
so everything happens in the tab you signed in with, on the portal. No page
is opened by address and no tab of the app's own is used. A tab on
`www.nwnatural.com` instead, where a portal session that timed out lands,
stops the run once.

- **The list.** The app reads the portal page's own Bill History link,
  checks its host, path and token, moves its start date back to 2000, and
  fetches it from inside the page. Bill History draws one table, Account,
  Due Amount, Due Date and Action, with a View link on each bill's row.
  Padding rows of empty cells are passed over.
- **Whole or stopped.** One page was seen holding every bill, with no
  pager or count. A pager, a count that is not the rows read, or a table
  with no bills stops the list rather than being called whole, since an
  empty history has not been seen and a refused start date would look the
  same. So does a row with no account, no single View link, a View address
  that is not a bill's, or a due date that is not a calendar date.
- **One account.** A bill is known by its due date, `bill-2026-10-21`.
  When the Account column holds more than one account, the run says so and
  lists nothing, since two accounts' bills could not be told apart. Two
  bills of one due date, a corrected bill reissued under the first one's
  date say, are both listed, and Discover names the date. When a bill of
  that date is already saved, it is kept and the other is not fetched.
  Otherwise only that date goes to Manual Review.
- **The PDF.** Each bill is its View address, fetched from inside the page
  with the portal's cookie, no redirect followed, and kept only when it is
  a PDF. The View addresses carry the session's token, so they are kept in
  memory for the run and never written.
- **Once a run.** The list is read once a run. It is read again only when
  a bill is not in it or is not answered with a PDF. When that read stops
  the list, the run stops there once, saying why, and nothing goes to
  Manual Review. Run Discover, then Resume.
- **Signing out.** A redirect, a 401 or a 403 on Bill History stops the
  run and keeps what it saved. Sign in again and run Resume. A bill refused
  that way is read for again in a fresh list, and refused right after a
  list that answered, it fails that one bill, since the session plainly
  works. A 403 from the portal's bot protection (DataDome) stops the run
  too, or Login, saying so, so you can answer it in the browser. Any other
  answer that is not a PDF, an HTML page among them, fails that one bill.

## Validation status

Built from a signed-in survey of one account on 2026-10-29. Bill History
listed 84 bills, 2019 to 2026, on one page, and a run saved them. Not yet
seen:

- More than one account on one sign-in, which stops the list.
- A Bill History with no bills, which stops the list.
- A pager or a row count on Bill History, either of which stops the list.
- Two bills on one due date.
- A DataDome challenge in the middle of a run.

Never touched are payments, scheduled payments, autopay, Equal Pay, bank
accounts and cards, paperless, programs, notifications, and starting,
stopping or moving service. Your account number is kept out of every log
and diagnostic file, and so is the portal's token.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. The browser test starts PaperPull's bundled Chromium on made-up
host names, so nothing reaches NW Natural or Paymentus.
