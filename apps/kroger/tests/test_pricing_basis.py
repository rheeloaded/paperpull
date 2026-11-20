"""Invented receipt lines only; preserve the price basis separately from item count."""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kroger_site as site
import storage
from paperpull_core.models import Item


@pytest.mark.parametrize('quantity,unit', [('1.75', 'lbs'), ('2.5', 'lbs'), ('0.8', 'lb'), ('0.25', 'kg'), ('18.45', 'gal')])
def test_weighted_price_basis_does_not_change_package_count(quantity, unit):
    item = site.items_from_lines(['Item Details', 'Example product', '$4.00',
                                 f'{quantity} {unit} x $2.29 each (approx.)', 'Payment Details'])[0]
    assert item.quantity == '1'
    assert item.pricing_quantity == quantity
    assert item.pricing_unit == ('lb' if unit == 'lbs' else unit)
    assert item.unit_price == '$2.29'
    assert item.line_total == '$4.00'  # Never recompute a printed total from rounded prices.
    assert Item.from_dict(item.to_dict()) == item


def test_each_price_basis_and_old_records():
    item = site.items_from_lines(['Item Details', 'Example package', '$6.00',
                                 '3 x $2.00 each', 'Payment Details'])[0]
    assert (item.quantity, item.pricing_quantity, item.pricing_unit) == ('3', '3', 'each')
    assert Item.from_dict({'name': 'Old record', 'quantity': '1'}).pricing_unit == ''


def test_legacy_history_is_backed_up_and_upgraded_before_append(tmp_path):
    path = tmp_path / 'history.csv'
    columns = ['Item Name', 'Quantity', 'Pricing Quantity', 'Pricing Unit', 'Unit Price']
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['Item Name', 'Quantity', 'Unit Price'])
        writer.writeheader()
        writer.writerow({'Item Name': 'Old item', 'Quantity': '1', 'Unit Price': '$2.00'})
    original = path.read_bytes()
    backups = tmp_path / 'Backups'
    ledger = storage.PricingCsvFile(path, columns, backups)
    ledger.append_rows([{'Item Name': 'New item', 'Quantity': '1', 'Pricing Quantity': '1.75',
                         'Pricing Unit': 'lb', 'Unit Price': '$2.29'}])
    with path.open(encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]['Unit Price'] == '$2.00'
    assert rows[0]['Pricing Quantity'] == ''
    assert rows[1]['Pricing Quantity'] == '1.75'
    assert rows[1]['Unit Price'] == '$2.29'
    assert any(p.read_bytes() == original for p in backups.iterdir() if p.is_file())
    ledger.append_rows([{'Item Name': 'Third item', 'Quantity': '1'}])
    with path.open(encoding='utf-8-sig', newline='') as fh:
        assert len(list(csv.DictReader(fh))) == 3


def test_unknown_header_is_never_overwritten(tmp_path):
    path = tmp_path / 'history.csv'
    path.write_text('Unexpected,Header\nprivate,value\n', encoding='utf-8')
    original = path.read_bytes()
    ledger = storage.PricingCsvFile(path, ['Quantity', 'Pricing Quantity', 'Pricing Unit'])
    with pytest.raises(ValueError, match='unknown header'):
        ledger._ensure_header()
    assert path.read_bytes() == original


def test_queued_legacy_writes_must_be_flushed_before_migration(tmp_path):
    path = tmp_path / 'history.csv'
    path.write_text('Quantity\n1\n', encoding='utf-8')
    original = path.read_bytes()
    ledger = storage.PricingCsvFile(path, ['Quantity', 'Pricing Quantity', 'Pricing Unit'])
    ledger.waiting_path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='queued Kroger CSV writes'):
        ledger._ensure_header()
    assert path.read_bytes() == original
