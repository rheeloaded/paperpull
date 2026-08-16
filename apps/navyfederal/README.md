# Navy Federal Credit Union — statement downloader

Downloads your Navy Federal **account statements** as PDFs from the online
banking portal (`digitalomni.navyfederal.org`). Read-only, delete-safe, part of
[PaperPull](../../README.md).

## Setup

```bat
setup.bat                 REM one-time: venv + Playwright
login.bat                 REM opens Chromium on port 9229 — sign in yourself
run_pilot.bat             REM download the newest 5 statements as a test
run_all.bat               REM download every available statement
```

The first run asks *"Whose account is this?"* — the name is saved to `config.json`
and stamped on every document (the **Account Holder** index column).

## How it works

- **You sign in.** `login.bat` opens a normal Chromium (port 9229); you complete
  sign-in and 2FA. The tool attaches over CDP and **reuses your signed-in tab**
  (the portal keeps its session there).
- The Statements page groups documents by account into expandable accordions
  (Checking & Savings, loans, certificates, Tax Information, Previous
  Statements). Discovery expands each group and reads its statement rows
  (date + account).
- **Download**: it expands the right account, clicks that statement's **View**
  button — which opens the PDF as a `blob:` in a new tab — then fetches the blob
  bytes and saves them, closing the extra tab. Filenames include the account so
  same-dated statements from different accounts don't collide.
- **Session timeouts.** Navy Federal shows an inactivity modal; the tool clicks
  its **"Continue Session"** keep-alive automatically. On a real sign-out it
  stops and hands control back to you.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that transfers, pays,
  deposits, disputes, or changes the account; a control must also look like a
  document action before it's clicked.

## Notes

- **Tax documents:** the Tax Information section is scanned too, but Navy Federal
  only posts tax forms (1099-INT etc.) seasonally — outside tax season there may
  be none to download.
- **Delete-safe & multi-account** like every PaperPull app (`--config`,
  `add_account.py`).
