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
    assert xt.CACHE_VERSION >= 2
