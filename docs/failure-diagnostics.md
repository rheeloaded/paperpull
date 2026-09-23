# Cutting the rounds down

A design note, written the day Costco went from a scaffold to a working
app. It exists because that took one recording and then eight bugs that
no recording could have shown, and because the same eight would have
taken nine to twelve rounds to fix through a tester.

## What the numbers actually say

From this repo's own history.

| Provider | Rounds | Where it got to |
|---|---|---|
| AT&T | 8 | Pilot confirmed. Rounds nine and ten still open |
| E*TRADE | 4 | Still untested |
| PG&E | 3 | Working |
| SMUD, Golden 1, State Farm, Newrez | 3 each | Still untested |
| Costco | 1 recording plus a live afternoon | Working |

Thirteen providers are marked untested today, and the three-round ones
are on that list. **They are not cheaper than Costco. They are
unfinished.** Costco is the only provider that has been driven all the
way through this loop to a working Pilot, and it got there because the
maintainer could run it himself.

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
app's version. Through the same redaction as everything else, and
printed for reading before it is attached.

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
