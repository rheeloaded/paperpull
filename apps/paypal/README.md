# PayPal monthly statement downloader

Downloads your own **PayPal monthly statements** as PDFs, for your
records. Read-only, delete-safe, and part of [PaperPull](../../README.md).

Mapped and run against the maintainer's own personal account on
2026-09-25. Twenty-five statements, August 2024 to August 2026, every
period checked against its filename, and a second run downloaded nothing.

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

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself, answer your own code, and leave the window open. The app
never sees your password. If a run stops with "session has ended", sign in
again in the open window and resume.

## Safety

This account moves money. PayPal can send and request money, transfer a
balance, buy crypto, donate, and apply for credit from the same pages.
This app activates no control at all. It makes the two requests above and
nothing else, a download has to be exactly a monthly statement on
`paypal.com` to be fetched, and an expired session stops the run rather
than reporting an empty success. The click guard every other app uses is
kept and tested here too.

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
