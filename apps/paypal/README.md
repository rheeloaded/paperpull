# PayPal monthly statement downloader

Downloads your own **PayPal monthly statements** as PDFs, for your
records. Read-only, delete-safe, and part of [PaperPull](../../README.md).

Mapped and run against the maintainer's own personal account on
2026-09-25. Twenty-five statements, August 2024 to August 2026, every
period checked against its filename, and a second run downloaded nothing.
A business account's statements are read too, from their own page,
written from one tester's recording and not yet run on a real business
account (see [Business accounts](#business-accounts)).

## How it reads the site

Statements live under **Settings, Statements & Taxes, All transactions**,
a month-by-month list for the past three years. The page gets that list
from PayPal's own endpoint, and each Download asks another for the PDF.
This app makes the same two requests from inside the signed-in page, so
the session never leaves the browser, and it clicks nothing.

A statement is identified by its month. Filenames read like
`2026-08-31 PayPal Monthly Statement.pdf`, dated by the month's last day.

**What it does not cover.** Tax forms (1099-K, 1099-INT, 1099-MISC and
crypto) are on the Tax documents tab. The account this was built on had
none, so their download was never seen and is not built yet. Custom
date-range statements are a request PayPal prepares, and are never
submitted. PayPal keeps three years online, so run this at least once a
year to keep a full history.

## Business accounts

Asked for these statements, PayPal sends a business account to its
settings page instead. A business account keeps its statements under
**Activity, All Reports, Statements**, and this app goes to that page by
its address. As the page loads it asks PayPal for its own list of
statements, and the app reads that answer as it arrives. It never asks for
the list itself.

From that list it takes only statements PayPal says are PDFs and ready. A
CSV and a statement PayPal is still preparing are left alone, and the run
says how many there were. A statement whose status, kind of file or dates
the app cannot read is left alone too, counted as failed, and described in
the failure file the run writes. For each statement it presses that
statement's own **Download** button, in the row that shows its dates, and
checks that the PDF names those dates before filing it under the same
names a personal account's statements get, like
`2026-08-31 PayPal Monthly Statement.pdf`. A PDF whose dates cannot be
checked is put in Manual Review rather than filed, and one that names
other dates is not kept at all. The name PayPal gives a downloaded file
carries the account's id and is never kept.

It never creates, generates, requests or schedules a statement or a
report, and never presses for a CSV or any other kind of file.

**Written from one tester's recording, and not yet run on a real business
account.** The recording showed the page, its list and the Download
button, and kept none of their values, so how PayPal writes a statement's
status and dates is a guess, and the app refuses whatever it cannot read
rather than go past it.

### Help test it on a business account

1. Click **Login**, sign in, and leave the window open. Login says Success
   only once the business statements list has come.
2. Click **Pilot**. It saves the five newest statements, or stops and says
   why.
3. Click **more**, then **Diagnose**. It opens the business statements page
   and presses nothing. It writes `Diagnostics\diagnose-documents.json`,
   which keeps the list's shape, each statement's status, kind of file and
   dates as written, and what one statement's Download button reads. Any
   word in it that is not on PaperPull's fixed list, and every digit, is
   written as its shape.
4. A run that fails also writes a `failure-<command>-<time>.json` file in
   the Diagnostics folder. It holds counts and states and
   no text from your account.
5. Read each file through, then attach it to the PayPal issue on GitHub.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself, answer your own code, and leave the window open. The app
never sees your password. If a run stops with "session has ended", sign in
again in the open window and resume.

## Safety

This account moves money. PayPal can send and request money, transfer a
balance, buy crypto, donate, and apply for credit from the same pages.
For a personal account this app activates no control at all. It makes the
two requests above and nothing else, a download has to be exactly a
monthly statement on `paypal.com` to be fetched, and an expired session
stops the run rather than reporting an empty success. For a business
account it presses a statement's own Download button and the list's own
next-page control and nothing else, each only once the click guard every
other app uses has passed it, and the guard refuses anything that would
create, generate, request or schedule a report, and any kind of file but a
PDF.

## Commands

```
paperpull paypal setup
paperpull paypal login        sign in yourself, leave the window open
paperpull paypal discover     list what the site has, download nothing
paperpull paypal pilot        the newest five
paperpull paypal all          everything, delete-safe on a rerun
paperpull paypal verify       re-check every saved PDF
paperpull paypal diagnose     survey the page and the list, for when it changes
```

## Tests

```
python -m pytest tests -q
```
