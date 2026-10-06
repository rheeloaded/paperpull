"""What a page's words may become in a file somebody posts.

A recording, a Diagnose file, a download attempt and a failure file are
all written to be attached to a public issue. Each used to take what a
page said and run it through redaction, which removes the shapes
somebody thought of, a long run of digits, an email, an amount, a
greeting, the owner's name. A word is none of those. An account's id
made mostly of letters goes straight through in a downloaded file's
name, and so do a street address and a vehicle in the samples a
Diagnose file keeps.

So nothing here removes anything. A file is built from this list of
words. A word on it is kept as the page wrote it. Any other word is
written as its shape, every letter as a and every digit as 9, so a link
reading "Statement for Zorvex 0400" comes out as "Statement for aaaaaa
9999". A maintainer still sees which control it was, how long the rest
was and where its numbers sat, and nothing that was only the account's.

    from paperpull_core.words import shape, words_for, write_shaped

    words = words_for(provider="Example Bank", site=site)
    label = shape(text, words)
    write_shaped(path, info, words)

WHAT MAY LEAVE

    a word on the list         KNOWN below, written in this file
    the app's own name         from what its source calls it, words_for
    a shape                    a for a letter, 9 for a digit
    punctuation                one character at a time, as it was
    a fixed string             Fixed, for a sentence or a time we wrote
    a count or a yes or no     bounded, in shape_tree

The account holder's own name, as the app was given it, is never kept,
even when a part of it is a word on the list. A greeting's name, an
email address and an amount are written as words of ours before
anything else is looked at, so that their length does not leave either.

ADDING A WORD

A word goes on the list when it is the kind of word a provider writes
on a page or in an address for every customer alike. Never a name, a
place, a street, a vehicle, a merchant or a product, and never because
one recording needed it. A word left off costs a maintainer one round of
asking. A word that should not be there costs somebody their privacy,
and it cannot be taken back once posted.
"""
from __future__ import annotations

import functools
import json
import re
import string
from typing import Iterable

# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------
# Lowercase, split on whitespace. A word of one letter is never on it, so
# an initial always leaves as its shape.

_GRAMMAR = """
about above across after again against ago all almost along already also although
always am among an and another any anybody anyone anything anywhere are around as at
away back be became because become becomes been before behind being below beside
besides between beyond both but by can cannot could did do does doing done down
during each either else enough even ever every everyone everything few for from
further get gets getting give given gives giving go goes going gone got had has have
having he her here hers herself him himself his how however if in inside instead into
is it its itself just last least less let lets like likely many may me might mine more
most much must my myself near nearly need needed needs neither never new next no
nobody none nor not nothing now of off often on once one only onto or other others
otherwise our ours ourselves out outside over own per please rather same see seen
several shall she should since so some someone something sometimes soon still such
than that the their theirs them themselves then there therefore these they this those
though through thus till to together too toward towards under unless until up upon us
very via was way ways we well were what whatever when whenever where whether which
while who whoever whole whom whose why will with within without would yet you your
yours yourself yourselves don doesn didn isn wasn aren weren won wouldn couldn
shouldn
"""

_NUMBERS = """
zero one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty
seventy eighty ninety hundred thousand million billion first second third fourth
fifth sixth seventh eighth ninth tenth half quarter double single multiple twice
number numbers numbered nbr num no
"""

_TIME = """
year years yearly annual annually month months monthly week weeks weekly biweekly
semimonthly semiannual day days daily date dates dated time times timed timing today
yesterday tomorrow tonight now current currently recent recently latest newest
oldest earliest previous prior past future period periods cycle cycles season
seasonal ytd mtd qtd fiscal calendar am pm morning afternoon evening night hour hours
hourly minute minutes min mins second seconds sec secs ms millisecond milliseconds
timestamp timezone utc gmt est edt cst cdt mst mdt pst pdt since thru through until
till start started starting starts end ended ending ends begin beginning begins began
early earlier late later lately due expires expiry expiration
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur
thurs fri sat sun weekday weekend
"""

