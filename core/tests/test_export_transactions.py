"""tools/export_transactions.py. Transactions read out of statement text by
shape, checked against the statement's own printed balances. Every fixture
here is made up. The layouts are the ones real statements use, a running
balance column with debit and credit columns, a signed-amount card
statement with its summary printed up front, and a two-account statement
with a balance pair per account."""
import csv
import json
import importlib.util
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "export_transactions.py"
spec = importlib.util.spec_from_file_location("export_transactions", TOOL)
xt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xt)

BANK = """Statement Period: 06/13/2026to 07/12/2026
Beginning Balance $4,812.37
3 Deposits/Credits $2,188.73
4 Withdrawals/Debits $557.25
Ending Balance $6,443.85
Date Description Debits Credits Balance
06/13 Beginning Balance 0 0 $4,812.37
06/13 RECURRING DEB CARD PURCH 40117 $58.21 0 $4,754.16
06/15 ACH DEP PAYROLL 0 $2,146.73 $6,900.89
06/19 POS DEBIT GROCER $187.44 0 $6,713.45
06/20 DEPOSIT@MOBILE 0 $42.00 $6,755.45
07/05 DEBIT PRENOTIFICATION $0.00 0 $6,755.45
07/09 EXTERNAL BILL PAYMENT $311.60 0 $6,443.85
07/12 Ending Balance - - $6,443.85
Average Daily Balance $5,618.00
""".splitlines()

CARD = """Closing Date 07/12/26
New Balance $3,314.00
Late Payment Warning: Previous Balance $0.00
New Balance = $0.00
Previous Balance $2,318.40
Payments/Credits -$6,257.01
New Charges +$7,252.61
New Balance $3,314.00
Payments Amount
06/28/26* ELECTRONIC PAYMENT RECEIVED-THANK -$2,318.40
07/08/26* ELECTRONIC PAYMENT RECEIVED-THANK -$3,900.00
Credits Amount
06/16/26 SEASIDE INN LAKEVIEW 10417 -$38.61
New Charges Amount
06/10/26 PAYPAL * EXAMPLEPARK OH $183.99
06/11/26 HARBOR HOTEL LAKEVIEW 1,642.45 $1,642.45
06/12/26 AplPay EXAMPLE MOBILE UPGRADE WA $320.00
12/26/25 LATE POSTING FROM LAST YEAR $5,106.17
Total New Charges $7,252.61
""".splitlines()

TWO_ACCOUNTS = """Statement Period
05/22/26 - 06/21/26
Date Transact ion Detai l Amount($) Balance($)
05-22 Beginning Balance 1,183.35
05-23 Transfer From Shar es 640.00 1,823.35
05-23 ACH Paid To Somebody 1,520.00 - 303.35
05-23 Transfer To Shares 303.00- 0.35
05-26 Dividend 0.01 0.36
06-21 Ending Balance 0.36
05-29 A CH 48.17
Date Transact ion Detai l Amount($) Balance($)
05-22 Beginning Balance 378.80
05-23 Transfer From Chec king 303.00 681.80
05-23 Transfer To Checking 640.00 - 41.80
05-26 Dividend 0.04 41.84
06-21 Ending B alance 41.84
""".splitlines()


def test_amount_tokens_in_every_shape_a_statement_prints():
    f = xt.parse_amount_token
    assert f("$1,234.56") == 1234.56 and f("1,234.56") == 1234.56
    assert f("-$5.00") == -5.0 and f("$-5.00") == -5.0 and f("5.00-") == -5.0
    assert f("(5.00)") == -5.0 and f("5.00CR") == -5.0 and f("-$1,642.45⧫") == -1642.45
    assert f("0") is None and f("12345") is None and f("06/16") is None and f("1.5317") is None


def test_trailing_amounts_come_off_the_right_and_a_lone_minus_or_cr_binds():
    desc, amts, raw = xt.split_trailing_amounts("ACH Paid To Somebody 1,520.00 - 303.35")
    assert desc == "ACH Paid To Somebody" and amts == [-1520.0, 303.35]
    desc, amts, raw = xt.split_trailing_amounts("RECURRING DEB CARD PURCH 40117 $58.21 0 $4,754.16")
    assert desc == "RECURRING DEB CARD PURCH 40117" and amts == [58.21, 0.0, 4754.16]
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
    assert (s["period_start"], s["period_end"]) == ("2026-06-13", "2026-07-12")
    assert (s["beginning"], s["ending"]) == (4812.37, 6443.85)
    amounts = [(t["date"], t["amount"], t["balance"]) for t in s["transactions"]]
    assert amounts == [("2026-06-13", -58.21, 4754.16), ("2026-06-15", 2146.73, 6900.89),
                       ("2026-06-19", -187.44, 6713.45), ("2026-06-20", 42.0, 6755.45),
                       ("2026-07-05", 0.0, 6755.45), ("2026-07-09", -311.6, 6443.85)]
    assert s["sum"] == round(6443.85 - 4812.37, 2)
    names = [t["description"] for t in s["transactions"]]
    assert "Beginning Balance" not in names and "Ending Balance" not in names


def test_a_card_statement_reconciles_on_signed_amounts_against_the_right_balance_pair():
    s = xt.parse_statement(CARD)
    assert s["status"] == "reconciled, signed amounts"
    assert (s["beginning"], s["ending"]) == (2318.4, 3314.0)      # not the $0.00 pair printed first
    by = {t["description"]: t for t in s["transactions"]}
    assert by["HARBOR HOTEL LAKEVIEW"]["amount"] == 1642.45              # the signed last amount, not the first
    payments = sorted(t["amount"] for t in s["transactions"] if t["description"].startswith("ELECTRONIC PAYMENT"))
    assert payments == [-3900.0, -2318.4]
    assert by["LATE POSTING FROM LAST YEAR"]["date"] == "2025-12-26"   # rolled back across new year
    assert all(t["balance"] is None for t in s["transactions"])


def test_two_accounts_on_one_statement_reconcile_separately_and_a_stray_line_is_kept():
    s = xt.parse_statement(TWO_ACCOUNTS)
    assert s["status"] == "reconciled, 2 sections, 1 line(s) outside the balance brackets"
    assert [sec["status"] for sec in s["sections"][:2]] == ["reconciled, balance column"] * 2
    assert (s["beginning"], s["ending"]) == (1183.35, 41.84)
    stray = [t for t in s["transactions"] if t["description"] == "A CH"]
    assert len(stray) == 1 and stray[0]["section"] == 3
    checking = [t["amount"] for t in s["transactions"] if t["section"] == 1]
    assert checking == [640.0, -1520.0, -303.0, 0.01]
    assert sum(t["amount"] for t in s["transactions"] if t["section"] == 2) == pytest.approx(41.84 - 378.80)


def test_a_statement_that_does_not_add_up_says_by_how_much():
    lines = [l.replace("$6,443.85", "$6,443.00") for l in BANK]
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
    t = xt.transaction_line("06/26/2026 Total Stock Market Portfolio Buy 2.4417 $34.81 $85.00")
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
    assert rows[0]["Date"] == "2026-07-09" and rows[0]["Amount"] == "-311.6" and rows[0]["Reconciled"] == "yes"
    assert rows[0]["Account"] == "Checking 1234"
    r2 = xt.export(tmp_path, as_csv=True, log=lambda *_: None)
    assert r2["read"] == 0 and r2["cached"] == 1 and len(calls) == 1     # second build reads nothing
    assert (tmp_path / xt.CACHE_NAME).is_file()


