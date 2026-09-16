# Charles Schwab statements, tax forms, letters and trade confirmations

This provider reads documents from a browser where you sign in yourself.
Passwords and verification codes are never handled by the downloader.

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself.
4. Run `paperpull schwab diagnose`, then `paperpull schwab pilot`.
5. Check the downloaded documents before using `paperpull schwab all`.

Existing download history is retained in the provider's local state files.
Deleting a downloaded file does not reset that history.

## Validation status

Uses current upstream core, standard launchers, a provider-local Python
environment, and a separate browser profile on port 9245.
Automated tests cover parsing, filing, document identity, browser configuration,
and request/control guards. Start with a small pilot and inspect its results.

## How it reads the site

Nothing on the page is clicked to find or fetch a document. Accounts and the
document list come from Schwab's statements gateway, the same JSON calls the
page itself makes, and each PDF is fetched from the gateway's download
endpoint with the session already in the browser. The statements page shares
its shell with a trade ticket, which is why the app stays off the page's
controls entirely. The one click it ever makes is on a "Continue session" or
"I'm still here" button when Schwab's timeout prompt appears.

Download identifiers are opaque and not stable, so a document is identified by
what it is (type, name, date, account) plus its position among identical
descriptors on the same day. Before each download the list for that day is
fetched again and the document is matched afresh. If the account nickname on
Schwab changes, the labels change with it and history for that account starts
over, so pick a nickname and keep it.


## Maintenance

Provider behavior is in `schwab_site.py`; the command orchestration is in
`schwab_docs.py`. The storage specification and document rules define naming
and filing. Keep configuration, diagnostics, downloaded documents and browser
profiles private. Test fixtures must use synthetic names and identifiers.
