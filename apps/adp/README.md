# ADP Workforce Now pay statement downloader

**Not yet tested against a real account.** This app was built without an
ADP Workforce Now login, so that someone who holds one can test it without
writing code. It runs, its guards are tested, and every guess about
workforcenow.adp.com is marked in `adp_site.py`. What it needs is a survey
from a signed-in account, which the Diagnose button produces and which
contains no personal data. The conversation is
[issue #46](https://github.com/rheeloaded/paperpull/issues/46).

Downloads your ADP Workforce Now **pay statements and W-2s** as PDFs.
Read-only, delete-safe, part of [PaperPull](../../README.md). ADP sells
many products. This app is for the employee portal at workforcenow.adp.com,
the one the requester uses, and may or may not fit myADP, RUN or TotalSource
logins. A survey from one of those would tell.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **ADP Workforce Now**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile
   at ADP's sign-in. Sign in yourself, answer any code it sends, and leave
   the window open on Myself, Pay and Annual Statements.
4. Click **more** under the buttons, then **Diagnose**. It reads the pay
   statements page and writes `Diagnostics\diagnose-documents.json` in
   the ADP Workforce Now folder. It downloads nothing, clicks nothing but
   a statements link, takes no screenshot, and masks any run of six or
   more digits.
5. Open that file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
6. Attach the file to [issue #46](https://github.com/rheeloaded/paperpull/issues/46)
   with a sentence about what the pay statements page looks like to you.
7. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Pay Statements\`, then attach a fresh Diagnose file.

Two or three rounds usually gets a provider working.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9265, sign in yourself
paperpull adp diagnose            REM the survey, for the maintainer
paperpull adp pilot               REM once the site layer is confirmed
```

## How it is meant to work

- **Real Edge or Chrome.** ADP's sign-in may go through your employer's
  own identity provider and often asks for a code, so `login.bat` launches
  the browser already on the machine with a separate profile and leaves
  the sign-in to you.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Pay and Annual Statements.** Discovery opens the Myself page the
  requester named and takes the first route that is not a sign-in page
  and looks like a list of statements. Every control whose name says it
  fetches a pay statement or a tax form ("View", "Download", "Pay
  Statement", "W-2") is read, and the pay date comes from the control's
  name or the row it sits in. Workforce Now fills that page from ADP's own
  statement services, and the survey records the shape of what it loads,
  so the second round can read the list the way the page does.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Pay Statements\` or `Tax Documents\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything about direct
  deposit, withholding, W-4, time off, timecards, benefits, beneficiaries,
  addresses or settings. A control must also look like a document action
  before it can be clicked.

## Scope

- Whatever the Pay and Annual Statements page lists. ADP keeps several
  years of pay statements and W-2s online, and the survey will show how
  far back the page reaches and whether older years sit behind a filter.
