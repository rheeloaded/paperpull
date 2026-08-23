# Contributing

Thanks for your interest! A few notes to keep this project safe and consistent.

## Ground rules

- **Never commit private data.** No real `config.json`, no `*-browser-profile/`,
  no downloaded PDFs, no logs/diagnostics. See [SECURITY.md](SECURITY.md). Run
  `git status` before every commit.
- **Keep the tools read-only.** Any new site interaction must go through the
  `FORBIDDEN_CONTROL_RE` / `SAFE_DOC_CONTROL_RE` guards in that app's
  `*_site.py`. Never add code that submits a form, confirms a dialog, moves
  money, or changes an account setting.

## When a provider changes its site

Each app isolates all provider-specific selectors, URLs, and page behavior in
its `*_site.py`. That is the file to repair when a site changes — the rest of an
app (discovery, delete-safe state, PDF validation, folders) is provider-agnostic.

## Adding a new provider

**The best way to grow PaperPull is to add the providers *you* use.** There's a
full walkthrough — architecture, the read-only contract, exploring a site,
testing, and submitting — in **[docs/adding-a-provider.md](docs/adding-a-provider.md)**.
See **[PROVIDERS.md](PROVIDERS.md)** for what's supported and what's requested,
and to claim one so two people don't build the same thing.

In short: clone the closest existing app (a receipt-style one like
`amazon`/`target`, or a statement-style one like `amex`/`robinhood`/`redcard`),
then:

1. Rewrite `*_site.py` for the new site (navigation + document collection +
   download). This is the only file with real work in it.
2. Point `config.example.json` at a **unique** CDP port (9222–9240 are taken;
   use 9241+) and this app's output folders.
3. Update `document_rules.json` (classification) if the app uses it.
4. Tune `FORBIDDEN_CONTROL_RE` for the provider, and keep the tests green
   (`python -m pytest tests`).
5. Verify against your real account (`--discover`, `--pilot`, re-run skips), then
   add yourself to PROVIDERS.md and open a PR.

## Tests

Each app has a `tests/` folder. Run `python -m pytest tests` from within the app
directory (with its venv active).

## Releasing

PaperPull uses **one repo-wide version** ([SemVer](https://semver.org)) via git
tags + GitHub Releases:

- **PATCH** — bug fixes, or repairing an app after a provider changes its site
- **MINOR** — a new app, or a cross-app feature
- **MAJOR** — breaking changes (repo layout, config format)

To cut a release:

1. Bump `VERSION` and add a `CHANGELOG.md` entry.
2. Commit, then tag: `git tag -a v0.2.0 -m "..." && git push origin v0.2.0`
3. On GitHub, create a Release from that tag (let it auto-generate notes).