def test_two_statements_of_one_name_in_a_patterns_folders_are_told_apart(tmp_path, monkeypatch):
    """A naming pattern's folders can hold two files of one name, one for
    each account (#101). Each is read by the full path its index row gives,
    and the sheet names each with the folders it is in inside the folder of
    its kind, so the two are told apart. A file in the folder of its kind is
    named by its name alone, as it always was."""
    pytest.importorskip("pdfplumber")
    bank = tmp_path / "A Bank"
    name = "2026-07-15 A Bank Statement.pdf"
    files = [bank / "Statements" / "Checking 1111" / name,
             bank / "Statements" / "Savings 2222" / name,
             bank / "Statements" / "2026-06-15 A Bank Statement.pdf"]
    for p in files:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF " + str(p).encode())
    with open(bank / "A Bank Document Index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Document Date", "Document Title", "PDF Full Path"])
        w.writeheader()
        for p in files:
            w.writerow({"Document Date": "2026-07-15", "Document Title": "Statement",
                        "PDF Full Path": str(p)})
    read = []
    monkeypatch.setattr(xt, "pdf_lines", lambda p: (read.append(p), list(BANK))[1])
    r = xt.export(tmp_path, as_csv=True, log=lambda *_: None)
    assert r["statements"] == 3 and sorted(read) == sorted(files)
    with open(r["path"], encoding="utf-8-sig", newline="") as fh:
        named = {row["Statement"] for row in csv.DictReader(fh)}
    assert named == {"Checking 1111/" + name, "Savings 2222/" + name,
                     "2026-06-15 A Bank Statement.pdf"}
    index = bank / "A Bank Document Index.csv"
    assert xt.statement_name(index, tmp_path / "elsewhere" / "x.pdf") == "x.pdf"


def test_a_statement_in_the_documents_folder_is_named_with_its_folders(tmp_path):
    """Moved to the account's documents folder (#102), which is written down
    beside the index, a statement is named from inside that folder."""
    bank, docs = tmp_path / "A Bank", tmp_path / "Watched"
    bank.mkdir()
    index = bank / "A Bank Document Index.csv"
    pdf = docs / "Statements" / "Checking 1111" / "2026-07-15 Statement.pdf"
    assert xt.statement_name(index, pdf) == "2026-07-15 Statement.pdf"
    (bank / "documents-folders.json").write_text(json.dumps([str(docs)]), encoding="utf-8")
    assert xt.statement_name(index, pdf) == "Checking 1111/2026-07-15 Statement.pdf"
    assert xt.statement_name(index, docs / "Statements" / "flat.pdf") == "flat.pdf"
    nested = bank / "Documents" / "Statements" / "Savings 2222" / "x.pdf"
    (bank / "documents-folders.json").write_text(json.dumps([str(bank / "Documents")]),
                                                 encoding="utf-8")
    assert xt.statement_name(index, nested) == "Savings 2222/x.pdf"


def test_with_no_statement_on_disk_nothing_is_written(tmp_path):
    """Every build that found no statement wrote an empty workbook and then
    said there was nothing to export, so the one a person had built before
    was replaced by an empty one."""
    pytest.importorskip("pdfplumber")
    (tmp_path / "Gone Bank").mkdir()
    with open(tmp_path / "Gone Bank" / "Gone Bank Document Index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Document Date", "PDF Full Path"]); w.writeheader()
        w.writerow({"Document Date": "2026-01-01", "PDF Full Path": str(tmp_path / "gone.pdf")})
    last = tmp_path / "All Transactions.csv"
    last.write_text("the workbook built last time\n", encoding="utf-8")

    r = xt.export(tmp_path, as_csv=True, log=lambda *_: None)
    assert r["statements"] == 0 and r["missing"] == 1 and r["path"] is None
    assert xt.main(["--root", str(tmp_path), "--csv"]) == 1
    assert xt.main(["--root", str(tmp_path)]) == 1
    assert last.read_text(encoding="utf-8") == "the workbook built last time\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["All Transactions.csv", "Gone Bank"]


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
    assert xt.balance_line("Ending Balance $5,204.18 3 items") == ("ending", 5204.18)   # a real trailing number is left alone


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

COSTCO = """Billing Period: 08/15/26-09/12/26
Previous balance $1,380.00
New balance $763.30
Payments -$960.00
08/17 PAYMENT THANK YOU -$960.00
08/18 FLEX PLAN 04 CREDIT ADJ 08/17/26 -$7,204.56 Earned This Period
08/18 FLEX PLAN 04 CREDIT ADJ 08/17/26 -$52.40 Year To Date : $1,106.58
08/19 08/19 COSTCO WHSE #0684 LAKEVIEW VA $142.16 5% on gas at Costco ............ +$0.00
CORNER CAFE LAKEVIEW VA 2% on Costco and Costco.com
08/20 08/20 $11.80
08/21 08/21 $120.00 ANNUAL MEMBERSHIP FEE
08/22 08/22 FLEX PLAN 04 TRANSFERRED APR PURCH $7,204.56
08/22 08/22 FLEX PLAN 04 TRANSFERRED APR PURCH $52.40
08/23 08/23 NEW BALANCE *4410 HARBORVIEW MD $31.48
08/24 08/24 NYT DIGITAL APR 2026 800-698-4637 NY $14.25
08/25 08/25 GROCER 6120 LAKEVIEW VA $23.61
Purchase APR 24.99%
Total fees charged in 2026 $0.00
""".splitlines()


def test_a_rewards_box_glued_onto_a_transaction_line_is_cut_off():
    """The PDF reader lays the rewards box's words onto whichever
    transaction line sits level with it. One line lost its trailing
    amount, one handed over the box's number, and the flex plan credits
    that should have cancelled their transfers went missing, which is
    why 19 of 24 Costco statements did not add up."""
    got = xt.parse_statement(COSTCO, "2026-09-12")
    assert got["status"] == "reconciled, signed amounts"
    by_line = {t["line"]: t for t in got["transactions"]}
    assert by_line[5]["amount"] == -7204.56 and by_line[5]["description"] == "FLEX PLAN 04 CREDIT ADJ 08/17/26"
    assert by_line[6]["amount"] == -52.40, "the box's year-to-date number is not the transaction"
    assert by_line[7]["amount"] == 142.16 and by_line[7]["description"] == "COSTCO WHSE #0684 LAKEVIEW VA"


def test_a_merchant_on_the_neighboring_line_and_an_amount_printed_first():
    got = xt.parse_statement(COSTCO, "2026-09-12")
    by_line = {t["line"]: t for t in got["transactions"]}
    assert by_line[9]["amount"] == 11.80 and by_line[9]["description"] == "CORNER CAFE LAKEVIEW VA"
    assert by_line[10]["amount"] == 120.00 and by_line[10]["description"] == "ANNUAL MEMBERSHIP FEE"


def test_the_month_apr_and_a_shoe_store_are_transactions_the_rate_line_is_not():
    got = xt.parse_statement(COSTCO, "2026-09-12")
    descs = {t["description"] for t in got["transactions"]}
    assert "FLEX PLAN 04 TRANSFERRED APR PURCH" in descs
    assert "NYT DIGITAL APR 2026 800-698-4637 NY" in descs
    assert "NEW BALANCE *4410 HARBORVIEW MD" in descs
    assert not any("24.99" in d for d in descs)
    assert got["ending"] == 763.30, "the shoe store is not the ending balance"


def test_a_bare_number_after_the_amount_is_a_column_not_a_bleed():
    """A retirement statement prints an amount, then units and a share
    price. That is a column this tool does not read, not a box beside the
    line, and reading the amount off it would file a contribution with
    the wrong sign. The line stays unread, as before."""
    assert xt.transaction_line("10/03/2021 Contribution $88.14 $0.00 $17.83 48.2109 4.9431") is None
    assert xt.transaction_line("06/13 RECURRING DEB CARD PURCH 40117 $58.21 0 $4,754.16")["amounts"] == [58.21, 0.0, 4754.16]


