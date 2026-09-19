# PaperPull on the Microsoft Store

PaperPull follows the paint.net model. The Store edition costs $2.99 and buys
convenience, a Store-signed package that installs with no warning, updates
through the Store, and uninstalls cleanly. The GitHub edition is the same
program, free, built by the same workflow from the same tag, and unsigned
until free open-source signing comes through. Nothing is held back from
either. The source is public under the AGPL, which permits selling copies,
and the PaperPull name is a trade name (`TRADEMARK.md`), so no one else can
list a "PaperPull" on the Store.

This file is the playbook. The first half is what the maintainer does in
Partner Center. The second half is the listing text and the certification
notes, ready to paste.

## What the repository already does

The Windows package workflow builds `PaperPull-<version>.msix` on every
tag, unsigned, which is what the Store wants, since the Store signs on
submission. The manifest declares the `runFullTrust` capability, Windows
10 build 19041 as the floor, x64, and the four logo assets the Store
requires, all drawn from `packaging/paperpull.ico`. It proves the package
installs and runs by signing a throwaway copy on the runner and launching
it. The package identity, which the Store assigns when the name is
reserved, comes from four repository variables so the source never
carries it.

The package is x64. The Store offers an x64 package to ARM64 devices too,
where it runs under emulation, so one package covers every Windows 11
machine. A native ARM64 package is `python packaging/build_windows.py
--arch arm64 --msix` on an ARM64 machine (a `windows-11-arm` runner, if it
ever moves into the workflow). It comes out as `PaperPull-<version>-arm64.msix`
with `ProcessorArchitecture="arm64"`, and a submission can carry both
packages side by side under the same identity and version, the Store
picking per device. Nothing else changes.

| Variable | What goes in it | Where it comes from |
|----------|-----------------|---------------------|
| `MSIX_IDENTITY_NAME` | `Package/Identity/Name`, like `12345RheeLoaded.PaperPull` | Partner Center, Product identity |
| `MSIX_PUBLISHER` | `Package/Identity/Publisher`, `CN=<a GUID>` | Partner Center, Product identity |
| `MSIX_PUBLISHER_DISPLAY` | Publisher display name | Partner Center, Account settings |
| `MSIX_DISPLAY_NAME` | The reserved name, spelling and case exact | Partner Center, the reservation |

## Steps, in order

1. **Open a developer account** at partner.microsoft.com, individual type,
   one-time $19. Individual is right for a single developer selling their
   own work. See the policy note below on why individual is defensible.
2. **Reserve the name** "PaperPull" under Apps and games, New product,
   MSIX or PWA app. The reservation is what makes the name yours on the
   Store.
3. **Read the identity.** Product management, Product identity. Copy the
   three values into the repository variables above, and the reserved
   name into the fourth. Settings, Secrets and variables, Actions,
   Variables.
4. **Build.** Push a tag, or run the Windows package workflow by hand on
   main. Download the `PaperPull-msix-unsigned` artifact. That `.msix` is
   the submission.
5. **Run the certification kit locally**, once, before the first
   submission. Windows App Certification Kit ships with the Windows SDK.
   It catches manifest and asset problems in minutes that the Store takes
   a day to report.
6. **Create the submission.** The sections and what goes in each are
   below. Save each as you go, they are independent.
7. **Submit.** Certification takes one to three business days. A failure
   comes with a report naming the policy. Fix, rebuild, resubmit.
8. **After it is live,** put the Store link in the README and the release
   notes, and add `ms-windows-store://pdp/?productid=<id>` to the panel's
   footer as the update path for Store installs.

Every later release is step 4 and a new submission with the new `.msix`.
The version in the manifest is `<major>.<minor>.<patch>.0` from `VERSION`,
and the Store requires each submission's version to be higher than the
last.

## The submission, section by section

