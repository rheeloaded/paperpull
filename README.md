# PaperPull

![Version](https://img.shields.io/github/v/tag/rheeloaded/paperpull?sort=semver&label=version&color=blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
[![Support on Ko-fi](https://img.shields.io/badge/Ko--fi-support%20this%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/rheeloaded)

**Receipt & Statement Downloader** — a family of small, **read-only** tools that log in *alongside you* to your own
accounts and download your **statements and receipts** as PDFs — so you can
archive them (e.g. into [paperless-ngx](https://docs.paperless-ngx.com/)) instead
of clicking through each site by hand.

Thirteen providers are supported today, all built on the same pattern:

| App | Provider | Documents | Notes |
|-----|----------|-----------|-------|
| [`amazon`](apps/amazon) | Amazon | Order invoices (full history) | Per-year order pagination |
| [`amex`](apps/amex) | American Express | Statements, Year-End Summary | Click-nav SPA; in-memory session |
| [`dominion`](apps/dominion) | Dominion Energy (VA) | Billing statements | Paginated MUI accordion; ~18-month limit |
| [`gap`](apps/gap) | Gap Inc. (Gap, Old Navy, Banana Republic, Athleta) | Order receipts | Lazy-loading history; ~13-month limit |
| [`navyfederal`](apps/navyfederal) | Navy Federal CU | Account statements | Per-account accordions; blob-tab PDFs |
| [`redcard`](apps/redcard) | Target RedCard / Circle Card (TD Bank) | Billing statements | Statements table; per-year switcher |
| [`robinhood`](apps/robinhood) | Robinhood | Account statements, tax docs | "View More" pagination |
| [`target`](apps/target) | Target | Receipts (Online + In-Store) | Print-capture |
| [`tmobile`](apps/tmobile) | T-Mobile | Bill statements | Bill-history page; detailed-bill download |
| [`usaa`](apps/usaa) | USAA | Statements | JSON-API enumeration |
| [`verizon`](apps/verizon) | Verizon (Fios) | Bill statements | Real Edge (bot block); dropdown + CDP download |
| [`walmart`](apps/walmart) | Walmart | Receipts | Hardened against bot detection |
| [`wealthfront`](apps/wealthfront) | Wealthfront | Statements, tax docs | |

> ⚠️ **Read this first:** these tools drive real, signed-in financial accounts.
> See [SECURITY.md](SECURITY.md) before you run *or* publish anything. In short:
> never commit your `*-browser-profile/` folder, your `config.json`, or any
> downloaded PDF. The `.gitignore` blocks them — don't override it.

## How it works (the shared design)

Every app follows the same four ideas:

1. **You sign in; the tool attaches.** `login.bat` (or `./login.command`) opens a browser window — a
   plain Chromium for most apps, or your installed Edge/Chrome for the few sites
   with bot detection (e.g. Walmart, Verizon) — using that app's own profile and
   a dedicated debugging port. **You** complete sign-in, 2FA, and any device
   approval yourself. The tool then connects to that already-authenticated
   browser over the Chrome DevTools Protocol (CDP). It never sees your password
   or handles your 2FA.
2. **Read-only by construction.** All site interaction lives in `*_site.py`,
   guarded by a hard blocklist (`FORBIDDEN_CONTROL_RE`) *and* a document
   allowlist (`SAFE_DOC_CONTROL_RE`). Nothing that buys, sells, transfers, pays,
   deletes, or changes a setting can be clicked.
3. **Delete-safe.** Once a document is saved it gets a sticky `downloaded_ok`
   marker. Delete the PDFs after importing them elsewhere and a re-run will
   **not** fetch them again — it only grabs what's genuinely new
   (`new-this-run.txt` lists them each run).
4. **Multi-account.** A `--config config.<name>.json` flag lets one app serve a
   second person's account with its own profile, port, and output folders — no
   data mixing. The launchers take the account label as an argument
   (`login.bat spouse` / `./login.command spouse`).

## Quick start

![Quick start](docs/quickstart.gif)

**One-shot setup** (creates a venv for every app + the GUI, installs the browser):

```bat
setup-all.bat        REM Windows
```

```bash
./setup-all.command  # macOS / Linux
```

Then either drive everything from the **[GUI control panel](gui)** — pick an
app and account, click an action, and watch the live output:

```bat
gui\run_gui.bat
```

![PaperPull control panel](docs/control-panel.gif)

…or run a single app directly (using `amex` as the example):

```bat
cd apps\amex
copy config.example.json config.json    REM then edit paths as needed
login.bat                 REM opens Chromium — sign in yourself, leave it OPEN
run_pilot.bat             REM download the newest few as a test
run_all.bat               REM download everything available
```

Each app also has its own README with provider-specific details and quirks.
(Prefer to set apps up one at a time? Each has its own `setup.bat` / `setup.command`.)

## Requirements

- **Windows or macOS** (Linux works too — it uses the same scripts as macOS)
- Python 3.11+
- Playwright (installed per app by the setup script)

Every app ships both launchers: `.bat` for Windows and `.command` for
macOS/Linux, with the same names and the same behaviour. On macOS you may need
to allow a script the first time (right-click → Open), and the very first run
of `chmod +x *.command` if your copy lost the executable bit in transit.

## Contributing — add your provider

No one has accounts everywhere, so **PaperPull grows when people add the
providers they use.** If a bank, card, brokerage, utility, telecom, or retailer
you use isn't here yet, you're the ideal person to add it:

- 📖 **[Adding a provider](docs/adding-a-provider.md)** — a step-by-step guide
  (clone the closest app, rewrite one file, stay read-only, test, submit).
- 📋 **[PROVIDERS.md](PROVIDERS.md)** — what's supported and what's requested;
  claim one so nobody builds it twice.
- 📥 Can't build it yourself? [Request a provider](https://github.com/rheeloaded/paperpull/issues/new/choose)
  and someone with that account may pick it up.

Every contribution keeps the **read-only, local, no-credentials** design — see
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Status & roadmap

- ✅ All **thirteen** apps work and are in regular use.
- 🔜 **More providers:** community-driven — see [PROVIDERS.md](PROVIDERS.md).
- 🔜 **Scheduled/assisted runs:** a monthly "nudge + sweep" (e.g. the 1st) that
  opens the login browsers and then runs discover + resume across every app once
  you've signed in — delete-safe, so it only grabs what's new. Fully unattended
  runs stay out of scope by design: the tools never store credentials or bypass
  2FA, so a human sign-in stays in the loop (long-session retailer apps may
  tolerate more automation than banks/cards).
- ✅ **Shared core:** the support code the apps used to duplicate now lives once
  in [`core/`](core) as `paperpull-core`. An app declares an `AppSpec` — its
  folders, routing, CSV columns and config defaults — and keeps only its
  orchestrator and its `*_site.py`. `tools/check_installs.py` reports whether
  your installs have drifted from the repo.

## Support

If PaperPull saves you time, you can support its development on Ko-fi:
**[ko-fi.com/rheeloaded](https://ko-fi.com/rheeloaded)** ☕. Entirely optional and
much appreciated — it doesn't change anything below.

## Legal

This project is for **personal archival of your own records**. It is not
affiliated with, endorsed by, or sponsored by any of the companies listed.
All product names and trademarks are the property of their respective owners.
Automating access to a website may be restricted by that site's Terms of
Service — you are responsible for how you use these tools. Provided **as-is,
without warranty of any kind** (see [LICENSE](LICENSE)).
