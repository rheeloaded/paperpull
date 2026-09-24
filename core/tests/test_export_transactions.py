"""tools/export_transactions.py. Transactions read out of statement text by
shape, checked against the statement's own printed balances. Every fixture
here is made up. The layouts are the ones real statements use, a running
balance column with debit and credit columns, a signed-amount card
statement with its summary printed up front, and a two-account statement
with a balance pair per account."""
import csv
import importlib.util
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "export_transactions.py"
spec = importlib.util.spec_from_file_location("export_transactions", TOOL)
xt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xt)

BANK = """Statement Period: 06/16/2026to 07/15/2026
Beginning Balance $5,759.48
3 Deposits/Credits $2,192.25
4 Withdrawals/Debits $643.78
Ending Balance $7,307.95
Date Description Debits Credits Balance
06/16 Beginning Balance 0 0 $5,759.48
06/16 RECURRING DEB CARD PURCH 12345 $74.99 0 $5,684.49
06/18 ACH DEP PAYROLL 0 $2,153.25 $7,837.74
06/22 POS DEBIT GROCER $330.19 0 $7,507.55
06/23 DEPOSIT@MOBILE 0 $39.00 $7,546.55
07/08 DEBIT PRENOTIFICATION $0.00 0 $7,546.55
07/12 EXTERNAL BILL PAYMENT $238.60 0 $7,307.95
07/15 Ending Balance - - $7,307.95
Average Daily Balance $6,900.00
""".splitlines()

CARD = """Closing Date 07/14/26
New Balance $4,176.59
Late Payment Warning: Previous Balance $0.00
New Balance = $0.00
Previous Balance $2,008.75
Payments/Credits -$6,053.77
New Charges +$8,221.61
New Balance $4,176.59
Payments Amount
06/30/26* ELECTRONIC PAYMENT RECEIVED-THANK -$2,008.75
07/10/26* ELECTRONIC PAYMENT RECEIVED-THANK -$4,000.00
Credits Amount
06/18/26 PRINCESS ROYALE OCEANFRONT 12345 -$45.02
New Charges Amount
06/12/26 PAYPAL * KINGSDOMINI OH $244.99
06/13/26 GRAND HYATT NASSAU 1,981.45 $1,981.45
06/14/26 AplPay TMOBILE WEB UPGRADE WA $266.00
12/28/25 LATE POSTING FROM LAST YEAR $5,729.17
Total New Charges $8,221.61
""".splitlines()

TWO_ACCOUNTS = """Statement Period
05/25/26 - 06/24/26
Date Transact ion Detai l Amount($) Balance($)
05-25 Beginning Balance 1,489.35
05-26 Transfer From Shar es 400.00 1,889.35
05-26 ACH Paid To Somebody 1,689.00 - 200.35
05-26 Transfer To Shares 200.00- 0.35
05-29 Dividend 0.01 0.36
06-24 Ending Balance 0.36
06-01 A CH 55.32
Date Transact ion Detai l Amount($) Balance($)
05-25 Beginning Balance 229.27
05-26 Transfer From Chec king 200.00 429.27
05-26 Transfer To Checking 400.00 - 29.27
05-29 Dividend 0.04 29.31
06-24 Ending B alance 29.31
""".splitlines()


def test_amount_tokens_in_every_shape_a_statement_prints():
    f = xt.parse_amount_token
    assert f("$1,234.56") == 1234.56 and f("1,234.56") == 1234.56
    assert f("-$5.00") == -5.0 and f("$-5.00") == -5.0 and f("5.00-") == -5.0
    assert f("(5.00)") == -5.0 and f("5.00CR") == -5.0 and f("-$1,981.45⧫") == -1981.45
    assert f("0") is None and f("12345") is None and f("06/16") is None and f("1.5317") is None


def test_trailing_amounts_come_off_the_right_and_a_lone_minus_or_cr_binds():
    desc, amts, raw = xt.split_trailing_amounts("ACH Paid To Somebody 1,689.00 - 200.35")
    assert desc == "ACH Paid To Somebody" and amts == [-1689.0, 200.35]
    desc, amts, raw = xt.split_trailing_amounts("RECURRING DEB CARD PURCH 12345 $74.99 0 $5,684.49")
    assert desc == "RECURRING DEB CARD PURCH 12345" and amts == [74.99, 0.0, 5684.49]
    desc, amts, raw = xt.split_trailing_amounts("Interest 12.34 CR")
    assert amts == [-12.34]


