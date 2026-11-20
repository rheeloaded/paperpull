# Starlink Invoices

Archive PDFs from Starlink's US English Billing → Invoices page. Sign in manually in PaperPull's dedicated browser window. Discovery reads each invoice page using the Invoices pager, and the connector saves a PDF only when the invoice number and issue date match its row. The PDFs go in `Bills` under the configured output folder.

In PaperPull, open **Starlink Invoices**, choose **Sign in**, and then choose **Get Documents**. A completed invoice is skipped on later runs. For a quick verification from the command line, run `paperpull starlink discover` followed by `paperpull starlink pilot`.

The connector reads the invoice grid and requests the same invoice PDF shown by the site's **Invoice PDF** link. It does not use the Payments grid or change billing settings.
