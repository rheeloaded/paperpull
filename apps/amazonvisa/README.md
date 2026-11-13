# Amazon Visa

Downloads the card statement PDFs and other PDFs the
[Amazon Visa portal](https://kunden.openbankpay.com/amazon/login) already
holds, the statement history of each card contract the sign-in shows and
the documents in each category the portal lists. Requested in
[#171](https://github.com/rheeloaded/paperpull/issues/171) and contributed
by [@MelleD](https://github.com/MelleD) in
[#214](https://github.com/rheeloaded/paperpull/pull/214). Its CDP port is
9315.

**Run on the contributor's own account.** Discover listed 28 PDFs, 26 of
them card statements. Three statements, one contract and one other PDF
were saved, and all five passed verification. Downloading the statements
again saved no duplicates. A whole run and a second account have not been
reported yet.

## Sign in and download

Run the following commands from the PaperPull checkout. Run setup once with
Python 3.11 or later, then create your local config.

```sh
./paperpull --root ./apps amazonvisa setup
```

```sh
cp apps/amazonvisa/config.example.json apps/amazonvisa/config.json
```

```sh
./paperpull --root ./apps amazonvisa login
```

Sign in yourself, answer your own two-factor prompt, and leave the Amazon
Visa window open. Then check the list and save the newest few PDFs.

```sh
./paperpull --root ./apps amazonvisa discover
```

```sh
./paperpull --root ./apps amazonvisa pilot
```

Use `all` for a full download, `resume` to carry on with a run that
stopped, and `verify` to check the saved files. The local `config.json`
sets the output folder and the document types. The index and progress
file let later runs skip PDFs already saved.

## How it reads documents

The signed-in page asks the portal's own client for the lists and tickets,
so the session and each signed PDF link stay in the browser, and only each
document's description and the PDF asked for leave it. The PDF itself
comes from the portal's document store, asked for without cookies. No
control is pressed and the app never signs in or answers a prompt.

- The card list names every card contract, and each contract's statement
  history is read whole. A statement with no PDF yet, its fields empty
  or left out, is counted and said.
- Each document category the portal lists is read, and a document that is
  not a PDF is counted and said. A document that is also a statement is
  listed once.
- An answer with no card in it, a card whose statement rows all leave out
  the fields that name their PDFs, a statement row with one of them and
  not the other, a categories answer that holds something but not their
  list, a category without its documents or its size, a category whose
  documents fill the whole answer of 100, or a statement list with
  records still pending stops Discover before any of the list is
  recorded. An empty categories answer is no categories.
- A date that comes with a time and a zone is its day in Berlin. A plain
  day is taken as it is.
- A call the portal never answers is given up on after 30 seconds.

Documents are told apart by kind, date, the last four of the card contract
and the title, and a stored id is a hint the list is checked against.
Documents alike that cannot be told apart fail rather than be saved as
each other. A document whose PDF does not come (a refused or failed
ticket, a sign-in page in its place, no link, or an answer that is not a
PDF) has the list read again. If the list answers as signed out, the run
stops there. If it still answers, that document fails alone, the run goes
on, and the next run asks for it again.

## Development checks

```sh
python -m pytest apps/amazonvisa/tests -q
```

The in-page tests run the app's own page script against made-up answers,
in Node for the page script alone and in Playwright's Chromium for whole
runs through the app's main, with the webpack runtime and client module
the page script asks for. No account is used.
