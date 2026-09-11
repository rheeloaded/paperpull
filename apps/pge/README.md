# PG&E (Pacific Gas and Electric) — bill downloader

Downloads your monthly **billing statements** as PDFs from the PG&E
account portal (`pge.com`). Read-only, delete-safe, and part of [PaperPull](../../README.md).

## Setup

```bat
setup.bat                 REM one-time: create the venv + install Playwright
login.bat                 REM opens Chromium on port 9242 — sign in yourself
run_pilot.bat             REM download the newest 5 bills as a test
run_all.bat               REM download every available bill
```

The first run asks *"Whose account is this?"* — the name you enter is saved to
`config.json` and stamped on every bill (the **Account Holder** column of the
index CSV).

## How it works

- **You sign in.** `login.bat` opens a normal Chromium window using this app's
  own profile and port (9242). You complete sign-in and 2FA yourself; the tool
  attaches to that signed-in browser over CDP.
- **Discovery** reads the Statements / Billing History area to list available energy statements.
- **Download** initiates a PDF download for each selected statement.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays a bill, changes
  service, or edits the account; a control must also look like a document action
  (`SAFE_DOC_CONTROL_RE`) before it's ever clicked.
- **Delete-safe.** Once a bill is downloaded it's marked done for good.
