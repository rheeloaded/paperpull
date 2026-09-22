# State Farm document downloader

**Not yet tested against a real account.** This app was built without
a State Farm auto, home or life policy, so that someone who holds one can test it without
writing code. It runs, its guards are tested, and every guess about
statefarm.com is marked in `statefarm_site.py`. What it needs is a survey from a
signed-in account, which the Diagnose button produces and which contains
no personal data. The conversation is
[issue #37](https://github.com/rheeloaded/paperpull/issues/37).

Downloads your State Farm **bills, renewal notices, ID cards and payment receipts** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **State Farm**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   State Farm folder. It downloads nothing, clicks nothing but a documents
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
7. Attach both files to [issue #37](https://github.com/rheeloaded/paperpull/issues/37)
   with a sentence about how bills, ID cards and policy documents are separated (tabs, per policy, one list), and what the download control is called.
8. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Insurance Documents\`, then attach a fresh Diagnose file.

A Diagnose file and one recording together are usually enough to get a
provider working in a single round. Diagnose on its own takes two or three.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9261, sign in yourself
paperpull statefarm diagnose         REM the survey, for the maintainer
paperpull statefarm pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** Statefarm.com's sign-in is happiest in a real browser, so `login.bat` launches the browser already on the machine with a separate profile.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Documents and billing.** Discovery tries the documents and billing routes under statefarm.com's customer care in turn and takes the first that is not a sign-in page and looks like a documents list. Every control whose name says it fetches a bill, a renewal notice, an ID card, a receipt or a policy document ("View", "Download", "ID card", "Bill PDF") is read, and the date comes from the control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Insurance Documents\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that pays, sets up autopay, files or reports a claim, changes coverage, adds or removes a vehicle, driver or policy, starts a quote, cancels or renews anything, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Bills and renewal notices file to `Statements\`, ID cards and policy documents to `Insurance Documents\`, payment receipts to `Statements\` as Receipt.
- State Farm keeps documents per policy. The first survey shows how policies are switched, and the second round drives it, so a first Pilot may only see one policy.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull statefarm add-account NAME`).
