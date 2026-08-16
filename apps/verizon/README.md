# Verizon (Fios) — bill downloader

Downloads your Verizon **Fios / Home Internet** monthly bill statements as PDFs
from My Verizon. Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup

```bat
setup.bat                 REM one-time: venv + Playwright
login.bat                 REM opens Microsoft Edge on port 9230 — sign in yourself
run_pilot.bat             REM download the newest 5 bills as a test
run_all.bat               REM download every available bill (up to ~24 months)
```

## How it works

- **Real Edge, not Chromium.** Verizon's bot-protection blocks the bundled
  Playwright Chromium ("This page isn't available right now"). `login.bat`
  therefore launches your installed **Microsoft Edge** (falling back to Chrome,
  then Chromium) with the debugging port, and the tool attaches to that.
- **You sign in** in that Edge window; the tool reuses the signed-in tab.
- **Downloads via the "Download Your Bill" page** (`verizon.com/downloadbill`):
  it reads the Bill Date dropdown (Verizon keeps ~24 months), then for each bill
  selects the date, chooses **Download PDF**, and clicks **Get My Bill**.
- **Download capture.** Because we attach to your *real* Edge (not a
  Playwright-managed browser), downloads land in Edge's own download folder. The
  tool points that folder at a temp dir (`.vz-downloads`) over CDP, then moves
  each PDF into `Statements/`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays a bill, changes
  a plan, or edits the account; a control must also look like a document action.

## Scope

- **Fios / Home Internet only.** If you also have (or had) Verizon *Wireless*,
  that's a separate account. An **active** second account can be added with the
  multi-account feature (`add_account.py`, its own login/profile/port). A
  **closed** wireless account is generally no longer downloadable through My
  Verizon — check your email for the final Verizon Wireless bill PDFs instead.
- Delete-safe & multi-account like every PaperPull app.
