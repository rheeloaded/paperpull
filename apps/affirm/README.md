# Affirm loan agreement downloader

Downloads your own **loan agreements** from Affirm, one per loan, as PDFs,
for your records. Read-only, delete-safe, and part of
[PaperPull](../../README.md).

Mapped and run against a real account on 2026-09-19. Two loans, two
agreements, 13 and 15 pages each, and a second run downloaded nothing.

## What Affirm has, and what it does not

For a pay-over-time account **there is no monthly statement**. The "Affirm
Loans statement" Affirm's help center describes belongs to the Affirm Money
account and the Affirm Card, under the Money tab, which the account this
was built against does not have, so those are not covered here. If you
hold one and want its statements, open an issue with a `diagnose` survey.

What every loan does have is its **loan agreement**, the Truth in Lending
disclosure with the payment schedule, under "Loan terms" in the loan's
Details tab. That is the document this app keeps, one per loan, settled
loans included, dated the day the loan was made and named for the
merchant, `2025-11-29 Affirm Loan Agreement - Pottery Barn.pdf`.

The Details tab also offers a "Loan verification document". That is a
letter written on request with today's date, from a signed link that
expires, a request rather than a record, so the app leaves it alone.

## How it reads the site

Three GET calls the page itself makes, from inside the signed-in page on
the cookie session, so nothing leaves the browser. One lists every loan,
one gives a loan's created date, one gives its Details tab, where the
"Loan terms" entry carries the agreement's URL. The agreement is an HTML
page, which the app fetches the same way and renders to PDF in a temporary
tab of the same browser. Nothing on the page is clicked.

## Safety

This is a lender's account. The site can make a payment, set up autopay,
store a card or bank account, take a new loan, and change contact details.
This app never activates a control that does any of those. It clicks
nothing, and the calls it makes refuse to run from any page that is not on
`affirm.com` and refuse any URL that is not. An expired session stops the
run rather than reporting an empty success.

## Sign-in

`paperpull affirm login` opens a plain Chromium at affirm.com. You sign in
yourself with your phone number and the text-message code, and leave the
window open. The app never sees either.

## Commands

```
paperpull affirm setup
paperpull affirm login        sign in yourself, leave the window open
paperpull affirm discover     list the loans and their agreements, download nothing
paperpull affirm pilot        the newest five
paperpull affirm all          everything, delete-safe on a rerun
paperpull affirm verify       re-check every saved PDF
```

## Tests

```
python -m pytest tests -q
```
