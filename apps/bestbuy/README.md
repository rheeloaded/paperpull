# Best Buy Receipts Downloader (local, supervised)

Downloads your Best Buy purchase history, online orders, orders placed in a
store and store purchases, and saves each one's **details page** as a PDF
receipt, plus two CSV files

- `Best Buy Order History.csv`, one row per purchased item
- `Best Buy Receipt Index.csv`, one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Best Buy **manually**. The tool never
touches your credentials and never bypasses a check or a code.

## What Best Buy keeps, and how far back this goes

The Purchases page opens on "Past 3 Years" and shows only a few purchases
at a time. Behind it Best Buy answers one request per year, and this tool
asks for every year back from this one until three years in a row are
empty. On the account it was built on that reached 2015, a year the page's
own menu does not offer. A store purchase shows up when your My Best Buy
account was used at the register.

Very old online orders are kept by Best Buy only as a reference, with no
date or total, and their details page no longer opens. They are counted
and skipped, since there is no receipt to save.

To narrow what gets downloaded, set `default_start_date` in `config.json`
or pass `--start-date 2024-01-01` or `--year 2025`.

## Best Buy's bot protection

Best Buy stops answering when too many requests arrive too quickly, and for
a while even its own Purchases page shows nothing. This tool waits between
years and between pages so a normal run stays well clear of that. If it
does happen, the run stops, says so, and keeps its progress. Leave it for
an hour and run it again.

## How it connects (important)

`login.bat` opens your installed **Microsoft Edge** (or Chrome) with
debugging port **9273** and a profile folder of its own. **You** sign in.
The tool then connects to that browser and reads the pages you are allowed
to see. No stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv` and installs Playwright and pypdf |
| 2 | `login.bat` | Opens the browser. Sign in, open Account, Purchases, **leave it open** |
| 3 | `paperpull bestbuy pilot` | The newest three of each kind, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `paperpull bestbuy all` | Your entire purchase history (asks for `yes`) |
| any time | `paperpull bestbuy resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull bestbuy verify` | Re-validate every indexed PDF |

## How receipts are captured

To learn the history the tool chooses one year in the page's range menu,
which makes the page ask Best Buy for that year, and it asks the same
question again from inside the page for every other year. Choosing a year
is only a filter.

A purchase's details page is its receipt: the date, the order number, the
payment, the total and sales tax, and each item with its model, SKU and
quantity, and for a store purchase the store. The tool opens it by its own
address, checks that it names this purchase, keeps only the receipt block,
and saves it with Chromium's `printToPDF`. **"Print Receipt" and "View
Receipt" are never pressed**, one opens the browser's print dialog and the
other only spins.

Files land in `Online\` or `In-Store\` as
`YYYY-MM-DD Best Buy <Category> Receipt.pdf`, and a return, whose total is
negative, as `... Return.pdf`. A feedback survey that sometimes covers the
page is hidden in your local page and never answered.

## Safety

- Read-only on Best Buy. Never buys, reorders, returns, cancels, pays,
  applies for credit, trades in or changes account settings. Nothing is
  clicked but the range menu and a year in it.
- The one request it repeats is the Purchases page's own, at its own
  address, checked against Best Buy's host.
- Stops and hands control to you on a check, a code, sign-out, or rate
  limiting.
- Progress written atomically after every purchase. Interrupted runs
  continue with `paperpull bestbuy resume`.
- Existing PDFs are never overwritten.

## Tests

```
.venv\Scripts\activate
pytest
```
