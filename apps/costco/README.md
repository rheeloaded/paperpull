# Costco Receipts Downloader (local, supervised)

**Untested, and built without a Costco account.** Everything this app
believes about a signed-in Costco page is a guess made from the public
site. The sign-in, the address of the orders page and the fact that
Costco runs a bot check were all read off the live site and are real.
Where a purchase sits on that page, what a receipt looks like and how to
open one are guesses, marked GUESS in `costco_site.py`.

**If you shop at Costco, you can fix that in one sitting and without
writing any code.** See [Help test it](#help-test-it-no-programming-needed).
The conversation is [issue #47](https://github.com/rheeloaded/paperpull/issues/47).

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
4. Click **more** under the buttons, then **Record**. Go back to the
   browser and click your way to one receipt the way you normally would,
   an in-warehouse one if you have it, then come back and click **Stop
   recording**. It writes `Diagnostics\recording.json`, the path you
   actually took. It records nothing you type, reads no cookies, and
   refuses to start before you are signed in.
5. Click **Diagnose** as well. That writes
   `Diagnostics\diagnose-costco.json`, what the app sees on the page,
   which says what this app got wrong.
6. Open each file in Notepad and read it through. The recording ends by
   printing anything worth a second look. Delete any line you do not like
   the look of.
7. Attach both to [issue #47](https://github.com/rheeloaded/paperpull/issues/47)
   with a sentence about whether warehouse receipts and online orders are
   on the same page or behind separate tabs, and how far back the list
   goes. Do not attach a screenshot of a receipt. Those carry your
   membership number and the card tail, and the recording deliberately
   does not.
8. When a new build is posted, click **Pilot** and say whether PDFs
   landed in `In-Warehouse\` or `Online\`.

One recording is usually enough. A survey on its own takes two or three
rounds, and once took nine.

## What was actually verified, and when

Read off the live public site on 2026-09-22, signed out.

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

## What is a guess

- Where purchases sit on the page, and what the link to one looks like.
- Whether a receipt is a page, a PDF or a panel that opens in place.
- Whether warehouse receipts and online orders share one list.
- How far back Costco keeps either of them.
- Costco's own words for the kinds of purchase. The table in
  `costco_site.py` is generous on purpose so a near miss still files
  correctly.

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
- **The purchase list is read off the page**, not fetched from an API,
  because the bot sensor refuses a call this app makes itself. Every
  link on the list that looks like one purchase becomes a record, and
  the record carries the href the page itself drew rather than a URL
  this app assembled.
- **Each purchase is opened and rendered to PDF** with CDP printToPDF.
  No button is clicked, the page's own Print button included, and the
  native print dialog is never involved.
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
