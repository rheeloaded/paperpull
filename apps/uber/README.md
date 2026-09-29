# Uber Receipts Downloader (local, supervised)

Saves a PDF receipt for every Uber ride and every Uber Eats order you paid
for, plus two CSV files

- `Uber Order History.csv`, one row per purchased item
- `Uber Receipt Index.csv`, one row per downloaded PDF

**Rides** are every trip on riders.uber.com, saved into `Rides\`. **Uber
Eats** is every food or grocery order on ubereats.com, saved into `Uber
Eats\`. Each receipt is Uber's own PDF, the same file its Download PDF link
gives you. A trip canceled before anything was charged, or an order that
cost nothing, has no receipt and is skipped.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Uber **manually**. The tool never
touches your credentials and never bypasses a check or a code.

## Two sign-ins

Uber keeps these two behind two separate sign-ins, even in one browser.

- **Your trips**, at riders.uber.com, is where the rides are. `login.bat`
  opens it.
- **Uber Eats**, at ubereats.com/orders, is where the orders are. Open it
  in a second tab of the same window and sign in there too.

If either one asks you to sign in again partway through a run, the tool
says which, stops that side, keeps everything it already read, and leaves
the tab open for you to sign in. The run is reported as stopped, and
Resume carries on.

After an hour or two with nothing asked, Uber stops answering the trips
page's own calls while you are still signed in, and loading the page again
brings them back without a sign-in. The tool does exactly that, once, before
it decides a side is signed out.

## What it keeps

A ride is named for where it went, as your trip list shows it,
`2026-06-15 Uber Ride to Union Station Receipt.pdf`. An Uber Eats order is
named for its store, `2026-04-18 Uber Eats Corner Deli Receipt.pdf`. Uber
names both, so there is nothing to guess and nothing for
`review_names.bat` to fix, although it is there if you want other names.

Uber's website only goes back so far. On the account this was built on
the trip list reached back about ten months and the Eats orders about two
years, and Uber answered nothing for anything earlier. Whatever Uber still
shows, this tool saves.

To narrow what gets downloaded, set `default_start_date` in `config.json`
or pass `--start-date 2025-01-01` or `--year 2026`. The lists stop once
they are past that date.

## How it connects (important)

`login.bat` opens your installed **Microsoft Edge** (or Chrome) with
debugging port **9281** and a profile folder of its own. **You** sign in.
The tool then connects to that browser and reads the pages you are
allowed to see. No stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv` and installs Playwright and pypdf |
| 2 | `login.bat` | Opens the browser. Sign in to your trips, and to Uber Eats in a second tab, **leave it open** |
| 3 | `paperpull uber pilot` | The newest three ride receipts and three Uber Eats receipts, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `paperpull uber all` | Your entire receipt history (asks for `yes`) |
| any time | `paperpull uber resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull uber verify` | Re-validate every indexed PDF |

`uber_receipts.py --rides` and `--eats` run one side only.

## How receipts are captured

Both sites answer their own pages from APIs on their own hosts, and the
tool asks them the same questions from inside the signed-in page, the way
the page asks them, pausing between calls.

**Rides.** The trip list, twenty trips at a time, then each paid trip's
details for the day it was taken, since the list writes no year. For the
receipt it asks what the page's receipt window asks, which says when the
newest receipt was made, then fetches the PDF that receipt's Download PDF
link points at.

**Uber Eats.** The order list, ten orders at a time, the next ten asked for
the way the page's Show more asks. For the receipt it asks what the page's
View receipt asks, then fetches the PDF its Download PDF link points at.

Either way the PDF is read back before it is filed. Every ride receipt
prints its trip's receipt ID, and so do Uber Eats receipts from December
2025 on, and a receipt that does not carry its own is destroyed rather than
saved under the purchase's name. An older Uber Eats receipt prints no ID,
so it is checked for its own date and total instead.

## Safety

- Read-only on Uber. Nothing is pressed on either site, and never Resend
  Receipt, which would email you, or a rating, tip, help, reorder, report
  or expense control.
- On riders.uber.com it makes three queries only, the trip list, a trip's
  details and a trip's receipt, and a mutation is refused before anything
  is sent. On Uber Eats it makes two calls only, the order list and an
  order's receipt.
- Every address it opens is checked against Uber's own two hosts,
  riders.uber.com and www.ubereats.com, and nothing wider.
- A failed call is answered, never retried in a loop.
- Progress written atomically after every purchase. Interrupted runs
  continue with `paperpull uber resume`.
- Existing PDFs are never overwritten.

## Tests

```
.venv\Scripts\activate
pytest
```

Every trip, order, store, name and amount in the tests is invented.
