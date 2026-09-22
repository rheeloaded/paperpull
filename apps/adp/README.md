# ADP Workforce Now pay statement downloader

Downloads your ADP Workforce Now **pay statements and W-2s** as PDFs.
Read-only, delete-safe, part of [PaperPull](../../README.md). Built and
run against a real Workforce Now employee account on 2026-09-21, 20 pay
statements and two W-2s, asked for in
[issue #46](https://github.com/rheeloaded/paperpull/issues/46).

ADP sells many products. This app is for the employee portal at
workforcenow.adp.com. myADP, RUN and TotalSource logins use the same
statement services behind a different shell, so it may work there too,
and a Diagnose file from one of those would tell.

## Setup, for a checkout

```bat
setup.bat                         REM one-time: venv + Playwright
login.bat                         REM opens Edge or Chrome on port 9265, sign in yourself
paperpull adp pilot               REM newest five, then stops for your inspection
paperpull adp all                 REM everything the services list (asks for yes)
paperpull adp diagnose            REM a masked survey, if something looks wrong
```

## How it works

- **Real Edge or Chrome.** ADP's sign-in often goes through your
  employer's own identity provider and asks for a code, so `login.bat`
  launches the browser already on the machine with a separate profile and
  leaves the sign-in to you. Sign in, and leave the window open.
- **The page's own services.** Workforce Now's Pay & Tax Statements page
  fills itself from ADP's statement services on my.adp.com, one call for
  pay statements and one for tax statements. The app makes the same two
  calls from inside the signed-in page, with the same cookies, and reads
  the lists. The worker id those calls need is read from the addresses the
  page already called, never asked for.
- **Each statement's own PDF.** Every entry in those lists carries the
  address of its PDF. The app fetches it from inside the page and saves it
  to `Pay Statements\` or `Tax Documents\` as
  `YYYY-MM-DD ADP Workforce Now Pay Statement.pdf` or
  `YYYY-12-31 ADP Workforce Now W-2 Tax Form.pdf`. Nothing on the page is
  clicked, and only my.adp.com and workforcenow.adp.com are ever asked.
- **Read-only.** `FORBIDDEN_CONTROL_RE` refuses anything about direct
  deposit, withholding, W-4, time off, timecards, benefits, beneficiaries,
  addresses or settings, and there is no code here that clicks at all.
- **Delete-safe.** A statement downloaded once is remembered as done, so
  deleting the PDF after importing it into paperless-ngx never brings it
  back.

## Scope

- Everything the two services list. The account this was built against
  listed every pay statement of the employment (a little under a year) and
  a W-2 for each year. "Hide My Pay" on the page does not hide anything
  from the services.
- One employer per login. A person with pay from two employers in
  Workforce Now signs in to each separately, and the W-2 filename carries
  the employer's name.

## When ADP changes its portal

All ADP selectors/URLs live in **`adp_site.py`** only. Run
`paperpull adp diagnose` to capture the current page and the shape of
the data it loads into `Diagnostics\`, with every long number masked, then
repair that one file.

## Tests

```
.venv\Scripts\activate
pytest
```
