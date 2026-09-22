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

## What this does not fix

- A provider that only breaks on an account with something unusual on
  it, a second membership, a joint account, a closed card
- Anything behind a challenge the tester has to answer by hand
- Judgement about whether a saved PDF is the *right* document, which
  needs a person to look at it

## Where it would live

In `paperpull_core`, called by the orchestrator on any failed step, with
each app contributing its own `FALLBACK` dictionary and nothing else.
Thirty-seven of the forty-eight apps already declare one, 362 selectors
between them, so the census costs almost nothing to turn on across all
of them. The other eleven drive an API rather than a page and need a
different census, most likely the request that failed and its status.
