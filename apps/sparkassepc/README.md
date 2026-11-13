# Sparkasse Pforzheim Calw

Downloads existing PDFs offered through the direct download links in the electronic Postfach. It reads the full date range across the pages of Posteingang, Gesendet and Papierkorb. Messages without a direct PDF download are counted and left in the mailbox. Requested in [#175](https://github.com/rheeloaded/paperpull/issues/175).

The app uses CDP port **9316**. Sign in yourself and leave the Postfach open. Clear any search, select Gesamtzeitraum, and clear any selected rows before running.

```sh
./paperpull --root ./apps sparkassepc setup
```

```sh
cp apps/sparkassepc/config.example.json apps/sparkassepc/config.json
```

```sh
./paperpull --root ./apps sparkassepc login
```

```sh
./paperpull --root ./apps sparkassepc discover
```

```sh
./paperpull --root ./apps sparkassepc pilot
```

The direct download keeps the document's unread marker. The app checks that marker before saving. Use `all` for the full scope, `resume` to continue, and `verify` to check saved PDFs. Progress and the document index are kept locally.

On one contributor's account, Discover found 205 PDFs dated from 2019 to 2026.
It reported 13 entries without a direct PDF link. The Pilot saved two distinct
statements and verified both. A second Pilot skipped both files. A full download
and other accounts have yet to be tested.
