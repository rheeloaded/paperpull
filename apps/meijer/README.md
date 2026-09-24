# Meijer Receipts Downloader (local, supervised)

**Not yet tested against a real account.** This app was built without a
Meijer account, from the orders page the requester named, so that someone
who holds one can test it without writing code. It runs, its guards are
tested, and every guess about meijer.com is marked in `meijer_site.py`.
What it needs is a Diagnose file from a signed-in account, which contains
no personal data. The conversation is
[issue #42](https://github.com/rheeloaded/paperpull/issues/42).

Downloads your Meijer orders and receipts as PDFs, plus two CSV files:

- `Meijer Order History.csv`, one row per order
- `Meijer Receipt Index.csv`, one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Meijer **manually**. The tool never
touches your credentials and never bypasses CAPTCHAs or OTP.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Meijer**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in to meijer.com yourself, answer any code it sends, and leave the
   window open.
4. Click **more** under the buttons, then **Diagnose**. It opens the
   orders page (and the places in-store receipts are likely to live),
   follows the first receipt or order-details link it finds, and writes
   `Diagnostics\diagnose-meijer.json` in the Meijer folder. It downloads
   nothing to keep, clicks nothing, takes no screenshot, and masks every
   number of two digits or more and every email address. It also records
   the shape (field names, not values) of the data the page loads.
5. Click **Record**, in the same **more** menu. Go back to the browser window
   and click your way to one document the way you normally would, then come
   back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough, written
   for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold the
   page's words with the numbers masked, every link on it with its kind,
   the rows the app would take, the shape of the page's data, and whether
   the receipt link gave a PDF or a page. If anything in it looks
   personal, delete that line.
7. Attach both files to [issue #42](https://github.com/rheeloaded/paperpull/issues/42)
   with a sentence about what the orders page and a receipt look like to
   you, and whether your in-store purchases show up there or only under
   mPerks.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Online\`, then attach a fresh Diagnose file.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps.

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

## How it connects (important)

This tool does **not** drive a scripted sign-in. `login.bat` opens your
installed **Microsoft Edge** (or Chrome) with debugging port **9266** and
a profile folder of its own. **You** sign in. The tool then connects to
that already-signed-in browser and reads the pages you are authorized to
see. Meijer.com sits behind bot protection, which is why the browser
already on your machine is used and not the bundled one.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf |
| 2 | `login.bat` | Opens the browser. Sign in, open your orders, **leave it open** |
| 3 | `paperpull meijer diagnose` | The survey, for the maintainer |
| 4 | `paperpull meijer pilot` | Newest five orders, then **stops** for your inspection |
| 5 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 6 | `paperpull meijer all` | Your entire order history (asks for `yes`) |
| any time | `paperpull meijer resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull meijer verify` | Re-validate every indexed PDF |

## How it is meant to work

- **Discovery reads the orders page**, `meijer.com/shopping/orders.html`,
  trying the places in-store digital receipts are likely to live after it,
  then `?page=2` and on until a page adds nothing new. Each row with a
  total becomes one order, with its date and the links on it. An order
  keeps its identity by the id in its link, or by a short hash of the row
  when the link has none.
- **The receipt link is the document.** The app fetches the row's receipt
  or order-details link from inside the signed-in page. If the answer is a
  PDF, that is the file. If it is a page, the app opens it, hides
  everything outside the receipt block, and renders it with Chromium's
  `printToPDF`. Nothing is submitted, no button is pressed, and the native
  print dialog is never involved. Files land in `Online\` as
  `YYYY-MM-DD Meijer <Category> Receipt.pdf`.
- **In-store purchases** are the open question. Meijer shows them as
  digital receipts under mPerks when the loyalty account is linked, and
  where that list lives is the first thing the Diagnose file will settle.

## When Meijer changes its website

All Meijer selectors/URLs live in **`meijer_site.py`** only. Run
`python meijer_receipts.py --diagnose` to capture the current page
structure into `Diagnostics\`, then repair that one file.

## Safety

- Read-only on Meijer. Never adds to a cart, reorders, clips a coupon,
  redeems mPerks rewards, refills a prescription, cancels or changes an
  order, or changes account settings. Forbidden controls are blocked by an
  explicit regex, and nothing is clicked at all. Only a receipt's own link
  address is followed, and only on meijer.com.
- Stops and hands control to you on CAPTCHA/OTP, sign-out, or rate limiting.
- Sequential processing with polite randomized delays.
- Progress written atomically after every order. CSV/JSON backed up before
  rewrites. Interrupted runs continue with `paperpull meijer resume`.
- Existing PDFs are never overwritten (collisions get ` (2)`, ` (3)`, …).

## Tests

```
.venv\Scripts\activate
pytest
```
