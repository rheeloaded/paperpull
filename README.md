# PaperPull

![Version](https://img.shields.io/github/v/tag/rheeloaded/paperpull?sort=semver&label=version&color=blue)
![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
[![Sponsor on GitHub](https://img.shields.io/badge/sponsor-on%20GitHub-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/rheeloaded)
[![Support on Ko-fi](https://img.shields.io/badge/Ko--fi-support%20this%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/rheeloaded)
[![Website](https://img.shields.io/badge/website-paperpull.net-4c8dff)](https://paperpull.net)

**Collect years of statements and receipts. Skip the endless downloading.**

PaperPull retrieves the statement and receipt history your banks, cards,
stores and utilities already hold, organizes it as PDFs on your own
computer, and turns your purchases and transactions into spreadsheets. It
is a family of small, **read-only** tools that sign in *alongside you*: you
type the password and answer the two-factor prompt in a real browser
window, and PaperPull reads what you can see. Free and open source, no
account, no cloud. Made for archiving (into
[paperless-ngx](https://docs.paperless-ngx.com/) or a folder of your own)
instead of clicking through each site by hand.

![The PaperPull control panel after a pilot run on a sample archive. Every name and amount is invented.](docs/panel.png)

**Website:** [paperpull.net](https://paperpull.net), with the [getting-started guide](https://paperpull.net/guide.html), the [provider directory](https://paperpull.net/providers.html) and the [Paperless-ngx tutorial](https://paperpull.net/paperless.html). **Download:** the [latest release](https://github.com/rheeloaded/paperpull/releases/latest), Windows 10 or 11 and macOS on Apple Silicon, Linux from source.

**It also turns those PDFs into spreadsheets.** Your receipts become one
long table of every item you have ever bought, across every store and every
account, with what it cost and when. The transactions inside your bank and
card statements are read out of the PDFs into a workbook, one row each, and
every statement is checked against its own printed balances, so a row you
are looking at is a row that adds up. One button on the control panel, or
one command. See [Every purchase in one spreadsheet](#every-purchase-in-one-spreadsheet)
and [The transactions inside your statements](#the-transactions-inside-your-statements).

Runs on **Windows and macOS** (and Linux), with the same commands on each.

**PaperPull is free, and it costs money to make.** There is a server and
domains to keep paid, developer accounts for the signed Mac build and the
Microsoft Store, the tools it is built with, and evenings on every provider
to build it and to keep it working as sites change. If it saves you time, you can show your
appreciation and support future development by
**[sponsoring on GitHub](https://github.com/sponsors/rheeloaded)** or
**[donating on Ko-fi](https://ko-fi.com/rheeloaded)**, or by buying the
**Microsoft Store edition** for $9.99, one time, the same program with a
signed installer and automatic updates. Or download it free from the
[Releases page](https://github.com/rheeloaded/paperpull/releases). Nothing
is held back from the free build. See [Support](#support).

Thirty-four providers are supported today, all built on the same pattern.
Thirteen more, AT&T, Wells Fargo, SBA, Verizon Mobile, SMUD, Golden 1, E*TRADE,
State Farm, Newrez, Kroger, GitHub, Meijer and American Family, are built and waiting for someone with an account to
test them ([#26](https://github.com/rheeloaded/paperpull/issues/26),
[#27](https://github.com/rheeloaded/paperpull/issues/27),
[#28](https://github.com/rheeloaded/paperpull/issues/28),
[#31](https://github.com/rheeloaded/paperpull/issues/31),
[#34](https://github.com/rheeloaded/paperpull/issues/34),
[#35](https://github.com/rheeloaded/paperpull/issues/35),
[#36](https://github.com/rheeloaded/paperpull/issues/36),
[#37](https://github.com/rheeloaded/paperpull/issues/37),
[#38](https://github.com/rheeloaded/paperpull/issues/38),
[#41](https://github.com/rheeloaded/paperpull/issues/41),
[#43](https://github.com/rheeloaded/paperpull/issues/43),
[#42](https://github.com/rheeloaded/paperpull/issues/42),
[#45](https://github.com/rheeloaded/paperpull/issues/45)):

| App | Provider | Documents | Notes |
|-----|----------|-----------|-------|
| [`affirm`](apps/affirm) | Affirm | Loan agreements (Truth in Lending), one per loan | JSON API from inside the page, nothing clicked; no monthly statement exists for a pay-over-time account |
| [`adp`](apps/adp) | ADP Workforce Now | Pay statements, W-2s | Statement services from inside the page, nothing clicked, real Edge/Chrome. Requested in [#46](https://github.com/rheeloaded/paperpull/issues/46) |
| [`aafmaa`](apps/aafmaa) | AAFMAA (Armed Forces Mutual) | Annual statements, policy docs | ASP.NET WebForms; one documented disclosure dialog |
| [`ally`](apps/ally) | Ally Bank | Account statements, tax forms | JSON API; same-dated statements named from the PDF |
| [`amazon`](apps/amazon) | Amazon (any country's store, `marketplace` setting) | Order invoices (full history) | Per-year order pagination |
| [`amfam`](apps/amfam) | American Family Insurance | Billing statements, policy documents, declarations, ID cards | **Untested, built without an account. Have one? [Help test it](apps/amfam/README.md#help-test-it-no-programming-needed)** Being tested by [@jpfieber](https://github.com/jpfieber). |
| [`amex`](apps/amex) | American Express | Statements, Year-End Summary | Click-nav SPA; in-memory session |
| [`att`](apps/att) | AT&T (Mobility, Fiber, Internet) | Monthly bills | **Pilot confirmed by [@watling777](https://github.com/watling777) in round eight.** The full run and a second account are the rounds still open ([#26](https://github.com/rheeloaded/paperpull/issues/26)) |
| [`anthem`](apps/anthem) | Anthem BCBS (Elevance, 14 Blue states) | EOBs, plan docs (all years), ID cards, letters | Health insurance (PHI); tRPC API, nothing clicked. Contributed by [@riordan](https://github.com/riordan) |
| [`capitalone`](apps/capitalone) | Capital One | Bank and card statements, tax forms, letters | Ported by [@davidrudnick](https://github.com/davidrudnick); fresh live pilot pending |
| [`chase`](apps/chase) | Chase (credit cards) | Card statements | Real Edge/Chrome; per-card accordions + year picker |
| [`citi`](apps/citi) | Citi (credit cards) | Monthly card statements | Statements API from inside the page, nothing clicked; the site lists about two years online |
| [`discovercard`](apps/discovercard) | Discover (credit cards) | Card statements | **Capital One is moving these accounts onto its own site. Once yours has moved this app can no longer read it** ([#13](https://github.com/rheeloaded/paperpull/issues/13)) |
| [`dominion`](apps/dominion) | Dominion Energy (VA) | Billing statements | Paginated MUI accordion; ~18-month limit |
| [`ebay`](apps/ebay) | eBay | Order receipts, ten years of purchase history | Order-details page rendered to PDF, nothing clicked, real Edge/Chrome. Requested in [#44](https://github.com/rheeloaded/paperpull/issues/44) |
| [`etrade`](apps/etrade) | E*TRADE | Statements, trade confirmations, tax forms | **Untested, built without an account. Have one? [Help test it](apps/etrade/README.md#help-test-it-no-programming-needed)** Being tested by [@watling777](https://github.com/watling777). |
| [`fairfaxwater`](apps/fairfaxwater) | Fairfax Water (VA) | Water bills | Mendix portal, driven like a person; PDFs for the last year only, so run it quarterly |
| [`fidelity`](apps/fidelity) | Fidelity Investments | Statements, trade confirmations, tax forms | Document Access Hub API from inside the page, nothing clicked; real Edge/Chrome |
| [`gap`](apps/gap) | Gap Inc. (Gap, Old Navy, Banana Republic, Athleta) | Order receipts | Lazy-loading history; ~13-month limit |
| [`kroger`](apps/kroger) | Kroger (Pick 'n Save, Metro Market, Fred Meyer, Ralphs and the rest) | Receipts, in-store, fuel, pickup and delivery | **Built against an account with no purchases yet. Have one? [Help test it](apps/kroger/README.md#help-test-it-no-programming-needed)** Being tested by [@jpfieber](https://github.com/jpfieber). Purchase-history API and receipt page, nothing clicked, real Edge/Chrome |
| [`github`](apps/github) | GitHub | Payment receipts (Pro, Copilot, Actions, Sponsors and the rest) | **Built against an account with no payments yet. Have one? [Help test it](apps/github/README.md#help-test-it-no-programming-needed)** Being tested by [@jpfieber](https://github.com/jpfieber). Receipt links fetched or printed, nothing clicked |
| [`golden1`](apps/golden1) | Golden 1 Credit Union | Statements, tax forms | **Untested, built without an account. Have one? [Help test it](apps/golden1/README.md#help-test-it-no-programming-needed)** Being tested by [@watling777](https://github.com/watling777). |
| [`meijer`](apps/meijer) | Meijer | Order receipts, in-store digital receipts where mPerks lists them | **Untested, built without an account. Have one? [Help test it](apps/meijer/README.md#help-test-it-no-programming-needed)** Being tested by [@jpfieber](https://github.com/jpfieber). Nothing clicked |
| [`mypay`](apps/mypay) | DFAS myPay | eRAS, CRSC, 1099-R, 1095 | Government pay system; JSON API, nothing clicked |
| [`mtb`](apps/mtb) | M&T Bank | Mortgage statements, escrow, 1098 | Own online banking; you list, app expands all years |
| [`netbenefits`](apps/netbenefits) | Fidelity NetBenefits (workplace 401(k)) | Quarterly or monthly statements, made to order | The site generates statements on request; the app requests each period and renders it, nothing clicked |
| [`navyfederal`](apps/navyfederal) | Navy Federal CU | Account statements | Per-account accordions; blob-tab PDFs |
| [`newrez`](apps/newrez) | Newrez | Mortgage statements, escrow analysis, 1098 | **Untested, built without an account. Have a Newrez mortgage? [Help test it](apps/newrez/README.md#help-test-it-no-programming-needed)** Being tested by [@watling777](https://github.com/watling777). |
| [`paylocity`](apps/paylocity) | Paylocity | **Pay statements** | Escher JSON API, enqueue-poll-fetch PDF; nothing clicked |
| [`pge`](apps/pge) | PG&E (Pacific Gas and Electric) | Billing statements | Salesforce portal with a paginated history. Contributed by [@appchamp](https://github.com/appchamp), a pagination repair being tested by [@watling777](https://github.com/watling777) |
| [`redcard`](apps/redcard) | Target RedCard / Circle Card (TD Bank) | Billing statements | Statements table; per-year switcher |
| [`robinhood`](apps/robinhood) | Robinhood | Account statements, tax docs | "View More" pagination |
| [`sba`](apps/sba) | SBA (MySBA Loan Portal) | Loan statements, 1098 | **Untested, built without an account. Have an SBA loan? [Help test it](apps/sba/README.md#help-test-it-no-programming-needed)** |
| [`schwab`](apps/schwab) | Charles Schwab | Statements, tax forms, letters, trade confirmations | Ported by [@davidrudnick](https://github.com/davidrudnick); fresh live pilot pending |
| [`smud`](apps/smud) | SMUD (Sacramento Municipal Utility District) | Monthly bills | **Untested, built without an account. Have one? [Help test it](apps/smud/README.md#help-test-it-no-programming-needed)** Being tested by [@watling777](https://github.com/watling777). |
| [`statefarm`](apps/statefarm) | State Farm | Bills, renewal notices, ID cards, receipts, policy documents | **Untested, built without an account. Have a policy? [Help test it](apps/statefarm/README.md#help-test-it-no-programming-needed)** Being tested by [@watling777](https://github.com/watling777). |
| [`target`](apps/target) | Target | Receipts (Online + In-Store) | Print-capture |
| [`tmobile`](apps/tmobile) | T-Mobile | Bill statements | Bill-history page; detailed-bill download |
| [`tsp`](apps/tsp) | Thrift Savings Plan | Participant statements, 1099-R | Secure Mailbox API from inside the page, nothing clicked; downloading marks the message read |
| [`ukg`](apps/ukg) | UKG Pro / UltiPro | **Pay statements** | Per-employer tenant; JSON-API, nothing clicked |
| [`usaa`](apps/usaa) | USAA | Statements | JSON-API enumeration |
| [`usbank`](apps/usbank) | U.S. Bank | Credit-card statements | Ported by [@davidrudnick](https://github.com/davidrudnick); fresh live pilot pending |
| [`verizon`](apps/verizon) | Verizon (Fios) | Bill statements | Real Edge (bot block); dropdown + CDP download |
| [`verizonmobile`](apps/verizonmobile) | Verizon Mobile (wireless) | Monthly bills | **Untested, built without an account. Have one? [Help test it](apps/verizonmobile/README.md#help-test-it-no-programming-needed)** |
| [`walmart`](apps/walmart) | Walmart | Receipts | Hardened against bot detection |
| [`wellsfargo`](apps/wellsfargo) | Wells Fargo | Account statements, tax documents | **Untested, built without an account. Have one? [Help test it](apps/wellsfargo/README.md#help-test-it-no-programming-needed)** |
| [`wealthfront`](apps/wealthfront) | Wealthfront | Statements, tax docs | |

> ⚠️ **Read this first:** these tools drive real, signed-in financial accounts.
> See [SECURITY.md](SECURITY.md) before you run *or* publish anything. In short:
> never commit your `*-browser-profile/` folder, your `config.json`, or any
> downloaded PDF. The `.gitignore` blocks them, don't override it.

## How it works (the shared design)

### The one decision everything follows from

Your documents live on the provider's site, and it will only hand them to a
browser that is already signed in. So PaperPull never tries to *be* you, it
works *beside* you. You sign in yourself, in a real browser window, and the
tool attaches to that window afterwards and reads.

```mermaid
flowchart TB
    you(["You"]) -->|"sign in · 2FA · device approval"| br["A real browser window<br/>its own profile · its own debugging port"]
    br -.->|"attaches over CDP, reads, never authenticates"| app
    subgraph app ["One app = one provider"]
        orch["Orchestrator<br/>discover → download → verify<br/>the same in every app"]
        site["provider_site.py<br/>selectors · URLs · download quirks"]
        core["paperpull-core<br/>naming · filing · state · CSV · PDF checks"]
        orch --> site
        orch --> core
    end
    app --> out[("Your folders<br/>PDFs + an index CSV")]
```

That single choice is why there is no password anywhere in this project, why
2FA and device approvals are never an obstacle, and why a provider tightening
its login breaks nothing here.

In practice that first step is `paperpull <app> login` (or the app's own
`login.bat` / `login.command`), which opens the browser for you, a plain
Chromium for most apps, or your own installed Edge/Chrome for the few sites
whose bot detection turns a fresh Chromium away (Walmart, Verizon, Chase).
Each app gets its own profile and its own debugging port, so several
signed-in browsers can sit open at once without colliding. Those profiles
are separate from your everyday browser on purpose, so each starts with no
extensions and no saved logins. They are real browser profiles, though, so
a password manager installed into one, from the extension store in the
window Login opens, stays there for every Login of that provider after.
It is one profile per provider, so the extension goes in once for each
provider you set up, not once for all of them.

**Everything a provider knows lives in one file.** `provider_site.py` holds
every selector, URL and download quirk for that site. The orchestrator around
it is the same in every app, and `paperpull-core` underneath it is
shared. When a provider redesigns, the repair is one file, never a rewrite,
and never a change to how documents get named, filed or tracked.

### What one run actually does

```mermaid
flowchart TB
    D["Discover<br/>list what the provider still has"] --> Q{"Already downloaded?"}
    Q -->|yes| S["Skip it"]
    Q -->|no| DL["Download the PDF"]
    DL --> V{"Is it a real PDF?"}
    V -->|no| MR["Manual Review<br/>flagged, never silently lost"]
    V -->|yes| F["Classify, name, file<br/>+ append to the index CSV"]
    F --> OK["Mark downloaded_ok<br/>sticky, survives deletion"]
```

Three plain-text files carry the state, and you can read all of them:

| File | Holds |
|------|-------|
| `discovery.json` | what the provider showed us this run |
| `progress.json` | what happened to each document, including the sticky `downloaded_ok` |
| `<Provider> Document Index.csv` | one row per saved document, for humans and spreadsheets (receipt apps also keep an `Order History.csv`, one row per line item) |

That last step is what makes a re-run safe. `downloaded_ok` is keyed to the
document, not to the file on disk, so you can import everything into
paperless-ngx, delete the PDFs, and the next run still skips them. It only
fetches what is genuinely new, and lists it in `new-this-run.txt`.

### Read-only by construction

Nothing that buys, sells, transfers, pays, deletes, or changes a setting is
ever clicked, and all site interaction lives in `provider_site.py` where it can
be read in one sitting. Every app that clicks enforces this deny-by-default, a
control must clear a blocklist (`FORBIDDEN_CONTROL_RE`) *and* match a document
allowlist (`SAFE_DOC_CONTROL_RE`), and the app's host allowlist refuses any
stored URL that points elsewhere. Sixteen apps click nothing at all (ADP, Affirm, Amazon,
Anthem, Citi, eBay, Fidelity, Gap, GitHub, Kroger, Meijer, myPay, NetBenefits, Paylocity, TSP, UKG), they read a JSON API or render a
page they navigated to. A repo-wide test checks every app's guard.
[SECURITY.md](SECURITY.md) spells out which app does which.

### One app, more than one person

In the control panel, **add a person** beside the Account box makes the
second person's account, and the Account box then runs every action against
it. From a terminal it is `paperpull <app> add-account spouse`, then
`paperpull <app> all --account spouse`. Either way it gets its own profile,
port and output folder beside the first one's, so no data mixes. Underneath it is a
`config.spouse.json` beside the app's `config.json`, which the app also takes
directly as `--config`, and the sign-in launcher takes the label too
(`login.bat spouse` / `./login.command spouse`). `python tools/add_account.py
spouse` does every app at once.

## Quick start

![Quick start](docs/quickstart.gif)

**One-shot setup** (creates a venv for every app + the GUI, installs the browser):

```bat
setup-all.bat        REM Windows
```

```bash
./setup-all.command  # macOS / Linux
```

Then either drive everything from the **[GUI control panel](gui)**, pick an
app and account, click an action, and watch the live output:

```bat
gui\run_gui.bat
```

![PaperPull control panel](docs/control-panel.gif)

…or run a single app from the terminal, with one command for all of them
(using `amex` as the example):

```bat
copy apps\amex\config.example.json apps\amex\config.json    REM then edit paths as needed
paperpull amex login            REM opens a browser, sign in yourself, leave it OPEN
paperpull amex pilot            REM download the newest few as a test
paperpull amex all              REM download everything available
paperpull amex resume           REM continue after an interruption
paperpull list                  REM every app it can see
```

`paperpull` is `paperpull.bat` on Windows and `./paperpull` on macOS and
Linux, or `python paperpull.py` anywhere. It finds the app by folder name,
slug or provider, runs it under its own environment, and passes anything else
straight through, so `paperpull chase all --year 2025 --account spouse` works.
The commands are `setup`, `login`, `discover`, `pilot`, `all`, `resume`,
`verify`, `diagnose` and `dry-run`. The panel offers the six of those a
person uses day to day, plus a Scope row (one year, or a date range) that
becomes the same `--year`, `--start-date` and `--end-date` every app takes.

Each app also has its own README with provider-specific details and quirks.
(Prefer to set apps up one at a time? `paperpull <app> setup`, or the app's
own `setup.bat` / `setup.command`.)

## Knowing when to run it again

`tools/status.py` reads the state each app already keeps and reports how current
every archive is. Copy it and `status.bat` next to your install folders and run
it. It downloads nothing and changes nothing.

```
PROVIDER                     DOCS  NEWEST          AGE  ISSUES     STATUS
Some Payroll                   12  2026-06-18     72 d  2x month   !! OVERDUE
A Bank                         97  2026-06-30     60 d  monthly    *  due
A Mortgage                     93  2026-07-31     29 d  monthly       current
A Shop                        667  2026-08-13     16 d  -             ongoing
```

It reports the archives you **have**. Nobody holds an account with every
provider, so a folder you never set up, or one left behind by a closed account,
is left out entirely rather than listed as missing or overdue. An archive that
was set up but never downloaded anything is called out by name, since that is
the one state a single run fixes.

It answers "is something new probably waiting" rather than "when did I last run
this", which are different questions. A run that only verified existing files
still updates a timestamp while telling you nothing about whether a new
statement exists. So the signal is the date of the newest document you actually
hold, measured against how often that provider issues them.

The cadence comes from your own history and is measured per account, so nothing
has to be configured, and a provider that moves from monthly to quarterly
corrects itself. Measuring per account matters: one bank folder can cover
several accounts, and pooling their dates makes a monthly cycle look weekly.
Receipt archives are shown without a due date, because purchases arrive
irregularly and "40 days overdue" would be noise.

### It also looks for holes in the middle

Being up to date is not the same as being complete. An archive can hold a
document from last week and still be missing whole years behind it, which is
exactly what happened twice while building this: one mortgage archive held a
single year of a seven year history, and a payroll archive quietly defaulted to
year to date. Both looked healthy by their newest document.

So each series is also checked for periods that look missing from the middle:

```
Possible gaps. A run that looks current can still be missing
periods in the middle, so these are worth a look.
  A Bank
     2025-03-18 to 2025-05-17   1 missing   3 series, including Savings
     2026-01-01 to 2026-04-02   2 missing   3 series, including Savings
```

The hard part is not finding gaps, it is not inventing them. Plenty of real
documents arrive irregularly, insurance ID cards and policy renewals among
them, where a long quiet stretch means nothing was issued rather than something
was missed. Flagging those would train you to ignore the report, so a series
has to earn an opinion first: at least six documents, a median interval of ten
days or more, and at least 65 percent of its intervals close to that median.
Only then is an interval roughly twice the usual one reported, and it is
reported as possible rather than certain.

Windows shared by several series are grouped, because one account missing a
month is usually a quiet month, while the same window missing across several at
once is what a run that failed part way looks like.

`--html` also writes a `status.html` dashboard you can bookmark, and `--quiet`
prints only what needs attention. The dashboard reads no document contents and
carries no amounts or account numbers, but it does list which providers you
hold accounts with, so it belongs with your installs and is gitignored here.

## Every purchase in one spreadsheet

The receipt apps (Amazon, Target, Walmart, Gap) record every line item they
see while downloading, in an `<Provider> Order History.csv` beside the PDFs.
`tools/export_purchases.py` gathers all of them into one workbook, one row
per item across every provider and account, newest first, with an Orders
sheet and a Summary of spend per provider per year. Amounts are numbers, so
Excel can sum them. Nothing reads a PDF and it takes about a second.

```
python tools/export_purchases.py --root "C:\path\to\your\installs"
```

The panel has the same thing on its **Spreadsheet** tab, one button, with a
dropdown for one provider at a time (`Amazon Purchases.xlsx`). The file is
rebuilt from scratch each time, so edit a copy, not the original.

## The transactions inside your statements

A statement archive holds PDFs, and the transactions are inside them.
`tools/export_transactions.py` opens each PDF a statement archive's index
knows about, reads it line by line, and keeps the lines that have the shape
of a transaction, a date, a description and an amount. Nothing in it is
written for one bank. What makes it trustworthy is the statement itself.
Every statement prints a beginning and an ending balance, and the
transactions between them have to add up.

```
python tools/export_transactions.py --root "C:\path\to\your\installs"
```

Where the statement carries a running balance column, the sign of every
amount is read off the balance and the statement reconciles to the cent by
construction. Where it prints signed amounts, they are summed as printed and
checked against every balance pair the statement shows, which is how a card
statement that prints its summary three times is read right. A statement
covering two accounts is reconciled one account at a time. A statement that
does not add up is still exported, with the difference in the Statements
sheet, so you know which rows to doubt. On the author's archive, every USAA
and Navy Federal statement and 120 of 128 American Express statements
reconcile. Brokerage statements never will, since their balances include
market movement, and the sheet says so.

Amounts are the effect on the balance. Money in is positive, money out is
negative, for a bank account and a card alike. Each PDF is read once and
remembered in a cache beside the installs, so the first build of a big
archive takes minutes and the next takes seconds. The panel's Spreadsheet
tab has this too, under Statements, streaming its progress.

## Windows and macOS

**Both have a package.** Every release on the
[Releases page](https://github.com/rheeloaded/paperpull/releases) carries
`PaperPull-<version>-setup.exe` for Windows, which installs the control
panel, the shared core and every provider into your own user folder with no
admin rights and no Python on the machine, and `PaperPull-<version>.zip`, the
same folder for anyone who would rather not run an installer. The package
is x64 and runs on Windows on ARM (a Snapdragon laptop, say) under the
emulation Windows 11 provides, where the browser it drives is your own
native Edge or Chrome and the Python side spends its life waiting on it. A
native ARM64 build is one flag away in `packaging/build_windows.py` and
will be shipped when someone needs it.

**Two Windows editions, one program.** The GitHub release is free. The
Microsoft Store edition is the same package from the same build, for
$9.99 one time, and what the price buys is convenience, a Store-signed
package that installs with no warning, updates through the Store, and
uninstalls cleanly, plus the knowledge that it keeps the project going.
Nothing is held back from either edition. The AGPL permits selling copies and the source stays public. For macOS
there is `PaperPull-<version>-arm64.dmg`, Apple Silicon only, signed and
notarized, so it opens with no warning. Drag PaperPull to Applications and
double-click it. The Windows installer is not yet code-signed, so Windows
shows its SmartScreen prompt the first time. See
[Code signing policy](#code-signing-policy) below.

For a checkout of this repository, one download covers both. The two
double-click files each app keeps, and the one-shot setup, come in both
flavors, and everything else is the same `paperpull` command on either:

| Task | Windows | macOS / Linux |
|------|---------|---------------|
| One-shot setup | `setup-all.bat` | `./setup-all.command` |
| Set up one app | `setup.bat` | `./setup.command` |
| Sign in | `login.bat` | `./login.command` |
| Test run | `paperpull amex pilot` | `./paperpull amex pilot` |
| Full run | `paperpull amex all` | `./paperpull amex all` |
| Control panel | `gui\run_gui.bat` | `gui/run_gui.command` |

A second account is the same on both: `paperpull amex all --account spouse`.

Only one thing genuinely differs. macOS keeps Playwright's browser inside an
app bundle and in a different cache directory, and a couple of providers need
a branded Edge/Chrome to get past their bot protection, that lookup lives in
`paperpull_core.browser` and is handled for you.

### Getting a checkout onto a Mac

To use PaperPull, the `.dmg` above is the way. This is for a checkout of the
repository.

**`git clone` is the smoothest route**, it preserves the scripts' executable
bit and macOS does not quarantine it.

If you download a release archive instead, prefer the **`.tar.gz`**: it keeps
the executable bit, while a `.zip` drops it. After unpacking a download,
macOS may also quarantine the scripts, so a double-click reports *"cannot be
opened because it is from an unidentified developer."* Both are cleared in one
go:

```bash
xattr -dr com.apple.quarantine .
chmod +x setup-all.command apps/*/*.command gui/*.command
```

## Requirements

- **Windows, macOS, or Linux**
- For the Windows installer or the macOS `.dmg`, nothing else. They carry
  their own Python.
- For a checkout, Python 3.11+ and Playwright (installed per app by the
  setup script)
- A Chromium-family browser for the few providers that need a real one
  (Chrome, Edge, Brave, Vivaldi or Opera). Safari and Firefox cannot be
  driven this way.

## Contributing a provider

No one has accounts everywhere, so **PaperPull grows when people add the
providers they use.** If a bank, card, brokerage, utility, telecom, or retailer
you use isn't here yet, you're the ideal person to add it:

- 📖 **[Adding a provider](docs/adding-a-provider.md)**, a step-by-step guide
  (clone the closest app, rewrite one file, stay read-only, test, submit).
- 📋 **[PROVIDERS.md](PROVIDERS.md)**, what's supported and what's requested;
  claim one so nobody builds it twice.
- 📥 Can't build it yourself? [Request a provider](https://github.com/rheeloaded/paperpull/issues/new/choose)
  and someone with that account may pick it up.

Every contribution keeps the **read-only, local, no-credentials** design, see
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Status & roadmap

- ✅ All **thirty-four** apps pass their tests, and the thirteen scaffolds theirs, more than 1,500 of them across the
  repo. Twenty-six are in regular use by the author. The other seven (Ally,
  Anthem, Capital One, Discover, PG&E, Schwab, U.S. Bank) were contributed
  by people who hold those accounts, and the four marked in the table above
  are awaiting a fresh live pilot since they were ported.
- ✅ **Packaged.** A Windows installer and a signed, notarized macOS app,
  both built by GitHub Actions from the tagged commit, with checksums. A
  Microsoft Store listing and free open-source code signing for Windows are
  in progress.
- 🔜 **More providers:** community-driven, see [PROVIDERS.md](PROVIDERS.md).
- 🔜 **Scheduled/assisted runs:** a monthly "nudge + sweep" (e.g. the 1st) that
  opens the login browsers and then runs discover + resume across every app once
  you've signed in, delete-safe, so it only grabs what's new. Fully unattended
  runs stay out of scope by design: the tools never store credentials or bypass
  2FA, so a human sign-in stays in the loop (long-session retailer apps may
  tolerate more automation than banks/cards).
- ✅ **Shared core:** the support code the apps used to duplicate now lives once
  in [`core/`](core) as `paperpull-core`. An app declares an `AppSpec`, its
  folders, routing, CSV columns and config defaults, and keeps only its
  orchestrator and its `*_site.py`. `tools/check_installs.py` reports whether
  your installs have drifted from the repo.

## Code signing policy

The Windows installer is built from a tagged commit of this repository by the
[Windows package](.github/workflows/build-windows.yml) workflow on a clean
GitHub runner, never from a developer's machine, and the checksums of what it
produced are published beside it. Signing goes through that same workflow so a
signed binary can only ever come from code that is in this repository.

This program does not transfer any information to other networked systems
unless specifically requested by the user. The only sites it contacts are the
providers you sign in to yourself, and the only download it ever offers is a
browser, at sign-in, with your agreement. The full statement is
[PRIVACY.md](PRIVACY.md).

Team roles, current status and the full policy are in
[docs/code-signing.md](docs/code-signing.md).

## Support

PaperPull is free and open source, and it costs real money and real time
to develop. There is a server and domain names to keep paid, developer
accounts for the signed and notarized Mac build and for the Microsoft Store
listing, and the tools it is built with. Every one of the thirty-odd
providers took evenings to build, and each one needs repairing when its
site changes, which they do.

If PaperPull saves you time, there are three ways to show your appreciation
and support future development. All are optional, and none changes what
the free build does.

- **Sponsor on GitHub:** **[github.com/sponsors/rheeloaded](https://github.com/sponsors/rheeloaded)**, one-time or monthly, from a card you already have on GitHub.
- **Donate on Ko-fi:** **[ko-fi.com/rheeloaded](https://ko-fi.com/rheeloaded)** ☕
- **Buy the Microsoft Store edition** for $9.99, one time, the same
  program from the same build, with a signed installer that opens with no
  warning and updates through the Store. The listing is in review and will
  be linked here once it is live. It unlocks nothing the free build lacks.

You can also help without spending anything: test a provider you hold an
account with (see [PROVIDERS.md](PROVIDERS.md)), report what breaks, or
contribute one. That is worth as much as a donation.

## Thanks

PaperPull only reaches the providers people bring to it. These people
built one, tested one against an account the author does not hold, or
found a bug and diagnosed it to the line.

- [@davidrudnick](https://github.com/davidrudnick), the Capital One, U.S.
  Bank and Charles Schwab apps, and a long run of panel fixes.
- [@riordan](https://github.com/riordan), the Anthem BCBS app, the first
  health insurer.
- [@appchamp](https://github.com/appchamp), the PG&E app.
- [@marecabo](https://github.com/marecabo), Amazon's legal invoice PDFs on
  the German store.
- [@watling777](https://github.com/watling777), the tester behind AT&T,
  SMUD, Golden 1, E*TRADE, State Farm and Newrez, seven providers' worth of
  surveys and pilots in a weekend, and the PG&E pagination bug.
- [@dertbv](https://github.com/dertbv), three exporter and Navy Federal
  bugs, each diagnosed so exactly there was nothing to add.
- [@liamrotheram](https://github.com/liamrotheram) and
  [@OberstK](https://github.com/OberstK), Amazon outside the United States.
- [@jpfieber](https://github.com/jpfieber), who asked for eBay and became
  PaperPull's first sponsor before it was even built.

If you tested a provider and are not here, say so on the issue and you
will be.

## Legal

This project is for **personal archival of your own records**. It is not
affiliated with, endorsed by, or sponsored by any of the companies listed.
All product names and trademarks are the property of their respective owners.
Automating access to a website may be restricted by that site's Terms of
Service, you are responsible for how you use these tools. Provided **as-is,
without warranty of any kind**.

**License.** PaperPull is free software under the
[GNU Affero General Public License, version 3](LICENSE). You can run it,
read it, change it and share it. If you distribute a changed version, or run
one as a service for other people, the same license applies to what you
distribute, source included. Contributions before 2026-09-18 were made under
MIT and that permission is kept, see [NOTICE.md](NOTICE.md).

**Name.** The PaperPull name is not part of the license. A modified version
needs its own name, so that anything called PaperPull is this project. What
that allows and what it doesn't is in [TRADEMARK.md](TRADEMARK.md).