def test_dates_take_the_statement_year_and_roll_back_across_new_year():
    assert xt.parse_date("06/16", 2026, (2026, 7)) == "2026-06-16"
    assert xt.parse_date("12/28", 2026, (2026, 1)) == "2025-12-28"
    assert xt.parse_date("06/30/26") == "2026-06-30"
    assert xt.parse_date("05-26", 2026, (2026, 6)) == "2026-05-26"
    assert xt.parse_date("Jan 5, 2026") == "2026-01-05" and xt.parse_date("5 Jan 2026") == "2026-01-05"
    assert xt.parse_date("06/16") is None                 # no year to borrow


def test_a_running_balance_column_gives_every_sign_and_reconciles_by_construction():
    s = xt.parse_statement(BANK)
    assert s["status"] == "reconciled, balance column"
    assert (s["period_start"], s["period_end"]) == ("2026-06-16", "2026-07-15")
    assert (s["beginning"], s["ending"]) == (5759.48, 7307.95)
    amounts = [(t["date"], t["amount"], t["balance"]) for t in s["transactions"]]
    assert amounts == [("2026-06-16", -74.99, 5684.49), ("2026-06-18", 2153.25, 7837.74),
                       ("2026-06-22", -330.19, 7507.55), ("2026-06-23", 39.0, 7546.55),
                       ("2026-07-08", 0.0, 7546.55), ("2026-07-12", -238.6, 7307.95)]
    assert s["sum"] == round(7307.95 - 5759.48, 2)
    names = [t["description"] for t in s["transactions"]]
    assert "Beginning Balance" not in names and "Ending Balance" not in names


def test_a_card_statement_reconciles_on_signed_amounts_against_the_right_balance_pair():
    s = xt.parse_statement(CARD)
    assert s["status"] == "reconciled, signed amounts"
    assert (s["beginning"], s["ending"]) == (2008.75, 4176.59)      # not the $0.00 pair printed first
    by = {t["description"]: t for t in s["transactions"]}
    assert by["GRAND HYATT NASSAU"]["amount"] == 1981.45              # the signed last amount, not the first
    payments = sorted(t["amount"] for t in s["transactions"] if t["description"].startswith("ELECTRONIC PAYMENT"))
    assert payments == [-4000.0, -2008.75]
    assert by["LATE POSTING FROM LAST YEAR"]["date"] == "2025-12-28"   # rolled back across new year
    assert all(t["balance"] is None for t in s["transactions"])


def test_two_accounts_on_one_statement_reconcile_separately_and_a_stray_line_is_kept():
    s = xt.parse_statement(TWO_ACCOUNTS)
    assert s["status"] == "reconciled, 2 sections, 1 line(s) outside the balance brackets"
    assert [sec["status"] for sec in s["sections"][:2]] == ["reconciled, balance column"] * 2
    assert (s["beginning"], s["ending"]) == (1489.35, 29.31)
    stray = [t for t in s["transactions"] if t["description"] == "A CH"]
    assert len(stray) == 1 and stray[0]["section"] == 3
    checking = [t["amount"] for t in s["transactions"] if t["section"] == 1]
    assert checking == [400.0, -1689.0, -200.0, 0.01]
    assert sum(t["amount"] for t in s["transactions"] if t["section"] == 2) == pytest.approx(29.31 - 229.27)


def test_a_statement_that_does_not_add_up_says_by_how_much():
    lines = [l.replace("$7,307.95", "$7,300.00") for l in BANK]
    s = xt.parse_statement(lines)
    assert s["status"].startswith("not reconciled, off by")
    assert len(s["transactions"]) == 6                      # still exported


def test_no_transactions_is_fine_when_the_balances_agree():
    s = xt.parse_statement(["Statement Period: 04/01/2026 to 06/30/2026", "Beginning Balance $7.68",
                            "Ending Balance $7.68", "06/30 Ending Balance -- -- $7.68"])
    assert s["status"] == "reconciled, no transactions" and s["transactions"] == []
    s = xt.parse_statement(["Some letter with no money in it", "Dated 01/02/2026"])
    assert s["status"] == "no balances printed"


