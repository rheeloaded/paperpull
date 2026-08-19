# Providers

The running list of what PaperPull supports — and what people want next. The
goal is an ever-growing set covering the banks, cards, brokerages, utilities,
telecoms, payroll systems, and retailers real people actually use.

- **Have an account with a provider that's not here?** You're the ideal person
  to add it — see **[Adding a provider](docs/adding-a-provider.md)**.
- **Want a provider but can't build it?** Open a
  [provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
  so someone with that account can pick it up.

## Supported (15)

| App | Provider | Documents | Category |
|-----|----------|-----------|----------|
| [`ally`](apps/ally) | Ally Bank | Account statements, tax forms | Bank |
| [`amazon`](apps/amazon) | Amazon | Order invoices (full history) | Retail |
| [`amex`](apps/amex) | American Express | Statements, year-end summary | Card |
| [`dominion`](apps/dominion) | Dominion Energy (VA) | Billing statements | Utility |
| [`gap`](apps/gap) | Gap Inc. (Gap, Old Navy, Banana Republic, Athleta) | Order receipts | Retail |
| [`navyfederal`](apps/navyfederal) | Navy Federal CU | Account statements | Bank / credit union |
| [`redcard`](apps/redcard) | Target RedCard / Circle Card (TD Bank) | Billing statements | Card |
| [`robinhood`](apps/robinhood) | Robinhood | Account statements, tax docs | Brokerage |
| [`target`](apps/target) | Target | Receipts (online + in-store) | Retail |
| [`tmobile`](apps/tmobile) | T-Mobile | Bill statements | Telecom |
| [`ukg`](apps/ukg) | UKG Pro / UltiPro | Pay statements | Payroll |
| [`usaa`](apps/usaa) | USAA | Statements | Bank / insurance |
| [`verizon`](apps/verizon) | Verizon (Fios) | Bill statements | Telecom |
| [`walmart`](apps/walmart) | Walmart | Receipts | Retail |
| [`wealthfront`](apps/wealthfront) | Wealthfront | Statements, tax docs | Brokerage |

## Requested / in progress

Anyone can add a row (via a [provider request](https://github.com/rheeloaded/paperpull/issues/new/choose)
or a PR). Claim one by commenting on its issue so two people don't build the
same thing. When it merges, it moves up to **Supported**.

New to this? Look for the **`good first provider`** label — those are easy sites
(a plain statements table + a real download link). See
[Which provider is a good first build?](docs/adding-a-provider.md#which-provider-is-a-good-first-build)

| Provider | Category | Requested by | Status |
|----------|----------|--------------|--------|
| _(none yet — add yours)_ | | | |

Status legend: **requested** → **claimed** (someone's building it) →
**in review** (PR open) → merged (moves to Supported).

## How the list grows

1. **Request** — someone opens a provider request (or adds a row here).
2. **Claim** — a contributor with that account comments to claim it.
3. **Build** — follow [Adding a provider](docs/adding-a-provider.md): clone the
   closest app, rewrite its `*_site.py`, keep it read-only, test the pilot.
4. **PR** — open a pull request (the template has a safety + privacy checklist).
5. **Merge** — it graduates to the Supported table above.

Providers change their sites over time; a supported app that breaks is a
**patch** fix to that app's `*_site.py`, not a rebuild — see
[CONTRIBUTING.md](CONTRIBUTING.md).
