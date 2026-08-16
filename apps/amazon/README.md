# Amazon Receipts Downloader (local, supervised)

Downloads your Amazon order history and saves each order's **printable order
summary** as a PDF, plus two CSV files:

- `Amazon Order History.csv` — one row per purchased item
- `Amazon Receipt Index.csv` — one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Amazon **manually**; the tool never
touches your credentials and never bypasses CAPTCHAs or OTP.

## Date range: your full history

By default this downloads **every order in your account** — discovery walks
each year newest-first, back to your first order (it stops automatically once it
reaches a year with no orders). To limit how far back it goes, set
`default_start_date` in `config.json` (e.g. `"2024-01-01"`) or pass
`--start-date 2024-01-01` / `--year 2025` on the command line.

## How it connects (important)

Amazon challenges automation-launched browsers, so this tool does **not**
launch its own browser. `login.bat` opens an ordinary Chromium (debugging
port **9223**) that **you** sign into; the tool then connects to that
already-signed-in browser and reads the pages you're authorized to see. No
stealth, no evasion — a real human signs in to a real browser.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9223 keeps this separate from the Walmart project (9222), so both
signed-in browsers can be open at once.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium; sign in, go to Your Orders, **leave it open** |
| 3 | `run_pilot.bat` | 5 newest orders, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `run_all.bat` | Your entire order history (asks for `yes`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_receipts.bat` | Re-validate every indexed PDF |
| any time | `review_names.bat` | Fix low-confidence filenames interactively |

Useful for splitting a large run:

```
python amazon_receipts.py --all --year 2025
python amazon_receipts.py --all --year 2026
python amazon_receipts.py --all --start-date 2024-01-01 --max-purchases 100
```

## How receipts are captured

Amazon exposes a dedicated printable invoice at
`/gp/css/summary/print.html?orderID=<id>`. The tool navigates straight there
and renders it with Chromium's `printToPDF`. No buttons are clicked and the
native print dialog is never involved. Files land in `Online\` as
`YYYY-MM-DD Amazon <Category> Receipt.pdf`.

Canceled orders are recorded in the CSVs with no PDF (nothing to print).

## When Amazon changes its website

All Amazon selectors/URLs live in **`amazon_site.py`** only. Run
`python amazon_receipts.py --diagnose` to capture the current page structure
into `Diagnostics\`, then repair that one file.

## Safety

- Read-only on Amazon: never reorders, returns, cancels, reviews, or changes
  account settings. Forbidden controls are blocked by an explicit regex.
- Stops and hands control to you on CAPTCHA/OTP, sign-out, or rate limiting.
- Sequential processing with polite randomized delays.
- Progress written atomically after every order; CSV/JSON backed up before
  rewrites; interrupted runs continue with `resume.bat`.
- Existing PDFs are never overwritten (collisions get ` (2)`, ` (3)`, …).

## Tests

```
.venv\Scripts\activate
pytest
```
