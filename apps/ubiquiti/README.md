# Ubiquiti Store receipts

Downloads the receipt PDF of every paid order on the Ubiquiti Store
(store.ui.com) into PaperPull's Receipts folder, one per order, named by its
order number.

1. Open the sign-in window from PaperPull's Ubiquiti page.
2. Sign in to store.ui.com manually (Sign In opens account.ui.com) and leave
   the window open on any store page.
3. Choose **Get new documents**.

The app reads the account's order history the way the store's own Order
History does, then fetches each order's "View Invoice" PDF with the signed-in
browser. Nothing on the page is clicked. Before saving, it checks that the PDF
is a "Receipt / Tax Invoice" printing the order's number and date.

Orders the store shows as Cancelled have only an "Unpaid Invoice", which is not
a receipt, so they are counted and the run says how many, but nothing is saved
for them. Orders from every regional store on the account (US, Canada) are
listed together. Orders of the store's earlier system, if the account has any,
are counted but not saved.

The store limits how quickly receipts may be fetched, so downloads are spaced
a few seconds apart. If it still says "too many requests", the run stops with
what it saved; wait a few minutes and Resume.

CLI commands on macOS are `paperpull ubiquiti login`, `paperpull ubiquiti pilot`,
and `paperpull ubiquiti all`.
