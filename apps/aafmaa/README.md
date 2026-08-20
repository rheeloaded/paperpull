# AAFMAA Document Downloader (local, supervised, READ-ONLY)

Downloads your AAFMAA (Armed Forces Mutual) **premium statements**, **policy
and insurance documents**, and **tax forms** as PDFs, and keeps an index CSV.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in **manually**; the tool never touches your
credentials and never bypasses AAFMAA's 2FA or security checks.

> **Status: the site layer is not verified yet.** The URLs and selectors in
> `aafmaa_site.py` are starting guesses. Run `login.bat`, then `diagnose.bat`,
> and repair them against what lands in `Diagnostics\`. The safety guard does
> not depend on any of that and applies from the first run.

## Read-only by design (this portal can move money)

The Member Center's own front page offers **Pay Premiums**, **Check Loan
Balances**, **Make a Payment**, **Update Family Information** and **Update
Contact Information**. A member can take a policy loan and pay a premium from
here, so read-only is not a nicety.

This tool only reads the document areas and saves PDFs AAFMAA has already
generated. It **never** pays a premium, requests or repays a loan, surrenders
or withdraws value, changes a beneficiary, edits contact or family details,
applies for or cancels coverage, or changes any setting. A control must pass
**two** checks before it may be clicked: it must look like a document action
(`SAFE_DOC_CONTROL_RE`) *and* match nothing in the blocklist
(`FORBIDDEN_CONTROL_RE`). Both live in `aafmaa_site.py` and are covered by
tests in `tests/test_doc_types.py`. There is no code path that submits a form
or confirms a dialog.

## How it connects

`login.bat` opens an ordinary Chromium (debugging port **9235**) that **you**
sign into. The tool then connects to that already-signed-in browser and reads
only the pages you are authorised to see. No stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9235 is this app's alone, so several signed-in browsers can be open at
once without two apps sharing a profile.

## How the site is built

`connect.aafmaa.com` is classic ASP.NET WebForms. Two things follow from that:

- The session is a **server-side cookie**, so navigating straight to a deep
  page keeps you signed in. Unlike the Amex app, nothing is lost on `goto`.
- Many "links" are not links — they are `__doPostBack(...)` handlers on an
  `<a>`, so the href tells you nothing and the control has to be clicked.
  Where a real handler URL with a document id exists, the tool uses that
  instead; clicking a row is the fallback.

## Documents captured

| Folder | Contents |
|---|---|
| `Statements\` | Premium statements and notices, billing statements, loan statements |
| `Insurance Documents\` | Certificates of insurance, policy documents, coverage summaries |
| `Tax Documents\` | 1099-INT, 1099-R, 1098 and similar (these contain your SSN) |
| `Year-End Summaries\` | Annual statements (created only once one is found) |
| `Other Documents\` | Anything else (only if you widen `document_types`) |
| `Manual Review\` | Files that failed PDF validation |

Filenames: `YYYY-MM-DD AAFMAA <Summary>.pdf`, e.g.
`2026-03-31 AAFMAA Premium Statement.pdf`,
`2025-12-31 AAFMAA Certificate of Insurance.pdf`,
`2025-12-31 AAFMAA 1099-INT Tax Form.pdf`.

Naming rules are in `document_rules.json` (plain regex -> summary, editable,
no code changes needed). Those rules are provisional too — retune them once
you have seen what your account actually calls things.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium (port 9235); sign in, open your documents area, **leave open** |
| 3 | `diagnose.bat` | Read-only look at the page structure; downloads nothing |
| 4 | `run_pilot.bat` | 5 newest documents, then **stops** for your inspection |
| 5 | inspect the PDFs/CSV | You approve before anything bigger runs |
| 6 | `run_all.bat` | Everything in scope (asks for `YES`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_documents.bat` | Re-validate every saved PDF |

Filters: `--type "Insurance Document"`, `--year 2025`,
`--start-date 2025-01-01`.

## If a site change breaks it

All the site-specific logic lives in `aafmaa_site.py`. If AAFMAA redesigns its
pages and discovery or download stops working, run `diagnose.bat` after signing
in — it dumps the current page structure to `Diagnostics\` so the selectors can
be updated to match. Nothing else in the app needs to change.

## Sensitive files

Premium statements and especially tax forms can contain your SSN, policy
numbers and coverage amounts. They are saved to the folder you set as
`output_dir` in `config.json` (the default is this app's own folder). Keep it
somewhere safe, and if that folder syncs to a cloud drive, know these
documents go with it. The index CSV deliberately records **no** policy
numbers, coverage amounts, or SSN — only what is needed to find and verify a
file.

## Tests

```
.venv\Scripts\activate
pytest
```
