# NW Natural bills

Bills are read from NW Natural's Paymentus payment portal, from inside the tab you signed in with; nothing is clicked. See the notes at the top of `nwnatural_site.py`.

Downloads the monthly bills of your NW Natural account from
nwnatural.com, `www.nwnatural.com`, as PDFs, about two years of them.
This reads from a browser where you sign in yourself, with your password
and the text-message code, on the port named in `config.json` (see
`config.example.json`, port 9301). Passwords and verification codes are
never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull nwnatural diagnose`, then `paperpull nwnatural pilot` (one bill).
5. Check the downloaded bill before using `paperpull nwnatural all`.

## How it works

Nothing is ever clicked. The app opens Billing History by its address, in
your nwnatural.com tab or, with none open, in a tab of its own, and
reads the bill rows the page draws, each carrying its invoice id and its
date from the column headed Statement Date. A tab of another site is never
used. Each bill is then fetched by its own address,
`/portal/BillingHistory/DownloadBillPdf`, with the signed-in session, no
redirect followed, and kept only when it is a PDF. Before each bill the
list is opened again and the bill is fetched only when exactly one row
still carries its invoice id and date. A list the app cannot read stops
rather than being called whole. If the portal answers as signed out, the
run stops and keeps what it saved. Sign in again and run Resume.

## Validation status

Built from a survey of a signed-in account on 2026-10-12, which listed
eight bills, and a full run on that account saved all eight. Not yet
seen:

- More than one account on one sign-in. The account selector is read,
  never changed. Only the selected account is listed, and the run says so.
- A Billing History with no bills.
- Two bills on one statement date, which stop the list.
- A blank Statement Date, which stops the list rather than taking the Due
  Date beside it.
- Solar (NBT) bills, which are fetched the same way and filed as bills.

Never touched are payments, autopay, Text to Pay, bank accounts, payment
arrangements, Level Pay, pricing plans, paperless, notifications, and
starting, stopping or transferring service. Your account number, contract
account and service address are kept out of every log and diagnostic file.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. The tab tests start PaperPull's bundled Chromium on made-up
host names, so nothing reaches NW Natural.
