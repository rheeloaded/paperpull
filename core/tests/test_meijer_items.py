from paperpull_core.meijer_items import parse_items


def receipt(items, total='5.00'):
    return f'''07/04/26 Fastlane1
GROCERY
{items}
mPerks # -- ********00
TOTAL TOTAL TAX .00
TOTAL {total}
PAYMENTS
Tx:1 Op:2 Tm:3 St:4 12:00:00'''


def test_reads_quantities_sales_and_discounts():
    items = parse_items(receipt('12345678901 MILK\n3 @ 4.99\nwas 16.47 now 14.97 F\n=> FREE item -4.99 F', '9.98'))
    assert len(items) == 1
    assert (items[0].name, items[0].quantity, items[0].line_total) == ('MILK', '3', '$9.98')


def test_coupons_and_weights_are_not_invented():
    items = parse_items(receipt('12345678901 MILK 6.00 F\nTotal Basket Coupon\n=> 1.00 off -1.00'))
    assert len(items) == 1
    assert items[0].unit_price == items[0].line_total == ''
    items = parse_items(receipt('4069 CABBAGE 5.00 F\n2.50 lb @ 1 lb / 2.00'))
    assert items[0].name == 'CABBAGE (2.50 lb)'
    assert items[0].quantity == ''


def test_requires_complete_matching_reconciled_receipt():
    text = receipt('12345678901 MILK 5.00 F')
    assert parse_items(text, '2026-07-05') == []
    assert parse_items(text, '2026-07-04', '6.00') == []
    assert parse_items(text.replace('5.00 F', '4.00 F')) == []
    assert parse_items(text.replace('mPerks #', 'unknown\nmPerks #')) == []
