# Renault Bank direkt

Downloads the PDFs Renault Bank direkt already holds in its Postfach and
archive, statements, tax documents, confirmations and the PDF attachments
of messages. Requested in [#172](https://github.com/rheeloaded/paperpull/issues/172)
and contributed by [@MelleD](https://github.com/MelleD) in
[#212](https://github.com/rheeloaded/paperpull/pull/212). Its CDP port is 9313.

**Run on the contributor's own account on 2026-11-12.** Discover
read the history, and a Pilot saved five recent documents, an older archive
document and a message attachment as valid PDFs. A second Pilot saved
nothing new. A whole run of the account has not been reported yet.

## Commands in a checkout

`--root ./apps` picks the app in this checkout even when the panel is set
to use another install folder.

```sh
./paperpull --root ./apps renaultbank login
```

Sign in yourself, answer your own two-factor prompt, and leave the window
open. The Postfach is at
`https://banking.renault-bank-direkt.de/services_cloud/portal/webcomp/epostfach/postfach`.

```sh
./paperpull --root ./apps renaultbank discover
./paperpull --root ./apps renaultbank pilot
./paperpull --root ./apps renaultbank all
```

Check the Pilot's PDFs first. Resume carries on with a run that stopped,
and Verify checks the saved PDFs on this computer.

## How it reads documents

The signed-in page asks Renault Bank direkt's Atruvia document API for the
lists and files, from the bank's own address. Cookies, the customer and
document tokens and the download tickets stay in the browser, and only
each document's description and the PDF asked for leave it. Before each
request the portal's own `getSecurityService().ensureTokenForApiCall()`
prepares its access cookie, as the portal's own pages do. A session that
has ended stops the run. The app never signs in or answers a prompt.

- `liefereBerechtigteKunden?institut=BANK` names every bank customer the
  sign-in can see, customers outside the profile picked at the moment
  included.
- `liefereDokumenteZuKunden` reads Posteingang and Archiv for each customer
  with no date, account or unread filter, page by page to the total the
  bank declares.
- Incoming and sent messages are read page by page to their declared
  count, and the older messages of a thread too. Each PDF attachment is
  listed once. A message with no attachment is counted and said, and its
  own text is not saved. An attachment that is not a PDF (a photo or a
  Word file, say) is left out, counted and said. A postbox of a linked
  outside provider is not supported and stops Discover with that said.
- A missing field, a page given twice, a total that changes or a history
  that stops short stops Discover before any of the list is recorded.
- A document's PDF is staged with `datasharing/documentUpload`, which
  prepares a document the bank already holds and sends no file. A message
  attachment uses `messageAttachmentDownload` and a download ticket. Both
  are then fetched from the portal's `ticket/download` address.

No control is pressed. Only a fixed list of read, list and download calls
is made, and redirects are refused. Transfer, payment, status, delete,
archive and activation calls are never made. The app never marks anything
read itself. Whether the bank marks a document read when its PDF is
fetched has not been checked yet.

Documents are told apart as DKB's are, by kind, date, the last four of the
account and the whole title, and a stored id is a hint the list is checked
against. Documents alike that cannot be told apart fail rather than be
saved as each other. A document whose PDF does not come (an HTTP error,
no ticket, an answer that is not a PDF) fails alone, and the run goes on
and the next run asks for it again. Progress and indexes stay on this
computer, and a document saved once is remembered even after its file is
deleted.

## Development checks

```sh
python -m pytest apps/renaultbank/tests -q
```

The in-page tests run the app's own page script against made-up answers,
in Node for each part of the list and in Playwright's Chromium for whole
runs. They check paging, the archive and threads, that tokens stay in the
page, ticket downloads, an ended session and a list that stops short. No
account is used. Diagnostic files and recordings are kept out of Git.
