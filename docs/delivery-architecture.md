# How a document reaches the disk

A design note about the last step of every run, written because the same
work is done forty eight times under forty eight sets of names and nobody
could say how many ways there actually are.

The question was whether the final delivery could be pulled out of each
provider's route into one module that handles capturing the bytes,
whichever way the site hands them over. The short answer is yes, that
half of it is already built and under-adopted, and the seam is in a
different place than it first looks.

## Rerunning the census

The table below is generated. Do not edit it by hand.

    python tools/delivery_census.py
    python tools/delivery_census.py --markdown

It reads call sites and skips imports, because roughly a third of the
apps import a helper they never call, having been generated from a
scaffold that did. An app that names nothing recognizable is reported
unclassified rather than guessed at.

## The seven mechanisms

| | mechanism | what it means |
|---|---|---|
| A | attachment, download event | The provider sent `Content-Disposition: attachment`, or the markup carried a `download` attribute, and Playwright saw a download |
| B | attachment, watched folder | The same thing against a browser the user launched, where Playwright's download event never fires |
| C | inline, caught in a tab | `Content-Disposition: inline` or none, so the browser's viewer rendered it and the app went and got the bytes |
| D | the `download` attribute, read | Where the app reads the attribute rather than merely looking for it |
| E | blob and data URLs | The page built the file in its own memory |
| F | asked for through the session | Nothing was triggered. The app requested the bytes itself, from inside the page or beside it |
| G | rendered by us | There was no file. The provider showed a page and we printed it |

## The table

| provider | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| aafmaa | x |  | x |  |  |  |  |
| adp | x | x | x |  |  | x |  |
| affirm |  |  |  |  |  |  | x |
| ally | x |  |  |  | x | x |  |
| amazon |  |  |  |  |  | x | x |
| amex | x |  |  |  | x | x |  |
| amfam | x | x | x |  |  | x |  |
| applecard | x | x | x |  |  | x |  |
| anthem |  |  |  |  |  | x | x |
| att | x | x | x |  | x | x |  |
| capitalone |  |  |  |  |  | x |  |
| chase | x |  |  |  | x | x |  |
| citi |  |  |  |  |  | x |  |
| costco |  |  |  |  |  |  | x |
| discovercard |  |  |  |  |  |  |  |
| dominion | x |  |  |  | x | x |  |
| ebay |  |  |  |  |  |  | x |
| etrade | x | x | x |  |  | x |  |
| fairfaxwater |  |  |  |  |  |  |  |
| fidelity |  |  |  |  |  | x |  |
| gap |  |  |  |  |  |  | x |
| github |  |  |  | x |  | x | x |
| golden1 | x | x | x |  |  | x |  |
| kroger |  |  |  |  |  |  | x |
| meijer |  |  |  | x | x | x | x |
| mtb |  |  |  |  |  | x |  |
| mypay |  |  |  |  |  | x |  |
| navyfederal |  |  |  |  | x | x |  |
| netbenefits |  |  |  |  |  |  | x |
| newrez | x | x | x |  |  | x |  |
| paylocity |  |  |  |  |  | x |  |
| pge | x |  | x |  | x | x |  |
| redcard | x |  |  |  |  |  |  |
| robinhood | x |  |  | x | x | x |  |
| sba | x | x | x |  |  | x |  |
| schwab |  |  |  |  |  | x |  |
| smud | x | x | x |  |  | x |  |
| statefarm | x | x | x |  |  | x |  |
| target | x |  |  |  |  |  | x |
| tmobile | x |  |  |  |  |  |  |
| tsp |  |  |  |  |  | x |  |
| ukg |  |  |  |  |  | x |  |
| usaa |  |  |  |  | x | x |  |
| usbank | x |  |  |  | x | x |  |
| verizon |  | x |  |  |  |  |  |
| verizonmobile | x | x | x |  |  | x |  |
| walmart |  |  |  |  |  |  | x |
| wealthfront | x |  |  |  |  |  |  |
| wellsfargo | x | x | x |  |  | x |  |

Totals are A 23, B 12, C 13, D 3, E 11, F 33, G 12. **Twenty of the forty
eight already carry three or more.**

### The two the census cannot classify

Both are hand-rolled under local names, which is the point rather than a
defect in the tool.

**Discover** races three mechanisms and says so in its own source. "Three
mechanisms are tried in order, because which one Discover uses is the key
unknown until the live probe." A download event, a blob or PDF tab, and a
direct href fetched from the page context. Every candidate ends at one
local `_write_if_pdf`, which checks for `%PDF-` before writing.

**Fairfax Water** opens the bill in a new tab on **docsight.net**, a
third-party document host, caught at the context level rather than on the
tab. It is column C except that the document is not on the provider's
domain at all.

## What the census settles

### The exit is already universal and the entry is not

There are **109 distinct places in the app layer that write bytes to
disk**, across `write_bytes`, `save_download`, `save_as`, `shutil.move`
and a raw `open(..., "wb")`.

**All forty eight then call `receipt_pdf.validate_pdf`.** One hundred and
fifty five call sites of it.

So every run already funnels through a shared post-condition, and nothing
is shared on the way in. That asymmetry is the whole opportunity and it
also means this is a consolidation rather than an invention.

