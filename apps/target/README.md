# Target Receipts Downloader (local, supervised)

Downloads your available Target.com purchase history (Online and In-store),
saves each printable receipt directly as a PDF, and maintains two CSV files:

- `Target Order History.csv` — one row per purchased item
- `Target Receipt Index.csv` — one row per downloaded PDF

Everything runs **locally**. Nothing (item names, receipts, account data) is
sent to any external AI API or third-party service. You sign in to Target
**manually** — the tool never touches your credentials, and never bypasses
CAPTCHAs or security checks.

## Setup (one time)

1. Double-click `setup.bat`
   (creates `.venv`, installs Playwright + pypdf, downloads Chromium)
2. Double-click `login.bat` and sign in to Target manually in the browser
   window that opens. Press Enter in the console when done.
   Your session is stored in the local `target-browser-profile` folder.

## Recommended workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `login.bat` | Manual sign-in, saved in local browser profile |
| 2 | `python target_receipts.py --diagnose` | Inspects one purchase per section; writes Diagnostics |
| 3 | `run_pilot.bat` | 5 newest Online + 3 newest In-store; then **stops** |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `run_all.bat` | Full history (asks for `YES` confirmation) |
| any time | `resume.bat` | Continue after an interruption — never restarts finished work |
| any time | `verify_receipts.bat` | Re-validate every indexed PDF |
| any time | `review_names.bat` | Fix low-confidence filenames interactively |

## All command-line options

```
python target_receipts.py --login | --discover | --pilot | --pilot-online |
    --pilot-instore | --online | --instore | --all | --resume | --verify |
    --review-names | --diagnose | --dry-run
Filters:  --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
          --max-purchases N  --order-number N  --include-invoices  --yes
```

## Output layout

```
C:\Users\YOU\Downloads\Target Receipts\
  Online\            receipts from Online orders
  In-Store\          receipts from in-store transactions
  Invoices\          invoices (only with --include-invoices)
  Manual Review\     PDFs that failed validation
  Logs\  Diagnostics\  Backups\
  Target Order History.csv    Target Receipt Index.csv
  progress.json  discovery.json  run-summary.txt
```

Filenames: `YYYY-MM-DD Target <Purchase Summary> Receipt.pdf`
(e.g. `2024-12-31 Target Groceries Receipt.pdf`). Collisions get ` (2)`,
` (3)`… — an existing PDF is **never overwritten**.

## Classification

`category_rules.json` holds editable keyword → category rules. Classification
is deterministic and fully local. Low-confidence purchases are saved anyway,
marked *Review Needed*, and can be renamed with `review_names.bat`.

## When Target changes its website

All Target selectors and page behavior live in **`target_site.py`** only.
Run `python target_receipts.py --diagnose` to capture what the page looks
like now (Diagnostics folder), then adjust `target_site.py`.

## Safety

- Read-only on Target: never orders, returns, cancels, reviews, or changes
  account/payment/delivery settings; never prints gift receipts.
- Stops and asks you to take over on sign-out, CAPTCHA, verification, or
  rate limiting. Never retries aggressively, never evades detection.
- Sequential processing with polite randomized delays.
- Progress written atomically after every purchase; CSV/JSON backed up to
  `Backups\` before rewrites; interrupted runs resume with `resume.bat`.

## Tests

```
.venv\Scripts\activate
pytest
```
