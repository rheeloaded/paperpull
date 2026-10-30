# Changelog

All notable changes to PaperPull are recorded here. Versioning follows
[Semantic Versioning](https://semver.org):

- **PATCH**, bug fixes, or repairing an app after a provider changes its site
- **MINOR**, a new app, or a cross-app feature
- **MAJOR**, breaking changes (repo layout, config format, removing an app)

## [0.59.2] - 2026-10-30

Bank of America knows Statements & Documents at the second address a
tester's window showed. Continue no longer goes round and round after a
list that was not read to its end, and the panel offers Get new
documents in its place.

### Fixed
- **Bank of America knows Statements & Documents at its second address
  (#121).** A second tester's window was on Statements & Documents at
  /statements-documents/home/ on secure.bankofamerica.com, and the run
  said the tab was not on it and asked nothing, since the app knew the
  page only by the address the first tester's recordings showed. That
  path, letter for letter, now counts as the page too. A page below it,
  the same path on another host, or the path inside another address is
  not taken for it, and a press that takes the tab to a page below it is
  followed by going back, as at the first address.
- **Continue no longer goes round and round after a list that was not
  read to its end (#124).** A Chase run stopped before it read the whole
  list, and every Continue after it said the list was not read to its end
  and to run Pilot or Run All, and then stopped. The summary under that
  said Resume carries on, and the panel offered Continue again, so pressing
  it could never get anywhere. Such a stop now says so in the run's result,
  and the panel offers Get new documents in its place, on the account's
  row, on its page, on the run's own page and in Get new for all, where
  trying such an account again reads the list rather than continuing the
  same way. The run's last line says to run Pilot or Run All. It is the
  same for every provider whose Continue carries on from what is listed,
  63 document apps and Anthem, and for a receipt app's Continue on an
  install that never listed anything. Any other stop, a sign-in, a page
  that would not open, or a Continue that reads the list again itself, is
  continued as before.

## [0.59.1] - 2026-10-27

Bank of America saves statements when the page's Download PDF links have
no address of their own, by pressing one once and learning how the page
asks for a PDF. A failure file no longer calls a list answer empty for an
empty errors list beside its rows, and one bad field no longer silences
its summary.

### Fixed
- **Bank of America learns how its page asks for a PDF when the Download
  PDF links have no address (#121).** On 0.59.0 the Statements heading
  opened as it should, and the run still saved nothing, since the page's
  one Download PDF link had "#" for its address and opens its PDF by a
  script of its own. The app now presses one such link, once a run, and
  hears the call the page makes for that PDF, a GET, or a POST of JSON or
  a form, on bankofamerica.com, naming no change, that holds exactly one
  listed statement's id. It keeps nothing the press brought, cancels the
  download and closes the tab the press opened, asks that call once more
  for the same statement, and keeps it only when that answers with a PDF.
  Each statement is then asked with its own call, from inside the page.
  The link has to be a link, not a button, whose words beside the bank's
  own names for the statements and accounts it listed pass the blocklists,
  read again right before the press, with nothing drawn over it. Login,
  Discover and Diagnose press no link, and a stop says in counts what the
  press brought.
- **A failure file no longer calls a provider's answer empty when it is
  not.** Its summary said an answer came back "with an empty list in it,
  which is an account with nothing in it or a filter that excluded
  everything" when any one list anywhere in the answer was empty. A list
  answer often carries an errors list with no errors in it beside the
  rows it found, and each row a list of its own with nothing in it, so
  Bank of America's statement list, holding ten statements, was called
  empty and sent a reader the wrong way. A row's own lists and an empty
  errors list no longer count. The summary now names the empty lists and
  says whether others held items, and what an empty one would mean is
  said only of the list the app reads, which the file cannot know.
- **Reading a failure file back never loses its whole summary to one bad
  field.** A file edited by hand or cut short by the disk could hold a
  field of the wrong type, a request's status as text or a journal
  entry's count as a list, and the summary raised on it, so the app
  printed none of its sentences. Each part of the summary now reads its
  own fields, and a part that cannot read them says nothing while the
  rest still speak.

## [0.59.0] - 2026-10-26

Bank of America downloads checking, savings and credit card statements,
with the stop from its first real run fixed. Navy Federal, Costco and
PayPal check a saved document against each kind of look-alike apart, nine
apps stop rather than call a list whole when part of it was not read, and
Capital One and Schwab no longer download statements saved before 0.34
again. pypdf 6.21.2 closes three advisories.

### Security
- **The Windows and Mac packages and the server image take pypdf 6.21.2
  and setuptools 84.1.0.** pypdf 6.21.1 has three advisories fixed in
  6.21.2, each a PDF made to keep pypdf reading for a long time, through
  repeated references to one missing object (GHSA-6c7f-9265-g8fw), a
  cross-reference table with wrong upper limits (GHSA-gmh7-3g9r-mjh5) or
  repeated malformed cross-reference streams (GHSA-jr96-gvgh-j3r4).
  PaperPull reads each PDF in a process of its own that is stopped after
  two minutes, so such a PDF was set aside unread and the run went on.
  setuptools 84.0.0 has a low advisory about installing old style wheels
  on Windows (GHSA-xmj3-9gf7-h52w). The packages use it only to build
  PaperPull's own core and then remove it, and the server image runs on
  Linux, so neither reached it. A checkout's requirements ask for pypdf
  6.21.2 as well. The packages also take starlette 1.9.0, which the
  server image already ran, and the image takes starlette 1.10.0.

### Added
- **Bank of America downloads statements (#121).** Checking, savings and
  credit card statements from Statements & Documents, built from the two
  recordings @appchamp made, one trip to a checking statement and one to a
  card's. His first run listed every statement and saved none, so it is
  still untested. Sign in, open Statements & Documents and leave the
  window there. The app reloads that page, keeps the list call the page
  makes, and asks every account's statements the same way from inside the
  page, year by year. The reload leaves the page's Statements heading
  shut, with no Download PDF link drawn under it, which is where his run
  stopped, so before it downloads, the app opens that heading, the one
  press it makes. It learns the form of the page's own Download PDF links
  and asks for each statement at its own address in that form. A statement
  is filed only when its text names its own day and account better than
  the other accounts' statements of that day and its own account's either
  side of it, and anything else goes to Manual Review. A file the bank
  names for another day is never filed. A page that does not answer the
  way the recordings showed stops the run with a failure file of counts
  rather than a guess. Login says you are signed in only when the
  statements list answered. With several Bank of America tabs open, the
  run works in the one on Statements & Documents, and stops when more
  than one is there. Tax forms are not covered yet.
- **PaperPull Server can answer only to the names you list.** By default
  the panel answers to the server's address, to a name without a dot such
  as `nas`, to a name ending in a home network suffix such as `.local`, and
  to the names in `PAPERPULL_HOSTS`. With `PAPERPULL_HOSTS_ONLY` set to `1`
  it answers only to the names and addresses in `PAPERPULL_HOSTS`, an
  address matched however it is written, and to the container's own
  loopback, which the self-test uses. A refused name gets a page saying the
  setting is on and where to add the name, and when nothing is listed the
  container's log says so at start and the self-test's network row fails.
  Plain HTTP and the default names are unchanged.

### Fixed
- **Navy Federal, Costco and PayPal check a saved document against each
  kind of document it could be taken for apart.** The check that a saved
  PDF is the one asked for counts only what no other listed document
  shares. Navy Federal asked it once, against the other account's
  statement of the same day, which shares the day, and the account's own
  statements either side, which share the account, so on a day both
  accounts are billed neither counted and the statement was filed
  unchecked. Now each statement is checked against the other accounts'
  of its day, then again against its own account's either side, which
  catches another month of the same account on such a day. On the
  maintainer's 64 statements every one is still filed, and 120 of 124
  swaps with the month either side are caught where one check caught 95.
  Costco did the same with a receipt that shares its day with one
  purchase and its total with another day's, and PayPal with a custom
  statement whose first day is one statement's and last day another's,
  which now is filed when both its days check out instead of waiting in
  Manual Review every time. A core census holds every app to it.
- **Wells Fargo, SBA and American Family read a document's button drawn as
  an input like any other button.** The core finds a document's button by
  its role and its name, and a page can draw one as an `<input>` of type
  button, submit, image or reset. The three apps counted only links and
  buttons as the page's document controls, so such an input was no other
  document control to them. Two statements of a day drawn so under one date
  heading were one entry, and the first was pressed for both. A View that
  names no kind, beside a tax form's part whose button was drawn so, read
  that part's words as its own, so View was pressed for the tax form and
  saved as it. And a tax form whose row prints no date took the date of a
  statement row drawn so, and was filed and pressed under that date.
  American Family's row rule also took a list for the row of a bill naming
  its own date beside a 1099 row drawn so, and left that bill for a person
  every run. Now each app counts those inputs as document controls, American
  Family's row rule included, and a page drawn with them reads exactly as
  the same page drawn with buttons. The twins were found by a fresh review
  of SBA's and American Family's reading and proven on all three apps, and
  the other shapes were found while fixing them, each proven in a browser
  before the change. The statements a tester's recordings show for Wells
  Fargo and American Family are links, which this leaves as they read.
- **Wells Fargo reads a masked number and the part around a link the way
  SBA and American Family do.** 0.58.0 gave the three apps one reading of
  what a document is, but the two fixes the fresh review of SBA's and
  American Family's copy found reached only those two. On Wells Fargo, in
  0.58.0 as in 0.57.1, a statement whose masked number runs into the
  control's own words, as two spans touching draw
  `Checking ****1099View statement`, was filed as a Tax Document, since any
  letter after the digits was taken for a form's name. And a 1099-INT whose
  button names only its date, beside the form's name and a hidden field of
  a form, an empty anchor or a control shown only on hover, was filed as an
  Account Statement, since the part read around the button stopped at that
  control. Now only a form's own letters after the digits, as in 1099-B or
  1099INT, make them a form's number, and the part read around a link stops
  only at a control drawn on the page, so both are left for a person,
  counted in Diagnose. A document is still filed only where the reading
  without the two rules agrees. The test that holds SBA's and American
  Family's copies of this reading alike now holds Wells Fargo's too, its
  whole reader compared with SBA's.
  Found by the fresh review of the SBA and American Family port and proven
  in a browser before the change. The statement links a tester's recording
  shows name their own kind and date, which neither shape touches.
- **Wells Fargo, SBA and American Family leave two more look-alike
  statements for a person.** A statement whose link names only an account's
  masked number ending 1099 and its date, as
  `Checking ****1099 01/31/2026 PDF` does, under a heading or beside words
  that name tax documents, was filed as a Tax Document, in 0.58.0 as in
  0.57.1. The two readings without the rule for masked digits took the
  digits for the form, and the careful reading took its kind from the tax
  words around the link, so all three agreed. And a masked number running
  into E-Statement or E-Bill, as in `Checking ****1099E-Statement` or
  `Policy ****1099-E-Bill`, was read as a form's name, since E is a form's
  letter, as in 1098-E. A form's letter with a dash and a letter after it
  now starts another word. A masked number's last digits now never decide
  a kind either way. A control whose kind the careful reading finds only by
  reading past such digits, in its own words or in the words around it, is
  left for a person, counted in Diagnose and held as the kind the other
  readings filed it as, so the day's real 1099 beside the first statement
  is still refused as its twin. That also leaves for a person a 1099 named
  after a bullet beside a link naming only its date, which 0.58.0 filed as
  a statement. The fresh review of this change found that the dash rule
  alone did the same to a 1099-R named "1099-R-IRA distribution" after a
  bullet. The change is the same in all three apps, and the test
  that holds their readers alike holds it. Found by the fresh review of the
  Wells Fargo change above and proven in a browser before the change. The
  statement links a tester's recording shows name their own kind and date,
  so neither shape touches them. A form whose link names only a masked
  number and its date, and a link naming only its date beside a masked
  number, are now left for a person even where the row names the form.
- **State Farm counts a button drawn as an input when it ties a document
  to its row.** State Farm finds a row's View Documents by its role, and an
  input of type button, submit, image or reset has a button's role, so it
  finds and presses one drawn that way. Its two checks around the press
  counted only links and buttons, though. Under a date heading, when a
  newer notice was added and opened in the pressed row's place, the other
  row's View Documents drawn as such an input did not say the notice might
  be that row's, and the newer notice was saved under the pressed row's
  name. In a category drawn as one row, a mailed entry's control drawn as
  an input did not stop the walk from the opened entry either, which took
  the mailed entry's date and had another day's document saved under it.
  Both checks count those inputs now, as they count buttons, and such a
  page is refused as the same page drawn with buttons is. A box to tick or
  a text field is still not counted.
- **Golden 1 keeps each account's history apart when its statements or
  its Statement History are drawn as inputs.** Golden 1 finds a dated
  statement and a Statement History by its role, and an input of type
  button, submit, image or reset has a button's role. Before each press it
  marks every control on the page, so a list the press brings can be told
  from one the dialog still shows, and it finds each account's panel by
  its Statement History, but both counted only links and buttons. With the
  statements drawn as such inputs, the list an account before left in the
  dialog was taken for the next account's when that account's own never
  came, and its statements were listed and saved as the next account's.
  With every Statement History drawn so, no panel was found, and the
  history of the panel that was open was read under the first account's
  key. Both count those inputs now, and such a page reads as the same page
  drawn with links.
- **American Family tells one bill's statements from another's when a
  Bill details is drawn as an input.** It finds each bill's Bill details by
  its role, and an input of type button, submit, image or reset has a
  button's role. Reading a bill's account from its card, and checking that
  what a press brought sits around no other bill, it counted only links
  and buttons as another bill's Bill details. So a bill whose card shows no
  number took the account number of the card beside it, and its statements
  were saved under that other bill's account. Statements a press drew
  around another bill's Bill details drawn as an input were read as the
  pressed bill's too, and were saved as its own, or sent both bills' copies
  to Manual Review. Both readings count those inputs now, as they count
  buttons. A box to tick or a text field named Bill details is still not
  one.
- **Bilt stops the list when the statements sheet shows a Load more drawn
  as an input.** A sheet showing a control for more, older or earlier
  statements stops the list, since the statements answer and the sheet
  could then agree on a part of it. That check counted only links and
  buttons, and read a control's text, label and title. A Load more drawn
  as an input of type button, submit, image or reset, which the browser
  gives a button's role, was not counted, so a part of the list could be
  read as whole. It is counted now, read by its value or an image's alt
  too. A box to tick or a text field reading the same words is still not a
  control for more.
- **Schwab opens its statements page at its new address (#122).** Schwab
  moved Statements & Tax Forms from /app/accounts/statements to
  /retail/accounts/statements, and the old address now redirects there.
  The app knew only the old one, so every run stopped saying it could not
  open the statements page. It now takes either, and only as the page's own
  address on Schwab's own host, never one named in another page's query or
  after its #. Thanks to @davidrudnick for the fix and the live run.
- **Capital One and Schwab no longer download a statement saved before
  0.34 again (#122).** Both keep a document under its account, and up to
  0.33 both numbered the documents of one day, type and title within each
  account. From 0.34 they were numbered across accounts, so when two
  accounts each had one such statement, both saved at 0, the second
  account's found 0 taken, was numbered 1, and was downloaded again beside
  the one saved as a "(2)" copy. Each account's documents are numbered on
  their own again. An archive numbered across accounts from 0.34 to 0.58
  keeps every number it has, two documents alike in one account included,
  and one that already took the "(2)" copies keeps both records and
  fetches nothing more. The same holds once the history moves to another
  computer through Export and Import history, whole or with --minimal,
  since the app then reads each saved number off its record's key.
  @davidrudnick found it in an archive going back to
  0.19 and wrote the Schwab fix, which on that archive fetched exactly the
  20 new documents. Capital One had the same numbering and takes the same
  fix.
- **NetBenefits saves a statement that names its plan only by type and
  employer (#123).** On a sign-in with several plans, a statement must
  name the plan it was made for, or it is set aside as the wrong document.
  A 457(b)'s statements from mid 2022 on print a line naming the employer
  and the title `457b Deferred Compensation Plan Retirement Savings
  Statement`, never the plan's name on Choose a Plan, so all 18 were set
  aside. Such a statement now counts as the plan's when the plan's name on
  the list gives its type, the site's header named one employer on the
  pages that showed the plan, every statement title in it is of that type
  and one follows that employer's name, it names no other plan and gives
  no type of a plan that may be at that employer, no other employer's name
  ends that employer's name, and no other plan on the sign-in may be of
  that type at that employer. A plan whose name gives no type counts as
  one that may be, unless the header named another employer on its page,
  or, for a plan whose page names none, its employer's combined statement
  places it at another employer. That statement must name the plan and the
  one it was made for, carry that plan's employer as the header named it,
  and carry no other employer's name, and one saved by an earlier run is
  read again while the header still names the same employer for its plan.
  A statement waiting only on such a plan is held in Manual Review, judged
  again at the end of each run that shows its plan, and filed or set aside
  once that can be told, never filed unchecked. A type glued to the words
  before it, as in `EMPLOYER MEM401K`, counts. A second plan of the type
  at the employer, the employer's combined statement and another
  employer's statement of the type are still set aside.
- **U.S. Bank never calls its statement list whole with an account or a
  year left out.** The list is read account by account and year by year
  through the page's own pickers. An account whose choice did not take, a
  year the picker would not take or still showed the year before for, and
  a picker that would not answer or listed none of its accounts or years
  were each passed over, and the list was still noted as read whole. So
  Resume could call a run finished with an account or a year never read.
  Now the run keeps what it read and takes it, says which picker it could
  not read through, writes a failure file and stops at its end rather than
  finish, so the next run reads the list again. A list that would not be
  counted, and rows the page's text reading could not read, stop the list
  as rows that would not answer always did, and that reading never chooses
  an option that is turned off or that the guard refuses.
- **Meijer no longer takes a tab whose rows were still changing for one
  read whole.** Discovery waits for a tab's rows to stop changing before
  it reads them. When they were still changing as the wait ran out, it
  read them all the same, counted the tab as read and noted the order list
  as whole. Now the purchases read are kept and the run goes on with them,
  but it says the list was not read whole, writes a failure file and stops
  at its end rather than finish, so Resume reads the list again. Such a
  tab never counts toward saying a purchase is no longer listed.
- **Citi takes no second copy of a statement kept for review, and an
  empty requested list no longer sets requested statements aside.** A
  regular statement put aside for review with its file kept was not
  counted as saved, so once Citi listed its month as a requested statement
  that came as a second file. And an answer listing no requested
  statements marked every requested statement not yet saved as No Longer
  Listed until a later list showed them again. An empty list now sets
  nothing aside, and a requested statement is still marked No Longer
  Listed once the last day Citi lists it has passed.
- **Chase never calls its statement list whole with a year or a card left
  out.** The list is read year by year through the "View" picker and card
  by card through each card's own accordion. A year the picker listed and
  would not take, and a card whose accordion would not open, were passed
  over, and the list was still noted as read whole, so Resume could call a
  run finished with a year or a card never read. The page's text reading,
  used when that walk finds nothing, did the same with an account or a
  year its dropdowns offered. Now the run keeps what it read and takes it,
  writes a failure file and stops at its end rather than finish, so the
  next run reads the list again. A year the open picker does not list, an
  option that is turned off and one the guard refuses are never chosen,
  and are left as they were.
- **Discover credit cards never call the statement list whole with an
  account or a year left out.** When the statement links read nothing, the
  page's text is read under each account and year its dropdowns offer. An
  account or a year whose choice did not take was passed over, and the
  list was still noted as read whole. Now the run keeps what it read and
  takes it, writes a failure file and stops at its end rather than finish,
  and that reading never chooses an option that is turned off or that the
  guard refuses.
- **Navy Federal never calls its statement list whole with an account
  group or a year left out.** Each account's statements show in a group
  opened with the others folded, and Previous Statements shows one year at
  a time. A group that would not open on its own and a year whose choice
  failed were passed over, and the list was still noted as read whole. Now
  the run keeps what it read and takes it, writes a failure file and stops
  at its end rather than finish, so the next run reads the list again. A
  year that is turned off is never chosen, and a group whose header's
  words sit on two lines is now opened like any other.
- **Wealthfront never calls its document list whole with a tax year left
  out.** A tax year its dropdown offered and would not take was passed
  over, and the list was still noted as read whole. Now the run keeps what
  it read and takes it, writes a failure file and stops at its end rather
  than finish. Tax years read from the page's text, with no dropdown to
  choose them in, and a year that is turned off are left as they were. A
  statement type the filter would not take is still passed over quietly,
  since an account may hold none of that type.
- **Newrez never calls its document list whole with a statements page or
  a year left out.** The monthly and yearly statements pages are opened by
  their addresses, and the monthly page's year picker is walked. A page
  whose address would not open and a year the picker offered whose choice
  would not take were passed over, and the list was still noted as read
  whole. Now the run keeps what it read and takes it, writes a failure
  file and stops at its end rather than finish. A year whose list never
  shows is left as it was, since a year with no statement never shows one.
- **Costco never calls its purchase list whole with a tab or a quarter
  left out.** Discovery reads the Warehouse and Online tabs and each
  quarter the Showing picker offers. A tab that would not open and a
  quarter the picker would not take were passed over, and the list was
  still noted as read whole, so Resume carried on without reading it
  again. Now the run goes on with what it read, writes a failure file and
  stops at its end rather than finish, and Resume reads the list again. A
  quarter that is turned off is never chosen.
- **Target never calls its purchase list whole with a year left out.** On
  a history page with a year filter, a year the filter offered that could
  not be chosen was passed over, and the list was still noted as read
  whole. Now the run goes on with what it read, writes a failure file and
  stops at its end rather than finish, and Resume reads the list again. A
  year that is turned off is never chosen. Target's history page shows no
  such filter today, so this holds for a page that brings one back.
- **Fairfax Water's and Affirm's COMMANDS.txt describe their own app.**
  Both were cut from a retirement plan's, so each said it downloads
  participant statements and a 1099-R, never moves money between funds,
  and files under Tax Documents\. Fairfax Water's now says it downloads
  water bills, and Affirm's that it downloads one loan agreement per loan,
  each with what its guard refuses and the folder its files go in. The
  commands in them were right and are unchanged.

## [0.58.0] - 2026-10-24

Wells Fargo opens Statements & Documents from the Accounts menu again, and
it, SBA and American Family tell a statement from a tax form of the same
day far more carefully. A first Bank of America shell is ready for a tester
to record. A split order's invoices take a new name together, and the
documents folder from 0.57.0 gets a round of fixes.

### Added
- **Bank of America, a first shell for a tester (#121).** Add it from
  the panel, sign in with Login, and press Record on one trip to a
  statement. That recording is what the real app is built from. This
  first build opens www.bankofamerica.com in a browser profile of its own
  and does nothing more. It presses nothing on the bank's pages and acts
  only on bankofamerica.com. Discover, Pilot and Run All say it is not
  built yet and stop, and Resume says nothing has been listed yet, so
  nothing is listed or downloaded. Login
  names a sign-in form or a check and never says you are signed in,
  since this build knows no signed-in page yet.

### Fixed
- **SBA and American Family tell a statement from a tax form of the same
  day.** Both kept one document for each date, named for the first control
  of that date they could read, and the download pressed the first control
  carrying the date, whatever it fetched, the shape Wells Fargo was fixed
  for in 0.42.0. So when a 1098 or a 1099 and a statement shared a date
  only one of them was ever found. And when the tax form could not be read
  while the page was surveyed, it was passed over, the date was recorded
  as the statement, and the download pressed the tax form and filed it as
  the statement. Now both read a control the way Wells Fargo does. A
  document is its date, its kind and the entry it sits in, so a statement
  and a tax form of one day are two documents, each pressed for itself,
  while View and Download of one statement stay one. Each control is read
  two ways, the way the app always read it, American Family's own row rule
  included, and with care, never taking another control's words or dates
  or a date printed over a list of rows. Read with care, the last digits
  of a masked number, a loan or a policy ending in 1099, are never a tax
  form, and a link that names only its date takes its kind from the part
  of the page that holds it alone. A control is filed only where the two
  readings agree on its date and its kind, and where they disagree it is
  left for a person and counted in Diagnose. Two entries of one day
  holding the same kind cannot be told apart, and that document is refused
  rather than guessed at, even when the download can see only one of the
  two. A control that would not answer stops the download from choosing
  past it, American Family's included when the page draws it again while
  it is read, and the control chosen is read again as the element that is
  then pressed. American Family reads each bill's list behind its Bill
  details this way, and its titles still name the two kinds it has always
  listed.
  Found by reading the code and proven in a browser before the change.
  Both apps are still untested, so no archive is known to hold a misfiled
  document.
- **A folder of one person's own can no longer hold the folder for every
  provider.** The documents folder page refused a person's own folder that
  was the folder for every provider or inside another person's folder in
  it, but not one around it, so a spouse's own `D:\Docs` with
  `D:\Docs\PaperPull` for every provider put everyone's documents inside
  the spouse's folder. That is refused now whichever is saved first, so to
  use such a folder for every provider, choose another folder for that
  person first. A run gives a person added since no folder inside such a
  folder, and the page says so rather than promise one. Where an earlier
  version already saved the folder for every provider inside a person's
  own, **Use it for every provider** gives that person a folder inside it
  too.
- **Move documents goes where the page says.** The panel filled in a
  person's folder in the folder for every provider before any action, a
  Move and its preview included. So an account with no documents folder
  setting, one set back to its provider's own folder before 0.57.0 for
  instance, was told Move brings its documents back to its own folder and
  had them moved into the folder for every provider. The folder is now
  filled in only before a download run, Pilot, Run All or Resume, and the
  page says it comes with their next download.
- **Two changes to one config at once no longer undo each other or its
  copy in Backups.** A run filling in its documents folder in one tab and a
  save in another could each read the config before the other wrote it, so
  one change was lost, and they could take one Backups folder, so the copy
  of the config as it was could be written over, or deleted along with that
  folder when one of the two writes failed. Every write of a provider's or
  person's config in the panel now waits for the one before it, adding a
  person, an import and the settings an update adds included, and a run
  fills in a documents folder only if nobody chose one meanwhile.
- **A config in a folder whose name is not UTF-8 is refused for what it
  is.** On Linux such a name reaches PaperPull as half characters, and a
  run can neither print it under the control panel nor keep it in its
  records, where it would name a file that is not there. A run still
  stops before doing anything, and now says the name is not UTF-8 text
  rather than that it holds a line break.
- **PaperPull Server's spreadsheet and failure file Downloads say a
  refusal in the panel.** Each sent the page to the file's address, so a
  refused download, a spreadsheet swapped for a link among them, replaced
  the panel with the refusal's text and dropped a run streaming on it.
  Each is now asked for first, and a refusal is said at the top of the
  panel.
- **Verify and a dry run leave `new-this-run.txt` as the last download run
  wrote it.** Each saves nothing, yet replaced the list with an empty one,
  as Discover and Rename no longer do. Each still writes its run summary.
  The list's second line now says each file is named as the run saved it,
  so a Rename or the move to a documents folder since may have given it
  another name or folder, or its name to another file when two traded
  names, and the README says so for Rename too.
- **Wells Fargo no longer takes an account's last four digits for a tax
  form, nor files a form whose link names only its date as a statement.**
  Read with care, the last digits of a masked account number, `****1099`,
  the picker's "... 5498" or "ending in 1098", were taken for a tax form,
  and the reading the app always had agreed, so that account's statement
  was filed as a Tax Document, alone or beside another account's statement
  of the day. And a link naming only its date for a screen reader, with no
  table row, list item or printed date around it, read nothing around it,
  so a 1099 or a 5498 printed beside it was filed as an Account Statement.
  Now such digits are the account's, and such a link reads the part of the
  page that holds it and no other control, never the tabs or menus around
  it, and never as its entry. Both rules only ever leave a document for a
  person, counted in Diagnose, since the kind as the app read it with care
  before them must agree as well, and a document they leave for a person
  still keeps a twin of its day from being guessed at. A lone bullet or
  asterisk between words, a period's "ending", a name cut short with dots
  and a form's name such as 1099-B are never taken for a mask.
  Found by the review of this reading's port to SBA and American Family,
  and by two fresh reviews of this change, each shape proven in a browser
  before the change. The statement links a tester's recording shows name
  their own kind and date, which neither shape touches.
- **A Wells Fargo statement whose size reads like a form's number is
  filed as a statement.** Each statement's link names its date and the
  size of its PDF, "Statement 09/30/26 (123K, PDF)", and a statement with
  check images can pass a megabyte. A statement of 1099K, 1098K or 5498K
  was filed as a Tax Document, since both readings took the size for that
  form, and beside the day's real 1099 the two were refused as twins and
  neither was saved. One whose size held such a number, 10990K say, was
  left for a person on every run. Now no reading reads a size, a number
  with K or M in parentheses before PDF, the reading the app always had
  included, since a size says nothing of what a document is. Such a link
  reads like any other statement's, and a form's own name is read as
  before, 1099K among them. A statement an earlier version filed as a Tax
  Document downloads once more under Statements, beside the earlier copy.
  Found by a fresh review of the masked-digits fix above, on the link
  shape a tester's recording shows, and proven in a browser before the
  change.
- **SBA and American Family no longer misfile a document by the two rules
  their new reading took from its review.** That reading, ported from Wells
  Fargo, takes a masked number's last digits for the loan's or the
  policy's, and has a link that names only its date read the part of the
  page around it. Two fresh reviews of the same rules in the Wells Fargo
  app found them wrong in these ways. A lone bullet, a lone asterisk or
  "ending" was taken for a mask, so a 1098 printed as `Loan ...4321 • 1098`
  beside a link naming only its date was saved as the Loan Statement, and
  a 1099-C after "Year ending" was left for a person. Three dots, an
  ellipsis, black circles, middle dots, an en dash or a spaced dash after
  the mask, and "last four digits" were never taken for one, the last
  since only sixteen characters before the digits were read, so such a
  statement was still filed as a Tax Document. The part read around a
  link passed over tabs and links that name no document, so a lone
  statement under "Statements" and "Tax forms" tabs was left for a person
  every run. And that part was taken for the link's entry, so two
  statements of a day whose controls the reading does not count as
  documents, links the core finds by their words (#38) or input buttons,
  became one document, and the first was pressed for both. Now a mask is
  two or more marks or one directly before the digits, any dash may follow
  it, "ending" masks only after a loan, a policy, an account or a number,
  or with "in" or "with" after it, and a number with a form's letters
  after it, 1099-C or 1099-INT, is always a form, while letters running
  into the digits from the next word, as two spans touching draw
  `****1099View`, never make it one. The part read around a link holds no
  other control or field drawn on the page, so a form's hidden field or an
  empty anchor does not cut it short, and it is never the link's entry.
  Both rules only ever leave a document for a person, since the careful
  reading without them must agree as well, and a document they leave for
  a person still keeps a twin of its day from being guessed at.
  Found by two fresh reviews of the Wells Fargo port and one of this
  change, each shape proven in a browser before the change, the twins on
  American Family too. No release carried these rules as first written.
- **SBA and American Family never read a document's size as a tax form.**
  A Wells Fargo tester's recording shows each statement's link naming its
  date and the size of its PDF, "Statement 09/30/26 (123K, PDF)", and both
  apps read a document the way Wells Fargo does. Printed on SBA's page, a
  statement of 1099K or 1098K would have been filed as a Tax Document,
  beside the day's real 1098 the two would have been refused as twins,
  and one of 10990K would have been left for a person every run. American
  Family took a size printed with a space, 1099 KB, for a 1099 the same
  way, and a row printing only a date and such a size made a bare View,
  or a marked PDF link in a payment's row, a tax form's control. Now no
  reading of what a document is reads a size, a number with K or M in
  parentheses before PDF, the reading each app always had included, and
  the words on either side of it stay apart, as the size kept them. Dates
  are read as before, and a form's name printed any other way is read as
  it always was. Neither app's pages are known to print a size, so this
  keeps both in step with Wells Fargo. A new test also holds alike the
  code the two apps share for reading a document's kind, so a change to
  one copy fails until the other has it too.
  Found by the Wells Fargo fix for its own statement sizes and proven in a
  browser before the change, the words kept apart by a fresh review of
  this change.
- **Wells Fargo presses View Statements & Documents in the Accounts menu
  (#27).** On 0.57.0 a tester's runs opened the top bar's Accounts menu,
  found View Statements & Documents in it by its whole name, and still
  stopped with "the accounts menu has no statements and documents link".
  Before the press the link's words are read a second time, and that
  reading took its label or else all of its text, which on the tester's
  page holds something the name leaves out, most likely a mark hidden from
  a screen reader or a word written for one alone. Now the link is also
  read the ways its name is made, its text without the parts hidden from a
  screen reader or the parts of its own that name it, and what it shows on
  screen still has to name statements and documents, so a control showing
  View Check Copies under a name put there for a screen reader alone, in
  the usual ways such words are hidden, is still refused. Every reading,
  the label and what the link's style draws included, is checked for words
  the guard refuses, so a label naming the link on a control that says or
  draws Close an Account is no longer taken. A soft hyphen or a character
  of no width, which the name leaves out, is left out of every reading
  too. The Accounts button is pressed only while it is the only button of
  that name that shows, at every read and at the press, where before it
  was found again by its place among them (the 0.57.0 review), and the
  app's requirements ask for the Playwright 1.51 that needs. The failure
  file says how each reading of the link went,
  in yes or no and lengths, a stop at the link's press says how the link
  was reached, and when the press does not open the statements page, the
  file says whether it took the tab elsewhere or opened another tab.
- **Every invoice of an order split into several takes a new name
  together, in every receipt app.** Target and Amazon save each invoice of
  a split order as a file of its own, "(1 of 2)" and "(2 of 2)", with one
  index row for the order and the others named in its notes. Review Names
  and Rename renamed only the file the row names, so a new summary or a
  new naming pattern left the order's other invoices under the name the
  order had before. Now both rename every invoice of the order together,
  each keeping its own part and going into the same pattern folders, and
  the notes, the rows and Target's list of invoices name them as they are
  now. An invoice put aside in Manual Review, one whose name says no part,
  and one that another purchase's rows, record or notes also name keep
  their names. The next Rename gives an invoice an earlier Review Names
  left behind the name the rest of its order has, and the Move to a
  documents folder now takes Amazon's other invoices along, as it already
  took Target's.

## [0.57.1] - 2026-10-22

A run whose documents go to a documents folder says what it saved again,
and keeps its list of new files. PaperPull Server's spreadsheet Download no
longer follows a link left in the spreadsheet's place.

### Security
- **PaperPull Server's spreadsheet Download no longer follows a link left
  in the spreadsheet's place.** An export writes its spreadsheet beside the
  providers' folders in the data folder, and Download then handed over the
  file of that name, opened again by name when it was sent. The data folder
  is often a share others can write, so anyone who could write there could
  swap the spreadsheet for a link after the export, or for a second name of
  another file, and the person who pressed Download got whatever it led to
  that the server can read, its settings in /config or a signed-in
  browser's cookies among them. Download now opens the file as it is at that moment,
  only a file of its own inside the folder the export was given, and sends
  it from that same open, as the support report and set-aside downloads
  already did. Anything else is refused with a note to export again. A
  spreadsheet nobody touched downloads as before, under the same name. Show
  in folder on the desktop reads nothing from the file and is unchanged.

### Fixed
- **A run whose documents go to a documents folder says what it saved.**
  Once a download run ends, the control panel moves what it saved into
  the account's documents folder with the app's own Rename, and every
  app's Rename wrote a run summary of its own, which left
  new-this-run.txt listing nothing. The panel read that list after the
  move, so a Citi run that saved 23 requested statements said Nothing
  new, and the home page logged it as a run with nothing new (#103). It
  happened for any account with a documents folder since 0.54.0, and
  since 0.57.0 every account has one once a base folder is chosen. The
  panel now reads the run's list as the run ends, before anything else
  runs for the account, and counts from the run's own result as well. A
  Rename leaves run-summary.txt and new-this-run.txt as the last download
  run wrote them, as Discover already did, so the list names each file
  where the run saved it, before the move.

## [0.57.0] - 2026-10-22

One documents folder for every provider. Set a base folder in Settings and
each provider and person gets a folder of its own inside it, such as one
Paperless-ngx, a NAS share or a synced folder watches. The packages and the
server image take pypdf 6.21.1, and a file or folder name with a line break
can no longer change what the panel reads of a run.

### Security
- **The Windows and Mac packages and the server image take pypdf 6.21.1.**
  pypdf 6.19.0, which opens every PDF PaperPull saves, has five advisories
  fixed in 6.20.0 to 6.21.1. A PDF that ends inside its cross-reference
  table kept pypdf reading forever (GHSA-39mj-jf6j-2qj3), and a stream
  with many filters could take a great deal of memory
  (GHSA-7mh2-4gg2-979f). PaperPull reads each PDF in a process of its own
  that is stopped after two minutes or 1 GB of memory, so such a PDF was
  set aside unread and the run went on, and 6.21.1 refuses the first one
  at once. The other three are in parts of pypdf PaperPull never calls,
  editing outlines and trees (GHSA-qfv9-64jg-mh7p, GHSA-9mx8-4j7g-633p)
  and opening a PDF's JPEG images (GHSA-5hx5-vpf9-5wcv). A checkout's
  requirements ask for 6.21.1 as well, so running setup again brings it in.
- **A name with a line break can no longer add an event to what the page
  reads of a run, or pass for its result.** Linux and macOS allow a line
  break in a file or folder name. The control panel shows the command a
  run starts with, which names a second person's config,
  config.<label>.json, and the page reads a run line by line, a blank line
  ending each event. So a config named with line breaks, made by hand or
  by anyone who can write to PaperPull Server's /data folder, could end
  the line showing the command and add events of its own, telling the page
  the run had finished clean or giving it counts the run never had. A
  run's own output was open the same way, since the panel took the run's
  counts from any line shaped like its result, and a run prints file
  names, folder names and text from a provider's page. Now every line the
  panel streams is written as one line, a line break in it shown as \n,
  and each run is given a mark that only its own result line carries. What
  a run prints is still shown as it printed it, so such a name can still
  show as two lines of a run's details, and the page may take the second
  for a line of its progress. The transactions export offers a file only
  from its own marked line, and only one in the folder it was given. The
  panel no longer lists a config or a provider folder whose name holds a
  line break or another control character, and saves no documents folder
  holding one. A run stops before printing anything when its config's
  path, output_dir, profile_dir, documents_dir or account_labels holds
  one. Rename the file or folder, or change the setting, to run it again.

### Added
- **One documents folder for every provider (#102).** The Settings
  Documents folder now starts with one folder for every provider and
  person, so a single folder can be synced to Google Drive or another
  cloud. Each provider and person gets a folder of their own inside it,
  named as their PaperPull folder is, such as `Chase Statements` and
  `Costco Receipts - spouse`. A provider or person added later gets theirs
  as their first run starts, and the run says so. The first save gives a
  folder in it to everyone whose config names no documents folder, one set
  back to the provider's own folder before this version included, since
  that left no setting. From then on a folder set for one provider and
  person below it, or their provider's own folder, is kept when the folder
  for every provider changes. The page lists each of those, and **Use it
  for every provider** gives them their folder inside it too. The panel
  writes each one's folder into their config as `documents_dir`, a copy
  of the config kept first, so a run from a terminal uses it too. No two
  providers or people share one folder in it, and on PaperPull Server it
  stays inside the data folder. Records, Manual Review, logs and browser
  profiles stay in the PaperPull folder as before, nothing is moved by
  saving, and documents saved before are still found where they are until
  Move. Thanks to @appchamp.

### Fixed
- **NetBenefits still knows a combined statement saved before the pypdf
  upgrade.** On a login with several plans, a plan whose statement is the
  employer's combined one counts as covered only when its own request
  gives that very statement, told by a digest of its text. The digest
  kept the text's spacing, and pypdf 6.20 reads some statements with
  fewer line breaks, so a statement saved before would no longer match
  the same statement asked for again, and a second copy would be kept.
  The digest now leaves out every whitespace character, a digest an
  earlier version kept still counts, and a saved statement still in its
  folder is read again to compare.

## [0.56.3] - 2026-10-21

E*TRADE reads each statement's account, so a sign-in with several accounts
gets each statement under its own account, and it takes a statement listed
on a later page of its list. PaperPull Server's image takes Pillow 13.0.0,
past a heap overflow in its JPEG decoding, and brings 0.56.2's fixes to the
server. The native Windows on ARM build, which no release ever shipped, is
gone.

### Security
- **The server image takes Pillow 13.0.0.** Pillow 12.3.0, which the
  server image installed for reading PDFs, has a heap buffer overflow in
  its JPEG decoding (GHSA-8g5g-8vmr-9782) and several other advisories,
  all fixed in 13.0.0. The image's own check found it after 0.56.2 was
  tagged and stopped that image from being published, so the server stayed
  on 0.56.1. The Windows and Mac packages already carried 13.0.0.

### Fixed
- **E*TRADE reads each statement's account (#96).** The app read the
  account from a field E*TRADE leaves empty, so no statement ever had one.
  Two accounts' statements of one title and day could not be told apart
  and were refused, and neither a file name nor a naming pattern with
  `{account}` ever said whose a statement was. @appchamp found where the
  account lives on the live page and wrote the fix (#119). Each statement
  carries a key for its account, and the page loads its account list
  beside the documents, which gives each key the label the Account column
  shows. Discovery now reads that list from the page's own answer, the way
  it reads the documents, and gives each statement its account's label. A
  closed account's label, which ends in "(Closed)", still says which
  account it is. A key the list gives no label, or two labels, gives the
  statement no account, never a guessed one. A Discover that reads no
  account list, or lists with no account a statement a saved record holds
  under its account, writes a failure file and stops before it records, moves or downloads
  anything, since every statement would read as one of no account and be
  taken again. One account's two documents of one title and day, two trade
  confirmations, stay two records and go to Manual Review, since no link
  tells them apart. A record is kept under the label's last digits, which
  renaming the account on E*TRADE does not change, and the key itself is
  never kept or written anywhere. On a sign-in of one account, every record
  kept before moves to its account and nothing is downloaded again. On a
  sign-in of several, a record kept before moves to the account its saved
  PDF prints, the way 0.54.0 moves one, and a statement whose saved PDF
  does not show its account is downloaded once more under a name that says
  the account. No file is renamed or moved until you run Rename. The
  records 0.56.1 kept by their place for two statements of one title and
  day, which were refused, go once the list gives that day's statements
  their accounts.
- **E*TRADE tries every element of a period's name in its period list.**
  Only the first element of that name was tried for each kind of control,
  so a period whose first one was hidden could go unchosen, older years in
  a list that scrolls among them. Each one is tried in turn, scrolled into
  view first, and a list that had closed is opened once more (#119). A
  press that raised is the last one made, so nothing else of the same
  words is pressed after it.
- **E*TRADE takes a statement listed on a later page of its list.**
  Discovery reads every page, but the download looked for a statement's
  row only on the page shown, so one listed past the first page went to
  Manual Review. It now presses the list's own Next page button, the one
  labeled exactly "Next page" in the list's pagination, only while that
  button is on and only until the page shows a row of the statement's date
  naming its title, and the next download starts again from the first
  page.

### Changed
- **The native Windows on ARM build is gone.** It was a switch in
  `packaging/build_windows.py` that no release ever used, since the x64
  package runs on Windows on ARM under emulation. cryptography, which
  PaperPull opens encrypted PDFs with, published its last Windows on ARM
  build in 46.0.3, so that switch could only ever build a package carrying
  a cryptography and an OpenSSL with known security problems, and its lock
  kept seven of GitHub's security alerts open for a package nobody
  downloads. The switch and its lock are removed, and the Windows package,
  its installer and the Store package are unchanged.

## [0.56.2] - 2026-10-20

Wells Fargo opens Statements & Documents from the top bar's Accounts menu,
where some accounts summaries keep it. U.S. Bank never takes an account as
chosen after a choice of it did not take, and E*TRADE keeps a statement
set aside for review when it folds the records 0.56.0 made.

### Fixed
- **U.S. Bank never takes an account as chosen after a choice of it did not
  take.** When the statement list did not come back in time after an
  account was chosen, or the picker went back to the account before, the
  choice was refused, but the picker could still show that account while
  the list held the previous account's statements. The next statement of
  that account then took the account on show as chosen, and on a list whose
  headings name no account it could press the previous account's statement
  of the same date and save it as this account's. A list that came late
  could also be read as the next account's. Now a choice that does not take
  opens the statements page again before anything else is read or pressed,
  no account is chosen on a page that will not open again, the account the
  picker shows is taken as chosen only after a choice that took, and the
  picker's option is chosen by its own label, so options drawn again a
  moment before cannot put another account in its place. The
  tester's page names the account in every heading, which kept this from
  happening there.
- **E*TRADE keeps a statement set aside for review when it folds its
  records.** Folding the duplicate records 0.56.0 made, and moving a record
  kept before #96 to its account's key, kept the record that was finished,
  and otherwise the one already there. A statement in Manual Review with a
  PDF that opens counts as done to a run but not as finished, so a failed
  record beside it won, the review copy's record was dropped with its file
  left behind, and the statement was downloaded again as a new file. A
  record holding a file that is there now wins over one holding nothing,
  and a finished record still wins over both.
- **Wells Fargo opens Statements & Documents from the Accounts menu.** On
  a tester's accounts summary the link shows only inside the menu that the
  top bar's Accounts button opens, as View Statements & Documents, and the
  page builds that menu only when it is opened. So every run stopped at its
  first step, saying the page had no such link. When no such link shows and
  the page has no Menu button, the app now opens a button named exactly
  Accounts, only when it is the only one and only while it says it is
  closed. Then it presses only the control named exactly View Statements &
  Documents or Statements & Documents that the open menu shows. The same
  menu holds Close an Account, Stop Future Payments and overdraft services,
  and none of them is ever pressed. When no such link shows, the run stops
  with the menu left open and nothing more pressed, and the failure file
  and Diagnose say whether the menu was opened, how many controls the page
  showed before and after, and how many of them name statements or
  documents. Thanks to @crazyhorse90210 for the screenshots and the
  Diagnose file (#27).

## [0.56.1] - 2026-10-20

U.S. Bank walks every account in its account picker and downloads the
statements it lists, and E*TRADE no longer lists and saves the same
statements again on every run, and reads every page of its documents
list. Amazon records a canceled order as canceled in the store's own
language, Spectrum no longer stops on a statement it has just saved, and
the Mac packages try Apple's ticket server again when it drops the
connection.

### Fixed
- **Spectrum no longer stops a run on a statement it has just saved.** It
  compares its download folder before and after each press, and a file the
  browser removed or renamed while the folder was being read made the whole
  folder count as unreadable, so a press that brought exactly its statement
  stopped the run as though it had started something else. A file that goes
  as it is read is now passed over before the press and still counts as a
  change after it, so a download the press began is never missed.
- **The Mac packages try Apple's ticket server again.** Stapling the
  notarization ticket lost its connection to Apple on several release
  builds and failed the whole build, so each staple and check now tries up
  to four times before it fails.
- **Amazon records a canceled order as canceled, in the store's own
  language.** On amazon.de a German account gets its order pages in German,
  and a canceled order's printable summary says Storniert and prints no
  total. The app knew only the English words for a canceled order, so it
  took that summary for one that had not rendered, recorded the order as
  Failed and asked for it again on every run. It now reads the order's
  status in the languages of the stores it supports (English, German,
  French, Spanish, Italian, Dutch, Swedish and Polish) before it asks
  whether the summary rendered, and only from a line that is the order's
  status or the sentence under it, never from an item's title. A summary
  that shows a total above zero, a shipment delivered, on its way or still
  to be sent, or a word saying the order was canceled in part is never
  taken as canceled, so an order canceled only in part, or one with a
  product named Cancelled, has its receipt saved, which an English order
  did not always have before. An invoice Amazon issued before the
  cancellation is still saved, and a summary with no total that says
  nothing of a cancellation is still asked for again. An order an earlier
  version left Failed this way is recorded as canceled on the next run,
  and an order it already recorded as canceled keeps that record. Thanks
  to @Weyoun for the report and the diagnosis (#114).
- **U.S. Bank walks every account in its account picker, and a run presses
  only what its own list read.** The account picker on U.S. Bank's
  statements page can be a plain list to choose from, and the app took its
  whole text, the "Choose an account" prompt and every account in it, for
  one account. So it read only the account on show and never chose another
  for a download. @appchamp found the cause and fixed it, and each account
  is now read and chosen in turn (#115). On top of that, an account counts
  as chosen only once its own list has come, so a list still showing the
  account before is never read or pressed as the new one's, and the app
  waits for the list and the year picker to draw, which a Pilot had read
  before they came (#116). When the account and year pickers read nothing
  while the page shows statements to download, the run stops with a
  failure file rather than read the page's text. That reading had taken
  whole sections for statements, each dated with its first row's date
  (#117), and it now takes only a row showing one date. A Pilot or Run All
  presses only statements its own list read. A record the page's text
  made is marked No Longer Listed by the next run whose pickers read
  statements, and a list read whole through every account and year marks
  any other statement it no longer shows, so no run, Resume included,
  tries such a record again until a list shows it once more. Nothing saved
  is ever marked. A download that saves nothing now names the step that
  stopped it, finding the statement, choosing its account or its year, or
  the press itself, and its failure file counts what the search for the
  statement's row saw. Thanks to @appchamp for the fix, the runs and the
  careful answers (#106).
- **E*TRADE no longer lists and saves the same statements again on every
  run.** 0.56.0 told apart statements the list gives no account by the
  list's own ids for each, and E*TRADE changes those every time the list
  loads. So each list holding a statement, and each Discover, added it
  again, and Run All saved the copies as new files, "Statement (3)" and
  on, or set them aside in Manual Review. Such a statement is now told
  apart by its place among those of its date and title, which every load
  gives it again. The next Discover folds the extra records into one for
  each statement and downloads nothing again. The extra files are left
  where they are, for you to delete. Thanks to @appchamp for tracking it
  down (#96).
- **E*TRADE reads every page of its documents list.** Discovery read only
  the first page of each period, so on a long list the documents past the
  first page were never listed, and the run still finished clean. It now
  asks for each later page the way the page asks for the first. When a
  page cannot be read, the run says so in a failure file, keeps the list it
  found, and stops before it downloads anything, since which row is which
  document rests on the whole list (#96).

## [0.56.0] - 2026-10-18

Citi downloads the older statements you requested, and Chase Business
saves the business card's statements. E*TRADE no longer saves one
account's statement for another's, U.S. Bank finds each statement it
listed, Diagnose always writes its file, and PaperPull Server says why
Chrome cannot start on a host such as Synology. The server can keep
Chrome's whole sandbox on a kernel with seccomp but no user namespaces,
starts no Chrome on one without seccomp, has an HTTPS setup, and ends
idle sessions, and the Windows and Mac packages install only the files
they were built with.

### Added
- **Citi downloads the older statements you requested.** Statements older
  than the two years Citi lists online have to be requested on Citi by the
  account holder, and Citi then lists them as Requested Statements for a
  limited time. The app now takes every requested statement that is ready
  while Citi lists it, dated the last day of its month, and never one for
  a month already saved. One Citi no longer lists is marked No Longer
  Listed rather than failed. The app still never submits a request itself.
  Thanks to @appchamp for the request and for recording the page (#103).
- **PaperPull Server can run on a host whose kernel has seccomp but no
  user namespaces.** Chrome's usual sandbox needs user namespaces, so the
  sign-in window was refused on such a host, since PaperPull never starts
  Chrome without its sandbox. Removing the `#` from two
  `cap_add: SYS_ADMIN` lines in the compose file now has Chrome use its
  setuid sandbox instead, which builds the same sandbox without user
  namespaces, and the self-test, the container's log and the panel count
  it as a sandbox. The helper is made setuid only where the kernel has
  seccomp, so Chrome never gets half its sandbox through it, which leaves
  out Synology's 4.4 kernels, built with neither. It is made setuid only
  where root alone could have put it, which is why the browser volume now
  belongs to root in every installation. Every other installation is
  otherwise unchanged, with no capability added and no setuid helper kept
  in the browser volume. It has not yet been seen on a real NAS, see "On
  Synology" in SERVER.md.

### Fixed
- **Diagnose always writes its file, and Wells Fargo looks behind the
  page's menu for Statements & Documents.** A Run All started from Wells
  Fargo's accounts summary stopped at its first step because no
  Statements & Documents link showed there, and Diagnose run on the same
  page stopped the same way before it wrote anything, so there was no file
  to send. Diagnose now writes its survey in every app when it stops
  early, and Wells Fargo's Diagnose surveys the page the window shows and
  says it could not open the documents page. When no Statements &
  Documents link shows, Wells Fargo now opens a button named exactly Menu
  to look for one, and presses nothing else. The failure file also counts
  links drawn with no address, controls inside a shadow root and controls
  named Statements & Documents, since Wells Fargo draws its links with no
  address and the file had counted none. Thanks to @crazyhorse90210 for
  the failure files (#27).
- **Diagnose keeps its detailed file in fifteen more apps when it stops
  early.** In Alpaca, Bilt, Chase Business, First Horizon, IRS, SDG&E,
  Shelby County Trustee, Simmons Bank, Spectrum, Venmo, Best Buy,
  Coinbase, M&T Bank, Nelnet and Optum Bank, a Diagnose that stopped at a
  page it could not open, or at a press it would not make, left before it
  wrote its detailed file, so only the survey was there to send. Each now
  writes it the way Wells Fargo does. It surveys the page the window shows
  without following any link and says where and why it stopped, and the
  survey beside it says so too.
- **Every other app's Diagnose keeps its detailed file when it stops early
  too.** ADP Workforce Now, American Family, Apple Card, AT&T, E*TRADE,
  Golden 1, Meijer, Newrez, SBA, SMUD, State Farm, TreasuryDirect and
  Verizon Mobile now write it the Wells Fargo way when a stop interrupts
  their look, and say where and why it stopped. Apple Card opens no
  statements section after its documents page would not open. PG&E's
  Diagnose, which kept its file when its walk of the history stopped, now
  keeps it when the documents page itself would not open, and walks no
  history after that.
- **The transactions export no longer stops at half of an emoji.** A
  statement's text can carry half of an emoji, from a font that names its
  characters in an unusual way, and a CSV has no way to write half a
  character, so the CSV export of transactions stopped at the first one.
  Each half is now written as U+FFFD, the replacement character shown as
  a question mark in a diamond, which is how a browser shows such a half
  on a page and prints it into a PDF, and two halves side by side become
  the emoji they make. Every spreadsheet PaperPull writes does the same,
  the .xlsx exports among them, which left the half out in 0.54.0, so the
  two formats agree. Excel reads what follows the mark as text, so =1+1
  there stays text, on opening and after an edit. The apps' own order
  history, receipt index and document index take the same mark when they
  are written. Measured on real archives, 179,703 values, 2,644 file
  names and 2,368 statement descriptions, none held such a half or the
  mark, so nothing already written changes.
- **An app run no longer stops at half of an emoji in a provider's data.**
  A provider's list or a document's own text can carry half of an emoji,
  where the provider cut a name short, and the run stopped at the first
  line it printed with that name, before anything was written down. The
  progress file could not hold the half either, and a Mac refuses a file
  name holding one. Every app now reads that text with each half as the
  replacement character, the way the browser shows it, so the progress
  file, the order history and index, the file name and what the run
  prints all say the same. An order number or a file name holding one is
  found again by the next run, by the check whether a receipt is already
  written down and by Rename. A half that reaches the progress file some
  other way takes the replacement character there too, and the file is
  always written. No real archive held such a half, so nothing already
  written changes.
- **U.S. Bank finds each statement it listed (#106).** The list read a
  statement's date from its Download button's label one way, and the
  download looked for that row again with a pattern that wanted the exact
  day, so on a page whose labels name only the month, or write the day as
  15th, every statement listed was then not found and a Pilot stopped on
  the first one before pressing anything. Both now read a row the same
  way, a day written 15th is read as that day rather than the end of its
  year, and two rows that read as one date are left alone. Thanks to
  appchamp for the failure files.
- **Meijer calls a purchase no longer listed only when every look saw its
  list.** Before a purchase is set down as no longer listed, Meijer looks
  for it twice. A look whose list never showed was passed over, so the
  other look alone could set the purchase down as gone. A look that sees
  no list now counts as not finding the purchase gone, and it stays to be
  looked for again.
- **E*TRADE no longer saves one account's statement for a statement the
  list gives no account (#96).** On a sign-in with several accounts, the
  list can leave a statement's account blank. Every check that compares
  accounts let such a statement through, so of several accounts'
  statements of one title and day, the one row the page showed was saved
  for it, whichever account it belonged to, and Discover kept only one of
  those statements and left the rest unlisted. Each one is listed now, and
  one with no account on a day the list gives its title more than once
  goes to Manual Review with nothing pressed. A statement is also left
  alone when the page shows fewer rows of its title and day than the list
  gave, since the one row shown may be another account's, and that goes
  for statements with an account too. A new download that is byte for
  byte the same file as another document of that day goes to Manual
  Review rather than being kept, and under a naming pattern that leaves
  the account out, a second account's file now ends in that account's
  last digits rather than " (2)". A sign-in of one account keeps every
  record and file name it had, and no saved file is renamed. No E*TRADE
  PDF has been seen yet. Thanks to @appchamp for the report.
- **Chase Business saves the business card's statements.** A business
  card's statement row has no "Opens menu to save document" menu, only an
  "opens document" link and a "Saves document" link, so every card
  statement went to Manual Review with "Could not capture the document
  PDF". The app now presses the row's own "Saves document" once and keeps
  the one PDF Chase sends, when it prints the card's last four and the
  row's date as its statement date. "opens document" is never pressed, checking
  statements are saved through their menu as before, and a row that shows
  both or neither is left for review.
- **PaperPull Server says why Chrome cannot start on a host without user
  namespaces (#110).** Chrome builds its sandbox from user namespaces and
  seccomp, and Synology DSM's kernel has neither. PaperPull never starts
  Chrome without its sandbox, so Chrome stopped the moment it started and
  the Browser Screen stayed black with nothing saying why. A sign-in waited
  twenty seconds, said to close every Chrome window and to install Chrome
  or Edge, and the self-test spoke only of a debugging port. The server
  now asks the kernel at its start and says in one line of the
  container's log whether this host can give Chrome its sandbox, and why
  not. The panel shows the reason at the top of every page, the
  self-test's sandbox line names it, and a sign-in says it at once. A
  container whose security profile was left out is told to check it. Of
  what Chrome writes, only the first 64 kB is kept for that, however many
  days its sign-in window stays open. The sandbox is never turned off.
  SERVER.md has a new On Synology section, with a Debian 12 virtual
  machine or the desktop app as the ways that work. Thanks to
  @akcamperdude for the report.
- **Meijer no longer waits for a receipt's download where it hears it.**
  Everything listening for a download on the page hears it in turn, so
  while Meijer waited there for the download to finish, up to twenty
  seconds, the check of what the press brought heard nothing. Meijer now
  only notes the download as it begins and waits for it afterward, still
  canceling one that has not finished in twenty seconds, so everything
  listening hears the download at once. A test now checks that no app
  waits for a download where it hears one.

### Security
- **A Diagnose file no longer names your cards or accounts.** The detailed
  file Diagnose writes kept a word whenever it was on PaperPull's fixed
  list, and a card's product name is made of ordinary words, so Citi's
  file kept "Custom Cash" in its sample lines with only the digits
  shaped. Now a title, a row, a control, a heading, an option or an error
  read off the page keeps only the words that say what kind of document
  it is, when, and what part of the page, and every other word is written
  as its shape even when it is on the list. Web addresses and the field
  names of the site's answers still keep the whole list. The same rule
  covers what Diagnose prints in every app, the file a failed download
  writes, and the controls clicked and options picked during Record.
  Thanks to appchamp for spotting it (#103).
- **The Windows package carries Python 3.12.14, with every 3.12 security
  fix since 3.12.10.** It was built on python.org's embeddable Python
  3.12.10, the last 3.12 for which python.org publishes Windows files, so
  no later security fix could reach it. It now carries the same Python as
  the Mac package, from python-build-standalone, checked against the
  SHA-256 its publisher lists before anything is built from it. The
  packaged Python still ignores `PYTHONPATH`, `PYTHONHOME` and the folder
  it is started in, as before. Each build and each package workflow asks
  the packaged Python which version it is and stops on any other answer.
  python-build-standalone does not sign its files the way the Python
  Software Foundation signed the embeddable ones, so the release build now
  signs the packaged Python's own programs and libraries (`python.exe`,
  `pythonw.exe`, `python312.dll`, `python3.dll` and `python\DLLs`) with the
  same certificate as `PaperPull.exe` and the installer, only while each is
  still the file the checked archive held, and the build stops if any of
  them is left unsigned.
- **The Windows and Mac packages install only the package files they were
  built with.** They installed whatever release of each package was newest
  on the day of the build, anything above a lower bound, and nothing
  checked a file. Each now installs from a lock for its system and
  architecture that names every package at one version with the hashes of
  its built files, and pip refuses a file whose hash is not there. The
  locks are written by `packaging/lock.py` from the pins in
  `packaging/requirements.in`, the versions the server image carries and
  the test suites run on, so the next packages carry Playwright 1.63.0,
  pypdf 6.19.0, FastAPI 0.141.1 and Uvicorn 0.52.3 where 0.55.0 had taken
  newer ones. The Tests workflow installs the Windows lock too, so the
  suites run on what the package ships. A Mac lock takes only packages
  that run on macOS 11, the oldest the bundle opens on, and the Intel Mac
  package carries cryptography 48.0.1, the last release with a built
  package for Intel Macs. The Windows build no longer runs a
  `get-pip.py` fetched unchecked, it uses the pip inside the checked Python
  download, and PaperPull's own core is built with the setuptools from the
  lock.
- **Every action the workflows run is named by its commit.** Most were
  named by a tag, which whoever holds the action can move to other code,
  the steps that sign the Windows package among them. Each is now named by
  its full commit with its version beside it, and Dependabot proposes
  their updates each week.
- **A release is made only from a commit whose tests passed.**
  `tools/release.sh` waited for the two package runs alone, found by the
  tag's name, so a commit whose Tests run was red could be published once
  its packages built, and a tag pushed again from another commit could
  hand over an earlier build's files. It now waits for a Tests run of the
  tag's own commit and stops unless one passes, takes only package runs
  built from the tag at that commit, reads each run's commit again before
  downloading its files, and stops when GitHub's tag names another commit
  than the checkout's.
- **PaperPull Server has an HTTPS setup, and the guide recommends it.**
  `server/compose.https.yaml` puts Caddy in front of the panel. Caddy
  answers by HTTPS on port 8765, with a certificate from a certificate
  authority of its own, carries the sign-in window as wss over the same
  connection, and is the only part on your network, since the panel is
  published on no port. The sign-in cookie is then the `__Host-` one that
  travels over HTTPS only, and wrong passwords count against the browser
  behind Caddy, never against Caddy itself. It is the same project with
  the same volumes as `compose.yaml`, so moving to it keeps the password
  and every sign-in, and `compose.yaml` goes on serving plain HTTP for an
  installation that has not moved. SERVER.md walks through trusting
  Caddy's authority on each device, and the release's server zip carries
  both files.
- **PaperPull Server ends a session nobody uses for eight hours.** A
  session lasted 14 days whether anyone used it or not, so a browser left
  signed in stayed signed in for two weeks. Only what the panel's own page
  asks for keeps a session going, never what a page of another program on
  the same server asks for with the same cookie. 14 days is still the most
  a session lasts.
- **The sign-in window asks for the password again after 15 minutes
  without use.** It is live control of every provider signed in there,
  and any session could open it. It now opens, and stays open, only
  within 15 minutes of someone being seen at it, the password typed, the
  window opened from the panel, or a key pressed or the mouse moved on it,
  whatever the panel does meanwhile, Run All included, and noVNC
  connecting again by itself starts no time of its own. After that it
  closes and says why. Signing out, a new password and the reset tool
  still close an open one within seconds. An open panel that was signed
  out shows the sign-in page on its next request.
- **Every answer of the panel says what it is, and that it is not to be
  kept.** On the desktop and the server, each answer carries
  `X-Content-Type-Options: nosniff`, and each but the icon, the typefaces
  and noVNC's files carries `Cache-Control: no-store`, a run's stream
  among them, which said no-cache. The panel's page carries a script
  policy that lets only its own script run, named by its hash. A census of
  every route checks every answer, refusals included. noVNC's own files
  are checked again on each visit, so a newer image never shows a page
  made of two noVNCs.
- **The security pages say what to do if something may have been
  exposed.** SECURITY.md and SECURITY-SERVER.md say how to end
  PaperPull's own sessions and the providers' sign-ins, how a release with
  a security fix is announced, and how to report a problem.
- **A document is taken in only up to a limit, whichever way it comes.**
  A document larger than 100 MB, twenty five times the largest of 2,644
  real ones, is refused, whether it is fetched, read inside the page,
  downloaded, printed or handed over in base64. It is refused before it is
  read wherever its length is declared, and one read inside the page or
  printed is stopped as soon as it passes the limit. A download is
  measured before it is copied, and one caught by the core's delivery is
  canceled when it takes longer than five minutes or grows past the
  limit in the download folder. A ZIP is opened only when it lists at most
  1,000 files, is stored or deflated, and its PDF unpacks to no more than
  100 times its packed size, and anything else is kept whole in Manual
  Review the way an archive that cannot be told apart already was. PDFs
  are read in a process of their own that is stopped after two minutes or
  1 GB of memory, so a PDF built to stall pypdf or fill the memory is set
  aside as one that does not validate, says why, and is not read again in
  the same run. A refusal never deletes or writes over a document already
  in the archive. The limits are in one place, paperpull_core/intake.py,
  and every refusal names the one it met and says it is raised there.
- **A download an app waits for itself is canceled after five minutes as
  well.** Only a download caught by the core's delivery was given a time.
  An app that waited for its own, Ally, Chase, U.S. Bank, PG&E, AAFMAA,
  Target, Wealthfront and about twenty more, waited for as long as the
  provider kept sending, since saving a download, asking why it failed and
  deleting it each wait for it to finish. Each now waits five minutes at
  most, and a download that has not finished by then is canceled and
  refused, saying so and naming DOWNLOAD_SECONDS. A download the browser
  writes into a download folder is canceled as soon as it grows past
  100 MB there, as delivery's was. A tab that started a download and
  closed does not end the wait, and the wait no longer holds up anything
  else listening on the page, the check of what a press brought among
  them.
- **The transactions export reads statements within the limits.** It read
  every PDF in the archive with pdfplumber in its own process, with
  nothing to stop a PDF made to keep it busy or fill the memory. Measured,
  a PDF of 70 KB kept pdfplumber reading for almost two minutes before it
  passed 700 MB, and one of 139 KB was still reading after five. Each
  statement is now read in PaperPull's PDF reader process, held to two
  minutes and 1 GB like every other PDF. A statement refused for a limit
  says so in its row of the Statements sheet, naming the limit, and the
  next export reads it again.
- **A document that comes as text or JSON is taken in only up to the
  limit.** Affirm's loan agreements, Apple's receipts, Anthem's letters
  and NetBenefits' statements arrive as HTML or JSON that the app prints,
  and they were read whole. They are now read inside the page a piece at a
  time and stop at 100 MB like any other document. The lists Amazon,
  Coinbase, Paylocity, Stripe and UKG ask for through the session are read
  through the same limit, and refused unread when their length says they
  are over it. Every other place an answer is read whole as text or JSON
  holds a list, or a PDF in base64 inside a page's own answer, which
  Chromium keeps only up to about 10 MB and whose decoding was already held
  to the limit. Each is named in a test with what bounds it, so a new one
  is looked at before it ships.
- **Best Buy and M&T press their year controls only when the control reads
  as one, and M&T never calls a list whole with a year left closed.** Best
  Buy's year menu and the year in it were pressed without a guard of their
  own, and M&T pressed a year heading whatever else it said. Best Buy now
  presses the menu only when it reads Past 3 Years or a year, and a year
  only when it is exactly the year wanted among those the opened menu
  showed, through the core's press checks, and a menu that reads otherwise
  stops the run saying so. M&T presses a heading only when it reads as a
  year heading, and when a year stays closed or opens and lists nothing,
  the run stops rather than marking the list whole with that year missing.
  A new test fails when an app defines a guard its run never asks, and the
  app pages and SECURITY.md no longer say that ADP, Best Buy, eBay, Meijer,
  PayPal or Discover clicks nothing, or that a Diagnose clicks only a
  documents link, where they press more.
- **PaperPull Server never starts Chrome on a host without seccomp-bpf.**
  Chrome's sandbox has two halves, its namespaces and a seccomp-bpf filter
  on its system calls. On a kernel with user namespaces and no seccomp,
  with the container's security profile removed by hand, Chrome started
  with only the namespace half, and the server said so and went on. Now no
  Chrome starts on such a host, not the sign-in window, not an app's own
  browser, not the receipt renderer and not the self-test's. The panel
  stays up and says why at the top of every page, a sign-in says Chrome
  was not started and why, and the self-test's sandbox line names it.
  SERVER.md says so under On Synology and Chrome does not start.

## [0.55.0] - 2026-10-17

Invest529 downloads your 529 college-savings statements and 1099-Q tax
forms. Bilt asks you to sign in again when it has signed you out, and Best
Buy signs in on PaperPull Server once the server's graphics are passed to
its container.

### Added
- **Invest529 (Virginia529 / Commonwealth Savers) downloads your 529
  college-savings documents.** Official quarterly statements for every
  beneficiary and 1099-Q tax forms, read through the account's own API
  from inside the signed-in page, nothing clicked. It is read only and
  never contributes, withdraws, changes the portfolio or a beneficiary,
  or changes a setting.

### Fixed
- **Bilt asks you to sign in again when it has signed you out.** A
  signed-out visit to the Bilt wallet stays at the wallet's address and
  draws the sign-in there, with no password field, so the run stopped
  with "the wallet does not show one Bilt Card" instead. The wallet's own
  sign-in words and its "Sign up / Log in" button are now read as signed
  out, so the run saves, stops and asks you to sign in again and Resume. A
  wallet that shows neither still stops the list as before.
- **Best Buy signs in on PaperPull Server.** The server's sign-in window
  draws on a virtual screen with no graphics of its own, so Chrome drew
  every page in software and turned WebGL off, and Best Buy took it for an
  automated browser, refusing a correct password and every code or dropping
  the connection with `ERR_HTTP2_PROTOCOL_ERROR`. The desktop app was never
  affected. The image now carries Mesa's graphics drivers, and with the
  machine's Intel or AMD graphics passed to the container the sign-in
  window draws on them, which Best Buy accepts. `compose.yaml` has the two
  lines to turn on, SERVER.md a Graphics section, and a sign-in, the
  self-test and every failure and Diagnose file say when the window has no
  graphics. Measured on a UGREEN NAS with Intel graphics.

## [0.54.0] - 2026-10-16

Simmons Bank loan documents and Coinbase One Card statements arrive, a
file naming pattern can put files in folders, and each person can have
the documents sent to a folder of their own. Wells Fargo reads a checking
account and every account in its picker, and no longer signs you out,
American Express reads its pages in other languages, E*TRADE gives
statements saved before 0.53.0 their account, and the security review's
fixes harden PaperPull Server, the browsers PaperPull starts and every
spreadsheet it writes.

### Added
- **Simmons Bank loan documents.** A new app saves the statements, notices
  and tax forms of a Simmons Bank loan from the bank's online banking
  (Banno, by Jack Henry) at `login.simmonsbank.com/documents`. The list is
  the page's own answer, read whole. It has to be one answer of one account,
  asked from the bank's own first day of documents, and the rows drawn have
  to name exactly its titles and types, or the list stops. Only a document
  row's own button is pressed, never Accept, Enroll, OK, Notify, the filter
  menu, the navigation links or Sign out, and the PDF is kept only when the
  press made the page ask that one document's PDF and brought one browser
  download named with the document's own file name. With no download, that
  exact address is asked once more with no redirect followed. A PDF whose
  text does not name its document goes to Manual Review. Files are named
  `<date> Simmons Bank Loan Statement.pdf`, `<date> Simmons Bank Notice -
  <title>.pdf` and `<date> Simmons Bank Tax Reporting <year>.pdf`. The user
  id, document ids, account number and last four, your name and email stay
  out of every log, record and diagnostic file. A paid-off loan's documents
  stay online only until a date the bank names, and Discover prints it.
  Built from a live survey of one paid-off mortgage and run live on it the
  same day, all 27 documents saved. A PDF names its document by its date,
  its title's month, or a date printed within a few days of the list's date
  in that month, since the bank's PDFs date themselves a day or three after
  the list does.
- **Coinbase One Card statements.** The Coinbase app now also saves your
  Coinbase One Card statements, as `<closing date> Coinbase One Card
  Statement.pdf` in the Statements folder. It opens the Statements page's
  Credit Card tab, reads the list of statements the page itself asks
  Coinbase for, and needs the rows the page shows to match that list
  exactly. For each statement it presses that row's own PDF button once,
  takes the address the page was handed for that statement only when it is
  on Coinbase's card statement host and carries that statement's closing
  date, and keeps the file only when it is a PDF that says Coinbase One
  Card and prints that closing date. A popup, a download, the tab going
  anywhere else, or an answer naming another statement or another date
  stops the run. The statement's id, the card account's id, the signed
  address and the amounts are never logged or kept. A card list that
  cannot be read whole, or that names more than one card account, leaves
  only the card statements, for the next run. Your monthly account
  statements and tax documents are still taken exactly as before, and the
  run then ends as one that did not finish. Run live on one account on
  2026-10-15, where it saved all 13 card statements beside the account
  statements and tax documents.
- **Folders in the file naming pattern (#101).** A `/` in a File names
  pattern now puts files in folders, inside the folder each kind of
  document already goes to, so `{provider}/{year}/{date:yyyy-mm-dd}
  {summary}` files a statement as `Statements/Chase/2026/2026-03-09
  Monthly Statement.pdf`. Only a `/` written in the pattern makes a folder,
  never one inside an account or a summary, and each folder is made safe
  the way a file name is. A folder whose part is empty is left out, so
  `{provider}/[{account}/]{date} {summary}` files a document with no
  account one folder up. A pattern goes at most three folders deep and
  every folder has to name a part, and the settings page says why when a
  pattern starts or ends with `/`, has a folder of plain text or goes
  deeper. The preview shows the folders. Manual Review stays one folder,
  and a folder that would leave no room for a name under the path limit,
  or would lead outside its folder through a link, leaves the file where
  it always went. Rename existing files moves files into the folders and
  back out again when the pattern changes, with the index and the run
  history following each file, so nothing downloads again. It removes a
  folder it leaves empty, never a folder that still holds anything, and
  puts every file back if it cannot write the index. Review names files
  each receipt the same way. Before, a `/` was dropped from the name
  without a word, so `{provider}/{date}` ran the two together. A pattern
  with no `/` names files exactly as before.
- **A documents folder for each person (#102).** Settings has a Documents
  folder for each provider and person, written into that person's config
  as `documents_dir`, a copy of the config kept first, so a folder
  Paperless-ngx watches, a synced folder or a NAS share can get each
  person's documents. A download is still saved and checked in the
  provider's own folder, and one that fails its check is put aside in
  Manual Review there. When a run from the panel ends, what it saved and
  checked moves into the documents folder, into Statements, Tax Documents,
  Receipts and the other folders of each kind, with any folders a naming
  pattern adds, copied across when the folder is on another drive. The
  records, Manual Review, Logs, Diagnostics and Backups never move, so the
  documents folder only ever gets documents that passed their checks.
  Saving moves nothing already there, and documents saved before are still
  found where they are by Verify, Rename, Review names and the check that
  never downloads a document twice. The page says how many are still in
  the provider's folder and offers Preview move and Move, which moves each
  one under the name it has, with its records following it, and puts every
  file back if a record cannot be written. After the folder changes or is
  cleared, the documents moved before are still found, and the same Move
  takes them to where it points now. A browser profile, a folder around
  one, a folder holding a provider's own folder and a folder inside or
  around a person's own folder are refused, and on PaperPull Server so is
  a folder outside the data folder, a link out of it included, both in the
  panel and when a run starts. A second person added later starts with
  documents in their own folder. With no documents folder set, every file
  goes where it always did.

### Fixed
- **A U.S. Bank failure file says which part of the statement list was
  missing (#106).** A Pilot gave up on its first statement before pressing
  anything, and the file it wrote counted only general selectors, which all
  matched. It now also counts the parts the download finds a statement's row
  by, the statement list, its section and heading, the rows and their
  Download buttons, the account picker and the year filter. Thanks to
  appchamp for the report.
- **Wells Fargo no longer signs you out looking for your statements (#27).**
  When the page it was on showed no statement, the app typed the
  statements address into the signed-in window, and Wells Fargo answered
  by ending the session. It now reaches Statements & Documents only by the
  page's own link, and a window that is not on your signed-in accounts
  stops the run and asks you to open the page yourself. On the page it
  opens the Statements and Disclosures section, where a checking account's
  statements are, and goes through every account in the account picker,
  so each account's statements are listed and the file names say which
  account when there is more than one. With one account the names and
  records stay as they were. With more than one, a statement an earlier
  version saved with no account downloads once more, under its account's
  name, and the earlier copy stays where it is. The sign-in window now
  opens on
  www.wellsfargo.com, whose own sign-on form worked on PaperPull Server
  where the statements address came up blank. Thanks to crazyhorse90210
  for the surveys and the recording.
- **SDG&E lists your bills with no My Energy Center tab open, and dates
  each bill by its Statement Date alone.** With no tab of yours on My
  Energy Center, Discover, Pilot and Run All stopped at once, saying the
  browser tab had left My Energy Center, since the new tab the app opens
  for itself was checked before Billing History was opened in it. Billing
  History now opens in that tab first, and a tab of another site is still
  never read or loaded. A bill's date was the first date in its row, so a
  blank Statement Date would have dated the bill by the Due Date beside it.
  The date is now read only from the column headed Statement Date, and a
  blank one stops the list rather than taking another column's date. No
  such row has been seen on the real page. Diagnose now writes the bill
  table's header, so a list that stops for want of that column can be
  repaired.
- **American Express finds the statements on pages that spell their test ids
  data-test-id (#107).** A German account's PDF statements page writes each
  Download button's test id as data-test-id, and the app read data-testid
  alone, so Discover reported no statements on a page listing all of them.
  Every test id is now read under both names, the dialog's Download among
  them. Where a page's links and headings are in another language, the
  links are found by where they point and the older statements' section by
  the part it opens, so a run that starts on the dashboard reaches the PDF
  statements and the older ones are listed and saved. A link found by where
  it points is taken only when it shows and leads to the activity page or
  the PDF statements, and where such links name two cards, nothing is
  pressed and the run says to open the card's statements. Each link on the
  way is pressed once, and one whose page does not come stops the run
  rather than being pressed again. An English page is reached the way it
  always was, its Older Statements heading included. Thanks to Weyoun for
  finding it all and the fix.
- **E*TRADE gives a statement saved before 0.53.0 its account when the
  file itself says which (#96).** On a sign-in with more than one account,
  0.53.0 left every statement an earlier version saved where it was, since
  the list alone cannot say which account it belonged to, and so each
  account's statements downloaded once more, named with the account,
  beside the old copies. Discover now reads each of those saved PDFs and
  gives its record an account only when the file prints that account's
  last digits as an account number, as in XXXX-1234, 6789-1234, ...1234 or
  "Account ending in 1234", no other listed account's digits appear
  anywhere in it, and it prints no other account number at all, so a
  closed account's statement that names an open one in a transfer is never
  taken for the open one's. That statement is not downloaded again, and
  its file keeps its name and folder until you run Rename, which now names
  it with its account like the statements downloaded since, under the
  default pattern or one with `{account}`. A statement whose file is gone,
  does not open, or shows no account, more than one account, or digits two
  of your accounts share stays as it was, and so does one whose account
  already has that statement saved or kept for review. Its account's copy
  then downloads once more as in 0.53.0, if it was not saved already. A
  year, an amount, a phone number or a tax id number is never taken for an
  account. The log says how many moved and why the rest stayed, never an
  account or a word of a file. No E*TRADE PDF has been seen yet, so how one
  prints its account number is still a guess. Thanks to @appchamp for the
  report.
- **A spreadsheet export no longer stops at a character an xlsx cannot
  hold.** An item name, a merchant name or a document title can carry a
  NUL or another control character from a provider's page, and the
  library that writes the workbook refuses the 29 control characters an
  xlsx has no place for, so one such character stopped the whole .xlsx
  export of purchases or transactions, in the control panel and in a
  terminal. U+FFFE, U+FFFF and half of a surrogate pair it wrote anyway,
  and Excel then would not open the workbook. Both workbooks now leave
  those characters out of the cell and keep the text around them, the way
  Excel itself drops a NUL from a CSV it opens. None of them prints, so no
  mark is put in their place, except that the six which stand between
  words, such as the vertical tab Word uses for a line break, become a
  space. One in front of text like a formula still hides nothing, and the
  cell keeps its quote prefix. The CSVs keep every character as before.
  Measured on real archives, 180,418 values and 2,368 statement
  descriptions, none held such a character.

### Security
- **PaperPull Server's sign-in cookie stays off plain HTTP behind an HTTPS
  proxy.** The cookie that keeps you signed in was never marked to travel
  over HTTPS alone, so with the server behind a reverse proxy that adds
  HTTPS, a plain HTTP visit to the proxy's name, one typed without https
  before the proxy sent the browser on, carried it in the clear. When the
  browser reached the server over HTTPS, which a proxy says in
  `X-Forwarded-Proto` or `Forwarded`, the server now gives it a cookie of
  its own name marked that way. That name, `__Host-paperpull_session`,
  has the browser keep it only over HTTPS and only for the very name that
  set it, so no other name under the same domain can set or replace it.
  Reached on the home network by plain
  HTTP, nothing changes, since a browser keeps no such cookie sent that
  way. The two names keep a plain HTTP sign-in at the proxy's name
  working after an HTTPS one, since a browser lets no plain HTTP page
  replace a Secure cookie of the same name.
- **The server image installs only the package files it was built and
  tested with.** `server/requirements.txt` named the packages the server
  runs, each at one version, but not the packages those bring in, which
  came at whatever version was newest on the day an image was built, and
  no file was checked. It now names every package, at one version, with
  the hashes of its built files, resolved by `server/lock.py` in the
  image's own Python, and the image is built with pip checking every file
  against its hash and taking only built packages. The direct pins a person
  raises are in `server/requirements.in`, and a test fails when one is
  raised without the lock written again. PaperPull's own core is built
  with the setuptools from the lock rather than one fetched unchecked.
- **The server image starts from a pinned base, lists its parts and is
  checked for known vulnerabilities.** The image was built from whatever
  `python:3.12-slim-bookworm` pointed at on the day, and nothing listed or
  checked what ended up inside it. The Dockerfile now names that base by
  its digest. Dependabot proposes the tag's newer digest each week, and
  `python server/lock.py --base` writes it by hand. Every build lists
  every package in the image as an SPDX software bill of materials and
  checks the list with Grype, and a critical vulnerability that has a fix
  stops the build before a release can publish it. The check also runs on
  its own each Monday and says when the base has a newer digest. A
  released image now
  carries that list and a record of the run that built it, both signed,
  and `gh attestation verify` checks them. `compose.yaml` names the image
  by version rather than `latest`, so a server moves to a new release only
  when you write its version there. A server set up with `latest` keeps
  working as before, since every release still publishes it.
- **The server image carries a pip with no known advisories.** The base
  image ships pip 25.0.1, which has six medium or low advisories fixed in
  later releases. The lock now names pip 26.2.1 with its hash, and building
  the image replaces the base's pip with it.
- **A shared data folder can no longer move a sign-in, the browser a run
  drives or where it saves.** On PaperPull Server each provider's
  `config.json` sits in the data folder, often a share other people can
  write to, and a run took three of its settings as written. Someone with
  the share could point `profile_dir` into the share, where others could
  read a signed-in profile's cookies, aim `cdp_url` at a browser on
  another machine, or send `output_dir` outside the data folder, through a
  link too. On the server a run now always signs in with the account's
  profile in the `profiles` volume, whatever the file says, and stops
  before it connects to or saves anything when `cdp_url` names anything
  but `127.0.0.1` or `localhost` or `output_dir` leads outside the data
  folder, judged where its links lead as the run starts, saying which
  setting and why. A server config that names no `output_dir` stops too,
  where before it saved into the container's home folder, which is lost
  when the container is made again. The panel keeps no run log, reads no
  records and moves no history outside the data folder either, and its
  run log replaces a link left at its name rather than follow it. The
  desktop app reads all three as before.
- **A shared data folder can no longer send UKG's signed-in browser to
  another site.** On PaperPull Server UKG's `base_url`, the employer's UKG
  site that its sign-in opens and every run reaches, was read from the
  shared `config.json` as written, and UKG's check of each page it
  requests allows whatever site that names. Someone with the share could
  have pointed it at a page of their own, which the Browser Screen would
  then show in place of UKG's. On the server a run and a sign-in now stop
  before opening any page unless `base_url` is an https address on
  `ultipro.com` or `saashr.com` with nothing after the name, and the
  refusal does not repeat the address, which can name an employer. A
  provider names such a setting and its domains in its AppSpec, and a test
  fails when any app's setting holds an address that nothing checks on the
  server. Amazon's `marketplace` was already held to Amazon's own stores.
  The desktop app reads `base_url` as before.
- **A link left in the shared data folder can no longer carry a write
  outside it.** Some shares let the people who use them leave a link, a
  file or folder name that leads somewhere else, and PaperPull Server's
  container user also owns the server's password file and every signed-in
  browser profile. A folder such as Logs, Diagnostics or Backups left as a
  link, or a link left at the name of a file a run or the panel writes,
  had that write land wherever the link led, and a file read through one
  could have been copied into the share. On the server a run now stops
  before it writes anything when a folder it writes into holds a link that
  leads outside the data folder, looking through a folder that is a link
  elsewhere in the data folder too and passing over a virtual environment
  or a browser profile, which no run writes into. It checks each folder
  again as it makes it, and never reads or writes its records, index,
  staged downloads, review list or backups through a link left at their
  names. The browser's downloads are never pointed at a folder that leads
  out. The panel never writes a config, a code file, the Stop button's file
  or a history through a link, never reads a file through one to copy what
  it read into the share, holds Removed inside the data folder and no
  longer copies a core into an install's venv, which the server never runs.
  The browser's own saves and each app's log are checked only where a run
  starts. The desktop app reads and writes as before.
- **PaperPull Server's password hash is stronger, and checking it no
  longer holds up the panel.** The password was hashed with scrypt at
  n=2^14, r=8, p=1, below every profile OWASP recommends, and the hash ran
  inside the panel's one event loop, so nothing else was answered while a
  sign-in was checked. It is now hashed at OWASP's n=2^14, r=8, p=5, the
  same 16 MiB at five times the work, on threads of its own, two at a
  time at most, and a server busy with many waiting asks the next sign-in
  to try again. A password kept at the old cost is hashed again at the new
  one the next time you sign in, and nobody is signed out. Each try is
  still counted before its password is checked, so many tries sent at
  once still meet the wait after five wrong ones.
- **PaperPull Server reads at most 8 KiB of a sign-in.** The sign-in and
  setup pages read a form's whole body before keeping its first 8 KiB, so
  a request could make the panel hold as much as it was sent. A form that
  says it is longer is refused at once, and one sent in pieces is refused
  as soon as it passes 8 KiB, without waiting for the rest.
- **Every browser PaperPull starts itself now runs inside its sandbox.**
  Playwright starts Chromium with `--no-sandbox` unless it is told
  otherwise, and two browsers were started that way, the one an app opens
  when its settings name no `cdp_url` and the headless one Target falls
  back to when a receipt will not print. A page in them had only the
  renderer between it and the computer. Both now start through the core,
  which always asks for the sandbox, refuses a setting that would turn it
  off, and takes no switch it has not been told keeps the sandbox whole. A
  browser whose sandbox cannot start, as for the root
  user, in a container that does not allow it, or for the downloaded
  Chromium on Ubuntu 23.10 and later, is not started at all, and the run
  says why. An earlier note here said PaperPull never starts a browser
  without its sandbox, which held only for the sign-in window. That window
  is started directly, not through Playwright, with no such switch, and is
  unchanged, and a test now holds it to that. A census test fails any other Playwright
  launch in the apps, the core, the panel, the server or the tools.
- **The headless receipt renderer keeps to the provider's hosts.** When
  Target's ordinary print fails, the receipt's address is printed again in
  a headless browser. Only that first address was checked, so a redirect
  from it was followed to any host, with every cookie of the browser, and
  what arrived was printed as the receipt. Now each request that browser
  holds before sending, each redirect on the way included, goes out only
  when the app's own host check accepts it, apart from the scripts, styles,
  fonts and pictures of Target's two static hosts. What a page can send
  without such a request, a socket, a worker's socket or a prefetch, finds
  no address for any host but Target's, since the browser is given no
  other. The page is checked again before and after it prints, nothing is
  saved when it left Target, and the browser is given only the cookies of
  Target's own hosts. Behind a proxy set for the whole computer the
  fallback does not run, and the receipt's note says so.
- **Text from a receipt or a statement no longer becomes a formula in the
  spreadsheets.** The purchases and transactions spreadsheets write out
  words other people chose, an item's name from a marketplace seller and a
  merchant's name from a card statement. A spreadsheet takes a cell that
  starts with = as a formula, and Excel takes one starting with +, - or @
  the same way, so an item named like a formula became a working one in
  the workbook and in the CSV, where a formula can reach an address and
  take the cells it names along. Every text cell in both workbooks, on
  every sheet, is now written as text, and one that starts like a formula
  also carries Excel's quote prefix, so editing it keeps it text too. In
  both CSVs such a value gets a single quote in front, and so does a piece
  of a value after a semicolon or a line break, where Excel set to split a
  CSV at semicolons starts a new cell. A full-width sign counts as the sign
  it stands for. Amounts, quantities and counts are still numbers, a
  refund's negative amount among them, and a plain negative number written
  as text, such as -12.34, is left as it is, since a spreadsheet reads it
  as that number and nothing more. A receipt or statement file whose name
  started with = also left a workbook Excel found a problem in and would
  not open as it was, and it now opens. The rule is in one place,
  `paperpull_core.sheets`, which both tools take from the core beside
  them, PaperPull Server's copies included.
- **Citi refuses any control that asks it for a statement.** Its guard
  refused only Request Older or Archived Statements, so other wordings such
  as Request a Statement passed. Asking Citi for a statement is an action
  on the account, so a control that requests one is refused in any wording,
  while Requested, a statement already there to download, is still allowed.
  Citi presses no such control today, so a run does nothing new (#103).
- **The apps' own CSV files keep text that looks like a formula as text
  too.** Every app writes its order history, receipt index and document
  index beside the PDFs for a person to open in Excel, and they hold the
  same words other people chose, an item's name from a seller, a store's
  name, a document's title and the file names made from them. A value that
  started with =, +, - or @ was a working formula when the file was opened.
  Such a value is now written with a single quote in front, and so is a
  piece of one after a semicolon or a line break, by the rule the
  spreadsheets follow. That rule also sees through a NUL character in
  front, which Excel drops as it opens a CSV, and through a double quote
  at the start of a piece, which Excel's import split at semicolons took
  for an empty quoted part with a working formula after it, in the
  spreadsheets' CSVs too. Every reader takes that quote off again, the app
  itself, Rename, Verify and both spreadsheet tools, so a file name, an
  order number and a path still match what is on disk. A name that really
  starts with a quote keeps it, written with one more in front. A refund's
  amount such as -$12.34 is left as it is, here and in the spreadsheets,
  since Excel reads it as a number and nothing more, while -$A$1 and
  -kr12.34 are quoted. After a semicolon it is quoted too, since a
  spreadsheet splitting at semicolons with a decimal comma would run it on
  into the next value. A file an earlier version wrote reads as it did,
  apart from a value that started with a quote and then something like a
  formula, which now reads without that quote, and a row is quoted the
  next time it is written. Measured on real archives, 180,418 values in 55
  files, no value reads differently and none is written differently.
- **Text Excel reads as its own escape stays as it came in the
  workbooks.** Excel reads `_x003D_` in an xlsx cell as =, so an item
  named `_x003D_1+1` opened as =1+1 without the quote prefix the other
  formula-like cells carry, and editing the cell made it a working formula.
  The underscore in front of such a run is now written as Excel's escape
  for an underscore, so the cell shows exactly the text the provider gave
  and the formula rule tests that text. No real value held such a run.

## [0.53.0] - 2026-10-15

Bilt Card statements arrive, there is a Mac package for Intel, and Wells
Fargo is confirmed on a real account. The release also has E*TRADE tell
several accounts' statements apart, a sign-in leave alone a port a hung
browser still holds, the transaction export find the closing date on Navy
Federal Visa statements, and repairs to Alpaca, First Horizon and
Robinhood.

### Added
- **A Mac package for Intel (#88).** Next to `PaperPull-<version>-arm64.dmg`
  for Apple Silicon, a release carries `PaperPull-<version>-x86_64.dmg` for
  Macs with an Intel processor, signed and notarized the same way, so an
  Intel Mac no longer has to run PaperPull from a checkout. The macOS
  workflow builds the two side by side, each on a GitHub runner of its own
  architecture, and each is smoke-tested on the hardware it is for.
  `packaging/build_macos.py` takes `--arch arm64` or `--arch x86_64`, the
  Mac's own when left out, and an Apple Silicon Mac can build the Intel one
  through Rosetta.
- **Bilt Card statements.** A new app saves the monthly statements of the
  Bilt Card 2.0, the card Cardless services, from the Bilt wallet. It
  presses only three things, the card's "View balance summary", "View
  statements" and one statement's own button, which opens the PDF in a
  tab. The statement is kept only when exactly one tab opened, on Bilt's
  statement host at the address of that statement's date, the page's own
  answer named that statement, and the PDF prints its date. The tab is
  closed afterwards. A second tab, a browser download or a tab on another
  host stops the run. The list is read from the page's own answer and has
  to match the buttons shown, count and dates, or the list stops rather
  than being called whole. An answer that holds more than its list and
  count, or a sheet that offers more or older statements, stops the list
  too. Nothing that pays, transfers a balance, redeems points, locks the
  card, adds a user or refers anyone is ever pressed, and the card id,
  statement ids, last four and your name stay out of every log and
  diagnostic file. Files are named `<date> Bilt Card Statement.pdf`, and
  a Download again of a statement whose file is still there saves a
  second copy beside it. Built from a live survey of one account and run
  live on it, eight statements saved. Statements of the Wells Fargo
  issued Bilt card, before February 2026, are not here.

### Changed
- **Wells Fargo is confirmed for credit card statements (#27).** A tester
  ran the app from 0.52.0 on a real account and it downloaded the credit
  card statements, the first account it has met since it was built without
  one. So Wells Fargo moves from waiting for a tester to supported, in the
  provider tables, the panel's list, its README and its status lines. With
  Bilt, sixty-nine providers are supported and six wait for a tester. Checking,
  savings, mortgage and tax documents have not been run on a real account
  yet, and the tables and the panel say so.
- **A release goes out with every download or not at all.**
  `tools/release.sh` stops before publishing, naming the file, when any of
  the five downloads did not come down, and it puts the two Mac disk images
  next to each other in the Assets list. The Python inside each Mac package
  is checked against the SHA-256 that python-build-standalone publishes
  before anything is built from it.

### Fixed
- **The transaction export reads the closing date on Navy Federal Visa
  statements whose label row pdfplumber cuts into pieces (#32).** On those
  statements every piece of the "Statement Closing Date" row sits at one
  height, but "i ng Date" came out long enough to be kept as a line of its
  own, and it sorted ahead of the rest of the row, so the label never stood
  before its date and the statement had no Period End. A longer piece at
  the height of the scattered characters is now rebuilt with them. Found,
  measured and fixed by @dertbv on their September and October statements,
  with the other five of their statements unchanged. The export reads every
  statement again once after the update.
- **E*TRADE tells your accounts' statements apart (#96).** The documents
  list shows each document's account in a column of its own, and the app
  read it and then dropped it, so no file name or index row said which
  account a statement came from, and two accounts' statements of the same
  title and day were taken as one document. Of those two, the download
  refused both, or saved whichever account's statement the page showed and
  never fetched the other. Each statement now keeps the account the list
  gives it, which a naming pattern can use as `{account}`, and when your
  sign-in has more than one account, the file name and the index's Document
  Summary end with the account, as in "Account Statement - Individual
  Brokerage -1234". A download takes only the link that names its own
  account, matched by the account's last digits, or by its whole name when
  it shows none. On a sign-in with one account, the statements saved before
  keep their records and file names the first time you Discover, so nothing
  is downloaded again. A closed account that no list names any more leaves
  a sign-in that reads as one account, so a statement 0.52.0 kept as one
  record for both accounts moves to the open account and is not fetched
  again, the same as 0.52.0 left it. On a sign-in with more than one
  account, which account a statement saved before belongs to cannot be
  told, so those files stay as they are and each account's statements are
  downloaded once more, named with the account. When an account's name ends
  with its last digits, changing its nickname on E*TRADE does not make its
  statements download again. Discovery logs how many accounts it found and
  never their names, and a failed download is logged by its date and title.
  Thanks to @appchamp for the report.
- **First Horizon Bank no longer misses an account panel the page draws a
  little late.** Once every panel is read, the page now settles twice and
  is read after each, and both reads must show the same panels. Before, the
  page was read once, and any panel drawn after that read was missed and the
  list was called whole. The same two reads run while a statement is looked
  up, so an account panel drawn late there now stops the run instead of
  sending the statement to review. A panel drawn more than 3 seconds after
  the panels are walked is still not seen, as the app's known ceilings say.
- **Alpaca calls its list of documents whole only when it can be.** A list
  whose window starts after it ends, or ended before yesterday, now stops
  Discover in words of its own rather than being called whole. An account
  application in the window no longer lets the list pass when something
  listed is dated before the earliest application, so a reissued
  application cannot let older statements go unnoticed. Two documents of
  one type on one date, which are left unsaved, are now counted in the run
  summary and named in the panel, not only on the console. Since they are
  listed again on every run, the panel never takes them as a reason to
  look, so the account still says when it is due or overdue.
- **Robinhood reads a statement's month more strictly.** A first page is
  taken for a month only when every statement period it prints ends in that
  month. A February page that also prints "Previous statement period
  01/01/2026 to 01/31/2026" is no longer taken for January, and is now
  refused under its own February title too, since nothing on it says which
  period is its own. It goes to Manual Review. Months Robinhood serves as
  PDFs are not read this way and are saved as before.
- **Robinhood checks an HTML month's account more surely.** A month served
  as HTML with too little text to tell it from another account's statement
  goes to Manual Review on an account page, rather than being saved as that
  account's. The text compared between accounts now has every space and
  line break taken out, so a newer pypdf that spaces words differently
  still finds the same statement, and a statement saved by 0.51.0 or
  0.52.0 is still found after its file is deleted. The note on a statement
  refused as another account's now reads "The same statement as", since
  the match can be by text and not by file.
- **The inert HTML print reads tags as a browser does.** A comment holding
  an apostrophe, or a stray quote in an attribute name, no longer hides a
  later event handler from the strip, and a javascript: link written with
  character references, such as "&#106avascript:", is made inert too.
  What a style, title, textarea, xmp, noembed or noframes element holds is
  read as text up to that element's own end tag, as a browser reads it, so
  a "<!--" or a quote there hides nothing after it. JavaScript was already
  off when the page is drawn, so none of these ran.
- **A sign-in no longer opens browser after browser on a port that a hung
  browser still holds (#90).** A browser left from an earlier sign-in that
  stopped responding kept its debugging port, so every browser tried next
  could not take it, and a Brave window and then a Chrome for Testing one
  opened on profiles of their own and closed again. A sign-in now notices
  a port that is taken but silent, even by a browser that takes no more
  connections, gives a browser still starting a few seconds to answer, and
  otherwise opens nothing and says how to find what holds the port and how
  to end it.

## [0.52.0] - 2026-10-14

Six providers arrive, First Horizon Bank checking statements, Chase
Business statements, TreasuryDirect, IRS tax transcripts, Spectrum
Internet and Mobile statements, and Venmo monthly statements. The release
also has NetBenefits read every plan on a sign-in with several employers,
and the transaction export find the closing date of a scattered summary
box and stop taking a due date or a next closing date for it.

### Added
- **First Horizon Bank checking statements.** The app saves the monthly
  statements First Horizon keeps online, about two years of them, from the
  Statements page of digital banking. It presses only two things: an
  account's panel, to open it, and one statement's own Download PDF, once,
  and it keeps the download only when it comes from that statement's own
  address and is a PDF. Nothing that pays, transfers, enrolls or changes
  statement delivery is ever pressed. If a statement's Download PDF is
  turned off on the page, nothing is pressed for it, the run goes on, and
  the statement is left for the next run. A panel the page hides, turns off
  or draws late stops the list, or the run, rather than being skipped. If
  the bank signs you out, or the run nears the bank's ten-minute session
  limit, the run stops, keeps what it saved, and asks you to sign in again
  and Resume. Account nicknames, numbers and balances are kept out of every
  log, diagnostic file and file name. A full run on a contributor's checking
  account saved all 24 statements online, one in Pilot and 23 in Run All.
- **Chase Business statements from the business document center.** A new
  `chasebusiness` app saves the monthly statements of the business accounts
  on a Chase business profile, up to the seven years Chase keeps online,
  filed as Business Checking, Business Card or Business Debit. It chooses
  each account in the document center's menu, opens Statements, picks each
  year and saves a statement through its row's own save menu and Save as
  PDF. Those six kinds of control are the only ones it ever presses, and
  payments, transfers, wires, Zelle, settings and sign-out are never
  touched. A run stops on its own when Chase shows its session timeout or
  signs you out, and keeps what it saved. Account names and numbers stay
  out of every file name, log and diagnostic file. Chase gives accounts
  and statements new ids at each sign-in, so a statement is known by its
  account's class and a short digest of its last four, which tells two
  accounts apart but is no secret, since a last four is easy to guess
  from it. Verified on one profile, where it saved 10 checking statements
  on a full run. A business card's statements are untested.
- **TreasuryDirect.** A new app for the U.S. Treasury's own site for
  savings bonds and Treasury securities. TreasuryDirect has no PDFs, so the
  app saves its pages as PDFs. Current Holdings, Security History and
  Payment History are dated snapshots, each kept only when its text names
  the page and drawn without its link addresses. TreasuryDirect ends your
  session if a page is opened any way but by its own links, so the app
  works in the tab you signed in with and only presses the site's own tab
  and history links, checked by their words and by exactly where they lead.
  It never opens an address, never submits a form, and never presses
  BuyDirect, Gift Box, Logoff, the Investor InBox or any link that changes
  your account. A year ManageDirect lists as taxable is shown once for you
  to save its 1099 yourself, since its pages have not been seen yet. One
  sign-in can hold several accounts, so each document is kept under the
  account it was listed on, by a digest of its number, and saved only while
  your tab shows that account. If TreasuryDirect signs you out or asks for
  a passcode or a security answer, the run stops and keeps what it saved.
  Your account number, name and session id are kept out of every log and
  diagnostic file. Run on a contributor's own account, where Discover
  listed 3 documents, Pilot saved 1 and Run All the other 2, and every PDF
  opened.
- **IRS Online Account, tax transcripts, run in full on one account.** The
  app saves your account, return, wage and income, and record of account
  transcripts from your IRS Individual Online Account, reading the same
  list the transcript page asks for and fetching each PDF by its own
  address with your signed-in session. Nothing on the site is clicked, and
  payments, payment plans, IP PINs, authorizations and your address are
  never touched. You sign in yourself through ID.me. If the tab is on
  ID.me or the account signs you out, the run stops and keeps what it
  saved. Your name and SSN are kept out of every log, record and file
  name. Two transcripts of one type and period are named apart by their
  form or MFT, and a transcript the IRS stops listing before it is saved
  goes to Manual Review while the run goes on. Built from a read-only
  survey of one account and run in full on it, 26 transcripts listed and
  all 26 saved as valid PDFs. Notices are not read yet. With notices in
  scope, a notices page that lists one stops Run All rather than being
  guessed at, and Resume then saves your transcripts. Take Other Document
  out of the app's document types and the notices page is never opened.
  Run Diagnose and attach the file to help.
- **Spectrum Internet statements, about a year of them.** For each
  statement the app brings up its page (an older one by pressing its own
  row on Statements, so the page prints that statement and not the newest),
  presses View Printable Statement once and keeps the PDF the page makes,
  only when it matches the PDF Spectrum sent for that statement, prints the
  statement's date and is not a copy of one already saved. Two statements
  of one date, one per account after a transfer, are left for a manual
  save. No tab is opened and nothing is downloaded through your browser,
  and if the browser will not take the run's own download folder, nothing
  is pressed and the run stops. A statement whose button Spectrum has
  turned off is left for the next run. The app never pays and never
  touches Auto Pay, paperless, equipment, service or settings, and
  account numbers and the service address stay out of every file and log.
  On the account owner's own account Discover listed 13 statements of two
  accounts, Pilot saved the newest and Run All saved 10 more.
- **Spectrum Mobile statements, from the same app.** Spectrum has no PDF
  of a Mobile statement, so for each finished one the app opens Billing,
  presses its "Mobile Account Number" link, presses the statement's own
  row and its Expand All, checks the page reads that statement's date and
  Mobile before and after, and prints the page to a PDF named like
  `2026-08-13 Spectrum Mobile Statement.pdf`. The statement still under
  way, the running total and device orders are not listed, and the page's
  own Print, Auto Pay, payments, device and settings controls are never
  pressed. The Mobile account number, phone numbers and amounts stay out
  of every file name, record and log. A live run listed all 12 Mobile
  statements and opened each one's own page, and a whole Mobile run is
  still to come.
- **Venmo monthly statements.** Venmo has no PDF statement on the web, only
  a statement page per month and a CSV. The app opens each finished month's
  statement page by its own address, presses its own "Show more" until every
  transaction is drawn, checks the page shows that month in full, and prints
  it to PDF as `<month end> Venmo Statement.pdf`, back to your start date.
  With no start date it reads two years, and when the oldest of those months
  has transactions it saves those months and then stops rather than call the
  list whole. Nothing else on the site is clicked, months with no
  transactions and the month still under way are skipped, and the CSV is
  never taken. A month whose "Show more" Venmo has turned off is left for
  review. It never sends, requests or transfers money and never touches
  banks, cards, crypto, business profiles or settings, and your profile id,
  username, name, email and phone stay out of every log and diagnostic file.
  Built and run on one account, 24 statements with the two busy months
  expanded in full. A page that is not what it expects stops the run rather
  than being guessed at.

### Fixed
- **Fidelity NetBenefits adds support for a sign-in with several employers
  and plans.** NetBenefits remembers the plan last looked at, and the app
  took such a sign-in for one with a single plan and named every statement
  after the employer in the statement's own header. With no plan
  remembered it found nothing at all. It now reads every plan from the
  site's Choose a Plan page, or from its Select Account page when there is
  no such page, chooses each plan in turn, makes a statement only while the
  Statements page shows that plan by name, and files it under that name,
  as in `2026-06-30 NetBenefits Quarterly Statement - ABC 457(b) Plan.pdf`.
  Nothing on the site is pressed, and the employer chooser, which would
  change a saved preference, is never used. A plan whose address sends you
  to another Fidelity site, as one plan's did to the Fidelity retail
  sign-in, is left for you to open yourself and never followed, and a
  sign-out partway stops the run and keeps what it saved. Plan and employer
  numbers are kept out of file names and diagnostics, and the plan list a
  run keeps, `plans.json`, is never committed. The plans of one employer
  share one combined statement, which is saved once under the employer's
  name, or the plans' names, and counted for each plan whose own request
  gives that very statement, and a statement that does not name the plan
  it was made for is set aside for review. A sign-in with one plan works
  exactly as before, with the same file names and records, and one that
  gains a second plan keeps what it saved rather than saving it again. A
  Choose a Plan page that shows one plan beside other links naming a plan
  stops the run and says so. The several-plans path was built from a
  read-only survey of one sign-in, and it ran live on one sign-in with two
  employers and four plans, 78 statements saved.
- **The transaction export reads the closing date of a summary box whose
  characters drift apart (#32).** 0.51.0 rebuilt such a box's lines by
  height alone. On a Navy Federal Visa statement the end of the
  "Statement Closing Date" label sat more than 4 points below its start,
  so it was cut off from its date and the statement still had no period.
  Each character now continues the line it touches that sits nearest its
  height, and the pieces of one row are read as one line, so the label
  stays in front of its date. The closing date is also the latest of the
  dates that run on right after its label, no longer the latest date
  anywhere on the label's line and the next. That was the due date when
  one printed there, and it gave American Express statements that print a
  Next Closing Date beside the Closing Date, and Target Circle Card
  statements with the due date on the line before, a Period End a month
  late. A page pdfplumber reads whole is not rebuilt, and the export reads
  every statement again once after the update.

## [0.51.0] - 2026-10-14

Alpaca arrives, statements and trade confirmations from a Live brokerage
account, and the control panel shows PaperPull's Terms of Use once, the
first time it opens. The release also has Robinhood save the months it
serves only as HTML, a sign-in and the runs after it use one browser or say
why not, an app in a source checkout follow the checkout's core again, and
the transaction export reconcile Navy Federal Visa statements and find
their statement period.

### Added
- **Terms of Use.** TERMS.md, also at paperpull.net/terms.html, says what
  PaperPull does and does not promise, disclaims warranties, limits
  liability, and takes away nothing the AGPL gives. The control panel, on
  the desktop and on PaperPull Server, shows a short summary the first time
  it opens and again whenever the terms change, and goes on once I
  understand is pressed. The answer is kept in the panel's settings file,
  so the server asks once for the box. The apps' own commands do not ask.
  Every package carries TERMS.md, and the panel's About card links the
  terms.
- **Alpaca brokerage and crypto statements and trade confirmations, for your
  Live account.** The app opens Alpaca's Documents page, reads the list the
  page itself asks for, and saves each statement and trade confirmation by
  pressing that row's own Download once and keeping the PDF your browser
  receives. Nothing else on the site is pressed, no trading, transfers,
  deposits, account switching or settings. A Paper account is never read. If
  Alpaca is showing Paper, the run stops and asks you to choose your Live
  account yourself, then Resume. The JSON copies of trade confirmations and
  the account application are skipped. If Alpaca has turned one document's
  Download off for now, that document is left for the next run and this run
  goes on. Two documents of one type on one date are counted and left
  unsaved, since a row cannot tell them apart, and the rest are saved. The
  page asks Alpaca for about three years of documents, so when the list
  holds no account application Discover stops unless `--start-date` or
  `default_start_date` falls on or after the list's first day. Your account
  name, account number and every document's ID are kept out of every log and
  diagnostic file, and file names and the document index never carry the
  account holder's name, whatever config.json asks. Built from the account
  owner's walk through their own Live account, then run whole on it, which
  saved 22 documents.

### Changed
- **How the browser choice is described.** The Walmart, Amazon, Verizon,
  Anthem and Chase apps say plainly why they sign in through the person's
  own installed browser, which is that those sites do not work in the
  browser build Playwright installs. Nothing about how they run changed.

### Fixed
- **An app in a source checkout follows the checkout's core again.** Before
  #65 each app in a checkout had a .venv of its own, and its setup installed
  the shared core editable, so the app ran the checkout's core as it
  changed. The control panel then copied the core into that .venv, where
  the copy won every import, and since the panel never refreshes a
  checkout's own apps, every later core change missed that app. The panel
  no longer copies the core over an editable install in its own checkout,
  and it takes out a copy an earlier panel left there. Installs outside the
  checkout, the packaged app and PaperPull Server keep their copy of the
  core and still have it brought up to date as before.

- **A sign-in and the runs after it use one browser, or say why not (#90).**
  On an Intel Mac, a Citi run opened a second window on another profile and
  found it signed out, though the sign-in had gone well. Each of these could
  lead there without a word, and none does any more.
  - A sign-in that finds another browser already listening on the app's
    port now says so, opens the sign-in page in that browser, which is the
    one a run attaches to, and launches nothing beside it. A browser started
    there could never take the port, while the wait for the port heard the
    old one and called the sign-in done.
  - A sign-in browser that never opened its debugging port is closed rather
    than left open beside the next one tried.
  - A config with no `cdp_url` still has the run open a browser of its own,
    and the run now says so, names its profile folder, and says how to use
    the sign-in window instead.
  - Seventeen apps fell back to port 9224, Wealthfront's, when a config named
    no port, so two apps could meet on one port. Each now falls back to the
    port its own example config names.
  The sign-in launchers of 21 apps no longer promise "a normal Chromium
  window", since the browser that opens depends on the app and the
  computer. Thanks to @appchamp for the report.

- **The transaction export reconciles card statements that print no signs
  (#32).** A Navy Federal Visa statement prints every amount unsigned and
  tells a payment or a refund from a purchase only by the PAYMENTS AND
  CREDITS heading above it, so the export summed everything as a charge
  and called the statement not reconciled. Rows under that heading, which
  can carry on after a page break, are now taken off the balance and the
  rest added to it. That reading is used only for a statement that prints
  no sign anywhere, and only when it adds up to the cent against the
  statement's own balances. Every statement is read again once, since the
  saved readings came from the old rule. Thanks to @dertbv for the sample
  lines.
- **The transaction export finds a statement period that pdfplumber
  scattered (#32).** On a Navy Federal Visa statement the summary box's
  characters sit at slightly different heights, and pdfplumber read each
  of its lines as a column of single characters, so the Statement Closing
  Date was lost and Period Start and Period End came out blank. A page
  that comes out that way has those characters put back into lines by
  height, while every line read whole stays exactly as it was, and the
  closing date label now allows a stray space inside a word. Thanks to
  @dertbv for working out what pdfplumber was doing.
- **Robinhood saves the months it serves only as HTML.** Some months of an
  account's statements come from Robinhood as a web page, behind a
  "Download HTML" control, and used to be refused as "not a PDF" and marked
  for manual review on every run. They are now rendered to PDF through
  PaperPull's own print path, drawn in a separate browser context with
  JavaScript off and no connection to anything, and kept only when the PDF's
  first page prints that month's statement period, labelled or, as an HTML
  month prints it, bare and spanning the whole month. A record
  listed under the old title moves under the cleaned one, keeping whichever
  of two is done, so nothing is downloaded twice. The page is stripped of
  anything active until nothing more comes out, and refused when a tag
  rebuilt by the strip is still there. A retirement or crypto page that
  hands over the individual account's HTML month is still caught, by the
  digest of the statement's text, since each print of one page is a
  different file. These months need the signed-in browser (`cdp_url`), and
  without it go to manual review.


## [0.50.0] - 2026-10-13

Two providers arrive, SDG&E bills from My Energy Center and Shelby County
property tax receipts, and PaperPull Server now hands over a support report
and the documents a run set aside as downloads. The release also has Costco
receipts name the part of Costco they came from, Kroger keep its banner
through Download again, and Discover send a card that moved to Capital One
to the Capital One app, so Discover counts as supported.

### Added
- **Costco receipts say which part of Costco they came from (#60).** A file
  name pattern's `{store}` gives Warehouse, Gas Station, Car Wash, or Gas
  and Car Wash, read off the heading Costco prints on each warehouse
  receipt, or Online for an order. Every row on the
  Warehouse tab says In-Warehouse, gas included, so the store was the list's
  word and told nothing apart. Rename reads it off the heading of each
  receipt already saved, asking nothing of Costco, and a preview leaves
  every record as it was. Food court, pharmacy and tire center receipts are
  Warehouse until a member's receipts show how to tell them apart.
- **SDG&E (San Diego Gas & Electric) bills from My Energy Center.** The app
  reads the bills Billing History lists, about two years of them, and saves
  each bill's PDF, fetched by its own address with your signed-in session.
  Nothing on the site is clicked, and payments, autopay, paperless,
  pricing plans and service changes are never touched. If My Energy Center
  signs you out partway, the run stops, keeps what it saved and asks you to
  sign in and Resume, rather than marking the rest for review. Your account
  number, contract account and service address are kept out of every log
  and diagnostic file. With more than one account on your sign-in, only the
  one selected in the portal is listed. A full run on a contributor's own
  account saved all 8 bills online.
- **Shelby County Trustee, property tax receipts and the current notice for
  one Memphis parcel.** The Trustee's public lookup needs no sign-in, so the
  parcel ID goes in config.json, where it stays. It is never written to a
  log or a diagnostic file, and neither is the owner the page shows or a
  bill or receipt number. Each receipt, and the notice while a balance is
  due, is a PDF the page builds itself, and the app keeps the one the press
  made without opening a tab. Both lists are read page by page to the
  total the page states, or the run stops. Two receipts paid the same day
  for one tax year are told apart by the last four digits of their receipt
  numbers. The payment site is never opened. A full run on a contributor's
  parcel saved 17 receipts across 16 tax years.
- **PaperPull Server hands over a support report and what was set aside.**
  The desktop opens a folder after a support report or a recording, and
  after a run that set documents aside, and the server offered nothing
  there, since its folders are on the server. The run's page now offers
  the report's file to download, the survey Diagnose says to attach or
  the recording, from the last hour, and the documents in the account's
  Manual Review folder as one zip. A screenshot Diagnose takes stays on
  the server. Neither hands over a link placed in the shared folder, a
  folder there that is a link, a second hard link to a file, or a file
  swapped for one after it was checked, and the failure file is handed
  over the same way.

### Fixed
- **Kroger keeps the store it reads on a Download again (#41).** A receipt
  saved before its store was read, then downloaded again, was saved under
  a name with the banner the receipt names, Metro Market or King Soopers,
  while its record kept no banner. Review Names then named that copy
  without it, and the next Rename put the banner back, renaming the file a
  second time.
- **Discover sends a card that moved to Capital One to the Capital One
  app.** A Discover run that landed on Capital One still said the app
  could not download from Capital One yet, long after the Capital One
  provider came to read a moved Discover card on capitalone.com (#13). It
  now says to press Add a provider on the panel's Accounts page and choose
  Capital One, and still says that what it saved is untouched and its
  history kept. The provider tables and the panel's line for Discover say
  the same, and Discover counts as supported, so sixty providers are
  supported and seven wait for a tester.

## [0.49.0] - 2026-10-12

Review names comes to the control panel, so PaperPull Server, which has no
console, can rename the receipts an app was unsure how to name, and
PaperPull Server is no longer a beta. The release also has Robinhood save
IRA statements, carries what Target and Apple need through a history moved
with `--minimal`, and has the panel tell a receipt saved under a name to
review from one set aside.

### Added
- **Review names in the panel, and on PaperPull Server.** Every receipt
  app asks for a better name for each receipt it was unsure how to name,
  and it only ever asked in a console, from the `review_names` file in its
  folder. PaperPull Server has no console, so it had no way to do it. A
  receipt provider's More now has **Review names**, on the desktop and the
  server alike. It lists the receipts waiting, with each one's date, order
  number and items, and renames each one you type a better summary for,
  with its rows in the receipt index and order history and its record in
  progress.json following it. A blank box keeps its name, and so do
  words that ask to keep it, such as keep, keep this name or same, here
  and in the console alike, so they never become a receipt's name. A
  summary is taken as one line of at most 120 characters. The app runs the review
  the console one runs, with what you typed, so it renames only what that
  review would, and a name typed for a receipt that stopped waiting
  meanwhile does nothing and is said. The double-click
  file still works as before.

### Changed
- **PaperPull Server is no longer a beta.** It has shipped with every
  release since 0.43.0, so the label is gone
  from its setup guide, the README, the panel's footer, the image's
  description and the server kit's read-me. Nothing about how it runs
  changes.

### Fixed
- **Robinhood saves IRA statements.** The retirement statements page,
  read since 0.46.0, was read only when a heading on it named a retirement
  account, so a statement of the individual account shown at the
  retirement address would not be saved again as a retirement one. On a real account the only
  heading on every statements page is the account holder's name, so no IRA
  statement was saved at all. Each statement's own title names its account
  there, "Consolidated IRA Statement" on the retirement page and
  "Individual Investing Account Statement" on the individual one. The page
  is now also read when no heading names any account and every statement
  it lists names a retirement account and none names another, and the
  individual list shown at that address is still never read as
  retirement statements. A page any of whose statements names another
  account is not read whatever its headings say, so an offer to open a
  retirement account, or a holder called Ira shown in capitals, no longer
  passes for the retirement account's own heading.
- **A Target order moved with `--minimal` while an invoice was still to
  fetch no longer saves the others again.** Target counts an invoice of an
  order as saved by the order's list of those it saved, and an order with
  one still to fetch has no row in the receipt index yet. `--minimal` left
  the list out, so on the new computer the next run saved the invoices
  already saved a second time under new names, and Download again did the
  same to every invoice on the list though its file was copied across. The
  export now carries the list for Target, each invoice's file, its place
  among the order's, the number Target prints on it, whether it was kept
  or put aside and its size and page count. A list filled into a record an
  older file moved names the files under this computer's folder, as a
  record the import adds does. What `--minimal` prints when it is done now
  says that order and invoice numbers stay, and file names, which can name
  accounts and items.
- **Target no longer stops on an order whose list of invoices was
  damaged.** An entry whose file was not text, or a list that was not a
  list, raised as the order's invoices were walked, so the order failed on
  every run without its invoices being tried. Such a value now reads as
  none, as every record value does, and an invoice it no longer names is
  fetched again.
- **A receipt saved under a name the app was unsure of is no longer said
  to be set aside.** A run that saved one said a document set aside sat in
  the Manual Review folder, where there was none, since the receipt was
  filed where it belongs and waits only for a better name. Every receipt
  app now reports such a receipt on its own, and the panel says it was
  saved under a name to review and offers Review names, keeping the Manual
  Review folder for a document really set aside.
- **An account's Latest documents lists receipts saved by older versions.**
  It read only records that say they were downloaded, which Target has
  written for every receipt it saves only since 0.41.1, so an older Target
  archive of 67 receipts said Nothing saved yet. A record from before then counts when it says it
  was completed.
- **An Apple purchase whose receipt Apple refused keeps its count of
  refusals through a move with `--minimal`.** Apple saves a record of the
  purchase in place of its receipt once it has refused the receipt on three
  separate runs. `--minimal` left out the runs counted so far, so on the
  new computer the purchase took three more refusals before its record was
  saved. The export now carries them, and the runs it was not asked on, for
  a purchase not saved yet, and a newer file fills them in for one an older
  file moved without them.

## [0.48.0] - 2026-10-12

A new control panel, on the desktop and on PaperPull Server, built around
what needs you. Every account shows one plain status and one button for
the next step, Get new for all runs every account that may have something
new, and each account remembers its last runs. The release also stops a
link from another program starting a run, keeps the index and every
ledger in step when Rename or Review Names cannot write one, carries what
American Family, AT&T and Optum Bank check in a history moved with
`--minimal`, and repairs several apps that stopped on a damaged record.

### Added
- **Get new for all.** When several accounts may have something new, one
  button runs them one after another, and pauses at one that does not
  finish so you can sign in again, try once more or skip it.
- **Each account remembers its last runs.** The panel notes every run it
  starts in `panel-runs.json` in the account's folder, how it ended and
  which files it saved, so a row can say a run stopped partway and an
  account shows its recent runs. A run closed with its page counts as
  stopped.

### Changed
- **A new control panel, built around what needs you.** The home page,
  Accounts, lists every provider and person, most in need first, each with
  one plain status (Overdue, New one likely, Possible gap, Stopped partway,
  Needs a look, Up to date, Not started) and one button for the next step.
  Each account has a page of its own with two steps, Open sign-in window
  and Get new documents, and Which dates as one choice of all dates, one
  year or a range. Try the newest few first and Only check what's there sit
  beside the main button, Continue appears after a run that stopped, and
  everything rarer is under More, each item saying in a line what it does.
  A run leads with its outcome and the files it saved, keeps the full
  output under Technical details, and offers a problem report where it
  ended, and a bar follows you to other pages while it goes. The panel's
  words follow, Login is Sign in, Pilot is Try the newest few first,
  Discover is Only check what's there, Run All is Get new documents and
  Resume is Continue, while the terminal's commands keep their names.
  Spreadsheets, File names and Settings are pages of their own. Light by
  default, dark when the system or Settings asks, and it fits a phone. It
  is set in Atkinson Hyperlegible, made for legibility, which ships inside
  the app under the SIL Open Font License, so no font is fetched from the
  web.
- **Download again is Restore deleted files**, a dialog of its own under
  More. It still needs a year or both a From and a To date, says what
  happens to files you still have and applies to one run, and it is never
  a box that changes what the next run does.
- **The welcome is three steps**, where to save, which providers and whose
  documents they are. Providers can be searched and grouped, and the
  account holder's name is asked on the page instead of in a browser
  prompt.
- **File names shows the name first.** Its parts are chips you add, remove
  and move, separator and date style are chosen by example, and the
  pattern can still be written by hand under Edit as text.
- **On PaperPull Server the sign-in window docks beside the page** when a
  sign-in starts, and the Browser Screen button is now Sign-in window. The
  header says when new files go to Paperless.
- **The welcome list says what each provider downloads in one plain line.**
  It showed the provider table from PROVIDERS.md, which is written for
  GitHub, so someone choosing their bank read who tested it, issue numbers
  and how it reads the site. Each provider now has a short line of its own
  in `gui/providers.json`, a provider not yet run on a real account says
  so, and a few carry a short note, such as Discover cards moving to
  Capital One.

### Fixed
- **A copy put aside for review stays in review after a history is moved
  in.** When the other computer had set the same receipt aside after three
  days of its page showing nothing, or had recorded the purchase or
  document as finished without saving it, an import replaced the record of
  a copy waiting in Manual Review here. A run then said the receipt did not
  show on three separate days for a purchase with a copy on disk, and
  deleting the copy no longer asked for it again. Such a record now keeps
  its own state while its copy is still there, including in an install
  that writes into its own folder, as a new one does. One whose copy was
  deleted before the import takes what the other computer finished, as
  before, and a document the other computer saved is still never
  downloaded again.
- **American Family still catches one bill's statement handed over as
  another's after a history moves with `--minimal`.** When a statement it
  takes has the very bytes of another bill's statement of that date, it
  trusts neither copy and sends both to Manual Review. It finds the other
  one by each saved statement's digest, date and account part, which
  `--minimal` left out, so on the new computer the statement was saved
  under the wrong bill. The export now carries those three for American
  Family. The account part is the masked last four of the bill's account
  or policy, which its record keys and file names already hold.
- **An Optum Bank history moved with `--minimal` still tells a corrected
  tax form from the one it corrects.** Optum can list a corrected 5498-SA
  under the title of the form it corrects, and the form saved first keeps
  its key. It is found by the address of its file on Optum's site, its
  product and its title, which `--minimal` left out. So on the new computer
  a page that listed the corrected form first gave it the saved form's key,
  the corrected form was never fetched, and the saved one was fetched
  again. The export now carries those, with the form's id, for Optum
  Bank's tax forms alone. Its key holds the product, title and id already,
  and the address adds Optum's own number for the form.
- **An AT&T history moved with `--minimal` still has a bill 0.34.0 saved
  under the wrong year fetched again.** AT&T clears such a copy as it
  starts (#26), finding it by its date, kind, account, size and page count
  beside the next year's bill, which `--minimal` left out. It mattered only
  for an install that had not opened AT&T since 0.34.2 when its history
  moved. The export now carries those five for AT&T. Its key holds the
  date, kind and account, which is only Wireless or Internet.
- **A history file made now, imported over one an older `--minimal` file
  moved, gives each record what its provider's own checks read.** An
  import kept a record it already held as it was, so a statement or form
  moved with an older `--minimal` never gained the digest, address, size
  or other fields American Family, AT&T, Optum Bank and Robinhood look for
  in their saved records, whatever file came after. A newer file, minimal
  or whole, now fills in each of those a record lacks, and never one it
  holds.
- **Rename no longer leaves the index naming files by their old names.**
  Apply renames, and Rename them on the File names page, renamed the files
  first and then wrote the index, the order history and the run state.
  With the index open in Excel, that write waited its minute and gave up
  after the files had moved, so the index and progress.json still named
  every renamed file by its old name. Verify then reported each one
  missing, and the next rename said every file was already named the way
  the app names it, so nothing pointed the index at them again. Now each
  of them is checked before anything is renamed, waiting the same minute
  while one is open in another program, and nothing is renamed while one
  stays open. A write that still fails after the files moved puts every
  file back under its old name, where the index and the run state still
  find it, and a file that cannot be put back is listed with its new name
  and its old one. Either way the rename says what happened and stops as
  a run that did not finish, so the panel no longer reports the files
  renamed. It also no longer says that Resume carries on from where it
  stopped, since Resume has nothing of a rename's to carry on with.
- **A run state open in another program no longer ends a run with a
  traceback.** Every app saves its run state, progress.json, on its way
  out, and only then writes the result the panel reads. With progress.json
  open in another program, that save waited its minute and stopped with a
  traceback, so the panel never got the run's result. A Rename that had
  just stopped because progress.json was open waited a second minute for
  it and then showed the traceback over its own clean stop. Now that save
  says in one line that the file could not be written and where it is,
  the run ends as it would have, and a file the run has already waited for
  is not waited for again. The list of what was found, discovery.json, is
  saved on the way out the same way.
- **Review Names no longer leaves the index naming a receipt by its old
  name.** Review Names, which renames the receipts a receipt app was unsure
  how to name, renamed each file and then wrote its new name into the
  index, the order history and progress.json. With the index or the order
  history open in Excel, the rename was done, the write waited its minute
  and gave up, and the index kept the old name, so Verify reported the
  file missing. Now each of them is checked before the first question,
  waiting the same minute while one is open in another program, and
  nothing is asked or renamed while one stays open. A write that still
  fails after a receipt was renamed puts that receipt back under its old
  name, never over another file, writes back what was written for it, and
  stops the review with a message saying so. Receipts renamed before it
  keep their new names.
- **Rename counts and lists a file once when two rows of the index name it.**
  Download again can leave two rows of one purchase naming one file. Rename
  preview, and the File names page, gave the second row a name of its own
  beside the first's, so the file was counted twice and listed with two new
  names, though it was renamed once. That second name was still kept from
  every other file, so another document wanting the same name could take
  " (3)" with " (2)" free, and the next Rename moved it again. A file
  already told apart from another by its number was moved on to " (2)" for
  its second row, and the next Rename moved it back. Each file now takes
  one name, and every row naming it follows it.
- **A Target order's list of invoices follows its files when Review Names
  or Rename renames them.** Target keeps every invoice of an order split
  into several in the order's record, and only one of them as the order's
  file. Both renames corrected the index rows and that one file and left
  the list naming the old names. A later file given such a freed name was
  then taken for this order's too, so Review Names left it out of the
  review and Rename kept its name. Each invoice in the list now names its
  file as it is, whichever invoice was renamed. A list an earlier rename
  left behind is mended when Review Names or Rename next runs, each entry
  following the order's own file that says it is that invoice, and Download
  again no longer counts another order's file under such a name as this
  order's, an invoice whose number did not read included. A file another
  order holds is taken for this order's only by an invoice number both
  carry, a later order's tip named only in its list holds its file too,
  and a renamed invoice deleted since is no longer followed onto a later
  order's file under its freed name. An invoice deleted once it was
  imported elsewhere keeps its entry, so it is not downloaded again.
- **Kroger, Chase, AT&T, Robinhood and NewRez no longer stop on a record
  holding a number or a list where text belongs.** progress.json can be
  edited by hand or left damaged by a crash. A store that was not text
  stopped Kroger's Rename and Review Names, a title or account that was not
  text stopped every Chase command as its records loaded, a saved bill's
  account or kind that was a list did the same in AT&T, and a title or
  date that was not text stopped the Rename of Robinhood's tax forms and of
  NewRez's statements. Such a value now reads as none, as an empty one
  does, and AT&T leaves such a bill out of its check for a bill saved under
  the wrong year.
- **The panel says when a Discover stopped.** In every app, Discover told
  the panel nothing about how it ended, so one that stopped, with its list
  cut short or never coming, read "finished, check output" just as one
  that read the whole list did, and its failure file was never offered.
  Discover now tells the panel how it ended. One that stopped reads as
  stopped, offers its failure file and offers Check again rather than
  Continue, which downloads. Discover still downloads nothing and leaves
  new-this-run.txt as the last download run wrote it.
- **A second run of the same account is refused while one is going.** Two
  tabs could start two downloaders on one account's records, browser and
  folder at once.
- **PaperPull Server's footer no longer says it runs locally or offers the
  Store edition.** It names PaperPull Server and its version, says it runs
  on your own server, and keeps the Ko-fi link.

### Security
- **A link opened from an email, a chat or a PDF no longer starts a run in
  the control panel.** The panel's page asks for everything it does by
  script, and the browser marks each such request as coming from the
  panel's own page. A link opened from another program is marked instead
  as an address the browser opened by itself, as one typed into the
  address bar is, and the panel answered that, since nothing about it
  pointed to another site. A run starts from a plain address, so a link to
  that address opened while the panel was running started the run, on
  PaperPull Server too in a browser signed in to it. Every address of the
  panel's API now refuses a request the browser opened by itself, on the
  desktop and on PaperPull Server, and so do the server's sign-in, its
  sign-out and its Browser Screen connection, which only its own pages ask
  for. The panel itself still opens from a link, a bookmark or the address
  bar. An address of the API typed in by hand is refused with a note
  saying only the panel's own page asks for it. A tool such as curl, which
  says nothing about where a request came from, is answered as before, and
  so is a browser too old to say, Safari before 16.4 among them.
## [0.47.0] - 2026-10-12

Your providers and download history can move to another computer or to
PaperPull Server, and PaperPull Server now runs each provider's code from
the image rather than the writable data folder. The release also repairs
renaming past a damaged record, Resume keeping to its year or dates, and
several providers.

### Added
- **Your providers and download history move to another computer, or to
  PaperPull Server (#67).** Export history on the Status tab saves a file
  listing each provider and person, their settings and every document
  already downloaded. Import a history file on the other machine, or
  Moving from another computer on its welcome page, shows what it will do,
  then sets up each provider and person not set up there, with the account
  holder's name, file name patterns and start date, and marks what they
  already downloaded, so nothing is downloaded again and nothing reaches
  Paperless a second time. Folders, browser profiles and debugging ports
  are always the new machine's own, a provider already set up keeps its
  settings, and no sign-in, password or PDF is in the file.
  `tools/migrate.py` now carries second people and settings too, and
  still imports a file from an older version. A path in a second person's
  folder is no longer taken for one in the first person's when its folder
  name begins the same way.

### Fixed
- **PaperPull Server runs each provider's code from the image, not the data
  folder.** The server ran a provider's entry script, its interpreter and
  the modules it imported from the install folder in the data share, which
  anyone who can write to the share can fill, so what was placed there ran
  inside the container that holds the signed-in browser profiles. The
  server now runs the shipped copy from the image, with the data folder
  holding only configuration, rules, documents and records. The desktop app
  is unchanged.
- **Rename and Review Names finish past a damaged record in progress.json.**
  A record whose file path or file name was a number, a list or a mapping,
  from a hand edit or a damaged file, stopped Rename after it had moved the
  files and rewritten the index, so progress.json kept naming files that
  were gone. Kroger's Rename stopped before it started, and Review Names
  stopped right after renaming a receipt whose own record held such a path
  or whose items were damaged. Such a value is now read as no path at all,
  as an empty one is, and is left as it was.
- **Anthem's member documents, ID cards and letters stay inside the year
  or dates a run asks for.** Run All took them after the EOBs in a loop of
  their own that read neither the year nor the dates, nor the configured
  start date. So a run for one year took every year's, and a Download
  again of one year took every one of them again and saved a second copy
  beside each. They now follow the same rule as the EOBs. A card is dated
  by when it took effect, and a card or letter that comes with no date is
  left out of a run that has a year or dates, as an EOB with no date is.
- **Ally no longer counts its statements list as read with a year missing.**
  Ally lists one year at a time, and Discover picks each year in turn.
  Once any one year had answered, the walk was taken as done, so a year
  whose pick did not take, or whose list Ally failed to send, was left out
  while the list was noted as read whole, and Resume never went back for
  it. Every year the picker offers now has to answer, and otherwise the
  run says the list was not read whole.
- **A second person's account no longer takes another app's browser port.**
  Add a person, and `add-account`, gave the new account its app's port
  plus 10, so a second E-ZPass account landed on Interactive Brokers' port
  and a second PayPal account on Coinbase's, and the two browsers attached
  to each other's signed-in session. The new port now moves past any port
  another app or account already uses.
- **Review Names and Rename agree on a name another order's file already
  has, and keep the part of a split order.** Review Names told such a file
  apart with " (2)" where a download and Rename add the order number, so
  the next Rename moved it again, and the first invoice of an order that
  came as two lost its "(1 of 2)" on the way. An invoice a download had
  told apart by its order number lost its part in both commands. Review
  Names now adds the order number as the others do, and a part followed by
  the order number or a " (2)" is kept.
- **Resume in every receipt app keeps to the year or dates it is given.**
  The panel passes the Scope row to Resume, and Pilot and Run All keep to
  it, but the fourteen receipt apps' Resume took every incomplete purchase
  of every year, and ignored the configured start date too. From a
  terminal, `--resume --redownload --year 2025` fetched every purchase of
  every year again. Resume now chooses its purchases the way Pilot and Run
  All do, as the document apps' Resume already did. So a configured start
  date holds on Resume too, a purchase with no date is left out of a
  Resume with a scope or a start date in every app but Walmart, and
  Walmart places such an online order by its order page, all as Run All
  does. A scoped Resume with nothing to do now says everything in scope is
  complete, not every purchase. Walmart's Resume also counts
  `--max-purchases` as its Run All counts a limit. It cut its list before
  any order page was open, so an online order whose page placed it outside
  the dates used a place and the orders inside them were left. Now such an
  order takes no place, and the run says how many the limit left.
- **PaperPull Server's Status tab, both spreadsheets and the sample work.**
  The server image carried only one of the scripts the panel runs from its
  tools folder, so the Status tab said status.py was not found, neither
  spreadsheet would build and "see the sample" failed. The image now
  carries all of them, and a test fails when the panel names a script the
  image leaves out.
- **PaperPull Server no longer looks in the data folder for the panel's own
  scripts.** With its own copy missing, the panel went on to look for the
  Status tab's and the spreadsheets' scripts in the data folder, which is
  often a shared folder other people can write to, and ran what it found
  there inside the container. On the server it now looks only beside the
  panel. The desktop still looks beside the installs too, where older
  layouts kept them.
- **A spreadsheet with nothing to put in it is no longer written.** Asked
  for the purchases spreadsheet with no order history, or the transactions
  workbook with no statement on disk, the panel and both export commands
  wrote an empty file and then said there was nothing to export. That
  empty file took the place of the last spreadsheet built. Now nothing is
  written, and the last one stays as it was.
- **A Robinhood history moved with `--minimal` no longer downloads tax
  forms and crypto statements again.** Robinhood knows a tax form it saved
  before the year was read, and a crypto statement saved under its old key,
  by fields the history tool's `--minimal` export left out. These are the
  undated key, the page that listed the document, its category, date, title
  and account, and the saved file's digest. So the new computer fetched
  those again, and could save the individual statement a second time as the
  crypto one. The export now carries those fields for Robinhood alone,
  a second person's Robinhood history included. They name no person and no
  account number, and Robinhood's record keys already hold most of them.
  The skip checks of the other apps read nothing that `--minimal` leaves out.
- **A history moved with `migrate.py --minimal` no longer downloads again a
  statement saved under a key without the account's last four.** Until
  0.34.0 a document's key cut its account to forty characters, and until
  0.17.1 Chase's left out the last four of any account. The 45 apps whose
  key carries the account move such a record to the key that keeps the
  last four when they load, rebuilding it from the record's own date,
  title, account and kind (and for Capital One and Schwab its place among
  same-day statements). `--minimal` left those out, so on the new computer
  the record stayed where it was and the statement, listed under its whole
  key, was fetched a second time. It reached an install that no version
  since had opened on the old computer. A record still under such a key
  now keeps those fields, every other record carries what it did before,
  and importing a file made now over a history an older `--minimal` file
  already moved gives those records what they were missing.

## [0.46.0] - 2026-10-11

Three new apps. Interactive Brokers is the 63rd, with monthly Activity
Statements from tylerverry, and Coinbase, with monthly statements and tax
documents, and Optum Bank, with HSA statements and tax forms, come from
JasperDale420, each reviewed and repaired before it went in. Robinhood
takes its documents page by page and reads the retirement page, also
from JasperDale420. A checkout runs every app on one environment that
setup-all builds once (#65). A document whose Download the site has
turned off is left for review while the run goes on, nothing more is
pressed after a press that may have been made, and a control a press
reveals is pressed only where that press put it. Download again keeps a
saved record when it saves nothing, Capital One and Schwab take each
document by its own id, and Rename leaves a shared file its name and
keeps each file named for the id it was saved under. PaperPull Server no
longer runs a Mac's hidden copy of an app and clears the browser locks a
stopped container left.

### Added
- **Interactive Brokers, the 63rd app, monthly Activity Statements
  (#77).** The Statements page's own Activity Statement dialog, with
  Monthly chosen, offers every month back to the one the account opened,
  and each month is saved by pressing the dialog's Download PDF button once
  with that month chosen, after its label passes the guard. Nothing else is
  pressed, and nothing is asked of Interactive Brokers directly. A file
  whose own name says it is for another month or another account is not
  taken. Sign-in lands on the person's regional domain, and .com, .co.uk
  and .ie are known. Contributed by tylerverry, whose full run saved 60 of
  61 months back to 2021, the last on a supervised retry. Before merging,
  a dialog that would not open was made to stop Discover where it used to
  note an empty list as read, the account number is read from the whole
  page, paper and advisor numbers included, so a notice above the heading
  no longer files every month again under a bare "Account", a page that
  names no account stops Discover once the months are filed under one, and
  a lookalike address is never suggested for the list of domains.
- **Coinbase, monthly statements and tax documents (#72).** Each complete
  month's statement on the Statements page is saved by pressing its row's
  own PDF button once, after its label passes the guard, on a page loaded
  afresh for it, and the download is taken only from Coinbase's statements
  bucket. The 1099-DA and the other tax forms, and the pregenerated gain
  and loss reports, come from the list calls the Taxes page makes and are
  fetched by their short-lived links with nothing pressed, so the page's
  own mark-read and mark-downloaded calls never happen. Contributed by
  JasperDale420, whose full run on a retail account saved 66 statements and
  2 tax documents, every one a valid PDF. Before merging, a statement is
  filed only when its own text names its month more plainly than the month
  before or after, and a download that could be another press's is never
  taken. The statements list is called whole only when it reaches the
  month of the account's first transaction. A second tax form of one year
  no longer changes the first form's key, the 1042-S is known, and a tax
  list that names another year or has a page left unread stops the
  listing. Diagnose presses nothing, and the app signs in on port 9286.
- **Optum Bank, HSA statements and tax forms (#73).** Each product the
  Forms & documents page links a statement for is read from its own
  statements page, the newest statements from their links, the older ones
  from the options of the page's date selector, and the 5498-SA and
  1099-SA from their links. Each is fetched by its own address on the
  member host with no redirect followed, and no control is pressed
  anywhere. A tab that lands on a HealthSafe ID sign-in page stops the
  run, and an Optum pilot exits as a run that stopped unless every
  document it chose was saved as a valid PDF. Contributed by
  JasperDale420, whose full run saved 21 statements and the 5498-SA.
  Before merging, a document was made to carry its product in its key,
  so a second product appearing later no longer downloads the first
  one's whole history again, and an archive saved before keeps its keys.
  A corrected form listed under the title of the one it corrects is now
  saved too, a placeholder in the date selector no longer stops the list,
  a tax form whose title names no year stops it, and links to a product
  that has no statements page no longer stop Discover. More than one
  product is untested.

### Changed
- **A checkout is set up as one environment, not one in every app folder
  (#65).** setup-all made a venv in each of the 62 app folders, about 400
  MB apiece on a Mac and well over 20 GB in all, though every app asks for
  the same few packages. It now builds one, `gui/.venv`, the control
  panel's own, with every app's requirements read in one pip call and the
  shared core. The panel, `paperpull`, and each app's login and
  review_names files run an app on its own `.venv` when it has one, and
  otherwise on `gui/.venv` once that can import what an app needs. Until
  it can, they say to run setup-all, where the panel used to send each
  provider to a setup of its own. An app that already has a `.venv` keeps
  running on it, and setup-all names those apps, so an older checkout gets
  the space back by running setup-all again and then deleting each app's
  `.venv`. An app's own setup file still gives it a venv of its own. Asked
  for by appchamp.

### Fixed
- **Robinhood took half a minute per statement, and read no retirement
  statements at all (#74).** Documents are now taken page by page, the
  individual page's first, then the retirement page's, then crypto, then
  tax, newest first within each. Taken by date across pages, each one
  opened and expanded a different page than the one before. A page
  already open that still shows a document's control is not opened again,
  and the control is found in one pass in the page, where the browser was
  asked about each of up to four hundred controls in turn. The tab is
  brought forward once for each page opened, since a press waits on
  animation frames a background tab does not get. The retirement
  statements page is read as well, and an account with an IRA got none of
  its statements before. It is read and pressed on only at its own address
  and only when a heading of its own names a retirement account. A
  retirement statement whose file is the individual statement of the same
  month goes to Manual Review as a wrong document, and a retirement page
  that lists one title twice, as two IRAs might, is not read yet, and the
  run says so. Contributed by JasperDale420, whose account went from 22 to
  26 seconds a document to 4 to 6, with 136 of 139 documents saved and the
  other three offered by Robinhood only as HTML. Before merging, a
  statement's control is pressed only when its own label or its own card
  names it, where a page of sibling links could have January's pressed for
  February. A prompt over a page kept open stops the run as a sign-in
  check does. A View More that cannot be pressed, or a page that would not
  open, leaves the list noted as stopped for Resume, and `--max-docs` takes
  the newest documents again.
- **USAA's Discover could miss most of the list from 0.26.0 on.** USAA's
  documents page asks USAA for its whole list as it loads, and the app
  reads the list from those answers. Since 0.26.0 the app opened the page
  and waited on it first, and only then listened, so it heard only the
  answers that came later, often none, and still called the list read.
  Pilot and Run All then worked only through what was heard and what an
  earlier version had listed. The app now loads the page while it listens,
  and a page whose list never arrives stops the run rather than pass for
  an empty one. Proven against a made-up page built from the July probe of
  USAA's own, not yet run against USAA.
- **USAA and Armed Forces Mutual know their documents page by what it is,
  not by how many rows it shows.** Each counted the page as open only once
  more than one row showed, and Discover stops on a page that will not
  open, so an account with one document, or none yet, could stop every
  Pilot and Run All. USAA's page is now known by its address and its My
  Documents heading or its table's header row, and Armed Forces Mutual's
  by its documents table's header row, or right after the app loads its
  address by its MY DOCUMENTS section, since its other sections show at
  the same address. A page that never drew still stops the run. On Armed
  Forces Mutual the header row and the membership letters already counted
  as rows, so only an account with no document yet and no letters stopped
  there.
- **USAA's download by row loads the list afresh before it presses.** It
  is used for a record with no document id. Since 0.26.0 it kept a page
  already showing, which at a document's own address still shows that
  document's PDF, so the capture could save it under the next document's
  name.
- **A receipt saved since its page last showed nothing starts its days
  again.** The days a receipt page showed nothing stayed on the purchase's
  record after a run saved something for it. That mattered where the save
  did not finish the purchase, a copy put aside in Manual Review, or a
  Target order with one invoice saved and another still missing. One more
  day of an empty page then set the purchase aside for review, as though
  its page had shown nothing three days running, and Target's missing
  invoice was never asked for again. Any save for a purchase now lets those
  days go, in all fourteen receipt apps.
- **Anthem names its member documents, ID cards and letters as Rename
  does.** Anthem takes these from lists of their own, apart from its EOBs,
  and named each file from the row its list gave rather than from the
  record written down for the file, which is where a name pattern and
  Rename find the document's id. So under a File names pattern with
  {number} in it, these files were saved without their id, and Rename
  offered to add it to every one. When two of them wanted one name, as two
  letters of one subject on one day can, the second was saved with " (2)"
  and Rename offered it the end of its id. Each file is now named from the
  record written down for it, and the second of two files of one name is
  told apart in words rather than by the end of an id, which read as
  " rmal1" for a second ID card. A second ID card of one member and kind
  adds " No. 2", a 1095-B listed under both of its type codes adds
  " type 1095", a letter the end of its message's own id, and an EOB of a
  claim that has two of one kind on one day adds its kind and Anthem's own
  number, as in " EOB 1", where it added " EOB1" before. A file saved
  before keeps its name until Rename is run, which offers the new name in
  a preview first. The old copy Download again leaves of such an EOB is
  read by its " EOB1" too and offered " EOB 1", never " (2)".
- **A receipt already saved keeps its record when Download again saves
  nothing.** Download again takes every purchase in scope again, the ones
  saved before included. In every receipt app, an attempt that ended with
  no copy of its own rewrote the saved receipt's record, at a page that
  would not open or was not the purchase's, with no receipt on the page, a
  control it could not read or an error, or with a copy that failed its
  check and was put aside in Manual Review. The record then named no file,
  or the copy put aside, with the attempt's summary and a state of Needs
  Manual Review, No Receipt Available or Failed, and after a wrong page
  that page's own total and items. Kroger also gave its purchase list the
  store the attempt read, which Rename reads for a receipt saved before
  0.41.0, and Walmart gave the record a date the attempt's page showed
  outside the dates of the run. Nothing was fetched again because of it.
  But the Pilot report showed the failed attempt in place of the saved
  receipt, the File names page's preview showed the copy put aside or left
  the receipt out, Rename named the saved file for the failed attempt,
  after a wrong page for another purchase, and Review Names no longer took
  the record for the saved file's. Apple's and Uber's next Discover also
  read the purchase from the site again, as one not yet settled. Now an
  attempt changes nothing in a saved receipt's record until it has saved
  a copy of its own. The record's notes say how it ended and that only
  another Download again tries it, since a plain run never does, and the
  Pilot report of that run lists it among what needs attention. Target
  also took the saved mark off an order when a Download again could not
  save every one of its invoices, so every later run walked it again. It
  now stays saved, the invoices that attempt did save are remembered so
  none is saved twice, and a Download again of the same dates fetches the
  rest.
- **A document already saved keeps its record when Download again saves
  nothing.** Download again takes every document in scope again, the ones
  saved before included. In every document app, an attempt that ended with
  no copy of its own, at a site that would not hand the document over, an
  error, a session that ran out or a copy that failed its check and was
  put aside in Manual Review, wrote the document as its listing gives it
  over the saved document's record. The record then named no file, or the
  copy put aside, with the attempt's state, and no longer said the
  document had been downloaded. So the next plain run fetched it again and
  saved a second copy beside the first, or brought back one deleted after
  importing it elsewhere. Where Dominion found a bill no longer online or
  Wealthfront found no download control, the record said the saved
  document had none. Capital One and Schwab also wrote the id a later
  listing gave over the one the file was saved under. Now an attempt
  changes nothing in a saved document's record until it has saved a copy
  of its own, as with receipts. The record's notes say how it ended and
  that only another Download again tries it, and the Pilot report of that
  run lists it among what needs attention. Anthem's member documents, ID
  cards and letters, saved apart from its EOBs, are kept the same way.
  Where the saved file had been deleted and the attempt left its own copy
  under that name, a copy that failed its check and could not be moved to
  Manual Review, the record no longer vouches for it, in receipt and
  document apps alike, and the next plain run fetches it again. An American Family bill handed another
  bill's statement sends both bills to Manual Review, its own copy saved
  before included, as a first run does.
- **Rename leaves the name of a file two purchases or documents name, in
  every app.** Deleting files once they are imported elsewhere frees their
  names, and a later purchase or document of the same day and summary is
  saved under one. When the later one's rows never reached the index, open
  in Excel through its run perhaps, its record and the deleted one's both
  named the file, and Rename named it for the deleted one, a Walmart
  receipt "2026-05-14 Unsure Purchase.pdf" offered "2026-05-14 Walmart Lamp
  Receipt.pdf". A file the records of two purchases (two order numbers,
  Target's invoices of an order included) or of two documents name now
  keeps its name, whichever of the two kept its rows. When the deleted
  one's rows were the ones gone, Rename used to name such a file for the
  later one, rightly, but the records cannot tell that case from the
  other, so it keeps its name there too. Robinhood's and Newrez's own
  records of one document under two keys still count as one.
- **Ally's Discover heard no list for an account with one year of
  statements.** Ally's statements page asks Ally for a year's list as it
  opens and again when its year picker moves, and the app reads the list
  from those answers. It began listening after Discover had opened the
  page, and by the app's own notes picking the year already shown asks for
  nothing, so with one year in the picker it heard no list at all, and
  with the page left on its oldest year it never heard that year. Either
  way the list was called read. With nothing heard it read the rows
  instead, which took the statements of one date that read alike as one
  and kept no document id. Every year is now picked from another one, and
  the last pick's answer is waited for. With one year in the picker the
  list is drawn again while the app listens, through the page's Tax Forms
  tab and back, and only when that brings nothing is the statements
  address loaded again. A list that never arrives, or a year picker that
  could not be read, stops the run rather than pass for an empty list.
  Proven against a made-up page, not yet run against Ally.
- **Capital One and Schwab take each document by its own id, never by its
  place in the list.** Two documents of one day sharing a type, a title
  and an account, two buys of one fund in a Schwab account for instance,
  were told apart only by where each stood in the provider's list. When
  the list came back in another order, or with a new one ahead of one
  already saved, the saved one was downloaded again in the other's place
  and the other never was, and no later run asked for it. Each document
  is now found by the id it was listed and saved under. Where the
  provider's ids change and cannot say which of two was saved before, the
  one not yet saved is marked for manual review rather than guessed at.
- **Review Names leaves out a file two purchases name, and keeps the name
  a file already has, in every receipt app.** Deleting receipts once they
  are imported elsewhere frees their names, and a later purchase of the
  same day and summary is saved under one. A new name typed for the older
  purchase's row then renamed the later purchase's file and left the later
  purchase's rows and record naming a file that was gone. A row whose file
  another purchase's index rows or record name as well, a Target invoice
  included, is now left out of the review, which says how many. Typing the
  summary a file already has moved it to "... (2).pdf", and the next
  Rename offered to move it back. The file now keeps its name, or takes the
  new case when only the case changed, and counts as reviewed.
- **Review Names keeps the "(1 of 2)" of an order split into several
  invoices, in every receipt app.** Target and Amazon save each invoice of
  a split order with its part at the end of its name. A new name typed in
  Review Names left the part out, so the first invoice was renamed as
  though it were the whole order, and no Rename could put it back, since
  Rename reads the part from the file's own name. The new name now keeps
  the part, as Rename does.
- **Putting an overlay away never presses Close account or Sign out.**
  Eleven apps put a cookie banner or a survey away by pressing any
  visible button whose name began with close, dismiss, no thanks or not
  now, after reading only its text against the app's own list, so a
  "Close account" button, or one named Close whose text or title said
  "Close my account" or "Sign out", was pressed. Apple Card never read a
  button's title, T-Mobile checked nothing, Verizon's reached "Close menu
  and sign out", and Costco closed its receipt dialog through any button
  whose text held Close. All of them, and American Family's, which was
  already careful, now go through one core helper. It presses only a
  button whose every label says close, dismiss, no thanks or not now and
  nothing else, never one in a dialog named for closing the account or
  signing out, and the core's shared list refuses closing an account and
  signing out in every app. Golden 1's history dialog Close reads every
  label too.
- **Nelnet reads every label a control carries.** The part of a label
  after " with subject " went unread as the document's title, and the
  labels joined after it with it, so "Download document with subject
  Notice | Make a payment" passed the guard. Each label is now judged on
  its own.
- **Nothing more is pressed after a press that may have been made.** When
  a press through the page raised, twelve apps went on to press a control
  it revealed, AT&T pressed the bill's View/print PDF next, and E*TRADE
  pressed the document's other controls, its own link a second time
  among them. Each now presses nothing more, waits as long as ever for
  what the press brought, and otherwise leaves the document for another
  run.
- **A receipt set aside stays set aside after moving to another
  computer.** The history tool's `--minimal` export left out the days a
  receipt page showed nothing, and an import into an install that already
  knew the purchase left them behind with either export. On the new
  computer Meijer then asked again for every receipt set aside, and the
  other receipt apps said each one was already completed instead of why it
  was skipped. Both now carry the days.
- **A run scoped to part of the history no longer counts the whole list as
  read.** A Discover, Pilot, Run All or Resume with a year or dates set,
  as the panel's Scope row passes them, noted the list as read to its end
  once its part was, in every app but Best Buy, Apple and Uber. So after
  a run that stopped partway through the whole history, one scoped run
  let the next unscoped Resume finish clean with the rest never read. A
  scoped run that reaches the end of its part now leaves things as the
  last unscoped run left them, so a list that stopped stays unfinished
  until a run with no year or dates set reads all of it, and Resume says
  to run one. A list read whole stays whole through scoped runs, even
  after one of them stops. Best Buy, Apple and Uber, which counted a run
  for a year or from a start date as unfinished and so read the list
  again on every Resume after one, now do the same, so keeping a scope
  set after a whole listing costs no second reading. A scoped run that
  stops is still a run that stopped.
- **Target fetches an invoice put aside again once its copy is deleted,
  and no longer saves a renamed invoice twice.** An online order with no
  store receipt is saved as its invoices, and one that fails its check is
  put aside in Manual Review, as a delivery driver's tip always is, since
  it names no item. When every invoice of an order was put aside,
  deleting the copy the order's record names asks for the order again, as
  it does for a receipt put aside. The next run counted the deleted copy
  as still on file, so it went through the order's invoices on Target,
  saved nothing, and wrote the order down as needing review again under
  the deleted file's name. Every run after did the same, adding a row to
  the receipt index each time, and so did a copy that no longer opened as
  a PDF. Now that invoice is fetched and checked again, as a receipt put
  aside is, and the order is then left alone while its copies are there
  and open. A tip fetched again is put aside again. An invoice that was
  kept still counts as saved after its file is deleted, unless Download
  again asks for it. Review Names and Rename gave an invoice's file a new
  name while the record's list of the order's invoices kept the old one,
  so Download again took the renamed invoice for missing and saved it a
  second time. It is now found under its new name.
- **A control a press reveals is pressed only where that press put it.**
  When pressing a document's own control brought nothing, American
  Family, Apple Card, AT&T, E*TRADE, Golden 1, Nelnet, Newrez, SBA, SMUD,
  State Farm, Verizon Mobile and Wells Fargo pressed a control the press
  had newly shown whose words finish a download, such as Download PDF or
  Save PDF, wherever on the page it was. A list drawn anew after the
  press, or a panel opened for another row, could show another document's
  Download, and its PDF would have been saved under this document's name.
  Now such a control is pressed only inside a dialog or menu the press
  opened, or beside the pressed control in a part of the page that held
  nothing else to press, and only while the pressed control is still on
  the page it was pressed on. Otherwise nothing more is pressed, the
  document is left for the next run, and download-attempt.json says where
  the control sat. AT&T's Regular PDF menu is still taken wherever AT&T
  draws it, since that was never recorded, but only while Download PDF is
  on the page, and the trace now says where it sat. Once the Download PDF
  pressed has left the page, AT&T presses nothing more for that bill,
  where it used to press whatever View/print PDF was showing then.
- **A document whose Download the site has turned off no longer stops
  every run there.** Most apps find a document's Download by its role and
  its name, which finds a grayed out one too. Playwright waited for it to
  turn on, eight seconds in most apps, and then the run stopped, and every
  later run stopped at the same document, so nothing after it was
  downloaded. Now such a control is not pressed, nothing more is pressed
  for that document, and the document is marked for review and tried again
  on the next run while the run goes on. That holds in the fifteen apps
  that press a document's own control through the core (American Express,
  American Family, Apple Card, AT&T, E*TRADE, Golden 1, Nelnet, Newrez,
  PG&E, SBA, SMUD, State Farm, Vanguard, Verizon Mobile and Wells Fargo),
  for a control grayed out the way Bootstrap and Material UI draw one too.
  The run still stops at a turned off control that something covers, at
  one that is not a document's own (a page picker, a section heading, a
  dialog's Download, ADP's View statement), and at one AT&T or E*TRADE
  finds turned off after pressing another control for the same document,
  since that press may still bring the PDF. Playwright waits as long as it
  always did, so a control the page turns on in that time is pressed as
  before.
- **`paperpull list` in the installed app no longer marks every app as
  needing setup.** It marked each app with no `.venv` of its own, which in
  the installed app, whose one Python carries everything, was all of them.
  It now marks only an app that nothing can run.
- **The Mac sign-in and setup files no longer print a stray caret.** Nine
  of them showed the caret Windows needs before & and >, as in
  "Statements ^& Activity".
- **The Windows sign-in files of ADP, AmFam, AT&T, Nelnet and Wells Fargo,
  and AT&T's setup, print their whole instructions.** A bare & on a line
  they print ends the line in Windows, so "Open your Statements &
  Documents page" stopped after "Statements" and was followed by
  "'Documents' is not recognized as an internal or external command", and
  AT&T's title and steps said the same of "T". Each & is now written the
  way Windows prints it, as PG&E and M&T always were, and a check reads
  every Windows file the repository ships for another such line.
- **Every app's next step names a command that still exists.** The
  run_pilot.bat, diagnose.bat and resume.bat files went when
  `paperpull <app> <command>` replaced them (#23), and 31 login.bat
  banners, 48 setup.bat files and 51 messages the apps print still told
  the person to run them, eight of the banners as "Tell Claude you're
  signed in". Each now names `paperpull <app> pilot` or
  `paperpull <app> diagnose`, a login.bat started for a second person
  shows the `--account` to add, and a message the apps print says to
  run the diagnostics, the pilot or Resume. The Mac sign-in files, made
  from the Windows ones, gain the step they lacked and say
  `./paperpull`, as a checkout on a Mac runs it. The editable document
  rules of ten apps point at the same command. A census over every
  launcher, doc, rules file and script an app ships now fails on a
  deleted launcher's name, where it read only the README and COMMANDS.txt
  files.
- **A File names pattern with {number} keeps a statement's file named for
  the id it was saved under.** Capital One and Schwab write down the id
  each new listing gives a statement they already know, and Rename named
  the file for the newest one. Schwab says its ids are not stable from one
  listing to the next, so under such a pattern a Rename after a Discover
  could offer to rename every Schwab file, while the File names page's
  preview showed the id as saved. And two statements of one day,
  one title and one account are told apart by their place in the list, so
  when the list came back in another order each took the other's id, and
  Rename offered to name each file for the statement it does not hold.
  Rename now reads which document a file holds, its order number or id,
  from the record written when the file was saved, while a summary or an
  account the app has learned to read since still reaches the name. A
  statement downloaded today is named for the id today's listing gave it,
  as before.
- **Ally's Rename keeps the name a statement's PDF gave it.** Ally names
  each statement after the accounts and the addressee its PDF shows, but
  Rename read the list's description over it and offered every such file
  the list's less telling name back, "Account Statement - Trust" in place
  of "Account Statement - Savings + Checking (Pat Sample)", which Apply
  would have taken. Rename now reads those from the record as the file was
  saved. A second copy of one statement to one person is told apart by the
  end of its Ally id as other second copies are, not by " (2)". A statement
  listed without Ally's id, as when the list is read from the page, is no
  longer taken again on every run. One taken that way before this version
  is taken once more, beside its first copy, and then no more.
- **The next Rename finishes a file left under its temporary name.** A
  file of a swap that Rename could neither finish nor send back, with its
  row in the index and its record naming it under a name ending
  ".renaming", was left out of every later Rename as not a PDF the app
  holds. It stayed there until it was renamed by hand, and then the index
  named a file that was gone. Rename now takes such a file, in a folder
  the app files documents in and never a link, as one of its own, and
  gives it the name the app would give it today.
- **Login on the server no longer runs a Mac's hidden copy of an app
  (#76).** A Mac writing to a network drive leaves a hidden "._" file
  beside every file it writes, "._ally_docs.py" beside ally_docs.py, and
  the panel took whichever sorted first as the app. On a server whose apps
  sit on such a drive, Login ran the hidden copy and stopped with "source
  code cannot contain null bytes". A hidden file is never taken as an app
  now, in the panel, the server and `paperpull`.
- **PaperPull Server clears the browser locks a stopped container left
  (#78).** Chrome marks a profile in use with a lock naming the computer
  and the browser's process. A sign-in browser still open when the
  container stopped left its lock behind, and once the container started
  again, with new process numbers, or was made anew from a newer image,
  Chrome took that profile for one in use elsewhere and never opened the
  debugging port, so Amazon's Login said no browser would open while every
  other app worked. The server now clears those locks as it starts, before
  any browser can open.
- **PayPal waits for a business report that is still being made (#61).**
  A report asked for with Create Report shows in the list as creating
  until it can be downloaded. The app read that status as one it could not
  read, so every run until the report was ready counted it as a failure
  and wrote a failure file. It is now counted as not ready yet, and a later
  run takes it once PayPal finishes it. Create Report itself is still never
  pressed.
- **Meijer presses a receipt's link the way the other apps press theirs
  (#42).** The receipt link on a purchase's row was pressed with a bare
  click given five seconds. On the last receipt of a long In-Store tab
  that click ran out of time on every run, and the run said only that the
  press brought no PDF. It is now pressed through the same place in the
  core as every other app's controls, given the same time, and never
  pressed twice. Something drawn over the link stops the run and says
  what it was, with the failure file written.

### Security
- **M&T presses a year heading only when nothing covers it, and once.**
  M&T's statements list opens one year at a time, and the app pressed each
  collapsed year's heading through the page with nothing checking what was
  drawn over it, since the core could check what covers a control only in
  a page's main frame and the list sits in a frame. The core now reads a
  control inside a frame in that frame, then checks that the frame is the
  thing on top in the page at the point to be pressed, as Playwright checks
  before its own press. Right after the press, unless the control heard the
  browser's own click at that point, the point is read once more, so a
  loading cover put up once the press went through does not stop the run.
  M&T presses each heading that way, with Playwright's own press.
  Something over a heading, inside the frame or over the frame in the
  page, stops the run before anything is pressed, and so does a heading
  that cannot be checked, with the reason said in PaperPull's own words and
  the failure file written. The words held to the forbidden list are now
  those of the heading pressed, where a second call used to find the
  heading again, and a heading pressed once is not pressed again, the same
  element or one the page draws anew with the same id and words. The
  heading is gone from the reviewed list of presses made through a page
  script, where two links PG&E makes itself to save a PDF remain.

## [0.45.0] - 2026-10-07

A receipt whose page did not show it is fetched on the next run, in
every receipt app, after a tester's Kroger receipts were skipped as
completed with no file anywhere, and the receipts earlier versions gave
up on that way are asked for again. Nelnet is the 62nd app, with student
loan statements, the 1098-E and notices, and Vanguard presses Show More
for its older statements, both from tylerverry. Rename names each file
for its own record and as its download did, renames only what its app
holds, and puts back a swap it cannot finish. Twelve apps and ADP press
through the page only when nothing covers the control, Review Names
leaves a receipt that failed its check to be fetched again, and Pilot,
Run All and Resume no longer finish clean after a page or a list they
did not read.

### Added
- **Nelnet, the 62nd app, student loan statements, the 1098-E and notices
  (#69).** The billing statements and notices in Inbox & Statements, read
  from the page's own list while it is paged, each saved by pressing its
  own row's Download button once its label passes the guard, and the
  1098-E from Tax Info, printed from the page after its button is pressed,
  since the form is not a file. Notices are named by their own subject.
  Contributed by tylerverry, whose full run saved all 47 documents, 41
  statements back to 2019, the 1098-E and 5 notices, every one a valid
  PDF, and whose second run downloaded nothing. Before merging, the 1098-E
  pressed was made the one for the form's own tax year, since an older
  year's form asked for again would have been the current one saved under
  the older year, an inbox notice that names the form is taken from its
  own row rather than Tax Info, and a page of the list that cannot be
  reached stops the listing, where it used to end it as though the list
  were whole.

### Fixed
- **A run whose documents page would not open no longer finishes clean.**
  In twenty document apps, when Discover could not open the documents
  page, even after checking the session, it said so and returned. Pilot
  then said there was nothing in scope to pilot, or worked through
  documents an earlier run had listed, Run All did the same, and the panel
  called the run finished although nothing had been listed, while a
  Resume after it said the list had not been read. Now the run stops
  there, as a run that stopped. Anthem's Run All still downloads the
  member documents, ID cards and letters, each from a list of its own,
  and stops after them. Discover and Wealthfront count the page as open
  only once it lists something, and AAFMAA and USAA once it shows more
  than one row, so an account with nothing posted yet stops each run until
  its documents come, and they now say so. A Discover account that has
  moved to Capital One still ends its listing with the notice that there
  is nothing to fix, and a Resume after it no longer says the list was not
  read. The twenty are AAFMAA, Affirm, Ally, Anthem, Capital One, Charles
  Schwab, Chase, DFAS myPay, Discover, Fairfax Water, Fidelity, M&T Bank,
  Navy Federal, NetBenefits, PG&E, TSP, U.S. Bank, USAA, Vanguard and
  Wealthfront.
- **Chase and Ally find their statements page open on a year with no
  statement in it yet.** The page opens on the current year, Chase's with
  one card's statements showing, and the check of the page counted the
  rows on screen. So from New Year until that year's first statement, and
  on Chase all year when the card shown had no statement in it, the page
  read as one that never opened. Discover listed none of the years before
  it, and a download gave up. The page is now known by its own address
  and its year picker, and on Chase by a card as well, whatever year it
  shows. A Chase tab left on the tax documents or year-end summaries no
  longer passes for the statements, which it did whenever it showed a
  row.
- **A dry run of Resume in Robinhood, USAA or Wealthfront no longer needs
  the browser.** Each asked for its tab before the first document, so even
  a dry run of Resume, which reads no list and downloads nothing, attached
  to the browser and stopped when it was closed. They now ask for it only
  once a document is about to be downloaded, as every other document app
  does. A dry run of Pilot or Run All still opens the browser, since it
  reads the list there.
- **Rename no longer gives one bill's file another bill's account.**
  Rename, and the File names page's offer to rename after a pattern
  change, name each file from the record the app keeps for it. That record
  was found by the statement's date and title, and every record of one
  date and title was merged into one. American Family titles each bill's
  statement "Account Statement" and its date, so with two bills that each
  had a statement of one day, a Rename preview offered to give the first
  bill's file the second bill's account and a " (2)", and after a pattern
  change both files were named for the second bill. Nothing was deleted
  and the index kept each bill's own summary, but the file names said the
  wrong account. Citi titles each card's statement the same way, so two
  cards' statements of one day did the same. Now a file is matched to the
  record that names that very file. Its date and title are asked only
  when no record names the file, and then only when a single document has
  that date and title and names no file of its own. A file that two rows
  of the index give to two documents keeps its name. That happens when a
  file deleted after it was imported elsewhere frees its name for a later
  download, and Rename used to name the later file for the deleted
  document. A file that still cannot be placed is named from its own index
  row, which can leave out what a record would add but never puts in
  another document's. The index and the run state follow a renamed file
  however its path was written.
  Ally, Anthem, Capital One, Chase, Discover, FedEx, M&T Bank, myPay,
  Navy Federal, Schwab, Stripe, UPS, USAA, U.S. Bank and Vanguard keep an
  id from the provider's page in a statement's record when there
  is one. Rename looked such a record up by that id, which an index row
  does not carry, so it never found one, and a naming pattern's account or
  number never reached a file those apps had already downloaded. Now it
  does.
- **Rename no longer offers " (2)" to a statement its download told apart
  by an id.** When two statements of one day and one summary would share
  a name, a download saves the second with the last six characters of the
  id its app keeps for it added, as in "2026-09-12 Chase Monthly Statement
  OC2222.pdf". Rename, and the File names page's offer to rename after a
  pattern change, looked for that id in the file's row of the index, which
  never has one. So under the very pattern the files were saved by, a
  preview offered to rename the second statement to "2026-09-12 Chase
  Monthly Statement (2).pdf". It happened in the fifteen apps that keep an
  id from the provider's page in a statement's record, Ally, Anthem,
  Capital One, Chase, Discover, FedEx, M&T Bank, myPay, Navy Federal,
  Schwab, Stripe, UPS, USAA, U.S. Bank and Vanguard. Rename now
  tells a file apart by what its download added, read from the record
  written when the file was saved, so a later listing that gives a
  statement another id, which Capital One, Schwab and Vanguard write down,
  does not move it. After a pattern change that gives both statements one
  name, the second keeps what its download added. A PayPal business
  statement keeps the first day it covers, which its download adds when
  another statement ending on the same day has the name. A statement saved
  with " (2)" before its app added the id to a taken name is offered the
  end of the id its record kept instead.
- **AAFMAA tells a second file of one name apart by its policy, never by
  "cument".** AAFMAA gives a document no id, and what its listing kept as
  one was the name of the View control on the document's row, which ends
  in "cument" for every document and names only the row's place on a page
  of the table. So when a file already had a document's name, the second
  was saved as "... cument.pdf" and a third as "... cument (2).pdf", which
  said nothing about which document either was, and a file name pattern
  with {number} in it wrote the control's whole name into every file name.
  A download now adds the document's policy number, which is part of what
  the app knows the document by. The summary in AAFMAA's names already
  carries the policy, so under the default pattern two files wanting one
  name are two documents of one policy and day, and the second is told
  apart by " (2)". The policy number tells two policies apart under a
  pattern that leaves the summary and account out. AAFMAA's records drop
  the control's name the next time the app starts, so {number} is empty
  for AAFMAA from then on, and the File names page counts it as a field
  AAFMAA never fills. Rename tells a file apart the way its download does,
  so it offers a file already saved with "cument" in its name the name a
  download gives it today, in a preview first, as for any other rename.
- **Rename no longer offers " (2)" to the old copy Download again leaves.**
  Download again saves the statement it takes again beside its first
  copy, as "2026-09-12 Chase Monthly Statement OC2222 (2).pdf", and the
  statement's record names the new copy from then on. No record names the
  old copy, and with two statements of that day and title Rename cannot
  tell whose it is, so it told the old copy apart by nothing, and a
  preview offered to rename "2026-09-12 Chase Monthly Statement
  OC2222.pdf" to "2026-09-12 Chase Monthly Statement (2).pdf". The old copy
  now keeps the end of the id in its name when that is what exactly one
  statement of its date and title would add, and is still named from its
  own row, never for that statement. After a pattern change it carries
  that ending into its new name, unless the name would have to be cut to
  fit the folder's limit, where it is told apart by a number as before. It
  happened in the apps that tell a second statement apart by an id, and
  for PayPal's business statements, told apart by their first day.
- **Every receipt app's Resume reads the purchase list again after a run
  that stopped while reading it.** After a Discover, Pilot or Run All that
  stopped while it read the purchase list, at a sign-in, a check or a
  browser that had been closed, Amazon, Costco, eBay, Gap, GitHub, Lowe's,
  Meijer and Walmart carried on from the purchases already found, said all
  of them were complete, and the panel called the run clean, although the
  rest of the history was never looked at. Their Resume now reads the list
  again before it downloads anything, as Target's does, and when the list
  does not come this time either, the run stops there as one that stopped,
  with the purchases it knows left for the next run. Apple, Best Buy, Home
  Depot, Kroger and Uber already read their lists again first, and still
  go on with the purchases they know when a list does not come. On an
  install that had never listed anything, all fourteen said the same clean
  line, and now Resume says no purchases have been listed yet and stops,
  without asking for the browser, until a Pilot or Run All reads the list.
  Each receipt app now notes in `last-listing.json`, as the document apps
  do, whether its last listing read the whole list, in place of the
  `.discovery-unfinished` file six of them kept, so an install of one of
  those six whose listing stopped under an earlier release still has its
  list read again by its first Resume. A Resume after a whole listing, or
  on an install from before this release that has listed purchases,
  finishes as it always did.
- **Review Names renames only a receipt the app holds, and the CSVs keep up
  with every rename.** It offered every receipt marked for review, and a
  purchase recorded with no receipt file, one with no printable receipt for
  instance, has an empty path, which reads as the folder the app runs in.
  Typing a new name for one had the app try to rename that folder. Windows
  refuses, since the folder is in use, and so do macOS and Linux, so the
  review stopped with an error, and the receipts renamed before it kept
  their new names on disk and in progress.json while both CSVs still named
  the old files. Closing the console window partway did the same to every
  rename of that review, since the CSVs were written only at the end. A row
  naming a file outside the app's folders would have been renamed as well.
  Now only a PDF in a folder the app files receipts in is offered, Manual
  Review included, each file once, and the review says how many rows it
  left out. A rename that fails is said and leaves that receipt as it was
  while the review goes on. Each rename goes into both CSVs as it happens,
  so they name the files as they are on disk however the review ends, and
  into every index row of that purchase naming the file, since Target
  archives from before 0.42.0 hold two for most invoice orders. A receipt
  whose file is gone is not offered either, where a new name for it used
  to change the CSVs alone. Every receipt app now runs the same Review
  Names, so this holds in all fourteen.
- **Review Names no longer keeps a receipt that failed its check from being
  fetched again.** A receipt whose PDF fails its check is put aside in
  Manual Review, and Review Names offers it, since Manual Review is one of
  the app's folders. A new name for it marked it Completed. After that no
  run fetched it again, though its copy was still the one that failed,
  deleting the copy no longer asked for it again as Meijer and Walmart say
  it does, and the panel's Status counted it as downloaded. A new name for
  an older copy, one put aside before a later run saved the receipt, put
  aside a newer copy or kept nothing, also moved the purchase's record
  onto that copy, so the next run could fetch yet another copy or never
  fetch the receipt again. A new name now changes a purchase's record only
  when the record names the file renamed, or when there is no record yet,
  and marks the receipt Completed only when that record says it was saved.
  This holds in all fourteen receipt apps. In Uber, which names every
  receipt itself, receipts put aside are the only ones the review offers.
- **Rename renames only a document its app holds.** Rename gives each file
  an app's index names the name the app would give it today, and it renamed
  whatever a row named as long as something was there. A row naming the
  output folder itself, a folder the app files documents in, a file outside
  the app's folders, one reached by climbing out of them through "..", the
  app's own config file in an output folder set to the app's own folder, a
  file in Logs, Diagnostics or Backups, or a file that is not a PDF was
  renamed to a document's name by `--apply`, which the panel's Apply
  renames runs with no preview first. A folder the app files documents in
  was renamed with every document in it, and on a Mac or Linux, where a
  file open inside does not stop it, so was the output folder itself. No
  app writes such a row itself, but an index copied with its output folder
  to a new place names the files in the old one, and an index edited by
  hand can name anything. Rename now renames only a PDF in a folder the app
  files documents in, Manual Review included, and says how many rows it
  left alone. A row it leaves alone is not renamed in the index or in
  progress.json either, where one naming a file with the same name as a
  file renamed used to take its new name, and no app reads a date or a
  store off the file such a row names, as Robinhood, Newrez and Kroger did.
  Every app renames through the same code, so this holds in each of them.
  Anthem's ID cards, letters, plan documents and authorizations, which it
  files by name rather than by routing, are still renamed, and so is a
  Robinhood tax form saved and left under the name it was written to beside
  its place, while one that failed its check is left for the next run to
  fetch again. Two receipts of one name in two folders, an online and an
  in-store one of one day and one summary for instance, now keep their own
  new names in the index, in progress.json and in the order history, where
  both took whichever came last.
- **Rename names a file in a deep folder as its download did, and always
  finishes.** A download cuts a file name to fit max_path_length, the path
  limit in config.json, when the folder is deep enough to need it. Rename
  took the name it wanted whole whenever no other file held it, so in a
  deep output folder Rename preview offered to give a file whose download
  had cut its name the whole name back, a path longer than the limit the
  download kept to, and Apply renames gave it. When several files wanted
  one name too long for their folder, Rename could look for a free name by
  adding " (2)", " (3)" and on, which cutting the name to fit took off
  again each time, so Rename preview and Apply renames never finished.
  Rename now names every file as downloads into its folder would, one
  after another. A name is cut to fit the same way, and a receipt that
  wants a name another receipt of the same rename was given takes its
  order number first, as a download does, where it used to take a " (2)".
  A file renamed after another file took its new name in the meantime
  keeps to the limit in config.json too, where it kept to 240.
- **Rename gives every file the name its preview gave it, and a swap it
  cannot finish goes back.** When one file wanted the name of another
  that was itself being renamed to a free name, and the first came first
  in the index, Rename put the first aside, found the second still under
  its name, and gave the first that name with " (2)" added, and only then
  renamed the second. The preview had said otherwise, and the next Rename
  offered to rename the file again. Now a file waits for the one holding
  the name it wants, each chain of names is renamed from its free end,
  and when a file of a chain cannot be renamed, those waiting for its
  name keep their own. Files that trade names, two or more in a ring,
  still go through a temporary name ending ".renaming". When another
  program, such as a sync client or virus scanner, held a file in a swap
  so its rename was refused, the file could stay under its temporary name
  while its row in the index and its record named its old name, which by
  then held the other file of the swap. Rename then said only that a file
  had been left alone. A refused rename is now tried a few more times, and
  when it is still refused the files of the ring go back to the names they
  had. A file that cannot leave its temporary name is named in what Rename
  prints, with the name to give it back when that name is free, and when
  its old name holds another file by then, its row and record name it
  where it is.
- **A receipt whose page did not show it is fetched on the next run
  (#70).** When Kroger answered a receipt with its own "There was a
  problem loading the receipt. Please try again.", the app said the
  receipt was marked for manual review, recorded the purchase as having no
  receipt, which is final, and wrote it into both CSVs. The next run said
  it was already completed and skipped it, and no file was anywhere.
  Amazon, Best Buy, Costco, eBay, Gap, GitHub, Home Depot and Lowe's did
  the same when a receipt page did not fill in, Target when an order's
  page showed neither a receipt nor an invoice, and Meijer, which did try
  again, wrote the purchase into both CSVs once more on every run that
  tried. Such a purchase is now a failure that says it is tried again next
  run, the panel counts it, and nothing goes into the CSVs until a run
  saves the receipt. One whose receipt has not shown on three separate
  days is set aside for review, written into the CSVs once, and skipped
  with a line that says so. The days are counted, not the runs, so a bad
  evening of runs during a store's outage sets nothing aside, and in the
  desktop app Download again still asks for it.
  Purchases an earlier version left that way are fetched on the next run
  as well, found by the words it noted them with. The rows it wrote for
  them stay in the CSVs, and the All Purchases workbook leaves out an
  order's rows from a write that saved nothing once a later one saved it.
  A purchase the store showed has no receipt, a Target order with only an
  invoice or a GitHub payment whose row has no receipt link, stays as it
  was, and moving a download history to another computer keeps the rest
  asked for.
- **Vanguard downloads the statements its table keeps behind Show More
  (#71).** The statements table shows a year's newest rows and keeps the
  older ones behind a Show More control, which the app never pressed, so
  those statements were recorded as having no row and left for manual
  review without a download. Now the statement's own year is picked
  first and Show More is pressed until its row is drawn, each press
  judged by the guard as every other control is, never Show More Options,
  at most thirty times and no further once a press draws nothing new. A
  row counts only once its download icon is drawn, where one in the
  page's text that was not drawn used to count. Contributed by tylerverry.

### Security
- **A press made through the page is made only when it is safe, and never
  twice.** American Family, Apple Card, AT&T, E*TRADE, Golden 1, Newrez,
  PG&E, SBA, SMUD, State Farm, Verizon Mobile and Wells Fargo pressed a
  document's control a second way whenever Playwright's own press raised,
  with the control's own click run inside the page, and ADP had the same
  code where nothing calls it. That press skips every check Playwright
  makes. It reached the control under whatever covered it, even when
  Playwright's error said something covered it, it reached a control that
  did not show, and when Playwright's press had already reached the page
  before it raised, it pressed the control a second time. The change that
  stopped forced presses, after a chat bubble took a press on a tester's
  American Express account, did not cover these, since its test reads
  Python and not the JavaScript an app runs in a page. That second press
  now goes through one place in the core. It is made at most once, and only
  when Playwright says nothing covered the control, its press never began
  and the control was not turned off, when no tab opened, no download or
  load began and nothing else the press brings came, when the control heard
  no press, when the app's own guard still passes every word the control
  carries and the app's own checks still pass, and when the control shows
  in the middle of the window with nothing over it. In the same step as the
  press, the control has to still be on the page with the words it had
  before. When something covers the control, or any of that cannot be told,
  nothing is pressed and the run stops, saying why in PaperPull's own words
  and writing the failure file. Close whatever covers the control in the
  browser window, then press Resume or run again. A press Playwright says
  was made before it raised is never made again, and the run goes on to
  wait for what it brought. A control the page took away before it was
  pressed, a list drawn anew say, is not pressed at all, and its document
  is left for the next run while the run goes on. PG&E's page picker no
  longer presses a page's number a second time when the first press moved
  nothing, and asks for the page by value instead, as it did before. PG&E's
  Diagnose, which walks the history's pages through that picker, says such
  a stop and still writes its files. Apple Card presses a statement's
  button again, after a first press that brought nothing, only when that
  first press went through without raising. A new test reads every script
  the apps and the core hand to a page, followed back through names,
  imports, joins, formats and the helpers that pass a script along, and
  fails on any press a page script makes that is not on its reviewed list
  with the reason it is safe. Besides the core's own, three remain on it,
  M&T's year headings in its statements frame, and two links PG&E makes
  itself to save a PDF.
- **ADP presses the View statement that shows its identity check only when
  it shows with nothing over it.** When ADP holds back a tax statement until
  the person verifies themselves, the app presses the Tax Statements card's
  own View statement, so that ADP shows its prompt in the browser. That
  press was the button's own click run inside the page, which reached it
  under whatever covered it and pressed it when it did not show. Now
  Playwright presses it, through the same place in the core as the presses
  above, and a button something covers or one that does not show stops the
  run before it says a prompt is showing, saying why in PaperPull's own
  words and writing the failure file. The scaffold capture ADP carried,
  which no run called, is gone.

## [0.44.0] - 2026-10-07

American Express and Vanguard press a control only when nothing covers
it, after a chat bubble took a press on a tester's American Express
account, and a test now fails if any app forces a press. The panel can
download again what an app already downloaded. PayPal reads a business
account's statements, American Family opens each bill's details to find
its statements, Walmart waits for its own invoice, Meijer stops looking
for store receipts its list no longer shows, and Resume no longer calls a
run clean after a list it did not read whole. Every file a tester might
post keeps a page's words only from a fixed list, every redirect is
checked against the provider's own sites, and the control panel answers
only its own page.

### Added
- **Download again, from the panel.** A box under Scope, Download again
  what this app already downloaded, makes the next Pilot or Run All go
  through every document in the chosen range again, the ones already
  downloaded included, and fetch again each one whose file is gone, the way
  `--redownload` does from a terminal. Downloads are remembered for good,
  so this is how somebody who deleted their PDFs after importing them
  elsewhere gets them back. Nothing is overwritten. A file still there
  stays as it is, and the app may save a second copy beside it under a
  name of its own. The box needs a year, or both a From and a To date,
  since one date alone leaves a whole history open. It asks before the run
  starts, clears once a Pilot or Run All that uses it has started, and is
  never remembered. Any other button leaves it ticked and says it applies
  only to Pilot and Run All. A run that downloads again and stops partway
  says that Resume will not download again, and that the same range would
  fetch again what it already restored. The panel adds the flag only to a
  confirmed, scoped Pilot or Run All asked for in a request body, and
  refuses it from anywhere else. PaperPull Server does not offer it, since
  every copy would go to Paperless a second time. A test of every app's
  own parser and done check makes sure each one takes the flag beside the
  panel's other flags and fetches a document it downloaded before when
  asked.
- **PayPal reads a business account's statements.** Asked for its
  statements, PayPal sends a business account to its settings page, and
  the run used to stop there. It now goes to the business account's own
  statements page, under Activity and All Reports, by its address, reads
  the list that page gets for itself as it loads, and presses each ready
  PDF statement's own Download button, found in the one row that shows its
  dates and never by where the row sits. A statement is filed only when
  its own text names its first or last day and names no statement listed
  near it better, a day two listed statements share counting for neither,
  under the same names a personal account's statements get. One whose
  dates cannot be checked, one that names another statement's dates better
  than its own, and one that names a statement ending on the same day as
  plainly as its own go to Manual Review instead, with a note saying
  which. A CSV and a statement PayPal is still preparing are left alone
  and counted, a statement whose status, kind of file or dates the app
  cannot read is left alone and described in the failure file, and nothing
  that would create, generate, request or schedule a statement or a report
  is ever pressed. The name PayPal gives a downloaded file carries the
  account's id and is never kept. Login says Success only once that list
  has come, and Diagnose on a business account reads the page as well,
  pressing nothing. A personal and a business statement for the same month
  share one record, so a second PayPal account needs its own setup. Written
  from one tester's recording and not yet run on a real business account.

### Fixed
- **PayPal's Resume no longer reports a clean run when nothing was
  listed.** After a run stopped before PayPal's list was read, as one on a
  business account's settings page did, Resume said everything in scope
  was complete and the panel called the run clean. Now it says no
  statements have been listed yet and stops as a run that stopped. After a
  run whose list stopped partway, it carries on with the statements it
  knows, then says the list was not read to its end and stops the same
  way.
- **Resume no longer reports a clean run after a list it did not read
  whole, in any document app.** PayPal's was fixed first, and every other
  document app's Resume did the same. Resume reads no list of its own,
  and after a Discover, Pilot or Run All that stopped while it was
  listing, at a sign-in, a page that would not open or a browser that had
  been closed, it said everything in scope was complete and the panel
  called the run clean, although the run had listed nothing, or only part
  of the list. Each listing now notes in `last-listing.json`, in the
  output folder, whether it read the whole list. With nothing listed yet,
  Resume says so and stops, and after a listing that stopped it says so,
  carries on with the documents it already knows, and then stops, both as
  runs that stopped, until Pilot or Run All reads the list again.
  E*TRADE's Resume, which reads its lists again itself, finishes clean
  when they come whole. A Resume after a whole listing, or on an install
  from before this release that has listed documents, finishes as it
  always did.
- **The wrong-document check no longer finds a month inside a date.**
  July's 7/2031 was found inside the August date 08/17/2031, its 07/2031
  at the end of the September date 09/07/2031, and its 2031-07 at the
  front of every ISO date in July, so a statement could be taken for
  another month's. A month now counts only as a number of its own, with no
  digit and slash or hyphen right before it and no slash or hyphen and
  digit right after it. A date written with a zero after its month's name,
  like August 01, 2031, is now found as that date, where before it was
  not found at all.
- **`./setup-all.command` sets up a checkout on macOS and Linux again.**
  From 0.19.0 it stopped before setting anything up. Taking the browser
  download out of it left an `if` with nothing but comments inside, which
  bash refuses to read, and since bash reads the whole loop before it runs
  any of it, the script printed its header and the Python it found, ended
  on a syntax error, and made no environment and installed nothing. The
  tests now have bash read every shell script the repository ships, on
  Windows with Git's bash and in CI on Linux and on macOS, with the bash
  3.2 a Mac runs them with.
- **`setup-all.bat` no longer reports a problem when every setup worked.**
  From 0.19.0 every run listed playwright-chromium among the setups that
  had problems and asked for another run, since the script still checked
  for the browser download it no longer makes. Its banner no longer says
  it downloads Playwright's Chromium either.
- **`./paperpull` runs in WSL from a Windows clone.** `.gitattributes`
  kept every `.command` and `.sh` file at Unix line endings but missed the
  terminal command, which has no suffix, so a Windows clone gave it CRLF,
  and in WSL it stopped before doing anything, since `env` looked for a
  `bash` with a carriage return on the end. A test now checks that every
  shell script, found by its first line as well as its name, checks out
  with Unix line endings.
- **A recording no longer keeps a downloaded file's name.** It keeps the
  file's kind, like `.pdf`, and the shape of the name, every letter
  written as a and every digit as 9, so it still shows where the name's
  dates sit. A provider can name a statement after the account it belongs
  to, and the masking the name went through took out digits and left
  letters.
- **Recordings, Diagnose files and failure files keep a word from a page
  only when it is on a fixed list.** The list holds the words sites use
  for every customer alike, like Statements, Download or a month, and any
  other word is written as its shape, whether it is a name on a button, an
  address, an id in a web address or a field name in the provider's
  answers. It used to be masking, which removes the kinds of value
  somebody thought of, digits, emails and amounts, and lets a word
  through. The detailed file Diagnose writes and the file a failed
  download writes go through the same list now, since the apps told
  testers to attach both, so either can be sent. A screenshot Diagnose
  takes still stays on your machine.
- **What Diagnose prints keeps a word from a page only when it is on the
  same list.** The files went through the list and the lines Diagnose
  prints did not, although the panel shows them and they are as easy to
  copy into an issue as a file is to attach. Twenty-four apps printed the
  date of each sample document and twenty-three its title too, as the page
  wrote them. PG&E printed the page's address and title and the labels of
  its controls, Capital One the page's headings and its accounts, Ally,
  Chase, Discover and U.S. Bank the label of a dropdown, the addresses the
  page asked for and values from the provider's answers, and eight receipt
  apps an order number. Every value in the lines Diagnose prints now goes
  through the list first, so a word that is not on it is written as its
  shape, while a count or a yes or no prints as it did. Newrez's year
  picker lines still name the years, as they were made to. The lines a
  provider's own module logs while Diagnose runs are not covered yet, so
  read the output through before pasting it. Amazon, Best Buy, eBay, Gap,
  Home Depot, Lowe's, Target and Walmart also no longer name a purchase's
  Diagnose files after its order number, since a file attached to an issue
  shows its name. And Newrez's detailed Diagnose file keeps each year its
  picker offered as its place in the picker, as its failure file does,
  since how many statements a year holds says when a loan began.
- **AAFMAA no longer gives up on a document when the first answer to its
  View press holds no PDF.** The capture took the first answer that called
  itself a PDF and, when that answer held none, marked the document for
  manual review, although the same press went on to hand the PDF over a
  moment later. A PDF the page reads before handing it over leaves its
  answer empty in Playwright 1.63, which the packaged app runs, where 1.62
  quietly asked AAFMAA for it again, and a PDF the browser shows in a tab
  or a window answers first with the PDF viewer's own page. Now every such
  answer is read in turn while the press keeps its full thirty seconds,
  the download included, and when nothing more comes for five seconds, an
  answer AAFMAA gave to an ordinary request on its own site is asked for
  once more. That ask goes only to AAFMAA's own site and follows no
  redirect, a postback is never sent twice, only a PDF is kept, and a
  document whose row shows a policy number still has to carry it.
- **Ten apps no longer give up on a PDF their provider's page reads for
  itself.** Apple Card, AT&T, E*TRADE, Golden 1, Newrez, SBA, SMUD, State
  Farm, Verizon Mobile and Wells Fargo share one way of catching a
  document. Under Playwright 1.63, which the packaged app runs, the
  browser's answer for a PDF the page reads into its own memory comes back
  empty, where 1.62 quietly asked for it again through the browser. When
  the page then kept that PDF to itself, drawing it in a viewer of its own,
  or showed it in a frame of its page or in a tab whose address it had
  already let go, nothing else brought it and the app saved nothing for
  that document. Now, once the app has waited its whole time and nothing
  else has come, the one answer that came back empty is asked for once
  more from inside the page, on the provider's own site and refusing any
  redirect, and only a PDF, or a ZIP where the app opens one, is kept. It
  is asked only when it answered a request that same press made, from its
  own tab or one it opened, and when the press read no other answer empty,
  since two could be two documents. A download, a tab or a second button
  the same press leads to still comes first, and a page's POST is never
  sent twice. American Family is left as it was, since it never takes a
  PDF the press made without a tab of its own. No provider is known to
  hand a document over this way, and every way a real account has shown
  still worked under 1.63, so this covers what a page could do.
- **AAFMAA puts its tab back on the documents list when a document showed
  in it.** After a View, AAFMAA put the tab back on its documents list only
  when the tab's address had left /Documents/, and before each document it
  took the tab as ready by its address alone. A View that shows the PDF in
  the tab itself leaves the tab at the documents page's own address, so the
  next document was looked for inside the PDF viewer and marked for manual
  review, and a tab of yours left showing a PDF there sent every document
  to manual review. A tab now counts as on the documents page only when
  its list is showing on AAFMAA's own site, and is sent back to it
  otherwise. AAFMAA's own View is not known to show a PDF in the tab, so
  no run is known to have met this.
- **PaperPull looks for Playwright's Chromium where Playwright keeps it.**
  Playwright picks that folder from a few settings, and PaperPull did not
  read them the same way. With PLAYWRIGHT_BROWSERS_PATH=0, Playwright keeps
  its browsers inside its own package, and 1 is an ordinary folder name to
  it, while PaperPull took both to mean the usual folder. On Linux it also
  ignored XDG_CACHE_HOME, which moves that folder. On such a machine an app
  set to use only that Chromium found none, the others opened another
  installed browser instead, and when there was no browser at all, the
  download PaperPull offered landed where it did not look, so it said the
  download had not finished. PaperPull now finds the folder by Playwright's
  own rules, which also cover a relative folder, the names npm gives these
  settings, and a Windows session without LOCALAPPDATA. Where that lets an
  app find the Chromium after it had been opening another browser, it may
  ask you to sign in once more. PaperPull Server uses a Chrome of its own
  and was not affected.
- **Linux finds the Chromium that Playwright downloads.** Playwright 1.57
  began unpacking its Chromium on x64 into a folder named chrome-linux64,
  and 1.63 moved ARM machines to chrome-linux-arm64, while PaperPull
  looked only in chrome-linux, the folder older releases used. So on Linux
  an app set to use only that Chromium found none, and with no browser of
  your own the sign-in step said none was found although that Chromium
  was there. Every folder Playwright has used is looked in now, and when
  several builds are on disk, the newest is used. Finding the new
  folders moves nobody to another browser, since on Linux an app left to
  choose puts this Chromium ahead of your own browser only where a build
  sits in chrome-linux, as it did before. Windows, macOS and PaperPull
  Server were not affected.
- **On Ubuntu 23.10 and later, signing in says why the Chromium that
  Playwright downloads did not open.** Those releases keep that Chromium
  from the user namespaces its sandbox needs, so it closes as soon as it
  starts. Login waited twenty seconds, then said a window had opened
  without a debugging port and to close any other copy of the browser,
  though no window had opened. It now says at once that Chromium closed
  because it could not start its sandbox, and what to do instead, which is
  to install Google Chrome or Microsoft Edge, to close every window of
  your own browser when that one was tried first, or to set "browser" to
  "auto" in an app set to use only that Chromium. PaperPull still never
  starts a browser without its sandbox, and every other way a browser can
  fail to open is waited for and explained as before.
- **Walmart says when it skips a document it put aside, and waits for its
  own invoice (#63).** A document a run puts aside in Manual Review counts
  as done while it is there, and later runs skipped it saying "Already
  completed and PDF verified", so a run that only skipped the summaries an
  earlier version had put aside could not be told from one that put them
  there again. A run now says that an earlier run put it aside, where its
  copy is, and that deleting it has the next run fetch it again, and Resume
  says how many it skips that way instead of calling every purchase
  complete. Walmart's own invoice, the one its Print invoice button prints,
  was looked for once, and when the page had not filled it yet the order
  page was printed in its place, without its items and without a word.
  While it is on the page and empty it is now waited for, up to about 15
  seconds, before the page is looked at for a sign-in or a bot check and
  checked to be the order's, so a bot check or a sign-in page that comes up
  meanwhile is asked about as it always was rather than printed. It is
  taken only when the order numbers it prints are the order's, or by the
  order's total when it prints none. When the order page is printed
  instead, the run says so, and the file a document put aside leaves in
  Diagnostics says whether the invoice was missing, empty, found or another
  order's, how much text it held and how many item rows. A document that
  prints no item at all is now put
  aside even when no item name could be read from the order's page, once
  that page or the document counts the order's items. One whose order
  counts and lists no item is kept as before.
- **Meijer stops looking, run after run, for store receipts its list no
  longer shows.** Meijer appears to list about two years of store
  receipts, which is inferred from one account and not confirmed. A
  purchase an earlier run had found that is now older than every receipt
  on the In-Store Receipts tab was looked for twice on every run, said its
  row had no receipt or details link, was counted for manual review, and
  was written into both CSVs again each time. It is now reported as no
  longer listed, naming the oldest date the tab still shows, writes no
  failure file, counts for no review, goes into both CSVs once so a spend
  summary still counts it, and is skipped by later runs until a discovery
  finds it on the tab again. That is said only of a tab seen whole. It was
  opened on that look, on a page the browser was showing, its rows stopped
  changing and drew no more when scrolled to the end, the page held fewer
  than 400 rows, it showed no control but the two tabs and each row's own
  receipt or details link, its oldest receipt is at least 20 months old,
  and the run's own discovery read it, so Resume never decides it. A
  purchase whose receipt was saved before is never reported so, and Download
  again leaves its rows in the CSVs as they are. A row that gave no
  receipt for any other reason now says what happened, that its row is not
  on the page, that more than one row fits it, that nothing on it reads as
  its receipt, or that pressing it brought no PDF, and is a failure the
  next run looks for again without writing it into the CSVs.
  `download-attempt.json` keeps every attempt of a run in order, where it
  kept only the last.
- **Meijer's Review Names offers only receipts it holds.** It offered every
  receipt marked for review, and a purchase recorded with no receipt file
  has an empty path, which reads as the folder the app runs in. Typing a
  new name for one tried to rename that folder, which on Windows stopped
  the review with an error partway through, and the receipts renamed
  before it were left out of both CSVs. It now offers only a PDF in the
  app's own Online, In-Store or Manual Review folder, a rename that fails
  leaves that receipt as it was and the review goes on, and the CSVs are
  written however the review ends.
- **American Family opens each bill's details to find its statements.** A
  Pilot on 0.43.0 opened Billing & Payments, found no statement and saved
  nothing. That page lists each bill with a Bill details button and no
  statement of its own, and the app never pressed it. Now each bill's Bill
  details is pressed in turn, only when its whole words are Bill details
  and every word it shows or announces passes the guard, and the app waits
  up to about twenty seconds for that bill's statements and then until
  they hold still. They are read only on Billing & Payments or the page
  that press led to, never where that address names a payment, autopay or
  a setting, and only the ones the press brought count as that bill's.
  Each statement carries the last four digits of the billing account
  number its bill's card labels, or of its policy number when the card
  labels no account number, in its file name too, so two bills'
  statements of the same date are both saved and told apart. A bill is
  left alone when it cannot be told from another bill or when the page
  its press opened names another account, and each bill left alone writes
  the failure file. When a bill's statement is byte for byte another
  bill's statement of the same date, both copies go to Manual Review,
  neither deleted. Diagnose also presses each Bill details that passes the
  guard and notes where it led, how many statements showed and how long
  they took. This has not yet been confirmed on a real account.

### Security
- **Every redirect is checked against the provider's own sites before it
  is followed, when an app asks for a document through Playwright's own
  client.** That client sends every cookie the person's browser holds for
  the site it asks, and by itself it follows up to twenty redirects without
  checking any. Each app checked the address it was handed. Most never
  checked where a redirect led, and M&T, Amazon, FedEx and Stripe checked
  only where the redirects ended, after every step had been asked. So an
  address that answered with a redirect to another site sent the browser's
  cookies for that site there, and the shared capture kept the PDF that
  came back. Now an address the browser already got its document from is
  asked again with no redirect followed, and a link asked for the first
  time follows a redirect one step at a time, each step checked with the
  app's own guard before it is asked. M&T, Amazon, FedEx and Stripe keep
  their limits of three or five redirects, and M&T still reads a longer
  chain as a session that has ended.
- **The control panel answers only its own page, at its own address.** A
  website you had open could point a name of its own at 127.0.0.1, and its
  page then counted as the panel's own in your browser. The panel never
  read the address a request was made to, so a GET from that page with no
  Referer started a run, and an Origin of null, which a page can arrange to
  send, passed for this computer. The panel now answers only at 127.0.0.1
  and localhost, takes an Origin or Referer only when it names the very
  address the request went to, port included, and refuses an Origin that
  is null or empty. Every answer also says that no other site may show the
  panel inside a page of its own, so a site cannot frame it to borrow a
  click on Run All. PaperPull Server answers to its address and to a home
  network name such as nas or nas.local, with the endings it knows listed
  in SERVER.md. A server reached by any other name, a VPN's or a reverse
  proxy's for instance, answers once that name is listed in the new
  `PAPERPULL_HOSTS` setting and the container is recreated. Signing out of
  it takes a request from its own page too.
- **The control panel no longer serves FastAPI's own pages.** FastAPI,
  which the panel is built on, adds a page at `/docs` and another at
  `/redoc` that describe the panel's API, and both load their script from
  cdn.jsdelivr.net. Opening either one ran that site's script as the
  panel's own page, and a script there can do whatever the panel's page
  can, starting a run included. Nothing in PaperPull links to these pages
  or uses them, so the panel is built without them, and without
  `/docs/oauth2-redirect` and `/openapi.json`, which come with them. All
  four answer 404, on the desktop and on PaperPull Server.
- **American Express and Vanguard press a control only when nothing covers
  it.** Both pressed some controls with force, which turns off Playwright's
  check that the control itself receives the press, so the press went to
  whatever was drawn over the control. On a tester's American Express
  statements page a chat bubble sat over part of the last Download button,
  and the press opened the chat. The presses after it landed on the chat's
  suggested replies and opened a window to dispute a charge, a live agent
  joined, and the run went on to each next document and pressed again there.
  Now every press brings its control to the middle of the window first and
  is made only when the control is the thing on top at the point Playwright
  presses, and Playwright checks once more as it presses. When anything else
  is on top, nothing is pressed and the run stops, saying what is over the
  control in words from PaperPull's fixed list and writing the failure file.
  Something that comes over the control at the very moment of the press
  does not get it when it is part of the page, since Playwright's own check
  holds the press back, waits and tries again, and the run stops only if it
  is still there when the press's time runs out. A frame of its own, the way
  some chat windows are drawn, is out of that check's sight and can still
  take the press, so the point is looked at again right after every press,
  and a frame there that was not there before stops the run too, as does
  one that was there underneath and now sits over the control. A press
  that was made and whose page did not answer in time stops the run as
  well, saying so, and is never made again. Close whatever covers it in the
  browser window, then press Resume or run again. American Express also no
  longer presses a Download a second time when the file type dialog does
  not open, or when the dialog's Download brings no download, and no longer
  goes on to the next document after one. The run stops there, and
  Vanguard's run stops the same way when its download icon brings no
  download. The file type dialog is closed only through its own Cancel or
  Close, or, when it has neither, with Escape sent once one of its own
  controls holds the focus, and nothing is pressed and no key is sent to
  another dialog or a chat window to close it. It is closed only once the
  statement is recorded as saved, so a stop there never loses one. A test
  now reads the Python source of every app and the core and fails on a
  Playwright action called with force, a press of the mouse at a point on
  the page, and a dispatch_event of a click or another press event. It does
  not read JavaScript, so a click an app makes through a page script,
  el.click() inside an evaluate, is not covered by it.

## [0.43.0] - 2026-10-05

PaperPull Server arrives, in beta, for an always-on machine at home
next to Paperless-ngx, with a setup guide and privacy and security pages
of its own. No app reads, clicks or takes over a tab of another site
anymore. Ten more receipt apps and forty-one document apps no longer call
a page signed in when their list did not come, and Kroger, Best Buy, Home
Depot, Uber and Apple no longer finish clean when their purchase list
stops partway. Home Depot reads every page of a long history, Meijer
records each store receipt once, Uber and Apple download on Resume with
no tab open, and State Farm is confirmed.

### Added
- **PaperPull Server, in beta.** PaperPull can run on an always-on
  machine at home, a NAS or a home server with Docker, next to
  Paperless-ngx, and be used from a browser on any computer on the home
  network. It is one Docker image, built by `server/build.py` from the
  files git tracks, which every release publishes at
  `ghcr.io/rheeloaded/paperpull-server` once that very image has started
  and passed its checks the way SERVER.md sets it up. Chrome is not in it. The container downloads Chrome from
  Google at its first start, checked against Google's signing key, and
  keeps it up to date in a volume of its own. Chrome's sandbox stays on,
  under a security profile that is Docker's default with the two system
  calls the sandbox needs allowed. The panel listens on the network only
  there and only behind a password, chosen on the first visit with a setup
  code from the container's log, and the providers' sign-in windows open on
  a browser screen the panel shows behind the same password. Providers are
  set up into the shared data folder, with their signed-in profiles in a
  volume of their own. After every run the panel tells its plug-ins, and
  the first plug-in copies the run's new documents into Paperless's consume
  folder. Setting it up is in SERVER.md, and it has privacy and security
  pages of its own, PRIVACY-SERVER.md and SECURITY-SERVER.md.
- **The PaperPull icon on the panel's browser tab.** The panel's page named
  no icon, so its tab showed the browser's blank one. It now shows the same
  icon as the installers.

### Fixed
- **No app reads, clicks or takes over a tab of another site.** Most
  document apps worked in the tab you signed in with when it was open, and
  otherwise in the first open tab of any site at all, and Target always took
  the browser's first tab. Resume goes straight to the documents a Discover
  found, so nothing opened the provider's page first. With the provider's
  tab closed, AAFMAA clicked a link named "1" on whatever page the other tab
  showed, American Express and Navy Federal clicked links named like their
  own menus there, Ally and Chase pressed a documents control on it and then
  loaded their own addresses into it, as TSP did, and every document was
  marked for manual review, or the run said your session had expired. Each
  app read that page for a sign-in or a check first. Now no app hands over a
  tab of another site. American Express, Navy Federal, Ally, Chase, Anthem,
  DFAS myPay, TSP and Verizon keep your session in the tab you signed in
  with, so with that tab closed a run stops at its first document and says
  to open it with login.bat and run again, with nothing marked. Anthem's
  member documents, ID cards and letters stop the same way rather than come
  back empty. The other document apps open their documents page in a tab of
  their own, the way Discover does, or for M&T Bank online banking's front
  page, since its statement list is only ever the one you list. Target
  works in a tab of its own when no Target tab of yours is open. AAFMAA and
  Paylocity also send a tab of yours that is on another page of their site
  to the documents page first, so Paylocity's statements no longer come
  back empty after a fresh sign-in. The tab you signed in with is still the
  one used when it is open, and a tab of yours that leaves the provider's
  site during a run is left as it is.
- **Home Depot reads every page of a purchase history longer than one
  page.** It asked Home Depot for twenty orders a page, whatever its own
  page asks for, and took a page with fewer for the last. Where Home Depot
  gives fewer orders a page than are asked for, every order past the first
  page was missed while the run finished clean. It now asks for as many a
  page as Home Depot's own page does and reads on until the count Home
  Depot gives is reached. A page with nothing new on it ends the reading,
  so a count larger than what comes is not asked after page by page.
- **Resume downloads Uber receipts and App Store receipts with no tab open
  on their sites.** After a Discover that read every list to its end,
  Resume goes straight to the purchases found, and each receipt is asked
  for from inside a tab on the provider's own site. With no such tab open,
  for instance once the tab used to sign in was closed, the app opened a
  new blank tab, every request was refused before it was sent, and each
  purchase was recorded failed with "No receipt came back", run after run.
  Resume now opens the trips page, the Uber Eats orders page or Report a
  Problem first, the way Discover does, and again whenever a tab the run
  opened has left the site partway through. A side that asks for a sign-in
  or shows a check there stops with its tab left open, as in Discover. A
  tab of yours already on the site is still the one used, and it is never
  reloaded or closed, and a tab of yours that leaves the site during a run
  is let go of where you took it, never loaded back, with the next receipt
  asked for from a tab of the run's own. Pilot and Run All were not
  affected, since they read the lists in the same run.
- **Meijer records each store receipt once, and waits for the In-Store
  receipts to show.** On a page that keeps the In-Store receipts while
  Online Orders is shown, hidden rather than removed, discovery read every
  one a second time from behind that tab, without its date, so each was
  recorded twice and Pilot could press the same receipt for both. Only the
  receipts the page shows are read now, and undated copies left by an
  earlier run go at the next discovery unless they were downloaded. The
  In-Store receipts come only once their tab is pressed, and they were
  read two and a half seconds after the press, so receipts that came later
  were missed and the Online tab's "You haven't placed any orders yet" was
  taken to mean neither tab had any. Each tab now gets up to 30 seconds,
  as a purchase's tab already did, and a tab that shows nothing is never
  taken to be empty. With nothing on either tab the run stops and says to
  look at the browser window, rather than finish as though there were
  nothing to find (#42).
- **Seven more receipt apps no longer call a page with no order list
  signed in.** Amazon, Costco, eBay, Gap, GitHub, Home Depot and Lowe's
  asked the way Walmart and Best Buy did before 0.41.0. Login said Success
  whenever one look at the orders page found neither a check nor a sign-in
  page, and a page still blank while a bot check decides has neither. Now
  it says Success only once the list is there, or the site's own word
  that there is nothing in it, and otherwise looks for a check for a
  little while and names it, or says the list did not load and to look at
  the browser window. Discovery stops there too, rather than finding
  nothing and finishing clean. Amazon tells a year with no orders from a
  page that never drew by Amazon's own count, "0 orders", so the walk
  back through the years still ends where the history starts, and a year
  whose page never drew now stops the run instead of ending the walk.
- **Kroger, Meijer and Target no longer call a page with no order list
  signed in either.** Their Login called the session signed in whenever
  one look at the history found neither a check nor a sign-in page, and
  Target's never looked for a check at all. Now each says so only once its
  list is there, or the site's own words that there is nothing in it, and
  otherwise looks for a check for a little while and names it, or says the
  list did not load and to look at the browser window. Discovery stops
  there too, rather than finding nothing and finishing clean. Meijer no
  longer takes a page that drew only the list's heading for its list,
  which a tester's run met (#42). In the person's own browser, when
  Target's orders do not come and nothing on the page can be named, it
  lets go of the browser and stops, at a console too, so whatever the
  window then asks is answered with the app gone, as Target's press and
  hold check is (#48).
- **Kroger no longer finishes clean when its purchase history API does not
  give the history.** Discovery asks the history API from inside the
  history page, and a refusal (Kroger's bot protection can refuse a call
  from a page that drew), no answer, or an answer without the list was
  read as a history with nothing new in it. The run finished clean, so
  Pilot and Run All went on with every new purchase missed. Now the run
  stops there, says so and writes a failure file, or at a console asks
  and then reads the history again. When the API stops partway, what came
  is kept and used, and the run stops at its end rather than finish, since
  older purchases may be missing. Resume after either reads the history
  again first, and when Kroger refuses again it still downloads the
  purchases already found and stops at its end. An account with no loyalty
  card keeps Kroger's own words for it.
- **Best Buy, Home Depot, Uber and Apple no longer finish clean when their
  purchase list stops coming partway.** Each asks the site for its
  purchase list from inside the signed-in page. A request that was refused
  or got no answer, at the first page or partway through, wrote a failure
  file, and the run went on as though the list had ended and finished
  clean, with purchases missed and the failure file never offered. An
  answer that was not the list, a page in its place or an empty answer,
  was read as a list with nothing more in it. Now what came is kept and
  used, and the run stops at its end rather than finish, which the panel
  reports as stopped after Pilot, Run All and Resume. When nothing came at
  all, Best Buy and Home Depot stop there, and at a console they ask and
  then read the history again. Uber and Apple go on with their other side
  first, as they do when one side asks for a sign-in, and an Uber trip
  whose details got no answer counts the same way. Resume reads the list
  again first while the last Discover left it unread, for Uber and Apple
  after a sign-in too, and when the site refuses again it still downloads
  the purchases already found and stops at its end. For Best Buy only the
  errors it answers past the oldest year it keeps end the history,
  wherever they come, and a refusal no longer does after an empty year, so
  a January with nothing bought yet no longer ends a history Best Buy
  refused at last year.
- **Document apps no longer say signed in when their documents page did
  not come.** Forty-one of them said "Connected and signed in" when the
  page they look for never appeared. They now say it did not load, so
  they cannot tell, and to look at the browser window and answer anything
  the site asks there.
- **The panel's README gave the old place for its settings file on
  Windows.** It said `%LOCALAPPDATA%\PaperPull\settings.json`, where
  versions before 0.19.1 kept it. The file lives in Roaming AppData,
  `%APPDATA%\PaperPull\settings.json`, and the panel moves an old one
  across. The README says so now, and names the Linux location too.
- **AT&T no longer chooses a date range past a dropdown it could not
  read.** A bill the history does not show is looked for through the
  history's date range, and the bill buttons carry no year, so the year a
  chosen span names dates every bill on the list. A dropdown whose name or
  options could not be read was passed over as though it were not there,
  so when it was the list's own filter, the span went to the next control
  of years the list does not follow, a second dropdown, a Date range menu
  or a legend beside the filter. The list was then dated to the year asked
  for, and its bill of the same month was saved under the older bill's
  date. Now no span is chosen when a dropdown could not be read, and the
  bill is marked for review and tried again on the next run. att.com's own
  date range is a calendar, which is never filled in, so no run is known
  to have met this.

### Changed
- **State Farm is confirmed on the tester's account (#37).** His full run
  saved every document State Farm lists for his policies, the payment
  receipt earlier rounds refused among them, so it moves from untested to
  confirmed.
- **The steps under the panel's buttons say what Discover does.** They
  named Login, Pilot and Run All and left Discover out, though it is one of
  the four buttons a normal day shows. They now say it shows what the
  provider has and downloads nothing, and that it is optional, since Pilot
  and Run All look too.

## [0.42.0] - 2026-10-03

Repairs from testers' reports and from checks run across every app.
Walmart receipts and invoices print their items again, State Farm presses
a receipt named the way State Farm's own list names it, Apple stops asking
for receipts past the point where an account's refusals start, and Golden
1 and amazon.de are confirmed. In an install the panel set up, Chromium
and Edge on Windows no longer cancel every download, and a tax form that
comes as a ZIP is saved. Across the apps, a purchase's page is checked to
be its own before it is printed, a control that could not be read is never
taken to be absent, every tab a press opens is closed, and a date or a
total counts only as a number of its own.

### Fixed
- **A receipt's date and total count only as numbers of their own.**
  Costco, GitHub, Kroger and Meijer accept a receipt that prints the date
  and total their list showed for a purchase, and the two were looked for
  as plain text, so "1/19/26" was found inside "11/19/26" and "1.23"
  inside "31.23". A January 19 purchase of $1.23 would have kept November
  19's receipt for $31.23 as its own. Each now has to stand as a number of
  its own, with no digit touching either end, while a till's spaced out
  print and a date followed by a time still match. Measured on real saved
  receipts, no receipt's own date and total stopped matching.
- **A date or a total counts only as a number of its own.** The check
  that a saved document is the one asked for looked for a row's date and
  total anywhere in the document's text. So a January 19 purchase's
  1/19/27 was found inside a November 19 receipt's 11/19/27, its total of
  1.23 inside 31.23, and a 2020 date at the front of a later one, and the
  document beside the one being saved could pass for it. That check runs
  in Costco, Uber, Navy Federal, Fairfax Water, Target RedCard, T-Mobile,
  TSP and Golden 1. Now no digit may touch the front or the end of a date
  or an amount, and no point or comma may join it to a number in front.
  Uber's last check before filing a receipt holds its total and dates to
  the same rule. A document number is matched as before. Measured first,
  read only, on every saved document of every install, no document lost
  its own date or total, what the check stopped finding was only a
  neighbor's date or total inside a longer number, and no verdict on an
  already saved document changed. That took a day before its month's name
  asked for with its zero, 05 Jan 2027, since some statements print it
  that way and the old search found them only by finding 5 Jan 2027 inside
  it. A zero-padded month before a day without one, 01/5/2027, was found
  the same way and is asked for too, though nothing saved prints it. The
  receipt check's date and total pair, which Costco, GitHub, Kroger and
  Meijer hand over, finds a date by the same rule and is given both forms
  as well.
- **Apple Card reads a list it could not open because the session had
  run out.** Discovery opens the card's statements, the Savings
  statements and the tax forms in turn. When Apple had signed the person
  out by the time one of them was opened, a run started from a terminal
  asked them to sign in again and then went on to the next list, so the
  one that would not open was missing from that run. When it was the tax
  forms, nothing said so. Now that list is opened again after the
  sign-in, and the question is asked again if the person pressed Enter
  before they had signed in. A run from the control panel stops there as
  before.
- **A tab a statement opens is closed even when it comes late.**
  American Family and Robinhood each open a statement in a new tab, and
  PaperPull takes the PDF without reading that tab, American Family's
  from the page that made it and Robinhood's from the link its site
  answers with. The press then closed the tabs it had seen open, and a
  tab the browser announced only after that stayed open in the person's
  browser, one per statement. Robinhood's site opens its tab only once it
  has answered, and on a made-up page doing the same, 3 presses in 40
  left the tab open. American Family's was left open once in a test run,
  with three other test runs on the same machine. Now American Family
  waits for a tab its page asked for, and Robinhood for the tab its site
  opens after the answer, five seconds at most, and closes it.
- **Ally reads a statement's tab only at Ally's own address.** When a
  statement's press brings no download, Ally takes the tab the press
  opened and fetches that tab's address with the signed-in session.
  Nothing looked at the address first, so a PDF in a tab anywhere else
  would have been saved as the statement. The check of which statement
  Ally served kept it too, since that check hears only Ally's own page,
  and it called the file verified when that page had been answered with
  the statement asked for. Now a tab off Ally's hosts is turned away
  unread, the way Chase turns one away, and it is still closed. A blob
  the page made, or a tab on Ally, is read as before. Ally is not known
  to open such a tab, and a made-up page in a real browser shows the
  case.
- **Chase and U.S. Bank close every tab a statement's press opens.** When
  a statement's control fires no download, both look for a tab the press
  opened and read the statement there, only at the bank's own address,
  since that read carries the signed-in session. Chase turned a tab
  anywhere else away and returned before closing it, and U.S. Bank never
  took such a tab and never closed it, so it stayed open in the person's
  browser, one per statement. Each closed only the tab it read, so a
  press that opened two left one open, and a press whose download came
  through closed none. Now every tab the press opened is closed however
  it ends, and a tab turned away is still never read. Neither bank is
  known to open such a tab, and made-up pages in a real browser show each
  case.
- **Six more apps close every tab a document's press opens.** The leak
  Chase and U.S. Bank had was looked for in every app, and six more had
  it. Ally closed only the one tab it looked at, so a second tab from the
  same press stayed open in the person's browser, and so did a tab opened
  by a press whose download came through. Target RedCard and T-Mobile left
  open any tab their press opened, read or turned away for its address.
  AAFMAA and Target's Print receipts kept only the newest tab a press
  opened, so the first of two stayed open, and Target left a tab opened
  beside a download. Golden 1 stopped looking once it had taken a tab for
  the vendor's, so another tab from the same press stayed open, and its
  Diagnose left open a tab the same press opened a moment after the
  vendor's. Now each closes every tab its press opened and reads none it
  turned away. Golden 1 keeps the vendor's tab it works in, and Target
  still hands back the tab a receipt is printed from. None of these sites
  is known to open such a tab, and made-up pages in a real browser show
  each case.
- **A control that could not be read is never taken to be absent.** On a
  slow page, a control, row or button that did not answer in time was
  passed over as if it were not there, and what to press was chosen from
  the rest. E*TRADE presses a document's control only when one names it,
  so of two controls naming one document, one of them slow, it would
  press the other as the only one. The same counting could go wrong in
  its row link step and for the page's Download button, and in PG&E,
  State Farm and Apple Card. Ally tells the statements of a date apart
  only by their place, so a row it could not read would move the next
  statement into that place and the wrong statement would be saved. Navy
  Federal left an account's group open when it could not read its
  header, so that account's row could be pressed for another account. In
  the core, a second step after a click was chosen from what the click
  revealed, and a control left out of the survey taken before the click
  looked revealed after it. Each now refuses when it could not read
  everything it chooses from, and the steps after it still look. A check
  across every app keeps it that way. Found when one E*TRADE test failed
  on a stalled CI machine, and nothing shows it happened on a real run.
- **Ally presses a tax form only when its year picker shows that form's
  year.** A tax row names its form, 1099-INT, and nothing that says which
  year it is for, so the year the list shows decides which year's form is
  pressed, and the list follows its year picker. Ally set the picker to
  the form's year and went on whether or not that worked, and it took a
  picker it could not read for a page with no picker, which skipped
  setting it and the check that the year can be reached at all. Either
  way another year's form could be saved under this one's name, and the
  check of which document Ally served caught that only when the form had
  an id and the page was seen fetching it by that id. Now the picker is
  read again after it is set and once more just before the press, and a
  tax form is pressed only when it shows the form's year and no dropdown
  before it went unread. Otherwise nothing is pressed, the form goes to
  manual review with the reason in the log, and the next run tries it
  again. Statements were never affected, because their rows are found by
  a date that carries the year. In the core, safe_selects can now say
  which dropdowns it could not name, which is how a picker that did not
  answer is told from no picker. Found by reading the code after the
  stalled CI run, and nothing shows it happened on a real run.
- **Dominion opens the bill it was asked for.** Each bill is listed by the
  date in its panel header, and the download then looked for the panel
  whose header held that date spelled 1/5/2025. That spelling is inside
  11/5/2025, and bills are listed newest first, so a January bill opened
  the November panel above it and saved November's bill under January's
  date, where it counted as downloaded for good. A header that pads its
  month, 01/15/2025, did the same beside 11/15/2025, and one that pads its
  day, 01/05/2025, was never found at all. A panel is now chosen by the
  first date in its header read whole, the same reading that listed the
  bill. A January or February bill whose day matches a November or
  December bill of the same year may hold the later bill. Move that file
  out of the folder first, since a file already there keeps its name, then
  `--redownload` with `--start-date` and `--end-date` on its date fetches
  the right one.
- **Ally and USAA find a statement's row by its own date.** Ally looked
  for a statement's row by several spellings of its date, anywhere in the
  row, and the first is 1/6/2026, which is inside 11/6/2026. Ally writes
  dates with the month's name today, so only a page that wrote them as
  numbers would have sent a January statement to the November row above
  it. USAA did the same for a document discovered without its id. A date
  there now counts only as a number of its own, the rule the check on a
  saved document's text already follows, and a locator can now be handed
  that rule. A check over every app now finds each place that looks for a
  date in what a page says and works out, by running the app's own code
  on sample dates, whether one date can be found inside another's. It
  found these three and no others.
- **Target no longer takes a control it could not read to mean there is
  no receipt.** Target reads the words of the control that opens an
  order's receipts, "Receipts & invoices", and gives the read a second
  and a half. One that did not answer in time was passed over, and when
  nothing else opened, the order was marked No Receipt Available, which
  is final. With include_invoices on, which is how a new install comes,
  the "View invoice" beside it was pressed instead, and the invoice was
  filed in the receipt's place with the order marked done. Either way the
  receipt was never asked for again, and a slow page was enough. Now
  nothing on such a page is pressed or concluded, and the order is tried
  again on the next run, with a note saying a control could not be read.
  The Print receipts and invoice controls had the opposite flaw. One
  whose words could not be read was kept as though they had passed the
  check that keeps a gift receipt or a return from being pressed. Now it
  is left out, nothing after it is pressed, and the order waits for the
  next run the same way. Target names its own gift receipt control "Print
  gift receipt", which the Print receipts name never matches, so no real
  run is known to have pressed one.
- **Wells Fargo tells a statement from a tax form of the same day.**
  Discovery kept one document for each date, named for the first control
  of that date it could read, and the download pressed the first control
  carrying the date, whatever it fetched. So when a 1099 and a statement
  shared a date only one of them was ever found. And when the 1099 could
  not be read while the page was surveyed, the date was recorded as the
  statement, and the download pressed the 1099 and filed it as the
  statement. Nothing checked which document the saved file was. Now
  discovery and the download read a control the same way, and a document
  is its date, its kind and the entry it sits in, its table or grid row,
  or else the part of the page around it that prints words of its own. A
  statement and a 1099 of one day are two documents, each pressed for
  itself, while View and Download of one statement stay one. Each control
  is read two ways, the way this app always read it, and with care, never
  taking another control's words or dates or a date printed over a list of
  rows. It is filed only where the two agree on its date and its kind, and
  where they disagree it is left for a person and counted in Diagnose, so
  nothing is filed under a kind or a date the old reading would not have
  given it. Two entries of one day holding the same kind cannot be told
  apart, two accounts under one date heading for instance, and that
  document is refused rather than guessed at, even when the download can
  see only one of the two. A control that would not answer stops the
  download from choosing past it, and the control chosen is read again as
  the element that is then pressed. Found by reading the code and proven
  in a browser before the change. Wells Fargo is still untested and nobody
  has reported running it, so no archive is known to hold a misfiled
  document.
- **A menu entry whose name holds a slash is pressed.** When a Download
  button opens a small menu, the entry that finishes the download is
  found by the words it showed, and "View/print PDF", which every
  provider cut from the scaffold looks for, could never be pressed. The
  pattern built from those words kept the slash bare, Playwright ends a
  pattern at a bare slash, and the locator failed the moment it was
  used, a failure that was caught without a word. The twelve apps that
  use it are ADP, American Family, Apple Card, AT&T, E*TRADE, Golden 1,
  Newrez, SBA, SMUD, State Farm, Verizon Mobile and Wells Fargo, and only
  AT&T found the entry another way, by its text. The core's new
  escape_for_locator writes the slash so the browser reads it, and a
  real browser presses a revealed View/print PDF through each of the
  twelve apps' own words and guard.
- **AT&T finds its View/print PDF button (#26).** Two of the patterns
  that name the bill's View/print PDF control kept its slash bare, so
  Playwright refused them and neither ever matched. A bill showing only
  that control was reported as having no PDF control, and the fallback
  tried when Download PDF gives nothing had not found its button once
  since it was added in 0.28.3. View/print PDF is pressed once at most,
  and only after Download PDF has had as long to appear as it always had.
- **Every app escapes the text it puts into a pattern for the browser.**
  Twenty-two more apps built such a pattern from text read off the page
  or out of their own records the same way, leaving any slash bare.
  Apple Card, Chase and U.S. Bank had nothing else to find the control
  with, so a document button, row or card whose name held a slash was
  never found. E*TRADE and State Farm fell back to finding it by its
  text, and the rest either cannot meet a slash today or reach the
  browser a way that reads one anyway. No document is known to have been
  missed. A census test now follows every pattern handed to the browser
  back to where it is built, and fails any app that writes a bare slash
  into one or escapes text into one with a bare re.escape.
- **In an install the panel set up, Chromium and Edge on Windows
  canceled every download, and eleven apps asked the provider for every
  document twice.** The apps that watch a hidden folder pointed the
  browser at it by a relative path, which is what the default output
  folder gives, and measured on Windows, the browser then cancels every
  download. ADP, American Family, Apple Card, E*TRADE, Golden 1, Newrez,
  SBA, SMUD, State Farm, Verizon Mobile and Wells Fargo got each document
  by asking for it a second time, and AT&T could not take a downloaded
  bill at all. The folder is now made absolute before the browser is
  pointed at it, as Vanguard's already was.
- **Where a download did land, a hidden copy of it was left behind.** In
  Chromium and Edge on Windows, a browser pointed at a folder saves the
  only copy of a download there, and the download event the app sees
  carries an empty file. In an install with an absolute output folder,
  those eleven apps took the empty file for a failure, asked again,
  saved that answer, and left the browser's file in the hidden folder,
  where it outlived the one in the archive once that was deleted after
  an import. The browser's file is now moved into place, so the provider
  is asked once and nothing is left behind. Where a browser gives the
  download event the whole file instead, as a tester's Chrome on macOS
  did, that file is saved as before. The next run clears the copies
  earlier versions left, and only files that are exact copies of a
  document still in the archive. Nothing else in the folder is touched.
- **AT&T and Verizon could stop saving bills after a single failure.**
  Chromium and Edge on Windows write a finished file of the same name
  over the old one in place, and both apps compared their folder by name
  alone, so one file left there under a bill's usual name hid every
  later bill of that name. A file written again now counts as a new
  one, in every app that watches a folder.
- **Two different PDFs arriving in the download folder during one
  capture now mean neither is taken.** The folder cannot say which is
  the document asked for, and a download the last press started can be
  one of them. The statement is left for the next run rather than filed
  under the wrong name. Vanguard takes its statement the same way now,
  so the last press's late download raising the first event is no
  longer saved as this statement when this statement's own lands too.
- **A tax form that came as a ZIP was never saved, in sixteen apps.**
  All but one of the documents apps have a step that opens a ZIP holding
  a tax form's PDF, and in the apps that take a download from the
  browser it never ran. American Family, Apple Card, AT&T, E*TRADE,
  Golden 1, Newrez, SBA, SMUD, State Farm, Verizon Mobile and Wells Fargo
  kept a download only
  when it began like a PDF, and then deleted anything else before that
  step was reached. AAFMAA, Ally, Chase and U.S. Bank kept only a PDF
  from a download event, and Verizon Fios only a PDF from its folder. A
  provider that handed over a ZIP got "Could not capture the document
  PDF" and a manual review on every run. The ZIP is now taken, driven in
  a real browser for every app that takes a download but Vanguard, whose
  own capture still keeps a PDF only.
- **A ZIP is opened only when it holds one PDF and nothing else.** That
  PDF is filed and checked like any other. Before, the first of several
  PDFs was filed under the document's name before anything checked it,
  the others were put beside it unchecked, and any other files in the
  archive were destroyed. A ZIP holding anything more is now kept whole
  in Manual Review, and the record says what it held, since which file
  is the document cannot be told. The same archive arriving again on a
  later run is kept once. This changes what Amex, Dominion, Robinhood
  and Wealthfront did with an archive of several files. Opening one is
  safe as well. A failure part way used to leave part of a PDF under the
  document's name and the archive out of sight, and now leaves the
  archive kept and nothing half written.
- **Target writes an invoice order down once.** An online order saved as
  its invoice went into the receipt index and the order history twice,
  first as No printable receipt available and Review Needed by the step
  that saved the invoice, then as Downloaded and Completed once the run was
  told the invoice was saved. It was counted twice as an invoice and once
  as needing review however good its name, so review_names offered every
  invoice order for renaming and the purchases workbook listed each of
  their items twice. In a real archive 22 of 23 invoice orders had two rows
  for their one file. Now each is written once, the way it ends, Completed
  unless the name it is filed under is a guess, and counted once. A tip's
  invoice put aside in Manual Review is still reported, as a file that did
  not pass its check. Rows written before are left as they are. Walmart
  kept a copy of the same step that nothing called, and it is gone. A check
  across the repository now refuses a step that writes a purchase down and
  then tells the method that asked, which writes it again, that it saved
  it.
- **A purchase's page is checked to be its own before it is printed.**
  Amazon, Gap, GitHub, Meijer, Target and Walmart print a purchase's page
  and keep it as the receipt, and the check on the saved file cannot tell
  a list from a receipt when the list names the purchase. Walmart's order
  list shows each order's items, GitHub's payment history each payment's
  date, amount and id, and a wrong page read first writes its own date
  and items into the purchase, so each of these, printed in a purchase's
  place, was kept as its receipt and marked downloaded. Now the page is
  read first, the way Best Buy reads the number on its details page. Its
  address has to name the purchase, and the number the page gives its
  purchase has to be this one and no other, Walmart's Order# or TC#,
  Amazon's order id, Gap's Purchase # and the number over Target's details
  page. GitHub and Meijer print a page only when a receipt link answers
  with one rather than a PDF, and that page has to be the one the link
  points to and not the list. A page that is not the purchase's is not
  saved, the purchase is asked for again on the next run, and the run
  reports a wrong document. A Target order's invoices are reached by
  presses from the order's page, and each invoice's page has to be at that
  order's address before it is printed, since an invoice never prints the
  order's number. One that is not is left unprinted, and the order is
  asked for again on the next run. The order list sent in place of an
  Amazon, Gap or Target purchase's page used to be recorded as that
  purchase having no receipt, which is final, so it was never asked for
  again, and it is not now. Measured first on saved receipts, every
  Amazon, Gap, Target and Walmart receipt was printed at an address naming
  its purchase, and every Amazon, Gap and Walmart one names its purchase
  the way the check reads it. Costco, eBay and Kroger do not read their
  page yet.
- **Walmart receipts and invoices print their items again.** By the end
  of September Walmart's order page folded its item list away, and its
  print style hid the list even when it was open, so the app's print of
  the page carried the date, the totals and the barcode and none of the
  items. The check passed such a document on the order's number and total
  (#63), so a run saved receipts with no items on them and called them
  done. A store receipt saved in July and the same purchase saved on
  October 1 differed by exactly that. The app now prints the invoice
  Walmart's own Print invoice button prints, which lists the items,
  without pressing that button, and a document that prints none of the
  order's items goes to Manual Review instead of being kept.
- **Walmart's bot check is looked for again just before a print.** It came
  up over an order page that had opened clean, and the print carried
  "Robot or human?" under the totals. Now the person is asked to answer it
  first, or under the panel the run stops with its progress saved, and the
  order's page is opened again before it is printed.
- **State Farm presses a document described the way State Farm's own list
  describes it (#37).** His Payment Receipt of March 11, 2025 was refused
  again on 0.41.1, for a payment word in what the page says after the
  dash, in a shape the nouns 0.41.1 let through, Billing/Payments,
  Payments, a card ending in its last four, did not cover. The list the
  page loads names every document, and a description that is word for word
  what it gives this document, its description or its category, read from
  the list of the very load the row is found on, is now read again with
  the money words a receipt is described by let off, payment, paid,
  billing, receipt and a card ending in its last four. Every other word of
  the guard still faces it, so "Switch to autopay" or "Billing settings" is
  refused whatever the list says. Its type still faces the whole guard,
  its names for a screen reader are asked too, and anything else is read
  as before. A name the page lists cut at sixty characters only has to
  start the list's words, and the whole name read off the control before
  the press has to be all of them. When the guard still refuses a
  document, `download-attempt.json` gives its description's words from a
  fixed list of ordinary ones, any other word as `*` and digits as `#`, so
  the next refusal says what shape it has.

### Changed
- **Apple stops asking for receipts past the point where an account's
  refusals start (#55).** Report a Problem refuses an account's oldest
  receipts, before October 2016 on one account, before May 2015 on another
  and anything older than eighteen months on a third, and every refused
  purchase was asked again on every run until its third refusal made a
  purchase record of it. Purchases go newest first, and once Apple has
  refused ten of an account's purchases in a row, each older than any
  receipt it has given that account, the older ones are not asked for the
  rest of the run, but for one a year until Apple refuses it. Each counts
  as refused on that run, so a record still waits for three separate runs,
  and the run that would make a purchase's record asks it, so every record
  rests on Apple refusing that receipt itself. The record says how many
  runs did not ask. If Apple gives one of the receipts still asked for,
  older purchases are asked again, and the next run starts from that
  receipt. `--redownload` asks every purchase, as before.
- **Golden 1 is confirmed on the tester's account (#35).** Rename gave his
  card's statements their new name, and his run saved every statement on
  both of his accounts. The README's SMUD row says confirmed now too, as
  PROVIDERS.md and SMUD's own README already did (#34).
- **amazon.de is confirmed by a user,** over ten years of orders (#24).

## [0.41.1] - 2026-09-30

Repairs from testers' reports on 0.41.0. American Family finds its
statements by the site's own mark, Meijer waits for its list, Target
reads the order list without loading it again, Walmart keeps an invoice
that prints its order number its own way, PayPal says where a business
account landed, and Robinhood dates a tax form by its tax year and reads
crypto statements. Golden 1 and State Farm get repairs too. Across the
receipt apps, a run that signs in again reads the page it had opened, a
printed page goes back to the screen, and a saved receipt has to name its
purchase rather than the provider.

### Fixed
- **A run that signs in again at a console reads the page it had opened.**
  When a site signed the person out partway through a run started from a
  terminal, the run asked them to sign in again, opened the order list,
  and then read that list as whatever it had opened before. In Walmart the
  list was printed and saved as an order's invoice, with another order's
  date, and the order was marked as downloaded for good. Best Buy filed
  good receipts as Mixed Purchases for review. Amazon, Costco, eBay, Gap,
  Home Depot, Kroger, Lowe's and Target opened a purchase the same way,
  GitHub printed its payment history as a receipt, and Amazon, eBay,
  GitHub, Meijer and Lowe's could end a walk of their history early with
  purchases never found. Robinhood looked for a statement on another
  section's page. Each now opens its page again after the sign-in, and
  asks again if the person pressed Enter before they had signed in. A run
  from the control panel was never affected, since it stops there and
  waits for Resume.
- **A printed page goes back to the screen.** Most receipt apps save a
  purchase by printing its page, and the page was switched to print media
  for that and never switched back. The call meant to undo it,
  `emulate_media(media=None)`, leaves the emulation as it is in Playwright
  for Python, where only "null" takes it off. So from a run's first printed
  purchase to the end of the run, every page the app read was read in its
  printed layout, the next purchase's page included, and the tab being
  watched showed that layout until the app let go of the browser. Walmart
  read the items of a run's later purchases without their quantities, every
  one on an in-store purchase and most on an online order. Saved runs show
  it, and a purchase read once each way differs in nothing else. The other
  receipt apps with saved runs to compare show no difference between a run's
  first purchase and the rest. Now the page goes back to the media it was
  in, so every purchase is read the way a run's first always was, and a
  check across the repository refuses any call that tries to put the media
  back with None. Purchases already saved keep what they were read with.
- **A saved receipt has to name its purchase, and the provider's name no
  longer does.** Every receipt app checks a saved PDF against its purchase
  before keeping it, and the check was satisfied by any one word it was
  handed, the first of which was the provider's own name. Every page of a
  provider's site carries that name, so any page passed. Walmart's order
  list, printed in the middle of a run after a sign-in, was kept that way
  as an online order's invoice and marked downloaded, so the invoice itself
  would never have been asked for. Now a PDF with text has to show the
  purchase's order number, its date in the form 2026-06-03, or the start
  of an item's name, and the provider's name counts for nothing, whoever
  hands it over, Uber's rides included, whose store is Uber. A scan, or one
  whose few words include the name, is kept as before. Costco, GitHub,
  Kroger and Meijer also hand over the date and total their list showed for
  a purchase, which count together, for a receipt with no number and no
  item the check could find, such as a Meijer till receipt or a Costco gas
  receipt, and a Costco gas receipt that did not say Costco, put aside
  before for that, is kept now. Measured before it was enabled on real
  saved receipts, it keeps every one but a Target invoice holding only a
  delivery tip, which Target's app files when an order has more than one
  invoice and the tip's comes first, and that is put aside now rather than
  kept as the order's invoice. A page naming only the provider, accepted
  before for nearly every purchase, is refused for every one, and the
  receipt of the purchase next to one on the list, accepted before in
  nearly every pair, is accepted in about one pair in forty, nearly all of
  them two purchases of the same item. What it does not catch is a list
  that names the purchase itself. GitHub's payment history shows a
  payment's own date and amount, so it passes as that payment's receipt,
  and only a check of the page before it is printed can tell them apart.
- **Golden 1 names a card under a heading in the plural (#35).** The
  tester's card sits under the vendor's heading "Credit Cards / Home
  Equity Lines of Credit", and the app looked for card as a whole word,
  so the card was read as an account and its statements were saved as
  Account Statement. Credit cards in the plural now counts, and a bare
  Cards still does not. Only a panel the plural alone reads as a card
  changes. It takes the key its own heading gives it, every other panel
  keeps the key it had, and a card and a home equity line under the same
  heading are both left as they were. Its statements saved under a key
  its own heading gave are carried to the card's on the next Discover,
  with whether they were downloaded and where the file is, so Rename
  gives the files the card's name and they are not fetched again. Ones it
  saved as the page's first panel, a key another panel may hold since,
  are listed again under the card's name instead, a second copy being the
  price of never passing one account's statement to another. The heading
  names a home equity line as well, and the only member known to have it
  holds a card, so it is read as a card's.
- **State Farm presses a document whose description names money (#37).**
  A Payment Receipt whose list entry carried no file address was never
  saved, because the guard read the document's whole name, and the
  list's own name for it, "Payment Receipt - Billing/Payments", holds a
  word the guard refuses on a control. A revealed document's type, before
  the dash, still faces the whole guard and has to be the type the list
  gives. Its description faces the words that act, and the whole guard
  too, less a few nouns in their own shape, a description that is only
  Billing/Payments, Payments, Autopay, Wire, Bill Pay or a card ending in
  its digits, and Limited in a vehicle's name. Anything else in a
  description still keeps the press away, and the trace now says which
  of the guard's own words did. Every name a screen reader may give the
  control, from aria-labelledby and title as well as aria-label, is asked
  too.
- **Target saves every invoice of an online order.** An order with no
  store receipt is saved as its invoice, and Target splits an order into
  invoices, one for each shipment and one for a delivery driver's tip,
  shown one at a time from a list of their own. Only the first was ever
  pressed, and the order was then marked done, so the others were never
  asked for. In a real archive the invoice saved for one order was the
  tip, while the item bought was on the invoice never saved. Now each
  invoice on the list is saved and checked on its own, named "(1 of 2)"
  and "(2 of 2)" the way Amazon names a seller's second invoice. One that
  names nothing of the order, a tip usually, is put in Manual Review
  rather than filed as the order's invoice, and the order's record points
  at the invoice that names its items. An order is marked done only once
  every invoice it has is saved. Until then it is tried again on each run,
  and an invoice saved before is not saved a second time. An order saved
  by an older version can be fetched again with `--online --order-number
  N --redownload`, and the invoice already on file is recognized by its
  invoice number and left alone. Each invoice control now passes the same
  guard the Print receipts controls do, since every one on the list is
  pressed.
- **Target sees its Print receipts press print.** The press builds the
  receipt and prints it, and the shared core keeps the receipt at that
  moment and marks the page as having printed. Since Target moved onto the
  core in August, the app looked for that mark under the name its own code
  had used before, which nothing sets. So it never saw a print, and every
  press waited out fifteen seconds before the receipt was saved, which it
  still was, only later. The step meant to forget an earlier press's print
  forgot nothing, so a later press on the same page that printed nothing
  would have been handed the earlier receipt. Now the app asks the core,
  forgets any earlier print in the page and its frames before it presses,
  and moves on as soon as the print comes. Walmart looked for the frame a
  receipt printed from by the same old name, and never found one either.
  A check across the repository now fails any app that reads those marks
  itself rather than asking the core.
- **American Family finds a statement by the site's own mark (#45).** A
  tester's recording on 0.41.0 showed each statement opens from a link
  American Family marks statementPDF for its own tests, a link with no
  address and no words of a statement's own, and the app looked only for
  a button or link that said View bill or the like, so a Pilot on his
  billing page found nothing. That link is found by its mark now, with
  every other check kept. Every word it shows or announces has to pass
  the guard, a press lands on it alone, its date comes from its own row,
  and a row with two of them is left alone. A billing page with nothing
  to take now writes the failure file, where the Pilot had finished with
  nothing to send.
- **Meijer waits for the In-Store list before it looks for a receipt
  (#42).** Well into a tester's Run All the orders page drew only its
  heading, and the app looked for the tab once and for the receipt's row
  for about ten seconds, then recorded that purchase as having no
  receipt, which is final. Now it waits for the list and opens the page
  once more if the list does not come. A purchase whose list never shows
  is left for the next run, and three in a row stop the run with word to
  wait and press Resume. A receipt put aside in Manual Review is no
  longer reported as completed and verified when a Pilot skips it, and
  the Pilot report measures a put-aside file instead of printing question
  marks.
- **Target leaves the order list as it is while reading it (#48).** The
  press and hold check refused a tester's hold with nothing attached, so
  being attached at the hold was not the cause, and the likelier one is
  that Target had already scored the session as automated. The app now
  reads the orders page Login opened where it is, when nobody has clicked
  in it and it is fresh, instead of loading it again, and no longer puts
  its print hook on the order list it reads at the start of a run.
- **Walmart keeps an invoice that prints the order number its own way
  (#63).** A saved invoice has to name its purchase, and a Walmart invoice
  prints the order number with a hyphen in the middle and rarely says
  Walmart, so a tester's three invoices were put aside. The order number
  is accepted the way Walmart prints it, when the invoice came from that
  order's own page and shows an amount. A put-aside invoice writes a small
  failure file of counts and yes or no facts, and the Pilot report
  measures it. A run limited to dates, by --year, a start or end date or
  the default start date, dropped every online order, since Walmart's
  online cards show no date. Such an order is opened to read its date
  now, one outside the dates is left for a later run and not counted as a
  failure, and its date is remembered.
- **PayPal says where it landed instead of calling it a sign-in (#61).**
  On a tester's business account PayPal sent the statements address to
  the business settings page, and the app took every page outside the
  personal account for a sign-in page, loaded the address four times and
  stopped with a traceback. Now it loads once, and a PayPal page that is
  neither the statements, a sign-in nor a security check stops the run
  with a plain message that names the page and asks for a Record. A
  business account's statements are not covered yet.
- **Robinhood dates a tax form by its tax year and reads the crypto
  statements again (#62).** A tax form whose title line did not carry its
  year was named 0000-00-00. Its year is read from its card, the year
  shown above it or the year printed on the form, and it is filed on
  December 31 of that year, and Rename gives a form already saved that
  way its date without downloading it again. Forms of different years
  under one title had been counted as one, so only the first was saved.
  The Robinhood Crypto statements page, left out when the app was built
  on an account that does not trade crypto, is read again, and a crypto
  statement carries Crypto in its name.

## [0.41.0] - 2026-09-29

Vanguard, the sixty-first app, saves the statements of every account on
Vanguard's statements page, contributed by tylerverry. Kroger is
confirmed on a tester's account and names each receipt for its store,
Meijer presses a receipt twice before putting it aside, Target lets go
of the browser before its check is answered, American Family starts
where its statements are, and Walmart and Best Buy no longer report a
sign-in that never reached the order list.

### Added
- **Vanguard, the 61st app, account statements (#57).** Every statement
  the statements page lists, monthly and quarterly, for every account on
  it, an employer 401(k) among them. The statements are read from the
  page's own list while its year picker is walked, and each is saved by
  pressing its own row's download control, whose label passes the guard
  first. A scoped run never selects a year it does not want. Contributed
  by tylerverry, whose Pilot and full run saved 135 statements across
  five accounts back to 2020, every one a valid PDF, and whose second run
  downloaded nothing. Before release, the download was changed to take
  the file the browser saves. Once a browser's download folder is set, as
  this app sets it, the download event's own copy is empty and the
  browser's file in that folder is the only one, measured on Chromium 149
  to 153 and Edge 154. The contributed version took the empty copy and
  left the browser's beside it in the archive, and a first review fix
  merged to main took the empty copy too and then deleted the browser's,
  so neither saved a statement on those browsers. A pre-release review
  found two more. Every install's folder is relative, and a browser told a
  relative download folder cancels every download, so no install would
  have saved a statement, and taking the newest PDF in a folder the whole
  browser shares could save another tab's download under this statement's
  name. Now the browser saves into a staging folder of the app's own,
  given as a full path, only the file the download event names is moved
  into place, nothing is taken when the download failed or never began,
  nothing else in that folder is touched, and where setting the folder has
  no effect the event's own copy is saved. One case stays open. A
  download that begins more than 90 seconds after its press, which no run
  has shown, can be taken for the next statement. The tests drive a real browser against a local server, with a
  relative folder, another tab's download landing mid-wait, a signed-out
  page, a download cut off and a press that starts none. A statement is named
  for its account once, where the account had been named twice, and one
  already saved under the longer name takes the shorter one with Rename.
  Discover walks the year picker once instead of twice, and Diagnose
  reads the fields Vanguard sends and takes no screenshot of a page that
  shows every balance. Its own sign-in browser uses port 9282, since 9281
  is Uber's.

### Fixed
- **Kroger names a receipt's banner, reads only its items, and is confirmed
  (#41).** The tester asked for the store in his file names, Metro Market
  or Fred Meyer rather than what the receipt holds. The purchase list never
  names the store, and the app kept the purchase type where the store goes,
  so a {store} part of a name pattern said In-Store. Each receipt's store is
  now read off its own page, where the header names it, and kept as the
  store, so a pattern like {date:yyyy-mm-dd} {store|provider} {summary}
  names the banner. Receipts saved before take their banner the next time
  Rename runs, read off each saved PDF with nothing asked of Kroger. The
  Order Summary's Original Item Total and Order Total were also read as
  items on every receipt, since they print the way an item does, and the
  items are now read from Item Details alone, with how many of each from
  the line under its price, and Rename takes those two lines out of the
  order history the Purchases workbook is built from, where earlier runs
  wrote them. A pre-release review found that Resume then Rename renamed
  good receipts back to In-Store, since Resume works from a purchase list
  0.40 wrote and Rename reads the list over the record, and that the
  cleanup could take out a purchase whose only rows were those two lines. A
  store is now only ever one read off a receipt, and anything else, old
  labels included, is dropped wherever it is met, a purchase with no other
  row keeps one with its item left blank, and a Rename preview puts back
  whatever it read however it ends. His Pilot on 2026-09-23 saved receipts
  that read properly, so Kroger is supported, no longer waiting for a tester.
- **Walmart and Best Buy no longer call a page with no order list signed
  in.** Login no longer says Success on a page whose order list never
  appeared, such as one still behind a bot check, and a run's discovery
  stops there instead of finding nothing and finishing clean.
- **Meijer presses a receipt twice before putting it aside (#42).** The log
  said a receipt that failed the check that it mentions Meijer or the
  purchase was being retried, and on the path that presses the row's own
  receipt control it never was. That control is now pressed once more, and
  a second capture that also fails never replaces the first. A receipt put
  aside in Manual Review still counts as done while it is there, and
  deleting it from there is how to ask for it again, since trying it again
  on its own every run added a copy a run, and replacing an earlier copy
  could replace another purchase's (reviews before release). A receipt put
  aside there also writes the file to attach, saying how the PDF came and
  what it holds, as counts and a fixed list of words, with the reason in
  words of the app's own, never the check's text, which can carry a file
  path.
- **Target lets go of the browser before its check is answered (#48).** When
  Target's press and hold check came up during a run at a terminal, the run
  waited for the answer with the app still attached to the browser, and a
  check like that can refuse a hold in a browser under automation. Now what
  was read is saved, the app lets go of the browser, which stays open, and
  the run stops and says to reload the page, answer the check and press
  Resume. Resume discovers again first when the check came during Discover,
  where it had read only the purchases already listed and finished clean. A
  sign-in step, such as a code, still waits at the terminal, and a sign-in
  or a sign-in step answered partway through a purchase now opens its
  details again, where it had looked for the receipt wherever the tab was
  left and marked it No Receipt Available for good.
- **American Family starts at Billing & Payments (#45).** The tester's
  answers showed the statements are at myaccount.amfam.com/billing, in the
  same tab, and open in a new tab at a blob: address the page makes itself.
  The app started at a documents page, never matched a control reading View
  bill, and read a blob tab only by its address, which a page can revoke the
  moment the tab has it. Now it opens Billing & Payments and no other page,
  and presses a control only when the whole of its words is a read verb and
  a statement's name, such as View bill or View billing statement for
  September 2026, with nothing after it but a date, a policy's last digits
  or "opens in a new tab". So nothing that changes how statements arrive,
  online, by mail, by text or as reminders, is ever pressed, where a word
  anywhere in a label had matched "Get your statements online". Every word
  a control shows or announces has to pass the guard too, its label, its
  visible text, an image's alt, text a style adds, and a press is refused
  where another control sits at its center. A bare View or Download PDF is
  taken only from a row of its own that names a bill or statement and no
  other document or payment, never from a list whose summary names a
  statement. Of a row's several dates only the one written right before as
  the statement's own is taken, and none where another is written as the
  next or a previous statement's, so no statement is filed under another's
  date. A row and a control's words are read with a space between their
  pieces as well, since spans that touch run their words together, and a
  word run into a number, "10/01/2026Next bill date", had slipped past every
  check that looks for a whole word. A Show all that would leave the page is not followed, and a billing
  page that sends the tab elsewhere is not read. Each PDF the page makes is kept as it is made,
  through a small core module, paperpull_core.blob_capture, and only the one
  PDF the press opened is taken. After a press that brought nothing the page
  is loaded again, so a PDF the page opens late is never taken for the next
  statement. Closing an overlay presses only Close, Dismiss, No thanks or
  Not now as the whole of a control's words, where anything that began
  with Close was pressed, "Close my account" among it. A date printed right
  against the next word, the way adjacent tags leave it, is read as well.
  Still waiting for a run on a real account.
- **The recorder keeps a click on a control marked only with a test id
  (#45).** American Family marks its controls with data-cy and nothing else,
  and a click on the words inside one was thrown away as the mouse
  wandering, so the tester's recording of the billing tab kept one click of
  seven. Any of data-testid, data-test-id, data-test, data-qa, data-cy and
  data-automation-id now marks a control, and a click inside one is kept
  and found by its test id, never by its words. Neither is a container
  with a role that is not a control, a row or a region, and a container's
  aria-label counts as its words, since the words of a section of an
  account page are names, numbers and addresses, in a file testers post
  publicly. The check a person reads before posting a recording now sees a
  name joined into an id, such as holder-Invented-Person. A framework's prefix for generated ids, such as
  Angular's ng-, now counts only at the start of a value, where anywhere in
  it took billing-nav for a generated id.

## [0.40.0] - 2026-09-29

Uber, the sixtieth app, saves the receipt of every ride and every Uber
Eats order. State Farm names a document for the policy it belongs to,
Newrez is confirmed on a tester's account, and the README links the
Microsoft Store edition, which is now live.

### Added
- **Uber, the 60th app, rides and Uber Eats.** One app with two folders.
  Rides holds Uber's own receipt PDF for every trip where money was spent,
  and Uber Eats the same for every order, each fetched from inside the
  signed-in page the way its Download PDF link fetches it. A trip canceled
  before anything was charged and an order that cost nothing have no
  receipt and are skipped. The trips are read through the page's own
  GraphQL, three queries only, and a mutation is refused before it is sent,
  so Resend Receipt can never email anyone. The Uber Eats orders and
  receipts are read through two calls of the page's own, and everything is
  paced two seconds apart and nothing is pressed. A ride receipt is filed
  only when it carries its own receipt ID, and so is an Uber Eats receipt
  from December 2025 on. An older one prints no ID and is checked for its
  own date and total, and one that never prints the word Uber is still
  recognized by its total, its store and its date. After an hour or two
  idle the trips page's own calls answer
  a redirect while the sign-in is still good, so a side is called signed
  out only when loading its page once more does not bring the session
  back. Built and run on the maintainer's own account, 24 receipts, 7 rides
  and 17 Uber Eats orders back to December 2024. Uber's website only shows
  so much, about ten months of trips and two years of orders there.

### Changed
- **State Farm names a document for the policy it belongs to (#37).**
  The tester's Pilot saved a renewal notice for his auto policy and one for
  his home, and both were named State Farm Renewal Notice. The title says
  which, Renewal Notice - Auto and Renewal Notice - Homeowners, or the
  vehicle on an auto policy, and the file name now keeps it, State Farm
  Renewal Notice Auto. A receipt, whose title repeats its kind after the
  dash, and a tax form keep their names. A file saved under the old name
  is not downloaded again, since a document is remembered by its title,
  and the next Discover gives its record the new name, so Rename moves the
  file to it.
- **Newrez is confirmed on the tester's account (#38).** His run walked
  three years of the statements page's year picker and saved every
  document, so it moves from partly tested to confirmed.
- **The README links the Microsoft Store edition,** which is live, and no
  longer says the listing is in review.

## [0.39.2] - 2026-09-28

Golden 1 reads each account from its own list, State Farm finds a row it
has just opened, Meijer and Ally save what they found, and Target stops
for its own bot check instead of working through it.

### Fixed
- **Golden 1 reads each account's statements from its own list (#35).**
  The tester's Discover listed the credit card's twelve statements with
  the checking account's twelve dates, and the Pilot then looked for a day
  the card never had, since the card's list runs on the 20th. The history
  is one dialog for every account, its new list arrives a moment after it
  opens, and the app read the old one, most likely from the links of the
  closed dialog, which a lookup by words takes in. Before Statement History
  or NEXT is pressed every control is now marked, only a list drawn after
  the press is read, only links that show, and a list left from another
  account never is. NEXT is given twenty seconds where it had six, a NEXT
  drawn as a disabled link counts as the last page, and Discover prints how
  each account's list came, how many pages it read and why the paging
  stopped, with the words its heading carries from a fixed list, so the
  next report says what the card is called. A second account of one kind
  is told apart by the masked number in its heading, else by the words of
  its heading without numbers or months, and never by the whole heading,
  which can carry a balance that changes. The wrongly dated records from
  0.39.1 were never saved and are dropped by the next Discover.
- **State Farm finds the row it has just opened (#37).** The tester's
  Pilot found the Payment Receipt's row, pressed View Documents, saw the
  receipt appear, and then found no row with its date, so it pressed
  nothing. An opened row also says until when its document stays online,
  two years on, and the row was read as that day. A date after tomorrow is
  never a row's date now, in text from inside the control's own row. An
  opened row's View Documents looks past a container naming only such a
  day, only inside a row of its own, as his rows are, and only while it
  shows the document the row revealed, so a row is never dated by its
  neighbor. Two reviews tried pages his files do not show, a category drawn
  as one list item, a help link beside a folded row, a neighbor sent by
  mail with no control, a row that renames its button Hide Documents, and
  none saves another document under a record's name. The trace also says
  whether the page asked for its list again after the press, and how each
  View Documents read its date when the row was not found.
- **Meijer presses the receipt without crashing, and presses nothing
  else (#42).** Every receipt on 0.39.1 raised AttributeError before
  anything was pressed, since the download listener was a list's own
  append method, which Playwright cannot mark. That had been so since the
  press was written, so the press itself had never run on a real account,
  and two reviews of it found it would have pressed other controls in the
  row, an Email Receipt among them, a wrapper at its middle, or a hidden
  copy, and taken a November receipt for a January purchase whose date
  "1/19/2026" sits inside "11/19/2026". Only a link or a button that shows,
  holds no other control and reads as the row's receipt is pressed now,
  never one whose words or name send, share or print, and only on the one
  row that fits the purchase. A window the press opens blank is kept until
  it is filled, a download counts only from Meijer, and what the trace
  says about a row's controls is built from fixed words, since a store's
  street had reached it. A test in the core now fails any app that hands
  Playwright a built-in, or takes a listener off with an object other than
  the one it added.
- **Ally finds a statement posted on the 1st to the 9th (#56).** Ally
  writes "September 06, 2026", and the row was looked for as "September 6,
  2026", so every statement of the tester's, all posted on the 6th, was
  never found. Both spellings are looked for now.
- **Target stops for its own bot check (#48).** A tester's Discover met a
  "Quick verification" window asking to press and hold, and none of the
  words the app knew for a check was on it, so it kept paging and then
  reloaded the orders page while he answered it. The app knows that check
  now, at the end of a long page and inside the frame its button sits in,
  stops paging the moment it comes, and never presses it. A purchase the
  check hid is never recorded as having no receipt, which would have been
  final. Only the check's own words are read in frames, so a page's own
  reCAPTCHA badge does not stop a run.
- **Eight more apps know a press and hold check spelled with an
  ampersand.** Best Buy, Costco, eBay, Gap, Home Depot, Kroger, Lowe's and
  Meijer listed "press and hold" only, and compare the page's words as
  they are written. A test in the core holds every app to both.

## [0.39.1] - 2026-09-27

Every account's statements for Golden 1, earlier years for State Farm,
Apple accounts without Family Sharing and a record for the receipts
Apple will not give, with Apple Card and E*TRADE confirmed on a
tester's account.

### Added
- **Apple saves a purchase record for a receipt Apple will not give.**
  Report a Problem refuses the receipt of older purchases with its own
  internal error, every one before October 2016 on the maintainer's
  account, and its own page cannot show them either. Such a purchase is
  asked again on later runs, and once Apple has refused it on three
  separate runs, the app saves a record made from Apple's purchase history
  in its place, headed as not Apple's receipt, with the order ID, the date,
  who bought it, the total and each item. It is filed as a Purchase Record
  and checked for its own order ID like a receipt.

### Fixed
- **Apple reads an account without Family Sharing (#55).** Report a
  Problem answers the family list of such an account with nobody in it,
  and the app found whose purchases to search from that list alone, so a
  tester's Discover found nothing. It now asks which account is signed
  in, the way the page does on every load, and searches that account's
  purchases by its one dsid, the form the page's own code uses for it.
- **One receipt Apple will not give no longer stops the App Store side.**
  Report a Problem answered one paid purchase's receipt with its own
  internal error, a 400, while the session was fine, and the app read that
  as a sign-in and stopped at that purchase on every run. A refused receipt
  now counts as a sign-in only when the family list is refused too, and
  otherwise that purchase is tried again next run while the rest are saved.
- **The terminal command writes UTF-8.** Output headed for a file or a pipe
  was written in the Windows code page, and printing a receipt named in
  Chinese failed that purchase. The panel always set UTF-8 for the apps it
  runs, and the terminal command now does the same.
- **Golden 1 reads every page of every account's statements (#35).** A
  Pilot on the tester's account saved five checking statements, and his
  recording showed why the rest were missed. The vendor keeps one panel
  per account, the credit card's included, each with its own Statement
  History, a dialog of twelve statements a page with NEXT under the list,
  and the app read the first panel's first page and nothing else. It now
  opens each panel, a closed one through its own heading, reads every
  page by NEXT, and names a card's statements Credit Card Statement. A
  download goes back to its statement's own panel and pages to its date.
  Statements saved before keep their names, so none is fetched twice. The
  guard no longer refuses a card statement, which it did twice over, by
  the bare word card and by reading edit inside Credit.
- **State Farm asks for each earlier year the way the page does (#37).**
  The tester's Discover on 0.38.0 showed the page's own read of the list
  answering with four documents, while every year the app asked for, the
  current one included, answered 401. The app asked with its cookies and
  nothing more, and the page's own call carries headers of its own. Each
  year is now asked with the headers the page's call sent, never a
  cookie, and Discover says how many there were and whether an
  authorization was among them, never what they held.
- **review_names leaves a receipt you renamed alone (#47).** Renaming a
  receipt marked it Completed and left its confidence Low, so the next
  review asked again about every receipt already renamed, in all thirteen
  receipt apps. A renamed receipt is now marked High as well, and one
  renamed on an earlier version is told apart by the note every rename
  leaves, so only the receipts kept as they were are asked about again.

## [0.39.0] - 2026-09-27

Apple, the 59th app, saves a receipt for everything paid for through
Apple, and two more repairs from the tester's runs of 0.38.0.

### Added
- **Apple, the 59th app.** Receipts for everything paid for through Apple,
  in one app with two folders. App Store holds a receipt for every paid
  purchase in the family, subscriptions such as Apple One and iCloud+,
  in-app purchases on a child's account in Family Sharing, and paid apps,
  songs and movies back to the iTunes years, each saved from Apple's own
  receipt. Free downloads are skipped. Apple Store holds the invoice of
  every hardware order, and a canceled order is recorded with no receipt.
  It reads Report a Problem's purchase list and each receipt from inside
  the signed-in page, and the store's order pages, and presses nothing.
  Built and run on the maintainer's own account.

### Fixed
- **Apple Card takes a statement where the page builds it (#52).** On the
  tester's Chrome both August statements downloaded, twice, with Chrome's
  own download menu open, and the app saw neither copy, so the newest
  statement of each list went unsaved. The app now keeps the PDF the page
  makes for the download and saves that, whatever the browser does with the
  download itself, and checks Apple's name for it as before. A PDF another
  Apple host hands the page is caught the same way.
- **E*TRADE reads a statement out of the site's own answer (#36).** A Pilot
  on the tester's account saved two of four statements. Pressing a
  document's link makes the page ask E*TRADE for it, and the answer is JSON
  with the PDF inside it, which the page then hands to the browser as a
  download. Two of those downloads never reached the app. It now takes the
  PDF straight out of that answer, which belongs to its own press the way
  a download does not, so the answer also wins over a download that starts
  while the app waits. An answer with no PDF in it is described in the
  attempt file by its shape alone.
- **Names like iCloud, iPhone and eBay keep their spelling in file
  names.** A word with a small first letter and a capital second one was
  capitalized into ICloud+ and IPhone. Rename brings older files in line.
- **Costco writes its failure file when a receipt page will not open.**
  The second failed attempt passed the failure writer an argument it does
  not take, so the run raised an error there instead of writing the file
  and moving the purchase to Manual Review.

## [0.38.0] - 2026-09-27

The double-click file for fixing receipt names is back and reaches the
installed app's folders, Windows installs get their terminal command, Mac
double-click files open, and two more repairs from the tester's runs of
0.37.1.

### Added
- **review_names is a double-click file again** in the twelve receipt
  apps, Amazon, Best Buy, Costco, eBay, Gap, GitHub, Home Depot, Kroger,
  Lowe's, Meijer, Target and Walmart. It went away with the other per-app
  launchers on 2026-09-15 (#23), but it asks for one name at a time and so
  cannot run in the panel, and the terminal command in its place was not
  on anyone's PATH in the installed apps (#47). In a checkout it runs on
  the folder's own Python. In a folder the installed app made, which has
  no setup file, it runs on the app's own Python, so those folders get it
  too, new ones at once and existing ones the next time the panel opens.

### Fixed
- **Windows installs have their terminal command again.** The panel's
  launcher was a batch file named PaperPull.bat, and Windows does not tell
  that name from paperpull.bat, the terminal command, so every Windows
  package since 0.19.0 had the panel launcher under both names and no
  terminal command at all. The Start menu and desktop shortcuts now open
  PaperPull.exe, which the installer already carried, and paperpull.bat is
  the terminal command the docs describe. Double-clicked with nothing after
  it, paperpull.bat still opens the panel, so an older shortcut keeps
  working. Its exit code is now the command's, where it used to report
  success every time.
- **Mac double-click files open.** The setup and login files of the 36
  apps generated on a Windows machine reached every Mac without the
  executable bit, so a double-click refused them. All of them carry it
  now, and a test refuses one that does not.
- **Newrez reads every year of statements (#38).** The statements page
  shows one year at a time, with a year picker above the list, and the app
  only read the year it opens on. Discovery now chooses each year the
  picker offers and reads its list once the list on screen is that year's,
  and an older statement is pressed only on its own year's list. Choosing
  a year is the only new thing the app does on the page. A December
  statement and that year's 1098 share a date, so documents are now told
  apart by kind as well as by date.
- **State Farm finds a redrawn row again, and asks for earlier years
  (#37).** Pressing a row's View Documents draws that row anew, and the
  app, still holding the old button, could not tie the revealed document
  to its row and saved nothing. It now finds the row again by the
  document's date and presses the document only when that one row holds
  it. The page's own list request carries a year setting that is not a
  four-digit year, so the year walk never asked for an earlier year. It
  now replaces that setting whatever it holds, and an older document is
  looked for on its own year's list.

### Documentation
- AT&T is confirmed on two accounts, wireless and internet, with a full
  run on each (#26).
- Newrez is partly tested, this year's statements and the 1098s download
  on a real account (#38).

## [0.37.2] - 2026-09-27

The first signed Windows release, and one repair from the tester's runs
of 0.37.1.

### Changed
- **Windows builds are signed.** The installer, and the PaperPull.exe
  inside it, the portable zip and the MSIX, carry the maintainer's Azure
  Artifact Signing certificate and a timestamp, so Windows names the
  publisher instead of calling it unknown. SmartScreen can still show its
  prompt while the certificate is new, since it learns to trust a
  publisher from downloads over time. The release workflow signs through
  the repository's own environment with no key stored anywhere, and a
  build that should be signed and is not stops before anything is
  uploaded. See [docs/code-signing.md](docs/code-signing.md).

### Fixed
- **Apple Card presses a button again when the press did nothing
  (#52).** The first Pilot on a real account saved three of five
  statements. The two it missed were each the first press on a list the
  app had just opened, card and Savings alike, which produced no
  download, no file and nothing new on the page, while every later press
  on the same list downloaded at once. A press that produces nothing at
  all is now made once more on the same button, found again by its name,
  and a press that puts anything new on the page is never repeated. The
  tax year a form's button names is now confirmed against the year
  printed on the form.

### Documentation
- PG&E is confirmed working again on a real account (#33).
- Costco's gas receipt reader was checked against the exact order a
  member's second paste kept, and reads it (#47).
- The README gives the terminal command inside the installed Mac app.

## [0.37.1] - 2026-09-26

Eight repairs from one overnight round of tester reports, every one of
them run on 0.37.0. Each fix was reviewed independently for whether it
answers the evidence and whether it could press anything unsafe or save a
document under another's name, and repaired until it passed.

### Fixed
- **AT&T reads past the first eight bills (#26).** The bill history shows
  bills eight at a time with Prev and Next, and the app only ever read the
  first page, so every older bill went to Manual Review. It now presses
  the list's own Next, works out each batch's years from the bills before
  it, and presses a bill only while the list still reads as it did when
  the bill was found. Earlier rounds aimed at the Date range, which the
  tester's recording showed changes nothing.
- **Apple Card follows the site as it is built (#52).** The first real
  recording showed card.apple.com draws each section when its link is
  pressed and answers every guessed address with a 404. The app now loads
  only the front page, waits for the menu, and follows the recorded links
  to card statements, Savings statements and tax forms. It reads only
  buttons named the way the site names them, refuses a list left over from
  before a press, and checks Apple's own file name against the document
  asked for.
- **Costco names a gas receipt (#47).** A fuel receipt has no item
  numbers, so it read no items and was named Mixed Purchases. The app now
  reads the Gas Station Receipt heading and the fuel line.
- **E*TRADE saves each document from its own row (#36).** Discovery walks
  every period, and the download then looked for documents on the empty
  oldest year it left on screen. It now shows each document's own period,
  and where several documents share a date it presses only the one its row
  names, never a notice or insert beside it.
- **Golden 1 reaches the statements tab from any page (#35).** Starting
  anywhere but the documents page, the app pressed the sidebar link, which
  opens no tab, and gave up, so a stale entry was tried first every time.
  It now waits on the documents page for the accounts to load, presses the
  button once, reads only the tab its own press opens, and no longer takes
  dates from the bank's own pages.
- **Newrez waits for a slow statement and names files by the printed date
  (#38).** A statement slower than 25 seconds failed. The app now waits
  longer while a download is visibly on its way, takes more care that a
  late download is not taken as the next statement, and names each file
  for the date printed after Statement Date. Records keep their identity,
  so nothing downloads again, and Rename can bring older names in line.
- **PG&E presses View Bill PDF (#33).** Since 0.19.0 every control's label
  read as blank, because of a Playwright call given an argument it does not
  take, so the safety check refused every View Bill PDF. Labels now read
  correctly, the check judges every label a control carries and everything
  around it, a bill is taken only from its own row, and a download counts
  only when it is the one that bill's save started.
- **State Farm waits for the Document Center to draw (#37).** The app
  looked for a document's row about a second after reloading, before the
  rows existed. It now waits for them, keeps each document's file address
  from discovery instead of discarding it, and presses a document revealed
  by a row only while it sits inside that row, and takes a PDF only from
  its own tab or one its press opened.

## [0.37.0] - 2026-09-26

Five new providers built and run in full on real accounts, two more built
and waiting for someone who uses them, and a run that stops now says so.

### Added
- **Best Buy.** Online orders, orders placed in a store, store purchases
  and returns, back to 2015, each details page saved as the receipt. Best
  Buy's own purchase list shows only what is on screen, so the app reads
  the history through the page's own query a year at a time. It is paced,
  because Best Buy stops answering a session that asks too quickly. 35
  purchases found and all 35 saved on the account it was built on.
- **E-ZPass Virginia.** Monthly and quarterly toll statements from the
  customer portal's own list. About a year of each is online, so the
  README says to run it at least once a year. 16 statements saved.
- **PayPal.** Monthly statements for the three years PayPal keeps online,
  from the site's own list and download. 25 statements saved.
- **UPS.** Shipping invoices from the UPS Billing Center. Each is asked
  for exactly the way the page's own code asks, including the invoice type
  it translates from a code to a word. Both invoices on the account saved.
- **MILITARY STAR card.** Monthly statements from MyECP, the Exchange
  Credit Program's site. The site numbers a statement by its place in a
  list that moves every month, so the app knows each one by its date. 25
  statements saved, back to April 2023.
- **Stripe, waiting for a tester (#53).** Fee invoices and tax forms from
  the merchant Dashboard. Built on a real account that has no documents
  yet, so no document has been seen.
- **FedEx, waiting for a tester (#54).** Shipping invoices from FedEx
  Billing Online. Built from a login not connected to Billing Online, so
  no invoice has been seen. It never fills in FedEx's connect form.

### Fixed
- **A run that stops says it stopped.** A sign-out in the middle of a run
  under the panel, where nobody can answer the prompt, used to end with
  all zero counts and "finished, no issues reported". It now shows
  "stopped before finishing" and says to press Resume. All 57 apps could
  stop that way, and it is fixed once for all of them.
- **Renaming leaves a file alone that is already told apart by its
  number.** A file named with its order number was moved to a " (2)" it
  did not need.
- **MILITARY STAR, E-ZPass Virginia and PayPal notice an idle session.** A
  tab left on the site still looked signed in after the session had timed
  out, so the run crashed instead of saying to sign in again. Each now
  loads its page fresh before reading the list.

## [0.36.0] - 2026-09-25

Two home improvement stores, each built on a real account and run in full
against it, and Costco returns.

### Added
- **Lowe's.** Store purchases, online orders and returns, from the purchase
  history back to 2023, each purchase's details page saved as its receipt
  with the store, items, model numbers, discounts, card and totals. The
  history is read by address with nothing pressed, and each receipt is
  checked against the purchase it was opened for. 41 purchases found and
  40 receipts saved on the account it was built on, the other a canceled
  order. Home-improvement categories for the filenames.
- **Home Depot.** Online orders, and store purchases where the history
  lists them, Home Depot's own print receipt with model and store SKU
  numbers, taken without ever opening the print dialog. Home Depot keeps
  two years of orders online and refuses anything older, so the README
  says to run it every few months. 8 orders found and 6 receipts saved,
  the other 2 canceled, and a returned order keeps its receipt.

### Fixed
- **Costco collects a return (#47).** A return's control reads "View
  Return Receipt" and the row reader looked only for "View Receipt", so
  returns were never collected. A gas purchase Costco types as fuel is
  named for it.
- **A provider's name is read whole when it holds an apostrophe.** The
  panel, the status tool and the migration tool read "Lowe's" as "Lowe".

## [0.35.0] - 2026-09-25

Name your files your way, a forty-ninth provider, and three tester
repairs.

### Added
- **Custom file names (#50).** The panel's new File names tab builds a
  pattern from parts, the date in any shape, the provider, the order or
  document number, the account, the total, the store and more, each
  shown with how many of your own files carry it. A part can be skipped
  when a document lacks it, so no name ends in a stray separator, and the
  three newest files are previewed under the pattern as you type. One
  pattern covers every receipts app or every statements app, and any app
  can have its own. Every config it changes is backed up first. The
  default names files exactly as before, checked against 18,908 real
  names with none different.
- **Rename to match.** After a save the tab offers to rename the files you
  already have, a preview of every file first, then the rename, one app
  and account at a time, stopping at the first that does not finish.
  Nothing is downloaded again.
- **Apple Card and Apple Savings (#52).** Card and Savings statements and
  the 1099-INT. Built without an account and waiting for a tester.
- **A wrong document is reported on its own.** When the identity check
  refuses a document, the output says so in a sentence and the panel
  names it first, instead of counting it as "needs review".
- **Every failure file carries a journal**, even when the run failed
  before saving anything, which is the run that needs one most.

### Fixed
- **Meijer looks for an in-store receipt on the In-Store tab (#42).** It
  reloaded the orders page, which opens on Online Orders, and looked for
  every in-store receipt there. It opens the right tab now and matches a
  row on its date too. The dateless copies an earlier version recorded
  are dropped, and purchases marked as having no receipt are tried again.
- **E*TRADE finds its period picker (#36).** The dropdown's real name
  carries its label, "Timeframe, Last 90 Days", so it was never found and
  every round read only the default ninety days. It now walks Year To
  Date and every year back.
- **A recording names a control inside a web component (#45).** A click
  inside one reached the recorder as the component around it and was
  thrown away. A click that still cannot be named now says what kind of
  element it landed on and where.
- **Rename builds names from the app's own record.** It used the index row
  alone, which would have left an order number or account out of every
  renamed file under a custom pattern. Apps known by a document id find
  their records now, and a split order keeps its "(1 of 3)".

## [0.34.2] - 2026-09-25

Five tester repairs from one night of reports, and the safeguard that
would have stopped 0.34.0's breakage from ever shipping.

### Fixed
- **PG&E presses View Bill PDF once.** A press that opened no tab was
  pressed again, which opened a second dialog on his account, and the
  wait for a download slept through the events it was waiting for. It
  now waits for the bill's viewer, and reads a bill that Salesforce
  hands back as base64 text inside its own answer, which is the one
  place nothing was looking (#33).
- **Newrez waits for its statement list.** Each document reloaded the
  page twice and read it before Newrez had finished signing back in, so
  one statement in five happened to work. A 1098 is looked for on the
  yearly page, where it lives (#38).
- **State Farm no longer looks for documents from 2028.** Old records
  filed under the date a document stays online were tried first. They
  are cleared, nothing can be dated in the future, and the document that
  appears under View Documents is pressed (#37).
- **Golden 1 takes a statement's date only from the bank's dated
  links.** A date printed near a View PDF control named a statement the
  bank never listed, and a saved statement that does not show its date
  goes to Manual Review instead of Statements (#35).
- **AT&T brings back the 2025 bills that 0.34.0 filled with 2026
  copies.** A record whose bill a year later has exactly the same size
  and page count is cleared so the real bill is fetched, and the copy is
  moved to Manual Review. The Date range control now records what it
  shows when pressed (#26).
- **AT&T's Date range goes through the dropdown filter** that every
  other app uses, which 0.34.1 skipped.
- **Costco counted a refused wrong receipt as an ordinary failure.**
- **Two found by a review before this release.** PG&E could have saved
  the viewer an earlier bill left open under the next bill's date when a
  press brought nothing new, and it now fetches only what is new. AT&T's
  Date range trace kept masked text of anything that appeared, which let
  a name, a street and a phone number through in a test, and it now keeps
  only a date filter's own words and reports everything else by length.

### Added
- **Every app on the shared capture code runs its real download path in
  a test.** A stand-in for the capture holds every call to the real
  arguments, so a mistake like 0.34.0's fails in the test suite instead
  of on an account. A new check fails any app that captures without one.

## [0.34.1] - 2026-09-25

A repair release. 0.34.0 broke four providers outright, and an
independent review of the new code found more behind them. Every one
was reproduced before it was fixed, and every fix has a test that fails
without it.

### Fixed
- **T-Mobile, Navy Federal, Target RedCard and Fairfax Water failed
  every document in 0.34.0.** Each passed a setting to the new capture
  code that it did not accept, so every request raised an error before
  anything was clicked and a whole run saved nothing. None of their own
  tests called that path. A new test reads every app's calls into the
  capture code and checks each against what it accepts.
- **Navy Federal could refuse and delete a correct statement.** It was
  checked against its date alone, which it shares with every account
  billed that day, so a Checking statement that named the card it paid
  lost to the card. It is checked against its account as well now, the
  way the measurement that turned the check on was made.
- **Costco could file a receipt that was never checked.** When the
  checked print failed, a retry printed the page straight to the final
  path, outside the check, and marked it verified.
- **T-Mobile and RedCard gave up too soon.** The new capture code waited
  twenty seconds where they had waited sixty and forty five, and RedCard
  presses a statement again when nothing arrives.
- **A locked folder read as nothing arriving.** A sync client or a virus
  scanner holding the file made RedCard press the statement a second
  time, and the move had already deleted the file it was replacing.
- **A check that could not be made took the download down.** An amount
  that was not a number raised, and left a half finished file behind.
- **AT&T could not reach bills older than its history showed.** The
  history lists the newest bills until its Date range is widened, and
  four bills on each account failed. The Date range is opened now, and
  only a narrow list of its own words may be pressed (#26).
- **AT&T could save a bill under the date a year earlier.** A bill
  button carries no year, and matching on the month and day alone meant
  asking for August 2025 while August 2026 showed pressed 2026. Each
  button's year is worked out from its place in the list now, and only
  the exact date matches (#26).
- **The wait helper let an app write its own check of readiness.** It
  could have reloaded the page, or waited thirty seconds each time it
  was asked, outside the time the wait was given. The checks are built
  by the helper now, and a page that comes right early ends the wait.
- **A recording lost its way inside a web component**, and a page could
  write text into a recording through a step's time.
- **The round count said the loop was stalled on the maintainer** when
  two issues were waiting on their tester, and missed GitHub's first
  working Pilot.

## [0.34.0] - 2026-09-24

A document is checked against the row it was listed under before it is
filed, and one place catches it however a provider hands it over. Plus a
long sweep of faults found by asking the same question of all forty
eight apps at once rather than waiting for anybody to report them.

### Added
- **Whether the document is the one that was asked for.** The realistic
  failure here is not saving nothing. It is saving the wrong thing under
  the right name, from a row index off by one, a selector that matched a
  neighbour, or a dialog that did not close so the next capture re-read
  the last document. Each writes a valid PDF to a correct-looking path
  and reports success, and nobody finds out until a tax year is being
  reconciled. `validate_pdf` looked like it checked for this, since it
  takes expected tokens, but it is satisfied when ANY appears and the
  first it is usually given is the provider's own name, which every page
  of every statement carries. Of its 148 call sites, 129 passed no
  tokens at all.
- **The check compares rows rather than checking one.** Asking whether a
  document mentions its row's date gets a yes from the wrong document,
  and four real archives said so. Navy Federal bills every account on
  the same day, so eight dates there carry more than one statement.
  Every Fairfax Water bill prints the previous bill's date beside its
  own. Requiring every fact to match instead is worse, because eight of
  twenty five TSP documents do not mention their own date at all, a
  mailbox row being dated when the document was delivered rather than by
  anything printed on it. So a fact counts only when no competing row
  shares it, and then it is a matter of how many. The July Fairfax bill
  carries April's date, so April scores one, and it carries July's
  amount too, so July scores two and April is refused. A document that
  prints none of this is left unchecked, which is not the same as
  belonging elsewhere. Measured over 174 documents in four archives,
  none refused.
- **One place that catches a document, however it arrives.** Seven ways
  a provider hands one over, counted across the apps, and twenty of the
  forty eight already tried three or more because which one a provider
  uses is not knowable before a live run. There were eleven near
  identical copies of the catching code, between 139 and 155 lines each,
  and 109 places in the app layer that wrote bytes to disk. A trigger
  cannot be retried, since it is a click on somebody's bank, so every
  way of catching a document is armed before it fires once and the race
  is read afterwards. Everything lands on a staging file beside the
  destination and moves into place only after it is checked, so a wrong
  document is destroyed rather than filed.
- **Six providers moved onto it and were run against real accounts.**
  Costco, T-Mobile, Navy Federal, Target RedCard, Fairfax Water and TSP,
  covering every way a document arrives. A printed page, a download
  event, a blob tab, an answer read in flight, and an app that fetches
  its own bytes with headers only it knows.
- **Waiting several ways, and saying which one the page needed.**
  `paperpull_core.ready` tries the guesses in order against one budget
  and records which worked. It only ever waits, never clicks or reloads,
  and a page counts as ready only when a required check says so. The
  answer goes into the journal, the failure file, and one "Waited for"
  line in the run's output, which the tester guide now asks people to
  paste. No app uses it yet. It is adopted per provider in its next
  round.
- **A recording carries the shape of the page.** Element kinds,
  attribute names and counts around each step, never text or values,
  built from fixed lists in the page and again in Python. The privacy
  canary gained fourteen more planted secrets, in attribute values and
  names, a custom tag, a shadow root and deeply nested text, and none
  reaches a recording or a failure file. `tools/read_recording.py`
  prints the shape as an outline.
- **Counting the rounds from the record.** `tools/rounds.py` reads how
  many trips around the repair loop each tester-built provider has
  taken, from git and from the issues, three ways, and says where the
  counts disagree. `--as-of` reads the record as it stood on an earlier
  day. Three providers have reached a working Pilot through a tester, at
  a median of six rounds, and all twelve still in progress are waiting
  on the maintainer. The baseline is in docs/failure-diagnostics.md.
- **Two tools for deciding rather than guessing.**
  `tools/delivery_census.py` says how each provider hands a document
  over, and `tools/identity_fit.py` says whether the wrong-document
  check can be trusted for a provider before it is switched on there.

### Fixed
- **A setting a provider gained never reached an install that already
  existed.** config.example.json becomes config.json once, when an
  install is made, and was never looked at again, so a setting added
  afterwards reached new installs only. The wrong-document check was
  switched on in six templates and off in all six installs on the
  machine running them. Missing keys are added on refresh now, a value
  somebody changed is never touched, and the config is backed up first.
- **Thirty-four apps could not read a date with a time after it.** The
  ISO pattern ended in a word boundary and there is none between the 4
  and the T in 2026-03-04T12:00:00Z, so the date came back empty. Plenty
  of these apps take their dates straight from a JSON API, where that is
  the ordinary way to write one.
- **Eleven apps read 12/31/99 as the year 2099.** All eleven came from
  one scaffold and none of the other thirty seven read a short year at
  all, so the two were never compared. The check that refuses impossible
  dates had nothing to say, because 2099 is a perfectly possible year.
- **Eight apps could not page forward, because Next is a forbidden
  word.** Every blocklist here refuses "next", rightly, since that is
  what a wizard's commit button says. Eight apps handed their pagination
  control to that same blocklist, so the run finished and reported
  success having seen the first page.
- **Two cards of the same product were one document, in thirty two
  apps.** A document is remembered by category, date, title and account,
  and the account was cut to forty characters, which is before the
  masked last four that tells two cards apart. The second card's entire
  history read as already downloaded and was dropped on every run, and
  nothing said so.
- **Forty-seven apps stopped with the wrong advice when the panel
  pressed a button.** The panel runs an app with stdin closed, on
  purpose, so a stray prompt cannot hang a run. An app calling input()
  there was told to run it from a real console window instead.
- **Two settings nearly every app reads and almost no template showed.**
  `browser` decides whether this drives a Chromium you already have,
  uses its own, or downloads four hundred megabytes, and forty two apps
  read it while five templates mentioned it. `default_start_date` is how
  you say you already have everything before a date.
- **Five apps said they were signed in on a page that had closed.**
- **Four apps had a URL guard that nothing ever called**, three set a
  dropdown without deciding it was safe to touch, and two refused to
  click the documents they collect.
- **The panel told people to attach the wrong file**, twice, and a
  provider's own page named a file that is not the one a failed run
  writes.
- Walmart's pagination under another name, UKG's Diagnose never writing
  more than five fields, Target launching its own browser, eBay trusting
  a filter it should not, Rename reading the name a file was given
  rather than the one it should have, and thirty lines in two apps that
  have never run.

## [0.33.0] - 2026-09-23

Two testers' reports, the tests running in CI at last, and four things
found by looking rather than by anybody reporting them.

### Added
- **The tests run on every push.** Four thousand of them lived here and
  nothing ran them, so whether a tag shipped with a passing suite
  depended on whoever cut it remembering, and on which interpreter they
  happened to use. A release cannot be the first time the tests are
  asked. A run where the canary skipped is not counted as green either,
  since the canary is what proves no secret escapes a diagnostic file.
- **Renaming what is already downloaded.** Every app takes `--rename`,
  and the panel offers it under "more" as two buttons, Rename preview
  and Apply renames. A naming scheme improves and the files on disk keep
  the old one. Nothing about them needs fetching, so nothing is asked of
  the provider. It is a preview until you apply it, it only touches
  files the app's own records know about, it never overwrites, nothing
  moves between folders, and running it twice does nothing the second
  time (#43, #49).
- **A collision is told apart by the order number.** Two purchases on
  one day were one name, settled with " (2)", which says nothing about
  which purchase it is and is not stable, since it depends on what is in
  the folder at that moment. Delete one file and the next run gives that
  name to a different receipt. The order number goes in the name now and
  the numbered suffix is the last resort. A name that does not collide
  is untouched (#49, #43).
- **A recording follows the provider into a tab it opens.** Every
  listener was on the first tab alone, so a tester who pressed a control
  that opened a tab sent a recording one step long, and everything after
  that was invisible. On a site that opens a tab that is everything
  worth recording. A tab on somebody else's host is still left alone,
  because a checkout opens a payment processor (#45).

### Fixed
- **A website you are visiting could start a download run.** The panel
  listens on 127.0.0.1, which keeps other machines out and does nothing
  about the browser already running on this one. Its guard read Origin
  and Referer and abstained when neither was there, and neither has to
  be there. A request carrying no origin at all is refused now.
- **One fetch in the project skipped the host check.** The headless
  fallback renderer took an address that came from the page and opened
  it carrying the signed-in state, with no check that it was the
  provider's. It asks the app's own guard first now, like every other
  fetch here.
- **Thirty-seven apps would have filed a document under a reference
  number.** A date is four digits, a dash, two, a dash and two, and so is
  "Reference 1234-56-78". A date has to name a day that exists now, which
  also rules out "Policy 2026-99-01" and a February the thirtieth.
- **eBay found two of nine, and the repair for it could never have
  worked.** It looked for a card's order number in each element's own
  text nodes, and eBay writes it inside a nested element, so on a real
  purchase history that matched nothing on any account. A row's whole
  text is read now. Diagnose also surveys the purchase history itself,
  which it never did, so a run that finds fewer orders than you made
  says which step lost them rather than leaving it to be guessed (#44).
- **Target opened a browser window and shut it again.** It asked you to
  press Enter when you had signed in, the panel closes an app's stdin so
  a stray prompt cannot hang a run, and that read end of file and took
  the process down with the window still open behind it. Waiting for a
  sign-in is one thing in the core now. With nobody to ask it grants
  nothing, leaves the browser open and says which button to press next
  (#48).
- **Meijer told an account with receipts that it had no orders.** "You
  haven't placed any orders yet" is the Online tab saying so, and that is
  the tab the page opens on, so asking before opening the other tab
  answered for the wrong one. A recording also corrected a guess, the
  receipt control being a link reading "view receipt pdf" rather than the
  icon with no text round two was built for (#42).
- **A browser that would not start ended sign-in with a traceback**
  rather than moving on to the next one sitting there ready to be tried.
- **A recording could start on a sign-in page.** Of the three things
  asked before it will, the last swallowed its own failure, so a page
  that would not answer left the question unasked and recording began.
- **A progress file of the wrong shape was quietly replaced.** A
  truncated one was already recovered from a backup. Valid JSON of the
  wrong shape, a list or a bare null, fell past the check with no backup
  at all, and that file is the only thing that knows a document has
  already been fetched.
- **A second person's config travelled with the code.** An install is
  brought up to the shipped version by copying, and three names were
  excluded from that by hand. A second account is `config.<label>.json`
  and no list knew about it.
- **A button that works on one provider and not another.** The panel
  sends the same flags to all forty-eight apps, and an app whose parser
  had never heard of one answered with a usage message and exit code 2,
  which reaches you as a button that does nothing.
- **Paylocity and UKG could not tell when they were being throttled**,
  so a payroll system that had said "too many requests" looked like an
  ordinary page with no documents on it, and the run would keep asking.
  A payroll system is the worst place to keep asking after it has said
  no.

## [0.32.0] - 2026-09-23

0.31.1 built a file that a failing run writes by itself and gave it to
one app. This gives it to all forty eight, gives the eleven that drive an
API rather than a page something to put in it, and tells the person
running the app that it exists, which 0.31.1 did not. Seven testers'
reports are repaired here too, two of them from the first recordings
anybody has sent in.

### Added
- **Every app keeps a journal.** 0.31.1 wired one into Costco only. All
  forty eight record what the app was about to do, which collection it
  chose from and which item of it, how many times each step had already
  run, and the state of the page at each checkpoint. A run that opened
  twelve documents and rendered none stopped between opening and
  rendering, which is one line in the file rather than a round of
  guessing.
- **A census of the provider's own calls, for the eleven apps that drive
  an API instead of a page.** Those apps look for nothing on a page, so
  the selector census had nothing to say about them and their failure
  file carried a page state and little else. They now record which calls
  answered and what came back. The address with anything account-shaped
  in it replaced by a hash mark, the method, the status, the kind of
  answer, the names of the query parameters, and the field names of a
  JSON answer with the type of each value. That tells a session that
  ended from an address that moved, and an account with nothing in it
  from a filter that excluded everything, neither of which could be told
  apart from outside before. Field names are the provider's schema and
  the same for every customer, except when the keys are account numbers,
  which happens, so a key that looks like an identifier is masked the way
  a path segment is. No value is kept, only the name of its type, and a
  response from anywhere but the provider is counted and never described.
  Thirty five tests, one of which puts a fake secret in every position a
  JSON body has and fails if any of them reaches the file.
- **The tester is told the file exists.** This was the half of 0.31.1
  that was missing and the half that mattered. The file wrote itself, the
  run printed a path, and nothing else said a word. The walkthrough did
  not mention it, none of the forty eight app pages mentioned it, and the
  three lines a failing run printed did not say to send it anywhere. The
  run now says what the file is, reads out what it noticed, and says to
  attach it to the provider's issue. The control panel shows a **Show the
  file to attach** button when a run leaves one, which opens the folder
  with the file selected rather than leaving a path on screen. The
  walkthrough has a section on what is in the file, what is deliberately
  not in it, and how to read it before sending it, and every provider
  still looking for a tester says the same on its own page. A test fails
  if a provider asks for a tester without telling them, which is how this
  went out unnoticed the first time.

- **A sample archive, so you can see what PaperPull produces before you
  point it at a bank.** The welcome screen now offers *See a sample
  archive*. It builds a folder of invented statements and receipts, five
  providers, and opens the panel on it. The Status tab fills in, with one
  archive overdue and a two-month gap in the middle of another, and both
  spreadsheet buttons build real workbooks from it, 479 transactions read
  out of the PDFs and reconciled against their own printed balances, and
  468 purchases across 190 orders. A yellow bar says what you are looking
  at, nothing can be downloaded, created or removed while you are in it,
  and *Leave the sample* puts you back on your own archive, which was
  never touched. Every document in it says on its face that it is a sample
  and that every name, amount and date is invented.

  It is also the answer to a fair question from anyone reviewing the
  program, including the Microsoft Store, who cannot test a downloader
  without an account at a bank. Nobody should have to hand over real
  banking credentials to see this work.

  The archive is written by `tools/make_sample.py` when you ask for it,
  from a fixed seed, in about a tenth of a second. Nothing generated is
  committed or carried in the installer, because a tree of files named and
  shaped exactly like real statements is the thing this repository's
  .gitignore exists to keep out.

### Fixed
- **SMUD said two different things about itself.** The README called it
  working and the panel called it untested. They agree now, and a test
  checks that they agree for every provider rather than for that one.
- **Every failure file so far said nothing about which build wrote it.**
  The version was a parameter no app passed, in all forty-eight of them,
  and it is the one field that says what a tester was running. It is
  worked out instead of asked for, from the panel when the panel started
  the run and from the checkout otherwise, and anything that does not
  look like a version is not written down.
- **PG&E would not save a bill it had found.** Discovery reads all
  twenty-five now, and capture then pressed View Bill PDF and lost what
  came back. The control can move the tab itself rather than open one,
  and then there is no popup, no download and no answer this tab was
  listening for. A tester's failure file showed a page with one iframe,
  six inputs and not one of the app's own selectors matching anything at
  all. A tab that moved is read where it stands, the PDF is asked for
  through the session rather than rendered, since a viewer renders one
  blank sheet, answers are listened for on the whole context rather than
  on one tab, and the tab goes back to the history afterwards so the next
  bill is looked for where it lives (#33).
- **E*TRADE said a row held nothing clickable while the row plainly held
  a document.** The table is built from web components and the cell is a
  `slot`, so a walk over each element's own children reached the slot and
  stopped, because what a slot shows lives somewhere else. Shadow roots
  and slots are walked now, pinned by tests in a real browser (#36).
- **State Farm found four documents and could save none.** A row keeps
  its documents folded away behind a button of its own, named "View
  Documents", which is not "view more" or "view all" and so was never
  pressed, leaving the page with no document link on it at all. A
  recording the member made settled it in one round. The rows are opened
  now, and a document named after what it is rather than after what
  pressing it does, "Renewal Notice", "Declarations Page", "ID Cards", is
  recognized as a document (#37).
- **Newrez found none of nine statements, and the survey never said
  why.** The survey records what each row says, with its digits masked,
  and what the app makes of the date it finds there, so a page that dates
  its rows in a way the app cannot read says so rather than reporting
  nothing at all (#38).
- **AT&T wrote a bare filename however many times the account label was
  fixed.** A bill discovered in an earlier round kept the summary it was
  given then, and a later run only ever refreshed where its link lived,
  so a fiber bill found before the app could read the account's kind
  stayed nameless. A bill that has not been saved yet takes the current
  name. One that has keeps it, because the file on disk is named already
  (#26).
- **A selector written in Playwright's dialect is counted rather than
  skipped.** The census asks a page its questions and a page cannot parse
  `:has-text(`, so those were reported as unanswerable. In the first
  failure file a tester sent, the one selector in that state was the one
  that fetches the document, so the census was silent about the thing
  that had just failed. Playwright speaks that dialect, so it is counted
  through the locator, which brings back numbers and nothing else (#33).
- **ADP's own refusal is written down and not only printed.** A tester
  signed out, signed back in, ran Resume twice, saw the lock-out message
  both times and had nothing in the Diagnostics folder to send, because a
  run that reaches a provider's refusal has not failed by its own
  reckoning and so wrote no file (#46).
- **Golden 1 wrote a trace with nothing in it.** Whether the vendor's tab
  opened, and which dates the page's own controls carry, are both in the
  file now, since an empty trace cannot be told from a run that never
  started (#35).


## [0.31.2] - 2026-09-23

Five repairs, every one of them from a sentence a tester wrote rather
than from anything the code said about itself.

### Fixed
- **A greeting gave up your surname.** The rule that takes a name out of
  a survey stopped after two words, so "Welcome, John Q Watling" lost the
  first name and the middle initial and kept the surname, which is what a
  tester found in a file he was about to attach. It takes the whole name
  now. Every word after the first has to begin with a capital, so it
  stops at the end of the name rather than eating the sentence it stands
  in, and the case-insensitive match that would have made that check mean
  nothing is scoped away. The other half of the same report is that his
  install had no account holder name at all, which 0.31.0 fixed by asking
  for one when an install is made (#38).
- **Target was the only app of forty-eight that could not use a browser
  you already have.** It drove Playwright's own Chromium and nothing
  else, so on the packaged Mac build, which carries no such copy, Login
  failed there while every other provider worked. It uses an installed
  Chrome, Edge or Brave when there is no bundled copy, in a profile of
  its own as before. Anyone whose Target app works today keeps the
  browser it works with (#48).
- **Newrez found none of nine statements.** Each row is a View and a
  Download whose address is `javascript:void(0)`, and the date is a month
  and a year, which the row reader would not accept because it asked for
  a day of a month. A month and a year dates a statement now and a year
  alone dates a 1098, discovery and capture agree on how a row is dated,
  and a month written as `09/2026` is that month rather than the end of
  that year, which would have collapsed twelve statements onto one date
  and dropped eleven of them (#38).
- **AT&T named the account you were not looking at.** The switcher lists
  every account and the one in focus is listed first, and round nine read
  the lines backwards. It reads them forwards now. When the switcher is
  not a button named "Account", which is what the fiber account turned
  out to have, the page itself is asked and what it marks as selected
  comes first. The survey records what it decided from, so a wrong
  filename can be read rather than guessed at (#26).
- **State Farm found four documents and saved none, and said nothing
  about why.** The document list gave no file address for any of them,
  and the page carried no control for their dates either, and neither of
  those wrote a line, so the file a tester sent had an empty list of
  responses in it, which reads exactly like a run that never started.
  Both say so in a sentence now, along with the dates the page's controls
  did carry. The year walk stops after two years running with nothing in
  them rather than always asking for seven, since State Farm keeps two
  (#37).

## [0.31.1] - 2026-09-23

### Fixed
- **The failure file 0.31.0 added could carry your name.** It gathered
  what looked useful and then scrubbed it, taking out emails, amounts,
  long runs of digits and the account holder's name. A test built for
  the purpose proved that was the wrong way round. Put a distinctive
  fake secret into every channel a browser offers, a name in the page
  title, a street and a card tail in a receipt's own text, an element
  id, a class, an order number in an address, a token in a query
  string, a hidden input, a console message, an uncaught exception,
  then produce the file and see what survives. Eleven of twenty one
  survived. The name came through the title. The street and the card
  tail came through the receipt's text, because they are words and the
  scrubbing knew about digits. **If you are on 0.31.0 and a run has
  failed, update before attaching the file it wrote to anything.**
- **Nothing is scrubbed now.** The file is built from a list of what
  may leave, and only a count, a boolean, a word from a fixed list, a
  duration or a name written in PaperPull's own source ever does. A
  field not on that list does not reach the file, so a provider added
  tomorrow cannot widen it by accident. An exception becomes one word
  rather than its message. Page text, titles, addresses, attributes and
  console output are gone entirely. One exception is kept and proved
  rather than assumed, a framework's own layout words in a class, since
  `div.modal.fade` is what identified a hidden dialog that had cost a
  day. A class of `customer-4821-panel` reduces to nothing. Twenty one
  of twenty one clean, held by a test that runs a real browser over
  that page whenever the format changes.
- **A capture puts the page back.** Saving a document takes everything
  except the document off the screen. Where a provider navigates
  between documents that costs nothing, because the next load discards
  it. Where it does not, the second document is looked for on a page
  where nothing can be clicked, so the first of a run works and every
  one after it fails. Every element's own style is remembered before a
  capture and restored afterwards in a finally, so a render that raises
  leaves the page as it found it, and the run records whether the
  restoring worked rather than assuming it.

### Added
- **A run keeps a journal.** What the app was about to do, which
  collection it chose from and which item of it, and the state of the
  page at each transition. The choice is the part a census cannot
  replace, because counting one collection and acting on the nth of
  another reads from outside exactly like a page that did not load, and
  that bug took two runs against a real account to find with a browser
  open. A pair of checkpoints is what carries an earlier problem
  forward, since a list that was visible at one and is present but not
  visible at the next is a page something hid and did not put back.
  Whether the address changed, and in which part, is the difference
  between a page that reloaded and one that did not, so the journal
  keeps the last address to compare against and never writes it down.
- Costco keeps one, through the tabs, the quarters and each receipt.

## [0.31.0] - 2026-09-22

### Added
- **Record, so a provider is built from what a person did rather than
  from a guess about it.** A survey describes a page and is still a
  guess, because it cannot know which control the account holder would
  click, in what order, or what the site does in between. AT&T took nine
  rounds of guessing. A tester now signs in themselves, presses **Record**
  in the panel or runs `paperpull <slug> record`, clicks through to one
  document the way they always do, and presses **Stop recording**. What
  comes out is `Diagnostics/recording.json`, the controls clicked named
  the way a person reads them, the option picked in each dropdown, where
  the page moved, what downloaded, and the addresses and shapes of the
  provider's own answers.
- **Nothing typed is captured, and that is enforced rather than
  promised.** The capture script listens for click, change and submit
  and for nothing else, so a password, a card number or a search term has
  no listener to be caught by. A field that was typed into is recorded as
  having been typed into and its value is the fixed word `[REDACTED]`.
  Cookies, headers and storage are never read, a recording refuses to
  start unless the page is on the provider's own host with no password
  field on it, and tests fail the build if any of that changes.
- **The app says what to look at before the file goes anywhere.** When a
  recording ends it prints the things redaction is known not to catch, a
  four or five digit number, a name standing on its own where no account
  holder name is configured, anything still shaped like an address or an
  email, each quoted so the tester can find it. One finding is one
  sentence however many places it appears in.
- **`tools/read_recording.py`**, which reads a recording back as what the
  person did, what the site answered, and the locator lines to start the
  site layer from, with the brittle ones and the ones the app's control
  guard would refuse called out.
- **[Testing a provider](docs/testing-a-provider.md)**, the whole thing
  written for somebody who has the account and does not write code, from
  the installer to the issue comment. Every untested provider's README
  now points at it.

- **Costco, the 48th app, and the first one written from a recording.** A
  member signed in, pressed Record once and clicked through to two
  warehouse receipts and one online invoice, and the app is that path
  written down rather than a guess at it. Orders & Purchases is two tabs,
  Warehouse and Online, and they are two different lists. How far back a
  member can see is a picker holding quarters that opens on the last
  three months, so a run that never touches it sees a quarter, and this
  walks them. A warehouse receipt is a dialog with no address of its own,
  so it is keyed on what its row shows, the date, the total and the
  warehouse. Neither print control is ever pressed, since both call
  `window.print()`, which opens a dialog no program can dismiss, and the
  receipt is rendered with printToPDF instead. Against the live account,
  34 purchases back to July 2024, four warehouse receipts saved as one
  readable page each and three online invoices (#47).
- **A failing run writes down what the page looked like, without anybody
  having to ask it to.** The expensive half of adding a provider is that
  the maintainer cannot run it, so a tester sends back a sentence and a
  round goes by. Diagnose does not close that, because it walks the page
  through the app's own code and can only see as far as the app already
  works. On a provider that does not work yet it says "found nothing". A
  failure now takes a census of the selectors the app declares, while the
  page is still on screen, saying for each one how many nodes matched and
  how many of those were visible. Matched none means the page had not
  drawn or the selector is wrong. Matched one and visible none means the
  thing found is not the thing on screen. Everything invisible means
  something hid the page and never put it back. Invalid means it was
  written in Playwright's dialect, which a browser does not speak. Those
  four lines state five of the eight bugs Costco cost, including the
  hidden modal that took a day. All 48 apps write one, at the first
  failure, four kilobytes, and a look-only run writes none because it has
  nothing to fail at.

### Fixed
- **A run that only looked at the page no longer wipes the record of the
  last one that downloaded.** Setting a run's mode causes a run summary
  at exit, which rewrites `new-this-run.txt`. For a download run that is
  right. For `diagnose`, which downloads nothing by design, it replaced a
  list that was still true, in all forty-seven apps since the mode was
  introduced. A tester running Diagnose silently lost the record of what
  their last real run fetched.
- **A field is never named by what is already in it.** The accessible
  name falls back to an element's text, and a server-rendered textarea
  holds its contents as text, so a form with the account holder's address
  pre-filled named the field after the address. Fields are now named by
  their label or not at all.
- **Stop recording follows the recording, not the App list.** The App
  list is not disabled while a run is going, so changing it mid-recording
  and pressing Stop wrote the signal into another provider's folder and
  the recording, watching its own, never ended.
- Nothing arriving from the page is trusted. The binding sits on
  `window`, so any script on the provider's page can call it, and a
  malformed payload used to lose the step it arrived with.
- A JSON response over 2 MB is recorded as too large rather than read,
  since reading a body is a round trip to the browser and a year of
  transactions has the same shape as a month of them.
- **An install made by the panel could not import the shared core.**
  `setup.bat` installs it from the repo two folders up, which is true
  only when the install sits inside the repo, so an install in somebody's
  Documents folder finished cleanly and left a venv that died on its
  first import. The panel knew where the core was the whole time and
  would only ever update a copy that already existed, never put one
  there. It seeds one now.
- **An install made by the panel had no account holder name.** An app
  asks for that on its first run at a console, and the panel closes an
  app's stdin, so it could not ask and the name stayed empty forever. An
  empty name is the one thing that stops redaction taking a person's own
  name out of a survey or a recording, which matters most for exactly the
  people who use the panel. It is asked for once when the install is
  made, where somebody is looking at a screen.
- **A provider with no environment yet says so in words rather than in a
  traceback.** Adding a provider and pressing Login gave `No module named
  'paperpull_core'`, a true sentence about the wrong interpreter that
  tells a tester nothing. The run is refused before anything starts, and
  the output pane gets the folder to open, the file to double-click, and
  the reload that puts the shared code in place.
- **Record watches the tab you are already on.** An app that attaches to
  a browser already running hands out a fresh page, which is right for a
  download run and useless for a recording, so a recording on any of the
  twenty-six providers that attach refused with "this is not a page on
  the provider's own site" while the person sat looking at the tab that
  was. It looks past the page it was given at the others in the same
  context, takes the provider's own, brings it to the front and says
  which one it picked.

## [0.30.2] - 2026-09-22

Tagged and built, never published. Everything in it is in 0.31.0.

### Added
- **ADP asks for an identity check before a tax statement, and the app
  now knows it.** A pay statement needs none, which is why a tester's pay
  statements landed and his W-2s did not. ADP answers the W-2's address
  with "Authentication is Required" and offers a code by text, email or
  call. The app reads that refusal for what it is, presses the Tax
  Statements card's own View statement so ADP shows the prompt in the
  browser window already open, and waits, taking the statement ADP's own
  viewer fetches once the code is accepted. Nothing is typed into the
  app, since the panel runs it with no keyboard. Asking twice is what
  blocks an account, so a tax form is asked for at one address only, one
  unanswered check ends that run's tax forms, and a blocked account is
  reported in ADP's own words. Tax forms run last, and the employer
  leads their filename (#46).

### Fixed
- **eBay found two of nine orders.** A card whose details link is missing
  or points elsewhere is taken from its own order number now, and the
  scroll waits for the page to stop growing as well as for the count to
  settle (#44).
- **Meijer read the wrong tab.** The page has Online Orders and In-Store
  Receipts and opens on the first, which is empty for someone who only
  shops in the store. Both are read now, a store receipt files under
  In-Store, and capture presses the row's own PDF icon (#42).
- **Two GitHub receipts on one day wrote one filename.** The row says
  nothing about what was bought, so GitHub's own payment id goes in the
  name (#43).
- **PG&E handed over no control although the link was plainly there.**
  Lightning replaces querySelectorAll on each element to hide a
  component's children. A walk over each node's own children is not
  patched, and that is how a row's controls are gathered now (#33).
- **E*TRADE wrote an empty download trace.** The row is found by its
  date, every way it might hand over a PDF is tried, and each attempt's
  requests go in the trace. The period picker's years are clicked by
  text (#36).
- **Golden 1's survey pressed a link, not the button of the same name**,
  so the vendor's tab never opened. The button comes first, and the tab
  it opens is read whatever host it lands on (#35).
- **Redaction lives in the core now.** Seventeen apps carried their own
  copy in three versions, five of which masked long digit runs and
  nothing else. One copy, one place to fix, with a test for each thing
  it removes.

## [0.30.1] - 2026-09-22

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
  with it. Money is found by shape, `Â£12.99` and `12,99 â‚¬` alike, and
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
  template and PR checklist said "9222â€“9232 are taken; use 9233+" and
  CONTRIBUTING said "9234+", but Gap is 9233 and UKG is 9234. A colliding port
  makes two apps share one browser profile, which has previously merged two
  accounts' documents. All four documents now say 9222â€“9234 taken, 9235+ free.
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
