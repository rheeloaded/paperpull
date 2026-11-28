# Poppins Payroll Documents Downloader (local, supervised)

For **household employers** who pay a nanny or another household employee
through [Poppins Payroll](https://www.poppinspayroll.com). Signed in as the
employer, it saves:

- **Pay stubs**, one per completed payroll, Poppins' own PDF, into `Pay Stubs`
- **Tax forms** from Documents: the employee's W-2 and overtime premium
  report, your W-3 and Schedule H, and the setup forms (SS-4, 2848,
  IL-2848, the Illinois unemployment insurance power of attorney), into
  `Tax Forms`
- **Tax payment history**: Poppins keeps no document for the quarterly
  federal and state withdrawals it makes, only a Payment History table on
  Taxes, Federal and Taxes, State. This app saves each table as a PDF of
  its own, headed as transcribed from Poppins on the day it was made, into
  `Tax Payment History`. A new one is made only when a new payment appears.

plus `Poppins Document Index.csv`, one row per downloaded PDF.

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to Poppins **yourself**; the tool never
touches your password or any verification prompt.

> ⚠️ **Pay stubs carry your employee's name, address, pay and tax
> withholding.** The index CSV deliberately records none of that, only what
> is needed to find and verify a file locally. Never commit the PDFs, the
> CSV, or your `config.json`.

## Read-only, and how

A Poppins sign-in can run payroll, move money and change bank accounts, so
this app **presses nothing**. It opens the Payroll list in your tab to see
that you are signed in, and asks for every other list and document by its
address with your session, each address checked against a short allowlist
first. A payroll's own page is refused outright, since it is the form that
edits hours and pay even for a payroll already paid, and so are Settings,
Employees and Generate FSA receipt. A pay stub is taken only from a row
marked Complete; the payroll still open for editing is passed by.

**Not covered:** FSA reimbursement receipts. Poppins makes one only when
you fill in and submit its Generate FSA receipt form, and this app never
submits a form.

## Using it

From the control panel, add Poppins and press Login, or from this folder:

```
./login.command          # opens a sign-in window on port 9327; sign in, leave it open
paperpull poppins discover
paperpull poppins pilot  # the newest three, then stops for you to look
paperpull poppins all
```

Run it every few months; nothing Poppins lists ages out that has been seen,
but a run catches the year's W-2, W-3 and Schedule H once Poppins makes them
in January.

## How it works

See the top of `poppins_site.py` for the pages, the addresses and what each
answers, as surveyed on a real employer account on 2026-11-27.
