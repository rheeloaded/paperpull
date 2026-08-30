<!-- Thanks for contributing! Fill in the checklist so this can be merged safely. -->

## What this PR does

<!-- e.g. "Adds a downloader for Fidelity brokerage statements (13th provider)." -->

## Type

- [ ] New provider app
- [ ] Fix for a provider whose site changed
- [ ] Docs / other

## Safety checklist (required)

- [ ] **Read-only.** No code path pays, transfers, redeems, enrolls, disputes,
      submits a form, or confirms a dialog. New controls are gated by
      `FORBIDDEN_CONTROL_RE` **and** `SAFE_DOC_CONTROL_RE`, tuned for this
      provider.
- [ ] **No credential handling.** The user signs in themselves; the app attaches
      to that session and only reads. No password/2FA code anywhere.
- [ ] **No private data committed.** `git status` shows only source — no real
      `config.json`, no `*-browser-profile/`, no PDFs, CSVs, logs, or state. No
      real names, account numbers, balances, or personal paths in code,
      comments, tests, or fixtures.
- [ ] `tests/` pass (`python -m pytest tests`), including the
      money/account-control safety tests.

## For a new provider

- [ ] Cloned the closest existing app; entry files renamed to `<slug>_*.py`.
- [ ] Uses a **unique CDP port** (9222–9241 are taken; used 9242+).
- [ ] Added a `config.example.json` (no real paths/owner).
- [ ] Added the provider to [PROVIDERS.md](../blob/main/PROVIDERS.md).
- [ ] Verified end-to-end against my real account: `--discover` lists documents,
      `--pilot` downloads valid PDFs, and a re-run **skips** them (delete-safe).

## Notes for reviewers

<!-- Anything unusual about this provider: bot detection, SPA session, download mechanism, history/pagination, session quirks. -->
