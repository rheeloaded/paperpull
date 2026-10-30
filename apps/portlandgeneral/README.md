# Portland General Electric bills

Downloads the monthly bills of your Portland General Electric account from
`portlandgeneral.com` as PDFs, about three years of them. This reads from a
browser where you sign in yourself, with your password and any verification
code, on the port named in `config.json` (see `config.example.json`, port
9300). Passwords and verification codes are never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull portlandgeneral diagnose`, then `paperpull portlandgeneral pilot` (one bill).
5. Check the downloaded bill before using `paperpull portlandgeneral all`.

## How it works

Nothing is ever clicked. The app opens Billing & Payment History,
`/secure/payment/billing-payment-history`, by its address, in your
portlandgeneral.com tab or, with none open, in a tab of its own. A tab of
another site is never used.

- **The list.** The page asks `api.portlandgeneral.com` for its rows,
  `POST /pge-graphql`, operation `getAccountDetails`, fifteen rows a page
  with the total beside them. The app takes that request and its answer,
  and asks the further pages with the same query and the page's own
  `authorization` and `aws_graphql_server` headers, only the offset
  changed. Those header values stay in memory for the run and are never
  written, logged or printed.
- **Whole or stopped.** The walk must start at the first row, every page
  must be for the same account and give the same total, no page may give
  a row an earlier page gave, and the rows read must come to the total.
  Rows are bills or payments. A row of any other type stops the list and
  is named in the failure file, so a rebill or a new type is never passed
  over.
- **Identity.** The API issues every bill id afresh with each answer, so a
  bill is known by its account's last four digits and its date,
  `bill-1234-2026-09-30`. Two bills of one account and date are both
  listed, and only that date goes to Manual Review.
- **The PDF.** Each bill is the page's own Detailed Bill request,
  `POST /pge-bill-api/pdf/bills` with `isSummary` and `isNonDetailed`
  false, asked from inside the page, and kept only when it is a PDF.
- **Once a run.** The list is read once and kept in memory with its bill
  ids. It is read again only when a bill's PDF is refused or the bill is
  not in it, and a bill is fetched only when that list is for the account
  it was recorded under.
- **Signing out.** A 401, a 403 or a redirect on a list just read stops
  the run and keeps what it saved. Sign in again and run Resume. Any other
  answer that is not a PDF fails that one bill.

## Validation status

Built from a signed-in survey of one account on 2026-10-29. Discover
listed 36 bills, about three years, over every page of the history, and a
Pilot saved the newest, byte for byte the PDF the page's own Detailed Bill
link gives. Not yet seen:

- More than one account on one sign-in. Only the account the page shows
  is read, and the run says how many others the sign-in holds, from the
  page's own `getAccountInfo` answer. Choose another account on the site
  and run Discover again to list its bills.
- A history with no bills.
- Two bills on one date, a rebill, or a row type other than Bill and
  Payment.

Never touched are payments, autopay, Equal Pay, payment arrangements, bank
accounts, pricing plans, paperless, programs such as Green Future or Peak
Time Rebates, notifications, and starting, stopping or moving service.
Your account number, the customers' names and the street address are kept
out of every log and diagnostic file.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. The browser test starts PaperPull's bundled Chromium on
made-up host names, so nothing reaches Portland General Electric.
