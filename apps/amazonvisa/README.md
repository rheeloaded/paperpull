# Amazon Visa

Downloads card statement PDFs and other PDFs from the [Amazon Visa portal](https://kunden.openbankpay.com/amazon/login). It reads the statement history for each visible card contract and the documents in each category the portal lists. Requested in [#171](https://github.com/rheeloaded/paperpull/issues/171).

The template uses CDP port **9315**.

## Sign in and download

Run the following commands from the PaperPull checkout. Run setup once with Python 3.11 or later, then create your local config.

```sh
./paperpull --root ./apps amazonvisa setup
```

```sh
cp apps/amazonvisa/config.example.json apps/amazonvisa/config.json
```

```sh
./paperpull --root ./apps amazonvisa login
```

Sign in yourself and leave the Amazon Visa window open. To check the list and save the newest few PDFs:

```sh
./paperpull --root ./apps amazonvisa discover
```

```sh
./paperpull --root ./apps amazonvisa pilot
```

Use `all` for a full download, `resume` to continue an interrupted run, and `verify` to recheck saved files. The local `config.json` controls the output folder and document types. The index and progress file let later runs skip PDFs already saved.

## What it reads

PaperPull uses the portal's own signed-in client for read requests. It keeps the session and signed PDF links inside the page. PDFs are fetched from the portal's document store and saved locally. Documents without a PDF and other file types are reported and skipped.

On one contributor's account, Discover listed 28 distinct PDFs, including 26 card statements. Trial downloads saved three statements, one contract and one other PDF. All five passed verification, and repeating the statement download saved no duplicates. A full download and additional accounts have yet to be tested.
