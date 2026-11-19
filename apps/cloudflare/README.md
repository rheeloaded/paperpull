# Cloudflare invoices

Downloads invoice PDFs from the selected Cloudflare account into PaperPull's
Invoices folder.

1. Open the sign-in window from PaperPull's Cloudflare account page.
2. Sign in manually and select the Cloudflare account to archive.
3. Leave **Manage Account → Billing → Invoices and documents** open.
4. Choose **Get new documents**. PaperPull identifies each invoice separately,
   including invoices from the same day.

The connector reads the account's paginated invoice history using the signed-in
browser. It verifies the invoice number and date in the PDF before saving it.
This connector supports the dashboard's Stripe-backed invoice PDFs.

CLI commands on macOS are `paperpull cloudflare login`, `paperpull cloudflare pilot`,
and `paperpull cloudflare all`.