`core/paperpull_core/capture.py` exists and its docstring states the
premise already. "The pieces here are the ones that need nothing from a
provider." Seventeen of forty eight import it. Eleven others carry a
`_catch_pdf` of their own, between 139 and 155 lines each, all descended
from the same scaffold.

### The mechanism is a property of provider times attachment mode

Columns A and B are the same web behavior. The provider sends the same
header and the markup is identical. Which column an app lands in depends
on whether Playwright launched the browser or attached to one the user
launched, because the download event does not fire in the second case and
the browser saves the file itself.

Twenty nine of forty eight apps attach to a real browser, for bot
protection. That was a scaffold-wide repair in 0.28.1 and it is the
reason column B exists at all.

**An interceptor has to model this, because it is not knowable from the
provider.** The same site delivers through A or B depending on how this
program happens to be connected on that machine on that day.

### Column D is not separately observable

At capture time an `<a download>` click and a `Content-Disposition:
attachment` response both produce a download event. The distinction
matters to the route, which is deciding whether to click, and not to
whatever catches the result. The census counts D only where an app reads
the attribute.

Ninety selector strings across the apps mention `a[download]`. That is a
place an app looks, not evidence of how a file arrived, and reading it as
the latter was the first wrong number this census produced.

### Column G is not a delivery

For twelve providers there is no file to intercept. Costco, Gap, Amazon,
Walmart, eBay, Kroger, Target, Affirm, Anthem, NetBenefits, Meijer and
GitHub all show a receipt as a web page and we print it.

A module that both catches deliveries and prints pages has two unrelated
jobs. Rendering is a sibling of the interceptor and not a member of it.

### Asking for the bytes is the most common mechanism of all

Thirty three apps request the document themselves rather than triggering
anything, either with a fetch from inside the page or with
`context.request` beside it, and for nine of them it is the only
mechanism they have. No click, no header, no browser involvement.

This is worth saying plainly because it is invisible in any taxonomy
built from web delivery standards. The provider never delivers anything.
We take it.

### The document is not always on the provider's host

Fairfax Water fetches from docsight.net. Golden 1 opens a vendor tab on a
third-party host. Any interceptor must take the allowlist from the app
rather than deriving it from the provider, and that allowlist stays in
compiled Python, never in data. See
[the guard hardening note](../CONTRIBUTING.md#the-rules).

## What an interceptor can own

It can own A, B, C, D, E and F, which is thirty nine providers and every
byte that crosses a network. It cannot own G, and it should not try.

Seven apps are column G alone, so nothing about this reaches them. Five
more are column G **and** something else, meaning one app both prints a
page for some documents and catches a real file for others. That settles
the question of whether rendering belongs inside the interceptor. It
cannot, because an app needs both at once.

The shape that follows from the census is a chain rather than a handler.
Every app that has been driven against a live account already tries
several mechanisms in order, because which one a provider uses is not
knowable before that run. Discover wrote that sentence in its own source.
The chain is already the architecture. It is copy-pasted forty eight
times.

## The handoff

The coupling today is one parameter. The scaffold's contract is

```python
def download_bill(page, dl_dir, iso_date, out_path, title="",
                  trace=None) -> bool
```

**The route receives `out_path` and returns a bool.** It navigates, finds
the control, guards it, tries a session fetch, falls back to `_catch_pdf`,
and writes the file. Delivery cannot be separated while the route owns the
destination.

The contract that separates them has the route describe the request
rather than perform it.

```python
@dataclass(frozen=True)
class DocumentRequest:
    trigger: Callable[[], None] | None  # the click, where there is one
    url: str = ""                       # where the bytes can be asked for
    render: RenderSpec | None = None    # where no file exists, only a page
    expect: Identity = ...              # date, total, type, for verifying
    hosts: tuple[str, ...] = ()         # this app's allowlist, not a guess
    hints: tuple[str, ...] = ()         # mechanisms to try first
```

```python
def deliver(page, request, out_path, journal) -> Delivery
```

Four things the census forces about it.

**It owns the trigger and is not called after the click.** Every mechanism
needs its listeners armed first. A route that clicks and then asks for
help has already lost the download event.

**The chain is ordered, additive and records which candidate won.** No
rollback between attempts. The journal names the winner so a maintainer
can pin it afterwards, which is the same machinery as items 2 and 3 of
[the round-reduction work](failure-diagnostics.md).

**Identity verification lives here.** The interceptor is the only place
that sees both what was asked for and what arrived. Putting it anywhere
else means putting it in forty eight places.

**`hints` keeps the common case cheap.** A route that knows its provider
is blob-first says so, and one attempt happens rather than six.

## Risk, and the one sequencing rule

This touches the exact code path that writes files into people's
financial archives, across forty eight providers, thirty seven of which
the maintainer cannot run.

**Identity verification lands first, standalone, before any of this.**
Then a delivery regression fails closed and refuses to write, instead of
filing the wrong statement under the right name where nobody would notice
until a tax year is being reconciled. Doing the consolidation before that
safety net is the one order to avoid.

After that, migrate in the groups the census already shows. The eleven
`_catch_pdf` apps move as one because they share an ancestor. The
seventeen that import `capture` are most of the way there. The nine
that only ask through the session barely need it. Discover and Fairfax
Water get read by hand, because they always will.
