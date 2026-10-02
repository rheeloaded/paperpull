# Changelog

All notable changes to PaperPull are recorded here. Versioning follows
[Semantic Versioning](https://semver.org):

- **PATCH**, bug fixes, or repairing an app after a provider changes its site
- **MINOR**, a new app, or a cross-app feature
- **MAJOR**, breaking changes (repo layout, config format, removing an app)

## [Unreleased]

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
