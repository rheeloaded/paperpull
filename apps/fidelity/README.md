# Fidelity Investments document downloader

Downloads your own **statements**, **trade confirmations** and **tax forms**
from Fidelity, as PDFs, for your records. Read-only, delete-safe, and part
of [PaperPull](../../README.md).

Mapped and run against a real account on 2026-09-18. Twenty-four documents,
four monthly statements and twenty trade confirmations, every one valid,
and a second run downloaded nothing.

## How it reads the site

After sign-in the browser is on Fidelity's web app at `digital.fidelity.com`.
Documents live in the **Document Access Hub** at `digitalservices.fidelity.com`,
an app with three tabs, statements, tax forms and trade confirmations, a
year picker on each, and a Download link per row. This app never clicks any
of them. It makes the same API calls the page makes, from inside the
signed-in page, so the session cookies never leave the browser. One call
lists the accounts, one lists a year of one kind, and one returns a
document's PDF. The API refuses a window wider than a year, so discovery
asks one year at a time, newest first, back to the oldest year the hub's
picker offers, and a run scoped with `--year` or `--start-date` asks only
for the years it wants. Tax forms are listed by tax year and can be dated in
the year after it, so a scoped run asks for the year before as well, and a
form is in scope when its own date or the last day of its tax year is.
`--year 2025` keeps the forms of tax year 2025 and the forms dated in 2025.

Each document is identified by its kind, its account and its period end
date, never by the hub's own id, which is stored as a hint and looked up
fresh at download time. Filenames carry the account's display name and the
last four digits of its number, never the whole number. Documents sharing a
title and a date are told apart by a number. A download finds its own row of
a fresh list by the id it keeps, or by that number when the list no longer
shows the id, and when the list cannot say which row it is, that document
fails and nothing is saved for it.

A **consolidated statement**, one covering several accounts, has no account
number of its own, so its account reads `Combined`. The default file name
leaves the account out, so it reads as it always did. A folder per account,
`Combined` among them, takes a `filename_pattern` with `{account}` in it, as
in [file naming](../../docs/file-naming.md).

**Which kinds a run downloads** is `document_types` in `config.json`. Trade
confirmations arrive weekly on an account that trades on a schedule and can
run to hundreds, so drop `"Trade Confirmation"` from the list if you only
want statements.

**Tax forms** are listed through their own call, and a contributor's Discover
listed them on a real account (#144). Nobody has shown one downloading yet.
The app asks for each through the hub's v1 download call, as that contributor
reports, and that step is marked unverified in the code. If a form will not
download, or you have seen one come down, run `paperpull fidelity diagnose`
and say so on an issue with the survey file.

One thing this does not cover. A **workplace plan** (a 401(k) through
NetBenefits) is listed by the accounts call but keeps its statements on
NetBenefits, not in this hub, so it is not read here.

## Sign-in

Fidelity sits behind a bot-management CDN, so sign-in uses your own
installed Edge or Chrome, in a separate profile, rather than a bare
Chromium, the same as Chase. You sign in yourself, answer your own
two-factor prompt, and leave the window open. The app never sees your
password.

## Safety

This is a brokerage and retirement account. The site can buy and sell,
transfer and wire money, take distributions and change beneficiaries. This
app never activates a control that does any of those. Every control it
would touch has to clear a blocklist of those words and match an allowlist
of document words, every URL it reads has to be on `fidelity.com`, and the
in-page request refuses any other host before it is sent. An expired
session stops the run rather than reporting an empty success.

## Commands

```
paperpull fidelity setup
paperpull fidelity login        sign in yourself, leave the window open
paperpull fidelity discover     list what the hub has, download nothing
paperpull fidelity pilot        the newest five
paperpull fidelity all          everything, delete-safe on a rerun
paperpull fidelity verify       re-check every saved PDF
paperpull fidelity diagnose     survey the hub, for when it changes
```

## Tests

```
python -m pytest tests -q
```
