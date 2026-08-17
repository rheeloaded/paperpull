# Security & privacy

These tools sign in to **real financial and shopping accounts** and download
**real statements and receipts**. Treat this repository accordingly.

## What must never be committed

The `.gitignore` already blocks all of the following. Do not override it.

- **Browser profile folders** (`*-browser-profile/`) — these hold live logged-in
  sessions: cookies and auth tokens for your bank, brokerage, and Amazon. This
  is the single worst thing that could leak. Anyone with them can act as you.
- **`config.json` / `config.<account>.json`** — your real paths and account
  labels. Only the sanitized `config.example.json` is tracked.
- **Downloaded documents** (`*.pdf`, `*.zip`) — your actual financial records.
- **Runtime state** — `discovery.json`, `progress.json`, `*.log`, `*.csv`,
  `Diagnostics/` (which can contain screenshots of signed-in pages), `Backups/`.

## Before your first commit

1. Confirm nothing sensitive is staged: `git status` should show only source,
   docs, and `config.example.json`.
2. If you ever accidentally commit a secret, deleting it in a later commit is
   **not enough** — it stays in git history. Scrub history (e.g. with
   `git filter-repo`) or start a fresh repo.

## Design safety (what the tools themselves do)

- **Read-only.** There is no code anywhere that submits a form, confirms a
  dialog, moves money, or changes a setting. How that is enforced depends on
  how the provider exposes its documents:

  - **The statement apps** (Amex, Dominion, Navy Federal, RedCard, Robinhood,
    T-Mobile, USAA, Verizon, Wealthfront) click a download control, and gate it
    with `is_safe_control()`: a hard blocklist (`FORBIDDEN_CONTROL_RE` —
    buy/sell/transfer/pay/delete/change-setting/…) **plus** a document
    allowlist (`SAFE_DOC_CONTROL_RE`). A control must pass **both**, so
    anything unrecognised is refused — deny by default.
  - **The receipt apps** (Amazon, Target, Walmart) click a print/invoice
    control matched by a narrow pattern and screened against the same
    blocklist. There is no separate allowlist in these three, so the guard is
    blocklist-only.
  - **Gap** clicks nothing at all: it navigates to the order page and renders
    it, so no control is ever activated.
- **You sign in, not the tool.** The tools attach to a browser *you* logged into
  (via Chrome DevTools Protocol). They never handle your password or 2FA.
- **Local only.** The browser's debugging port and the GUI both listen on
  `127.0.0.1` (localhost) — nothing is exposed to your network. Note that while
  the signed-in browser is open, any program running **on your own machine**
  could attach to that debugging port, so close the browser window when you're
  done downloading. The GUI additionally refuses any request whose `Origin`/
  `Referer` is not localhost, so another website you have open cannot drive it.
- **Delete-safe.** A sticky `downloaded_ok` marker means deleting the PDFs after
  you import them elsewhere will not cause re-downloads.

## Reporting

This is a personal-use project with no warranty. If you find a security issue,
open an issue describing it (without including any real credentials or data).
