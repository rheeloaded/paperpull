# PG&E (Pacific Gas and Electric) bill downloader

Downloads your monthly **billing statements** as PDFs from the PG&E
account portal (`myaccount.pge.com`). Read-only, delete-safe, and part of
[PaperPull](../../README.md).

## Setup

```bat
setup.bat                         REM one-time: create the venv + install Playwright
login.bat                         REM opens a browser on port 9244, sign in yourself
paperpull pge pilot               REM download the newest 5 bills as a test
paperpull pge all                 REM download every available bill
```

The first run asks *"Whose account is this?"* and the name you enter is saved
to `config.json` and stamped on every bill (the **Account Holder** column of
the index CSV).

## How it works

- **You sign in.** `login.bat` opens a browser window using this app's own
  profile and port (9244). You complete sign-in and 2FA yourself, then open
  **Billing and payments** so the bill history is on screen. The tool attaches
  to that signed-in browser over CDP and reuses that tab.
- **Discovery** reads every page of the bill history (the portal's "Jump to"
  page picker is the only control it operates outside a bill row) and lists
  one statement per bill date.
- **Download** finds the bill's row again, checks the row still carries that
  bill's date, and clicks its **View Bill PDF** control. The PDF arrives as a
  download, a network response, or a blob in a popup, and all three are
  handled. The popup is closed afterwards.
- **Read-only.** Every control in a bill row is judged by its label before it
  is clicked. It must read as a document action (view, download, PDF, bill)
  and must not match anything that pays, enrolls, changes service or edits
  the account. A row's **Pay** control never qualifies. There is no code here
  that submits a form or confirms a dialog.
- **Delete-safe.** Once a bill is downloaded it is marked done for good, so
  deleting the PDF after importing it elsewhere does not bring it back.

## Validation status

Ported onto the shared core and the standard command set. The bill history
parsing, pagination and PDF capture were worked out against the live portal
by the contributor. The rebuilt orchestration (run summary, index CSV, PDF
validation, resume) is covered by automated tests but has not had a fresh
live pilot. Start with `paperpull pge pilot` and inspect its results.

## Maintenance

Page behaviour is in `pge_site.py`, the command flow in `pge_docs.py`. When
the portal changes, `paperpull pge diagnose` writes what it sees (row counts, sample
rows, every control and whether the guard would allow it) to the Diagnostics
folder along with a screenshot.
