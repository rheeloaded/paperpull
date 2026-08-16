# Wealthfront Document Downloader (local, supervised, read-only)

Downloads your Wealthfront **account statements** and **tax documents** as
PDFs and maintains an index CSV.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses 2FA.

## Read-only by design

This is a brokerage account, so the tool is deliberately constrained:

- It only reads the Documents area and saves PDFs Wealthfront already generated.
- It **never** transfers money, deposits, withdraws, buys, sells, trades,
  rebalances, changes allocations, edits beneficiaries, or changes any setting.
- A hard blocklist (`FORBIDDEN_CONTROL_RE` in `wealthfront_site.py`) rejects
  any control whose label looks transactional, and a control must *also* look
  like a document action before it can be clicked. This is covered by tests
  (`tests/test_doc_types.py`).
- On any 2FA prompt, security challenge, sign-out, or rate limiting it stops
  and hands control back to you.

## Documents captured

Real PDF downloads (not re-rendered web pages), so you get Wealthfront's
original files.

| Folder | Contents |
|---|---|
| `Statements\` | Monthly / quarterly / annual account statements |
| `Tax Documents\` | 1099-B, 1099-DIV, 1099-INT, 1099-R, consolidated 1099, etc. |
| `Other Documents\` | Anything else, only if you widen `document_types` |
| `Manual Review\` | Files that failed PDF validation |

Trade confirmations, prospectuses, and agreements are skipped by default
(`skip_patterns` in `document_rules.json`).

Filenames: `YYYY-MM-DD Wealthfront <Summary>.pdf`, e.g.
`2025-12-31 Wealthfront Monthly Statement.pdf`,
`2025-12-31 Wealthfront 1099-B Tax Form.pdf`.
Period-titled documents ("December 2025", "Q4 2025") are filed on the **last
day of that period** so they sort chronologically.

## ⚠ These files are sensitive

This folder is inside **OneDrive**, so its contents sync to Microsoft's cloud.
Tax forms typically contain your **SSN and full account numbers**. That's a
deliberate choice you made; if you'd rather keep them off the cloud, change
`output_dir` in `config.json` to a local path (e.g. `C:\Users\YOU\Documents\...`)
and move the existing folders.

The index CSV deliberately records **no** account numbers, balances, or SSN —
only what's needed to locate and verify a file.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium (port **9224**); sign in, open Documents, **leave open** |
| 3 | `diagnose.bat` | Read-only look at the Documents page; downloads nothing |
| 4 | `run_pilot.bat` | 5 newest documents, then **stops** for your inspection |
| 5 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 6 | `run_all.bat` | Everything in scope (asks for `YES`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_documents.bat` | Re-validate every saved PDF |

Port 9224 keeps this separate from the Walmart (9222) and Amazon (9223)
projects, so all of them can have a signed-in browser open at once.

Useful filters:

```
python wealthfront_docs.py --all --type "Tax Document"
python wealthfront_docs.py --all --year 2025
python wealthfront_docs.py --all --start-date 2025-01-01
```

## When Wealthfront changes its website

All selectors/URLs live in **`wealthfront_site.py`** only. Run
`diagnose.bat` to capture the current structure into `Diagnostics\`, then
repair that one file. Document naming rules live in `document_rules.json`
(plain regex → summary, no code changes needed).

## Tests

```
.venv\Scripts\activate
pytest
```