_PAGE = """
home homepage menu menus main nav navigation navbar header footer sidebar breadcrumb
breadcrumbs back forward next previous prev more less show shows showing shown hide
hides hidden view views viewing viewed viewer open opens opening opened close closes
closing closed cancel canceled cancelled ok okay yes submit submitted continue
continued done save saves saved saving edit edits editing delete deleted remove
removed add added create created update updated updates change changed changes manage
managed managing select selected selection choose chosen choice choices option
options apply applied reset clear cleared refresh reload retry try tried again search
searched searching filter filters filtered sort sorted sorting order ordered
ascending descending asc desc expand expanded collapse collapsed toggle toggled
details detail summary summaries overview settings setting preferences preference
profile help support contact contacts faq faqs learn info information tips tip guide
center centre page pages paging pagination pager top bottom left right link links
linked button buttons btn tab tabs tabbed list lists listed listing item items row
rows column columns col cols table tables cell cells grid card cards panel panels
dialog dialogs modal modals popup popups popover window windows frame frames iframe
icon icons image images img logo label labels labeled labelled title titles text
texts heading headings section sections content contents container wrapper body
field fields input inputs form forms checkbox checkboxes radio dropdown dropdowns
picker pickers selector selectors listbox combobox textbox textarea menuitem tooltip
banner alert alerts notice notices message messages notification notifications inbox
mailbox mail mailed mailing email emails print prints printable printer printing
printed preview download downloads downloading downloaded upload uploads uploaded
export exports exported import imported share shared sharing send sending sent
request requests requested go goto visit visited find found get got access accessed
login logon logoff logout logged signin signon signout sign signed signing register
registered registration enroll enrolled enrollment unenroll unenrolled activate
activated deactivate enable enabled disable disabled verify verified verifying
verification confirm confirmed confirming accept accepted agree agreed decline
declined proceed finish finished complete completed incomplete pending processing
processed loading loaded load ready error errors warning warnings success successful
successfully failed failure failures fail unavailable available unable denied
expired invalid valid required optional step steps action actions click clicked
clicking press pressed tap fill filled check checked uncheck unchecked skip skipped
stop stopped wait waited waiting begin opening closing new old other more all
welcome hello hi hey good thanks thank sorry standard basic advanced simple quick
merchant merchants seller sellers vendor vendors partner partners
any each every none select ok
"""

_PEOPLE = """
account accounts acct accts user username usernames users member members membership
customer customers client clients owner owners holder holders cardholder cardmember
accountholder primary secondary joint authorized authorised beneficiary
beneficiaries spouse dependent dependents personal business businesses individual
family household employer employers employee employees company companies
organization organisation password passwords passcode passkey pin code codes otp mfa
sso twofactor factor security secure secured question questions answer answers
device devices trust trusted remember session sessions timeout token tokens key keys
id ids identity identification challenge captcha robot human nickname nicknames name
names middle full preferred address addresses street phone phones mobile cell
contact person people you your yours
"""

_DOCUMENTS = """
document documents doc docs edoc edocs edocument edocuments statement statements
stmt stmts estatement estatements ebill ebills bill bills billing billed invoice
invoices receipt receipts ereceipt ereceipts letter letters notice correspondence
report reports reporting form forms tax taxes taxform taxforms taxable confirmation
confirmations confirms trade trades traded agreement agreements disclosure
disclosures prospectus prospectuses policy policies declaration declarations decs
proof coverage coverages claim claims eob eobs explanation benefit benefits
paperless paper electronic digital archive archived archives history historical
record records file files filename filenames pdf pdfs copy copies original duplicate
attachment attachments enclosure certificate certificates contract contracts terms
conditions schedule schedules yearend summary notices supplement supplemental
amendment amended corrected correction form1099 consolidated composite
"""