def test_a_brokerage_trade_line_takes_the_amount_not_the_quantity():
    t = xt.transaction_line("06/29/2026 Total Stock Market Portfolio Buy 2.2055 $38.54 $85.00")
    assert xt._one_amount(t["amounts"], t["tokens"]) == 85.0


def test_only_statement_archives_with_pdfs_on_disk_are_offered(tmp_path):
    (tmp_path / "A Bank").mkdir()
    pdf = tmp_path / "A Bank" / "s.pdf"; pdf.write_bytes(b"%PDF")
    with open(tmp_path / "A Bank" / "A Bank Document Index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Document Date", "PDF Full Path"]); w.writeheader()
        w.writerow({"Document Date": "2026-01-01", "PDF Full Path": str(pdf)})
        w.writerow({"Document Date": "2025-12-01", "PDF Full Path": str(tmp_path / "gone.pdf")})
    (tmp_path / "Gone Bank").mkdir()
    with open(tmp_path / "Gone Bank" / "Gone Bank Document Index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Document Date", "PDF Full Path"]); w.writeheader()
        w.writerow({"Document Date": "2026-01-01", "PDF Full Path": str(tmp_path / "gone2.pdf")})
    assert xt.providers(tmp_path) == [{"provider": "A Bank", "folders": ["A Bank"], "pdfs": 1}]


def test_a_relative_pdf_path_is_taken_from_the_index_folder_not_the_working_directory(tmp_path, monkeypatch):
    """Every install the control panel creates has output_dir ".", so its
    index records a path relative to its own folder. The export tool runs
    from its own folder, where that path is nothing, and so the panel
    offered no providers to export and the sheet came out empty for them."""
    rel = str(Path("Statements") / "s.pdf")
    (tmp_path / "Citi Statements" / "Statements").mkdir(parents=True)
    (tmp_path / "Citi Statements" / "Statements" / "s.pdf").write_bytes(b"%PDF")
    with open(tmp_path / "Citi Statements" / "Citi Document Index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Document Date", "PDF Full Path"]); w.writeheader()
        w.writerow({"Document Date": "2026-01-01", "PDF Full Path": rel})
    monkeypatch.chdir(tmp_path.parent)
    assert xt.providers(tmp_path) == [{"provider": "Citi", "folders": ["Citi Statements"], "pdfs": 1}]
    index = tmp_path / "Citi Statements" / "Citi Document Index.csv"
    assert xt.pdf_path(index, {"PDF Full Path": rel}).is_file()
    assert xt.pdf_path(index, {"PDF Full Path": str(tmp_path / "abs.pdf")}) == tmp_path / "abs.pdf"