**Pricing and availability.** Base price $2.99 (the Store's 2.99 tier).
All markets, or the United States and English-speaking markets to start,
since every provider is a US site. No free trial. Visibility public.

**Properties.** Category, Productivity. Subcategory, Personal finance if
offered. Privacy policy URL,
`https://github.com/rheeloaded/paperpull/blob/main/PRIVACY.md`. Website,
`https://github.com/rheeloaded/paperpull`. Support contact, the
repository's Issues page. The product does not collect data. The product
does not use any capability that requires an additional declaration
beyond runFullTrust. System requirements, Windows 10 build 19041 or
later, x64 (runs on ARM64 under emulation), a Chromium-based browser
(Edge is always present), about 250 MB of disk.

**Age ratings.** The IARC questionnaire. No violence, no sexual content,
no gambling, no user interaction with other people, no sharing of
location, and the product does not itself contain the user's financial
information (it saves documents the user downloads from their own
accounts, to their own disk). Expect Everyone / 3+.

**Packages.** Upload the `.msix`. The `runFullTrust` capability is a
restricted capability and Partner Center asks for a justification. Use
this.

> PaperPull is a desktop application packaged as MSIX. It runs a local web
> server for its control panel (Python, bound to 127.0.0.1 only), launches
> the user's own installed browser with a separate profile, and attaches
> to that browser over the Chrome DevTools Protocol to read pages the user
> has signed in to. Those three things, a local listener, launching
> another program, and connecting to its debugging port, require full
> trust. The application makes no network connections of its own except
> to the provider sites the user signs in to, and an optional one-time
> download of a Chromium build from Playwright's CDN if no compatible
> browser is installed, which it asks about first.

**Store listing.** Below.

**Notes for certification.** Below. This one matters most.

## Listing text

**Name.** PaperPull

**Short description** (up to 100 characters).

> Download your own receipts and statements as PDFs. Read-only, runs on your computer.

**Description.**

> PaperPull downloads your own statements and receipts as PDFs from the banks, cards, brokerages, utilities and stores you already use, so you can archive them instead of clicking through each site by hand. Thirty-one providers today, from American Express and Chase to Amazon, Fidelity and Target.
>
> It never asks for your password. You sign in yourself, in a real browser window, and PaperPull attaches to that window afterward and reads. Two-factor prompts and device approvals are yours to answer, the way they should be. Nothing that pays, transfers, buys, sells or changes a setting is ever clicked. Every provider's code is built around a blocklist of those words, and the whole thing is open source so you can check.
>
> Everything stays on your computer. There is no account, no cloud, no telemetry. Your documents land in folders you choose, named by date, provider and kind, ready for a filing system or for paperless-ngx.
>
> It remembers what it has downloaded, so a rerun fetches only what is new, even after you have moved the old files somewhere else. A Status tab tells you which archives are due and where a period looks missing from the middle. A Spreadsheet tab turns your receipts into one long table of purchases, and reads the transactions out of your statement PDFs, checking each one against its own printed balances.
>
> This is the Store edition of a free, open-source program. The same program is on GitHub under the AGPL at no charge. Buying it here gets you a signed package that installs without a warning and updates through the Store, and supports the work.

**What's new** (per release, from the changelog's top entry).

**Product features** (bullet list field).

- Thirty-one providers, banks, cards, brokerages, payroll, insurance, utilities, retailers
- You sign in, it only reads. Never sees a password, never clicks pay
- Delete-safe. Move the PDFs anywhere, a rerun fetches only what is new
- Status tab shows what is due and where history has a gap
- Every purchase in one spreadsheet, and statement transactions reconciled to the cent
- Everything stays on your computer. No account, no cloud, no telemetry
- Open source under the AGPL

**Keywords.** statements, receipts, PDF, download, archive, bank statements, paperless, invoices, records, personal finance

**Screenshots.** `docs/store/1-panel.png`, `docs/store/2-setup.png`,
`docs/store/3-spreadsheet.png`, 1920 by 1080, taken against a folder with
no personal data in it. Retake them after any change to the panel.

**Copyright and trademark info.** Copyright (c) 2026 Bryan Rhee. PaperPull is a trade name of Bryan Rhee. Provider names are the property of their owners, and PaperPull is not affiliated with any of them.

## Notes for certification

This is the field the testers read. It has to head off the two things
that would fail the product otherwise, that the app cannot be fully
exercised without a real financial account, and that it involves signing
in to financial sites.

> PaperPull is a document downloader. It reads statements and receipts
> from accounts the user already holds, and saves them as PDFs on the
> user's own computer.
>
> What can be tested without any account. The application launches, the
> control panel opens in the default browser at http://127.0.0.1:8765,
> the first-run screen lists every supported provider and creates a folder
> per provider you tick, the Status and Spreadsheet tabs work on an empty
> folder, and every action on a provider that has not been signed in to
> ends with a clear message rather than an error. No network connection
> is made until a provider's Login is clicked.
>
> What cannot be given as a demo account. Each provider is a third-party
> financial or retail site (American Express, Chase, Fidelity, Amazon,
> and so on). Sign-in happens in a browser window on that site, with the
> user's own credentials and two-factor prompt, and PaperPull never
> receives, stores or transmits those credentials. There is no PaperPull
> account and no PaperPull server, so there is no demo account to give.
> The privacy policy at the URL above states this in full.
>
> The application is open source (AGPL-3.0). The complete source of this
> exact package, and the GitHub Actions workflow that built it from a
> tagged commit on a clean runner, are at
> https://github.com/rheeloaded/paperpull.

## The policy note on account type

Store policy 10.8.3 says a product that "requires financial account
information" must come from a company account, and defines that as
entering bank or card account information, PINs, passwords, and the like
into the product. PaperPull does not take any of those. The user types
their password into the bank's own site, in a browser window, and the
product only reads the pages that follow. It holds no field for a
password, an account number or a card, and its privacy policy says so.
That is the ground for an individual account. If certification reads it
the other way, the remedy is a company account, which costs $99 and needs
business verification, and the listing text does not change.

Policy 10.8.7 asks only that a price not be irrationally high for what
the product does. The older Store rule against charging for open-source
software that is free elsewhere was withdrawn in 2022 after Microsoft
clarified it was aimed at people listing other people's projects. Krita,
which is GPL and free from its own site, has charged on the Store for
years under exactly this model.

## What the Store edition does not change

The package is the same one the GitHub release carries, built by the same
run, which publishes the `.msix` checksum beside the installer's. There is no Store-only code path, no license check, and
no feature behind the price. A Store buyer who wants the GitHub edition
later loses nothing, and the other way around. Both read the same
`%APPDATA%\PaperPull\settings.json` and the same download folders.
