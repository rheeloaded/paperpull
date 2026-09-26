# E-ZPass Virginia statement downloader

Downloads your own **E-ZPass Virginia statements**, monthly and quarterly,
as PDFs, for your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

Mapped and run against the maintainer's own account on 2026-09-25. Sixteen
statements, twelve monthly and four quarterly, every period checked
against its filename, and a second run downloaded nothing.

## How it reads the site

After sign-in the browser is on the customer portal at
`myaccount.ezpassva.com`. Under **Statements & Transactions**, the
**View Online Statements** link loads a small page fragment with two
tables, Monthly and Quarterly, each row a period and a Download link. This
app asks for that same fragment from inside the signed-in page, so the
session never leaves the browser, and it clicks nothing. Each Download
link answers the statement PDF itself.

A statement is identified by its kind and its period, the three numbers in
its link. Filenames read like `2026-08-31 E-ZPass Virginia Monthly
Statement.pdf`, dated by the last day of the month or quarter.

**What it does not cover.** The portal keeps about the last twelve monthly
and four quarterly statements online, so run this at least once a year to
keep a full history. **View Transactions** is a searchable table of the
last year, not a document, and is left alone.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself and leave the window open. The app never sees your
password. If a run stops with "session has ended", sign in again in the
open window and resume.

## Safety

The account holds a prepaid toll balance and a card that refills it. The
portal can make payments, change the replenishment amount or card, add and
remove vehicles and transponders, and subscribe to paper statements. This
app activates no control at all. It asks for the statements list and the
PDFs it links and nothing else, a link has to be exactly a statement
download on `ezpassva.com` to be fetched, and an expired session stops the
run rather than reporting an empty success. The click guard every other
app uses is kept and tested here too.

## Commands

```
paperpull ezpassva setup
paperpull ezpassva login        sign in yourself, leave the window open
paperpull ezpassva discover     list what the site has, download nothing
paperpull ezpassva pilot        the newest five
paperpull ezpassva all          everything, delete-safe on a rerun
paperpull ezpassva verify       re-check every saved PDF
paperpull ezpassva diagnose     survey the page and the list, for when it changes
```

## Tests

```
python -m pytest tests -q
```