def test_an_address_line_is_never_taken_as_a_description():
    lines = ["Adjustment VA Home 93A", "10/20/25 212.40", "4100 ELM ST", "10/25/25 -64.35", "4100 ELM ST"]
    got = xt.read_transactions(lines, 2025, (2025, 11))
    assert [t["description"] for t in got] == ["Adjustment VA Home 93A"]


def test_the_box_is_never_a_description_and_a_neighbor_loses_its_bleed():
    lines = ["EXAMPLE HERON MARKET LAKEVIEW",
             "09/21 09/21 $47.30 purchases ........................................... +$17.40",
             "VA",
             "CORNER CAFE LAKEVIEW 4% cash back rewards on eligible gas and",
             "12/14 12/14 $23.20",
             "GREEN LEAF GROCER LAKEVIEW",
             "04/15 04/15 $21.10 1% on all other purchases +$36.94"]
    got = xt.read_transactions(lines, 2025, (2025, 12))
    assert [(t["amounts"][-1], t["description"]) for t in got] == [
        (47.30, "EXAMPLE HERON MARKET LAKEVIEW"),
        (23.20, "CORNER CAFE LAKEVIEW"),
        (21.10, "GREEN LEAF GROCER LAKEVIEW"),
    ]
    assert xt.transaction_line("08/21 08/21 $120.00 ANNUAL MEMBERSHIP FEE")["description"] == "ANNUAL MEMBERSHIP FEE"


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


# A Navy Federal Visa statement as pdfplumber reads it (#32), every value
# made up. No amount is signed, a payment or refund is told from a purchase
# only by the PAYMENTS AND CREDITS heading above it, the heading comes back
# after the page break with a refund under it, the Submitted By column
# wraps the merchant's town onto a line of its own, and there is no running
# balance column.
NFCU_VISA = """Closing Date 09/15/26
Previous Balance $2,500.00
New Balance $46.77
TRANSACTIONS
PAYMENTS AND CREDITS
Trans Date Post Date Reference No. Description Submitted By Amount
08/16/26 08/16/26 70000000000000000000001 NFO PAYMENT RECEIVED xxxx xxxx xxxx 0000 $1,482.17
08/21/26 08/22/26 70000000000000000000002 EXAMPLE HARDWARE 000001* ANYTOWN xxxx xxxx xxxx 0000 $214.60
VA
08/30/26 08/30/26 70000000000000000000003 NFO PAYMENT RECEIVED xxxx xxxx xxxx 0000 $1,105.00
TRANSACTIONS
PAYMENTS AND CREDITS
Trans Date Post Date R eference No. Description Submitted By Amount
09/02/26 09/03/26 70000000000000000000004 EXAMPLE AI PLAN xxxx xxxx xxxx 0000 $19.99
SOMETOWN CA
TOTAL PAYMENTS AND CREDITS $2,821.76
TRANSACTIONS
PAT EXAMPLE xxxx xxxx xxxx 0000
Trans Date Post Date Reference No. Description Amount
08/14/26 08/15/26 20000000000000000000005 WAREHOUSE CLUB 00001 ANYTOWN VA $312.45
08/15/26 08/17/26 20000000000000000000006 EXAMPLE MART T-0001 ANYTOWN VA $56.08
""".splitlines()


def test_a_card_that_signs_nothing_reconciles_by_its_credits_heading():
    s = xt.parse_statement(NFCU_VISA)
    assert s["status"] == "reconciled, signs from the statement's headings"
    assert (s["beginning"], s["ending"]) == (2500.00, 46.77)
    assert [t["amount"] for t in s["transactions"]] == [
        -1482.17, -214.60, -1105.00, -19.99, 312.45, 56.08]
    # The wrapped town is not a transaction of its own.
    assert len(s["transactions"]) == 6


def test_the_credits_section_carries_over_the_page_break_and_ends_at_its_total():
    under = xt.credit_rows(NFCU_VISA)
    lines = {NFCU_VISA[i] for i in under}
    assert any("NFO PAYMENT" in line for line in lines)
    assert any("EXAMPLE AI PLAN" in line for line in lines)
    assert not any("WAREHOUSE CLUB" in line or "EXAMPLE MART" in line for line in lines)
    assert not any(line.startswith("TOTAL") for line in lines)


def test_headings_never_sign_a_statement_that_does_not_add_up_with_them():
    # The same rows with the balances off by a dollar stay not reconciled,
    # with the amounts as printed, rather than a guess.
    off = [line.replace("New Balance $46.77", "New Balance $47.77") for line in NFCU_VISA]
    s = xt.parse_statement(off)
    assert s["status"].startswith("not reconciled")
    assert all(t["amount"] > 0 for t in s["transactions"])
    # Without the heading there is nothing to sign by.
    bare = [line for line in NFCU_VISA if "PAYMENTS AND CREDITS" not in line or line.startswith("TOTAL")]
    assert xt.parse_statement(bare)["status"].startswith("not reconciled")


def test_a_statement_that_prints_signs_is_never_signed_by_its_headings():
    # CHASE_CARD prints PAYMENTS AND OTHER CREDITS with signed amounts, and
    # keeps reconciling on the signs as printed.
    s = xt.parse_statement(CHASE_CARD)
    assert s["status"].startswith("reconciled") and "headings" not in s["status"]


def test_the_cache_is_read_again_for_the_heading_signs():
    assert xt.CACHE_VERSION >= 6


def test_the_navy_federal_summary_box_reads_its_balances_and_signs_nothing():
    """The Visa's summary box as pdfplumber prints it (#32, values made up):
    both balances on one line with the box's words glued on, Payments and
    Other Credits printed signed, a split decimal, and, as on a September
    statement, no closing date line at all, so the index date is the
    anchor. The signed summary lines are not transactions and do not stop
    the heading signs."""
    box = ["Previous Balance $2,500.0 0 New Balance $46.77 Go Paperless",
           "Payments -$2,587.17 Minimum Pay ment Due $25.00 Access up to 24 months of",
           "Other Cred its -$234.59 Payment Due Date 10/07/2026",
           "New Balance $46.77"]
    body = [line for line in NFCU_VISA[3:]]
    s = xt.parse_statement(box + body, "2026-09-15")
    assert (s["beginning"], s["ending"]) == (2500.00, 46.77)
    assert s["status"] == "reconciled, signs from the statement's headings"
    assert len(s["transactions"]) == 6


def _line(text, top, x0=40.0):
    """A line as pdfplumber's extract_text_lines gives it, one char per
    letter, 5 points wide."""
    chars = [{"text": ch, "x0": x0 + 5 * i, "x1": x0 + 5 * i + 4.5, "top": top}
             for i, ch in enumerate(text)]
    return {"text": text, "top": top, "chars": chars}


def _scattered(text, top, x0=300.0):
    """The same line as pdfplumber scatters it when its characters sit at
    jittered heights, one line per character (#32)."""
    jitter = [0.0, 1.6, 0.4, 2.9, 1.1, 2.2, 0.7, 3.1]
    out = []
    for i, ch in enumerate(text):
        if ch == " ":
            continue
        c = {"text": ch, "x0": x0 + 5 * i, "x1": x0 + 5 * i + 4.5, "top": top + jitter[i % len(jitter)]}
        out.append({"text": ch, "top": c["top"], "chars": [c]})
    return out


