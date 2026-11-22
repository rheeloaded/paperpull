# Mercury statements

PaperPull archives monthly deposit statements from the selected Mercury
organization. It reads the Checking and Savings statements displayed in
Documents & Data and verifies the account suffix and statement period
inside each PDF before saving it in Statements.

1. Open Mercury Statements in PaperPull and choose **Open sign-in window**.
2. Sign in to Mercury and select the organization you want to archive.
3. Keep the window open, then choose **Get new documents** in PaperPull.
   The connector opens **Documents & Data → Statements**. Use Mercury's
   **All** filter to see statements across deposit accounts.
4. To keep organizations in separate local folders, use PaperPull's
   **More → Add another person** for each additional organization.

The connector processes monthly deposit PDFs for the organization and
filters visible in the browser. It recognizes Checking and Savings rows
with a displayed account suffix. A row of another kind of account it
does not know, an empty table, or a list shown a page at a time stops the
run, so nothing is left out quietly. For Mercury IO credit statements, sweep
summaries, tax documents, or custom date exports, use Mercury's portal.