def test_the_export_caches_each_reading_and_writes_the_sheets(tmp_path, monkeypatch):
    pytest.importorskip("pdfplumber")
    (tmp_path / "A Bank").mkdir()
    pdf = tmp_path / "A Bank" / "2026-07-15 A Bank Statement.pdf"; pdf.write_bytes(b"%PDF")
    with open(tmp_path / "A Bank" / "A Bank Document Index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Account Holder", "Document Date", "Document Title", "PDF Full Path"])
        w.writeheader()
        w.writerow({"Account Holder": "", "Document Date": "2026-07-15", "Document Title": "Checking 1234",
                    "PDF Full Path": str(pdf)})
    calls = []
    monkeypatch.setattr(xt, "pdf_lines", lambda p: (calls.append(p), list(BANK))[1])
    r = xt.export(tmp_path, as_csv=True, log=lambda *_: None)
    assert r["transactions"] == 6 and r["statements"] == 1 and r["reconciled"] == 1 and r["read"] == 1
    with open(r["path"], encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["Date"] == "2026-07-12" and rows[0]["Amount"] == "-238.6" and rows[0]["Reconciled"] == "yes"
    assert rows[0]["Account"] == "Checking 1234"
    r2 = xt.export(tmp_path, as_csv=True, log=lambda *_: None)
    assert r2["read"] == 0 and r2["cached"] == 1 and len(calls) == 1     # second build reads nothing
    assert (tmp_path / xt.CACHE_NAME).is_file()


# -- #29, the closing month dated a year early --------------------------------

CHASE_CARD = """Opening/Closing Date 07/27/26 - 08/26/26
Previous Balance $1,000.00
Payments/Credits -$1,000.00
New Charges +$300.00
New Balance $300.00
PAYMENTS AND OTHER CREDITS
08/02 Payment Thank You - Web -$1,000.00
PURCHASE
07/28 GROCER 12345 $100.00
08/05 PHARMACY $80.00
08/20 FUEL STATION $120.00
""".splitlines()


def test_the_closing_month_keeps_the_statement_year():
    """A Chase card statement prints "Opening/Closing Date 07/27/26 -
    08/26/26". The period fallback matched "Closing Date" and took the
    first date after it, the OPENING date, so every August line was
    treated as later than the period end and dated 2025 (#29)."""
    s = xt.parse_statement(CHASE_CARD)
    assert (s["period_start"], s["period_end"]) == ("2026-07-27", "2026-08-26")
    assert sorted(t["date"] for t in s["transactions"]) == \
        ["2026-07-28", "2026-08-02", "2026-08-05", "2026-08-20"]
    assert s["status"].startswith("reconciled")


def test_the_closing_fallback_takes_the_latest_date_on_the_line():
    lines = ["Closing Date 07/27/26 08/26/26", "Previous Balance $10.00", "New Balance $10.00"]
    assert xt.find_period(lines) == (None, "2026-08-26")


def test_the_index_date_drives_the_year_and_a_disagreement_is_said():
    """The app that downloaded the statement recorded its date in the index.
    That date wins over whatever the text parse found, and when the two are
    far apart the status says so instead of trusting the parse."""
    lines = [l for l in CHASE_CARD if not l.startswith("Opening/Closing")]
    lines.insert(0, "Closing Date 08/26/26")
    s = xt.parse_statement(lines, doc_date="2026-08-26")
    assert sorted(t["date"] for t in s["transactions"])[-1] == "2026-08-20"
    assert "disagrees" not in s["status"]
    wrong = [l for l in CHASE_CARD if not l.startswith("Opening/Closing")]
    wrong.insert(0, "Closing Date 01/15/25")
    s = xt.parse_statement(wrong, doc_date="2026-08-26")
    assert [t["date"] for t in s["transactions"] if t["date"].startswith("2026-08")], s["transactions"]
    assert "disagrees with the index date 2026-08-26" in s["status"]
    assert s["period_end"] == "2025-01-15"        # what the text said is still reported


def test_a_fixed_parse_is_not_hidden_by_the_cache():
    """The cache is keyed on path, size and mtime, so a wrong-year parse
    would survive the fix unless the cache version moves with it."""
    assert xt.CACHE_VERSION >= 3


# -- #32, a split decimal and an empty bracket ---------------------------------

def test_a_decimal_split_across_a_space_still_reads_as_one_amount():
    """pdfplumber printed "$1,719.3 3". The amount did not parse, so the
    next amount in the window, the NEW balance, was taken as the beginning
    balance, and both ends of the statement read 466.93."""
    assert xt.balance_line("Previous Balance $1,719.3 3 New Balance $466.93 Go Paperless") == ("beginning", 1719.33)
    assert xt.balance_line("New Balance $466.9 3") == ("ending", 466.93)
    assert xt.balance_line("Ending Balance $5,759.48 3 items") == ("ending", 5759.48)   # a real trailing number is left alone


CARD_EMPTY_BRACKET = """Closing Date 09/15/26
Previous Balance $1,719.3 3 New Balance $466.93 Go Paperless
Payments -$1,500.00
New Balance $466.93
Transactions
09/02/26 NFO PAYMENT RECEIVED -$1,500.00
09/05/26 GROCER $120.00
09/09/26 FUEL $47.60
09/12/26 PHARMACY $80.00
""".splitlines()


def test_a_bracket_around_nothing_is_not_called_reconciled():
    """With the split decimal misread, the beginning and ending balances
    were both 466.93 a few lines apart, the bracket between them held no
    transactions, and it "reconciled" while all 70 real lines sat outside
    it. The word reconciled must never lead a status like that."""
    s = xt.parse_statement(CARD_EMPTY_BRACKET)
    assert (s["beginning"], s["ending"]) == (1719.33, 466.93)
    assert len(s["transactions"]) == 4
    assert not s["status"].startswith("reconciled, no transactions")
    assert s["status"] == "reconciled, signed amounts"
    # And the guard itself, on a statement whose only bracket is empty and
    # every transaction sits after it.
    lines = ["Closing Date 06/30/26", "Beginning Balance $100.00", "Ending Balance $100.00",
             "06/16 DEPOSIT $50.00", "06/18 DEBIT $50.00"]
    s = xt.parse_statement(lines)
    assert len(s["transactions"]) == 2
    assert s["status"] == "not reconciled, 2 transaction(s) outside the balance brackets"


# -- a card statement with a rewards box beside the list ---------------------

COSTCO = """Billing Period: 08/18/26-09/15/26
Previous balance $1,000.00
New balance $900.75
Payments -$500.00
08/20 PAYMENT THANK YOU -$500.00
08/21 FLEX PLAN 04 CREDIT ADJ 08/20/26 -$8,156.56 Earned This Period
08/21 FLEX PLAN 04 CREDIT ADJ 08/20/26 -$60.50 Year To Date : $1,209.58
08/22 08/22 COSTCO WHSE #0204 OAKTON VA $227.16 5% on gas at Costco ............ +$0.00
CORNER BAKERY OAKTON VA 2% on Costco and Costco.com
08/23 08/23 $14.10
08/24 08/24 $100.00 ANNUAL MEMBERSHIP FEE
08/25 08/25 FLEX PLAN 04 TRANSFERRED APR PURCH $8,156.56
08/25 08/25 FLEX PLAN 04 TRANSFERRED APR PURCH $60.50
08/26 08/26 NEW BALANCE *0019 ANNAPOLIS MD $27.26
08/27 08/27 NYT DIGITAL APR 2026 800-698-4637 NY $12.95
08/28 08/28 GROCER 1365 OAKTON VA $19.28
Purchase APR 24.99%
Total fees charged in 2026 $0.00
""".splitlines()


def test_a_rewards_box_glued_onto_a_transaction_line_is_cut_off():
    """The PDF reader lays the rewards box's words onto whichever
    transaction line sits level with it. One line lost its trailing
    amount, one handed over the box's number, and the flex plan credits
    that should have cancelled their transfers went missing, which is
    why 19 of 24 Costco statements did not add up."""
    got = xt.parse_statement(COSTCO, "2026-09-15")
    assert got["status"] == "reconciled, signed amounts"
    by_line = {t["line"]: t for t in got["transactions"]}
    assert by_line[5]["amount"] == -8156.56 and by_line[5]["description"] == "FLEX PLAN 04 CREDIT ADJ 08/20/26"
    assert by_line[6]["amount"] == -60.50, "the box's year-to-date number is not the transaction"
    assert by_line[7]["amount"] == 227.16 and by_line[7]["description"] == "COSTCO WHSE #0204 OAKTON VA"


def test_a_merchant_on_the_neighboring_line_and_an_amount_printed_first():
    got = xt.parse_statement(COSTCO, "2026-09-15")
    by_line = {t["line"]: t for t in got["transactions"]}
    assert by_line[9]["amount"] == 14.10 and by_line[9]["description"] == "CORNER BAKERY OAKTON VA"
    assert by_line[10]["amount"] == 100.00 and by_line[10]["description"] == "ANNUAL MEMBERSHIP FEE"


def test_the_month_apr_and_a_shoe_store_are_transactions_the_rate_line_is_not():
    got = xt.parse_statement(COSTCO, "2026-09-15")
    descs = {t["description"] for t in got["transactions"]}
    assert "FLEX PLAN 04 TRANSFERRED APR PURCH" in descs
    assert "NYT DIGITAL APR 2026 800-698-4637 NY" in descs
    assert "NEW BALANCE *0019 ANNAPOLIS MD" in descs
    assert not any("24.99" in d for d in descs)
    assert got["ending"] == 900.75, "the shoe store is not the ending balance"


def test_a_bare_number_after_the_amount_is_a_column_not_a_bleed():
    """A retirement statement prints an amount, then units and a share
    price. That is a column this tool does not read, not a box beside the
    line, and reading the amount off it would file a contribution with
    the wrong sign. The line stays unread, as before."""
    assert xt.transaction_line("10/06/2021 Contribution $95.56 $0.00 $95.56 65.6583 1.4554") is None
    assert xt.transaction_line("06/16 RECURRING DEB CARD PURCH 12345 $74.99 0 $5,684.49")["amounts"] == [74.99, 0.0, 5684.49]


def test_an_address_line_is_never_taken_as_a_description():
    lines = ["Adjustment VA Home 93A", "10/23/25 278.28", "4100 ELM ST", "10/28/25 -76.89", "4100 ELM ST"]
    got = xt.read_transactions(lines, 2025, (2025, 11))
    assert [t["description"] for t in got] == ["Adjustment VA Home 93A"]


def test_the_box_is_never_a_description_and_a_neighbor_loses_its_bleed():
    lines = ["BLUE HERON MARKET SPRINGFIELD",
             "09/24 09/24 $53.60 purchases ........................................... +$19.65",
             "VA",
             "CORNER BAKERY OAKTON 4% cash back rewards on eligible gas and",
             "12/17 12/17 $26.50",
             "GREEN LEAF GROCER OAKTON",
             "04/18 04/18 $24.00 1% on all other purchases +$41.56"]
    got = xt.read_transactions(lines, 2025, (2025, 12))
    assert [(t["amounts"][-1], t["description"]) for t in got] == [
        (53.60, "BLUE HERON MARKET SPRINGFIELD"),
        (26.50, "CORNER BAKERY OAKTON"),
        (24.00, "GREEN LEAF GROCER OAKTON"),
    ]
    assert xt.transaction_line("08/24 08/24 $100.00 ANNUAL MEMBERSHIP FEE")["description"] == "ANNUAL MEMBERSHIP FEE"


# -- dates, which reconciliation has nothing to say about ----------------------

def test_a_statement_whose_dates_are_a_year_out_does_not_read_as_reconciled():
    """Issue #29. Five Chase statements came out with every transaction
    dated a year early, because find_period returned the opening date as
    period_end, and all five reported "reconciled, signed amounts".

    The cause was fixed then. Nothing was added that would notice the next
    one, and the report said exactly why: reconciliation only weighs
    amounts against balances, so the dates can be anything at all."""
    txns = [{"date": "2025-08-03"}, {"date": "2025-08-14"}, {"date": "2025-08-22"}]
    astray = xt.dates_outside_period(txns, "2026-07-27", "2026-08-26")
    assert len(astray) == 3


def test_transactions_inside_their_own_period_are_left_alone():
    txns = [{"date": "2026-07-28"}, {"date": "2026-08-10"}, {"date": "2026-08-26"}]
    assert xt.dates_outside_period(txns, "2026-07-27", "2026-08-26") == []


def test_a_posting_a_day_or_two_past_the_close_is_ordinary():
    """A card posts a purchase after the close and a statement carries the
    previous payment. A few days either side is not a defect, and a check
    that calls it one gets turned off."""
    txns = [{"date": "2026-07-25"}, {"date": "2026-08-29"}]
    assert xt.dates_outside_period(txns, "2026-07-27", "2026-08-26") == []


def test_one_stray_date_is_reported_without_condemning_the_statement():
    txns = [{"date": "2026-08-01"}, {"date": "2026-08-15"}, {"date": "2019-04-02"}]
    assert len(xt.dates_outside_period(txns, "2026-07-27", "2026-08-26")) == 1


def test_no_period_and_no_dates_are_not_an_error():
    """Plenty of statements print no period at all, and this must not turn
    that into a complaint."""
    assert xt.dates_outside_period([{"date": "2026-08-01"}], None, None) == []
    assert xt.dates_outside_period([], "2026-07-27", "2026-08-26") == []
    assert xt.dates_outside_period([{"date": ""}], "2026-07-27", "2026-08-26") == []
    assert xt.dates_outside_period([{"date": "nonsense"}], "2026-07-27", "2026-08-26") == []
    assert xt.dates_outside_period([{"date": "2026-08-01"}], "bad", "worse") == []


def test_the_cache_version_moved_with_the_shape_of_a_parse():
    """The cache is keyed on path, size and mtime, so an old parse survives
    a change to the parser and hides it. #32 said so explicitly."""
    assert xt.CACHE_VERSION >= 5