def test_a_block_scattered_into_single_characters_is_rebuilt():
    """A Navy Federal Visa summary box came out of pdfplumber as some 200
    lines of one or two characters, and the Statement Closing Date line
    went with it, so the statement had no period (#32). The scattered
    characters are put back into lines by height, and every line read
    whole is kept as it was, in its place."""
    tls = ([_line("Credit Limit $9,000.00", 100.0)]
           + _scattered("Statement Closing Date 09/13/2026", 120.0)
           + _scattered("Payment Due Date 10/07/2026", 140.0)
           + [_line("Days in Billing Cycle 31", 160.0)])
    assert sum(1 for tl in tls if len(tl["text"]) <= 2) >= xt.SCATTER_MIN
    lines = xt.page_lines(tls)
    assert lines == ["Credit Limit $9,000.00", "Statement Closing Date 09/13/2026",
                     "Payment Due Date 10/07/2026", "Days in Billing Cycle 31"]
    assert xt.find_period(lines) == (None, "2026-09-13")


def _drifting(text, x0, tops, size=8.0):
    """A line as pdfplumber scatters it, one line per character, each
    character at its own height, tops(i) for the character at position i."""
    out = []
    for i, ch in enumerate(text):
        if ch == " ":
            continue
        c = {"text": ch, "x0": x0 + 5 * i, "x1": x0 + 5 * i + 4.5, "top": tops(i), "size": size}
        out.append({"text": ch, "top": c["top"], "chars": [c]})
    return out


DRIFT = [-3.0, 2.5, -1.0, 3.0, 0.5, -2.5, 1.5, -0.5]


def test_a_label_whose_characters_drift_more_than_4pt_stays_whole():
    """dertbv's September Visa on 0.51.0 (#32). The end of the label sat
    more than 4pt below its start, so bands of height read it as
    "Statement Clos 09/13/2026 about." with "i ng Date" on the next line,
    and the statement had no period. A character now continues the line it
    touches, so the label stays in front of its date. The word of the column
    beside it, at the same height, reads after the date, as pdfplumber would
    read a row."""
    label = "Statement Closing Date09/13/2026"
    start = label.index("ing")
    tls = ([_line("Credit Limit $9,000.00", 100.0)]
           + _drifting(label, 300.0,
                       lambda i: 125.0 + 0.2 * (i % 5) if start <= i < start + 8 else 120.0 + 0.3 * (i % 5))
           + _drifting("about.", 470.0, lambda i: 121.0)
           + _drifting("Payment Due Date 10/07/2026", 300.0, lambda i: 133.0 + DRIFT[i % 8] / 2)
           + [_line("Days in Billing Cycle 31", 160.0)])
    lines = xt.page_lines(tls)
    assert lines == ["Credit Limit $9,000.00", "Statement Closing Date09/13/2026 about.",
                     "Payment Due Date 10/07/2026", "Days in Billing Cycle 31"]
    assert xt.find_period(lines) == (None, "2026-09-13")
    # With nothing above it, the label's line is joined with the due date's.
    assert xt.find_period(lines[1:]) == (None, "2026-09-13")


@pytest.mark.parametrize("lines, closing", [
    (["Statement Closing Date09/13/2026 about.", "Payment Due Date 10/07/2026"], "2026-09-13"),
    (["Payment Due Date 10/07/2026", "Statement Closing Date09/13/2026 about."], "2026-09-13"),
    (["Minimum Payment Due 10/07/2026", "Statement Closing Date 09/13/2026"], "2026-09-13"),
    (["Credit Limit $9,000.00", "Statement Closing Date09/13/2026 by 10/07/2026."], "2026-09-13"),
    (["Statement Closing Date 09/13/2026 Payment Due Date 10/07/2026"], "2026-09-13"),
    # American Express statements of 2016 print the next closing date beside it.
    (["Closing Date03/14/16 Next Closing Date04/13/16 Account Ending"], "2016-03-14"),
    # Target Circle Card prints the due date on the line before.
    (["Payment Due Date: 10/17/2026", "Statement Closing Date: 9/18/2026"], "2026-09-18"),
])
def test_a_closing_date_is_never_taken_from_a_due_date_beside_it(lines, closing):
    """The closing date is the latest of the dates that run on right after
    its label. The latest date anywhere on the label's line, joined with
    the line before or after it, was the due date or the next closing date
    on each of these (#32). The last two shapes are from real statements,
    whose Period End this moved back to the statement's own date."""
    assert xt.find_period(lines) == (None, closing)


def test_two_lines_of_one_column_stay_apart_however_their_characters_drift():
    """Lines 8.5pt apart whose characters drift 3pt either way, the lower
    one set half a character to the right, as proportional type falls. A
    character of the lower line touches the upper line's last character
    and can sit within reach of it. It continues the line nearest its
    height."""
    tls = (_drifting("Statement Closing Date 09/13/2026", 300.0, lambda i: 120.0 + DRIFT[i % 8])
           + _drifting("Payment Due Date 10/07/2026", 302.5, lambda i: 128.5 + DRIFT[(i + 3) % 8]))
    assert xt.page_lines(tls) == ["Statement Closing Date 09/13/2026", "Payment Due Date 10/07/2026"]


def test_a_column_whose_rows_sit_between_the_labels_rows_is_not_glued_on():
    """The column beside the summary box sets its lines between the box's
    rows. Its first character is far from where the label's line ends, so
    it starts a line of its own, and its date never reads as the label's."""
    tls = ([_line("Credit Limit $9,000.00", 100.0)]
           + _drifting("Statement Closing Date 09/13/2026", 300.0, lambda i: 120.0 + DRIFT[i % 8] / 3)
           + _drifting("Payment Due Date 10/07/2026", 520.0, lambda i: 125.5 + DRIFT[i % 8] / 3))
    lines = xt.page_lines(tls)
    assert lines == ["Credit Limit $9,000.00", "Statement Closing Date 09/13/2026",
                     "Payment Due Date 10/07/2026"]
    assert xt.find_period(lines) == (None, "2026-09-13")


def test_a_line_below_that_starts_where_a_label_ends_is_not_joined_to_it():
    """The next row's date starts just right of where the label ends, the
    only line it touches. It is a row below, so it starts a line of its
    own, and the label keeps its own date."""
    tls = ([_line("Credit Limit $9,000.00", 100.0)]
           + _drifting("Statement Closing Date", 300.0, lambda i: 120.0 + DRIFT[i % 8] / 3)
           + _drifting("09/13/2026", 470.0, lambda i: 120.0 + DRIFT[i % 8] / 3)
           + _drifting("10/07/2026", 412.0, lambda i: 131.0 + DRIFT[i % 8] / 3))
    lines = xt.page_lines(tls)
    assert lines == ["Credit Limit $9,000.00", "Statement Closing Date 09/13/2026", "10/07/2026"]
    assert xt.find_period(lines) == (None, "2026-09-13")


@pytest.mark.parametrize("seed", range(20))
def test_every_line_of_a_block_drifting_3pt_either_way_reads_whole(seed):
    """Twelve lines 10pt apart whose characters each drift up to 3pt either
    way, every other line set half a character over as proportional type
    falls, so a letter of one line can sit nearer the next line's band than
    its own. Every line reads whole, in order, for each of twenty blocks."""
    import random
    rnd = random.Random(seed)
    tls = []
    for r in range(12):
        tls += _drifting(chr(65 + r) * 30, 40.0 + 2.5 * (r % 2),
                         lambda i, r=r: 100.0 + 10 * r + rnd.uniform(-3, 3))
    assert xt.page_lines(tls) == [chr(65 + r) * 30 for r in range(12)]


def _rebuilt(*lines):
    """xt._band_lines over lines given as (x0, tops), one letter each."""
    chars = [tl["chars"][0] for r, (x0, tops) in enumerate(lines)
             for tl in _drifting(chr(65 + r) * len(tops), x0, lambda i, tops=tops: tops[i])]
    return [text for _, text in sorted(xt._band_lines(chars))]


