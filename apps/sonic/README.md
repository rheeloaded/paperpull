# Sonic bills

PaperPull saves Sonic internet bill PDFs from Member Tools. It reads the
full list that Sonic shows in **Billing & Payments → View Bill History**,
matches the invoice number in each PDF, and uses the date shown in Sonic's
history for the filename.

1. Open **Sonic Bills** in PaperPull and select **Open sign-in window**.
2. Sign in to Sonic in that window and leave it open.
3. Choose **Get new documents**. The PDFs are saved in **Bills**.

PaperPull retrieves the history and PDFs using the signed-in browser. It
reads only Sonic's Member Tools billing-history page and the exact
invoice links listed there. The connector covers bills in the current
Member Tools history for the signed-in account.

To try one bill first, use **Try the newest few first**. The CLI commands
are `paperpull sonic login`, `paperpull sonic pilot`, and `paperpull sonic all`.
