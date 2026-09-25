# Cutting the rounds down

A design note, written the day Costco went from a scaffold to a working
app. It exists because that took one recording and then eight bugs that
no recording could have shown, and because the same eight would have
taken nine to twelve rounds to fix through a tester.

## What the numbers actually say

From this repo's own history, as it was remembered on 2026-09-22.

| Provider | Rounds | Where it got to |
|---|---|---|
| AT&T | 8 | Pilot confirmed. Rounds nine and ten still open |
| E*TRADE | 4 | Still untested |
| PG&E | 3 | Working |
| SMUD, Golden 1, State Farm, Newrez | 3 each | Still untested |
| Costco | 1 recording plus a live afternoon | Working |

Thirteen providers are marked untested today, and the three-round ones
are on that list. **They are not cheaper than Costco. They are
unfinished.** Costco got to a working app because the maintainer could
run it himself.

### The same numbers, counted from the record

`tools/rounds.py` counts them from git and the issues rather than from
memory, three ways, because each record is missing something. Shipped
is releases linked on the issue that changed the app. Grouped is
site-layer commits grouped by the tester reports between them. Named is
the highest round a commit subject gave the provider. Read as of
2026-09-22 the remembered numbers hold, AT&T 8, E\*TRADE 4, PG&E 3 and
Golden 1 3 by name, and SMUD 3 by releases. State Farm and Newrez got
their third round inside one commit that named seven providers and no
numbers, so by name they show 2.

Two things in the table above were wrong on the day. SMUD was not
untested, its Pilot saved five bills on 2026-09-22 after three rounds,
the first provider a tester took all the way. PG&E was not working, and
its tester's latest Pilot still saved nothing. The tool also found one
of its own mistakes. AT&T's issue linked 0.27.0, which carried nothing
for AT&T, and counting it gave nine.

The baseline, `tools/rounds.py --as-of 2026-09-24`, the day 0.34.0
shipped the first of the features meant to move it. Item 6 compares
against this.

| Provider | Status | Shipped | To a working Pilot | Days |
|---|---|---|---|---|
| AT&T | Working | 12 | 8 | 2.1 |
| E\*TRADE | Working, newest statement only | 7 | 6 | 3.2 |
| SMUD | Working | 4 | 3 | 1.1 |
| GitHub | Working | 4 | 1 | 0.4 |
| PG&E (repair) | In progress | 6 | | |
| Golden 1, State Farm, Newrez | In progress | 6 each | | |
| Meijer, American Family | In progress | 4 each | | |
| eBay, ADP, Target (repair) | In progress | 3 each | | |
| Kroger | In progress | 2 | | |
| Costco | In progress with a tester | 1 | | |
| Wells Fargo, SBA, Verizon Mobile | Untested, 4.6 days | 2 each | | |

Four providers have reached a working Pilot through a tester, at a
median of 4.5 rounds and a worst of 8, in a median of 1.6 days. Eleven
are still going, at a median of 4 rounds so far and a worst of 6.

This table was first written with three working and twelve in progress,
all twelve owed by the maintainer. An independent review of the tool
found both were its own bugs. GitHub's tester wrote that Pilot
"successfully captures 5", which the first pattern for a working Pilot
did not read, and a maintainer's reply that linked no new build was not
counted as a move at all, so two issues waiting on their tester read as
waiting on the maintainer. Both are fixed and tested. What was true on
the afternoon it was written is that most issues in progress ended on a
tester's report, and the evening's 0.34.0 answered them.

So Costco is not the hard case. Costco is the case we have ground truth
for, and the ground truth is that the expensive half comes after the
site is understood.

## Why a recording cannot close that half

A recording says what a person did. Every bug that cost a round on
Costco was about what happens when a program does the same thing.

    the selector was Playwright's, the browser rejected it
    the rows had not been drawn yet
    a hash change loads nothing, so the page never refreshed
    the dialog found was the hidden one Bootstrap leaves in the markup
    the modal locks the page, so printToPDF rendered one blank screen
    saving a receipt hid the page and nothing put it back
    the list read and the list pressed were different lists
    a till prints no currency sign, so no item parsed