_MONEY = """
payment payments pay pays paid paying payer payee payees payable payout payouts
payoff autopay recurring scheduled overdue balance balances amount amounts total
totals subtotal minimum maximum max fee fees charge charges charged credit credits
credited debit debits debited deposit deposits deposited withdrawal withdrawals
withdraw transfer transfers transferred wire wires ach eft check checks checking
savings saving money market cd cds ira iras roth rollover hsa fsa brokerage
retirement pension annuity annuities investment investments invest investing
investor investors portfolio portfolios position positions holding holdings asset
assets fund funds funding mutual stock stocks share shares bond bonds dividend
dividends interest principal escrow mortgage loan loans lending lend borrow borrower
lender line lines rate rates apr apy cash cashback reward rewards point points mile
miles bonus offer offers dispute disputes fraud visa mastercard wallet bank banks
banking online atm branch routing transaction transactions txn txns activity
activities posted post cleared purchase purchases purchased refund refunds refunded
return returns returned sale sales sold buy bought sell order orders shipment
shipments shipping shipped ship delivery deliveries delivered tracking track package
packages store stores warehouse pickup curbside instore cart checkout price prices
pricing quantity qty product products withholding withholdings deduction deductions
deductible earnings earning gross net wage wages salary paycheck paychecks paystub
paystubs stub stubs payslip payslips payroll direct employment job jobs hours
overtime pto leave insurance insured insurer premium premiums copay coinsurance plan
plans policyholder auto home homeowners renters life health
pharmacy provider providers network vehicle vehicles
car cars property utility utilities energy electric electricity gas water sewer
trash usage meter service services outage phone wireless internet tv cable data
toll tolls tag tags transponder violation violations usd dollar dollars cent cents
currency estimated estimate estimates actual budget budgets goal goals spending spend
contribution contributions contribute allocation allocations distribution
distributions vesting vested match matched financial finance finances gift gifts
coupon coupons discount discounts membership subscription subscriptions renewal
renew renewed premium income expense expenses year balance due paid trip trips ride
rides eats delivery fare fares
"""

_WEB = """
http https www com net org gov mil edu io co uk api apis rest graphql gql json xml
html htm xhtml csv tsv txt ajax svc static assets asset js css app apps application
applications web webapp site sites portal portals auth oauth saml callback redirect
redirects returnurl url urls uri href src path paths host hosts query params param
parameter parameters fragment hash index default root base version versions status
state states data result results response responses kind kinds type types value
values uuid guid count counts size sizes limit offset per range ranges modified
fetch init config meta metadata cookie cookies headers header length encoding
charset utf gzip octet stream binary plain blob png jpg jpeg gif svg webp zip docx xls
xlsx xlsm ods odt rtf ofx qfx qbo qif eml ics myaccount myaccounts dashboard desktop
browser browsers chrome edge firefox safari mobile secure login www2 cdn
"""

