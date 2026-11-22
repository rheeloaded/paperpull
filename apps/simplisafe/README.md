# SimpliSafe monitoring bills

PaperPull archives bills from **Manage Account → Monitoring Payments** in
the SimpliSafe desktop web app. It renders each invoice view locally as a
PDF after matching the invoice number and date to the history.

1. Open **SimpliSafe Bills** in PaperPull and choose **Open sign-in window**.
2. Sign in to SimpliSafe and leave the Account page open.
3. Use **Try the newest few first** to check a bill, or **Get new documents**
   to archive the history.

Bills are stored in the provider's **Bills** folder. The connector uses the
table's own Next page and Previous page buttons to reach older invoices,
and changes none of SimpliSafe's requests. A page whose rows do not
change after a press, or that disagrees with the invoice count, stops the
run with nothing filed from it.
An offline preview uses the saved discovery list and keeps the previous
download's file list.