None of those is observable by watching a person. Several are only
observable **on the second iteration**, which is a thing no survey and
no recording ever reaches.

## Why Diagnose does not close it either

Diagnose surveys the page **through the app's own code**. It calls
`goto_orders`, then `open_tab`, then `read_rows`, then `goto_receipt`,
and reports what each gave back.

That makes its depth a function of how correct the app already is. On
the Costco scaffold it would have said "no rows, no receipt to open" and
stopped, which is the same thing the first Pilot said. It only becomes
the rich file it is meant to be once navigation works, and navigation
working was five of the eight bugs.

**A survey is bounded by the code being surveyed.** That is the flaw,
and it is why running Diagnose alongside Record would have saved one
round at most.

## The thing that would work

Capture raw page state **at the moment of failure**, without going
through the app's own navigation, and write it without anybody being
asked to.

### 1. The selector census

The single highest-value artifact. For every selector the app relies on,
report what the page says about it.

```json
{
  "selector": "[role=dialog], [aria-modal=true]",
  "used_for": "receipt_area",
  "matched": 1,
  "visible": 0,
  "first": [{"tag": "div", "class": "modal fade", "box": [0, 0],
             "display": "none", "text_len": 281}]
}
```

That one entry is bug four, stated outright, in round one. Run over
every entry in `FALLBACK`, the census would have reported all of the
following in a single file.

- **bug one** as `"error": "not a valid selector"`, because an invalid
  selector fails loudly instead of matching nothing
- **bug two** as `matched: 0` on the first look and `matched: 5` after a
  wait, which is timing written down
- **bug four** as `matched: 1, visible: 0`
- **bug six** as every selector reporting `visible: 0` after a capture
- **bug seven** as two counts that should agree and do not

Five of eight, from one file, in one round.

### 2. The capture postmortem

When a PDF comes out under the minimum size, or a receipt does not
render, save what was on screen next to it. The masked text, the DOM
outline of the block that was isolated, its box and its scroll height,
and the computed overflow on `html` and `body`.

`989 bytes` tells a maintainer nothing. `isolated a node measuring 0 by
0 while body overflow was hidden` is bugs four and five together.

### 3. Written without being asked

The tester runs Pilot. If anything fails, the file is already in
`Diagnostics/` when it finishes, and the run says so in one line. No
second command, no second round spent asking for one.

This matters more than it sounds. Costco's tester ran Record and not
Diagnose, and the receipt line format, which Diagnose would have shown,
cost its own round as a result.

### 4. One file, one upload

`Diagnostics/failure-<command>-<time>.json`, carrying the census, the
postmortem, the last twenty log lines, the console errors, and the
app's version. Built on the list of what may leave, and printed for
reading before it is attached.

Diagnose writes the same survey on purpose, as
`Diagnostics/survey-diagnose-<time>.json`, and that is the file to
attach when a provider needs a first test or a repair rather than
having failed. The other file Diagnose writes,
`diagnose-<provider>.json`, is the detailed one. It carries the page's
title, the URL with its query string, the text of the rows and the
labels of the controls, and in half the apps a full page screenshot
sits beside it. That is what a repair is actually read from and it is
not something to attach anywhere. The panel used to say to attach it.

## What this would have cost Costco

Round one, the scaffold, fails. The failure file carries the census and
the postmortem. Bugs one, two, four, five, six and seven are all visible
in it. Round two fixes them and asks for a Pilot. Bug eight, the
currency sign, shows in the postmortem's captured text. Round three
lands it.

**Nine to twelve rounds becomes three.** Not one. A maintainer still
cannot run the thing, and no diagnostic changes that. But three rounds
is a week rather than a month, and a volunteer will still be answering
after three.

## What the research changed, and the canary proved

The first version of this collected what looked useful and ran it
through redaction. That was the wrong trust boundary, and a canary page
said so outright.

Build a page carrying a distinctive fake secret in every channel a
browser offers. Visible text, a hidden input, an aria-label, a class, an
id, a URL path, a query string, a fragment, a title attribute, a test
id, a console log, an uncaught exception. Produce an export and assert
that none of them comes out.

