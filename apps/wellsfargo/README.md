# Wells Fargo statement downloader

**Working on a tester's credit card account.** This app was built
without a Wells Fargo account, so that someone who holds one could test it
without writing code. In v0.52.0 a tester ran it on a real account and it
saved their credit card statements. Checking, savings, mortgage and loan
statements and tax documents have not been run on a real account yet, and
every guess about wellsfargo.com is still marked in `wellsfargo_site.py`.
For those, what it needs is a survey from a signed-in account, which the
support report in Get help produces and which contains no personal data. The
conversation is
[issue #27](https://github.com/rheeloaded/paperpull/issues/27).

Downloads your Wells Fargo **statements and tax documents** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

Credit card statements already download. These steps are for a checking,
savings, mortgage or loan account, or for a tax document.

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **Add a provider** on the Accounts page. The first time you open
   PaperPull it shows its terms and asks which folder your documents go in,
   then shows the same list by itself. Click **Wells Fargo**, then
   **Continue**, then **Set up**. Back on Accounts, click **Wells Fargo** to
   open its page.
3. Click **More**, then **Get help**, and click **Open sign-in window**
   there. Unlike the one on the provider's page, it starts no download once
   you are signed in. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Back in Get help, click **Make the report**. This support report reads
   the documents page and writes `Diagnostics\diagnose-documents.json` in
   the Wells Fargo folder. It downloads nothing, takes no screenshot, and
   writes any word that is not on PaperPull's fixed list as its shape. It
   presses only links and buttons that lead to the documents or show more of
   them, a documents link or "Show more" for instance.
5. Once the report is done, click **Back to Wells Fargo**, then **More**,
   then **Get help** again, and click **Record steps**. Go back to the
   browser window and click your way to one document the way you normally
   would, then come back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough,
   written for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
7. Attach both files to [issue #27](https://github.com/rheeloaded/paperpull/issues/27)
   with a sentence about what the documents page looks like to you.
8. When a new build is posted, click **Try the newest few first** on the
   provider's page and say whether PDFs landed in `Statements\`, then attach
   a fresh support report. If it says to sign in first, sign in from Get
   help as in step 3 and click it again.
   If the run printed any lines that begin with `Waited for`, copy
   those into your comment as well. They say which way of waiting
   each page needed, which is the thing the next build keeps.

A support report and one recording together are usually enough to get a
provider working in a single round. A support report on its own takes two
or three.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts and
states, with no text from your account in it. Attach it to the issue the same
way. It is what keeps the rounds after the first one short, and it is
described in full on the
[Testing a provider](../../docs/testing-a-provider.md#if-a-run-fails-send-the-file-it-wrote)
page.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9253, sign in yourself
paperpull wellsfargo diagnose         REM the survey, for the maintainer
paperpull wellsfargo pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** wellsfargo.com runs bot protection that walls the Playwright build of Chromium, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Statements & Documents.** The app reaches the page by pressing its own Statements & Documents link and never types a Wells Fargo address into the signed-in window, since an address typed there ended a tester's session (#27). A window that is not on your signed-in accounts stops the run and asks you to open the page yourself. On the page it opens the Statements and Disclosures section when that says it is closed. Every control whose name says it fetches a statement or a tax form ("Statement 09/30/26 (123K, PDF)", "View", "Download", "1099-INT") is read, and the date comes from the control's name or the row it sits in.
- **Several accounts.** With more than one account in the section's account picker, each account is chosen in turn and its statements are listed under it, and the file name ends with the account's nickname and last four digits. With one account nothing about the names changes. With more than one, a statement an earlier version saved with no account downloads once more under its account's name, beside the earlier copy. Two accounts ending in the same four digits stop the list, since the app tells accounts apart by them.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response, a new tab or this tab moving to the PDF,
  is caught and saved to `Statements\` or `Tax Documents\`. A download
  chooses its document's account in the picker first.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that transfers, pays, sends money by Zelle, wires, deposits, applies, opens or closes an account, locks a card, changes a limit or an address, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Whatever the Statements & Documents page lists. Wells Fargo keeps up to seven years of statements online.
- Wells Fargo shows statements one account at a time behind an account picker, measured on a tester's checking account (#27), and the app goes through every account in it. It reads the period the page shows first, so whether older statements need a period chosen is still to be seen.
- Checking, savings, credit card, mortgage and loan accounts all share the same page, so one app should cover any of them once the site layer is confirmed.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull wellsfargo add-account NAME`).
