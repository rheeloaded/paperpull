# eBay Receipts Downloader (local, supervised)

Downloads your eBay purchase history and saves each order's
**order-details page** as a one-page PDF receipt, plus two CSV files

- `eBay Order History.csv`, one row per purchased item
- `eBay Receipt Index.csv`, one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to eBay **manually**. The tool never
touches your credentials and never bypasses CAPTCHAs or OTP.

## What eBay keeps, and how far back this goes

eBay's purchase history is filtered by year. The "All" choice on the site
is not all of it, it is this year and the three before it. The filter is a
plain URL parameter with its own vocabulary (this year, last year, two
years ago and so on, out to ten years ago), so discovery walks one year at
a time from this year backward and stops after two empty years in a row.
That reached 2017 on the account it was built against. Orders older than
ten years are not reachable through the filter.

To narrow what gets downloaded, set `default_start_date` in `config.json`
(for example `"2025-01-01"`) or pass `--start-date 2025-01-01` or
`--year 2026` on the command line.

## How it connects (important)

This tool does **not** drive a scripted sign-in. `login.bat` opens your
installed **Microsoft Edge** (or Chrome, or the bundled Chromium when
neither is installed) with debugging port **9262** and a profile folder of
its own. **You** sign in. The tool then connects to that already-signed-in
browser and reads the pages you are authorized to see. No stealth, no
evasion, a real person signs in to a real browser.

**The signed-in browser window must stay OPEN while the tool runs.**

Port 9262 keeps this separate from the other PaperPull apps, so several
signed-in browsers can be open at once.

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf, downloads Chromium |
| 2 | `login.bat` | Opens the browser. Sign in, open Purchase History, **leave it open** |
| 3 | `paperpull ebay pilot` | Newest five orders, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `paperpull ebay all` | Your entire purchase history (asks for `yes`) |
| any time | `paperpull ebay resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull ebay verify` | Re-validate every indexed PDF |
| any time | `paperpull ebay review-names` | Fix low-confidence filenames interactively |

Useful for splitting a run

```
python ebay_receipts.py --all --year 2024
python ebay_receipts.py --all --start-date 2026-01-01 --max-purchases 100
```

## How receipts are captured

The signed-in order-details page **is** the receipt. eBay has no separate
invoice, and its "Printer friendly page" button did nothing under
automation. The tool opens `order.ebay.com/ord/show?orderId=...`, waits for
the order to fill in, hides everything outside the details block (Order
info, Delivery info, Item info, shipping address, Payment info), scales the
fixed-width desktop layout to the printable width so the amounts column is
not cut off, and renders the result with Chromium's `printToPDF`. Hiding
and scaling are display-only changes in the local page. Nothing is
submitted to eBay, no buttons are clicked, and the native print dialog is
never involved. Files land in `Online\` as
`YYYY-MM-DD eBay <Category> Receipt.pdf`.

The receipt shows the payment method with the email masked, the item total,
shipping, tax and the order total, the seller, and the shipping address.

For some orders from 2019 and before, eBay's own details page answers
"Order not found" every time. The purchase history still lists them,
so the app prints that order's history card instead (date, item, total,
seller, status, order number) as `YYYY-MM-DD eBay <Category> Order
Summary.pdf`. There is no tax or shipping breakdown for those, eBay no
longer has it.

Canceled orders are recorded in the CSVs with no PDF (nothing to print).

## eBay's daily limit

eBay allows one account a few hundred order-details pages a day. Past
that, every details page says "You've exceeded the number of requests
allowed in one day" until the next day. The app recognizes that page,
stops with its progress saved, and says so in the run summary. Run
`paperpull ebay resume` the next day and it continues from the order it
stopped at. A history of a couple hundred orders may take two days the
first time. After that a run only opens what is new.

## When eBay changes its website

All eBay selectors/URLs live in **`ebay_site.py`** only. Run
`python ebay_receipts.py --diagnose` to capture the current page structure
into `Diagnostics\`, then repair that one file.

## Safety

- Read-only on eBay. Never bids, buys, pays, returns, cancels, leaves
  feedback, contacts a seller, or changes account settings. Forbidden
  controls are blocked by an explicit regex, and nothing is clicked at all.
- Stops and hands control to you on CAPTCHA/OTP, sign-out, or rate limiting.
- Sequential processing with polite randomized delays.
- Progress written atomically after every order. CSV/JSON backed up before
  rewrites. Interrupted runs continue with `paperpull ebay resume`.
- Existing PDFs are never overwritten (collisions get ` (2)`, ` (3)`, …).

## Tests

```
.venv\Scripts\activate
pytest
```