# The words the files themselves are written in. The keys of a recording, a
# failure file and a Diagnose file, an element's kind, a role, the names of
# attributes the page shapes are built from, and the phrases the apps use
# for what they were doing. A word of ours that was not here would come out
# as its shape, which loses nothing private and makes the file harder to
# read, and core/tests/test_words.py fails on it.
_OURS = """
paperpull recording recorded survey surveyed diagnose diagnostics failure kind
provider schema command note notes extra postmortem journal entries entry dropped
oldest limit seen counts bodies read too large unreadable elsewhere matched visible
counted evaluation engine declared playwright css syntax invalid nodes node signal
classes has testid box display visibility position len on screen ready overflow
scroll height width anything largest errors rejections saved bytes expected least
kept candidates accepted rejected identity outcome refused unverified checked
verified unknown chars requests method methods query keys shape shapes path step
steps action locator how role roles tag tags marked where unresolved structure root
truncated children child other attrs attr data shadow in frame opened tab new effect
navigated landed download printed requests guard allows providers own site repeat
malformed print without stamp fill submit click select check value redacted at
waits winner elapsed strategy strategies attempts already late satisfied while
waiting phase phases operation ordinal chose collection selector precondition
attached result route change same unnamed wait sign documents rows recognized
collected samples category period error timestamp signed out challenge row table
pdf links download attrs found title survey pages responses opened from off
followed bill controls safe headings url status type method post keys query shape
control tab role text href category summary period date kind has link landed
discovery trace attempt attempts cards became empty missing years offered history entries
customer notes isolated isolation answered unanswered reach reached raised render
rendered renders validate validated validation capture captured capturing archive
opened deliver delivered fetch fetched list listed menu named neither nor nothing
partway pass passed place placed prints refused record session show showed stopped
take taken trip trips twice went appear asked call came carried checks could
different gave hand looked made pickers query raise searched store survey tab tabs
when would year twice span spans display block inline flex contents none
static relative absolute fixed sticky visible hidden collapse scroll auto clip
loading interactive complete same hash host unknown timeout navigation detached
selector not_found blocked spinner skeleton placeholder backdrop scrim lightbox fade
shown invisible inactive active expand enabled container wrapper inner outer
column item cell print printable noprint screen only
accordion drawer overlay sheet elements facts flow dom idle locked parse parser
patch put reason restored settled test watching string bool boolean null float int
str list nonetype more key keys item items bytes kept nested deep deeper example
area run runs shell tile tiles
aborted agrees ahead alone ambiguous appeared arrived assignments authorization
batch batches calls carrying channel characters charitable clusters connected dataset
datasets demand description discovered distance distinct drawn duration ease
element eligible events expression external extracted finishing folder food
free frequency fuel fulfillment generic grocery hint holds include insert known layout
legacy locale longest look looks manual mapped marketplace markets masked matches
media mobility mode moved naming occurrence opener openers origin originating
origins parent parsed pattern photo pump purchaser quarterly raw readable
received redirected redrawn ref refetch reloaded resource review sample say says said
scheme screenshot scrolled scrolling segments selects self serve station super
supermarkets system ticked travel turned turns ui unchanged unfinished unit units
unread unsure upcoming variables verdict walked want wanted wash words written wrong
country language categories workflow crypto reference lookup alias care msg uid csrf
seq januar februar juni oktober dezember okt dez kilobytes source sources
switcher layer maintainer repair repairs repaired built public ran
answering carries census clickable crowded decides embedded false fits hold land
listened mechanism reads refuses sits stand sure trying unlabeled unrecognized viewers
walk word side stayed proxy flight gal gallon gallons regular plus diesel unleaded
approved minus symbol
v1 v2 v3 v4 v5 v6 v7 v8 v9 1xx 2xx 3xx 4xx 5xx
"""

# Kinds of element, the ARIA roles and the attribute names a page's shape is
# built from, so the recorder's structure lists come through whole.
_MARKUP = """
html head body title meta link script style div span section article aside nav main
header footer form fieldset legend label input button select option optgroup
textarea output details summary dialog menu ul ol li dl dt dd table caption thead
tbody tfoot tr th td col colgroup iframe img picture svg canvas video audio source
track figure figcaption pre code blockquote address abbr em strong small sub sup b i
u s q br hr wbr time noscript object progress meter template slot frameset
search custom other text a h1 h2 h3 h4 h5 h6
alert alertdialog application banner cell checkbox columnheader combobox
complementary contentinfo definition directory document feed grid gridcell group
heading list listbox listitem log marquee math menubar menuitem menuitemcheckbox
menuitemradio navigation note presentation progressbar radio radiogroup region row
rowgroup rowheader scrollbar searchbox separator slider spinbutton status switch tab
tablist tabpanel term textbox timer toolbar tooltip tree treegrid treeitem
aria testid automation qa cy labelledby describedby controls expanded haspopup
modal live pressed owns sort tabindex readonly colspan rowspan placeholder rel alt
src href target action lang scope multiple disabled checked selected required
hidden open download value values id class name type role for method
"""

