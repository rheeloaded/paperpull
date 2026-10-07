# Nelnet statements and tax forms

Downloads your Nelnet student loan billing statements and your 1098-E as
PDFs. Nelnet services federal student loans for the Department of Education
at `nelnet.studentaid.gov`. This reads from a browser where you sign in
yourself. Passwords and verification codes are never handled by the
downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull nelnet diagnose`, then `paperpull nelnet pilot`.
5. Check the downloaded documents before using `paperpull nelnet all`.

Existing download history is retained in the provider's local state files.
Deleting a downloaded file does not reset that history.

## Validation status

Mapped and run against a real account (2026-10-07). A full run saved all 47
documents the site lists: 41 statements back to December 2019, the 1098-E,
and 5 notices. Every one is a valid PDF, nothing was sent to manual review,
and the count matches the inbox's 46 items plus the 1098-E. The statements
are three pages each, and the printed statement date in the five checked
matches its file name. The 1098-E is one page. Running it again downloaded
nothing. Automated tests cover the guard, the pager, the row reading, the
host check, filing, notice names, and the 1098-E capture in a real browser
against an invented page.

## What it saves

- **Statements.** The monthly billing statements from Inbox & Statements,
  filed in `Statements`.
- **The 1098-E.** From Tax Info, filed in `Tax Documents` and dated the end
  of its tax year.
- **Notices.** The letters in the same inbox, such as an annual repayment
  notice or a deferment or forbearance letter, filed in `Other Documents`.
  The shared rules have no word for a letter, so each is named by its own
  subject, cut near sixty characters, since Nelnet's subjects can run to a
  whole sentence.

Not saved:

- **Loan Summary and Payment Schedule.** These are web pages with a Print
  button and no file, and the Loan Summary carries the day it was opened, so
  neither is a document that stays the same.
- **Forms.** That page only links out to studentaid.gov.

The account tested had one loan account. How the inbox lays out a borrower
with several is not known.

## How it reads the site

The site is an Angular app on a cookie session, so opening a page by its
address keeps you signed in. Its data comes from a second host,
`mmaapi.nelnet.studentaid.gov`, which a request from inside the page with
only its cookies cannot reach, so nothing here asks that host directly.

Inbox & Statements is one list of statements and notices, ten rows a page,
paged inside the browser. The app reads each row from the page, with the
date from its first cell and the document's own name from its Download
button's label, and turns the pager with the page's own Next Page button.
Each row's Download button carries the document's id in `data-cy`, which is
how two rows are told apart. Pressing it makes the page fetch the PDF from
`mmaapi.nelnet.studentaid.gov/api/1/statements/pdf/...`, and the browser then
fires an ordinary download event named `statement_YYYYMMDD.pdf`, which the
app saves under its own name.

The 1098-E is not a file. Its button on Tax Info calls `window.print()`,
which would open the browser's print dialog and wait for a person. The app
holds that call back for the press, which is what makes the page lay out the
form, and then prints the live page to PDF itself.

## Nothing is pressed that could change anything

The only things pressed are a row's Download button, the 1098-E button, and
the list's pager buttons. Each goes through the guard first. The guard reads
the control's own wording and not the title of the document it belongs to,
because a notice titled "Deferment Approved" is a
document to download and not a button that requests a deferment. A control
that makes a payment, sets up auto debit, asks for a deferment or
forbearance, applies for anything, or changes a setting is refused whatever
document it sits beside.

The Log Out and Stay Logged In buttons the pages hold are never pressed.

Everything stays on this machine and nothing is sent anywhere.
