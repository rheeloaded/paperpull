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

- **Read-only.** Each `*_site.py` pairs a hard blocklist (`FORBIDDEN_CONTROL_RE`
  — buy/sell/transfer/pay/delete/change-setting/…) with a document allowlist
  (`SAFE_DOC_CONTROL_RE`). A control must pass **both** before it is ever
  clicked. There is no code that submits a form, confirms a dialog, moves money,
  or changes a setting.
- **You sign in, not the tool.** The tools attach to a browser *you* logged into
  (via Chrome DevTools Protocol). They never handle your password or 2FA.
- **Delete-safe.** A sticky `downloaded_ok` marker means deleting the PDFs after
  you import them elsewhere will not cause re-downloads.

## Reporting

This is a personal-use project with no warranty. If you find a security issue,
open an issue describing it (without including any real credentials or data).
