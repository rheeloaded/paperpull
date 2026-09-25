# Naming files with a template

The design for #50, before any of it is built. A person chooses how their
files are named from named fields, in the control panel, and a pattern can
skip what a provider does not know without leaving a stray separator
behind.

## What was decided

* **The engine is a small pattern language of our own**, named fields,
  optional sections, and a first-that-has-a-value choice. Not Jinja2. A
  template can never run code, an error names the field it is about, and
  a live preview is simple to build. Anything starting `{{` or `{%` is
  kept free for a Jinja mode later, if somebody ever needs one.
* **The settings page is a builder**, fields picked from a list and put in
  order, separators chosen, "skip if empty" ticked, with the pattern text
  shown beneath it for anybody who would rather type.
* **Two patterns, one for receipts and one for statements**, because they
  know different things. Any app can override its own.

## The syntax, draft

```
{date:yyyymmdd}[ - {provider}][ -- {number|kind}]
```

| Written | Means |
|---|---|
| `{field}` | the field's value |
| `{date:yyyy-mm-dd}` | a date in that shape, from `yyyy yy mm m dd d` and a month name `mmm` or `mmmm` |
| `[ ... ]` | an optional section, dropped whole, separators and all, when any field inside it is empty |
| `{a\|b\|c}` | the first of these that has a value |

Everything else is written as it stands. The result is always made safe
for the file system the way names are today, cut to the path limit, and
given `.pdf`. A clash with an existing file is still told apart by the
order number, as it is today.

## What each app actually knows

`tools/naming_fields.py` reads each app's record from its source, and with
`--installs` measures real archives, printing field names and counts and
never a value. The table below is from the maintainer's own thirty
archives on 2026-09-25. A percentage is how many of that app's records
fill the field. "yes" means the record has the field and there is no
archive to measure it against. Blank means the app's record has no such
field.

The columns map onto record fields as follows. **number** is an order
number or a document id, **kind** is the document type or category, and
**store** is the store or warehouse.

| app | records | date | kind | summary | title | number | account | period | total | store | purchase type | fulfillment |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aafmaa | 60 | 100% | 100% | 100% | 100% | 100% | 100% | 0% |  |  |  |  |
| adp | 22 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| affirm | 2 | 100% | 100% | 100% | 100% | 0% | 100% | 0% |  |  |  |  |
| ally |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| amazon | 820 | 100% | 100% | 100% |  | 100% |  |  | 97% | 0% | 100% | 16% |
| amex | 128 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| amfam |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| anthem |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| applecard |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| att |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| capitalone |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| chase | 185 | 100% | 100% | 100% | 100% | 0% | 100% | 0% |  |  |  |  |
| citi | 24 | 100% | 100% | 100% | 100% | 0% | 100% | 0% |  |  |  |  |
| costco | 7 | 100% | 100% | 100% |  | 100% |  |  | 100% | 100% | 100% | 100% |
| discovercard |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| dominion | 43 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| ebay | 47 | 100% | 100% | 100% |  | 100% |  |  | 98% | 100% | 100% | 0% |
| etrade |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| fairfaxwater | 5 | 100% | 100% | 100% | 100% | 0% | 100% | 0% |  |  |  |  |
| fidelity | 24 | 100% | 100% | 100% | 100% | 0% | 100% | 0% |  |  |  |  |
| gap | 4 | 100% | 100% | 100% |  | 100% |  |  | 100% | 100% | 100% | 0% |
| github |  | yes | yes | yes |  | yes |  |  | yes | yes | yes | yes |
| golden1 |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| kroger |  | yes | yes | yes |  | yes |  |  | yes | yes | yes | yes |
| meijer |  | yes | yes | yes |  | yes |  |  | yes | yes | yes | yes |
| mtb | 93 | 100% | 100% | 100% | 100% | 100% | 0% | 0% |  |  |  |  |
| mypay | 35 | 100% | 100% | 100% | 100% | 100% | 0% | 0% |  |  |  |  |
| navyfederal | 64 | 100% | 100% | 100% | 100% | 0% | 100% | 0% |  |  |  |  |
| netbenefits | 39 | 100% | 100% | 100% | 100% | 0% | 100% | 0% |  |  |  |  |
| newrez |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| paylocity | 12 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| pge |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| redcard | 26 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| robinhood | 99 | 99% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| sba |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| schwab |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| smud |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| statefarm |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| target | 140 | 100% | 100% | 100% |  | 100% |  |  | 100% | 76% | 100% | 23% |
| tmobile | 4 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| tsp | 25 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| ukg | 32 | 100% | 100% | 100% | 100% | 0% | 0% | 0% |  |  |  |  |
| usaa | 254 | 100% | 100% | 100% | 100% | 100% | 81% | 0% |  |  |  |  |
| usbank |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| verizon |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| verizonmobile |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |
| walmart | 61 | 100% | 100% | 100% |  | 100% |  |  | 100% | 0% | 100% | 3% |
| wealthfront | 115 | 100% | 100% | 100% | 100% |  | 100% | 7% |  |  |  |  |
| wellsfargo |  | yes | yes | yes | yes | yes | yes | yes |  |  |  |  |