# German, since amazon.de is supported and a recording there reads in it.
_GERMAN = """
rechnung rechnungen bestellung bestellungen konto kontoauszug kontoauszüge
herunterladen drucken anzeigen ansehen übersicht zahlung zahlungen datum jahr monat
bestellt geliefert versand lieferung rücksendung rücksendungen details mein meine
alle weitere zurück weiter suchen
"""

KNOWN = frozenset(
    w for w in " ".join((_GRAMMAR, _NUMBERS, _TIME, _PAGE, _PEOPLE, _DOCUMENTS,
                         _MONEY, _WEB, _OURS, _MARKUP, _GERMAN)).lower().split()
    if len(w) >= 2)

# What follows an apostrophe in a contraction, kept after a word so that
# "don't" is not written "don'a". A possessive's s is one of these, and the
# name before it is shaped like any other word.
_AFTER_APOSTROPHE = frozenset(("s", "t", "d", "m", "re", "ve", "ll"))
_APOSTROPHES = frozenset(("'", chr(0x2019)))

# A file's own kind, kept after its last dot in lowercase. Anything else
# after a dot is a word like any other.
EXTENSIONS = frozenset("""
pdf csv tsv txt zip gz xls xlsx xlsm ods doc docx odt rtf html htm xml json ofx qfx
qbo qif png jpg jpeg gif tif tiff bmp webp heic eml msg ics
""".split())

# Everything that is neither a letter nor a digit nor a space, and is
# written as itself. A character outside these leaves as "?".
_MARKS = frozenset(string.punctuation) | frozenset(chr(c) for c in (
    0x2022, 0x00b7, 0x2026, 0x2013, 0x2014, 0x2018, 0x2019, 0x201c, 0x201d,
    0x00ab, 0x00bb, 0x00a9, 0x00ae, 0x2122, 0x00b0, 0x00a7, 0x00b6, 0x20ac,
    0x00a3, 0x00a5, 0x00a2, 0x00d7, 0x00f7, 0x00bf, 0x00a1
))

# Written in place of what they stand for before anything else is looked
# at, so their length does not leave either. Both words are on the list.
EMAIL = "<email>"
AMOUNT = "<amount>"


class Fixed(str):
    """A string this program wrote, a sentence in its source or a time off
    its own clock, which shape_tree leaves as it is. Never a page's."""
    __slots__ = ()


# ---------------------------------------------------------------------------
# One string
# ---------------------------------------------------------------------------

_RUN = re.compile(r"[^\W_]+|\s+|.", re.S)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_MONEY_RE = re.compile("[$%s%s]" % (chr(0x20ac), chr(0x00a3))
                       + r"\s?-?\d[\d,]*(?:\.\d+)?")


@functools.lru_cache(maxsize=128)
def _declared_hosts(path: str) -> tuple:
    """The hosts a site module's source lists in ALLOWED_HOSTS, read from
    the file and never from the module. An app can add to that list while
    it runs, and Golden 1 adds its vendor's host when that tab opens, so
    what the module holds then is partly a page's."""
    import ast
    from pathlib import Path
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return ()
    named = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            named[node.targets[0].id] = node.value.value
    hosts = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ALLOWED_HOSTS" for t in node.targets):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "ALLOWED_HOSTS" and node.value is not None:
            value = node.value
        else:
            continue
        for part in ast.walk(value):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                hosts.append(part.value)
            elif isinstance(part, ast.Name) and part.id in named:
                hosts.append(named[part.id])
    return tuple(hosts)


