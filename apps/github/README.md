# GitHub Receipts Downloader (local, supervised)

**Working, confirmed on a real account.** This app was built against a
GitHub account that has never paid GitHub anything, so the shape of a
payment row came from GitHub's own documentation, and a tester with
payments then ran it. His survey read twenty-three rows and his Pilot
saved five receipts. Two receipts bought on one day used to write one
filename, since a payment row says nothing about what was bought, and
GitHub's own payment id is in the name now. The conversation is
[issue #43](https://github.com/rheeloaded/paperpull/issues/43).

Downloads the receipts from your GitHub **Payment history** (Pro, Team,
Copilot, Codespaces, Actions, storage, Sponsors payments, anything GitHub
charged you for) as PDFs, plus two CSV files:

- `GitHub Order History.csv`, one row per payment
- `GitHub Receipt Index.csv`, one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to GitHub **manually**. The tool never
touches your credentials, your tokens or your keys, and never bypasses
two-factor prompts.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **GitHub**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in to github.com yourself, answer any code or passkey prompt, and
   leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   Payment history page, follows the first receipt link it finds, and
   writes `Diagnostics\diagnose-github.json` in the GitHub folder. It
   downloads nothing to keep, clicks nothing, takes no screenshot, and
   masks every number of two digits or more, every email address and
   every @handle.
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
   the rows the app would take, and whether the receipt link gave a PDF
   or a page. If anything in it looks personal, delete that line.
7. Attach both files to [issue #43](https://github.com/rheeloaded/paperpull/issues/43)
   with a sentence about what a receipt looks like to you.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Online\`, then attach a fresh Diagnose file.

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
installed **Microsoft Edge** (or Chrome) with debugging port **9264** and
a profile folder of its own, so passkeys and password managers work the
way they do in your own browser. **You** sign in. The tool then connects
to that already-signed-in browser and reads the pages you are authorized
to see.

**The signed-in browser window must stay OPEN while the tool runs.**

## Setup / workflow

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `setup.bat` | Creates `.venv`, installs Playwright + pypdf |
| 2 | `login.bat` | Opens the browser. Sign in, open Payment history, **leave it open** |
| 3 | `paperpull github diagnose` | The survey, for the maintainer |
| 4 | `paperpull github pilot` | Newest five payments, then **stops** for your inspection |
| 5 | inspect the PDFs/CSVs | You approve before anything bigger runs |
| 6 | `paperpull github all` | Your entire payment history (asks for `yes`) |
| any time | `paperpull github resume` | Continue after an interruption. Never redoes finished work |
| any time | `paperpull github verify` | Re-validate every indexed PDF |

## How it is meant to work

- **Discovery reads the Payment history page**, `github.com/account/billing/history`,
  then `?page=2` and on until a page adds nothing new. Each row with an
  amount becomes one payment, with its date, its description and the
  links on it. A payment keeps its identity by the id in its receipt
  link, or by a short hash of the row when the link has none.
- **The receipt link is the document.** GitHub's documentation says each
  row has a view icon and a download icon under "Receipt" (and "Invoice"
  where there is one). The app fetches the download link from inside the
  signed-in page. If the answer is a PDF, that is the file. If the link
  opens a receipt page, the app opens it, hides everything outside the
  receipt block, and renders it with Chromium's `printToPDF`. Nothing is
  submitted, no button is pressed, and the native print dialog is never
  involved. Files land in `Online\` as
  `YYYY-MM-DD GitHub <Category> Receipt.pdf`.

## When GitHub changes its website

All GitHub selectors/URLs live in **`github_site.py`** only. Run
`python github_receipts.py --diagnose` to capture the current page
structure into `Diagnostics\`, then repair that one file.

## Safety

- Read-only on GitHub. Never pays, changes a plan, touches the card on
  file, a budget, a token, a key or a setting. Forbidden controls are
  blocked by an explicit regex, and nothing is clicked at all. Only a
  receipt's own link address is followed, and only on github.com.
- Stops and hands control to you on a verification prompt, sign-out, or
  rate limiting.
- Sequential processing with polite randomized delays.
- Progress written atomically after every payment. CSV/JSON backed up
  before rewrites. Interrupted runs continue with `paperpull github resume`.
- Existing PDFs are never overwritten (collisions get ` (2)`, ` (3)`, …).

## Tests

```
.venv\Scripts\activate
pytest
```
