# Costco Receipts Downloader (local, supervised)

**Works against a real account.** Built from a member's recording and
then run against their membership, where it found 34 purchases going
back to July 2024 across ten quarters on both tabs, and saved warehouse
receipts and online invoices as readable PDFs. The recording and the
rounds are on
[issue #47](https://github.com/rheeloaded/paperpull/issues/47).

It has been run by one person on one membership, so it is new rather
than proven. If you have a Costco card, a **Pilot** run and a word about
what it got wrong is worth a lot.

Downloads your Costco purchase history and saves each purchase's receipt
as a PDF, plus two CSV files, one row per line item and one row per
receipt.

- **Read-only.** Nothing is bought, returned, refunded, renewed or
  cancelled. The guard in `costco_site.py` refuses every control whose
  name says otherwise, and there is a test for each of them.
- **You sign in yourself.** No password, card or membership number is
  ever typed by this app or stored by it.
- **Nothing leaves your machine** except the pages Costco itself serves
  you.

## Help test it, no programming needed

The short version. The long version, written for somebody who has never
contributed to anything, is
[Testing a provider](../../docs/testing-a-provider.md).

1. Install PaperPull from the
   [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Costco**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate
   profile. Sign in to costco.com yourself, answer any code it sends, and
   leave the window open.
4. Click **Pilot**. It takes the newest few from each tab. Say whether
   PDFs landed in `In-Warehouse\` and `Online\`, and whether they are
   readable, which is the one thing nobody has checked yet.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps.
5. If a run stops early it writes a `failure-*.json` in `Diagnostics`
   by itself and prints where. Attach that. It names the step that broke
   and holds no text from your account.
6. If a run finishes but the PDFs are wrong, click **more**, then
   **Diagnose**, and attach that file. It says what the app sees on both
   tabs. A fresh **Record** helps too, if the path it takes has changed.
7. Read any file through before you attach it. A recording ends by
   printing anything worth a second look. Delete any line you do not
   like.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
8. Attach both to [issue #47](https://github.com/rheeloaded/paperpull/issues/47)
   with a sentence about whether warehouse receipts and online orders are
   on the same page or behind separate tabs, and how far back the list
   goes. Do not attach a screenshot of a receipt. Those carry your
   membership number and the card tail, and the recording deliberately
   does not.
One recording was enough to write this app. Making it work took several
runs against the account afterwards, which is the normal shape of it and
not a sign anything went wrong.

## How Costco is put together

Everything here was seen on a signed-in account on 2026-09-22.

**Orders & Purchases is one page with two tabs**, and they are two
different things behind one heading. **Warehouse** is what was bought at
a warehouse, including the gas station and the car wash, and it is the
half nobody else can get at, because Costco keeps it for a matter of
months and the paper fades. **Online** is costco.com orders. Switching
tabs does not navigate, it asks the API and redraws.

**How far back you can see is a picker labelled "Showing"**, holding
quarters rather than years, "2026 April - June" and so on, opening on
"Last 3 Months". So a run that never touches it sees a quarter at most.
This app walks the quarters, and on the account it was built against
that was ten of them, back to January 2024. A quarter holds ten rows at
a time.

**A warehouse receipt is a dialog.** "View Receipt" opens it on the same
page, with no navigation and no address of its own, and the dialog
carries a "Print Receipt" link and a "Close" button. Because it has no
address, a receipt here is identified by what its row shows, the date,
the total and the warehouse. Two receipts from the same warehouse on the
same day for the same amount would collide, which is the cost of a list
that carries no identifier.

**An online order is two links.** "View Order Details" goes to
`/myaccount/#/app/<client id>/orderdetails/<order number>`, and that page
carries a "Print Invoice" link to `/OrderDetailPrintView`, a plain
printable page. This app reads both addresses and goes to them. It
presses neither.

**Neither print control is ever pressed.** Both call `window.print()`,
which opens a dialog no program can answer or dismiss. The receipt is
rendered with CDP printToPDF instead.

**There is one API, and this app does not use it.** Everything goes
through `https://ecom-api.costco.com/ebusiness/order/v1/orders/graphql`,
POSTed with a `query` and `variables`. A recording keeps the shape of an
answer and never a value, so the query text is not known and this app
does not guess at it. It drives the page the way the member did. If a
later round brings the queries back, discovery is the only part that
changes.

## What was verified off the public site, signed out

- **Orders and purchases** is
  `https://www.costco.com/myaccount/#/app/4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf/ordersandpurchases`.
  That UUID is the same for every member. It is the OAuth client id, not
  an account id, which the sign-in redirect proves by handing it back as
  `client_id`.
- **Signing in** is Azure AD B2C on `signin.costco.com`, returning to
  `https://www.costco.com/OAuthLogonCmd`. Password, emailed passcode and
  passkey are all offered, so you sign in yourself and this app only ever
  finds the session already there.
- **Costco runs Akamai Bot Manager.** Verified the hard way, because its
  script wraps `window.fetch` and refused a call made from an automated
  page. So this app drives a real Edge or Chrome and reads the page
  rather than calling an API behind the page's back.
- **There is a virtual waiting room** wired in. At a busy hour a run can
  land in a queue, which looks like a page that never arrives, so it is
  named in the output rather than left to guess at.
- **The old storefront is still mounted**, `OrderStatusCmd` and friends,
  kept as a second route to try when the new one gives nothing.

## What is still open

- **One membership, one person.** Everything here held on that account.
  A second one is the next thing this needs.
- **Whether a quarter ever holds more than ten rows**, and if it does,
  how you ask for the eleventh. Nothing on that account went over ten,
  so there was nothing to find out from.
- **The gas station and the car wash.** The API answers with counts for
  both, so Costco tracks them apart, and no row for either turned up to
  look at.
- **What a returned or cancelled purchase looks like**, on either tab.
- **The GraphQL queries.** Everything the page does goes through one
  endpoint, and a recording keeps the shape of an answer and never a
  value, so the query text is not known. Reading the page works and is
  slower than asking the API would be.
- **Classification is best effort.** Costco's till prints short names
  and 113 of them are in `category_rules.json` now. Anything it does not
  recognise is filed as "Mixed Purchases", which is a true description
  of most Costco trips and not an error.

## In-warehouse and online

Purchases file into two folders.

- `In-Warehouse\` for anything bought at a warehouse, including the gas
  station, the pharmacy and optical.
- `Online\` for costco.com orders, delivery and anything else.

The folder is named the way Costco names it. The route key inside the
code is the shared `In-Store` constant, which is why those two differ.

## How it connects (important)

Costco sits behind a bot check, so `login.bat` launches the Edge or
Chrome already on your machine with a separate profile on port **9268**,
and this app attaches to that window. It never launches its own
browser and never asks for your password.

## Setup, for a checkout

```bat
setup.bat                       REM one-time: venv + Playwright
login.bat                       REM opens Edge or Chrome on port 9268, sign in yourself
paperpull costco record         REM the recording, the useful one
paperpull costco diagnose       REM the survey, for the maintainer
paperpull costco pilot          REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Akamai is happiest in a real browser, so
  `login.bat` launches the one already on the machine with a profile of
  its own.
- **You sign in** in that window. The app reuses the signed-in tab.
- **Both tabs are read, quarter by quarter**, off the page rather than
  from the API, for the reason above. A row's own words become the
  record, and an online row carries the address the page itself drew.
- **A warehouse receipt** is opened by pressing that row's View
  Receipt, which is the only way in, and the dialog is rendered with CDP
  printToPDF and then dismissed with Escape.
- **An online order** is opened by address, twice, and nothing on either
  page is pressed at all.
- **Nothing is downloaded twice.** A purchase already in `progress.json`
  is skipped forever, even if you delete the PDF afterwards.

## When Costco changes its website

Repair `costco_site.py` and nothing else. That is where every selector,
URL and page behavior lives. Run `record` first, then
`python tools/read_recording.py <the file>`, which prints what was
clicked and the locator lines to start from.

## Safety

- Read-only. No control whose name mentions cart, checkout, return,
  refund, renewal, cancellation, payment or printing is ever touched.
- Only `https` URLs on `costco.com` and its subdomains are ever opened.
  An href read off the page that points anywhere else is dropped.
- Your membership number, card and password are never read, stored or
  typed.
- Diagnostics mask every number of two digits or more, every email
  address and the account holder's name.

## Tests

```bat
.venv\Scripts\python.exe -m pytest tests -q
```
