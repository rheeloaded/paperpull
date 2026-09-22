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
5. Open that file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
6. Attach the file to [issue #45](https://github.com/rheeloaded/paperpull/issues/45)
   with a sentence about what the documents page looks like to you.
7. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\` or `Insurance Documents\`, then attach a fresh
   Diagnose file.

Two or three rounds usually gets a provider working.

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