### What it says

* **Every app fills date, kind and summary**, and provider and owner come
  from the app and its config. A default pattern can use only these and be
  right everywhere.
* **Receipts know much more.** Order number is filled in every one
  measured and total in nearly every receipt. Store is filled where the
  provider has stores and is empty for Amazon and Walmart, whose orders
  here are online.
* **Statements know little beyond the basics.** An account is filled
  where a provider holds several (Chase, Citi, Navy Federal, Fidelity,
  NetBenefits, USAA at 81 percent). A document number exists in four apps
  only, AAFMAA, M&T, myPay and USAA. A period is almost never filled, 7
  percent in Wealthfront and nothing anywhere else.
* **That is why the first-that-has-a-value choice matters.** A statements
  pattern that wants a number has to fall back to something, or it names
  most statements with a hole in them.

### One thing the audit found

**Amex fills no account in 128 statements**, where every other card
provider with several accounts fills it in all of them. Harmless with one
card, and a naming clash waiting to happen with two.

## The fields, first version

| Field | Receipts | Statements | From |
|---|---|---|---|
| `date` | yes | yes | the document's date |
| `year`, `month` | yes | yes | the same date |
| `provider` | yes | yes | the app |
| `owner` | yes | yes | the config, when set |
| `kind` | yes | yes | Receipt, Invoice, Statement, Tax Document |
| `summary` | yes | yes | what the app calls the document today |
| `number` | yes | four apps | order number, document id |
| `account` | where there are several | where there are several | the label the app shows, already masked |
| `total` | yes | no | the order total |
| `store` | where there is one | no | store or warehouse |
| `type` | yes | no | Online, In-Store |
| `part` | yes | yes | "2 of 3", when a document is split |

The preview shows beside each field how often this provider fills it, from
the person's own archive, so nobody builds a pattern on a field that is
always empty for them.

## Defaults that change nothing

The two default patterns reproduce today's names exactly, so upgrading
renames nothing.

```
receipts    {date:yyyy-mm-dd}[ {owner}] {provider} {summary} {kind}[ ({part})]
statements  {date:yyyy-mm-dd}[ {owner}] {provider} {summary}[ ({part})]
```

A test renders every app's names both ways, today's builder and the
default pattern, over real record shapes, and they must match to the
character.

## What building it takes

1. `core/paperpull_core/naming.py`, the parser and renderer, with its
   tests, including every example on #50 and a pattern of every error.
2. `build_pdf_filename` takes the whole record. It is called in 74 places
   across the apps with the date, the summary and the kind only, so each
   call hands over the record as well, and a guard across every app holds
   it.
3. The patterns live in config, `filename_pattern_receipts` and
   `filename_pattern_statements`, with an app's own `filename_pattern`
   winning over both. `ensure_settings` adds nothing, since an absent
   pattern means the default.
4. The panel's settings page, the builder, the text box, and the preview
   on the three newest real files of the chosen app, with each field's
   fill rate.
5. On a change, the panel offers "rename existing files to match", which
   is `--rename`'s preview and then its apply. That needs nothing new,
   because it already asks the app what a file should be called.

## Not in the first version

Folders from a pattern, such as `Statements/{year}/`. Changing case. Any
logic beyond an optional section and a fallback.
