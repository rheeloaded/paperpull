# Anthem BCBS — member document downloader (READ-ONLY)

Downloads your Anthem Blue Cross Blue Shield member documents as PDFs, read-only
and delete-safe, part of [PaperPull](../../README.md):

- **Explanation of Benefits (EOB)** — Medical, Pharmacy and Chiropractic (and EOB
  Checks).
- **Member documents** — plan and benefit documents across **every coverage year**
  the portal keeps (plan confirmations, Evidence of Coverage, Certificate of
  Coverage, and a 1095-B tax form if the account has one).
- **ID / insurance cards** — each covered member's digital card, front and back,
  as one PDF per card.
- **Letters** — every secure Message Center letter, read and unread.

Every one of these is fetched by the portal's own read-only member API from inside
your signed-in page — **nothing on the page is ever clicked, submitted or
confirmed.**

> **Built from a logged-in recon of the live portal (2026-08-31); not yet run
> end to end.** The EOB list and PDF endpoints and their request inputs were
> confirmed against the live site, but the API's **response field names were not
> observed** (the recon harness blocked the replay). The collector parses them
> defensively and will name the real fields on the first pilot. Run
> `diagnose.bat`, then `run_pilot.bat`, and check the PDFs before a full run.
>
> One app, many states. Anthem/Elevance operates the Blue Cross Blue Shield
> plans in 14 states (CO, CT, GA, IN, KY, ME, MO, NV, NH, NY, OH, VA, WI); they
> share this member portal, so this app should serve any of them unchanged.

## Read this first

The Anthem portal is behind mandatory MFA and, at the edge, Akamai Bot Manager.
Two things follow.

- **You sign in, and you check "remember this device."** The tool never handles
  your password or your one-time code. Signing in yourself in a real, branded
  Chrome/Edge (which `login.bat` launches) with a persistent profile is also the
  posture that passes the bot check; the remembered-device cookie then lets
  later runs skip the MFA prompt.
- **EOBs are Protected Health Information.** They name providers, dates of
  service, diagnoses and claim amounts. Keep the output folder somewhere safe.

## Read-only by design (a health portal can change your care and coverage)

The member portal can change your PCP, request an ID card, refill a
prescription, appeal a claim, enroll you in paperless delivery, pay a premium
and message your care team. This tool does none of it. Concretely:

- **Nothing on the page is clicked.** Every document — EOB, member document, ID
  card and letter — is fetched by the portal's own API from inside the signed-in
  page. There is no click, no form submit, no dialog confirmation, and the only
  navigation is to a read-only page to capture the session; a test enforces that
  the code never fills, submits, confirms or clicks anything.
- **The guard refuses coverage and account controls outright.** Find care,
  change PCP, refill, appeal, grievance, prior authorization, message, schedule,
  enroll, switch plan, pay premium, go paperless, plus every "change", "update",
  "consent", "agree", "submit" and "authorize" variant.
- **A document is fetched by a validated identity, never a URL.** The identity
  is `claimType|claimId|docKind`: the claim type and kind must be ones this app
  knows and the claim number is validated to Anthem's alphanumeric shape, so the
  request is built from values this app recognises rather than any stored string.
- **The opaque per-document token never leaves the page.** Anthem authorises a
  PDF fetch with a per-document `eobId` token minted into the page. It is read
  and spent inside the page in one expression and is **never stored**; the
  identity above is looked up fresh at download time.
- **A session that expires — or an Akamai block page — stops the run** and says
  so, rather than filing everything as "needs manual review" and exiting as
  though it worked.

## Setup

```bat
setup.bat                 REM one-time: venv + Playwright
login.bat                 REM opens a real browser on port 9242 - sign in yourself
diagnose.bat              REM read-only look at what is on the page; downloads NOTHING
run_pilot.bat             REM download the newest few as a test, then stop
run_all.bat               REM download everything in scope (asks for YES)
```

`login.bat` opens Anthem's sign-in page (`www.anthem.com/account-login/`). Sign
in the way you normally do, complete the MFA yourself (check "remember this
device"). Anthem redirects you to `membersecure.anthem.com`; open the
**Explanation of Benefits Center** there and **leave the browser window open**.
The tool attaches to that already-signed-in member tab and reads only what you
can see. It never handles your credentials or your MFA code.

If a run stops saying the session expired or was blocked, sign in again and use
`resume.bat` — finished documents are never re-fetched.

## Documents captured

| Folder | Contents |
|---|---|
| `EOBs\` | Medical, Pharmacy and Chiropractic Explanation of Benefits (and EOB Checks) |
| `Plan Documents\` | Plan / benefit documents across every coverage year (plan confirmations, Evidence of Coverage, Certificate of Coverage). The filename carries the coverage period, e.g. `(2025 H1)` |
| `Authorizations\` | Authorization / referral documents (created on demand) |
| `Tax Documents\` | 1095-B health-coverage form, if the account has one (created on demand) |
| `ID Cards\` | Each covered member's digital ID / insurance card (front and back) as one PDF, named per member (created on demand) |
| `Letters\` | Secure Message Center letters, one PDF per message (created on demand) |
| `Other Documents\` | Anything else recognised but unrouted (created on demand) |
| `Manual Review\` | Files that failed PDF validation |

Every surface is fetched the same way — by the portal's own authenticated member
API, from inside the signed-in page, nothing clicked. `run_all` (and `--all`)
fetches **all** of them. Each also has its own command:

```
python anthem_docs.py --documents    member documents, all coverage years
python anthem_docs.py --id-cards      digital ID / insurance cards
python anthem_docs.py --letters       secure Message Center letters
```

The member documents span **all coverage periods** the portal exposes, so prior
years' plan and tax documents come down alongside the current year's. A document
already downloaded once is never re-fetched — even a prior-year one — so a later
run only picks up what is new.

**Letters are read-safe.** The secure-message list already carries every message's
body, so no message is ever opened, and the tool never marks a message read: a
run leaves your unread count exactly as it found it (verified against the live
portal). Unread letters are downloaded and stay unread.

Filenames: `YYYY-MM-DD Anthem Explanation of Benefits - <Patient> - <ClaimType>
Claim <number>.pdf`. On a plan covering more than one person, the patient name
keeps each member's EOBs distinguishable; the claim number keeps two claims that
share a date distinct. An EOB and its reimbursement EOB Check stay distinct too.
(The patient name is captured best-effort; if the portal's field name differs
from what is expected, the pilot's filenames will lack the name and the real
field is added then.) Naming rules live in `document_rules.json` (editable).

EOB history is **capped at 24 months** — the API returns nothing for a start date
older than ~25 months (confirmed live), so older EOBs are not available through
this portal.

### Not captured yet

- **Claims summaries** (the claims list, separate from the EOB Center).
- **EOB history older than ~24 months** — the EOB API returns nothing for a start
  date older than about 25 months (see below). Member documents, ID cards and
  letters have no such window and come down in full.

## Sensitive files

EOBs are among the most sensitive documents this project handles: they carry a
member ID, provider names, dates of service, procedure descriptions and claim
amounts. They are saved to the folder you set as `output_dir` in `config.json`.
Keep it somewhere safe, and if that folder syncs to a cloud drive, know these
documents go with it. `diagnose.bat` writes no screenshot, deliberately, so a
page full of claims does not end up in a file that is easy to attach to a bug
report by accident.

## Tests

```
.venv\Scripts\activate
pytest
```
