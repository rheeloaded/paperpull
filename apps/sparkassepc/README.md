# Sparkasse Pforzheim Calw

Downloads the PDFs Sparkasse Pforzheim Calw already holds in its electronic
Postfach, the ones it offers as a direct download. Requested in
[#175](https://github.com/rheeloaded/paperpull/issues/175) and contributed by
[@MelleD](https://github.com/MelleD) in
[#216](https://github.com/rheeloaded/paperpull/pull/216). Its CDP port is 9316.

**Run on the contributor's own account.** Discover read the history of
Posteingang, Gesendet and Papierkorb, back to 2019, and counted the
messages with no direct PDF. A Pilot saved two statements, both verified,
and a second Pilot saved nothing new. A whole run has not been reported yet.
The page turns and the download press were reworked before merging (below)
and have not been run against the bank since.

## Commands in a checkout

`--root ./apps` picks the app in this checkout even when the panel is set
to use another install folder.

```sh
./paperpull --root ./apps sparkassepc setup
cp apps/sparkassepc/config.example.json apps/sparkassepc/config.json
./paperpull --root ./apps sparkassepc login
```

Sign in yourself, answer your own prompts, and leave the window open. Clear
any search in the Postfach and select Gesamtzeitraum before running.

```sh
./paperpull --root ./apps sparkassepc discover
./paperpull --root ./apps sparkassepc pilot
./paperpull --root ./apps sparkassepc all
```

Check the Pilot's PDFs first. Resume carries on with a run that stopped,
and Verify checks the saved PDFs on this computer. Progress and the
document index are kept on this computer.

## How it reads documents

The Postfach is read in your signed-in tab, as its pages show it. With no
tab of yours on the bank's site, the app opens the Postfach in a tab of its
own, which shares your session.

- Each folder, Posteingang, Gesendet and Papierkorb, is opened afresh by its
  own link and read from its first page to its last. A page is turned only
  by pressing the Postfach's own numbered page button, the press you would
  make, and read once it shows that page number. Page turns wait the same
  pause the config sets between documents.
- A row that offers no direct PDF download, a message with only text say,
  is counted, said and left in the Postfach.
- A document is known by its row's own identity, kept only as a digest, so
  a list in another order or two documents alike never swap their files.
- A document's PDF comes from pressing that row's own direct download link,
  the link known by its class and by its address in the folder, never by
  the subject it shows. The bank prepares the download, and the step that
  would take the tab to the PDF service is held so the tab stays where it
  is. That one PDF is then asked for once from inside the tab.
- Whether the bank marks a document read when its PDF is taken has not
  been checked. The run never stops for it.

Nothing else is pressed. The app never sends a form of its own, never
moves money and never changes a setting.

## When it stops rather than guess

A part of the list that is missing stops the listing, never reads as the
end of it. That is a pager missing from a full page or from a folder turned
past its first page, a page number that cannot be read, a row with more
than one direct download, a downloadable row with no identity, and rows
listed with no direct download anywhere. A Postfach of one short page with
no pager is listed as it is. A row ticked in the Postfach stops a page
turn, since the press would send it too. A sign-in page in place of the
list stops the run as signed out, and so does one in place of a PDF once
the folder, asked for again, answers signed out. A document the bank gives
no PDF for, while the list still answers, fails alone and the run goes on.
