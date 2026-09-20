# Citi credit card statement downloader

Downloads your own monthly **card statements** from Citi Online, as PDFs,
for your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

Mapped and run against a real account on 2026-09-20. Twenty-four
statements, every one valid, a second run downloaded nothing, and the
transaction export reads all twenty-four to the cent.

## How it reads the site

After sign-in the browser is on Citi Online at `online.citi.com`, an
Angular app. Statements live on the **Account Statements** page, which is
fed by a JSON API the page calls itself. This app makes the same three
calls from inside the signed-in page, so the session never leaves the
browser, and it clicks nothing. One call lists the cards, one lists the
statements the site has online for a card, and one returns a statement's
PDF. Every card on the sign-in is read, so one sign-in covers them all.

A statement is identified by its card and its closing date. There is no
document id. Filenames carry the card's name as the site shows it, with
the last four digits and the "Card by Citi" boilerplate dropped, so a
month with two cards gets two names instead of a (2).

**What it does not cover.** The site lists roughly the last two years of
statements online. Older ones sit behind **Request Older Statements**,
which is a request this app will never submit, so anything older has to
be asked for on the site by hand. The **Annual Account Summary** is a web
page, not a PDF, and is left alone. A credit card issues no tax forms.

## Sign-in

Citi Online is happiest in a real browser, so sign-in uses your own
installed Edge or Chrome, in a separate profile. You sign in yourself,
answer your own two-factor prompt, and leave the window open. The app
never sees your password. The session is short, so a run that stops with
"session has ended" only needs a fresh sign-in and a resume.

## Safety

This is a credit card account. The site can pay, transfer balances, take
cash advances, redeem points, change the credit line, add users and lock
or replace the card. This app activates no control at all. It makes the
three API calls above and nothing else, every URL it reads has to be on
`citi.com`, and an expired session stops the run rather than reporting an
empty success. The click guard every other app uses is kept and tested
here too, so the repo-wide guard tests cover this app the same as the
rest.

## Commands

```
paperpull citi setup
paperpull citi login        sign in yourself, leave the window open
paperpull citi discover     list what the site has, download nothing
paperpull citi pilot        the newest five
paperpull citi all          everything, delete-safe on a rerun
paperpull citi verify       re-check every saved PDF
paperpull citi diagnose     survey the page and the API, for when it changes
```

## Tests

```
python -m pytest tests -q
```
