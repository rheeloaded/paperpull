# 1822direkt

Downloads existing account and card statements, securities documents, tax
certificates and other PDFs from the 1822direkt Postbox. Requested in
[issue #174](https://github.com/rheeloaded/paperpull/issues/174).

**Tested on one contributor’s real account on 2026-11-12.** Discovery read
80 distinct PDFs across the available history and conversation attachments.
A five-document Pilot saved valid PDFs; the repeated Pilot saved no new
files. A full download of the whole account has not been run.

1822direkt is the **84th supported provider** and the **93rd app**.
The template uses CDP port **9314**.

## Sign in and run

From this checkout:

```sh
./paperpull --root ./apps direkt1822 login
```

Sign in yourself, answer any two-factor prompt and leave the browser open.
Sign-in is at `https://www.1822direkt-banking.de/ng-banking/login/eingabe`;
the Postbox is at `/ng-banking/banking/postbox`.

### Conversation access requires an explicit choice

1822direkt’s only observed method for reading conversation attachments,
`leseUndVermerkeMitId`, also marks the conversation read. To enumerate all
available PDF attachments, explicitly allow that side effect:

```sh
./paperpull --root ./apps direkt1822 discover --allow-mark-read
./paperpull --root ./apps direkt1822 pilot --allow-mark-read
./paperpull --root ./apps direkt1822 pilot --allow-mark-read
```

Check the Pilot’s PDFs. The second Pilot must download nothing new. To
keep the choice for this install or use it from the panel, set
`"open_conversations": true` in the private `config.json`. The tracked
example defaults to `false`. Without consent, a multi-part conversation
stops discovery rather than being silently treated as a complete list.

```sh
./paperpull --root ./apps direkt1822 all --allow-mark-read
```

Resume continues an interrupted download; Verify checks saved PDFs locally.
The bank may end a supervised session. Sign in yourself again and restart
Pilot/All or Resume; files already saved are remembered and skipped.

## Scope and implementation

- Uses the Postbox’s own JSON list API inside the signed-in page. Its
  authenticated `benutzerInfo` response prepares the same `X-JOBA-AUTH`
  and `X-CSRF-TOKEN` headers as the public client. Tokens never leave the
  browser and are not stored in run files.
- Reads Posteingang, Gesendet and Papierkorb with no account, category,
  date or unread filters. `include_trash` can be set to `false` to leave
  Papierkorb out. It reads documents without restoring deleted entries.
- Pages start at zero. Every declared page and total is checked; repeated
  entries, changed counts and incomplete pages stop the whole listing.
- With conversation consent, older PDF attachments are read too. The
  same document id under several conversation subjects is downloaded
  once, preferring the direct list’s metadata.
- Downloads use the public client’s dedicated PDF URL. No conversation
  needs to be opened merely to download a directly listed PDF. Redirects
  are refused and bytes must begin with the PDF signature.
- Known bank category codes identify account/card statements, securities
  documents and tax certificates. Unknown types use title rules or the
  Other Document folder. DKB-style orchestration handles indexing,
  identity, filename collisions and delete-safe progress.

Plain text/HTML bodies are not exported as PDFs. The bank shows some sent
file attachments only as names with no download link; these are counted
and not exported. Multiple customer relationships under one sign-in are
not mapped yet and explicitly stop the listing. Several accounts/products
within one customer relationship are included in the unfiltered Postbox.

No banking control is clicked. Payment, transfer, trading, signing,
activation, delete, restore and account-setting endpoints are excluded.
The sole intentional state change is the bank’s read-marking that the
account holder explicitly opts into for opening conversations.

## Development checks

```sh
python -m pytest apps/direkt1822/tests -q
```

The actual in-page JavaScript is tested with Node and invented API answers:
zero-based pagination, complete totals, deduplication, consent gating,
in-page token containment, downloads and session failure. No account is
accessed by those tests. `capture_structure.py` is an optional local helper
that captures Postbox route names and JSON schemas without scalar values,
headers, cookies or PDF contents. Runtime diagnostics stay out of Git.
