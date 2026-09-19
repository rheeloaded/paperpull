# Fairfax Water bill downloader

Downloads your own **water bills** from Fairfax Water's customer portal, FW
Customer, as PDFs, for your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

Mapped and run against a real account on 2026-09-19. Four bills saved and
verified, one older bill the portal's document host no longer held, and a
second run downloaded nothing.

## What the portal offers

FW Customer (`www.fwcustomer.org`) lists every bill on the account in its
Billing History, quarterly, back years. **Only the bills of the last year
have a PDF**, which is what Fairfax Water's own FAQ says ("view bills from
the last year"). Older rows are dates and amounts only, and are not
documents here. So the archive grows one bill a quarter, and a run every few
months is what keeps it whole. Start now and you keep everything from here
on.

## How it reads the site

The portal is a Mendix app whose client talks to one endpoint in a protocol
of GUIDs and change sets, so this app drives the pages the way a person
does. It opens the Billing & Payment page from the left nav (a page, not a
payment), reads the Billing History grid, and for each bill with a View
button it clicks View. That opens the bill PDF in a new tab on
`docsight.net`, Fairfax Water's document host, under a one-time signed
link. The app never navigates there itself. It catches the tab the portal
opens, reads the PDF out of that tab's own response, writes it, and closes
the tab. Each bill is identified by its invoice date and the last four
digits of the account number. Filenames read
`YYYY-MM-DD Fairfax Water Bill - 1234.pdf`.

## Safety

The portal can pay a bill, set up autopay, store a card or bank account,
start or stop service, and change paperless and contact settings. This app
never activates a control that does any of those. It clicks exactly two
kinds of control, the "View" on a bill row and "Show More" on the grid, both
by their exact names and both checked against a blocklist that refuses pay,
payment, autopay, card, bank account, start, stop, enroll, paperless and the
rest. The left nav's page links have their own exact allowlist, because
"Billing & Payment" is a page that pays for nothing while the word would
trip the control guard. Every URL it reads has to be on `fwcustomer.org`,
`fairfaxwater.org` or the document host. An expired session stops the run
rather than reporting an empty success.

## Sign-in

`paperpull fairfaxwater login` opens a plain Chromium at the portal. You
sign in yourself and leave the window open. The app never sees your
password.

## Commands

```
paperpull fairfaxwater setup
paperpull fairfaxwater login        sign in yourself, leave the window open
paperpull fairfaxwater discover     list the bills with a PDF, download nothing
paperpull fairfaxwater pilot        the newest five
paperpull fairfaxwater all          everything, delete-safe on a rerun
paperpull fairfaxwater verify       re-check every saved PDF
```

## Tests

```
python -m pytest tests -q
```
