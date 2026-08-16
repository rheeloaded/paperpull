# Verizon (Virginia) — bill downloader

Downloads your monthly **billing statements** as PDFs from the Verizon
Virginia account portal (`myaccount.verizonenergy.com`). Read-only, delete-safe,
and part of [PaperPull](../../README.md).

## Setup

```bat
setup.bat                 REM one-time: create the venv + install Playwright
login.bat                 REM opens Chromium on port 9230 — sign in yourself
run_pilot.bat             REM download the newest 5 bills as a test
run_all.bat               REM download every available bill
```

The first run asks *"Whose account is this?"* — the name you enter is saved to
`config.json` and stamped on every bill (the **Account Holder** column of the
index CSV).

## How it works

- **You sign in.** `login.bat` opens a normal Chromium window using this app's
  own profile and port (9230). You complete sign-in and 2FA yourself; the tool
  attaches to that signed-in browser over CDP and **reuses your tab** (the portal
  keeps its session there).
- **Discovery** reads the paginated **Billing History** table — each bill is a
  Material-UI accordion whose header shows the statement date. It walks every
  page to list all bills.
- **Download** expands a bill's row and clicks its *"Download Your Detailed Bill
  PDF"* button, capturing the PDF.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays a bill, changes
  service, or edits the account; a control must also look like a document action
  (`SAFE_DOC_CONTROL_RE`) before it's ever clicked. Pagination is the only thing
  clicked beyond download/expand.

## Good to know

- **Verizon only keeps bill PDFs for ~18 months.** Older bills all return an
  identical *"Images for Bills older than 18 months are not available"*
  placeholder. The tool detects that, deletes the junk file, and marks those
  bills **No Receipt Available** (they won't be retried). So a full run saves the
  ~18 most recent bills and records the rest as unavailable.
- **Delete-safe.** Once a bill is downloaded it's marked done for good — delete
  the PDF after importing it elsewhere and it won't be re-downloaded.
- **Multi-account** via `--config config.<name>.json` (see `add_account.py`).
