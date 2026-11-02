# Invest529 Document Downloader (local, supervised, read-only)

Downloads your Invest529 **account statements** and **tax documents** as
PDFs and maintains an index CSV.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses 2FA.

## Read-only by design

This is a 529 college-savings account, so the tool is deliberately constrained:

- It only reads the Documents area and saves PDFs Invest529 already generated.
- It **never** contributes, withdraws, requests a distribution, changes the
  investment portfolio, edits a beneficiary, or changes any account setting.
- A hard blocklist (`FORBIDDEN_CONTROL_RE` in `invest529_site.py`) rejects
  any control whose label looks transactional, and a control must *also* look
  like a document action before it can be clicked. This is covered by tests
  (`tests/test_doc_types.py`).
- On any 2FA prompt, security challenge, sign-out, or rate limiting it stops
  and hands control back to you.

## Documents captured

Real PDF downloads (not re-rendered web pages), so you get Invest529's
original files.

| Folder | Contents |
|---|---|
| `Statements\` | Quarterly / annual account statements and confirmations |
| `Tax Documents\` | 1099-Q (on qualified/non-qualified distributions), and any other tax form Invest529 posts |
| `Other Documents\` | Anything else, only if you widen `document_types` |
| `Manual Review\` | Files that failed PDF validation |

Trade confirmations, prospectuses, and agreements are skipped by default
(`skip_patterns` in `document_rules.json`).

Filenames: `YYYY-MM-DD Invest529 <Summary>.pdf`, e.g.
`2025-12-31 Invest529 Quarterly Statement.pdf`,
`2025-12-31 Invest529 1099-Q Tax Form.pdf`.
Period-titled documents ("December 2025", "Q4 2025") are filed on the **last
day of that period** so they sort chronologically.

## ⚠ These files are sensitive

Statements and especially tax forms typically contain your **SSN and full
account numbers**. They're saved to the output folder you set as `output_dir`
in `config.json` (the default is this app's own folder). Keep it somewhere
safe, and if that folder syncs to a cloud drive, know these documents go with
it.

The index CSV deliberately records **no** account numbers, balances, or SSN,
only what's needed to locate and verify a file.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf (uses a Chromium browser already on this PC - Edge on Windows) |
| 2 | `login.bat` | Opens a browser (port **9296**); sign in through Okta, open Documents, **leave open** |
| 3 | `paperpull invest529 diagnose` | Read-only look at the Documents page; downloads nothing |
| 4 | `paperpull invest529 pilot` | 5 newest documents, then **stops** for your inspection |
| 5 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 6 | `paperpull invest529 all` | Everything in scope (asks for `YES`) |
| any time | `paperpull invest529 resume` | Continue after an interruption; never redoes finished work |
| any time | `paperpull invest529 verify` | Re-validate every saved PDF |

Port 9296 is unique to this app, so it keeps its own signed-in browser
separate from every other provider's - all of them can be open at once.

Useful filters:

```
python invest529_docs.py --all --type "Tax Document"
python invest529_docs.py --all --year 2025
python invest529_docs.py --all --start-date 2025-01-01
```

## When Invest529 changes its website

All selectors/URLs live in **`invest529_site.py`** only. Run
`paperpull invest529 diagnose` to capture the current structure into `Diagnostics\`, then
repair that one file. Document naming rules live in `document_rules.json`
(plain regex → summary, no code changes needed).

## Tests

```
.venv\Scripts\activate
pytest
```
