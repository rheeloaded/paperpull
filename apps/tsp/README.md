# Thrift Savings Plan (tsp.gov) statement downloader

Downloads your own **participant statements** and **1099-R tax forms** from
TSP's My Account, as PDFs, for your records. Read-only, delete-safe, and
part of [PaperPull](../../README.md).

Mapped and run against a real account on 2026-09-18. Twenty-five documents
back to January 2022, every one valid, and the run marked nothing for
review.

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

## How it reads the site

After sign-in the browser is on My Account, which lives at
`api.rk.tsp.gov`, the plan's recordkeeper, not on tsp.gov's own pages.
Statements and tax forms are messages in the **Secure Mailbox**, each with
one PDF attached. The app reads that mailbox through the same two API calls
the page itself makes, one for the list, one for a message's attachment,
run from inside the signed-in page so the session token never leaves the
browser. Nothing on the page is clicked. Every message is identified by
its subject and delivery date, and looked up again fresh before download.

**One side effect, stated plainly.** Fetching a message's attachment is
what the site does when you open the message, and it marks the message as
read. The unread count in your mailbox goes down as documents download.
Nothing else changes.

Notices such as Payment Confirmation, Payment Rights Notice and Rollover
Contribution Status are filed as Other Document and skipped unless you add
`"Other Document"` to `document_types` in `config.json`.

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
paperpull tsp diagnose            REM read-only survey of the mailbox, downloads nothing
paperpull tsp pilot               REM download the newest 5 as a test
paperpull tsp all                 REM download every statement in scope
```

`diagnose` writes `Diagnostics/diagnose-documents.json`, a survey of the
page rather than a screenshot. Runs of six or more digits are masked, and
JSON is recorded as shape only, never values.

## What it files

| Folder | What |
|---|---|
| `Statements/` | Annual, quarterly and online account statements, the statement supplement, and the Lifetime Income Illustration |
| `Tax Documents/` | 1099-R |

Filenames follow the usual `YYYY-MM-DD TSP <Summary>.pdf`, dated by the
message's delivery date.

## When the site changes

Page behavior is in `tsp_site.py`, the command flow in `tsp_docs.py`. The
STATUS block at the top of `tsp_site.py` records the API, the two session
headers it needs and where they come from. The 1099-R arrives with a
print-stream line in front of the PDF header, which is stripped, and
statements do not. If a download starts failing, `diagnose` shows what the
mailbox looks like now.
