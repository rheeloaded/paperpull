# Docker's default security profile

`moby-default.json` is Docker's default seccomp profile, unchanged, as
released by the moby/profiles project.

| | |
|---|---|
| Project | [moby/profiles](https://github.com/moby/profiles), the profiles Docker Engine uses |
| File | `seccomp/default.json` |
| Release | `seccomp/v0.2.4`, commit `245180c51918481c0525424b3ee025d2b435d46c` |
| SHA-256 | `785b2429264afba4d594320337cb17f144f3c7d51585f9805eef72e28f4f9334` |
| License | Apache License 2.0, in [LICENSE-APACHE-2.0](LICENSE-APACHE-2.0) |

PaperPull Server's profile, `../seccomp-chrome.json`, is made from it by
`../seccomp.py`, which allows the two system calls Chrome's sandbox needs and
changes nothing else. That file is a modified version of this one.

To take a newer release, replace `moby-default.json` with it, update the
table above, run `python server/seccomp.py --write`, and read the
difference before committing it. `seccomp.py` refuses a profile laid out
differently from the one it was written against, rather than guess.
