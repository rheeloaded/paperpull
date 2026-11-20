"""Pricing basis survives both export formats; fixtures contain invented purchases."""
import csv
import importlib.util
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / 'tools/export_purchases.py'
spec = importlib.util.spec_from_file_location('export_pricing_basis_tool', TOOL)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


@pytest.fixture
def purchases(tmp_path):
    path = tmp_path / 'Kroger Order History.csv'
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['Purchase Date', 'Order or Receipt Number', 'Item Name',
                                               'Quantity', 'Pricing Quantity', 'Pricing Unit', 'Unit Price', 'Line Item Total'])
        writer.writeheader()
        writer.writerow({'Purchase Date': '2026-01-01', 'Order or Receipt Number': 'example',
                         'Item Name': 'Example product', 'Quantity': '1', 'Pricing Quantity': '1.75',
                         'Pricing Unit': 'lb', 'Unit Price': '$2.29', 'Line Item Total': '$4.00'})
        writer.writerow({'Item Name': 'Legacy product', 'Quantity': '1'})
    return exporter.load_purchases('Kroger', path)


def test_csv_keeps_pricing_basis_numeric_and_unknown_legacy_basis_empty(tmp_path, purchases):
    assert (purchases[0]['Quantity'], purchases[0]['Pricing Quantity'], purchases[0]['Pricing Unit']) == (1, 1.75, 'lb')
    assert purchases[1]['Pricing Quantity'] is None
    assert purchases[1]['Pricing Unit'] is None
    output = tmp_path / 'Purchases.csv'
    exporter.write_csv(output, purchases)
    with output.open(encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]['Pricing Quantity'] == '1.75'
    assert rows[0]['Pricing Unit'] == 'lb'
    assert rows[0]['Line Total'] == '4.0'
    assert rows[1]['Pricing Quantity'] == ''


def test_xlsx_preserves_numeric_quantity_and_text_unit(tmp_path, purchases):
    openpyxl = pytest.importorskip('openpyxl')
    output = tmp_path / 'Purchases.xlsx'
    exporter.write_xlsx(output, purchases, exporter.orders_from(purchases), [])
    wb = openpyxl.load_workbook(output)
    ws = wb['Purchases']
    columns = {cell.value: cell.column for cell in ws[1]}
    assert ws.cell(2, columns['Pricing Quantity']).value == 1.75
    assert ws.cell(2, columns['Pricing Quantity']).data_type == 'n'
    assert ws.cell(2, columns['Pricing Unit']).value == 'lb'
    assert ws.cell(2, columns['Quantity']).value == 1
    assert ws.cell(3, columns['Pricing Quantity']).value is None
    wb.close()
