# Gap Receipts Downloader (local, supervised)

Downloads your Gap Inc. order history and saves each order's **order-details
receipt** as a PDF, plus two CSV files:

- `Gap Order History.csv` — one row per purchased item
- `Gap Receipt Index.csv` — one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Gap **manually**; the tool never
touches your credentials and never bypasses CAPTCHAs or OTP.

## One login, every Gap Inc. brand

A single Gap account covers **Gap, Old Navy, Banana Republic, Athleta and
Gap Factory**, and one order history holds orders from all of them. The
brand is recorded per order where Gap makes it identifiable.

## Date range: what Gap still shows

Gap's order history is **not** year-paginated: everything the account still
exposes — roughly the **last 13 months** — lazy-loads onto one page as you
scroll, and discovery scrolls until Gap stops adding orders. Older orders
are simply gone from the site and cannot be downloaded. To narrow what gets
downloaded, set `default_start_date` in `config.json` (e.g. `"2025-01-01"`)
or pass `--start-date 2025-01-01` / `--year 2026` on the command line.

## How it connects (important)

This tool does **not** drive a scripted sign-in. `login.bat` opens an
ordinary Chromium (debugging port **9233**) that **you** sign into; the tool
then connects to that already-signed-in browser and reads the pages you're
authorized to see. No stealth, no evasion — a real human signs in to a real
browser.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9233 keeps this separate from the Walmart project (9222), so both
signed-in browsers can be open at once.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens Chromium; sign in, open Order History, **leave it open** |
| 3 | `run_pilot.bat` | 5 newest orders, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `run_all.bat` | Your entire order history (asks for `yes`) |
| any time | `resume.bat` | Continue after an interruption; never redoes finished work |
| any time | `verify_receipts.bat` | Re-validate every indexed PDF |
| any time | `review_names.bat` | Fix low-confidence filenames interactively |

Useful for splitting a run:

```
python gap_receipts.py --all --year 2026
python gap_receipts.py --all --start-date 2026-01-01 --max-purchases 100
```

## How receipts are captured

The signed-in order-details page **is** the receipt (Gap has no separate
printable invoice). The tool navigates to `/my-account/order-details/<id>`,
waits for the page to finish loading its data, hides everything except the
purchase-summary block, and renders that with Chromium's `printToPDF` — a
clean one-page receipt instead of three pages of site navigation. Hiding is a
display-only change in the local page; nothing is submitted to Gap. No
buttons are clicked and the native print dialog is never involved. Files land
in `Online\` as `YYYY-MM-DD Gap <Category> Receipt.pdf`.

Canceled orders are recorded in the CSVs with no PDF (nothing to print).

## When Gap changes its website

All Gap selectors/URLs live in **`gap_site.py`** only. Run
`python gap_receipts.py --diagnose` to capture the current page structure
into `Diagnostics\`, then repair that one file.

## Safety

- Read-only on Gap: never reorders, returns, cancels, reviews, or changes
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
