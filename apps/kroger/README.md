# Kroger Receipts Downloader (local, supervised)

**Not yet tested against an account with purchases.** This app was built
against a Kroger account that had signed in but never bought anything, so
the sign-in, the purchase-history page and its API were mapped for real
and the receipt page was found, but no receipt has been rendered yet. What
a real receipt looks like is marked GUESS in `kroger_site.py`. What it
needs is a Diagnose file from an account with purchases, which contains no
personal data. The conversation is
[issue #41](https://github.com/rheeloaded/paperpull/issues/41).

Downloads your Kroger purchase history and saves each purchase's receipt
as a PDF, plus two CSV files:

- `Kroger Order History.csv`, one row per purchased item
- `Kroger Receipt Index.csv`, one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Kroger **manually**. The tool never
touches your credentials and never bypasses CAPTCHAs or OTP.

## Every Kroger banner, one sign-in

One Kroger account covers Kroger, Pick 'n Save, Metro Market, Fred Meyer,
Ralphs, King Soopers, Fry's, Smith's, QFC, Dillons, Harris Teeter and the
rest of the family. Sign in at kroger.com and the purchase history there
shows purchases from all of them. Which banner a purchase came from is
recorded where the site says.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Kroger**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in to kroger.com yourself, answer any code it sends, and leave the
   window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   purchase-history page the way the page reads itself, opens your newest
   receipt page, and writes `Diagnostics\diagnose-kroger.json` in the
   Kroger folder. It downloads nothing, clicks nothing, takes no
   screenshot, and masks every number of two digits or more and every
   email address.
5. Click **Record**, in the same **more** menu. Go back to the browser window
   and click your way to one document the way you normally would, then come
   back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough, written
   for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold the
   shape of the purchase list (field names, purchase types, statuses,
   masked values), the lines of one receipt with the numbers masked, and
   the names of the buttons on that page. If anything in it looks
   personal, delete that line.
7. Attach both files to [issue #41](https://github.com/rheeloaded/paperpull/issues/41)
   with a sentence about what the receipt page looks like to you.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `In-Store\` and `Online\`, then attach a fresh Diagnose file.

A Diagnose file and one recording together are usually enough to get a
provider working in a single round. Diagnose on its own takes two or three.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. Attach it to the issue the same
way. It is what keeps the rounds after the first one short, and it is
described in full on the
[Testing a provider](../../docs/testing-a-provider.md#if-a-run-fails-send-the-file-it-wrote)
page.

## In-store, fuel, pickup and delivery

Kroger's history mixes them. In-store and fuel-center purchases go to
`In-Store\`. Pickup, delivery and ship-to-home orders go to `Online\`.
Run one kind on its own with `--instore` or `--online`. An order that is
still pending has no receipt yet. It is recorded and looked at again on
the next run.

## How it connects (important)

This tool does **not** drive a scripted sign-in. `login.bat` opens your
installed **Microsoft Edge** (or Chrome) with debugging port **9263** and
a profile folder of its own. **You** sign in. The tool then connects to
that already-signed-in browser and reads the pages you are authorized to
see. Kroger.com runs Akamai bot protection, which is why the browser
already on your machine is used and not the bundled one.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf |
| 2 | `login.bat` | Opens the browser. Sign in, open Purchase History, **leave it open** |
| 3 | `paperpull kroger diagnose` | The survey, for the maintainer |
| 4 | `paperpull kroger pilot` | Newest few of each kind, then **stops** for your inspection |
| 5 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 6 | `paperpull kroger all` | Your entire purchase history (asks for `yes`) |
| any time | `paperpull kroger resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull kroger verify` | Re-validate every indexed PDF |
| any time | `paperpull kroger review-names` | Fix low-confidence filenames interactively |

## How it is meant to work

- **Discovery reads the page's own API.** When the purchase-history page
  opens it asks `/atlas/v1/post-order/v1/purchase-history-search` for its
  list. The app makes the same call from inside the signed-in page, with
  the same header, a page at a time until the API says it is the last one.
  Verified against the live site with an empty account.
- **The receipt page is the receipt.** Each finished purchase has a page
  at `/mypurchases/image/<receipt key>` that renders the receipt into a
  print area 635px wide, with a Print button of its own. The app opens
  that page by URL, hides everything outside the print area (the Print
  button included, never pressed), and renders it with Chromium's
  `printToPDF`. Hiding is a display-only change in the local page. Nothing
  is submitted to Kroger, no buttons are clicked, and the native print
  dialog is never involved. Files land in `In-Store\` or `Online\` as
  `YYYY-MM-DD Kroger <Category> Receipt.pdf`.
- **Line items** come from the API record (UPC and quantity, with the
  product name where the record carries one) and from the rendered
  receipt's lines where they can be read. The receipt's line shape is the
  main thing the first Diagnose file will settle.

## When Kroger changes its website

All Kroger selectors/URLs live in **`kroger_site.py`** only. Run
`python kroger_receipts.py --diagnose` to capture the current page
structure into `Diagnostics\`, then repair that one file.

## Safety

- Read-only on Kroger. Never adds to a cart, reorders, clips a coupon,
  requests a refund, changes a tip, or changes account settings. Forbidden
  controls are blocked by an explicit regex, and nothing is clicked at all.
- Stops and hands control to you on CAPTCHA/OTP, sign-out, or rate limiting.
- Sequential processing with polite randomized delays.
- Progress written atomically after every purchase. CSV/JSON backed up
  before rewrites. Interrupted runs continue with `paperpull kroger resume`.
- Existing PDFs are never overwritten (collisions get ` (2)`, ` (3)`, …).

## Tests

```
.venv\Scripts\activate
pytest
```
