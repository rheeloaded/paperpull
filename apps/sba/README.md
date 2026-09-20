# SBA statement downloader

**Not yet tested against a real account.** This app was built without
an SBA loan serviced through the MySBA Loan Portal (EIDL, PPP, 7(a), 504 or disaster loan), so that someone who holds one can test it without
writing code. It runs, its guards are tested, and every guess about
sba.gov is marked in `sba_site.py`. What it needs is a survey from a
signed-in account, which the Diagnose button produces and which contains
no personal data. The conversation is
[issue #28](https://github.com/rheeloaded/paperpull/issues/28).

Downloads your SBA **statements and tax documents** as PDFs. Read-only,
delete-safe, part of [PaperPull](../../README.md).

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **SBA**. Pick it in the App list.
3. Click **Login**. Your own Edge or Chrome opens with a separate profile.
   Sign in yourself, answer any code it sends, and leave the window open.
4. Click **more** under the buttons, then **Diagnose**. It reads the
   documents page and writes `Diagnostics\diagnose-documents.json` in the
   SBA folder. It downloads nothing, clicks nothing but a documents
   link, takes no screenshot, and masks any run of six or more digits.
5. Open that file in Notepad and look through it. It should hold page
   headings, the names of buttons and links, and the shape of the data the
   page loads, no values. If anything in it looks personal, delete that
   line.
6. Attach the file to [issue #28](https://github.com/rheeloaded/paperpull/issues/28)
   with a sentence about what the documents page looks like to you.
7. When a new build is posted, click **Pilot** and say whether PDFs landed
   in `Statements\`, then attach a fresh Diagnose file.

Two or three rounds usually gets a provider working.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9254, sign in yourself
paperpull sba diagnose         REM the survey, for the maintainer
paperpull sba pilot            REM once the site layer is confirmed
```

## How it is meant to work

- **Your own browser.** `login.bat` launches the Edge or Chrome already on the machine with a separate profile. The portal signs in through login.gov or an SBA account, and both are yours to complete.
- **You sign in** in that window. The tool reuses the signed-in tab.
- **Statements.** Discovery tries the portal's likely routes in turn and takes the first that is not a sign-in page and looks like a statements list. Every control whose name says it fetches a statement or a tax form ("View statement", "Download", "1098") is read, and the date comes from the control's name or the row it sits in.
- **Downloads.** A row that links straight to a PDF is fetched from inside
  the page with the session's own cookies. Otherwise the row's control is
  clicked, once it has passed the guard, and whatever the site does, a
  download event, a PDF response or a new tab, is caught and saved to
  `Statements\` or `Tax Documents\`.
- **Read-only.** `FORBIDDEN_CONTROL_RE` blocks anything that makes or schedules a payment, enrolls in autopay, asks for hardship, deferment or forgiveness, applies, uploads, submits, or edits the account. A control must also look like a document action before it can be clicked.

## Scope

- Whatever the portal lists for each loan. Monthly statements and the year-end 1098.
- A borrower with more than one SBA loan sees them one at a time. The first survey shows how the portal lays that out, and the second round drives it, so a first Pilot may only see one loan.
- This is the MySBA Loan Portal at lending.sba.gov, for EIDL, PPP, 7(a), 504 and disaster loans the SBA services itself. A loan serviced by a bank has its statements at the bank.
- Delete-safe and multi-account like every PaperPull app
  (`paperpull sba add-account NAME`).
