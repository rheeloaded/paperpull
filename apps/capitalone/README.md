# Capital One bank and card statements, tax forms and letters

This provider reads documents from a browser where you sign in yourself.
Passwords and verification codes are never handled by the downloader.

It clicks nothing except the "continue session" dialog. Documents are found
by calling Capital One's own document search, which takes its parameters as
a POST body holding only document categories, a date range and an account
reference. That is a query, not a change to anything. The PDF itself is
fetched with a plain GET, and every request is checked inside the browser
against Capital One's own hosts before it is sent.

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself.
4. Run `paperpull capitalone diagnose`, then `paperpull capitalone pilot`.
5. Check the downloaded documents before using `paperpull capitalone all`.

Existing download history is retained in the provider's local state files.
Deleting a downloaded file does not reset that history.

## Validation status

Uses upstream core, a provider-local Python environment, and a separate browser
profile on port 9247. It does not require shared-browser or panel extensions.

A supervised statement run of the same provider logic in a downstream
installation downloaded a new statement and skipped completed history without
reported errors. That installation used a shared browser; the standalone
configuration is covered by automated tests but has not had a fresh live pilot.
Tax forms, letters, and all account variants have not been comprehensively
verified. Start with a small pilot and inspect its results.

## Maintenance

Provider behavior is in `capitalone_site.py`; the command orchestration is in
`capitalone_docs.py`. The storage specification and document rules define naming
and filing. Keep configuration, diagnostics, downloaded documents and browser
profiles private. Test fixtures must use synthetic names and identifiers.
