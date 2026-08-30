# DFAS myPay — retiree document downloader (READ-ONLY)

Downloads your **Retiree Account Statements (eRAS)**, **CRSC pay statements**
and tax forms from DFAS myPay as PDFs. Read-only, delete-safe, part of
[PaperPull](../../README.md).

> **Verified end to end against a live account (2026-08-29)**, for the
> retiree document types.
>
> **Active-duty document types are supported but untested.** Leave and Earnings
> Statements and W-2s are enumerated using myPay's own document-type numbers,
> over the same API the other types are proven on, but this has **not been
> tested against a real active-duty account**. It should work and may not. Run
> `diagnose.bat` first, then `run_pilot.bat`, and check the PDFs before
> trusting a full run.

## Read this first, because it is a government system

myPay is a U.S. Government information system. Two things follow from that,
and neither is something this tool decides for you.

- **Check whether DFAS permits this.** Their terms of use may restrict
  automated access even to your own account. You are the account holder, you
  sign in yourself, and this tool only reads and downloads documents DFAS has
  already generated for you. Whether a script may drive that session is DFAS's
  call. If in doubt, use myPay by hand.
- **You accept the DoD consent banner, not this tool.** It never clicks
  through a government consent notice, never accepts terms, and never submits
  a form.

## Read-only by design (myPay can move your retirement pay)

myPay can redirect your net pay to a different bank, change federal and state
withholding, start and stop allotments, and alter SBP and beneficiary
elections. This tool does none of it. Concretely:

- **Nothing on the page is clicked.** There is no click, no form submit, no
  dialog confirmation, and no navigation anywhere in the site layer, and a test
  enforces that.
- **The guard refuses pay controls outright.** Direct deposit, routing and
  account numbers, allotments, withholding and W-4, SBP, SGLI, TSP,
  beneficiary, address, login ID and password, plus every "change", "update",
  "start", "stop", "consent", "agree", "submit" and "certify" variant.
- **The SSN field on the sign-in page is only ever detected**, as a signal that
  you are signed out. It is never read from and never typed into.
- **A document is fetched by a validated (type, date) pair, never a URL.** The
  type must be one of myPay's own document types and the date a real calendar
  date, so the request is built from values this app recognises rather than
  from any stored string.
- **A short session that expires stops the run** and says so, rather than
  filing everything as "needs manual review" and exiting as though it worked.

## Setup

```bat
setup.bat                 REM one-time: venv + Playwright
login.bat                 REM opens Chromium on port 9241 - sign in yourself
diagnose.bat              REM read-only look at what is on the page; downloads NOTHING
run_pilot.bat             REM download the newest few as a test, then stop
run_all.bat               REM download everything in scope (asks for YES)
```

Sign in at `mypay.dfas.mil` the way you normally do, with your Login ID and
password or your CAC, accept the DoD banner yourself, open your statements
area, and **leave the browser window open**. The tool attaches to that
already-signed-in browser and reads only what you can see. It never handles
your credentials, your CAC PIN, or your 2FA.

myPay sessions time out quickly. If a run stops saying the session expired,
sign in again and use `resume.bat` — finished documents are never re-fetched.

## Documents captured

| Folder | Contents |
|---|---|
| `Statements\` | Retiree Account Statements (eRAS), CRSC pay statements, and Leave and Earnings Statements (LES) |
| `Tax Documents\` | 1099-R, W-2, W-2C and IRS 1095 forms |
| `Year-End Summaries\` | Year-end statements (created on demand) |
| `Other Documents\` | Anything else (created on demand) |
| `Manual Review\` | Files that failed PDF validation |

Filenames: `YYYY-MM-DD DFAS myPay <Summary>.pdf`, so an eRAS and a CRSC
statement for the same month stay clearly distinct even though both are pay
statements and share a folder. Naming rules live in `document_rules.json`
(plain regex, editable) and are provisional until you have seen what myPay
actually calls things.

## Sensitive files

These are the most sensitive documents this project handles. A retiree account
statement carries a DoD ID, gross and net pay, VA waiver, SBP election and
address. A CRSC statement relates to a disability determination. A 1099-R
carries a taxpayer identification number.

They are saved to the folder you set as `output_dir` in `config.json`. Keep it
somewhere safe, and if that folder syncs to a cloud drive, know these documents
go with it. The index CSV records **no** dollar amounts. `diagnose.bat` writes
no screenshot, deliberately, so a page full of pay figures does not end up in a
file that is easy to attach to a bug report by accident.

## Tests

```
.venv\Scripts\activate
pytest
```