def test_a_letter_that_two_lines_could_take_goes_to_the_nearer_one():
    """The second line's sixth letter, at 105.6, is within reach of both
    lines. It continues its own, whose height it is nearer, not whichever
    line was begun first. Found by search over small drifting blocks."""
    assert _rebuilt((40.5, [99.5, 100.0, 102.3, 99.3, 100.0, 101.3, 103.4, 98.9]),
                    (44.2, [110.6, 106.5, 112.4, 112.4, 111.4, 105.6, 109.9, 111.7])) == [
        "AAAAAAAA", "BBBBBBBB"]


def test_the_start_of_a_line_left_on_its_own_goes_back_to_its_line():
    """The second line's first letter, at 113.7, is too far from the next
    at 107.2 for them to join, and is left a piece too short to have a
    height of its own. It goes to the line nearest its height, its own,
    rather than standing as a line of one letter. Found by search."""
    assert _rebuilt((40.0, [100.0, 96.0, 98.1, 96.7, 99.2, 96.3, 96.2, 98.4]),
                    (41.2, [113.7, 112.8, 107.2, 113.1, 112.3, 110.8, 112.1, 111.8])) == [
        "AAAAAAAA", "BBBBBBBB"]


def test_a_value_printed_well_to_the_right_of_its_label_reads_after_it():
    """A summary box can print the value at its right edge. The label and
    the value are read as one line, the label first, even when the value
    sits a little higher."""
    tls = (_drifting("Statement Closing Date", 300.0, lambda i: 121.0 + DRIFT[i % 8] / 2)
           + _drifting("09/13/2026", 450.0, lambda i: 119.5 + DRIFT[i % 8] / 4))
    assert xt.page_lines(tls) == ["Statement Closing Date 09/13/2026"]


def test_a_page_read_whole_is_left_exactly_as_pdfplumber_gave_it():
    tls = [_line("Previous Balance $2,500.00", 100.0), _line("A", 110.0), _line("B", 118.0),
           _line("08/16/26 NFO PAYMENT RECEIVED $1,482.17", 130.0)]
    assert xt.page_lines(tls) == [tl["text"] for tl in tls]


def test_a_closing_date_label_with_a_stray_space_is_still_read():
    assert xt.find_period(["Statement Clos ing Date09/13/2026"]) == (None, "2026-09-13")
    assert xt.find_period(["Statement Closing Date 08/13/2026", "Days in Billing Cycle 31"]) == (
        None, "2026-08-13")


def _cut_row(pieces, top, x0=300.0, gaps=()):
    """One row as pdfplumber cut it on dertbv's September and October Visa
    (#32), every piece a line of its own at one height. Characters are 5
    points apart, and a wider gap opens before each character index in
    `gaps`, where a space falls."""
    out, x, i = [], x0, 0
    for piece in pieces:
        chars = []
        for ch in piece:
            if ch == " ":
                continue
            if i in gaps:
                x += 5.0
            chars.append({"text": ch, "x0": x, "x1": x + 4.5, "top": top, "size": 8.0})
            x += 5.0
            i += 1
        out.append({"text": piece, "top": top, "chars": chars})
    return out


# The 21 pieces of the label row as pdfplumber 0.11.10 gave them, the date's
# digits written in. All sit at top 457.2, and only "i ng Date" is longer
# than two characters.
SEPTEMBER_ROW = ["St", "a", "t", "e", "m", "e", "n", "t", "C", "l", "o", "s", "i ng Date",
                 "0", "9", "/1", "3", "/2", "0", "2", "6"]


def test_a_long_piece_cut_from_a_scattered_row_is_rebuilt_with_it():
    """dertbv's September and October Visa on 0.52.0 (#32). The label row
    reached page_lines as 21 pieces at one height. "i ng Date" was long
    enough to be kept as a line of its own, sorted ahead of the rebuilt
    "Statement Clos 09/13/2026", and the label never stood before its date.
    A longer piece at the height of the scattered ones is now rebuilt with
    them, as @dertbv proposed."""
    tls = ([_line("Credit Limit $9,000.00", 400.0)]
           + _cut_row(SEPTEMBER_ROW, 457.2, gaps=(9, 13, 16))
           + [_line("Days in Billing Cycle 31", 480.0)])
    lines = xt.page_lines(tls)
    assert lines[0] == "Credit Limit $9,000.00" and lines[-1] == "Days in Billing Cycle 31"
    assert len(lines) == 3
    assert xt.find_period(lines) == (None, "2026-09-13")


def test_a_whole_line_away_from_the_scattered_rows_is_kept_as_it_was():
    """Only a longer piece within a point of two scattered ones is taken into
    the rebuild. A whole line on its own height elsewhere on the page stays
    exactly as pdfplumber read it."""
    tls = ([_line("Previous Balance $2,500.00", 300.0)]
           + _cut_row(SEPTEMBER_ROW, 457.2, gaps=(9, 13, 16))
           + [_line("Payment Due Date 10/07/2026", 470.0)])
    lines = xt.page_lines(tls)
    assert lines[0] == "Previous Balance $2,500.00"
    assert lines[-1] == "Payment Due Date 10/07/2026"


def test_the_cache_is_read_again_for_the_rebuilt_lines():
    assert xt.CACHE_VERSION >= 9


# -- text that looks like a formula stays text ----------------------------------------

# A merchant chooses the name a statement prints, and the archive's index
# names the account. Each value here is shaped like a formula and is
# harmless arithmetic or an address on a reserved domain.
MERCHANT = '=HYPERLINK("https://example.invalid/?"&A1,"Open")'
FORMULA_BANK = """Statement Period: 06/13/2026to 07/12/2026
Beginning Balance $4,812.37
Ending Balance $6,443.85
Date Description Debits Credits Balance
06/13 Beginning Balance 0 0 $4,812.37
06/13 %s $58.21 0 $4,754.16
06/15 @SUM(1,1) 0 $2,146.73 $6,900.89
06/19 +1+1 GROCER $187.44 0 $6,713.45
06/20 -1+1 0 $42.00 $6,755.45
07/05 =1+1 $0.00 0 $6,755.45
07/09 -42 $311.60 0 $6,443.85
07/12 Ending Balance - - $6,443.85
""" % MERCHANT
ACCOUNT = "@SUM(2,2), =2+2"          # Account Holder, then the Document Title
STATEMENT = "=3+3 Statement.pdf"
FORMULAS_BY_SHEET = {
    "Transactions": {"+Bank", ACCOUNT, MERCHANT, "@SUM(1,1)", "+1+1 GROCER", "-1+1", "=1+1",
                     STATEMENT},
    "Statements": {"+Bank", ACCOUNT, STATEMENT},
}


@pytest.fixture
def formula_root(tmp_path, monkeypatch):
    pytest.importorskip("pdfplumber")
    folder = tmp_path / "Plus Bank"
    folder.mkdir()
    pdf = folder / STATEMENT
    pdf.write_bytes(b"%PDF")
    with open(folder / "+Bank Document Index.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Account Holder", "Document Date", "Document Title", "PDF Full Path"])
        w.writeheader()
        w.writerow({"Account Holder": "@SUM(2,2)", "Document Date": "2026-07-15",
                    "Document Title": "=2+2", "PDF Full Path": str(pdf)})
    monkeypatch.setattr(xt, "pdf_lines", lambda p: FORMULA_BANK.splitlines())
    return tmp_path


def _cells(ws):
    return [c for row in ws.iter_rows() for c in row]


def _column(ws, name):
    header = [c.value for c in ws[1]]
    return [row[header.index(name)] for row in ws.iter_rows(min_row=2)]