def words_for(provider: str = "", site=None) -> frozenset:
    """The app's own words, from what its source calls it.

    The provider's name as the app writes it, the name of its site module
    and the hosts that module's source lists, so "American Family" and
    amfam_site give american, family and amfam, and Golden 1 its vendor's
    host. All of it is written in the app's source. Nothing here is read
    from a page, a config or a host learned at run time."""
    found = set()
    module = str(getattr(site, "__name__", "") or "").rsplit(".", 1)[-1]
    if module.endswith("_site"):
        module = module[:-len("_site")]
    path = getattr(site, "__file__", None)
    hosts = _declared_hosts(str(path)) if path else ()
    for source in (provider, module) + hosts:
        # A run of letters, and a run of letters and digits whole, so the
        # host golden1.com and the module golden1_site read as golden1 and
        # not as golden9. A digit on its own is never one of these.
        for run in re.findall(r"[^\W_]+", str(source or "")):
            if len(run) >= 2 and not run.isdigit():
                found.add(run.lower())
        for run in re.findall(r"[^\W\d_]+", str(source or "")):
            if len(run) >= 2:
                found.add(run.lower())
    return frozenset(found)


@functools.lru_cache(maxsize=64)
def _vocabulary(words: frozenset, private: tuple) -> frozenset:
    """The list, the app's own words, and never the owner's."""
    return (KNOWN | words) - frozenset(private)


def _private() -> tuple:
    from .redact import private_words
    return tuple(sorted({w.lower() for w in private_words()}))


# The only words of two letters a run may be split into. Any word of the
# list could be, and "Mayon" read as may and on, a surname kept whole.
_JOINERS = frozenset(("my", "id", "of", "to", "on", "in", "by", "at", "or"))


def _splits(low: str, vocab: frozenset) -> bool:
    """Whether a run of letters is words of the list written together,
    myaccount or statementsandtaxes. Three letters at least a piece, or
    one of the few short words such a run is joined with."""
    n = len(low)
    if n < 5 or n > 40:
        return False
    ok = [True] + [False] * n
    for i in range(2, n + 1):
        for j in range(max(0, i - 24), i - 1):
            piece = low[j:i]
            if ok[j] and piece in vocab and (len(piece) >= 3 or piece in _JOINERS):
                ok[i] = True
                break
    return ok[n]


def _camel(run: str) -> list:
    """statementDate as statement and Date, PDFFile as PDF and File."""
    pieces, start = [], 0
    for i in range(1, len(run)):
        a, b = run[i - 1], run[i]
        after = run[i + 1] if i + 1 < len(run) else ""
        if (a.islower() and b.isupper()) or (a.isupper() and b.isupper() and after.islower()):
            pieces.append(run[start:i])
            start = i
    pieces.append(run[start:])
    return pieces


def _known(piece: str, vocab: frozenset) -> bool:
    """A word of the list, in any case. Words written together are looked
    for only in lowercase, the way an address or a key joins them, since a
    capitalized word is how a page writes a name."""
    low = piece.lower()
    if low in vocab:
        return True
    if not piece.islower():
        return False
    # ebusiness, eservices, the electronic prefix on one word of the list.
    if len(low) >= 5 and low[0] == "e" and low[1:] in vocab:
        return True
    return _splits(low, vocab)


# Inside a token that is not all words of the list, a word of the list is
# kept only when it is at least this long. An id of thirteen letters and
# digits kept some short word ("AT", "NO", "PDF") in one case in twenty
# when every word was kept, and in one in five hundred with this.
_ALONE = 4


def _token(tok: str, vocab: frozenset) -> str:
    """One run of letters and digits. Kept whole when it is a word of the
    list, or its letters are all words of the list (statementDate,
    page2, acct123Summary), with every digit a 9 either way. Otherwise each
    letter part is shaped unless it is a word of the list long enough not
    to turn up inside an id by chance."""
    if tok.lower() in vocab:
        return tok
    pieces = []
    for run in re.findall(r"[^\W\d_]+|\d+", tok):
        if run[0].isdigit():
            pieces.append((run, None))
        elif _known(run, vocab):
            pieces.append((run, True))
        else:
            pieces.extend((p, _known(p, vocab)) for p in _camel(run))
    whole = all(known for _, known in pieces if known is not None)
    out = []
    for piece, known in pieces:
        if known is None:
            out.append("9" * len(piece))
        elif known and (whole or len(piece) >= _ALONE):
            out.append(piece)
        else:
            out.append("a" * len(piece))
    return "".join(out)


