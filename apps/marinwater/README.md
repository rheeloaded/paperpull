# Marin Water bills

Downloads water bill PDFs from [Marin Water’s Paymentus portal](https://ipn4.paymentus.com/cp/mwdc) for one account.

## Use it

1. Add **Marin Water** in PaperPull and choose **Open sign-in window**.
2. Sign in to Paymentus yourself and leave the account tab open.
3. Choose **Try the newest few first** to check a sample, then **Get new documents** to save the available history.

From a source checkout, run `./setup-all.command` on macOS or `setup-all.bat` on Windows. The equivalent commands are `paperpull marinwater login`, `paperpull marinwater pilot`, and `paperpull marinwater all`. Use `./paperpull` on macOS.

## How it works

The connector reads the signed-in tab’s **View Bill History** link and requests the account’s bill table from inside the tab. Each row uses the portal’s bill date and its own **View Bill** link. PDFs come from the allowlisted DataProse viewer in a separate request context. Paymentus cookies and signed PDF links stay out of the archive records.

When several rows share a bill date, the connector identifies each PDF by its SHA-256 fingerprint. It checks that fingerprint again before saving and uses a short suffix when a filename would collide. Identical PDF copies count as one bill. If a previously archived date-only bill cannot be matched to a PDF in the history, use **Restore deleted files** for that date to save the identified PDFs while preserving the old record.

The connector only reads history and downloads bills. You handle sign-in and verification in the browser. Tested on a contributor account, including separate PDFs sharing one bill date and a fresh discovery with reissued links.

## Tests

Run `python -m pytest apps/marinwater/tests` from the repository root with the PaperPull test environment active. The tests use synthetic history and PDF data.
