# SMUD document downloader

**Working, confirmed on a real account.** This app was built without a
SMUD electric account and repaired across three rounds from the surveys
and traces one tester sent. His Pilot saved the five most recent bills
and his full run saved the rest of the twenty-four SMUD keeps. The
conversation is
[issue #34](https://github.com/rheeloaded/paperpull/issues/34).

Downloads your SMUD **monthly bills** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **SMUD**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   SMUD folder. It downloads nothing, clicks nothing but a documents
   link, takes no screenshot, and masks any run of six or more digits.
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
7. Attach both files to [issue #34](https://github.com/rheeloaded/paperpull/issues/34)
   with a sentence about whether past bills are listed on the same page as the current one or behind a bill history link, and what the download control is called.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\`, then attach a fresh Diagnose file.

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
login.bat                         REM opens Edge or Chrome on port 9259, sign in yourself
paperpull smud diagnose         REM the survey, for the maintainer
paperpull smud pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** A utility portal is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Billing history.** Discovery tries the billing routes on myaccount.smud.org in turn and takes the first that is not a sign-in page and looks like a bill list. Every control whose name says it fetches a bill ("View bill", "Download", "Bill PDF") is read, and the date comes from the control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, sets up autopay, enrolls in a program or a rate plan, starts, stops or moves service, requests an extension, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Whatever the billing history lists. Utilities usually keep one to two years of bills online.
- One service account per sign-in is assumed. If you have more than one, say so in the issue.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull smud add-account NAME`).
