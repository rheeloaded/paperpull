# T-Mobile — bill downloader

Downloads your T-Mobile monthly **bill statements** as PDFs from My T-Mobile.
Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup

```bat
setup.bat                 REM one-time: venv + Playwright
login.bat                 REM opens a browser on port 9231 — sign in yourself
run_pilot.bat             REM download the newest 5 bills as a test
run_all.bat               REM download every available bill
```

## How it works

- **Plain Chromium.** T-Mobile does not block the bundled Playwright Chromium,
  so `login.bat` launches it with a debugging port and the tool attaches to
  that signed-in browser — consistent with the other PaperPull apps.
- **You sign in** in that window; the tool reuses the signed-in tab.
- **Bill history.** Discovery opens `t-mobile.com/bill/historical`, where every
  available bill (current + past) is listed. Each bill exposes a **Download
  detailed bill** button whose label carries the bill date
  (e.g. *"Aug 12, 2026 Download detailed bill PDF"*).
- **Downloads** are ordinary browser download events — clicking a bill's
  **Download detailed bill** button fires a real download that Playwright
  captures directly, and the PDF is saved into `Statements/`. (No CDP
  download-directory plumbing is needed.)
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays a bill,
  enrolls in autopay/paperless, changes a plan, or edits the account; a control
  must also look like a document action before it can be clicked.

## Scope

- **The detailed bill** (the full multi-page PDF) is downloaded for each period.
  T-Mobile also offers a shorter "summary bill"; PaperPull keeps the detailed
  one.
- **History depth is whatever My T-Mobile exposes** on the bill-history page
  (a handful of recent months at the time of writing). Older bills that
  T-Mobile no longer lists cannot be downloaded through this page.
- A second T-Mobile account (e.g. a family member's) can be added with the
  multi-account feature (`add_account.py`, its own login/profile/port).
- Delete-safe & multi-account like every PaperPull app.