**Eleven of twenty one came out.** A name through the page title. A
street and a card tail through the receipt's own text, because they are
words and the masking knew about digits. An element id and a class,
straight out. Costco passing an audit earlier was luck, because its
receipt happened to be mostly digits.

So the export is now built the other way around. **Only an enum, a
boolean, a bounded count, a duration, or a word from our own source may
leave.** Everything else the browser can give is denied, and a field
that is not on the list does not reach the file, so a provider added
tomorrow cannot widen it by accident. An exception becomes one word from
a fixed list rather than its message. A step is lowercase prose written
in the source, and a capital letter is enough to refuse it, because page
text has capitals and our own steps do not.

The one thing allowed out of a class attribute is whichever of a fixed
vocabulary of layout words it contains, whole tokens only. That keeps
`div.modal.fade`, which was the answer to the bug that cost a day, and
throws away everything else. A class of `customer-4821-panel` reduces to
nothing.

Twenty one of twenty one clean now, and the canary is a test that runs
whenever the schema changes.

## The journal and the checkpoints

The census says what the page looked like when a run gave up. It cannot
say anything about a state the run never reached, and that is what makes
the bugs stack. So there is a second thing, kept as the run goes.

`core/paperpull_core/journal.py`. Three kinds of entry and nothing else.

    an operation    the app was about to do something it named
    a choice        it found N candidates and took the nth of them
    a checkpoint    the page's state at a transition

**A choice is the one a census cannot replace.** Counting one collection
and acting on the nth of another reads, from outside, exactly like a
page that did not load. That bug took two live runs to find with a
browser in front of me. Recorded, it is two lines naming different
collections with different counts, side by side.

**A checkpoint is what carries an earlier layer.** A list that was
visible at one checkpoint and is still present but no longer visible at
the next is a page something hid and did not put back, stated while the
run is still going, long before the symptom appears.

The address is the exception worth explaining. Whether it changed, and
in which part, is the difference between a page that reloaded and one
that did not, which was a bug of its own. The journal keeps the last
address to compare against and never writes it down. What comes out is
one of same, hash, query, path, host.

Everything in it goes through the same allowlist as the export, and the
canary runs over the journal too.

## The eleven that drive an API

Eleven of the forty eight declare no selectors, because they read a JSON
API rather than a page. The selector census had nothing to say about
them, so a quarter of the catalogue got a page state and little else.

`core/paperpull_core/api_census.py` is their half. It listens rather
than asking, on Playwright's response event, so it works whatever way an
app makes its call and no app had to change how it calls anything. Page
driven apps get it too, because they call APIs as well.

Per call, the path with anything id shaped in it masked, the method, the
status, the kind, the names of the query parameters, and the shape of a
JSON answer.

**The shape is the point and it is the risk.** A maintainer needs the
field names, because an API that renamed `documents` to `items` looks
from outside exactly like an account with nothing in it. Those names are
the provider's schema, the same for every customer.

Except when they are not. An object keyed by account number exists, and
there the keys are the values. So a key that looks like an identifier is
masked the way a path segment is, and no value is ever kept, only the
name of its type.

    /v1/accounts/12345678/documents  ->  /v1/accounts/#/documents
    ?year=2026&token=SECRET          ->  query_keys [token, year]
    {"88213344": {"balance": 99.99}} ->  {"#": {"balance": "number"}}

The sentence it exists to write is the one that costs a round every
time. **An empty list at status 200 is an empty account or a filter that
excluded everything, and those are different problems.** It says which
it cannot tell, rather than leaving a maintainer to guess.

## Guessing the wait, and finding out which guess was right

Two of Costco's eight bugs were the wrong kind of wait. Rows read before
they were drawn, and a hash-only change of address that loads nothing.
Written blind, the right wait is a guess, so `paperpull_core.ready` takes
several guesses in order and reports which one got the page ready.

```python
got = ready(page, [network_idle(), count_reaches("tr.order", 1),
                   count_settles("tr.order")],
            invariant=has("tr.order"), budget_ms=20000,
            journal=_journal, name="order rows")
```

The rules are the reason it is safe.

