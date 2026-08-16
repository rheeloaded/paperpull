# Walmart Receipts Downloader (local, supervised)

Downloads your available Walmart.com purchase history (Online and In-store),
saves each printable receipt directly as a PDF, and maintains two CSV files:

- `Walmart Order History.csv` — one row per purchased item
- `Walmart Receipt Index.csv` — one row per downloaded PDF

Everything runs **locally**. Nothing (item names, receipts, account data) is
sent to any external AI API or third-party service. You sign in to Walmart
**manually** — the tool never touches your credentials, and never bypasses
CAPTCHAs or security checks.

## How Walmart differs from a normal run

Walmart uses aggressive bot detection (PerimeterX "Robot or human?"). An
automation-launched browser cannot pass it. So this tool does **not** launch
its own browser — instead it **connects to an ordinary Chromium that YOU sign
into**, over the DevTools protocol (`cdp_url` in `config.json`). A real human
signs in to a real browser (no stealth, no evasion); the tool only reads the
pages you are authorized to see. Because the browser is launched normally,
`navigator.webdriver` is false and Walmart treats it as a human session.

Consequence: **the signed-in browser window must stay OPEN the whole time**
the tool runs. Closing it signs you out (Walmart uses in-memory session
cookies).

Receipts are captured with Chromium's `printToPDF` (print media) directly on
the order-details page — the tool never clicks "View receipt details" /
"Print invoice" (those fire the native print dialog). In-store trips are saved
as **Receipts**, online orders as **Invoices** (Walmart exposes only an
invoice for online orders).

## Setup (one time)

1. Double-click `setup.bat`
   (creates `.venv`, installs Playwright + pypdf, downloads Chromium)
2. Double-click `login.bat`. It opens a normal Chromium window (with a
   debugging port) at Walmart's sign-in page.
3. Sign in to Walmart in that window (handle any "Robot or human?" check).
   Go to walmart.com/orders and confirm you see your orders.
4. **Leave that browser window OPEN.** Then run `run_pilot.bat` / `run_all.bat`.
   Verify the connection any time with `python walmart_receipts.py --login`.

## Recommended workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `login.bat` | Manual sign-in, saved in local browser profile |
| 2 | `python walmart_receipts.py --diagnose` | Inspects one purchase per section; writes Diagnostics |
| 3 | `run_pilot.bat` | 5 newest Online + 3 newest In-store; then **stops** |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `run_all.bat` | Full history (asks for `YES` confirmation) |
| any time | `resume.bat` | Continue after an interruption — never restarts finished work |
| any time | `verify_receipts.bat` | Re-validate every indexed PDF |
| any time | `review_names.bat` | Fix low-confidence filenames interactively |

## All command-line options

```
python walmart_receipts.py --login | --discover | --pilot | --pilot-online |
    --pilot-instore | --online | --instore | --all | --resume | --verify |
    --review-names | --diagnose | --dry-run
Filters:  --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
          --max-purchases N  --order-number N  --include-invoices  --yes
```

## Output layout

```
C:\Users\YOU\Downloads\Walmart Receipts\
  Online\            receipts from Online orders
  In-Store\          receipts from in-store transactions
  Invoices\          invoices (only with --include-invoices)
  Manual Review\     PDFs that failed validation
  Logs\  Diagnostics\  Backups\
  Walmart Order History.csv    Walmart Receipt Index.csv
  progress.json  discovery.json  run-summary.txt
```

Filenames: `YYYY-MM-DD Walmart <Purchase Summary> Receipt.pdf`
(e.g. `2024-12-31 Walmart Groceries Receipt.pdf`). Collisions get ` (2)`,
` (3)`… — an existing PDF is **never overwritten**.

## Classification

`category_rules.json` holds editable keyword → category rules. Classification
is deterministic and fully local. Low-confidence purchases are saved anyway,
marked *Review Needed*, and can be renamed with `review_names.bat`.

## When Walmart changes its website

All Walmart selectors and page behavior live in **`walmart_site.py`** only.
Run `python walmart_receipts.py --diagnose` to capture what the page looks
like now (Diagnostics folder), then adjust `walmart_site.py`.

## Safety

- Read-only on Walmart: never orders, returns, cancels, reviews, or changes
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
