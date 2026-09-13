# U.S. Bank credit-card statements

This provider reads documents from a browser where you sign in yourself.
Passwords and verification codes are never handled by the downloader.

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself.
4. Run `diagnose.command` / `diagnose.bat`, then `run_pilot.command` / `run_pilot.bat`.
5. Check the downloaded documents before using `run_all.command` / `run_all.bat`.

Existing download history is retained in the provider's local state files.
Deleting a downloaded file does not reset that history.

## Validation status

Ported to the current upstream core. Automated checks are recorded with the
change; a fresh supervised live pilot of this port is still required.
No claim is made that all account variants or document types have been tested.

## Maintenance

Provider behavior is in `usbank_site.py`; the command orchestration is in
`usbank_docs.py`. The storage specification and document rules define naming
and filing. Keep configuration, diagnostics, downloaded documents and browser
profiles private. Test fixtures must use synthetic names and identifiers.
