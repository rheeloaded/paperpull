# UKG Pay Statements Downloader (local, supervised)

Downloads your **pay statements** from your employer's UKG site and saves them
as PDFs, plus an index CSV:

- `UKG Document Index.csv` — one row per downloaded PDF

Everything runs **locally**. Nothing is sent to any external AI API or
third-party service. You sign in to UKG **yourself**; the tool never touches
your credentials, your SSO, or any verification prompt.

> ⚠️ **Pay statements are the most sensitive documents this project handles.**
> They typically carry your full name, home address, employer, salary, tax
> withholding, and often the last four digits of a bank account. The index CSV
> deliberately records none of that — only what is needed to find and verify a
> file locally. Never commit the PDFs, the CSV, or your `config.json`.

## First: tell it where your UKG lives

Unlike every other app here, **UKG has no single web address.** Each employer
runs its own tenant, and UKG ships several products with different pages:

| Product | Address looks like |
|---|---|
| UKG Pro (formerly UltiPro) | `https://yourcompany.ultipro.com` |
| UKG Ready (formerly Kronos Workforce Ready) | `https://secure6.saashr.com` |
| UKG Workforce Central | `https://yourhost/wfc/...` |

Copy `config.example.json` to `config.json` and set **`base_url`** to the
address you see in your browser once you are signed in. It is not in the code
on purpose: it varies per employer, and it identifies your employer, so it
stays out of the repo.

## Signing in — however your company does it

Some companies use a UKG username and password. Others hand off to corporate
single sign-on (Okta, Microsoft Entra/Azure AD, Ping, and so on), often with
an MFA prompt. **Both work the same way here, and neither involves this
tool:** `login.bat` opens an ordinary browser at your UKG address, you sign in
however your company works, and the tool then attaches to that already-signed-in
session over the Chrome DevTools Protocol.

There is no login automation in this app to break or to mishandle a password.

## Setup / workflow

| Step | Windows | macOS / Linux | What it does |
|------|---------|---------------|--------------|
| 1 | `setup.bat` | `./setup.command` | Creates `.venv`, installs Playwright + the shared core |
| 2 | edit `config.json` | same | Set `base_url` to your employer's UKG address |
| 3 | `login.bat` | `./login.command` | Opens a browser; sign in, **leave it open** |
| 4 | `run_pilot.bat` | `./run_pilot.command` | A few newest statements, then **stops** for your inspection |
| 5 | inspect the PDFs/CSV | same | You approve before anything bigger runs |
| 6 | `run_all.bat` | `./run_all.command` | Everything available (asks for confirmation) |
| any time | `resume.bat` | `./resume.command` | Continue after an interruption; never redoes finished work |
| any time | `verify_documents.bat` | `./verify_documents.command` | Re-validate every indexed PDF |

Port **9234** keeps this separate from the other apps, so several signed-in
browsers can be open at once.

## Where files land

- `Pay Statements\` — the pay stubs
- `Manual Review\` — anything that failed validation

**Not yet: W-2s and other tax forms.** They live in a different part of UKG
(Menu → Myself → Pay → Tax Forms / W-2), which this app does not read yet.
The routing and the classification rules for them are already in place, so
adding them is a change to `ukg_site.py` alone — a `Tax Documents\` folder
appears the moment one is actually downloaded.

## Safety

- **Read-only, deny-by-default.** A control is clicked only if it clears a
  blocklist *and* matches the document allowlist. On a payroll site the
  blocklist matters more than anywhere else in this project: direct deposit,
  bank/routing details, W-4 withholding, address and password changes, benefit
  enrolment, time-off requests and timecard submission are all explicitly
  refused, and anything unrecognised is refused too.
- You sign in; the tool never handles credentials, SSO, or MFA.
- Sequential processing with polite randomized delays.
- Progress written atomically after every document; interrupted runs continue
  with `resume`.
- Existing PDFs are never overwritten.

## When UKG changes its site

All UKG selectors live in **`ukg_site.py`** only. Run
`python ukg_docs.py --diagnose` after signing in to capture the current page
structure into `Diagnostics\`, then repair that one file.

## Tests

```
.venv\Scripts\activate
pytest
```
