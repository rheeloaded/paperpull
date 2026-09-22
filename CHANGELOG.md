# Changelog

All notable changes to PaperPull are recorded here. Versioning follows
[Semantic Versioning](https://semver.org):

- **PATCH**, bug fixes, or repairing an app after a provider changes its site
- **MINOR**, a new app, or a cross-app feature
- **MAJOR**, breaking changes (repo layout, config format, removing an app)

## [Unreleased]

### Fixed
- **PG&E, round three.** Every bill row on the tester's history read
  "View Bill PDF" and handed over no control, so the words are on
  something that is not an anchor, a button or a lightning-button. A
  row's controls are now found by their own text, innermost element first,
  whatever kind it is and through shadow roots, and a row that still
  hands over nothing prints its outline in the log. The Jump to picker
  opened without listing its options, so the page jump is also asked of
  the picker through its own value and change event, the way its parent
  hears a choice (#33).
- **E*TRADE, round four.** Discovery found nothing although the page
  listed a statement, so the caught searchItems answer's documentDate
  was in a form the app did not read. Dates are now read as an ISO date,
  an ISO date-time or an epoch in seconds or milliseconds, and the survey
  records the shape of the dates it saw. The period picker offers the
  years back to 2019 and nothing wider, so when no wider period exists
  the app chooses each year in turn and gathers every list (#36).

## [0.30.0] - 2026-09-21

### Fixed
- **AT&T, round nine.** Round eight's pilot saved the tester's bills, the
  first time. Two things came back with it. The current bill was saved
  twice, once dated by its issue date and once by its due date, the
  second a record round two had left in discovery from the billing
  center's current-balance box. Discovery now drops records the history
  no longer lists when nothing was downloaded for them, and a date that
  follows the word "due" is never a bill date. And the filename now
  leads with the account's kind read off the account switcher, "Wireless
  Monthly Statement" or "Fiber Monthly Statement", so a household with
  two accounts can tell them apart in Paperless (#26).
- **Golden 1, round three.** The second survey reached the documents
  page and never looked inside the vendor's tab, because "View Documents"
  is a button and the survey followed only links. The survey now presses
  that button itself, waits for the tab it opens, records the tab's host,
  headings, controls, row counts and frames whatever host it lands on,
  marked, and listens for the sign-on calls across every tab (#35).

### Added
- **ADP Workforce Now.** Pay statements and W-2s, requested in #46. The
  Pay & Tax Statements page fills itself from ADP's statement services on
  my.adp.com, and the app makes the same two calls from inside the
  signed-in page, reads the two lists, and fetches each statement's own
  PDF address. The worker id the calls need is read from the addresses
  the page already called. Nothing is clicked. Run against a real
  account, 20 pay statements and two W-2s, a second run downloaded
  nothing. Port 9265, real Edge or Chrome, since the sign-in usually
  goes through the employer's own identity provider.
- **Two more apps built and waiting for their testers.** Meijer (#42),
  order receipts and, where mPerks lists them, in-store digital receipts,
  cut from the GitHub receipt scaffold with a walk of the likely routes
  and a record of the shape of every JSON answer the page loads.
  American Family Insurance (#45), billing statements, policy documents,
  declarations pages and ID cards, cut from the document scaffold with
  the insurer's guard. Neither has an account behind it here. Each has a
  Diagnose that writes a masked survey for the tester. Ports 9266 and
  9267.

## [0.30.0-github.1] - 2026-09-21

A prerelease for the GitHub and Kroger tester. Latest stays 0.29.1.

### Added
- **GitHub, built and waiting for its tester (#43).** Receipts from the
  Payment history page, github.com/account/billing/history. Discovery
  reads the page and its ?page=N pages until one adds nothing new, each
  row with an amount is a payment. The row's receipt link is fetched from
  inside the signed-in page and saved when it is a PDF, or its page is
  opened, cut down to the receipt block and printed. Nothing is clicked.
  Built against an account that has never paid GitHub, so the sign-in and
  the history page are verified and the row and receipt shapes come from
  GitHub's documentation. Diagnose writes a masked survey of the page,
  its links, and what the first receipt link gives. Port 9264.

## [0.29.1] - 2026-09-21

### Fixed
- **AT&T, round eight.** Round seven's trace showed the click on "Download
  PDF" landing and nothing appearing, because the menu it opens is made
  of elements that are not buttons, links or menuitems, so the
  before-and-after comparison of those roles could not see "Regular PDF"
  or "View/print PDF". The entries are now found by their text, whatever
  element they are, with a wait for the menu to open, "Regular PDF" is
  clicked, and the trace records every element on the page whose text
  says PDF, with its tag, role and visibility (#26).
- **The README said a password manager installed into the sign-in profile
  stays for every provider.** It stays for that provider. Each provider has
  its own profile so several can be signed in at once on their own ports,
  so the extension goes in once per provider (#40).

## [0.30.0-kroger.1] - 2026-09-21

A prerelease for the Kroger tester. Latest stays 0.29.0.

### Added
- **Kroger, built and waiting for its tester (#41).** Receipts for the whole
  Kroger family (Pick 'n Save, Metro Market, Fred Meyer, Ralphs and the
  rest share one sign-in and one purchase history). Discovery makes the
  same purchase-history API call the page makes, from inside the
  signed-in page, a page at a time. Each finished purchase's receipt
  page is opened by URL, cut down to its print area and rendered with
  printToPDF. In-store and fuel go to In-Store, pickup and delivery to
  Online, a pending order is recorded and revisited. Nothing is clicked.
  Built against an account that had never bought anything, so the
  sign-in, the history page, its API and the receipt route are verified
  and the receipt's own lines are not. Diagnose writes a masked survey
  of the list and one receipt page for the tester to attach. Port 9263,
  real Edge or Chrome.

### Fixed
- **The panel's left column no longer paints over the footer** on a short
  window. The grid row now shrinks with the window, so the controls column
  scrolls inside it instead of drawing across the footer.

### Changed
- **README leads with what PaperPull is for**, the same words as the
  website, with a screenshot, and the Microsoft Store edition is $9.99 one
  time. The free build holds nothing back, and says so.

## [0.29.0] - 2026-09-21

### Added
- **eBay.** Order receipts from the purchase history, requested in #44.
  The order-details page is the receipt, so the app opens it by URL,
  waits for the order to fill in, hides everything outside the details
  block, scales the fixed-width desktop layout to the printable width so
  the amounts column is not cut off, and renders it with printToPDF.
  Nothing is clicked. The site's "All" filter is only four years, but
  its year filter is a URL word out to ten years ago, so discovery walks
  one year at a time and stops after two empty years. Some orders from
  2019 and before get eBay's own "Order not found" page every time, and
  for those the app prints the order's history card (date, item, total,
  seller, status, order number) as an Order Summary instead. eBay also
  caps how many details pages an account may open in a day, a few
  hundred, and past the cap every one lands on a "daily limit exceeded"
  page. The app recognizes it, stops with progress saved, and resume
  continues the next day. Run against a real account, 108 orders back to
  2017, the first day reached the cap after the second full pass. Port
  9262, real Edge or Chrome.

## [0.28.5] - 2026-09-21

### Added
- **A second person, from the panel.** "Add a person" beside the Account
  box asks for a label and a name, makes the account with its own folder
  beside the first one's, its own sign-in window and its own port, and
  selects it. The terminal command is still there, but a packaged Mac
  install has no `paperpull` on the PATH, so the panel was the only
  honest answer (#39). A packaged install keeps its downloads in the
  install folder itself, and the second account's folder is now a sibling
  of the install, where the old rule made a folder called " - spouse"
  inside it.
- **The README says a password manager can live in the sign-in profile.**
  The profile Login opens is separate from your everyday browser on
  purpose, so it has no extensions, and a password manager installed into
  it once stays for every Login after (#40).

## [0.28.4] - 2026-09-21

### Fixed
- **AT&T, round seven.** The tester answered the question: "Download PDF"
  opens a small menu with "Regular PDF" and "Accessibility PDF", and
  "View/print PDF" opens the PDF in a new tab. "Regular PDF" is the
  second step now, ahead of the accessibility variant.
  [#26](https://github.com/rheeloaded/paperpull/issues/26).
- **PG&E, round two.** The page jump still did not take, and a bill row
  on page 1 handed over no control. A jump counts when the rows changed
  even if the picker's value never updates, the option is clicked through
  the DOM when a plain click did nothing, a Next control is the fallback,
  the row's PDF control is found by its text when it is neither an anchor
  nor a button, and a row that hands over nothing says what it holds.
  [#33](https://github.com/rheeloaded/paperpull/issues/33).
- **SMUD, round three.** Discovery listed all 24 bills, and a Download
  opened the PDF in the same tab, which nothing caught. A PDF the tab
  itself moved to is fetched through the session and the tab sent back,
  and the control's own link is fetched through the session before any
  click. [#34](https://github.com/rheeloaded/paperpull/issues/34).
- **Golden 1, round two.** Sign-in is at login.golden1.com/login and
  lands on digitalbanking.golden1.com, whose documents page has a "View
  Documents" button that signs the person on to the credit union's
  document vendor, ebank.hepsiian.com, in a new tab. The Login button had
  opened a 404. The routes are right now, the vendor's host is allowed,
  and discovery and download work in the vendor's tab once the button
  has opened it. [#35](https://github.com/rheeloaded/paperpull/issues/35).
- **E*TRADE, round three.** Discovery found nothing because the documents
  page is a single-page app that calls nothing when landed on twice. It
  is reloaded now, the period picker is widened to the widest period it
  offers (its options are recorded), and a document is downloaded by its
  own link in its row, which is what a person clicks.
  [#36](https://github.com/rheeloaded/paperpull/issues/36).
- **State Farm, round three.** The Document Center fills itself from a
  customerMetadata call with a year parameter, whose answer names each
  document's date, category, type, id and file address. Discovery reads
  this year's answer as the page loads and asks the same address for each
  of the last seven years, a document's file address is fetched from
  inside the page, ID cards and policy documents file under Insurance
  Documents. [#37](https://github.com/rheeloaded/paperpull/issues/37).
- **Newrez, round three.** "Account Details" leads to a servicing app
  whose address carries the loan number, and the statements and the 1098
  are at statements/monthly and statements/yearly under it. The loan
  number is read off the address at run time, never stored, and both
  pages are read. The tester found both answering with an API error on
  Newrez's side, which the app now reports rather than mistaking for an
  empty list. [#38](https://github.com/rheeloaded/paperpull/issues/38).
- **Every scaffold's survey.** A path segment shaped like an id or a key
  is masked, the way a query string and a digit run already were. A
  control the survey follows that opens a new tab is surveyed there, then
  the tab is closed, with its host marked when it is not the provider's.
  A call's method and the names of its POST body keys are recorded. And
  the eight scaffolds cut from Wells Fargo get what AT&T got in round six,
  the click's own outcome, a second step the click revealed, and a
  `download-attempt.json` trace when a download fails.

## [0.28.3] - 2026-09-21

### Fixed
- **AT&T, round six, from the round-five trace.** With every capture in
  place, the click on "Download PDF" still produced nothing, no download,
  no response, no tab, nothing in the browser's own download list. So the
  click either needs a second step, puts the PDF in a viewer, or is not
  landing, and the trace could not tell those apart because a click
  failure was swallowed. The click's own outcome goes in the trace now,
  the page is compared before and after it, a control the click revealed
  (a format choice, a download confirm) is taken as the second step once
  it has passed the guard, an embedded viewer is read through the page,
  and "View/print PDF" is tried when "Download PDF" gave nothing.
  [#26](https://github.com/rheeloaded/paperpull/issues/26).
- **PG&E read the first page of its history seven times.** The Jump to
  page picker was clicked, the app slept a second and a half, and read
  the table, which still showed the page before. A seven-page history
  came back as 28 rows and 4 bills, every bill filed under page 7, and
  nothing found there at download time. A jump now counts only once the
  picker reads the target and the rows have changed, discovery keeps a
  bill's first sighting and stops when a page repeats the one before it
  rather than reading it again under a new number, and a download looks
  for its bill on the page it was seen on and then on every other page.
  Found by watling777 in [#33](https://github.com/rheeloaded/paperpull/issues/33).
- **E*TRADE, round two, from the first survey.** The Documents page is
  `/etx/pxy/accountdocs`, a list with a type filter, a date filter that
  defaults to the last 90 days, a Download button and pagination, fed by
  an API on ext-web.etrade.com whose answer carries each document's
  guid, type, title, date and account. The documents page is the first
  route, the Tax Center the second, and discovery reads the API answer
  as the page loads it, within the page's own default window for now.
  [#36](https://github.com/rheeloaded/paperpull/issues/36).
- **Newrez, round two, from the first survey.** Sign-in lands on a
  dashboard with "Access My Loan" and "Account Details" and no statements
  on it, and the route guesses went back there. The loan servicer's guard
  refused "Access My Loan" for the word loan, which on this site is the
  noun of everything, so only applying for, getting or taking out a loan
  is refused now, and the survey follows those two controls.
  [#38](https://github.com/rheeloaded/paperpull/issues/38).
- **Three things every scaffold's survey does better.** It follows
  buttons as well as links, since two sites put the documents behind a
  button. It records the names of a JSON call's query parameters, and a
  value only when it is a plain word such as `docType=STATEMENT`, never
  an id, a token or a number, which is what a repair needs to make the
  same call with a wider filter. And its row samples put rows that carry
  a date first, ahead of a nav full of links.

## [0.28.2] - 2026-09-20

### Fixed
- **SMUD, round two, from the first survey.** The dashboard's BILLING
  HISTORY link goes to `/manage/billing`, a table of two years of bills
  with a View link (an HTML bill page) and a Download link per row, and
  older bills sit on `/manage/billing/archive`. The Download link goes to
  SMUD's bill vendor on i-doxs.net, so that host is in the allowlist.
  The billing page is the first route now, the archive is read after it,
  and a row's Download wins over its View.
  [#34](https://github.com/rheeloaded/paperpull/issues/34).
- **State Farm, round two, from the first survey.** Sign-in lands on My
  Accounts at my.statefarm.com, and the first round's customer-care
  route landed on a contact page. Documents live in the Document Center
  on edocuments.statefarm.com, bills in the Payment Center on
  financials.statefarm.com. The Document Center is the first route, the
  survey follows "View documents & PDFs", "Documents (excludes claims)"
  and the ID card link, and the word claims inside that documents link no
  longer trips the guard.
  [#37](https://github.com/rheeloaded/paperpull/issues/37).
- **A survey never carries the person's name.** "Welcome, NAME" on a
  dashboard button reached a survey file. Every scaffold's survey now
  masks the name after a greeting.

## [0.28.1] - 2026-09-20

### Fixed
- **Every scaffold waited for a download event a real browser never
  sends.** A real Edge or Chrome attached over CDP saves a download
  itself, into its own Downloads folder, and Playwright's download event
  never fires. The Verizon app learned this a year ago and points the
  browser at a folder it watches. The nine scaffolds cut from the AT&T
  template did not, so AT&T's tester clicked "Download PDF" five times in
  round four and the app saw nothing each time, with a trace showing a
  clean click and no PDF. All nine now point the attached browser at
  `.<provider>-downloads` under the output folder and watch it after
  every click, alongside the download event, the PDF response and the
  new tab they already caught, and a PDF that opens in a new tab, a
  blob: tab included, is read out of the tab the way Chase reads one. A
  repo-wide test now refuses any app that clicks in a real browser
  without one of those. [#26](https://github.com/rheeloaded/paperpull/issues/26).

## [0.28.0] - 2026-09-20

### Fixed
- **AT&T, round four, from the round-three pilot.** Discovery read all
  sixteen bills from the history API, and every download failed the same
  way. The history page's bill buttons were matched on their accessible
  name, which a button can carry as an aria-label that reads nothing like
  its face, so none matched, and the fallback then looked for "Download
  PDF" on the history page instead of the billing center, since the
  history page passes the billing check too. The buttons are matched on
  the text a person sees now, the wait is for the buttons themselves, the
  billing center is opened as its own page, and a miss records the
  buttons it saw, digits masked, so the next trace explains itself.
  [#26](https://github.com/rheeloaded/paperpull/issues/26).

### Added
- **Five providers built without accounts, for their requester to test.**
  SMUD ([#34](https://github.com/rheeloaded/paperpull/issues/34)), Golden 1
  Credit Union ([#35](https://github.com/rheeloaded/paperpull/issues/35)),
  E*TRADE ([#36](https://github.com/rheeloaded/paperpull/issues/36)), State
  Farm ([#37](https://github.com/rheeloaded/paperpull/issues/37)) and Newrez
  ([#38](https://github.com/rheeloaded/paperpull/issues/38)), all requested
  by the AT&T tester, who holds each account. Each is cut from the Wells
  Fargo scaffold with its own routes, its own guard on top of the bank
  words (a loan servicer's payoff and hardship words, a utility's start,
  stop and move service, a brokerage's trade, buy, sell and order, an
  insurer's claims, coverage and quotes), its own rules, tests and tester
  guide. State Farm files ID cards, declarations and policy documents
  under Insurance Documents. E*TRADE's provider string is ETRADE, since a
  star is not a filename character. A trade confirmation and an insurer's
  ID card pass the guard, a trade and a lost card do not. Every one is
  marked untested everywhere a person would see it. Ports 9257 to 9261.

## [0.27.1] - 2026-09-20

### Fixed
- **AT&T, round three, from the second survey.** The survey reached the
  billing center and followed "See bill history" to a page that lists
  past bills as buttons ("Bill, Jul 23 - Aug 22") and, while loading,
  calls the site's own history API with sixteen bills, each with its
  cycle dates and a statement id. Round two's pilot had recognized only
  the current bill and clicked "See bill history" instead of the
  "Download PDF" beside it. Discovery now reads the history API as the
  page loads it, passively, and falls back to the bill buttons, stepping
  the year back across January since the buttons carry none. A download
  opens the history, clicks the bill's own button, then the "Download
  PDF" it reveals, and catches what arrives, with the current bill taken
  from the billing center's own button. "See bill history" is
  navigation, not a bill. A failed download now writes
  `Diagnostics/download-attempt.json` with what the site answered, so the
  next round can read what the button called. Only the account in focus
  is read this round. Still untested until a Pilot lands PDFs.
  [#26](https://github.com/rheeloaded/paperpull/issues/26).
- **Transaction export, the Account column and the last of the box.**
  The Account column read the index's title, which is often just
  "Statement" or a date. It now reads the summary, which is what names
  the file and says which account, "Statement - FREEDOM (...1234)",
  "Costco Anywhere Visa Monthly Statement". And on a card statement with
  a rewards box, five descriptions in 2,368 still carried the box's words
  where the box sat on an amount-first line or on the merchant's own
  wrapped line. Both shapes are cut now. Verified on the full Citi
  workbook through the panel's own Spreadsheet route, 24 of 24
  reconciled, every statement's rows summing to its printed balances.

## [0.27.0] - 2026-09-20

### Added
- **Citi credit cards.** Monthly card statements from Citi Online, read
  through the same JSON API the Account Statements page uses, from inside
  the signed-in page, nothing clicked. Every card on the sign-in is read.
  Identity is the card plus the closing date, and the filename carries the
  card's name without its last four. The site lists roughly two years
  online, older statements sit behind a request the app never submits,
  and the Annual Account Summary is a web page, not a PDF, and is left
  alone. Run against a real account, 24 statements, a second run
  downloaded nothing, and the transaction export reads all 24 to the
  cent. Port 9256.

### Fixed
- **An upgrade now reaches the installs that already exist.** The panel
  copied a provider's code into its folder at Set up and never touched it
  again, so a fix shipped in a release reached new installs only, and
  everyone who had already set the provider up kept running the code
  from the day they did. The first AT&T tester installed the release with
  the round-two repair, clicked Diagnose, and sent back a survey from the
  old code, which is how this was found. The panel now compares each
  install's shipped files with this version's, byte for byte, when it
  opens, replaces the ones that differ, and says so under the apps root.
  Config, progress, the PDFs and the browser profile are never in
  question, and a replaced file is kept under `Backups/code-<time>/`, so
  an edited `document_rules.json` is a copy away. A checkout install's
  copy of the shared core inside its venv is brought up too.
  [#26](https://github.com/rheeloaded/paperpull/issues/26).
- **The transaction export found no PDFs for a panel install.** Every
  install the panel creates has `output_dir` "." and records each PDF's
  path relative to its own folder. The export tool runs from its own
  folder, where that path is nothing, so the panel offered no providers
  to export and the sheet came out empty for them. A relative path is now
  taken from the index's folder.
- **Card statements with a rewards box beside the list.** The PDF reader
  glues the box's words onto the transaction line level with it, so a
  line lost its trailing amount and was dropped, or handed over the box's
  number instead of its own. A line is now cut at the first word after
  its amount. A transaction whose merchant wrapped onto the line before or
  after it takes that line as its description, an amount printed before
  its description is read the right way round, and the month APR in a
  description is no longer mistaken for the interest rate word. A shoe
  store called New Balance is no longer the statement's ending balance.
  On a Costco Visa archive this took reconciliation from 5 of 24
  statements to 24 of 24, with no change to any other archive. Cache
  version 4.

## [0.26.1] - 2026-09-20

### Fixed
- **A balance split across a space read as the wrong balance.** pdfplumber
  sometimes prints "$1,719.3 3". The amount did not parse, so the next
  amount in the window, the NEW balance, was taken as the beginning
  balance, and both ends of a card statement read the same. The window is
  joined before scanning, the way split words already were.
- **A bracket around nothing no longer calls itself reconciled.** With
  both balances misread to the same value a few lines apart, the section
  between them held no transactions, "reconciled" trivially, and led the
  status while all seventy real lines sat outside it. A statement whose
  only brackets are empty now says "not reconciled" first. Both from
  dertbv in [#32](https://github.com/rheeloaded/paperpull/issues/32).
  Cache version 3.
- **AT&T, round two, from the first tester's survey.** Sign-in lands on
  the overview, a shop page with one "View bill" button, which was enough
  to pass the billing-page check, so discovery read 125 rows of phones
  and cases and no bills. The billing center is the first route now, read
  off the site's own nav, the overview never counts as billing, and when
  the routes miss the nav's Billing link is followed. The survey follows
  billing buttons as well as links. [#26](https://github.com/rheeloaded/paperpull/issues/26).
- **A survey never carries a URL's query string.** Query strings are
  where a site keeps session details, and the survey only needs the path,
  so every scaffold's survey now cuts a URL at the question mark.

## [0.26.0] - 2026-09-20

### Added
- **Verizon Mobile, built without an account, for someone with one to
  test.** The wireless side of My Verizon, cut from the AT&T scaffold
  with the same carrier guard, real Edge or Chrome since verizon.com walls
  the Playwright build (the Fios app proved it), and the bill routes under
  `/digital/nsa/secure/ui/` as the first guess with the Fios app's Download
  Your Bill page as the fallback. Fios keeps its own app. Its Diagnose
  survey, tests and a README that opens by saying it is untested are in
  place. [#31](https://github.com/rheeloaded/paperpull/issues/31). CDP
  port 9255.

### Fixed
- **Transactions in a statement's closing month were dated a year
  early.** A Chase card statement prints "Opening/Closing Date 07/27/26 -
  08/26/26". The period parser's fallback matched "Closing Date" and took
  the first date after it, the opening date, so every line in the closing
  month looked later than the period end and was pushed back a year,
  while the statement still reported itself reconciled. The parser now
  reads that line as a period, the fallback takes the latest date on its
  line, and the statement date the app recorded in its index when it
  downloaded the file is what the year is taken from, with a disagreement
  between the two said in the Statements sheet rather than trusted. The
  cache version moved so old parses are re-read. Found and diagnosed by
  dertbv in [#29](https://github.com/rheeloaded/paperpull/issues/29), with
  6 of 47 rows matching an outside record before and 47 of 47 after.
- **Navy Federal's statements page moved.** It lives on the banking host
  now, `digitalomni.navyfederal.org/nfcu-online-banking/statements`, and
  every old `www.navyfederal.org` path answers Page Not Found, outside the
  banking app, which ended the session. The app goes to the new page, and
  recognizes it with every group collapsed, since statement rows only
  exist once a group is expanded. Reported with the live URL by dertbv in
  [#30](https://github.com/rheeloaded/paperpull/issues/30).
- **A page you opened by hand is read, not replaced.** Navy Federal, USAA
  and Robinhood promised that if their known URLs missed, the page you had
  navigated to yourself would be used. Their candidate loop ran first
  regardless, and when every candidate missed it left the browser on a
  dead page, so the promise could not be kept and each retry cost a
  sign-in. All three now check the open page before trying anything.
  Also from [#30](https://github.com/rheeloaded/paperpull/issues/30).

## [0.25.0] - 2026-09-20

### Added
- **Wells Fargo and SBA, built without accounts, for someone with one to
  test.** Both are cut from the AT&T scaffold, the generic site layer
  that reads document dates off whatever control fetches a document and
  catches a click as a download event, a PDF response or a new tab. Wells
  Fargo (Statements & Documents on connect.secure.wellsfargo.com, real
  Edge or Chrome, a bank guard that refuses transfer, Zelle, wire, pay,
  deposit, apply, open, close, lock, limit and every settings word) is
  [#27](https://github.com/rheeloaded/paperpull/issues/27). SBA (the
  MySBA Loan Portal at lending.sba.gov, monthly loan statements and the
  1098, a loan-servicer guard that refuses pay, autopay, hardship,
  deferment, forgiveness, apply, upload and submit) is
  [#28](https://github.com/rheeloaded/paperpull/issues/28). Each has its
  Diagnose survey, its tests, and a README that opens by saying it is
  untested. CDP ports 9253 and 9254.

### Changed
- **The website and the Store listing material live elsewhere.** The
  Microsoft Store playbook, its screenshots and logos, and the website
  are in a private repository now. This one holds the program, its
  packaging and its privacy policy.

## [0.24.2] - 2026-09-20

### Added
- **A Diagnose button on the panel, behind "more".** The AT&T tester
  instructions said to click Diagnose, and the panel had no such button,
  only the command line did. It runs the app's survey, which downloads
  nothing and writes to the Diagnostics folder, and is how a provider
  built without an account gets tested by someone who has one. It sits
  with Verify behind a "more" link under the main buttons, since both are
  for when something is off rather than for a normal day, and the panel
  remembers whether you left it open. Resume moved up beside Pilot so Run
  All stands alone at the bottom.

## [0.24.1] - 2026-09-20

### Changed
- **The ask is said plainly.** PaperPull is free and costs money to make,
  an Apple developer membership every year, a Store account, and evenings
  per provider. The README says so near the top and in a rewritten Support
  section, with the two ways to help, a Ko-fi donation or the $2.99 Store
  edition, and the free download beside them. The panel's footer says the
  same in one line.

## [0.24.0] - 2026-09-19

### Added
- **AT&T, built without an account, for someone with one to test.** A
  bill downloader for myAT&T (Mobility, Fiber, Internet) cloned from the
  T-Mobile app, with a carrier guard that refuses pay, autopay, add a line,
  upgrade, trade-in, plan, SIM, suspend, port and every settings word, a
  real Edge or Chrome launch since att.com runs Akamai, and a site layer
  whose every guess is marked. Its Diagnose button surveys the billing
  page into a file with no screenshot, digit runs masked and JSON as shape
  only, which a tester attaches to
  [#26](https://github.com/rheeloaded/paperpull/issues/26) without
  writing code. The README says in its first line that it is untested,
  and the provider table says so too. CDP port 9252.

### Changed
- **T-Mobile's rules file is a carrier's.** It still carried the crypto
  1099 and trade confirmation rules of the brokerage app it was cloned
  from. Harmless, nothing on a phone bill matched them, but wrong.
- **The spreadsheets are on the front page.** The README, the Store
  listing text and the package description all led with the downloading
  and left the part people like best, reading the PDFs into spreadsheets,
  to a section far down. It is now the second paragraph everywhere.

## [0.23.1] - 2026-09-19

### Fixed
- **Browsers are found the way Windows finds them.** The sign-in browser
  was looked for in a fixed list of folders built from `PROGRAMFILES`,
  which quietly points at `Program Files (x86)` when the program runs
  under emulation on a Windows on ARM machine, so a native ARM64 Chrome
  in the real Program Files was a coin flip and a per-user Brave a miss.
  The registry's App Paths keys are asked first, in the 64-bit view, for
  Edge, Chrome, Brave, Vivaldi and Opera, HKCU before HKLM, then the
  folders under `ProgramW6432`, both Program Files and `LOCALAPPDATA`.
  Brand order is kept whatever found the browser, and one install found
  two ways is still offered once.
- **Ready means DevTools answered, not that the port opened.** The
  launcher waited for the debugging port to accept a connection, which
  the browser does before the protocol is up, and an attach in that gap
  failed blaming the wrong thing. It now waits for `/json/version` on
  `127.0.0.1` to answer with the websocket address the attach will use.

### Changed
- **The Windows build takes `--arch`.** `x64` is the default and what
  every release ships. `--arch arm64`, on an ARM64 machine, builds a
  native Windows on ARM portable folder, installer and MSIX from the same
  source, named `-arm64`, with the embeddable ARM64 Python from python.org
  and every package's native wheel. Not shipped, because the x64 build
  already runs on ARM64 Windows under emulation and would not be faster
  native in a program that waits on a browser, but a flag away for the
  day someone asks. The build scripts find the Windows SDK and Inno Setup
  through the environment instead of a literal `C:\Program Files (x86)`.

## [0.23.0] - 2026-09-19

### Added
- **Affirm**, the 31st provider. One loan agreement per loan, the Truth in
  Lending disclosure with the payment schedule, settled loans included,
  dated the day the loan was made and named for the merchant. Three GET
  calls the page itself makes, from inside the signed-in page, and the
  agreement's HTML rendered to PDF. Nothing is clicked. A pay-over-time
  account has no monthly statement, the statements Affirm's help center
  describes belong to the Affirm Money account and Card, which are not
  covered. Run against a real account, two agreements. CDP port 9251.
- **Fairfax Water**, the 30th provider, for the FW Customer portal. The
  portal is a Mendix app, so this one is driven the way a person drives
  it, the Billing & Payment page from the left nav, the Billing History
  grid, and a click on each bill's View, which opens the PDF in a new tab
  on the utility's document host. The app catches that tab, reads the PDF
  out of its own response, and closes it. Only the last year's bills have
  a PDF, which the portal's FAQ says too, so the archive grows a bill a
  quarter. Run against a real account, four bills saved, one the host no
  longer held. CDP port 9250.
- **The Microsoft Store playbook.** `docs/microsoft-store.md` is the
  paint.net model applied to PaperPull, a $2.99 Store edition that is the
  same program as the free GitHub build, signed by the Store and updated
  through it. It covers the developer account, the name reservation, the
  four repository variables that carry the package identity, the
  submission section by section with the listing text and certification
  notes ready to paste, and the policy reasoning for an individual
  account and for charging for open source. Screenshots under
  `docs/store/`.

### Changed
- **Amazon saves the real invoice PDF where there is one.** Each order's
  Invoice menu (Rechnung on amazon.de) is read with a plain GET, and any
  invoice PDF it links is downloaded as Amazon issued it, saved as
  `YYYY-MM-DD Amazon <Category> Invoice.pdf`, one per seller on a split
  order. On amazon.de that PDF is the legal invoice, where the printable
  summary is not. Orders without one get the printable summary as before.
  The summary parser also reads a German-language account's labels, since
  Amazon serves German pages to such an account whatever the URL asks for.
  A downloaded invoice that fails validation goes to Manual Review rather
  than being replaced by a print of the screen. On amazon.com this means
  third-party-seller orders now save the seller's invoice PDF. Contributed
  by marecabo in #25.
- **A second account is one command.** `paperpull <app> add-account NAME`
  writes the `config.NAME.json` an app runs against with `--account NAME`,
  and `python tools/add_account.py NAME` does every app under the root at
  once. The thirty per-app copies of `add_account.py` are gone. Each one
  carried its own hard-coded list of install paths, stale in every copy,
  so the tool that promised to set up a second person everywhere set them
  up in whichever seven apps its author happened to have at the time.
- **A full audit of the code.** Every app's site module was compared
  against what its orchestrator and tests actually call, and 96 functions
  and constants nothing referenced were removed, nearly 1,200 lines, most
  of it residue from the app each one was cloned from. Verizon's included four
  functions that referenced names never defined anywhere, dead since the
  day the app was written. Comments and docstrings that still described
  the parent app (a brokerage guard on a phone bill, a mailbox on a
  water utility) now describe the app they are in. Unused imports and
  variables are gone, and `ruff.toml` at the repo root keeps them gone.
  Spelling is American throughout, and the em dash is retired from every
  file.
- **Purchase classification weighs European amounts correctly.** An
  item priced `1.234,56 EUR` was read as 1.23 when the receipt's category
  was chosen, so a big-ticket item on a German order weighed less than a
  banana. Amounts are now read by shape, as the Amazon parser already
  did.
- **The panel unlocks only the buttons a run locked.** A finished run
  re-enabled every button on the page, including the Spreadsheet tab's
  build buttons that are disabled when there is nothing to build from.

## [0.22.0] - 2026-09-19

### Added
- **Fidelity NetBenefits**, the 29th provider, for a workplace 401(k).
  NetBenefits keeps no archive of statements. Its Statements page makes
  one for any period on request, so the app requests each completed
  quarter (or month, by config) itself, through the same form request the
  page sends with the site's token fetched and used inside the page, and
  renders the answer to PDF the way the page's print button would.
  Discovery stops at the first period the site refuses after a real one.
  The site times a session out on page activity and moves its own tab
  around, so the app reloads the Statements page every minute and retries
  once if the tab moves mid-call. Run against a real plan, 39 quarterly
  statements back to 2016, all valid. CDP port 9249.
- **Fidelity Investments**, the 28th provider. Statements, trade
  confirmations and tax forms from the Document Access Hub, read through
  the same three API calls the page makes, from inside the signed-in page
  so the session never leaves the browser. Nothing is clicked. One call per
  year, since the API refuses a wider window, and a scoped run asks only
  for its years. Identity is kind, account and period end date, never the
  hub's id. Run against a real account, 24 documents, all valid. Tax forms
  are mapped but unverified, the account had none. A workplace 401(k) keeps
  its statements on NetBenefits and is not covered. Sign-in uses your own
  Edge or Chrome, as Chase does. CDP port 9248.
- **The transactions inside your statements, in one spreadsheet.**
  `tools/export_transactions.py` and the panel's Statements section read
  every statement PDF an archive holds, line by line, and keep the lines
  with the shape of a transaction. Nothing is written for one bank. Each
  statement is checked against its own printed balances, by the running
  balance column where there is one, and by the signed amounts against
  every balance pair otherwise, one account at a time on a statement that
  covers two. A statement that does not add up is exported anyway with
  the difference shown. Amounts are the effect on the balance, money in
  positive. Every PDF is read once and cached beside the installs. Needs
  `pdfplumber`, now in the panel's requirements and the packages.
- **Amazon reads any country's store.** `marketplace` in `config.json`
  (`amazon.co.uk`, `amazon.de`, `amazon.ca` and eleven more, default
  `amazon.com`) points the app at that store and moves the host allowlist
  with it. Money is found by shape, `£12.99` and `12,99 €` alike, and
  written back in one canonical form. Dates read in the store's order,
  including `5 January 2025` and `5. Januar 2025`. On a store whose pages
  are not in English every URL asks for English, which Amazon remembers.
  A store the app does not know is refused with the list, not guessed.
  Asked for by amazon.de and amazon.co.uk users in #24.
- **Every purchase in one spreadsheet.** `tools/export_purchases.py` and the
  panel's new Spreadsheet tab gather the order history the receipt apps
  already keep (Amazon, Target, Walmart, Gap, second accounts included) into
  `All Purchases.xlsx` beside the installs. One row per line item, newest
  first, with an Orders sheet and a Summary of spend per provider per year.
  Amounts are numbers. No PDF is read, it takes a second, and the file is
  rebuilt from scratch each time. A CSV is one click away, and is what you
  get when openpyxl is not installed. A dropdown picks one provider for
  `Amazon Purchases.xlsx` and the like. Only providers with line items are
  offered, since a statement archive has documents, not purchases.

### Fixed
- **Amazon, Whole Foods items now have prices and quantities.** The
  printable summary for a Whole Foods or Amazon Fresh order lists each item
  as a title line followed by a line that is only its price, with no
  "Sold by" and no quantity, and an item bought twice is listed twice. The
  parser did not know that layout, fell back to product names alone, and
  every Whole Foods line in the order history had a name and nothing else.
  It reads the layout now, collapses repeats into a quantity, and a new
  `reparse-items` command backfills receipts already on disk from their
  PDF text, offline. A parse is kept only when its lines add up to the
  subtotal printed on the receipt, or come within 5% of it with the
  shortfall written to Notes. Some summaries genuinely leave items out.

### Changed
- **License is now the GNU Affero General Public License, version 3.** From
  the first release until 2026-09-18 PaperPull was MIT, and contributions
  from that period keep their MIT permission (`LICENSE-MIT`, `NOTICE.md`).
  A changed version that is distributed, or run as a service for other
  people, now has to carry the same license and its source. Using PaperPull
  to archive your own records is unchanged.
- **The PaperPull name is reserved** under section 7(e) of the license. A
  modified version needs its own name. `TRADEMARK.md` says what is allowed
  without asking, which is most things, and what needs a rename.

## [0.21.0] - 2026-09-18

### Changed
- **A scoped run no longer walks every year.** On providers with a year
  picker (U.S. Bank, Chase, Target RedCard, Wealthfront's tax years, and
  Target's order history), selecting a year is a round trip, three seconds
  or so on U.S. Bank, and discovery used to select every one and let
  `--year`, `--start-date`, `--end-date` and `default_start_date` filter the
  result afterwards. Now a scoped run skips selecting the years it would
  throw away. An unscoped run still walks everything, and discovery only
  ever adds to what it knows, so `discovery.json` stays complete for the
  status tracker's gap detection either way. Suggested by a U.S. Bank
  user.
- **Amazon honors `--end-date` when choosing which years to load.** It
  already skipped years before `--start-date`. Now a run scoped to 2021
  through 2023 loads those three order-history years and not this year's
  first, and the year range comes from the same `paperpull_core.scope`
  rules as the other providers.

### Added
- **A Scope row on the control panel.** All years is the default and
  changes nothing. Pick one year, or a from and to date, and every action
  except Login runs with the matching `--year`, `--start-date` and
  `--end-date`. The panel validates what the page sends before it reaches
  a command line, and remembers the choice in that browser.
- **`MSIX_DISPLAY_NAME`** lets the Store package's display name match the
  spelling Partner Center reserved, case included.

## [0.20.0] - 2026-09-18

### Added
- **Thrift Savings Plan**, the 27th provider and the second US government
  system. Participant statements and the 1099-R, read from My Account's
  Secure Mailbox through the same two API calls the page makes, from inside
  the signed-in page so the session token never leaves the browser. Nothing
  is clicked. Run against a real account, 25 documents back to 2022, all
  valid. Downloading a message marks it read, and the README says so. The
  1099-R arrives with a print-stream line in front of the PDF header, which
  is stripped.
- **A contributing guide that assumes nothing.** CONTRIBUTING.md now walks a
  first-time contributor from making a GitHub account to seeing a change
  merged, with the ways to help that need no code, the rules, and what
  happens after a pull request is opened. The provider guide gained the two
  things every contributed provider this month needed, anchored verb stems
  in the guard and the repo-wide tests run from the root before a PR.

## [0.19.1] - 2026-09-18

A patch on the Windows package. Nothing a user does changes.

### Fixed
- **The settings file no longer lives beside the program.** On Windows the
  panel's one setting, which folder holds the downloads, sat in Local
  AppData, the same folder the installer uses for the program, and survived
  upgrades and uninstalls only because nothing happened to delete it. It
  moves to Roaming AppData, where Windows expects per-user application
  data. A file left in the old place by 0.19.0 is moved across the first
  time the new panel runs, so the choice carries over.
- **Nothing writes into the program folder any more.** The packaged Python
  wrote bytecode beside every module it imported. It goes to the user's
  temp folder now, the same arrangement as the macOS bundle. A local build
  was run and checked, no `__pycache__` anywhere in the package after
  running an app under it.

### Added
- **`PaperPull.exe`** beside `PaperPull.bat`, with the icon. It does the same
  thing, start the panel, open the browser to it, wait, and honors
  `PAPERPULL_PORT` so a second copy can run beside one that holds 8765.
- **An MSIX for the Microsoft Store** is built on every tag and proved to
  install and run on a clean runner. Not yet in the Store. The Store signs
  it on submission, which is the route to a Windows package with no
  SmartScreen prompt and no certificate of the project's own.

## [0.19.0] - 2026-09-17

The first release with installers, and the first that ships nothing built on
a developer's machine. Every file on the release page was built by GitHub
Actions from this tag on a clean runner, with checksums published by the same
run. It was 0.19.0-beta.1 and beta.2 for two days first, and the macOS build
went through a full install and a real download run on a Mac before the beta
label came off. The Windows installer is not yet code-signed, and the release
notes say what that looks like.

### Added
- **A macOS package, signed and notarized.** `PaperPull-<version>-arm64.dmg`
  carries the same panel, core and providers as the Windows package, built
  on a clean Apple Silicon runner, signed with a Developer ID, notarized by
  Apple and stapled, so it opens on any Mac with no warning. Double-clicking
  the app opens a Terminal window running the panel and a browser tab to it.
  Apple Silicon only.
- **A Windows installer.** `PaperPull-<version>-setup.exe` puts the
  control panel, the shared core and every provider on a machine with no
  Python on it. Nothing is frozen, it carries the official embeddable CPython
  and the same code as this repo. A zip of the same folder is there for
  anyone who would rather not run an installer.
- **A first-run screen.** A brand-new user is asked where the downloads
  should live and which providers they hold accounts with, and the panel
  creates an install for each. Someone with an existing set of downloads
  points the panel at that folder instead and keeps everything.
- **Upgrade in place.** `tools/upgrade.py` brings an install from any earlier
  version onto the current code without losing its history. It fixes the
  `localhost` CDP address, adds the settings a newer version expects, and
  backs up the config first. `tools/migrate.py` exports and imports the
  download history so a fresh install never re-downloads what an old one
  already has.
- **Remove a provider from the panel.** The folder is moved aside, nothing
  is deleted, and it can be added back.
- **Use the browser you already have.** Every app looks for Edge, Chrome,
  Brave, Vivaldi or Opera before offering the 400 MB Playwright download,
  and offers it only at sign-in when nothing else answers. `browser` in the
  config picks `auto`, `installed` or `bundled`.
- **Four providers**, taking the count to 26. Capital One (bank and card
  statements, tax forms, letters), U.S. Bank (credit-card statements) and
  Charles Schwab (statements, tax forms, letters, trade confirmations,
  reports, for brokerage and charitable accounts), all contributed by David
  Rudnick. PG&E (monthly billing statements), contributed by Champ. Each is
  marked in the provider table as ported with a fresh live pilot pending.
- **The panel says how a run went.** Every app prints a counts line at the
  end that the panel reads, so a run that downloaded nothing, failed
  something, or left files for manual review is told apart from a clean one.
  Contributed by David Rudnick, along with the Output and Status tabs staying
  usable while a run is going and a migration for legacy Chase keys.
- **Status tab** in the panel, showing how current each archive is and which
  periods are missing from the middle.

### Changed
- **One command for every app.** `paperpull <app> <command>` at the repo
  root (`paperpull.bat` on Windows, `./paperpull` on macOS and Linux, or
  `python paperpull.py` anywhere) finds an app by folder name, slug or
  provider, runs it under its own environment, and passes anything else
  through. The commands are the ones the panel offers, plus any mode an app
  has of its own. Requested in #23.
- **272 launcher files are gone.** Every app kept seven double-click files
  per platform that each called one script with one flag. Each app now
  ships `setup` and `login` only, and the docs say `paperpull <app> pilot`
  where they said `run_pilot.bat`. A test refuses the old files coming back
  with a provider cloned from an old checkout.
- The dispatcher ships inside the Windows package, so the terminal works
  there too, under the packaged Python.
- The shared core is 0.1.6.

### Fixed
- `tools/check_installs.py` and `tools/upgrade.py` compare an install's copy
  of the shared core file by file, not by version string. Nineteen installs
  carried a stale copy the string check called current, and every one of
  them crashed on Login. `upgrade.py --apply` refreshes the copy and keeps
  the old one in Backups.
- A test now refuses any function that clicks what a bare selector finds
  without consulting a guard, the shape of the PG&E fetch as it arrived.
- **Robinhood downloads.** The site changed the download link to a JSON
  answer carrying a pre-signed storage URL. The app follows it now and
  checks the bytes are a PDF before keeping them.
- **Eight bugs from a line-by-line review** of the new code before 1.0,
  among them a filename shortener that could produce an empty name, a merge
  that shared state between the two histories it was merging, and a status
  tracker that reported a change of statement schedule as missing documents.
- **The `new-this-run.txt` list is replaced on every run**, so a run that
  downloaded nothing no longer shows the previous run's files. Contributed
  by David Rudnick.
- **Every contributed provider had the same two gaps**, fixed on the way in.
  The verb `edit` was matched without a leading word boundary, so it matched
  inside `Credit` and refused `Credit Card Statement` on a credit-card
  provider. And the run-list and run-result changes above had landed after
  the branches were cut.
- **PG&E** needed more. The click that fetched a bill could fall back to the
  first link in the row, which is where Pay sits. Every row click now goes
  through the label guard and the row is matched to the bill's date first.
  Landing on any PG&E page counted as reaching the bill history. The port
  collided with Anthem's. The command flow is rebuilt on the pattern the
  other apps share.
- The status table's numbers line up under their headings, and the example
  path in the setup screen shows single backslashes.
- **Installs created by the packaged app no longer carry the double-click
  launchers.** They call a per-app venv the package does not have, so every
  one of them failed when clicked. The panel does their job.

## [0.18.0] - 2026-09-09

### Added
- **Anthem BCBS**, the 22nd provider and the first health insurer. EOBs,
  member and plan documents across all coverage years, digital ID cards, and
  secure-message letters. Contributed by David Riordan. The app clicks
  nothing, reading instead from the same authenticated endpoints the member
  app itself calls, with the bearer captured and replayed inside the page so
  it never reaches this process. Letters are read without being opened,
  because the list response already carries the body, so no message is marked
  read.
- **Move your download history to another computer.** `tools/migrate.py`
  exports what has already been downloaded and imports it into a fresh set of
  installs, so a new machine skips everything the old one had without copying
  a single PDF. Installs are matched by provider, so a renamed folder still
  lines up. An import never deletes, never downgrades, backs up first, and
  changes nothing when run twice.
- **Status inside the control panel.** A Status tab beside Output lists every
  archive with its document count, newest document, age, cadence and state,
  followed by the same possible-gaps section the console report prints.

### Fixed
- **Six apps crashed the moment a download started.** amex, dominion,
  redcard, robinhood, tmobile and verizon still imported `receipt_pdf`, which
  moved into the shared core weeks ago. Eleven dead imports, every one fatal.
  Reported by a user, because the imports sit inside functions where nothing
  in a test suite ever reaches them.
- **A browser profile could be written to the wrong folder.** Every config
  carries the profile as a relative path, so the app created it in one place
  and the browser resolved it to another. Four profiles holding live
  signed-in session cookies were found sitting inside the shared Playwright
  browser cache, which a browser update would have deleted without warning.
- **A change of statement schedule was reported as missing documents.** One
  bank moved three savings accounts from monthly to quarterly, and a single
  median across the whole history made every quarter afterwards read as two
  missing statements. Only a trailing run at a slower steady rhythm is
  excused now, so a genuine hole in the middle is still reported.
- **Discover is moving to Capital One.** A moved account was told to fix a
  sign-in that was never broken. It now says what actually happened, and the
  provider tables flag it. There is no Capital One support yet.
- Gap labels no longer repeat the account name when a summary already carries
  it.

### Security
- A test now proves a signed-in browser profile can never be committed. Three
  lines in `.gitignore` were the only thing standing between live session
  cookies and a public repo, and nothing checked they still covered every app.
- A test now walks every file in every app for imports at any depth, including
  the ones inside functions that a green test suite never touches.
- Anthem's PDF render fails closed. Its network block sat inside a bare except
  that swallowed failures and rendered anyway, on content an outsider can
  influence, in a page sharing the signed-in session.

## [0.17.1] - 2026-08-30

### Fixed
- **A failed download no longer leaves an empty file wearing a real
  statement's name.** Playwright creates the target file before the bytes
  arrive, so a capture that failed left a zero byte PDF sitting in the output
  folder looking exactly like a genuine download. Five of those turned up in a
  real archive. The run had reported them as needing review, but the folder
  said otherwise, and the folder is what people look at. All seven apps that
  download this way now remove the file they could not fill. The check also
  rejects a file that exists but does not start with the PDF marker, which
  catches an error page saved under a PDF name. It runs only on the failure
  path, so a tax archive that legitimately arrives as a ZIP is untouched.
- **Chase skipped every card whose name contains "rewards".** The card header
  was judged against the general control blocklist, which refuses "rewards"
  because "Redeem rewards" is a real button on a card page. Amazon Prime
  Rewards, Southwest Rapid Rewards and IHG One Rewards were dropped along with
  every statement they held, leaving one line in the log while the run still
  reported success. A card is now judged on action verbs instead, so a product
  name is not mistaken for a button.
- **The word "edit" matched inside "Credit".** The settings guard would have
  refused to open a document titled "Credit Card Statement". The pattern now
  requires a word boundary.
- **Signing in no longer fails silently when the browser is already open.**
  Launching Edge or Chrome while a copy is already running hands the address to
  the existing window and drops the settings the tool needs. A window opened,
  the sign-in was spent, and nothing revealed the problem until the next
  command. The debugging port is now confirmed at login, where it can still be
  explained.
- Chase kept only the first 40 characters of a card name as its key, so two
  cards of the same product collided and the second card's whole history was
  discarded as a duplicate. The last four digits are kept in the key now.
- Chase could click an unlabelled pagination element, because a selector
  matched any element whose class contained "next" and an empty label passed
  the blocklist trivially. It now requires a readable label.
- Chase host-checks the address before fetching a document with the signed-in
  session, rather than trusting whatever a click opened.

### Testing
- Guard coverage runs across every app at once rather than per app. Per-app
  tests are how these problems drifted into separate copies in the first place.
  765 tests.

## [0.17.0] - 2026-08-30

### Security
- **Every app now has a parsed host allowlist**, up from two out of
  twenty-one. A review found the rest would fetch or navigate to whatever URL
  a stored record or a page attribute contained, using the live signed-in
  session. One bank app accepted any href containing ".pdf" or "statement",
  including a fully off-host one. Four apps ran `page.goto` on a stored value
  unchecked. Twelve chose which browser tab to drive with a substring test, so
  "provider.com" also matched "provider.com.phish.example". Each allowlist is
  derived from that app's own base URL, and every app was checked to confirm
  the hosts it genuinely uses still pass.
- **Guards that existed but never ran.** Six apps defined a control guard and
  never called it in production. One called it with a hardcoded string, so it
  always returned true and gated nothing; it reads the control's real label
  now.
- **Settings controls could be clicked in every app.** Only bare verb stems
  were matched, so "Save Changes", "Document Removal" and "Loss Mitigation
  Application" all passed. The shared core now carries a verb-led pattern and
  every app consults it, so the next improvement lands everywhere at once.
- **One repo-wide test** now checks all of this across every app together.
  Testing it per app is what allowed the drift, since each app's tests only
  ever knew about that app.

### Changed
- The documentation no longer publishes account facts. It stated not just that
  a provider is supported but that a real person holds an account there, with
  document counts and date spans. The "verified against a live account" claim
  stays, because that is about the code. The tallies, spans and account
  inventories are gone, along with two real statement dates that revealed a
  billing cycle day, two real document identifiers, a personal default date
  shipped in a shared example config, and example paths naming private folders.

### Notes
- Two mistakes made and caught while doing the guard work, recorded because
  the shape of them matters. Folding money NOUNS into the label guard refused
  real documents in five apps ("Detailed Bill PDF", "Pay Statement"), so the
  guard is verb-led and holds none. Blocking a bare "save" also refused
  "Save PDF", so the rule was narrowed to the commit-shaped forms. Both were
  found by re-checking each app against its own document labels rather than
  trusting the change.
- Receipt apps keep a blocklist used inline rather than an allowlist, on
  purpose: they must still click "Load more", which a document-word allowlist
  would refuse.

## [0.16.0] - 2026-08-30

### Added
- **A status tracker** (`tools/status.py`, `tools/status.bat`). Reads the state
  each app already keeps and reports how current every archive is. Prints a
  table, and with `--html` writes a self-contained dashboard. Pure stdlib,
  reads local state only, downloads nothing and changes nothing.

  It answers "is something new probably waiting" rather than "when did I last
  run this". A run that only verified existing files still updates a timestamp
  while saying nothing about whether a new statement exists, so the signal is
  the date of the newest document actually held, measured against how often
  that provider issues them. The cadence comes from the archive's own history,
  measured per account, so nothing needs configuring.

  It reports the archives that EXIST. Nobody holds an account with every
  provider, so an unused folder or one left by a closed account is left out
  rather than shown as missing.

- **Gap detection.** Being up to date is not the same as being complete. An
  archive can hold a document from last week and still be missing whole years
  behind it, which happened twice in this project. Each series is now checked
  for periods missing from the middle. A series must earn an opinion before it
  gets one, because plenty of real documents arrive irregularly and flagging
  those would train you to ignore the report.

### Fixed
- **Six ways the status tool could report all-clear over a damaged archive**,
  found by red-teaming it. `--quiet` hid the gap report entirely, so the mode
  meant for routine checking printed "everything is current" over an archive
  missing a whole year. A single future-dated record masked a stale archive. A
  truncated state file made a provider vanish from the report rather than be
  flagged. One record carrying a timezone offset beside one without raised an
  error that destroyed the report for every provider. Text the console cannot
  encode killed the run before the dashboard was written. Each was reproduced
  first, re-attacked after, and pinned by a test.
- **Two code-execution vectors in the launcher**, both demonstrated working
  first. It is documented to live in a data folder, which is a plausible place
  for other software to drop a file, so a planted `py.bat` could run instead of
  Python and a planted `statistics.py` could be imported instead of the real
  module. The launcher now blocks both.
- A `.gitignore` gap: `config.json.save` and similar backup copies were not
  ignored, though they hold the owner name and local paths exactly as
  `config.json` does.

### Security
- **Repository history was rewritten** to remove a value that should never
  have been committed. An existing clone will not fast-forward, so re-clone
  rather than pull.

## [0.15.0] - 2026-08-29

### Added
- **DFAS myPay now serves active-duty accounts too**, not just retirees.
  Leave and Earnings Statements (LES), W-2s and corrected W-2Cs are enumerated
  using myPay's own document-type numbers, over the same API the retiree
  documents are proven on. One app covers both: a document type that does not
  apply to an account returns nothing and is skipped, so a retiree run is
  unchanged (re-verified against a live account).

  **This is untested against a real active-duty account** and is labeled that
  way in the app README and in the code. It should work and it may not. Run
  `diagnose.bat`, then `run_pilot.bat`, and check the PDFs before a full run.

### Fixed
- A corrected **W-2C would have been filed as an ordinary W-2**, making the
  correction and the original indistinguishable on disk. The W-2C rule is now
  matched first.
- **A regex corruption check that could not see the corruption.** Rules files
  have repeatedly been written with one backslash level eaten, leaving a
  literal control character where a word boundary belongs, so the pattern
  silently matches nothing. The existing check read the file's bytes, but JSON
  escapes a control character as two ordinary characters, so a corrupted file
  looked clean. The new check reads the PARSED values, confirms every pattern
  compiles, and runs across all 21 apps. It was verified by deliberately
  reintroducing the corruption and watching it fail.

## [0.14.0] - 2026-08-29

### Added
- **DFAS myPay retiree documents (21st provider)** (`apps/mypay`, CDP port
  9241). Monthly Retiree Account Statements (eRAS), CRSC pay statements, annual
  RAS, 1099-R and IRS 1095 forms. Read-only and delete-safe. Verified end to end
  against a live account, every document a valid and byte-unique PDF.

  myPay exposes a clean JSON API, so **nothing on the page is ever clicked,
  no form is submitted and nothing is navigated** - enforced by a test. On a
  system where direct deposit, federal and state withholding, allotments and
  SBP elections sit one nav click from the documents, not activating a control
  at all is the strongest guarantee available.

  **The session token never leaves the browser.** myPay authenticates with a
  bearer token plus three identifying headers. Rather than lift that
  government credential into this process, every call runs inside the page and
  reads the token in the same expression that uses it. It is never logged and
  never written to disk.

  **A document is identified by its type and date, not by myPay's numeric Id.**
  The first live run proved why: for generated documents that Id is a transient
  handle that does not survive the session, so stored ones returned 404 and
  every eRAS and 1099-R was recorded a second time under a new Id. The numeric
  Id is now looked up fresh at download time.

  The guard is built for a military pay account: direct deposit, routing and
  account numbers, allotments, withholding and W-4, SBP, SGLI, TSP,
  beneficiary, address, login ID and password, and every change / update /
  start / stop / consent / agree / submit / certify variant. The SSN field on
  the sign-in page is only ever detected as a signed-out signal, never read
  from and never typed into. `diagnose` writes no screenshot here, because a
  myPay page shows pay figures and identifiers.

## [0.13.1] - 2026-08-23

Hardening pass over the new M&T app, from a line-by-line review of it. Every
item below is a real defect that was found and fixed, not a precaution.

### Fixed (security)
- **A crafted on-host link could be queued as a document.** The collector
  accepted any URL merely *containing* a document endpoint name, so an on-host
  route carrying that name as a query parameter passed the host allowlist and
  would have been fetched with the live session cookie. Endpoints are matched
  against the URL path now.
- **The collector read, and clicked inside, every tab in the browser.** It
  attaches to an ordinary browser, so that meant unrelated sites. Every frame
  is host-checked before it is read or clicked.
- **The one click on the live path had no guard at all**, while the README
  claimed every click was checked. The year-expander click now checks its label
  against the blocklist, and the claim in the README was rewritten to describe
  what the code actually does.
- **The blocklist let settings and payment controls through.** "Save Changes",
  "Request Payoff Statement", "Open Escrow Options", "Loss Mitigation
  Application", "Document Removal" and others passed, because verbs were
  matched without their endings. Verb families and settings words are covered
  now, and a bare "Save" is refused rather than treated as a document action.
- **Redirects were followed unchecked.** They are capped, and the final URL is
  re-validated before anything is written.
- **Removed 282 lines of dead code** cloned from another provider, including
  four functions that clicked page controls with no check, one that rebuilt a
  stale deep link, and one whose own comment described a wrong-document bug it
  would have re-armed.

### Fixed (correctness and honesty)
- **An expired session produced a run that looked successful.** M&T answers
  with a sign-in page at HTTP 200, so every document was filed as "needs manual
  review" and the tool exited 0 having saved nothing. It now recognizes that
  response, stops, explains what happened, and exits non-zero.
- **A run that saves nothing no longer exits 0.**
- **1098 tax forms took their year from the availability date**, so a form for
  one year could be titled and dated as the next.
- An empty href resolved to M&T's home page and was downloaded as a document.
- The work tab was chosen by substring, which could select an unrelated tab.

## [0.13.0] - 2026-08-23

### Added
- **M&T Bank mortgage documents (20th provider)** (`apps/mtb`, CDP port 9240).
  Mortgage statements, year-end statements and 1098 tax forms from M&T's own
  online banking. Read-only and delete-safe. Verified end to end against a live
  account, all documents valid PDFs.

  M&T services its mortgages in-house (onlinebanking.mtb.com), not a
  subservicer. Documents are server-rendered with real per-document download
  URLs, so downloading is a plain host-checked GET of each document's own href
  and nothing on the page is clicked. Tax forms live on a second M&T host
  (m.mtb.com); both are allowlisted, parsed, never by prefix.

  Two things a mortgage portal forced, both handled read-only. The statement
  list only appears after you select the account and click View, a form submit
  this app does not perform, so you list it and the app reads whatever tab
  holds it. And the statements are split into collapsed year sections, only
  the current year open by default; the app expands each one (a read-only
  request that lists that year) so the full history is read. An earlier build
  silently captured only the current year, which is exactly the failure the
  pilot-then-inspect step exists to catch.

  The safety guard is tuned for a mortgage: it refuses paying the loan,
  autopay, payoff requests, escrow changes, refinance, recast and the rest,
  and a bare Edit/Update/Change too. The index records no balances or amounts.

## [0.12.0] - 2026-08-22

### Changed
- **Paylocity now fetches the whole pay-statement history, not just the
  current year.** The Pay History list endpoint defaults to a year-to-date
  view, but it takes a start date; the app now passes a far-past one and asks
  for everything. Confirmed against a live account.
  returned all 81 where before it saw 12. `--year` and `--start-date` still
  narrow the result.

### Notes
- **W-2 PDFs remain out of scope, and now the reason is precise.** Paylocity
  does not serve the W-2 as a PDF from its API. The form's link is a SAML
  single-sign-on redirect into a separate content system, and automating an
  SSO handshake into a third-party host on a payroll account is not something
  this project does. The finding is recorded in the app README so it is not
  re-investigated from scratch.

## [0.11.0] - 2026-08-22

### Added
- **Paylocity, the nineteenth provider** (`apps/paylocity`, CDP port 9239).
  Pay statements from the Paylocity Pay History area, read-only and
  delete-safe. The second payroll app after UKG, and the opposite kind of
  site: one fixed public address (access.paylocity.com), not a per-employer
  tenant. The employer is identified by the Company ID typed at sign-in, which
  the app never handles or stores.

  Nothing on the page is clicked. Discovery and download are plain GETs to the
  JSON endpoints Paylocity's own Pay History screen uses. A statement PDF is
  generated on demand, so download is a three-step flow the site itself
  follows: enqueue a report, poll until a download URL comes back, then fetch
  the PDF from it. On a site that can change direct deposit and withholding,
  not activating a control at all is the strongest guarantee available.

  A statement is identified by companyId, employeeId and history id, packed
  together rather than as a URL, so a query-string change cannot silently
  fetch the wrong file. The index CSV records no amounts, and the identity
  (which carries the employee id) is kept in discovery/progress only, never
  written to the CSV. Both are pinned by tests, alongside the payroll guard
  that refuses direct deposit, withholding, W-4, beneficiary and the rest.

  A run collects the current calendar year: Paylocity's Pay History
  defaults to a year-to-date view and this app reads that default. Older
  years sit behind the page's year filter, not wired up yet. W-2s are not
  fetched either, since Paylocity returns W-2 data as JSON rather than a
  PDF; the routing and folder are in place for both.

## [0.10.0] - 2026-08-22

### Added
- **AAFMAA (Armed Forces Mutual), the eighteenth provider** (`apps/aafmaa`,
  CDP port 9238). Annual statements and policy documents from the Member
  Center, read-only and delete-safe. Verified against a live account with a
  full run against a live account.

  The Member Center is classic ASP.NET WebForms, and it taught this repo
  three lessons the hard way:

  - **A postback name is not an identity.** WebForms names repeater controls
    by row position, so the same control name exists on every pager page and
    means "row 2 of whatever is showing". Documents are identified by title,
    date and policy, the pager is normalized to page 1 before every walk, and
    each download re-finds its row by content before clicking anything.
  - **Every saved statement must prove who it belongs to.** During a broken
    early run, a manually released PDF was captured under a different
    insured's filename, with a correct name, plausible size, and a clean
    validation pass. After download the file is read back and must contain
    its own row's policy number, or it goes to Manual Review with the reason
    stated.
  - **One dialog is answered, the only one in the project.** AAFMAA
    interposes a disclosure ("I confirm that I have read the message above")
    between the View control and some documents. The app answers it under a
    hard gate: matching dialog id, the disclosure's own sentence in the text,
    and not one money-related word, or it refuses. A dialog left over from an
    earlier document is cleared by reloading, never answered, because its
    View button belongs to a different document. SECURITY.md states the
    exception plainly.

  Only the default MY DOCUMENTS section is read so far. The Insurance
  Documents and Digital Vault sections are separate postback views, recorded
  as unimplemented in the app README.

### Fixed
- The build-a-provider issue template still told contributors ports 9237 and
  up were free while Discover holds 9237. It now says 9239+, matching the
  other three port documents.

## [0.9.0] - 2026-08-21

### Added
- **Discover credit cards, the seventeenth provider** (`apps/discovercard`,
  CDP port 9237). Card statements only, read-only and delete-safe, in a **real
  Edge/Chrome** window. Verified end to end against a live account
  (about two years of history), downloaded and checked, with a delete-safe
  re-run confirmed.

  Discover is the simplest bank-style provider so far, and the app is
  correspondingly small:

  - **Discovery is one read.** Every statement period's row, each with its own
    PDF link, is already in the DOM on plain page load - 24 links before any
    interaction, the same 24 after opening the period chooser. Nothing is
    clicked, no accordion expanded, no year swept. The Chase app's machinery
    exists because its rows only exist while one card's accordion is open on
    one year; none of it was carried over.
  - **A statement is served directly** at `stmtPDF?view=true&date=YYYYMMDD`, so
    the bytes are fetched with the signed-in context's own cookies using the
    href *read from the page* - never a URL built from a template, so a change
    to the query string cannot silently fetch the wrong period.
  - There is **no `<select>`** on the page: the period chooser is a link-based
    dropdown, which is why a select-based lookup finds nothing.

  The app slug is `discovercard` rather than `discover` because `--discover` is
  the CLI's own verb and the control panel has a **Discover** button; `redcard`
  sets the precedent of naming by the card product.

  A login with more than one Discover card is **unverified** and documented as
  such: the account this was built against has one card, so the page names none.

  On a full run, 22 of 24 listed periods downloaded and the two oldest returned
  `text/html` instead of a PDF. The app refuses to write a non-PDF body, so
  those are flagged for manual review rather than saved broken; the cause (a
  retention limit shorter than the listed periods, or rate limiting at the tail
  of a long run) is not established and is documented as open.

### Fixed
- **The statement-URL guard checks the host, not just the path.** The
  download fetch carries the signed-in session's cookies, and the old check
  accepted any absolute href (`startswith("http")`) so long as the path
  pattern and the date matched - review demonstrated a fetch from
  `evil.test` walking straight through it. The URL is now parsed and its
  scheme and host compared against Discover's own, which also refuses a
  suffix host (`card.discover.com.evil.test`) and a userinfo host
  (`card.discover.com@evil.test`), the two shapes that once walked through
  the UKG app's prefix-compared tenant guard. Found in review.

### Changed
- The Discover app's control guard - written for this app, backported to
  Ally and Chase as 0.7.2, then generalised into `paperpull_core.controls`
  in 0.8.0 - is deleted here in favour of delegating to that core module.
  The app keeps only its own vocabulary: `FORBIDDEN_CONTROL_RE`, and
  `PRODUCT_PICKER_RE` passed as an extra rule with the picker's options
  checked against it. The sign-in-form hole the local copy fixed is recorded
  under 0.7.2 and 0.8.0 below.

## [0.8.1] - 2026-08-21

### Fixed
- **Ally's and Chase's `--diagnose` never reported a refused dropdown.** When
  the control guard moved into `paperpull_core.controls` in 0.8.0, the
  verdict key in `describe_selects` became `refused`, but both apps' diagnose
  summaries still filtered on the old per-app key
  (`refused_as_money_control`), which the core never sets - so the "dropdowns
  refused" line could not appear, however many were refused. The JSON report
  itself was always right; only the printed summary read the dead key. Found
  while delegating the Discover app's guard to the core in #8.

- Core tests pin the key names `describe_selects` returns. Apps read them by
  name, so a rename deletes a caller's output without failing anything, which
  is exactly what happened above.

## [0.8.0] - 2026-08-21

### Added
- **The control guard moved into `paperpull_core.controls`**, so an app no
  longer decides for itself whether a control on the page may be touched. It
  declares its own provider vocabulary and inherits everything that is true of
  every provider.

  This is the fix behind 0.7.2 rather than another patch of it. The judgment
  had been written three times, in three apps, and only the third one written
  considered that a control might belong to a sign-in form rather than a
  money-movement widget. A shared rule means the next provider inherits that
  lesson instead of rediscovering it, which is how it was found in the first
  place.

  The module is deliberately opinionated about two things. It fails closed, so
  an identity that could not be read is unsafe rather than safe, because that
  is what a detached or mid-navigation element looks like. And it is tested in
  both directions, because a guard that refuses the year picker does not
  announce itself, it just makes discovery return nothing and an empty run
  looks like an empty account.

  Ally and Chase now delegate to it. Core is 0.1.5.

### Changed
- Core tests include a check that no shared pattern contains a control
  character. Writing a regex through a shell heredoc has twice turned a
  word-boundary escape into a literal backspace in this repo, which still
  compiles and then matches nothing.

## [0.7.2] - 2026-08-21

### Fixed
- **Ally and Chase could read and write a control inside a sign-in form.**
  Both apps refused a dropdown only when it looked like part of a
  money-movement widget, so a control whose identity said `login-form` or
  `signin-form` was treated as ordinary and could be selected. Nothing was
  ever submitted and no credential was touched, but setting a value inside a
  login form is not reading, and reading is all these tools do.

  It was reachable. Both apps navigate to guessed document URLs, and
  `--diagnose` recorded whether that navigation succeeded and then carried on
  regardless, inspecting whatever page it had landed on. A missed guess lands
  on a public or sign-in page.

  A control is now refused for belonging to a sign-in or registration form as
  well as for moving money, every control is refused outright while a password
  field is on screen, and `--diagnose` no longer inspects controls unless it
  is on a signed-in documents page. All four cases are pinned by tests in both
  apps.

  Found by David Rudnick while building the Discover provider, where the same
  defect had the app select inside a marketing site's login dropdown after a
  wrong URL guess. Backported here rather than left to land with that app.

## [0.7.1] - 2026-08-21

### Fixed
- **A run started from the control panel could hang showing nothing at all.**
  App subprocesses inherited the panel server's stdin, so `sys.stdin.isatty()`
  was true and an app on its first run asked for the account holder's name,
  waiting for input into a terminal nobody was looking at. Because `input()`
  writes its prompt without a newline, and the panel reads whole lines, the
  prompt was never shown either. The page displayed the command and then
  nothing, with every button disabled. Apps now get no stdin, so the prompt
  cannot happen and the run ends instead of hanging. Contributed by David
  Rudnick in #7.

### Changed
- The control panel's README records that an app run from the panel cannot ask
  for the account holder's name, so that column stays blank until it is set
  from a terminal or in `config.json`.

## [0.7.0] - 2026-08-21

### Added
- **Ally Bank, the fifteenth provider** (`apps/ally`, CDP port 9235). Account
  statements and tax forms, read-only and delete-safe. Verified end to end against a
  live account.

  Ally needed two things no earlier app did:

  - **Statements cannot be told apart by their metadata.** Ally posts several
    on the same date, one per account grouping, plus a copy of each joint
    statement addressed to each accountholder, and describes them
    identically: same `documentName`, same row label, no account information.
    Only `documentId` differs. So a downloaded statement is named from **its
    own first page**, whose account table and addressee are parsed
    structurally (by Ally's template text and the masked account-number
    column, never by a list of expected account nicknames, those are chosen
    by each customer). Unrecognized layout keeps the metadata name and says
    so; nothing is guessed.
  - **Every download is verified.** Because several rows look identical, the
    row clicked is an inference, so the app watches which `documentId` Ally
    actually serves and discards the file if it is not the one requested. This
    caught two real mismatches during development that would otherwise have
    filed one document under another's name.

  Tax forms come from the same endpoint with `docType=TAXFORMS`, found by
  opening the page's own tax tab and capturing the request rather than
  assuming the parameter. They file by **tax year, not posting date** (the
  2025 1099-INT is issued in January 2026), and a `corrected` form is flagged
  so it cannot be mistaken for the original.

- **Chase credit cards, the sixteenth provider** (`apps/chase`, CDP port
  9236). Card statements only, read-only and delete-safe, in a **real
  Edge/Chrome** window (the `verizon`/`walmart` pattern) rather than the
  bundled Chromium. Verified end to end against a live account.
  

  Chase's document center is one accordion per card with a styled "View:"
  year picker. Two things it taught:

  - **Attribute a document from its row, not from the API reply.** Every row
    names itself in full, "Aug 09, 2026 Statement SAPPHIRE RESERVE (...1234)
    Saves document", while the JSON reply carries no account field, and
    collapsing, expanding and changing the year all hit the same endpoint. A
    listener that tagged "the next reply" with "the current card" filed one
    card's statements under its neighbour; matching on the row cannot.
  - **A card that is already expanded never re-fetches.** The first live run
    silently missed one of six cards for exactly that reason, with a total
    that looked perfectly plausible. Every card is now collapsed before it is
    opened.

  Tax documents and year-end summaries are deliberately out of scope for this
  app.

## [0.6.4] - 2026-08-19

### Fixed
- **The control panel's Login button never finished, leaving every button
  disabled.** The sign-in browser inherited the launcher's stdout, and since
  the user is told to keep that window open, the panel's stream never reached
  end-of-file. The browser is now started with its stdio detached (which also
  stops its updater/crash-handler chatter flooding the console). On Windows it
  is additionally detached from the launcher's process group, so closing the
  launching console no longer takes the sign-in window with it.
- **On macOS, no app could find the bundled Chromium.** Playwright renamed its
  macOS bundle from `Chromium.app/Contents/MacOS/Chromium` to `Google Chrome
  for Testing.app/Contents/MacOS/Google Chrome for Testing`; only the old name
  was matched. On an up-to-date install every app silently launched Edge or
  Chrome instead, and on a Mac with neither, reported that no browser was
  installed while Playwright's Chromium sat right there. The tests missed it
  because they only ever constructed the old layout. Both are matched now, and
  the new one is covered by tests. Core is 0.1.4 so `check_installs.py` can
  tell an install still running the old lookup.
- **`.gitignore` did not cover hand-made copies of the state files.** A file
  such as `discovery.json.pre-fix` or `progress.json.bak` holds the same real
  account data as the original, but only the exact names were ignored, one
  such copy was nearly committed while building a new app. Suffixed copies
  and `*.json.bak` / `*.json.orig` / `*.csv.bak` are now ignored too.

## [0.6.3] - 2026-08-19

### Fixed
- **The control panel left a downloader running after you closed its tab.**
  `/api/run` streams a run's output over SSE; when the browser disconnected,
  nothing stopped the child process. The downloader kept going unseen - still
  driving your signed-in browser over CDP, still writing PDFs and
  `progress.json` - with no output on screen. Believing it had stopped, you
  could press Run again and put two runs on one `progress.json`, one CDP port
  and one output folder, which is the collision that has previously mixed two
  accounts. Closing the tab now stops the run. Nothing is lost: `downloaded_ok`
  is only set once a document is saved, so the next run resumes and re-fetches
  nothing.

  The stream had to become an async generator to fix this. With a sync one,
  Starlette wraps it in `iterate_in_threadpool`, which never calls `.close()`
  on it - so a `try/finally` around the loop looks correct, and still never
  runs. Verified over a real socket against a throwaway app, both for the
  disconnect path and for a normal run's exit code.
- `gui/app.py` raised `SyntaxWarning: invalid escape sequence '\S'` on every
  import - a `\Scripts` path inside a non-raw docstring. Harmless today, a
  `SyntaxError` in a future Python.

### Changed
- The control panel states the project's Python floor (3.11+) and checks it at
  startup, failing with one sentence rather than something obscure. Nothing
  under `gui/` had recorded which Python version it targets.


## [0.6.2] - 2026-08-18

### Fixed
- **The Dominion app was a Robinhood clone whose text and rules were never
  rewritten.** Dominion Energy is a residential utility, but the app described
  itself as "a brokerage / crypto account", and `login.bat` promised the user
  it "NEVER buys, sells, trades, ... moves crypto", telling them the wrong
  thing about what it does on their account. Its `document_rules.json` was
  Robinhood's whole vocabulary (consolidated 1099, crypto 1099, 1042-S, 5498,
  480.6, prospectus, trade confirmations), and its tests asserted that a power
  company issues "Crypto Statement" and "1099-B", and passed. Rules, tests,
  docstrings and the sign-in text now describe a utility that posts bills.
  This mattered beyond one app: `docs/adding-a-provider.md` recommends cloning
  `dominion` for statement providers, so every new app inherited it.
- **Contributor docs sent people onto a port already in use.** The issue
  template and PR checklist said "9222–9232 are taken; use 9233+" and
  CONTRIBUTING said "9234+", but Gap is 9233 and UKG is 9234. A colliding port
  makes two apps share one browser profile, which has previously merged two
  accounts' documents. All four documents now say 9222–9234 taken, 9235+ free.
- **`.gitignore` covered every output folder except `Pay Statements`**, the
  UKG one, holding the most sensitive documents in the project. PDFs were
  already ignored by `*.pdf`, so nothing leaked, but the folder was the only
  one not named.
- Five site modules claimed, two lines apart, both "verified working against
  the live site" and "best-guess scaffolding written WITHOUT having seen the
  signed-in pages" (Dominion, Navy Federal, Robinhood, USAA, Verizon). The
  stale half is gone.
- Dominion, RedCard, T-Mobile and Verizon each described themselves as a
  "statement & tax-document downloader" and precreated a `Tax Documents`
  folder, though none has any tax discovery at all, the same permanently
  empty folder 0.4.1 removed elsewhere and the UKG audit fixed for UKG. The
  routes remain, so a surprise tax document is still filed rather than dropped.

### Changed
- Eight statement apps carried `include_invoices`, `pilot_online` and
  `pilot_instore` in their config defaults. All three are receipt-app concepts
  and none was ever read by a statement app; they are replaced by the
  `pilot_count` those apps actually use.
- Removed two functions with no callers anywhere: `ensure_statements_page`
  (Amex, an alias) and `find_download_control` (Wealthfront), plus the unread
  `tax_center` URL in Dominion and Verizon, another Robinhood leftover, in
  both cases pointing at the billing page.

## [0.6.1] - 2026-08-18

### Fixed
- **`setup-all.bat` never installed the shared core, so a fresh Windows clone
  produced fourteen virtual environments that all failed at startup with
  `ModuleNotFoundError: paperpull_core`.** Every app has imported the core
  since 0.5.0, and each app's own `setup.bat` was updated to install it; the
  one-shot script was missed. `setup-all.command` on macOS was unaffected, so
  Windows was the broken path. It installs the core from `core/` in a repo
  checkout and falls back to the bundled wheel in a standalone copy.
- `setup-all.bat` downloaded Playwright's Chromium once per app. It is a
  single shared install, so thirteen of the fourteen downloads were redundant
 , and it is by far the slowest step.
- `setup-all.bat` reported "All set - 9 apps" regardless of how many it had
  set up; the count was hardcoded when there were nine. It counts now.
- The failure summary in `setup-all.bat` began `echo !!`, and `!` is the
  delayed-expansion escape, so `cmd` consumed the marker *and* the list of
  failed apps with it, the one line that says what went wrong printed as a
  bare `FAILED`.

### Changed
- Both `setup-all` scripts reuse an existing virtual environment instead of
  rebuilding it. Rebuilding one that is in use fails with a permission error,
  which is exactly the situation in which someone re-runs setup.

## [0.6.0] - 2026-08-18

### Added
- **UKG Pro / UltiPro, pay statements (14th provider), and a new category:
  payroll.** UKG is the first provider without a fixed address: every employer
  runs its own tenant, so the site is read from `base_url` in `config.json`
  rather than hardcoded, which also keeps it out of the repo, since a tenant
  address identifies the employer. Sign-in varies too (a UKG username and
  password, or corporate SSO with MFA); neither involves the tool.

  Statements and PDFs both come from the JSON API that UKG's own mobile app
  uses, over the ordinary session, so **on a site that can also change direct
  deposit and tax withholding this app never activates a control at all.** It
  additionally refuses any URL whose path says `EDIT` rather than `VIEW`,
  which is how UKG Pro itself separates the two.

  W-2s and other tax forms are *not* fetched yet; the routing and rules for
  them are in place, so adding them is a change to `ukg_site.py` alone.

### Fixed
- A first run with no `config.json` died with a `FileNotFoundError` traceback.
  It now names the file, gives the copy command for the platform, and explains
  why the file is not shipped. Malformed JSON reports the syntax error, and a
  config saved from Notepad with a BOM now loads. This is every app's first
  run, not just the new one.
- **UKG:** two pay runs sharing a date (a regular and an off-cycle) collapsed
  into one record, silently losing a statement. Repeated dates are now
  disambiguated by document number.
- **UKG:** the tenant guard compared URLs with a string prefix, so
  `https://tenant.example.com.evil.test/` and
  `https://tenant.example.com@evil.test/` both passed it. It now parses the
  URL and compares scheme, host and port, and rejects embedded credentials.

### Changed
- **UKG:** records store the API path rather than the full URL, so the
  employer's tenant address no longer reaches `discovery.json`,
  `progress.json` or the index CSV.
- The provider tables no longer claim UKG downloads W-2s, which it does not.

## [0.5.0] - 2026-08-17

### Added
- **macOS and Linux support.** Every app ships a `.command` launcher beside
  each `.bat`, with the same names and behavior, plus `setup-all.command` and
  `gui/run_gui.command`. Browser discovery is platform-aware: Playwright keeps
  Chromium under `LOCALAPPDATA` on Windows, `~/Library/Caches` on macOS (inside
  `Chromium.app`) and `~/.cache` on Linux, and the Edge/Chrome lookup that two
  bot-protected providers rely on knows where those live on each OS.
- **`paperpull-core`**, the support code the apps used to duplicate now lives
  once in `core/`. An app declares an `AppSpec` (its folders, routing, CSV
  columns and config defaults) and keeps only its orchestrator and `*_site.py`.
  About 15,400 duplicated lines became a 1,500-line core plus short
  declarations, so a fix lands once instead of thirteen times.
- **`tools/check_installs.py`** reports whether standalone installs have
  drifted from the repo. It reads only code, never config, state, CSVs, PDFs
  or browser profiles.

### Fixed
- AES-encrypted PDFs failed validation because pypdf needs its optional crypto
  extra; some providers issue them. Depending on `pypdf[crypto]` fixes it
  everywhere at once.
- Browser discovery picked the *oldest* installed Playwright Chromium, and
  sorted lexicographically so `chromium-1000` ranked below `chromium-999`.
  Newest build now wins.
- The macOS launchers referred users to `.bat` files, and their banner text was
  interpolated into double quotes, mangling output, and executing anything
  shaped like `$(...)` had a `.bat` ever contained it. Banners are now properly
  single-quoted.
- `setup-all.command` used an empty-array expansion that errors under `set -u`
  on the bash 3.2 macOS still ships.
- Running a launcher before setup gave a bare "No such file or directory"; it
  now names the script to run.

### Changed
- `SECURITY.md` and the README described the read-only guard as a blocklist
  **and** an allowlist for every app. That is true of the nine statement apps,
  which refuse any control not on the allowlist; the three receipt apps have no
  allowlist and screen a narrow print/invoice pattern against the blocklist,
  and Gap clicks nothing at all. Both documents now say what each app actually
  enforces.
- Test fixtures and code comments no longer carry real order numbers or a real
  carrier tracking number; they use same-shaped fakes.

## [0.4.1] - 2026-08-16

### Fixed
- **Gap**, in-store purchases are now separated from online orders. Gap's
  history page mixes the two; they were all being typed "Online" and filed in
  `Online\`. There is now an `In-Store\` folder (matching the Target and
  Walmart apps), online orders record the Gap Inc. brand that shipped them,
  in-store purchases record the store, and `--online` / `--instore` run one
  kind. Also fixes card-boundary detection: card text was bounded by length,
  so on an account whose cards are sparse the walk captured the whole list and
  every purchase inherited the first card's date. A card now ends at the first
  sibling order id.

### Changed
- **Gap** gained `run_online.bat` / `run_instore.bat`, matching Target and
  Walmart.
- **Amazon** drops the same dead invoice branch as Gap: `_handle_no_receipt`
  was never called, so the `Invoices\` folder and the `include_invoices` knob
  it depended on could never be reached. What Amazon saves is unchanged, its
  printable order summary is captured as the receipt, as it always was.
- **Every app** now creates only the document folders it can actually fill.
  Each app was cloned from the nearest existing one and inherited that app's
  whole folder list, so installs grew permanently-empty folders, `Insurance
  Documents` (real only for USAA, which is also an insurer), `Other Documents`
  (never a configurable document type), and `Invoices` (reachable only in the
  Target and Walmart apps). Routing is unchanged and now creates a folder on
  demand, so a category that is reachable but rare still gets its folder the
  moment a document lands there. Nothing that holds documents is affected.

## [0.4.0] - 2026-08-16

### Added
- **Gap Inc.**, order receipts (13th provider). One Gap login covers Gap, Old
  Navy, Banana Republic, Athleta and Gap Factory, and a single order history
  holds orders from all of them; the brand is recorded per order. The order
  history lazy-loads on scroll rather than paginating by year, so discovery is a
  single scrolled pass over everything Gap still exposes (about the last 13
  months). Gap ships no printable invoice and no print stylesheet, so each
  order's own details page is captured: the app waits for the page to load its
  data, hides everything outside the purchase-summary block (a display-only
  change to the local page), and renders the result with `printToPDF`, a
  receipt with the purchase header, line items and charge summary, and none of
  the site navigation.

## [0.3.1] - 2026-08-16

### Security
- **GUI control panel** now refuses any request whose `Origin`/`Referer` host is
  not localhost, closing a cross-site "trigger a run" vector on the command API
  (`/api/apps`, `/api/run`). The server already binds to `127.0.0.1` only and
  has no CORS; `SECURITY.md` now documents the localhost/CDP posture (close the
  signed-in browser when you're done, while it is open, any local process could
  attach to its debugging port).

## [0.3.0] - 2026-08-16

### Added
- **Verizon (Fios)**, Fios / Home Internet bill statements (10th provider).
  Uses your installed Microsoft Edge (T-Mobile-style bot protection blocks the
  bundled Chromium) and captures downloads via a controlled directory over CDP.
- **T-Mobile**, monthly bill statements (11th provider). Reads the bill-history
  page and downloads each period's detailed-bill PDF via a real download event.
- **Target RedCard / Target Circle Card**, monthly billing statements (12th
  provider). The RedCard credit account is serviced by TD Bank USA; reads the
  statements table (per-year switcher) at mytargetcirclecard.target.com and
  downloads each row's statement PDF via a real download event.

## [0.1.0] - 2026-08-15

First tagged release.

### Apps (9 providers)
- **Amazon**, order invoices, full order history
- **American Express**, statements + year-end summary
- **Dominion Energy (VA)**, billing statements
- **Navy Federal Credit Union**, account statements
- **Robinhood**, account statements + tax documents
- **Target**, receipts
- **USAA**, statements
- **Walmart**, receipts
- **Wealthfront**, statements + tax documents

### Features
- Read-only, connect-to-your-browser design, you sign in yourself; the tool
  never handles credentials or bypasses 2FA
- Delete-safe skip, deleting PDFs after importing them elsewhere never causes
  a re-download
- Account-holder ("owner") tagging: a first-run prompt plus an "Account Holder"
  column in the index CSV
- Multi-account support via `--config`
- Local FastAPI **control-panel GUI** that drives every app
