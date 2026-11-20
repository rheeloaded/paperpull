"""Read complete Meijer till receipts locally; never guess from order-list labels."""
import re
from decimal import Decimal, ROUND_HALF_UP

from paperpull_core.models import Item


def parse_items(text, expected_date='', expected_total=''):
    """Return items only when date and item/discount/tax totals reconcile.

    Meijer's bare product codes are store identifiers, not necessarily UPCs.
    Basket coupons cannot be attributed to individual products, so prices
    on those receipts stay blank. Missing produce weights stay blank too.
    """
    try:
        if not text or len(text) > 100000:
            return []
        lines = [re.sub(r'\s+', ' ', s.strip()) for s in text.splitlines() if s.strip()]
        date = re.match(r'^(\d{2})/(\d{2})/(\d{2}) ', lines[0])
        if not date or not any(re.match(r'^Tx:\d+ Op:\d+ Tm:\d+ St:\d+ ', s) for s in lines):
            return []
        printed_date = f'20{date[3]}-{date[1]}-{date[2]}'
        if expected_date and printed_date != expected_date:
            return []
        sections = {'GENERAL MERCHANDISE', 'DRUGSTORE', 'GROCERY'}
        start = next(i for i, s in enumerate(lines) if s in sections)
        end = next(i for i, s in enumerate(lines) if s.startswith('mPerks # -- '))
        if end <= start or 'PAYMENTS' not in lines:
            return []
        items, amounts = [], []
        basket, coupons = Decimal(0), False
        i = start
        while i < end:
            line = lines[i]
            if line in sections:
                if coupons:
                    return []
                i += 1
                continue
            if line in {'COUPONS', 'Total Basket Coupon', 'mPerks Offer'}:
                coupons = True
                i += 1
                continue
            if coupons:
                m = re.fullmatch(r'(?:\d+ Vendor Coupon|=> .+?) -(\d*\.\d{2})(?: [A-Z]+)?', line)
                if not m:
                    return []
                basket += Decimal(m[1])
                i += 1
                continue
            heading = re.fullmatch(r'\*?(\d{4,14}) (.+)', line)
            if not heading:
                return []
            code, name = heading.groups()
            qty, amount, unit = '1', None, ''
            inline = re.fullmatch(r'(.+?) (\d*\.\d{2}) [ +]*[A-Z]+', name)
            if inline:
                name, amount = inline[1], Decimal(inline[2])
            else:
                q = re.fullmatch(r'(\d+) @ (\d*\.\d{2})(?: (\d*\.\d{2}) [ +]*[A-Z]+)?', lines[i+1])
                if q:
                    i += 1
                    qty = q[1]
                    if q[3]:
                        amount = Decimal(q[3])
                elif re.fullmatch(r'1 @ \d+ / \d*\.\d{2}', lines[i+1]):
                    i += 1
                if amount is None:
                    i += 1
                    sale = re.fullmatch(r'was (\d*\.\d{2}) now (\d*\.\d{2}) [ +]*[A-Z]+', lines[i])
                    if not sale:
                        return []
                    amount = Decimal(sale[2])
            while lines[i+1].startswith('=> '):
                i += 1
                discount = re.fullmatch(r'=> .+? -(\d*\.\d{2}) [A-Z]+', lines[i])
                if not discount:
                    return []
                amount -= Decimal(discount[1])
            weight = re.fullmatch(r'(\d*\.\d+) lb @ 1 lb / (\d*\.\d{2})', lines[i+1])
            if weight:
                # Purchases CSV has no unit column: retain the printed unit in
                # the name instead of exporting pounds as whole-item counts.
                i += 1
                name += f' ({weight[1]} lb)'
                qty = ''
            elif re.fullmatch(r'2[12]\d{9}|\d{4}', code):
                qty = ''
            if amount < 0 or (qty and Decimal(qty) <= 0):
                return []
            if qty:
                unit = '$' + str((amount / Decimal(qty)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
            items.append(Item(name=name, quantity=qty, unit_price=unit, line_total=f'${amount:.2f}'))
            amounts.append(amount)
            i += 1
        totals = [s.split()[-1] for s in lines[end:] if re.fullmatch(r'TOTAL \d*\.\d{2}', s)]
        taxes = [s.split()[-1] for s in lines[end:] if re.fullmatch(r'(?:TOTAL )?TOTAL TAX \d*\.\d{2}', s)]
        if len(totals) != 1 or len(taxes) != 1 or not items:
            return []
        total = Decimal(totals[0])
        if expected_total and Decimal(str(expected_total).replace('$', '').replace(',', '')) != total:
            return []
        if sum(amounts) - basket + Decimal(taxes[0]) != total:
            return []
        if basket:
            for item in items:
                item.unit_price = item.line_total = ''
        return items
    except (ValueError, IndexError, StopIteration, ArithmeticError):
        return []


def read_items(path, expected_date='', expected_total=''):
    from paperpull_core.receipt_pdf import pdf_text
    return parse_items(pdf_text(path), expected_date, expected_total)
