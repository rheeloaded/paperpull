# Lowe's Receipts Downloader (local, supervised)

Downloads your Lowe's purchase history, store purchases and online orders
alike, and saves each purchase's **details page** as a PDF receipt, plus two
CSV files

- `Lowe's Order History.csv`, one row per purchased item
- `Lowe's Receipt Index.csv`, one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Lowe's **manually**. The tool never
touches your credentials and never bypasses a check or a code.

## What Lowe's keeps, and how far back this goes

MyLowe's, Purchase History lists online orders and store purchases
together, five to a page. A store purchase shows up when it was made with
your MyLowe's card or phone number at the register. Lowe's says the
history holds orders placed after 2021, and on the account this was built
on it reached back to January 2023.

The whole history is read page by page by its own address, with the range
set to All, so nothing on the page is pressed. To narrow what gets
downloaded, set `default_start_date` in `config.json` (for example
`"2025-01-01"`) or pass `--start-date 2025-01-01` or `--year 2026`.

## How it connects (important)

This tool does **not** drive a scripted sign-in. `login.bat` opens your
installed **Microsoft Edge** (or Chrome) with debugging port **9271** and a
profile folder of its own. **You** sign in. The tool then connects to that
already-signed-in browser and reads the pages you are allowed to see. Lowe's
sits behind bot protection, which is why it is your own browser, and no
stealth or evasion is used.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv` and installs Playwright and pypdf |
| 2 | `login.bat` | Opens the browser. Sign in, open Purchase History, **leave it open** |
| 3 | `paperpull lowes pilot` | The newest three store purchases and three online orders, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `paperpull lowes all` | Your entire purchase history (asks for `yes`) |
| any time | `paperpull lowes resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull lowes verify` | Re-validate every indexed PDF |
| any time | `paperpull lowes review-names` | Fix low-confidence filenames interactively |

## How receipts are captured

A purchase's details page **is** its receipt. It shows the store's name and
address or the delivery address, each item with its item and model numbers,
price, quantity and any discount, the payment method's last four digits,
and the subtotal, tax and total billed. The tool opens the page by the
purchase's own id, checks that the page's heading names this purchase and
refuses it if not, hides everything outside the receipt block, and renders
the result with Chromium's `printToPDF`. Hiding is a display-only change in
the local page. **Print Details is never pressed**, since it opens the print
dialog and its print copy leaves out the card.

Files land in `In-Store\` or `Online\` as
`YYYY-MM-DD Lowe's <Category> Receipt.pdf`. A return has a details page of
its own and is saved as `... Return.pdf`. A canceled order is recorded in
the CSVs with no PDF. The categories are home-improvement ones, Plumbing
Supplies, Paint Supplies, Hardware, Heating and Cooling and so on, and they
live in `category_rules.json`, which you can edit.

## When Lowe's changes its website

All Lowe's selectors and addresses live in **`lowes_site.py`** only. Run
`paperpull lowes diagnose` to capture the current page structure into
`Diagnostics\`, then repair that one file.

## Safety

- Read-only on Lowe's. Never buys, reorders, returns, cancels, changes an
  order, writes a review, or changes account settings. Forbidden controls
  are blocked by an explicit list, and nothing is clicked at all.
- Stops and hands control to you on a check, a code, sign-out, or rate
  limiting.
- Sequential processing with polite randomized delays.
- Progress written atomically after every purchase. CSV and JSON backed up
  before rewrites. Interrupted runs continue with `paperpull lowes resume`.
- Existing PDFs are never overwritten. Two receipts that would share a name
  are told apart by their purchase numbers.

## Tests

```
.venv\Scripts\activate
pytest
```