def test_every_text_cell_on_both_sheets_is_a_string_cell_never_a_formula(formula_root):
    openpyxl = pytest.importorskip("openpyxl")
    import zipfile
    r = xt.export(formula_root, log=lambda *_: None)
    assert r["reconciled"] == 1 and r["transactions"] == 6
    wb = openpyxl.load_workbook(r["path"])
    assert wb.sheetnames == list(FORMULAS_BY_SHEET)
    for ws in wb:
        cells = _cells(ws)
        assert all(c.data_type in ("s", "n") for c in cells), \
            [(c.coordinate, c.data_type) for c in cells if c.data_type not in ("s", "n")]
        assert all(c.data_type == "s" for c in cells if isinstance(c.value, str))
        assert {c.value for c in cells if c.quotePrefix} == FORMULAS_BY_SHEET[ws.title], ws.title
    descriptions = {c.value: c for c in _column(wb["Transactions"], "Description")}
    assert descriptions[MERCHANT].data_type == "s"
    # A description that is a plain negative number is text, with nothing in front.
    assert descriptions["-42"].data_type == "s" and not descriptions["-42"].quotePrefix
    with zipfile.ZipFile(r["path"]) as z:
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/")]
        assert len(sheets) == 2
        assert not any(b"<f>" in z.read(n) or b"<f " in z.read(n) for n in sheets)


def test_amounts_balances_and_counts_stay_numbers_with_their_format(formula_root):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(xt.export(formula_root, log=lambda *_: None)["path"])
    txns, stmts = wb["Transactions"], wb["Statements"]
    amounts = _column(txns, "Amount")
    assert sorted(c.value for c in amounts) == [-311.6, -187.44, -58.21, 0.0, 42.0, 2146.73]
    for col in ("Amount", "Balance"):
        for c in _column(txns, col):
            assert c.data_type == "n" and c.number_format == "#,##0.00;[Red]-#,##0.00", (col, c.value)
    (stmt,) = list(stmts.iter_rows(min_row=2))
    stmt = dict(zip([c.value for c in stmts[1]], stmt))
    assert (stmt["Beginning Balance"].value, stmt["Beginning Balance"].data_type) == (4812.37, "n")
    assert (stmt["Ending Balance"].value, stmt["Ending Balance"].data_type) == (6443.85, "n")
    assert (stmt["Transactions"].value, stmt["Transactions"].data_type) == (6, "n")
    assert stmt["Sum of Amounts"].data_type == "n"
    assert stmt["Status"].value == "reconciled, balance column" and stmt["Status"].data_type == "s"


def test_the_csv_quotes_text_that_could_start_a_formula_and_no_amount(formula_root):
    r = xt.export(formula_root, as_csv=True, log=lambda *_: None)
    with open(r["path"], encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    by_amount = {x["Amount"]: x for x in rows}
    assert by_amount["-58.21"]["Description"] == "'" + MERCHANT
    assert by_amount["2146.73"]["Description"] == "'@SUM(1,1)"
    assert by_amount["-187.44"]["Description"] == "'+1+1 GROCER"
    assert by_amount["42.0"]["Description"] == "'-1+1"
    assert by_amount["0.0"]["Description"] == "'=1+1"
    assert by_amount["-311.6"]["Description"] == "-42"
    assert by_amount["-311.6"]["Balance"] == "6443.85"
    for x in rows:
        assert (x["Provider"], x["Account"], x["Statement"]) == ("'+Bank", "'" + ACCOUNT, "'" + STATEMENT)
        assert (x["Date"][:5], x["Statement Date"], x["Reconciled"]) == ("2026-", "2026-07-15", "yes")
        assert not x["Amount"].startswith("'") and not x["Balance"].startswith("'")


# -- an index the app wrote itself -----------------------------------------------------

INDEX_COLUMNS = ["Account Holder", "Document Date", "Document Title", "PDF Filename",
                 "PDF Full Path"]


def _archive(root: Path, by_the_app: bool) -> Path:
    """One statement whose file name starts like a formula, its index
    written as an app writes it through core storage's CsvFile, or plainly
    as an older version wrote it. The path is relative to the index's
    folder, as every install the control panel creates records it."""
    folder = root / "Plus Bank"
    folder.mkdir(parents=True)
    (folder / STATEMENT).write_bytes(b"%PDF")
    row = {"Account Holder": "@SUM(2,2)", "Document Date": "2026-07-15", "Document Title": "=2+2",
           "PDF Filename": STATEMENT, "PDF Full Path": STATEMENT}
    index = folder / "+Bank Document Index.csv"
    if by_the_app:
        from paperpull_core.storage import CsvFile
        CsvFile(index, INDEX_COLUMNS).append_rows([row])
    else:
        with open(index, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS)
            w.writeheader()
            w.writerow(row)
    return index


def test_an_index_the_app_wrote_finds_its_statement_and_gives_the_words_it_was_given(
        tmp_path, monkeypatch):
    """The app's index holds a file name like =3+3 Statement.pdf with a
    quote in front, so read as it is, the statement would be looked for
    under a name it does not have and left out of the spreadsheet without
    a word. It is found, and both spreadsheets are the ones the same words
    written plainly give."""
    pytest.importorskip("pdfplumber")
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(xt, "pdf_lines", lambda p: FORMULA_BANK.splitlines())
    old, new = tmp_path / "old", tmp_path / "new"
    _archive(old, by_the_app=False)
    index = _archive(new, by_the_app=True)
    assert ",'=3+3 Statement.pdf,'=3+3 Statement.pdf" in index.read_text(encoding="utf-8-sig")
    (row,) = xt._index_rows(index)
    assert xt.pdf_path(index, row).is_file()
    assert [p["pdfs"] for p in xt.providers(new)] == [1]
    made = {}
    for root in (old, new):
        r = xt.export(root, as_csv=True, log=lambda *_: None)
        assert (r["statements"], r["transactions"]) == (1, 6), root.name
        made[root.name] = Path(r["path"]).read_bytes()
    assert made["old"] == made["new"]
    sheets = {}
    for root in (old, new):
        wb = openpyxl.load_workbook(xt.export(root, log=lambda *_: None)["path"])
        sheets[root.name] = {ws.title: [[(c.value, c.data_type, c.quotePrefix) for c in row]
                                        for row in ws.iter_rows()] for ws in wb}
    assert sheets["old"] == sheets["new"]


# -- what an xlsx cell cannot hold ---------------------------------------------------

# Every character XML 1.0 has no place for, so an xlsx cannot hold it. The
# control characters are the 29 openpyxl refuses, and the last two and the
# surrogates it wrote into a workbook Excel would not open.
CONTROLS = [chr(n) for n in range(0x20) if n not in (0x9, 0xA, 0xD)]
IN_A_FILE = CONTROLS + [chr(0xFFFE), chr(0xFFFF)]
CANNOT_HOLD = IN_A_FILE + [chr(n) for n in range(0xD800, 0xE000)]
_CANNOT = frozenset(CANNOT_HOLD)
# The six Python counts as blank space, which become a space in a cell.
BLANK = frozenset(chr(n) for n in (0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x1F))


def _held(text: str) -> str:
    return "".join(" " if c in BLANK else "" if c in _CANNOT else c for c in text)


def _excel_reads(text: str) -> str:
    """What Excel shows for an xlsx string, _x and four hex digits and _ as
    one character (measured 2026-10-16, see test_sheets.py)."""
    import re
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), text)


