# Newrez document downloader

**Not yet tested against a real account.** This app was built without
a Newrez mortgage, so that someone who holds one can test it without
writing code. It runs, its guards are tested, and every guess about
newrez.com is marked in `newrez_site.py`. What it needs is a survey from a
signed-in account, which the Diagnose button produces and which contains
no personal data. The conversation is
[issue #38](https://github.com/rheeloaded/paperpull/issues/38).

Downloads your Newrez **mortgage statements and 1098 forms** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Newrez**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   Newrez folder. It downloads nothing, clicks nothing but a documents
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
7. Attach both files to [issue #38](https://github.com/rheeloaded/paperpull/issues/38)
   with a sentence about how you get from the dashboard to your statements, and whether the 1098 sits with them or on a tax page.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Tax Documents\`, then attach a fresh Diagnose file.

A Diagnose file and one recording together are usually enough to get a
provider working in a single round. Diagnose on its own takes two or three.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9257, sign in yourself
paperpull newrez diagnose         REM the survey, for the maintainer
paperpull newrez pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Newrez's portal is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Documents.** Discovery tries the documents and statements routes under myaccount.newrez.com in turn and takes the first that is not a sign-in page and looks like a documents list. Every control whose name says it fetches a statement, an escrow analysis or a 1098 is read, and the date comes from the control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Tax Documents\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, schedules a payment, sets up autopay, requests a payoff, an escrow change or hardship help, uploads anything, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Whatever the documents area lists. Monthly mortgage statements, the yearly 1098, and escrow analysis statements if they sit on the same page.
- One loan per sign-in is assumed. If you have more than one Newrez loan, say so in the issue, the survey will show how the site switches between them.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull newrez add-account NAME`).