* Every strategy only waits. None clicks, reloads, navigates or goes back,
  so trying one and then the next changes nothing on the page. A strategy
  can only be built by the module, and handing it a function is refused.
* The invariant is required and decides. A wait that returned has not
  proved anything, and a page already ready costs one question and no
  wait, which measured the same as the bare count it replaces. It is
  built by the module too, `has`, `url_matches`, `new_source`,
  `load_complete` or `all_of`, each one question that does not wait. A
  check of the app's own could reload the page, or read text through a
  locator and wait thirty seconds each time it was asked, outside the
  budget. The polling waits ask it on every look, so a page that comes
  right early ends the wait, and the journal says it came right while
  waiting rather than crediting a wait that did not get it there.
* One budget for the whole call. Nine guesses do not turn a ten second
  failure into a ninety second one. `within_ms` caps a guess that could
  hang, a change of address that never comes.
* Nothing raises. A closed page, an invariant that threw, a selector in
  Playwright's dialect, each is an outcome in the answer.

The answer goes to two places. The journal records every attempt, its
outcome and its milliseconds, as words from fixed lists, and the failure
file says in a sentence which wait worked. A run that worked writes no
file, so the first answer for each wait is also printed once, as a
`Waited for` line, and the tester guide and every tester README ask for
those lines to be pasted. The next round keeps the winner and drops the
rest.

Adopting it is per app and happens in each provider's next round, at the
waits that are guesses. `test_every_app_waits_safely.py` checks every app
that does passes its journal, a name, an invariant and a budget.

## The page's shape, in a recording

A recording names each control the way a person reads it, which is what
a locator is written from, and nothing about where that control sits.
Whether it is the third of twelve rows of the same shape, whether its
parent is a custom element or a shadow root, whether a hidden twin sits
beside it. Those are what a selector is actually written from, and every
one cost Costco a round.

So each recorded step now carries the structure around the control. The
path from the body down to it, its neighbors at every level, and three
levels inside it. Each element is a tag off a fixed list, `custom` for
one the site defined and `other` for anything else, a role off the ARIA
list, the names of the attributes it carries from a fixed list with the
rest counted, how many children it has, whether it is visible, and
whether it has any text of its own. Never the text, never a value, never
an address.

It is built on the allowlist twice. The page builds each node from the
lists, and Python builds it again from what the page sent, because any
script on a provider's page can call the recorder's binding. The canary
page now plants secrets in attribute values, attribute names, a custom
element's tag, an inline style, a shadow root and text sixteen levels
down, and none reaches a recording or a failure file. A step's shape is
capped at 300 elements and says when it was cut, and costs about a
millisecond per click on a page of three thousand rows.

`tools/read_recording.py` prints it as an outline with the control
marked.

## What this does not fix

- A provider that only breaks on an account with something unusual on
  it, a second membership, a joint account, a closed card
- Anything behind a challenge the tester has to answer by hand
- Judgement about whether a saved PDF is the *right* document, which
  needs a person to look at it

## Where it lives

Built. `core/paperpull_core/failure.py`, called by every one of the 48
apps at the point each already knows it has given up, with each app
contributing its own `FALLBACK` dictionary and nothing else. One file
per run, taken at the first failure while the page is still sitting on
it.

Proved against the live Costco page with the selectors exactly as they
were wrong on day one. It named the Playwright-dialect selector, named
the engine-prefix one, and reported the hidden Bootstrap modal as
`matched 1, visible 0, div.modal fade, box [0, 0]`, with the reading
underneath saying a framework leaving a hidden copy of a dialog in the
markup looks exactly like that. Four kilobytes, no emails, no amounts,
no names, nothing personal in it.
Thirty-seven of the forty-eight apps declare one, 362 selectors between
them. The other eleven drive an API rather than a page, so their census
comes back empty and the rest of the file, the page state and the text
it was reading, still applies. A census of the request that failed and
its status is what those eleven want, and is not built yet.

The round count is `tools/rounds.py`. Run it with `--as-of` to read the
record as it stood on an earlier day, which is how a before and after
gets compared without trusting anybody's memory, including the tool's.