def _greeted(text: str) -> list:
    """Where a greeting's name stands, "Welcome back, Bill", which leaves as
    its shape whatever the list says about its words. The owner's own name
    is taken off the list instead (_vocabulary), which covers it wherever
    it stands, alone, joined to another word or inside an address."""
    from .redact import _GREETING_RE
    return [(m.end(1), m.end()) for m in _GREETING_RE.finditer(text)]


def _shape(text: str, words: frozenset, collapse: bool, private: tuple) -> str:
    # One letter and nothing else is kept. It says nothing about anyone,
    # and it is what an element's tag (p, b, i) and a step's own key are.
    # Inside a longer string a letter alone is an initial, and is shaped.
    if len(text.strip()) == 1 and text.strip().isalpha():
        return text.strip() if collapse else text
    text = _EMAIL_RE.sub(EMAIL, text)
    text = _MONEY_RE.sub(AMOUNT, text)
    vocab = _vocabulary(words, private)
    greeted = _greeted(text)
    out = []
    before = ""        # the token before this one, as the page wrote it
    word_kept = False  # whether the last run of letters and digits was kept
    for m in _RUN.finditer(text):
        tok = m.group()
        if tok[0].isspace():
            out.append(" " if collapse else " " * len(tok))
        elif tok[0].isalnum():
            if any(a < m.end() and m.start() < b for a, b in greeted):
                out.append("".join("9" if c.isdigit() else "a" for c in tok))
                word_kept = False
                before = tok
                continue
            if (before in _APOSTROPHES and tok.lower() in _AFTER_APOSTROPHE
                    and m.start() >= 2 and text[m.start() - 2].isalpha()):
                shaped = tok
            elif (len(tok) == 1 and tok.isalpha() and before == "_" and word_kept
                  and not text[m.end():m.end() + 1].isalnum()):
                # The unit that ends a key of ours, wait_s or after_click_s,
                # after a word that was kept. After a name it is shaped like
                # the name, so Smith_J stays aaaaa_a.
                shaped = tok
            else:
                shaped = _token(tok, vocab)
            out.append(shaped)
            word_kept = shaped == tok and not set(tok) <= {"9"}
        else:
            out.append(tok if tok in _MARKS else "?")
        before = tok
    joined = "".join(out)
    return joined.strip() if collapse else joined


@functools.lru_cache(maxsize=65536)
def _shape_cached(text: str, words: frozenset, collapse: bool, private: tuple) -> str:
    return _shape(text, words, collapse, private)


def shape(text, words: Iterable = (), *, collapse: bool = True) -> str:
    """One string, every word on the list as it was and every other as its
    shape. Spaces are run together unless collapse is False."""
    text = "" if text is None else str(text)
    if not text:
        return ""
    return _shape_cached(text, frozenset(words), collapse, _private())


def shape_name(name, words: Iterable = ()) -> str:
    """A downloaded file's name. Its kind stays, in lowercase, when it is a
    kind on the list, and the rest is shaped letter for letter, so its
    length stays too."""
    name = "" if name is None else str(name)
    stem, dot, ext = name.rpartition(".")
    if dot and stem and ext.lower() in EXTENSIONS:
        tail = "." + ext.lower()
    else:
        stem, tail = name, ""
    body = shape(stem, words, collapse=False)
    if len(body) + len(tail) > 255:
        body = body[:252 - len(tail)] + "..."
    return body + tail


def _segments(path: str, words) -> str:
    from urllib.parse import unquote
    return "/".join(shape(unquote(p), words, collapse=False) for p in path.split("/"))


