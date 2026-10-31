# Providers

The running list of what PaperPull supports, and what people want next. The
goal is an ever-growing set covering the banks, cards, brokerages, utilities,
telecoms, payroll systems, and retailers real people actually use.

- **Have an account with a provider that's not here?** You're the ideal person
  to add it, see **[Adding a provider](docs/adding-a-provider.md)**.
- **Want a provider but can't build it?** Open a
  [provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
  so someone with that account can pick it up.

## Supported (71, plus seven built and waiting for a tester)

| App | Provider | Documents | Category |
|-----|----------|-----------|----------|
| [`affirm`](apps/affirm) | Affirm | Loan agreements, one per loan; Affirm Money and Card statements not covered | Lender |
| [`adp`](apps/adp) | ADP Workforce Now | Pay statements and W-2s, everything the statement services list, nothing clicked | Payroll |
| [`aafmaa`](apps/aafmaa) | AAFMAA (Armed Forces Mutual) | Annual statements, policy & insurance documents | Insurance / member association |
| [`capitalone`](apps/capitalone) | Capital One | Bank and card statements, tax forms, letters | Bank / card |
| [`cetera`](apps/cetera) | Cetera (AdviceWorks) | Brokerage account statements and quarterly performance reports, every account and quarter the client portal keeps, from the page's own statement and report lists asked from inside the signed-in page, nothing clicked. Built and run on a contributor's own account, 56 statements and 5 reports | Brokerage |
| [`ally`](apps/ally) | Ally Bank | Account statements, tax forms | Bank |
| [`alpaca`](apps/alpaca) | Alpaca (Live brokerage account) | Brokerage and crypto statements and trade confirmations for the Live account, each row's own Download pressed once and the presigned file taken through the browser. The JSON twins of trade confirmations and the account application are skipped, and a Paper account is never read. Built and run on a contributor's own Live account, 22 documents | Brokerage / crypto |
| [`att`](apps/att) | AT&T (Mobility, Fiber, Internet) | Monthly bills. Confirmed by @watling777 on two accounts, wireless and internet, with a full run on each (#26) | Telecom |
| [`amazon`](apps/amazon) | Amazon | Order invoices (full history) | Retail |
| [`amfam`](apps/amfam) | American Family Insurance | Billing statements and any tax form listed with them. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #45. Being tested by @jpfieber | Insurance |
| [`amex`](apps/amex) | American Express | Statements, year-end summary | Card |
| [`anthem`](apps/anthem) | Anthem BCBS (Elevance, 14 Blue states) | EOBs, member/plan documents (all coverage years), digital ID cards, secure-message letters; tRPC API, nothing clicked. Contributed by @riordan | Health insurance (PHI) |
| [`apple`](apps/apple) | Apple (App Store and Apple Store) | Receipts for everything paid for, App Store subscriptions such as Apple One and iCloud+, in-app purchases anywhere in Family Sharing and paid apps, each saved from Apple's own emailed receipt with free downloads skipped, and Apple Store orders, each order's invoice saved and a canceled one recorded without a receipt. Built and run on the maintainer's own account | Retail |
| [`applecard`](apps/applecard) | Apple Card and Apple Savings | Apple Card statements, Savings statements, tax forms. Confirmed by @watling777, whose Pilot and full run saved every statement and the 1099-INT forms (#52) | Card / savings |
| [`bestbuy`](apps/bestbuy) | Best Buy | Receipts for online orders, orders placed in a store and store purchases, and returns, each purchase's details page saved as the receipt, back to 2015. Built on the maintainer's own account, 35 purchases found and all 35 saved. Best Buy's bot protection stops answering if asked too quickly, so it is paced, and a blocked run says to wait an hour | Retail |
| [`bilt`](apps/bilt) | Bilt Card (Bilt Card 2.0, serviced by Cardless) | Monthly card statements from the Bilt wallet. Run live on one account on 2026-10-15, where Discover, Pilot and Run All saved all eight statements. Only the card's "View balance summary", "View statements" and a statement's own button are pressed, and the PDF is taken from the tab that button opens. Statements of the Wells Fargo issued Bilt card are not here | Card |
| [`bofa`](apps/bofa) | Bank of America | Checking, savings and credit card statements. UNTESTED, built from a tester's two recordings, and its first two runs listed the statements and saved none. Statements & Documents' own list and PDF links, read from inside the page, with its Statements heading opened, and when the links have no address, one pressed to learn the page's own call for a PDF. Have an account? Run Pilot and say on issue #121 whether the statements are right | Bank |
| [`chase`](apps/chase) | Chase (credit cards) | Card statements | Card |
| [`chasebusiness`](apps/chasebusiness) | Chase Business (business document center) | Business checking and business card statements, up to the seven years Chase keeps online, from the document center's account menu and year picker, then a checking row's two-step Save as PDF or a card row's own Saves document link, each control pressed through the guard. Live-run on one profile: 10 Business Checking statements saved, every PDF opened, and the business card's first statement saved once the card had cycled. That profile's debit account showed no statements in the center, so it is untested | Bank / card |
| [`citi`](apps/citi) | Citi (credit cards) | Monthly card statements, the roughly two years the site lists online; statements API, nothing clicked | Card |
| [`coinbase`](apps/coinbase) | Coinbase | Monthly account statements back to the account's first month, Coinbase One Card statements (run live on 2026-10-15, all 13 saved), and tax documents, the 1099-DA and other tax forms and the pregenerated gain and loss PDF reports. Contributed by @JasperDale420. A statement row's own PDF button is pressed and the download taken only from Coinbase's statements bucket, and tax PDFs come from the list calls the Taxes page makes, nothing pressed. A full run on a retail account saved 66 statements and 2 tax documents | Crypto exchange |
| [`costco`](apps/costco) | Costco Wholesale | Receipts, in-warehouse, gas, pharmacy and costco.com orders. Written from a member's recording and run against their account. One membership so far, a second Pilot is welcome, see issue #47 | Retail |
| [`discovercard`](apps/discovercard) | Discover (credit cards) | Card statements. A card that has moved to Capital One is read there by the Capital One app (#13) | Card |
| [`dominion`](apps/dominion) | Dominion Energy (VA) | Billing statements | Utility |
| [`ebay`](apps/ebay) | eBay | Order receipts, the order-details page rendered to PDF, ten years of purchase history, nothing clicked. Confirmed by @jpfieber on issue #44, every order back to 2017 | Retail |
| [`etrade`](apps/etrade) | E*TRADE | Statements, trade confirmations, tax forms. Confirmed by @watling777, whose Pilot and full run saved every statement (#36). No tax form seen yet, his account has none | Brokerage |
| [`ezpassva`](apps/ezpassva) | E-ZPass Virginia | Monthly and quarterly statements, the roughly one year of each the portal keeps online, so run it at least once a year. Built on the maintainer's own account | Tolls |
| [`fairfaxwater`](apps/fairfaxwater) | Fairfax Water (VA) | Water bills, the last year's, from the FW Customer portal | Utility |
| [`fedex`](apps/fedex) | FedEx (Billing Online) | Shipping invoices. UNTESTED, built from a login not connected to Billing Online, no invoice seen. Use it? Run Diagnose and attach the file to issue #54 | Shipping |
| [`fidelity`](apps/fidelity) | Fidelity Investments | Statements, trade confirmations, tax forms; Document Access Hub API, nothing clicked | Brokerage |
| [`invest529`](apps/invest529) | Invest529 (Virginia529 / Commonwealth Savers) | Official quarterly statements for every beneficiary and 1099-Q tax forms; the account's own API, nothing clicked. Built and run on the maintainer's own account, 38 documents across three beneficiaries | 529 college savings |
| [`firsthorizon`](apps/firsthorizon) | First Horizon Bank | Checking statements, the two years the bank keeps online. Each account's panel is expanded and each statement's own Download PDF is pressed once. Built and run on a contributor's own account, 24 statements | Bank |
| [`gap`](apps/gap) | Gap Inc. (Gap, Old Navy, Banana Republic, Athleta) | Order receipts | Retail |
| [`homedepot`](apps/homedepot) | The Home Depot | Receipts for online orders, and store purchases where the history lists them, Home Depot's own print receipt with model and store SKU numbers. Home Depot keeps two years online, so run it every few months. Built on the maintainer's own account, 8 orders found and 6 receipts saved | Retail |
| [`kroger`](apps/kroger) | Kroger (Pick 'n Save, Metro Market, Fred Meyer, Ralphs and the rest) | Receipts, in-store, fuel, pickup and delivery. Confirmed by @jpfieber on issue #41, whose Pilot saved receipts that read properly, each naming its banner, Metro Market or Fred Meyer, for a file name pattern | Retail |
| [`lowes`](apps/lowes) | Lowe's Home Improvement | Receipts for store purchases and online orders, and returns, from the purchase history back to 2023, each purchase's details page saved as the receipt. Built on the maintainer's own account, 41 purchases found and 6 saved in the first pilot | Retail |
| [`github`](apps/github) | GitHub | Payment receipts for Pro, Copilot, Actions, Sponsors and anything else GitHub charged. Confirmed by @jpfieber on issue #43, whose Pilot saved five of the twenty-three receipts his account holds | Software services |
| [`golden1`](apps/golden1) | Golden 1 Credit Union | Statements, tax forms. Confirmed by @watling777, whose run saved every statement on both of his accounts, a credit card's named as one (#35) | Credit union |
| [`ibkr`](apps/ibkr) | Interactive Brokers | Monthly Activity Statements for the account the Statements page shows. Contributed by @tylerverry. A full run saved 60 of 61 months, September 2021 to September 2026, every one a valid PDF, the last saved on a supervised retry. Tax forms, trade confirmations and flex queries are not read | Brokerage |
| [`irs`](apps/irs) | IRS (Individual Online Account) | Account, return, wage and income, and record of account transcripts, read from the list the transcript page asks for and each fetched by its own address, nothing clicked. Built from a read-only survey and run in full on the builder's own account, 26 transcripts listed and all 26 saved as valid PDFs. A notice stops Run All until one has been seen, and Resume then saves the transcripts. Sign-in is ID.me, the account holder's own | Government / tax |
| [`meijer`](apps/meijer) | Meijer | Order receipts, and in-store digital receipts where mPerks lists them. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #42. Being tested by @jpfieber | Retail |
| [`myecp`](apps/myecp) | MILITARY STAR card (MyECP, Exchange Credit Program) | Monthly card statements, the three and a half years MyECP keeps online. Built on the maintainer's own account, 25 statements | Card |
| [`mypay`](apps/mypay) | DFAS myPay | eRAS, CRSC, 1099-R, 1095 | Government pay system; JSON API, nothing clicked |
| [`mtb`](apps/mtb) | M&T Bank | Mortgage statements, escrow, 1098 | Mortgage servicing |
| [`netbenefits`](apps/netbenefits) | Fidelity NetBenefits | Quarterly or monthly 401(k) statements for every plan on the sign-in, made to order and rendered, nothing clicked | Workplace retirement plan |
| [`navyfederal`](apps/navyfederal) | Navy Federal CU | Account statements | Bank / credit union |
| [`nelnet`](apps/nelnet) | Nelnet | Student loan billing statements and the 1098-E, from a federal student loan servicer. Contributed by @tylerverry. A full run saved all 47 documents, 41 statements back to 2019, the 1098-E and 5 notices, every one a valid PDF | Student loan servicer |
| [`newrez`](apps/newrez) | Newrez | Mortgage statements, escrow analysis, 1098. Confirmed by @watling777, whose run saved every document, three years of statements through the statements page's year picker and the 1098s (#38) | Mortgage servicer |
| [`optum`](apps/optum) | Optum Bank (HSA) | Monthly HSA statements and tax forms, the 5498-SA and, in a year with distributions, the 1099-SA, each a plain link on the member site fetched by its own address, nothing clicked. Contributed by @JasperDale420, whose full run saved 21 statements and the 5498-SA. One HSA so far, so more than one product is untested | HSA custodian |
| [`paypal`](apps/paypal) | PayPal | Monthly statements, the three years the site keeps online. Tax forms not yet covered. Built on the maintainer's own account, 25 statements. A business account's statements from Activity, All Reports, written from a tester's recording and not yet run on a business account. Have one? Run Pilot and Diagnose and attach the files to the PayPal issue | Payments |
| [`paylocity`](apps/paylocity) | Paylocity | Pay statements | Payroll |
| [`pge`](apps/pge) | PG&E (Pacific Gas and Electric) | Billing statements. Contributed by @appchamp. Repaired in 0.37.1 and confirmed on a real account by @watling777 (#33) | Utility |
| [`redcard`](apps/redcard) | Target RedCard / Circle Card (TD Bank) | Billing statements | Card |
| [`robinhood`](apps/robinhood) | Robinhood | Account statements for the individual, retirement and crypto accounts, tax docs. A statement Robinhood serves only as HTML (seen for three recent months) is left for manual review | Brokerage |
| [`sba`](apps/sba) | SBA (MySBA Loan Portal) | Loan statements, 1098. UNTESTED, built without an account. Have an SBA loan? Run Diagnose and attach the file to issue #28 | Government loan servicing |
| [`schwab`](apps/schwab) | Charles Schwab | Statements, tax forms, letters, trade confirmations | Brokerage |
| [`sdge`](apps/sdge) | SDG&E (San Diego Gas & Electric, My Energy Center) | Monthly bills, about two years online, each read from Billing History and fetched by its own address, nothing clicked. One account at a time. With several, only the one selected in the portal is listed. Built and run on a contributor's own account, 8 bills | Utility |
| [`shelbycounty`](apps/shelbycounty) | Shelby County Trustee (Memphis, TN property tax) | Property tax receipts, one per payment, back to the parcel's first year online, and the current tax notice while a balance is due. A public lookup with no sign-in, the parcel ID goes in config.json. The page builds each PDF in the browser and the app keeps it, opening nothing. Built and run on a contributor's own parcel, 17 receipts | Tax authority |
| [`simmons`](apps/simmons) | Simmons Bank (Banno online banking, a loan) | Loan statements, notices and tax forms from the Documents page. Only a document row's own button is pressed, and the download taken only when it is that document's own. One account per sign-in, a second account stops the list. A paid-off loan's documents stay online only until the date the bank names. Built and run on a contributor's own paid-off mortgage, 27 documents | Bank / mortgage |
| [`smud`](apps/smud) | SMUD (Sacramento Municipal Utility District) | Monthly bills. Confirmed by @watling777 on issue #34, whose Pilot took the newest five and whose full run took the rest of the history | Utility |
| [`spectrum`](apps/spectrum) | Spectrum (Charter) | Internet statements, about a year online. An older statement is chosen by pressing its own row, then one "View Printable Statement" is pressed and the PDF the page makes is kept only when its text prints the statement's date, never a tab. Two statements of one date are left for a manual save. Mobile statements, which the site has no PDF of, are opened by their own row, expanded with Expand All and printed from the page. Internet run on the contributor's own account, 11 statements saved. A whole Mobile run is still to come | Telecom |
| [`stripe`](apps/stripe) | Stripe (merchant Dashboard) | Fee invoices and tax forms such as the 1099-K. UNTESTED, built on an account with no documents yet. Have some? Run Diagnose and attach the file to issue #53 | Payments |
| [`statefarm`](apps/statefarm) | State Farm | Bills, renewal notices, ID cards, receipts, policy documents. Confirmed by @watling777, whose full run saved every document State Farm lists for his policies (#37) | Insurance |
| [`target`](apps/target) | Target | Receipts (online + in-store) | Retail |
| [`tsp`](apps/tsp) | Thrift Savings Plan (tsp.gov) | Participant statements, 1099-R | Federal retirement (government system) |
| [`tmobile`](apps/tmobile) | T-Mobile | Bill statements | Telecom |
| [`treasurydirect`](apps/treasurydirect) | TreasuryDirect (U.S. Treasury, savings bonds and Treasuries) | No PDFs exist, so its pages are saved as PDFs, dated snapshots of Current Holdings, Security History and Payment History. Moves only by pressing the site's own links in the signed-in tab, since opening an address ends the session, and never opens an address or submits a form. A taxable year's 1099 is listed once for manual review and its link never pressed, until a taxable year is surveyed. One account at a time, each document kept under the account it was listed on. Run on a contributor's own account, Discover 3, Pilot 1, Run All 2, every PDF opened | Government securities |
| [`uber`](apps/uber) | Uber (rides and Uber Eats) | Receipts for every ride and every Uber Eats order paid for, each saved as Uber's own receipt PDF, with trips canceled before anything was charged and orders that cost nothing skipped. Uber's website only reaches back so far, about ten months of trips and two years of orders on the account it was built on. Built and run on the maintainer's own account, 24 receipts saved | Rides / food delivery |
| [`ukg`](apps/ukg) | UKG Pro / UltiPro | Pay statements | Payroll |
| [`ups`](apps/ups) | UPS (Billing Center) | Shipping invoices from billing.ups.com, every invoice My Invoices lists. Built on the maintainer's own account | Shipping |
| [`usaa`](apps/usaa) | USAA | Statements | Bank / insurance |
| [`usbank`](apps/usbank) | U.S. Bank | Credit-card statements | Card |
| [`vanguard`](apps/vanguard) | Vanguard | Account statements, monthly and quarterly, for every account the statements page lists, an employer 401(k) among them. Contributed by @tylerverry. A full run on five accounts saved 135 statements back to 2020, every one a valid PDF | Brokerage |
| [`venmo`](apps/venmo) | Venmo (account.venmo.com) | Monthly account statements, back to your start date. With none set it saves two years, and when the oldest of those months has transactions the run then ends as one that stopped rather than call the list whole. Venmo has no PDF statement on the web, so each finished month's statement page is opened by its own address and printed to PDF, with only the month's own "Show more" pressed until every transaction is drawn. Months with no transactions are skipped and the CSV is not taken. Built and run on one account, 24 statements with two busy months expanded in full. A business profile is not listed | Payments |
| [`verizon`](apps/verizon) | Verizon (Fios) | Bill statements | Telecom |
| [`verizonmobile`](apps/verizonmobile) | Verizon Mobile (wireless) | Monthly bills. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #31 | Telecom |
| [`walmart`](apps/walmart) | Walmart | Receipts | Retail |
| [`wellsfargo`](apps/wellsfargo) | Wells Fargo | Account statements, tax documents. Credit card statements confirmed on a real account by @appchamp (#27). Checking, savings, mortgage and tax documents are untested | Bank / card / mortgage |
| [`wealthfront`](apps/wealthfront) | Wealthfront | Statements, tax docs | Brokerage |

## Requested / in progress

Anyone can add a row (via a [provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
or a PR). Claim one by commenting on its issue so two people don't build the
same thing. When it merges, it moves up to **Supported**.

New to this? Look for the **`good first provider`** label, those are easy sites
(a plain statements table + a real download link). See
[Which provider is a good first build?](docs/adding-a-provider.md#which-provider-is-a-good-first-build)

| Provider | Category | Requested by | Status |
|----------|----------|--------------|--------|
| _(none yet, add yours)_ | | | |

Status legend: **requested** → **claimed** (someone's building it) →
**in review** (PR open) → merged (moves to Supported). **Built, needs a
tester** is an app written without an account, which anyone who holds one
can finish by running its Diagnose button and attaching the result.

## How the list grows

1. **Request**, someone opens a provider request (or adds a row here).
2. **Claim**, a contributor with that account comments to claim it.
3. **Build**, follow [Adding a provider](docs/adding-a-provider.md): clone the
   closest app, rewrite its `*_site.py`, keep it read-only, test the pilot.
4. **PR**, open a pull request (the template has a safety + privacy checklist).
5. **Merge**, it graduates to the Supported table above.

Providers change their sites over time; a supported app that breaks is a
**patch** fix to that app's `*_site.py`, not a rebuild, see
[CONTRIBUTING.md](CONTRIBUTING.md).
