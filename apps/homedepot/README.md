# Home Depot Receipts Downloader (local, supervised)

Downloads your Home Depot purchase history and saves each order's receipt,
**Home Depot's own print receipt**, as a one-page PDF, plus two CSV files

- `Home Depot Order History.csv`, one row per purchased item
- `Home Depot Receipt Index.csv`, one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Home Depot **manually**. The tool never
touches your credentials and never bypasses a check or a code.

## What Home Depot keeps, and how far back this goes

**Home Depot keeps the last two years of orders online, and no more.** Its
purchase history refuses any request that reaches further back. So run this
every few months, and each run takes what is new before it ages out. Your
archive keeps everything it has ever saved, however old.

Online orders are there. A store purchase shows up when the history lists
it, and the account this was built on had none, so store purchases are
handled the same way but have not been seen yet.

To narrow what gets downloaded, set `default_start_date` in `config.json`
or pass `--start-date 2026-01-01` or `--year 2026`.

## How it connects (important)

This tool does **not** drive a scripted sign-in. `login.bat` opens your
installed **Microsoft Edge** (or Chrome) with debugging port **9272** and a
profile folder of its own. **You** sign in. The tool then connects to that
already-signed-in browser and reads the pages you are allowed to see. No
stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv` and installs Playwright and pypdf |
| 2 | `login.bat` | Opens the browser. Sign in, open Purchase History, **leave it open** |
| 3 | `paperpull homedepot pilot` | The newest three orders, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `paperpull homedepot all` | Everything Home Depot still has (asks for `yes`) |
| any time | `paperpull homedepot resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull homedepot verify` | Re-validate every indexed PDF |

## How receipts are captured

The purchase history page asks Home Depot for your orders with one request.
The tool takes that request as the page made it and asks it again from
inside the page, a page of results at a time, so the list is Home Depot's
own. Nothing is pressed.

Each order's details page already carries its printable receipt, hidden on
screen and shown only when printing: the order number and date, each item
with its model and store SKU numbers, the billing address, the card's last
four digits and the payment breakdown. **"View Receipt" is never pressed**,
because all it does is open the browser's print dialog, which blocks the
window until someone closes it. The tool switches the page to its print
layout instead, keeps only the receipt, checks it names this order, and
saves it with Chromium's `printToPDF`.

Files land in `Online\` (or `In-Store\`) as
`YYYY-MM-DD Home Depot <Category> Receipt.pdf`. A canceled order is recorded
in the CSVs with no PDF. A returned order keeps its receipt, which shows
the refund.

## When Home Depot changes its website

All Home Depot addresses and page behavior live in **`homedepot_site.py`**
only. Run `paperpull homedepot diagnose` to capture the current structure
into `Diagnostics\`, then repair that one file.

## Safety

- Read-only on Home Depot. Never buys, reorders, returns, cancels, pays,
  applies for credit, or changes account settings. Forbidden controls are
  blocked by an explicit list, and nothing is clicked at all.
- The one request it repeats is the history page's own, at its own address,
  checked against Home Depot's host.
- Stops and hands control to you on a check, a code, sign-out, or rate
  limiting.
- Progress written atomically after every order. Interrupted runs continue
  with `paperpull homedepot resume`.
- Existing PDFs are never overwritten.

## Tests

```
.venv\Scripts\activate
pytest
```
