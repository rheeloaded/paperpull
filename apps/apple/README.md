# Apple Receipts Downloader (local, supervised)

Saves a PDF receipt for everything you paid Apple for, from both of the
places Apple sells, plus two CSV files

- `Apple Order History.csv`, one row per purchased item
- `Apple Receipt Index.csv`, one row per downloaded PDF

**App Store** is subscriptions, Apple One and iCloud+ among them, in-app
purchases and paid apps, for everybody in your Family Sharing group. Each
receipt is Apple's own emailed receipt, saved as a PDF into `App Store\`.
Free downloads have no receipt and are skipped.

**Apple Store** is hardware you ordered from apple.com, shipped or picked
up. Each order's invoice is saved as a PDF into `Apple Store\`, and a
canceled order is recorded as canceled with no receipt.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Apple **manually**. The tool never
touches your credentials and never bypasses a check or a code.

## Two sign-ins

Apple keeps these two behind two separate sign-ins, even in one browser.

- **Report a Problem**, at reportaproblem.apple.com, is where the App
  Store purchases are. `login.bat` opens it.
- **The Apple Store order list**, at apple.com/shop/order/list, is where
  the hardware orders are. Open it in a second tab of the same window and
  sign in there too.

If either one asks you to sign in again partway through a run, the tool
says which, stops that side, keeps everything it already read, and leaves
the tab open for you to sign in. The run is reported as stopped, and
Resume carries on.

## What it keeps

An account without Family Sharing is read too. Its family list names
nobody, so the tool asks, the way the page itself does on every load,
which account is signed in, and searches that one account's purchases
(#55).

On the account this was built on, roughly four purchases in five were
free app downloads, with no receipt to save. Only purchases where money
was spent are kept, a purchase Apple has not charged yet is left for the
next run, and a purchase made on a child's account says whose it was, in
the Notes column and in the record.

An App Store receipt is named for what was bought, the app or the
service, as Apple names it, `2026-05-14 Apple Apple One Receipt.pdf`. An
Apple Store invoice is named for its main product, from the editable
`category_rules.json`. Anything it is unsure of is left for
`review_names.bat`.

To narrow what gets downloaded, set `default_start_date` in `config.json`
or pass `--start-date 2024-01-01` or `--year 2025`. The App Store search
stops once it is past that date.

## How it connects (important)

`login.bat` opens your installed **Microsoft Edge** (or Chrome) with
debugging port **9280** and a profile folder of its own. **You** sign in.
The tool then connects to that browser and reads the pages you are
allowed to see. No stealth, no evasion.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv` and installs Playwright and pypdf |
| 2 | `login.bat` | Opens the browser. Sign in to Report a Problem, and to the Apple Store in a second tab, **leave it open** |
| 3 | `paperpull apple pilot` | The newest three App Store receipts and two Apple Store invoices, then **stops** for your inspection |
| 4 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 5 | `paperpull apple all` | Your entire purchase history (asks for `yes`) |
| any time | `paperpull apple resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull apple verify` | Re-validate every indexed PDF |

`apple_receipts.py --app-store` and `--apple-store` run one side only.

## How receipts are captured

**App Store.** Report a Problem answers its own page from an API on its
own site, and the tool asks it the same questions from inside the signed-in
page, the way the page asks them. It reads the family's members, then the
purchase search for all of them together, fifteen purchases at a time,
pausing between batches. For each paid purchase it asks for the receipt
the page's own View Receipt shows, which is Apple's emailed receipt as
HTML, and draws it in a blank tab of the same browser to print it.

**Apple Store.** The order list and each order's details page carry their
data in the page itself, so each is opened and read, one at a time. The
invoice opens in a new tab, its Print button is hidden for the PDF, and
the page is printed with Chromium's `printToPDF`.

Either way the PDF is read back before it is filed, and a receipt that
does not carry its own order number is destroyed rather than saved under
the purchase's name.

## Receipts Apple will not give

On the account this was built on, Report a Problem would not give the
receipt of any purchase from 2004 to September 2016, or of one from 2021.
It answered each with its own internal error, and its own page cannot show
those receipts either. A receipt Apple refuses while you are signed in is
not taken for a sign-in, so the run carries on, and the purchase is asked
again on later runs.

Once Apple has refused a purchase's receipt on three separate runs, the
tool saves a purchase record in its place,
`2015-03-01 Apple Minecraft Purchase Record.pdf`. It is made from Apple's
own purchase history, says at the top that it is not Apple's receipt, and
carries the order ID, the date, who bought it, the total and each item
with what was paid. It is checked for its own order ID like a receipt,
and the purchase is then done and not asked again. `--redownload` asks
Apple for the receipt once more.

Where Apple's refusals start differs by account. A tester's ended in May
2015, and another's covers anything older than eighteen months (#55).
Purchases are asked newest first, and once Apple has refused ten of an
account's purchases in a row, each older than any receipt it has given that
account, the older ones are not asked for the rest of the run, but for one
a year until Apple refuses it. Each counts as refused on that run, so a
purchase record still waits for three separate runs, and the run that would
make a purchase's record asks it, so every record rests on Apple refusing
that receipt itself. The record says how many runs did not ask. If Apple
gives one of the receipts it is still asked for, older purchases are asked
again, and `--redownload` asks every purchase.

## What is not covered yet

- **Older Apple Store orders.** The order list says when older orders
  exist, but how it pages was never seen, the account this was built on
  has three orders. When Apple says there are more, the run says so and
  leaves them unread rather than guessing.
- **Refunds.** A refunded App Store purchase is not saved as a document of
  its own.

## Safety

- Read-only on Apple. Nothing is pressed on either site, not View
  Receipt, not Print, and never a cancel, return, refund, report or edit
  control.
- On Report a Problem it reads three endpoints only, the family list, the
  purchase search and a purchase's receipt. The report, refund, concern
  and trust and safety endpoints the page can reach are refused by an
  allowlist before any call is made.
- Every address it opens is checked against Apple's own hosts,
  reportaproblem.apple.com, www.apple.com, store.apple.com and the store's
  numbered secure host, and nothing wider.
- A failed call is answered, never retried in a loop.
- Progress written atomically after every purchase. Interrupted runs
  continue with `paperpull apple resume`.
- Existing PDFs are never overwritten.

## Tests

```
.venv\Scripts\activate
pytest
```

Every order, name, email and amount in the tests is invented.
