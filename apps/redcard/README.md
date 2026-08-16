# Target RedCard / Target Circle Card — statement downloader

Downloads your **Target Circle Card (RedCard credit)** monthly **billing
statements** as PDFs and keeps an index CSV. Read-only, delete-safe, part of
[PaperPull](../../README.md).

The RedCard **credit** card (recently rebranded "Target Circle Card") is issued
and serviced by **TD Bank USA** through the "Manage my Target Circle Card"
portal (`rcam.target.com` → `mytargetcirclecard.target.com`). This app targets
that portal. (The RedCard **debit** card is a different, Target-hosted product
and is out of scope.)

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses the portal's 2FA / verification.

## Read-only by design (this is a credit-card account)

The tool only reads the Statements area and saves the statement PDFs TD already
generated. It **never** makes a payment, sets up autopay, transfers a balance,
takes a cash advance, redeems rewards/points, applies for anything, disputes a
charge, locks/cancels a card, enrolls in paperless, or changes any setting. A
control must pass **two** checks before it can be clicked: it must look like a
document action *and* match nothing in a large money / account blocklist
(`FORBIDDEN_CONTROL_RE` in `redcard_site.py`). Covered by tests
(`tests/test_doc_types.py`). There is no code path that submits a form or
confirms a dialog.

## How it connects

`login.bat` opens an ordinary Chromium (debugging port **9232**) that **you**
sign into; the tool connects to that already-signed-in browser and reads the
pages you're authorized to see. No stealth, no evasion. TD's portal does not
block the bundled Chromium, so a plain Chromium is used (like most PaperPull
apps).

**The signed-in browser window must stay OPEN while the tool runs.**

## How it works

- Statements live at `mytargetcirclecard.target.com/statements` as a single
  **table**: Date (MM-DD-YYYY) | Document type | balances | Payment due |
  **Download pdf** | View.
- A **year switcher** (`2026 / 2025 / 2024`) reloads the table one year at a
  time. Discovery reads the current year, then clicks each past year and reads
  those rows too.
- Each row's **"Download pdf"** link fires a real browser download event that
  Playwright captures directly (filename `YYYYMMDD.pdf`), which is saved to
  `Statements/` as `YYYY-MM-DD Target Circle Card Statement.pdf`.
- **Short session:** TD's portal session is short-lived. If it expires
  mid-run, a download is retried after a fresh navigation, and a genuinely
  expired session is reported so you can sign in again and `resume.bat`. For a
  clean run, sign in and run the pilot promptly.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium (port 9232); sign in, open your Statements, **leave open** |
| 3 | `run_pilot.bat` | 5 newest statements, then **stops** for your inspection |
| 4 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 5 | `run_all.bat` | Every statement in scope (asks for `YES`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_documents.bat` | Re-validate every saved PDF |
| any time | `diagnose.bat` | Read-only dump of the page structure; downloads nothing |

## Delete-safe (paperless-ngx workflow)

Once a statement downloads successfully it is remembered as done for good — you
can delete the PDF (e.g. after importing into paperless-ngx) and it will NOT be
re-downloaded. Each run writes `new-this-run.txt` listing exactly what was
downloaded that run. To rebuild deleted files, add `--redownload`.

## A second account

`login.bat spouse` + `python add_account.py spouse` set up a second Target
Circle Card login with its own folders, browser profile, and debugging port —
no re-downloading and no mixing of data.

## Tests

```
.venv\Scripts\activate
pytest
```