def _no_cell_holds_what_an_xlsx_cannot(path):
    openpyxl = pytest.importorskip("openpyxl")
    import zipfile
    wb = openpyxl.load_workbook(path)
    for ws in wb:
        for c in _cells(ws):
            assert not (isinstance(c.value, str) and not _CANNOT.isdisjoint(c.value)), c.coordinate
    with zipfile.ZipFile(path) as z:
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/")]
        assert not any(b"<f>" in z.read(n) or b"<f " in z.read(n) for n in sheets)
    return wb


def _bank_with_every_character(chars) -> tuple:
    """A made-up statement, one $1.00 debit described SHOP, the character,
    NAME for each character, and a last one whose description Excel would
    read as its escape for =. Its lines, and the balance after that last."""
    begin = 1000.0 + len(chars)
    bal, lines = begin, []
    for i, what in enumerate(["SHOP " + c + "NAME" for c in chars] + ["_x003D_1+1"]):
        bal -= 1
        lines.append("06/%02d %s $1.00 0 $%s" % (i % 28 + 1, what, format(bal, ",.2f")))
    return (["Statement Period: 06/01/2026to 06/30/2026",
             "Beginning Balance $%s" % format(begin, ",.2f"),
             "Ending Balance $%s" % format(bal, ",.2f"),
             "Date Description Debits Credits Balance",
             "06/01 Beginning Balance 0 0 $%s" % format(begin, ",.2f")]
            + lines + ["06/30 Ending Balance - - $%s" % format(bal, ",.2f")]), bal


def _bank_folder(root: Path, holder: str, title: str) -> Path:
    """The statement's folder, its index written as the app writes it,
    through core storage's CsvFile."""
    from paperpull_core.storage import CsvFile
    folder = root / "Plus Bank"
    folder.mkdir()
    (folder / "June Statement.pdf").write_bytes(b"%PDF")
    index = CsvFile(folder / "Bank Document Index.csv", INDEX_COLUMNS)
    index.append_rows([{"Account Holder": holder, "Document Date": "2026-06-30",
                        "Document Title": title, "PDF Filename": "June Statement.pdf",
                        "PDF Full Path": "June Statement.pdf"}])
    return index.path


def test_an_index_and_a_statement_holding_a_character_an_xlsx_cannot_hold_make_both_spreadsheets(
        tmp_path, monkeypatch):
    """A provider's JSON can carry a NUL or another control character in a
    document title, and a statement's text in a description. openpyxl
    refused the row holding one and the whole workbook was lost. Now the
    character is taken out of the cell, a space standing in for one that is
    blank space, the text around it stays, one in front of =1+1 leaves =1+1
    with the quote prefix, and the CSV keeps every character the statement
    gave."""
    pytest.importorskip("pdfplumber")
    assert len(CONTROLS) == 29
    index = _bank_folder(tmp_path, chr(0) + "=1+1", "Checking " + "".join(IN_A_FILE))
    assert chr(0) in index.read_text(encoding="utf-8-sig")
    lines, last = _bank_with_every_character(IN_A_FILE)
    monkeypatch.setattr(xt, "pdf_lines", lambda p: lines)
    r = xt.export(tmp_path, log=lambda *_: None)
    assert (r["statements"], r["transactions"], r["reconciled"]) == (1, len(IN_A_FILE) + 1, 1)
    wb = _no_cell_holds_what_an_xlsx_cannot(r["path"])
    txns, stmts = wb["Transactions"], wb["Statements"]
    for c in _column(txns, "Account") + _column(stmts, "Account"):
        assert (c.value, c.data_type, c.quotePrefix) == ("=1+1, Checking " + " " * 6, "s", True)
    shown = {b.value: d for b, d in zip(_column(txns, "Balance"), _column(txns, "Description"))}
    escaped = shown.pop(last)
    assert _excel_reads(escaped.value) == "_x003D_1+1" and not escaped.quotePrefix
    assert {d.value for d in shown.values()} == {"SHOP NAME"}
    assert all(c.data_type == "n" for c in _column(txns, "Amount"))
    with open(xt.export(tmp_path, as_csv=True, log=lambda *_: None)["path"],
              encoding="utf-8-sig", newline="") as fh:
        written = {float(x["Balance"]): x["Description"] for x in csv.DictReader(fh)}
    assert {c for c in IN_A_FILE if not c.isspace()} <= set("".join(written.values()))
    for balance, d in shown.items():
        assert d.value == _held(written[balance]), balance


# The surrogates, each half of a character UTF-16 writes as two, and the
# mark a browser shows for one on its own (sheets, HALF OF A CHARACTER).
HALVES = frozenset(chr(n) for n in range(0xD800, 0xE000))
HIGH, LOW, MARK = chr(0xD83D), chr(0xDE00), chr(0xFFFD)


def _descriptions(r: dict) -> dict:
    """Each transaction's description by its balance, from the CSV read
    strictly as UTF-8, or from the workbook's Transactions sheet."""
    if r["format"] == "csv":
        with open(r["path"], encoding="utf-8-sig", newline="") as fh:
            return {float(x["Balance"]): x["Description"] for x in csv.DictReader(fh)}
    txns = _no_cell_holds_what_an_xlsx_cannot(r["path"])["Transactions"]
    assert all(c.data_type == "n" for c in _column(txns, "Amount"))
    return {b.value: d.value for b, d in zip(_column(txns, "Balance"), _column(txns, "Description"))}


def test_a_statement_holding_a_surrogate_makes_both_spreadsheets_from_the_pdf_and_from_the_cache(
        tmp_path, monkeypatch):
    """A statement's text reaches the export from the PDF, and on a later
    export from the cache, which is JSON and holds half of a surrogate pair
    as an escape. So every character an xlsx cannot hold is tried here, the
    2,048 surrogates too, both ways and into both spreadsheets. The CSV
    stopped at the first half with UnicodeEncodeError. Each half is U+FFFD
    in both now, as a browser shows it."""
    pytest.importorskip("pdfplumber")
    _bank_folder(tmp_path, "Jane", "Checking")
    lines, last = _bank_with_every_character(CANNOT_HOLD)
    halves = {1000.0 + len(CANNOT_HOLD) - i - 1 for i, c in enumerate(CANNOT_HOLD) if c in HALVES}
    assert len(halves) == 2048
    for as_csv in (False, True):
        (tmp_path / xt.CACHE_NAME).unlink(missing_ok=True)
        monkeypatch.setattr(xt, "pdf_lines", lambda p: lines)
        for way in ("from the PDF", "from the cache"):
            r = xt.export(tmp_path, as_csv=as_csv, log=lambda *_: None)
            assert (r["transactions"], r["reconciled"]) == (len(CANNOT_HOLD) + 1, 1), way
            shown = _descriptions(r)
            escaped = shown.pop(last)
            assert (escaped if as_csv else _excel_reads(escaped)) == "_x003D_1+1", way
            assert len(shown) == len(CANNOT_HOLD), way
            assert {shown[b] for b in halves} == {"SHOP " + MARK + "NAME"}, way
            if not as_csv:
                assert {d for b, d in shown.items() if b not in halves} == {"SHOP NAME"}, way
            monkeypatch.setattr(xt, "pdf_lines", lambda p: pytest.fail("read the PDF again"))
        assert chr(92) + "ud800" in (tmp_path / xt.CACHE_NAME).read_text(encoding="utf-8")


