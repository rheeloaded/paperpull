# United Airlines receipts

Saves the receipts on a MileagePlus account at united.com into PaperPull's
Receipts folder as PDFs: one for each flight reservation, named by its
confirmation number, and one for each travel option bought separately (a
seat, a bag, an upgrade), named by its receipt number.

1. Open the sign-in window from PaperPull's United page.
2. Sign in to united.com yourself and leave the window open.
3. Choose **Get new documents**.

united.com has no receipt PDF. The app opens the receipts page
(united.com/en/us/receipts), reads the list the page asks for by your
MileagePlus number, and for each receipt presses that row's "View receipt"
the way you would. It reads the receipt United sends back, closes the tab
the page opened, and prints the receipt to a PDF. A reservation for several
travelers has a receipt for each of them, and they are filed together in
one PDF, in United's order. Before saving, it checks that each receipt
prints its confirmation or receipt number and its date of purchase.

"View receipt" and "Load more results" are the only things it presses. It
never presses "Email receipt" and never changes the page's search or filters.
A receipt is filed under the day its tickets were issued, and the date of an
exchange for a ticket that was changed.

united.com refuses requests that do not come from the page itself, so the
app works only through the open receipts page, and it spaces receipts 10 to
20 seconds apart. If united.com starts refusing, the run stops with what it
saved. Wait a while and Resume.

CLI commands on macOS are `paperpull united login`, `paperpull united pilot`,
and `paperpull united all`.
