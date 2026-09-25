# Providers

The running list of what PaperPull supports, and what people want next. The
goal is an ever-growing set covering the banks, cards, brokerages, utilities,
telecoms, payroll systems, and retailers real people actually use.

- **Have an account with a provider that's not here?** You're the ideal person
  to add it, see **[Adding a provider](docs/adding-a-provider.md)**.
- **Want a provider but can't build it?** Open a
  [provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
  so someone with that account can pick it up.

## Supported (35, plus fourteen built and waiting for a tester)

| App | Provider | Documents | Category |
|-----|----------|-----------|----------|
| [`affirm`](apps/affirm) | Affirm | Loan agreements, one per loan; Affirm Money and Card statements not covered | Lender |
| [`adp`](apps/adp) | ADP Workforce Now | Pay statements and W-2s, everything the statement services list, nothing clicked | Payroll |
| [`aafmaa`](apps/aafmaa) | AAFMAA (Armed Forces Mutual) | Annual statements, policy & insurance documents | Insurance / member association |
| [`capitalone`](apps/capitalone) | Capital One | Bank and card statements, tax forms, letters | Bank / card |
| [`ally`](apps/ally) | Ally Bank | Account statements, tax forms | Bank |
| [`att`](apps/att) | AT&T (Mobility, Fiber, Internet) | Monthly bills. Pilot confirmed by @watling777 in round eight, the full run and a second account still being tested on issue #26 | Telecom |
| [`amazon`](apps/amazon) | Amazon | Order invoices (full history) | Retail |
| [`amfam`](apps/amfam) | American Family Insurance | Billing statements, policy documents, declarations, ID cards. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #45. Being tested by @jpfieber | Insurance |
| [`amex`](apps/amex) | American Express | Statements, year-end summary | Card |
| [`anthem`](apps/anthem) | Anthem BCBS (Elevance, 14 Blue states) | EOBs, member/plan documents (all coverage years), digital ID cards, secure-message letters; tRPC API, nothing clicked. Contributed by @riordan | Health insurance (PHI) |
| [`applecard`](apps/applecard) | Apple Card and Apple Savings | Apple Card statements, Savings statements, tax forms. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #52. Being tested by @watling777 | Card / savings |
| [`chase`](apps/chase) | Chase (credit cards) | Card statements | Card |
| [`citi`](apps/citi) | Citi (credit cards) | Monthly card statements, the roughly two years the site lists online; statements API, nothing clicked | Card |
| [`costco`](apps/costco) | Costco Wholesale | Receipts, in-warehouse, gas, pharmacy and costco.com orders. Written from a member's recording and run against their account. One membership so far, a second Pilot is welcome, see issue #47 | Retail |
| [`discovercard`](apps/discovercard) | Discover (credit cards) | Card statements | Card, **moving to Capital One** ([#13](https://github.com/rheeloaded/paperpull/issues/13)) |
| [`dominion`](apps/dominion) | Dominion Energy (VA) | Billing statements | Utility |
| [`ebay`](apps/ebay) | eBay | Order receipts, the order-details page rendered to PDF, ten years of purchase history, nothing clicked. Confirmed by @jpfieber on issue #44, every order back to 2017 | Retail |
| [`etrade`](apps/etrade) | E*TRADE | Statements, trade confirmations, tax forms. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #36. Being tested by @watling777 | Brokerage |
| [`fairfaxwater`](apps/fairfaxwater) | Fairfax Water (VA) | Water bills, the last year's, from the FW Customer portal | Utility |
| [`fidelity`](apps/fidelity) | Fidelity Investments | Statements, trade confirmations, tax forms; Document Access Hub API, nothing clicked | Brokerage |
| [`gap`](apps/gap) | Gap Inc. (Gap, Old Navy, Banana Republic, Athleta) | Order receipts | Retail |
| [`kroger`](apps/kroger) | Kroger (Pick 'n Save, Metro Market, Fred Meyer, Ralphs and the rest) | Receipts, in-store, fuel, pickup and delivery. UNTESTED, built against an account with no purchases. Have one? Run Diagnose and attach the file to issue #41. Being tested by @jpfieber | Retail |
| [`lowes`](apps/lowes) | Lowe's Home Improvement | Receipts for store purchases and online orders, and returns, from the purchase history back to 2023, each purchase's details page saved as the receipt. Built on the maintainer's own account, 41 purchases found and 6 saved in the first pilot | Retail |
| [`github`](apps/github) | GitHub | Payment receipts for Pro, Copilot, Actions, Sponsors and anything else GitHub charged. Confirmed by @jpfieber on issue #43, whose Pilot saved five of the twenty-three receipts his account holds | Software services |
| [`golden1`](apps/golden1) | Golden 1 Credit Union | Statements, tax forms. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #35. Being tested by @watling777 | Credit union |
| [`meijer`](apps/meijer) | Meijer | Order receipts, and in-store digital receipts where mPerks lists them. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #42. Being tested by @jpfieber | Retail |
| [`mypay`](apps/mypay) | DFAS myPay | eRAS, CRSC, 1099-R, 1095 | Government pay system; JSON API, nothing clicked |
| [`mtb`](apps/mtb) | M&T Bank | Mortgage statements, escrow, 1098 | Mortgage servicing |
| [`netbenefits`](apps/netbenefits) | Fidelity NetBenefits | Quarterly or monthly 401(k) statements, made to order and rendered; nothing clicked | Workplace retirement plan |
| [`navyfederal`](apps/navyfederal) | Navy Federal CU | Account statements | Bank / credit union |
| [`newrez`](apps/newrez) | Newrez | Mortgage statements, escrow analysis, 1098. UNTESTED, built without an account. Have a Newrez mortgage? Run Diagnose and attach the file to issue #38. Being tested by @watling777 | Mortgage servicer |
| [`paylocity`](apps/paylocity) | Paylocity | Pay statements | Payroll |
| [`pge`](apps/pge) | PG&E (Pacific Gas and Electric) | Billing statements. Contributed by @appchamp, a pagination repair being tested by @watling777 | Utility |
| [`redcard`](apps/redcard) | Target RedCard / Circle Card (TD Bank) | Billing statements | Card |
| [`robinhood`](apps/robinhood) | Robinhood | Account statements, tax docs | Brokerage |
| [`sba`](apps/sba) | SBA (MySBA Loan Portal) | Loan statements, 1098. UNTESTED, built without an account. Have an SBA loan? Run Diagnose and attach the file to issue #28 | Government loan servicing |
| [`schwab`](apps/schwab) | Charles Schwab | Statements, tax forms, letters, trade confirmations | Brokerage |
| [`smud`](apps/smud) | SMUD (Sacramento Municipal Utility District) | Monthly bills. Confirmed by @watling777 on issue #34, whose Pilot took the newest five and whose full run took the rest of the history | Utility |
| [`statefarm`](apps/statefarm) | State Farm | Bills, renewal notices, ID cards, receipts, policy documents. UNTESTED, built without an account. Have a policy? Run Diagnose and attach the file to issue #37. Being tested by @watling777 | Insurance |
| [`target`](apps/target) | Target | Receipts (online + in-store) | Retail |
| [`tsp`](apps/tsp) | Thrift Savings Plan (tsp.gov) | Participant statements, 1099-R | Federal retirement (government system) |
| [`tmobile`](apps/tmobile) | T-Mobile | Bill statements | Telecom |
| [`ukg`](apps/ukg) | UKG Pro / UltiPro | Pay statements | Payroll |
| [`usaa`](apps/usaa) | USAA | Statements | Bank / insurance |
| [`usbank`](apps/usbank) | U.S. Bank | Credit-card statements | Card |
| [`verizon`](apps/verizon) | Verizon (Fios) | Bill statements | Telecom |
| [`verizonmobile`](apps/verizonmobile) | Verizon Mobile (wireless) | Monthly bills. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #31 | Telecom |
| [`walmart`](apps/walmart) | Walmart | Receipts | Retail |
| [`wellsfargo`](apps/wellsfargo) | Wells Fargo | Account statements, tax documents. UNTESTED, built without an account. Have one? Run Diagnose and attach the file to issue #27 | Bank / card / mortgage |
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
