# Thrift Savings Plan (tsp.gov) statement downloader

Downloads your own **participant statements** and **1099-R tax forms** from
TSP's My Account, as PDFs, for your records. Read-only, delete-safe, and
part of [PaperPull](../../README.md).

> **Status: in discovery.** The app is scaffolded with the guards, the
> folders and the rules in place, but the pages behind My Account have not
> been mapped yet, so `discover` finds nothing and says so. `diagnose`
> gathers what is needed to map them. See the STATUS block at the top of
> `tsp_site.py` for exactly what is confirmed and what is not.

## This is a US government system

TSP is run by the Federal Retirement Thrift Investment Board. Its terms of
use may restrict automated access to your own account. That is your call to
make before running this. What the app does on its side is the same as
every other PaperPull provider, and stricter in two ways.

- You sign in yourself, enter your own one-time passcode, and accept any
  consent banner yourself. The app never clicks through a government
  banner and never sees your password or passcode.
- An expired session stops the run loudly rather than reporting an empty
  success.

## What it will never do

My Account can move money between funds, change contribution allocations,
start a withdrawal or an installment, take a loan, change beneficiaries and
change where money is sent. Every one of those words is on the blocklist in
`tsp_site.py`, a control must also read as a document action before it is
touched, and the survey `diagnose` runs follows only links whose text is
exactly a document or mailbox word. A test pins each of those.

## Setup

```bat
setup.bat                         REM one-time: create the venv + install Playwright
login.bat                         REM opens a browser on port 9246, sign in yourself
paperpull tsp diagnose            REM read-only survey of what My Account shows, downloads nothing
paperpull tsp pilot               REM once mapped, download the newest 5 as a test
paperpull tsp all                 REM once mapped, download every statement in scope
```

`diagnose` writes `Diagnostics/diagnose-documents.json`. It holds the page
titles, headings and controls it saw, the guard's verdict on each control,
and the shape (not the contents) of any JSON the site returned. Runs of six
or more digits are masked, so an account number never reaches the file.
There is no screenshot, because a retirement account page shows balances.

## What it files

| Folder | What |
|---|---|
| `Statements/` | Quarterly and annual participant statements, and letters or notices from the mailbox |
| `Tax Documents/` | 1099-R and any other tax form |

Filenames follow the usual `YYYY-MM-DD TSP <Summary>.pdf`.
