# Renault Bank direkt

Provider setup for [issue #172](https://github.com/rheeloaded/paperpull/issues/172).

**In progress: sign-in, Record and Diagnose are available. Document discovery
and downloads still require a recording from an account holder.** The public
Atruvia portal reveals no authenticated document list or PDF endpoint. This
setup assumes neither ING selectors nor an undocumented banking API.

The intended scope is all available statements, tax documents, confirmations
and other account documents, across every accessible account and product,
including the full available history.

## Record the document workflow

From the repository root on macOS:

```sh
./paperpull renaultbank setup
./paperpull renaultbank login
```

Sign in yourself in the browser that opens, complete two-factor authentication,
and leave it open. Then, in a second terminal from the repository root:

```sh
./paperpull renaultbank record
```

While recording, open the Postfach, open a document and download its PDF.
If available, also visit archive/history, account selectors, filters and the
next page, so the full history can be implemented. Return to the terminal and
press Enter to stop. Review `apps/renaultbank/Diagnostics/recording.json` before
sharing it in this chat. Never share credentials, cookies or downloaded bank PDFs.
The [recording guide](../../docs/testing-a-provider.md) explains what is captured.

Alternatively use **Record steps** under **More → Get help** in the panel.
`./paperpull renaultbank diagnose` produces a passive support report.

## Implementation status

- Stable entry URL: `https://banking.renault-bank-direkt.de/services_cloud/portal/`.
- Postfach: `https://banking.renault-bank-direkt.de/services_cloud/portal/webcomp/epostfach/postfach`.
- Authentication routes are treated as signed out.
- Separate browser profile and CDP port `9311`.
- Document categories, index, resumable state and CLI follow the existing apps.
- No automatic clicks, form submissions or downloads while the site is unmapped.
- Discover/Pilot/All stop explicitly rather than report an empty successful run.

## Tests

```sh
python -m pytest apps/renaultbank/tests -q
```
