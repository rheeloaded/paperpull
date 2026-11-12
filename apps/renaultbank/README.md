# Renault Bank direkt

Downloads existing PDFs from the Renault Bank direkt Postfach and archive,
including statements, tax documents, confirmations and message attachments.
Requested in [#172](https://github.com/rheeloaded/paperpull/issues/172).

**Status: tested on one contributor’s real account on 2026-11-12.**
Discovery read the available history; five recent documents, an older archive
document and a message attachment were saved as valid PDFs. A repeated Pilot
saved no new files. A full download of the entire account has not been run.

## Commands in a checkout

`--root ./apps` selects the provider in this checkout even when the panel
is configured to use a different install folder.

```sh
./paperpull --root ./apps renaultbank login
```

Sign in yourself, answer your own two-factor prompt, and leave the window open.
The Postfach is at
`https://banking.renault-bank-direkt.de/services_cloud/portal/webcomp/epostfach/postfach`.

```sh
./paperpull --root ./apps renaultbank discover
./paperpull --root ./apps renaultbank pilot
./paperpull --root ./apps renaultbank pilot
./paperpull --root ./apps renaultbank all
```

Check the first Pilot’s PDFs. The second Pilot must save no new files.
Resume continues a stopped download; Verify checks saved PDFs locally.

## How it reads documents

The signed-in page makes same-origin calls to Renault’s Atruvia document
API. Cookies, customer/document JWTs and download tickets stay in the
browser. Only document metadata and the requested PDF bytes leave it.
Before a request, the portal’s own `getSecurityService().ensureTokenForApiCall()`
prepares its access cookie, as the portal’s HTTP interceptor does. An expired
login session stops the run; the app never attempts a login or answers a prompt.

- `liefereBerechtigteKunden?institut=BANK` supplies every accessible bank
  customer, including customers outside the currently selected profile.
- `liefereDokumenteZuKunden` reads Posteingang and Archiv separately for
  each customer, without date, account or unread filters. The response’s
  `aufsetzpunkt` is followed until the declared total is reached.
- Incoming and sent correspondence is paginated by its declared count.
  Older entries in correspondence threads are read too; each attachment
  is listed once. Text-only messages are counted and reported, but their
  text is not exported. Linked external-provider postboxes are unsupported
  and stop discovery explicitly.
- Missing metadata, repeated pages, changing totals or incomplete history
  stop discovery before it commits a partial list.
- Document downloads use the observed `datasharing/documentUpload` call,
  which stages an existing bank document for download; it sends no file.
  Message attachments use `messageAttachmentDownload` and a download
  ticket. PDFs are fetched by the portal’s `ticket/download` URL.

No banking control is pressed. Requests are limited to an explicit set of
read/list/download operations; redirects are refused. Transfer, payment,
status, delete, archive and activation endpoints are excluded. The app does
not explicitly mark anything read. Any server-side read-marking caused by
a download has not been checked yet.

The orchestration follows DKB: category, date, account suffix and full title
identify a document; ids are re-resolved as hints. Ambiguous documents fail
rather than being confused with another. Progress and indexes remain local,
and successful downloads are remembered even if their files are later removed.
Non-PDF downloads fail explicitly rather than being saved as PDFs.

## Development checks

```sh
python -m pytest apps/renaultbank/tests -q
```

The in-page API tests use Node and invented responses to check pagination,
archive and thread traversal, JWT containment, ticket downloads, session
expiry and incomplete-list failures. No account is used by those tests.
`capture_structure.py` is a local development helper for route/schema
reports; it saves no request/response values, authentication headers or PDF
contents. Diagnostic files and recordings are ignored by Git.
