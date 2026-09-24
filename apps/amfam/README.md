# American Family Insurance document downloader

**Not yet tested against a real account.** This app was built without an
American Family policy, so that someone who holds one can test it without
writing code. It runs, its guards are tested, and every guess about
myaccount.amfam.com is marked in `amfam_site.py`. What it needs is a
survey from a signed-in account, which the Diagnose button produces and
which contains no personal data. The conversation is
[issue #45](https://github.com/rheeloaded/paperpull/issues/45).

Downloads your American Family **billing statements, policy documents,
declarations pages, ID cards and notices** as PDFs. Read-only, delete-safe,
part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **American Family**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile
   at myaccount.amfam.com. Sign in yourself, answer any code it sends, and
   leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   American Family folder. It downloads nothing, clicks nothing but a
   documents link, takes no screenshot, and masks any run of six or more
   digits.
5. Click **Record**, in the same **more** menu. Go back to the browser window
   and click your way to one document the way you normally would, then come
   back here and click **Stop recording**. It writes
   `Diagnostics\recording.json`, which is the path you actually took rather
   than a guess at it. It records nothing you type and reads no cookies, and
   it refuses to start before you are signed in. The whole walkthrough, written
   for someone who has never done this, is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open each file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
   A recording also has a long `structure` block on each step. It holds
   only element kinds, attribute names and counts, so there is nothing
   in it to edit.
7. Attach both files to [issue #45](https://github.com/rheeloaded/paperpull/issues/45)
   with a sentence about what the documents page looks like to you.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Insurance Documents\`, then attach a fresh
   Diagnose file.
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

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9267, sign in yourself
paperpull amfam diagnose          REM the survey, for the maintainer
paperpull amfam pilot             REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Insurer sign-ins are happiest in a real
  browser, so `login.bat` launches the browser already on the machine with
  a separate profile and leaves the sign-in to you.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Documents and billing.** Discovery tries the My Account routes in
  turn and takes the first that is not a sign-in page and looks like a
  list of documents or bills. Every control whose name says it fetches a
  document ("View", "Download", "Declarations page", "ID card", "View
  bill") is read, and the date comes from the control's name or the row it
  sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Insurance Documents\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, sets up
  autopay, files or reports a claim, changes coverage, adds a vehicle or a
  driver, starts a quote, cancels or renews, or edits a setting. A control
  must also look like a document action before it can be clicked.

## Scope

- Whatever the documents and billing pages list. The survey will show how
  far back American Family keeps them online and whether older documents
  sit behind a policy picker or a year filter.
