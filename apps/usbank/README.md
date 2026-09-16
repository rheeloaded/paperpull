# U.S. Bank credit-card statements

This provider reads documents from a browser where you sign in yourself.
Passwords and verification codes are never handled by the downloader.

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself.
4. Run `paperpull usbank diagnose`, then `paperpull usbank pilot`.
5. Check the downloaded documents before using `paperpull usbank all`.

Existing download history is retained in the provider's local state files.
Deleting a downloaded file does not reset that history.

## Validation status

Uses current upstream core, standard launchers, a provider-local Python
environment, and a separate browser profile on port 9243.
Automated tests cover parsing, filing, document identity, browser configuration,
and request/control guards. Start with a small pilot and inspect its results.


## Maintenance

Provider behavior is in `usbank_site.py`; the command orchestration is in
`usbank_docs.py`. The storage specification and document rules define naming
and filing. Keep configuration, diagnostics, downloaded documents and browser
profiles private. Test fixtures must use synthetic names and identifiers.
