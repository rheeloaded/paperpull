# AliExpress receipts and seller tax invoices

Saves, for every AliExpress order:

- **the order's receipt**, the page AliExpress shows under **Receipt** on an
  order (order ID and time, subtotal, discounts, shipping, tax, total, the
  shipping address, the masked card, the items and the seller), printed to PDF
  into **Receipts**. AliExpress's own Download button on that page makes a
  PNG image, so PaperPull prints the page instead;
- **the seller's sales-tax invoice**, and for a cancelled or expired order the
  **credit note** that reverses it, the PDFs AliExpress issues under
  **Download invoice**, into **Seller Tax Invoices**. Their amounts are in CNY.

1. Open the sign-in window from PaperPull's AliExpress page.
2. Sign in to AliExpress yourself, clearing any slider or code check, and leave
   the window open.
3. Choose **Get new documents**.

PaperPull works in a tab of its own. It reads the order list the way the
Orders page does, pressing only **View orders** to load more, and asks for each
order's receipt and invoices with the page's own requests. Every PDF is checked
before it is saved: a receipt for its order ID, date and total, an invoice or
credit note for its heading, its invoice number and the order it belongs to.

An invoice the seller has not issued yet is counted and said, not saved, and
PaperPull never asks a seller for one. An order too old for AliExpress's
receipt page (one from 2020 had none) is counted and said too.

If AliExpress asks for a slider or puzzle check, the run stops with what it
saved. Clear the check in the browser and Resume.

CLI commands on macOS are `paperpull aliexpress login`,
`paperpull aliexpress pilot`, and `paperpull aliexpress all`.
