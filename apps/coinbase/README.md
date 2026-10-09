# Coinbase statement and tax-document downloader

Mapped against a signed-in retail account on 2026-10-09. Read-only, delete-safe, part of PaperPull.
You sign in yourself in the browser PaperPull opens on the port named in config.json (see config.example.json); the tool attaches afterwards and
never handles credentials.

Two document areas, both on accounts.coinbase.com:

- **Monthly statements** (Statements page): one PDF per complete month back to the account's first
  month. The row's own PDF button is pressed once, which makes Coinbase build that month's PDF, and
  the download is taken only from Coinbase's statements S3 host. "Last 30 days" is skipped.
- **Tax documents** (Taxes > Documents): 1099 forms for every year since the first transaction and
  the pregenerated gain/loss PDF reports, read from the page's own list call and fetched from
  Coinbase's tax-forms S3 host. Nothing is pressed there, so the page's own mark-read /
  mark-downloaded calls never happen.

Never touched: the custom statement generator, the tax report generator, anything that trades,
sends, stakes or changes a setting. Tests: `python -m unittest discover -s tests` from this folder
with PaperPull's bundled Python.