def shape_query(url, words: Iterable = ()) -> str:
    """A URL's parameters, each name and each value shaped, so
    docType=STATEMENT stays and an id becomes its shape."""
    from urllib.parse import parse_qsl, urlsplit
    try:
        pairs = parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=True)
    except ValueError:
        return ""
    return "&".join("%s=%s" % (shape(k, words)[:40], shape(v, words)[:40])
                    for k, v in pairs[:20])


_SCHEMES = frozenset(("http", "https", "blob", "data", "about", "file", "chrome",
                      "edge", "javascript"))


def shape_url(url, words: Iterable = (), *, query: bool = True) -> str:
    """An address, every part shaped. Never the user and password some
    addresses carry before the host, and the query only when asked."""
    from urllib.parse import urlsplit
    url = "" if url is None else str(url)
    words = frozenset(words)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return shape(url, words)
    out = ""
    if parts.scheme:
        scheme = parts.scheme.lower()
        out += (scheme if scheme in _SCHEMES else shape(scheme, words)) + ":"
    if parts.netloc:
        host = parts.hostname or ""
        out += "//" + ".".join(shape(label, words) for label in host.split("."))
        if port:
            out += ":" + "9" * len(str(port))
    out += _segments(parts.path, words)
    if query and parts.query:
        out += "?" + shape_query(url, words)
    if parts.fragment:
        out += "#" + _segments(parts.fragment, words)
    return out


# ---------------------------------------------------------------------------
# A whole file
# ---------------------------------------------------------------------------

_MAX_COUNT = 100000
# Deeper and longer than any file of ours. A recording's page shape nests
# two levels for every element between the body and the control, up to
# eighty-three elements, and a limit of fourteen cut every real page's
# shape short without a word.
_MAX_DEPTH = 200
_MAX_ITEMS = 1000
_MAX_TEXT = 500


def shape_tree(value, words: Iterable = (), depth: int = 0):
    """Everything an app put in a file, rebuilt from what may leave.

    A string is shaped, a key too. A Fixed string stays as it is. A whole
    number is a count, between nought and a hundred thousand. Any other
    number is dropped, since an amount is one, and a yes or no stays. A
    structure deeper or longer than any of ours is cut, and anything else
    is shaped from its text. Nothing an app hands this can come out as it
    went in unless it is on the list."""
    words = frozenset(words)
    if depth > _MAX_DEPTH:
        return "..."
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Fixed):
        # Still marked, so a file built from this and gone over again on
        # its way to the disk keeps it.
        return value
    if isinstance(value, int):
        return max(0, min(value, _MAX_COUNT))
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return max(0, min(int(value), _MAX_COUNT)) if value.is_integer() else None
    if isinstance(value, str):
        return shape(value, words)[:_MAX_TEXT]
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:_MAX_ITEMS]:
            key = k if isinstance(k, Fixed) else shape(str(k), words)[:80]
            while key in out:
                key += "+"
            out[key] = shape_tree(v, words, depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [shape_tree(v, words, depth + 1) for v in list(items)[:_MAX_ITEMS]]
    import dataclasses
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return shape_tree(dataclasses.asdict(value), words, depth + 1)
    return shape(str(value), words)[:_MAX_TEXT]


def write_shaped(path, value, words: Iterable = ()) -> None:
    """The one way a file a tester may post is written. Whatever the app
    gathered goes through shape_tree on the way to the disk."""
    from .storage import atomic_write_text
    atomic_write_text(path, json.dumps(shape_tree(value, words), indent=2))


# ---------------------------------------------------------------------------
# Reading a shape back
# ---------------------------------------------------------------------------

def is_shape(token: str) -> bool:
    """Whether a run of letters or digits in a shaped string stands for
    something that was not on the list, a run of 9, or a run of a two
    letters long or more. A lone a is read as the word, since "Pay a
    bill" is far more common on a page than an initial standing alone."""
    return bool(token) and (set(token) == {"9"} or
                            (len(token) >= 2 and set(token) == {"a"}
                             and token.lower() not in KNOWN))
