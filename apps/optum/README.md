# Optum Bank HSA statement and tax-form downloader

Mapped against a signed-in account on 2026-10-09. Read-only, delete-safe, part of PaperPull. You
sign in yourself (HealthSafe ID) in the browser PaperPull opens on port 9291; the tool attaches
afterwards and never handles credentials.

Nothing is ever clicked. Statements and tax forms are plain links on the member site,
account.optumbank.com: the six newest statements are links, the older ones are the options of the
page's date selector, and tax forms (5498-SA, and the 1099-SA in a year with distributions) are links
on the same page. Each is fetched by its own address with the signed-in session.

Never touched: payments, reimbursements, contributions, investments, cards, claims, beneficiaries,
settings, the HSA forms (rollover, correction, closure...). Tests: `python -m unittest discover -s
tests` from this folder with PaperPull's bundled Python.
