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