def _statement_pdf(lines) -> bytes:
    """A one-page PDF of these lines in Helvetica, whose ToUnicode map gives
    the codes of { | } ~ by number, as a high half, a low half, a low half
    and a high half. pdfplumber takes a number there for the character it
    names, so { and | read as the two halves of U+1F600."""
    def literal(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = ("BT /F1 10 Tf 14 TL 40 750 Td "
               + " ".join("(%s) Tj T*" % literal(line) for line in lines) + " ET").encode("ascii")
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CMapName /Halves def\n1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
            "1 beginbfrange\n<7B> <7E> [55357 56832 56832 55357]\nendbfrange\n"
            "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(cmap), cmap),
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (n, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


HALF_LINES = ["Statement Period: 06/01/2026to 06/30/2026",
              "Beginning Balance $1,000.00",
              "Ending Balance $996.00",
              "Date Description Debits Credits Balance",
              "06/01 Beginning Balance 0 0 $1,000.00",
              "06/02 SHOP ~NAME $1.00 0 $999.00",
              "06/03 {| CAFE $1.00 0 $998.00",
              "06/04 ~=1+1 $1.00 0 $997.00",
              "06/05 =1+1} $1.00 0 $996.00",
              "06/30 Ending Balance - - $996.00"]


def test_a_statement_whose_font_gives_half_a_character_makes_both_spreadsheets(tmp_path):
    """pdfplumber gives half of a surrogate pair for a font whose ToUnicode
    map names a character by number (measured 2026-10-16, pdfplumber
    0.11.10), and the CSV export stopped at it with UnicodeEncodeError. The
    PDF here is read by pdfplumber itself. pdf_lines makes the text whole as
    it reads it (paperpull_core.characters), so both spreadsheets, from the
    PDF and then from the cache, show a half as U+FFFD, as a browser shows
    it, and two halves side by side as the character they make, and the
    cache holds U+FFFD too."""
    pdfplumber = pytest.importorskip("pdfplumber")
    pytest.importorskip("openpyxl")
    index = _bank_folder(tmp_path, "Jane", "Checking")
    pdf = index.parent / "June Statement.pdf"
    pdf.write_bytes(_statement_pdf(HALF_LINES))
    with pdfplumber.open(str(pdf)) as opened:
        given = opened.pages[0].extract_text() or ""
    assert "SHOP " + HIGH + "NAME" in given, ascii(given)
    read = xt.pdf_lines(pdf)
    assert "06/02 SHOP " + MARK + "NAME $1.00 0 $999.00" in read, [ascii(line) for line in read]
    assert not any(HIGH in line or LOW in line for line in read), [ascii(line) for line in read]
    want = {999.0: "SHOP " + MARK + "NAME", 998.0: chr(0x1F600) + " CAFE",
            997.0: MARK + "=1+1", 996.0: "=1+1" + MARK}
    for as_csv in (True, False):
        (tmp_path / xt.CACHE_NAME).unlink(missing_ok=True)
        for way in ("from the PDF", "from the cache"):
            r = xt.export(tmp_path, as_csv=as_csv, log=lambda *_: None)
            assert (r["transactions"], r["reconciled"], r["read"]) == \
                (4, 1, int(way == "from the PDF")), way
            quoted = {**want, 996.0: "'=1+1" + MARK} if as_csv else want
            assert _descriptions(r) == quoted, way
        # The emoji the two halves make is written as two escapes, which
        # read back as the one character, so the cache is read to tell.
        cached = json.dumps(json.loads((tmp_path / xt.CACHE_NAME).read_text(encoding="utf-8")),
                            ensure_ascii=False)
        assert MARK in cached and chr(0x1F600) in cached
        assert not any(c in HALVES for c in cached)
    import openpyxl
    txns = openpyxl.load_workbook(r["path"])["Transactions"]
    prefixed = {b.value: d.quotePrefix for b, d in zip(_column(txns, "Balance"),
                                                         _column(txns, "Description"))}
    assert prefixed == {999.0: False, 998.0: False, 997.0: False, 996.0: True}


def _stalling_pdf(pieces: int = 1_000_000) -> bytes:
    """A PDF of a few kilobytes whose text, a million pieces drawn one after
    another, keeps pdfplumber reading for seconds and fills its memory, as
    test_pdf_reader's does."""
    import zlib
    body = zlib.compress(b"BT /F1 1 Tf " + b"(x) Tj 1 0 Td " * pieces + b"ET", 9)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out) + b" " * 4000


def test_a_page_whose_characters_did_not_come_keeps_every_line():
    """The PDF reader hands back a page's characters only when it counts
    enough short lines to rebuild, and counts on the text made whole. Where
    the two counts could differ, two halves of one character counted as two
    there and as one here, the rebuild had no characters and the lines it
    would rebuild were lost (review). They are kept as read."""
    tls = [{"text": chr(65 + n % 26), "top": 100.0 + 12 * n} for n in range(xt.SCATTER_MIN)]
    tls.append({"text": "Ending Balance $996.00", "top": 400.0})
    assert xt.page_lines(tls) == [tl["text"] for tl in tls]


def test_a_statement_refused_for_a_limit_is_named_and_read_again_by_the_next_export(
        tmp_path, monkeypatch, capsys):
    """pdfplumber read the archive in the export's own process, with nothing
    to stop a PDF made to keep it busy or to fill the memory. It reads in
    PaperPull's PDF reader now, held to PDF_SECONDS. A statement refused is
    named with the limit it met and is not kept in the cache, so raising the
    limit is all the next export needs to read it."""
    import time
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("pdfplumber")
    from paperpull_core import intake, pdf_reader
    monkeypatch.setattr(intake, "PDF_SECONDS", 1)
    pdf_reader.stop()
    pdf_reader.forget()
    try:
        index = _bank_folder(tmp_path, "Jane", "Checking")
        (index.parent / "June Statement.pdf").write_bytes(_stalling_pdf())
        started = time.monotonic()
        r = xt.export(tmp_path, log=lambda *_: None)
        assert time.monotonic() - started < 15
        assert (r["statements"], r["read"], r["transactions"]) == (1, 1, 0), r
        assert "PDF_SECONDS" in capsys.readouterr().out
        (row,) = openpyxl.load_workbook(r["path"])["Statements"].iter_rows(min_row=2,
                                                                           values_only=True)
        status = row[xt.STMT_COLUMNS.index("Status")]
        assert status.startswith("The PDF took longer than 1 seconds to read"), status
        assert "PDF_SECONDS in paperpull_core/intake.py is the limit" in status, status
        cache = tmp_path / xt.CACHE_NAME
        held = json.loads(cache.read_text("utf-8"))["files"] if cache.exists() else {}
        assert not any("June Statement.pdf" in k for k in held), "a refusal was kept"
        # The next export reads it again, and the run's memory refuses the
        # same bytes at once.
        again = time.monotonic()
        r = xt.export(tmp_path, log=lambda *_: None)
        assert (r["read"], r["cached"]) == (1, 0), r
        assert time.monotonic() - again < 5
    finally:
        pdf_reader.stop()
        pdf_reader.forget()


def test_a_statement_filed_without_kind_folders_is_named_with_every_folder(tmp_path):
    """A documents folder the Move filed without kind folders (#201) has a
    pattern's folders at its first level, so none of them is taken for the
    folder of a kind and left out of the name."""
    bank, docs = tmp_path / "A Bank", tmp_path / "Watched"
    bank.mkdir()
    index = bank / "A Bank Document Index.csv"
    (bank / "documents-folders.json").write_text(json.dumps([str(docs)]), encoding="utf-8")
    pdf = docs / "2026" / "Checking 1111" / "2026-07-15 Statement.pdf"
    assert xt.statement_name(index, pdf) == "Checking 1111/2026-07-15 Statement.pdf"
    (bank / "documents-folders-flat.json").write_text(json.dumps([str(docs)]), encoding="utf-8")
    assert xt.statement_name(index, pdf) == "2026/Checking 1111/2026-07-15 Statement.pdf"
    assert xt.statement_name(index, docs / "2026-07-15 Statement.pdf") == \
        "2026-07-15 Statement.pdf"
