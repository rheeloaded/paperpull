# Adding a provider

No one person has accounts everywhere, so PaperPull grows when people add the
providers *they* use. This guide walks you through building a new downloader
app, using the same pattern every existing app shares. Budget a few evenings.
Most of the work is figuring out how one specific site lays out its
statements.

If you just want a provider to *exist* but can't build it yourself, open a
[provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
instead, someone with that account may pick it up.

---

## The three non-negotiables

These keep PaperPull safe to run against real financial accounts. A PR that
breaks any of them can't be merged.

1. **Read-only, always.** Your app may only navigate, read a document list, and
   download PDFs the provider already generated. It must **never** click a
   control that pays, transfers, redeems, enrolls, disputes, or changes any
   setting. Every clickable control is gated by two regexes in your
   `*_site.py`: a blocklist (`FORBIDDEN_CONTROL_RE`) *and* a document allowlist
   (`SAFE_DOC_CONTROL_RE`). A control must pass **both**. There is no code path
   anywhere that submits a form or confirms a dialog, keep it that way.
2. **Never handle credentials.** The user signs in themselves in a real browser
   window, and your app *attaches* to that already-signed-in session over the Chrome
   DevTools Protocol. Your code never sees a password, never types into a login
   field, and never touches 2FA.
3. **Never commit private data.** No real `config.json`, no `*-browser-profile/`,
   no downloaded PDFs, no logs/CSVs/state. These are all gitignored, run
   `git status` before every commit and confirm only source is staged. See
   [SECURITY.md](../SECURITY.md).

---

## How an app is built (60-second tour)

Each app is a generic engine plus **one** provider-specific file:

- `*_docs.py` / `*_receipts.py`, the engine: discovery, delete-safe state, PDF
  validation, folders, the CLI (`--login/--discover/--pilot/--all/--resume/
  --verify/--rename/--diagnose/--record`). **You rarely touch this.**
- `*_site.py`, **everything provider-specific**: URLs, selectors, how to reach
  the documents, how to list them, how to download one, plus the safety guards.
  **This is the file you write.**
- `storage.py`, a short `AppSpec` declaration of your folders and CSV columns
  (step 4), and `document_rules.json`, the editable rules that turn a
  document's title into the summary in its file name.
- Everything shared comes from `paperpull-core` (`core/paperpull_core/`), and
  you inherit it unchanged. That covers file names, the CSV index,
  classification, PDF checks, pressing a control (`pressing`), checking and
  filing a downloaded file (`identity`, `delivery`), numbering documents
  alike (`keys`), tabs, redirects and failure files.
- `config.json`, per install, holds the output folder, the browser profile
  folder, the browser to use and a unique CDP port in `cdp_url`.
  `"browser": "auto"` takes the person's own Edge or Chrome and falls back to
  the bundled Chromium. `config.example.json` is the tracked template.
- `login.bat` opens that browser with a debugging port, and the app attaches
  to it over the Chrome DevTools Protocol.

So your job is really to answer three questions for your provider, inside
`*_site.py`:

> **1. Where are the documents?** (navigate there)
> **2. What documents exist?** (read the list, dates + titles)
> **3. How do I download one?** (click/fetch → save a PDF)

---

## Which provider is a good first build?

Some sites are much friendlier than others. If this is your first PaperPull app,
pick one that looks **easy**, and save the hard ones for later.

**Easy (great first build)**, a portal that:
- keeps you signed in across normal navigation (`page.goto` works, a
  server-side cookie session), **and**
- lists statements in a plain HTML table or list, **and**
- has a direct "Download PDF" link that fires a real browser download, **and**
- doesn't block a browser PaperPull drives (no endless "are you human" loop).

Closest templates: **`redcard`**, **`tmobile`**, **`dominion`**. If your
provider looks like these, you can likely be done in an afternoon.

**Medium**, statements split across a year or period dropdown or pagination,
several document types to classify, or a download that opens a blob in a new
tab you have to `fetch()` (see `navyfederal`).

**Hard (not a first project)**, bot detection that blocks Chromium (needs real
Edge, `walmart`, `verizon`), an in-memory SPA session where `page.goto` logs
you out (`amex`), print-only receipts with no download button, captured via
`printToPDF` (`walmart`, `target`), or a portal whose session expires fast and
silently (`redcard`).

Not sure which bucket yours is in? Sign in, poke around the statements page for
ten minutes, and check: does refreshing the URL keep you logged in, and does a
statement have a real download link? Two yeses = easy.

## Step by step

### 1. Clone the closest existing app

Pick the app most like your provider and copy its folder to `apps/<yourslug>/`:

- **Receipts** (retailers), clone `amazon` or `target`.
- **Statements** (banks, brokerages, cards, utilities, telecoms), clone
  `redcard`, `tmobile` or `dominion` when the page lists statements with a
  download link, or `fidelity` or `tsp` when the page fetches its list from
  the site's own API.

Rename the two entry files to `<yourslug>_docs.py` / `<yourslug>_site.py` and do
a find-and-replace of the old slug/name (watch for the provider's **full** name,
e.g. "American Express" as well as "Amex", the token substitution misses it).

An app ships exactly two double-click files, `setup.bat` and `login.bat`
(plus their `.command` twins, generated by `tools/make_unix_launchers.py`).
Everything else, pilot, all, resume, verify, diagnose, is run through the
repo-level `paperpull <yourslug> <command>`, which finds your app by its
folder and the slug in its `*_docs.py` name. There is nothing to add for
that, and please do not copy in `run_*.bat` files from an old checkout. A
test refuses them.

### 2. Pick a free CDP port + set config

Each app uses its own debugging port so several signed-in browsers can be open
at once. Check the `cdp_url` in each `apps/*/config.example.json` for the
ports already taken and use the next free one in your `config.example.json`
and local `config.json`. Leave `output_dir` and `profile_dir` as `.` and
`./browser-profile`, which is this app's own folder.

### 3. Sign in and explore the live DOM

This is where the real work is. Run `login.bat`, sign in yourself, open your
statements page, and **leave the browser open**. Then attach and inspect, the
download mechanism is the key unknown every time. Write a throwaway probe (see
any app's history) or use `paperpull <yourslug> diagnose`, and answer:

- What URL holds the document list? Does the session **survive `page.goto`**
  (server-side cookie session) or only survive **click-navigation** (in-memory
  SPA token, like Amex)?
- How is the list structured, a table? cards? a year/period dropdown?
  pagination or "load more"?
- **How does a download actually happen?** This varies a lot (see Tips below).

The quickest way to answer all three is a recording. Add your app in the
panel with **Add a provider** and open its page. Click **More**, then **Get
help**, sign in with **Open sign-in window** there, then press **Record
steps** and click your way to one document. `recording.json` in the app's `Diagnostics` folder
lists each press and every answer the page asked the site for, and typed
values are never captured. [testing-a-provider.md](testing-a-provider.md)
walks through it, and a recording is also how someone who has the account
can help when you don't.

**Take the document where the page already gets it.** When the recording
shows the PDF arriving in an answer the page asked for, or as a blob, fetch
it the same way from inside the page rather than waiting on a browser
download. Under automation a download event is the least reliable way in.

### 4. Declare the provider

Your app's `storage.py` is a short `AppSpec` declaration, not a copy of anyone
else's storage code, the folders you file into, how a document routes to one,
your CSV columns, and a few config defaults. Everything else comes from
`paperpull-core`. See [core/README.md](../core/README.md) for the fields, and
any existing app for a worked example.

Mark a folder `precreate=False` when the provider *can* route there but rarely
does. It is then created only when a document actually lands in it, so an
install never grows a folder it can never fill.

### 5. Implement the site layer

Rewrite `*_site.py` to answer the three questions. At minimum the engine expects
these (names vary slightly by base app, match whatever your cloned `*_docs.py`
calls):

| Function | Does |
|---|---|
| `goto_documents(page)` | Navigate to the documents area; return `True` if it loaded |
| `collect_download_docs(page)` (or `collect_documents`) | Return a list of docs, each with an ISO `date_text` and a `title` |
| `download_document(page, …, out_path)` (or `download_bill`) | Download one doc's PDF to `out_path`, return `True`/`False` |
| `looks_signed_out(page)` / `detect_security_challenge(page)` | Session/challenge detection (mostly inherited) |
| `is_safe_control(name)` + `FORBIDDEN_CONTROL_RE` / `SAFE_DOC_CONTROL_RE` | The read-only guard, **tune the blocklist to your provider** |
| `paperpull_core.pressing.click(page, locator, css=…, what=…, words=…)` | Presses a control once, as a person sees it with nothing on top of it, or stops the run |
| `parse_date` / `parse_period_date` | Date parsing (inherited; extend the format list if your dates are unusual) |

### 6. Tune the read-only guard

Add provider-specific dangerous verbs to `FORBIDDEN_CONTROL_RE` (e.g. a card
portal needs `redeem`, `balance transfer`, `cash advance`, and a utility needs
`autopay`, `budget billing`). The tests in `tests/test_doc_types.py` assert a
long list of money/account controls are refused. Keep them green.

**Anchor the verb stems on both sides.** Every one of the last four
contributed providers arrived with `edit\s+` or `edit\b` in the blocklist,
and both match the end of "Credit", so "Credit Card Statement" was refused
on a credit-card provider. The form that works is

```
r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
```

and a test that says a label with "Credit" in it is allowed while "Edit
profile" is not. Copy one from any recent app.

**Every click goes through the guard, with the element's own label.** Not
just the ones you expect to be risky. A provider once fetched each bill by
clicking the first link or button in the row when the labeled one was not
found, and a bill row also holds Pay. The repo-wide test refuses any
function that clicks what a bare selector (`a`, `button`, a wildcard, an
unnamed role) finds without consulting the guard, and it will fail your PR
until the guard is in the path.

**Press with `paperpull_core.pressing.click`, not `locator.click()`.** It
takes the page, the locator, a CSS selector the control matches, a few words
naming it ("the View bill button for the bill of 2026-09-30") and your app's
word list. It reads the control the way a person sees it, presses it only
when nothing sits on top of it, and stops the run rather than press when
something is off. A plain `locator.click()` checks none of that.

### 7. Test it

From the app folder, with the environment setup-all built active, which is
`..\..\gui\.venv\Scripts\activate` (or `source ../../gui/.venv/bin/activate`
on macOS).

```
python <slug>_docs.py --discover     # lists what it found
python <slug>_docs.py --pilot        # downloads the newest few, then stops
python -m pytest tests               # your app's own tests
```

Then, from the repository root with the same venv, the tests that run
across every app. The whole core takes a while, so start with the tests
that name your app, and run everything once before you open the PR.

```
python -m pytest core -k <slug>
python tools/run_all_tests.py --suites <slug>,core,core-censuses,core-browsers
```

Each suite runs in a pytest of its own. A pytest that reaches into two, such
as `pytest .` or an app's tests together with the core's, stops before it
collects anything and says what to run instead.

These are the ones a review would otherwise send back. They check that the
guard refuses controls that commit something, that the URL check refuses
other hosts, that no function clicks what a bare selector finds, that Login
says signed in only once the document list is on the page, that an app on
core delivery has a test driving its download path
(`paperpull_core.testkit.StrictDelivery`), that documents numbered alike are
numbered by every field of their key, that a failed capture removes the
empty file it left, that `new-this-run.txt` is replaced on every download
run (even an empty one) and kept as it is by Discover, Verify, Rename and a
dry run (`lists_what_it_saved`), and that `write_run_summary` ends with
`report_run_result(s)` and `main` returns 130 on Ctrl+C, which is how the
control panel tells a clean run from a bad one. The last two arrived
after most contributors had cloned their template, and every provider merged
since needed them added on the way in. Cloning from an app on the current
`main` gives you all of it.

Verify the pilot PDFs open and look right, then re-run `--pilot` and confirm it
reports **"already downloaded, skipping"** (delete-safe works).

### 8. Scrub and open a PR

`git status`, only source should be staged (no profile/config/PDFs/state). Add
your provider to [PROVIDERS.md](../PROVIDERS.md) and give it a short line in
[gui/providers.json](../gui/providers.json) for the panel's welcome list, fill
in the PR checklist, and open it. See [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Tips (hard-won, one app at a time)

- **When unsure, refuse.** A document the app can't tell from another goes to
  Manual Review, or the run stops with a failure file. It never goes into the
  wrong folder or under another document's name. A missed document shows up
  in a Pilot, a wrong one doesn't.
- **Signed in means the list is on the page.** Login, Discover and Resume say
  signed in, or nothing new, only once the document list itself has rendered,
  never because no sign-in form or challenge showed. A blank page has
  neither. `core/tests/test_every_app_login_needs_the_list.py` checks every
  app's Login.
- **Number documents alike by their whole key.** When two documents share a
  title and a day, `paperpull_core.keys.told_apart` gives each a number. Its
  `fields` must hold every field your key holds, an account or a category
  included, or two accounts' statements of one day share one set of numbers.
  A census in `core/tests/test_a_document_told_apart_by_its_place.py` checks
  every app that uses it.
- **Never copy a real value into source.** Invent account numbers, dates,
  amounts and names of the same shape for tests, fixtures and comments, even
  when building against your own account.

- **If the site has a year picker, let a scoped run skip years.** Selecting
  a year is a round trip. Take `keep=None` in your collector, and when it
  is given, drop the picker options it refuses before selecting any of
  them. The orchestrator passes `scope.period_filter(self.args, self.config)`
  from `paperpull_core`, which is `None` on an unscoped run so every year is
  still walked and `discovery.json` stays complete. See `chase_site.py` for
  the six lines.


- **Download mechanisms vary, identify yours first.** The ones seen so far
  are the site's own API asked from inside the page with the page's own
  headers (Fidelity, TSP, USAA, Bank of America), a real browser **download
  event** (`page.expect_download`), an inline **blob in a new tab** you
  `fetch()` from the page (Navy Federal), CDP **`Page.printToPDF`** when the
  receipt is a print-only page with no download button (Walmart, Target), and
  a browser-managed download folder when attached to a browser the person
  launched (Verizon). Rank anything tied to the page's own answer above a
  download event.
- **Bot detection?** With `"browser": "auto"` an app already opens the
  person's own Edge or Chrome when one is installed, which passes most checks
  the Playwright build fails. If a site still blocks it (a WAF page, an
  endless "are you human" loop), see how `walmart` and `verizon` open and
  attach to a browser the person launched (`cmd_open_browser`).
- **SPA vs server session.** If `page.goto` logs you out, the session lives in an
  in-memory token, navigate by **clicking** the app's own links and reuse the
  signed-in tab (see `amex`). If `goto` is fine, use URLs (most providers).
- **Never work in a tab of another site.** The browser an app attaches to is
  the person's own, with whatever tabs they have open. `page()` takes their
  tab on the provider's own host when one is open and otherwise a new tab of
  the run's own from `paperpull_core.tabs.new_tab`, never the first tab it
  finds. `process()` asks `tabs.on_its_site` for the tab before each
  document. A provider whose session is a cookie passes it a way to open its
  documents page by address, and one that keeps its session in the tab it
  was signed in with passes none, so Resume with that tab closed stops and
  says so rather than reading or clicking whatever page is open.
  `core/tests/test_no_app_acts_on_another_sites_tab.py` holds every app to
  both.
- **Ask from outside the page without following a redirect.**
  `page.request` and `page.context.request` send every cookie the person's
  browser holds for the host they ask, and by themselves they follow up to
  twenty redirects to any host. Asking again an address the browser already
  got its document from needs none, so pass `max_redirects=0`. A link asked
  for the first time goes through `paperpull_core.redirects.get` with the
  app's own `is_safe_url`, which follows a redirect one step at a time and
  only to the provider's own hosts.
  `core/tests/test_no_request_follows_a_redirect_off_the_allowlist.py`
  names every other call it can find, so keep the client in a plain name,
  attribute or parameter where it can follow it.
- **Short sessions.** Some bank portals expire fast and the SPA keeps showing a
  cached page while download clicks silently no-op. Detect it (a hard reload
  bounces to the login URL) and report it so `--resume` retries after re-login
  (see `redcard`).
- **Pagination / history.** Statements are often split by year/period behind a
  dropdown or "load more", walk all of them during discovery.
- **Broken `aria-label`s happen.** Derive dates from the visible row text, not a
  label the site failed to interpolate (see `redcard`).
- **A pattern handed to a locator is read by the browser, not by Python.**
  Playwright writes it into its selector between slashes, so a `/` outside
  a character class ends it early, and a named group `(?P<x>...)` is
  refused outright. Write the slash as `\/`, and put text into a pattern
  with `paperpull_core.controls.escape_for_locator`, never `re.escape`,
  which leaves `/` bare. The locator fails only when it is used, and the
  callers catch that, so nothing else will say so.
  `core/tests/test_every_app_hands_playwright_a_pattern_it_can_read.py`
  follows each pattern back to where it is built and names the one.

Read the `*_site.py` of the app closest to yours, it's the best template, and
each one's top comment documents that provider's quirks.

Further reading in this folder covers recordings and tester rounds
([testing-a-provider.md](testing-a-provider.md)), how a downloaded file is
checked and filed ([delivery-architecture.md](delivery-architecture.md)),
what a failure file holds ([failure-diagnostics.md](failure-diagnostics.md))
and how files are named ([file-naming.md](file-naming.md)).
