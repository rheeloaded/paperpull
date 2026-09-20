# Code signing

## Status

**macOS is signed and notarized.** The `.dmg` and the app inside it are
signed with the maintainer's Developer ID, notarized by Apple, and stapled,
so they open on any Mac with no warning. Apple Silicon only.

**Windows is not yet signed.** An application to
[SignPath Foundation](https://signpath.org), which provides free code signing
certificates to open-source projects, is in progress. Until it is granted,
Windows shows its SmartScreen prompt the first time the installer runs, and
the release notes say so. When it is granted this page and the README will
carry the attribution SignPath asks for.

**The Microsoft Store edition is signed by the Store.** The same build
produces an unsigned `.msix`, and the Store signs it with Microsoft's
certificate on submission, so a Store install shows no warning. That
edition costs $2.99 and is otherwise the same program.

## How a release is built

Nothing that ships is built on a developer's machine.

1. A maintainer pushes a version tag (`v0.19.0`, say) to this repository.
2. The [Windows package](../.github/workflows/build-windows.yml) workflow
   runs on a clean GitHub-hosted Windows runner. It checks out that exact
   commit, downloads the official embeddable CPython from python.org,
   installs the project's dependencies from PyPI, stages only the files git
   tracks, refuses to continue if any config, download history, browser
   profile or PDF is found in the stage, runs a smoke test under the packaged
   interpreter, and compiles the installer with Inno Setup.
3. The workflow uploads the unsigned installer, the portable zip and a
   `SHA256SUMS.txt` as run artifacts.
4. Once signing is active, the workflow hands the installer to SignPath. A
   person listed as an Approver below reviews and approves the signing
   request. SignPath verifies the artifact came from this repository's
   workflow before it signs anything.
5. The [macOS package](../.github/workflows/build-macos.yml) workflow runs
   on a clean GitHub-hosted Apple Silicon runner on the same tag. It builds
   the bundle from the same commit, signs every binary in it with the
   Developer ID certificate held in the repository's secrets, sends the
   bundle to Apple for notarization, staples the ticket, then does the same
   for the disk image. The certificate lives in a keychain that exists only
   for that job and is deleted when it ends.
6. A maintainer attaches the artifacts to the GitHub release by hand. No
   step in the workflow publishes on its own.

Anyone can rebuild the package themselves with
`python packaging/build_windows.py --installer` and compare checksums.

## What is inside the package, and who wrote it

Everything in the installer is either this project's own source, the
official CPython build (signed by the Python Software Foundation), or an
open-source Python package installed from PyPI at build time. The packages
are listed in `packaging/build_windows.py`. There is no proprietary code and
nothing that is not also in this repository or on PyPI.

Only this project's own installer is signed. The upstream components inside
it keep whatever signature their publishers gave them.

## Privacy

The policy is [PRIVACY.md](../PRIVACY.md). In one sentence, this program does
not transfer any information to other networked systems unless specifically
requested by the user.

Concretely, the only sites it contacts are the providers a user signs in to
themselves, and only when the user starts a run. It does not phone home,
check for updates, or send telemetry. The one download it may offer is a
browser, at sign-in time, only if no usable browser is already on the
machine, and only after the user agrees on screen. Everything it saves stays
on the user's own computer.

## Team

PaperPull is maintained by one person. Contributed providers arrive as pull
requests and are reviewed before they merge. Branch protection on `main`
requires a pull request.

| Role | Who | What it means |
|------|-----|---------------|
| Authors | [rheeloaded](https://github.com/rheeloaded) | May change source code without a separate review |
| Reviewers | [rheeloaded](https://github.com/rheeloaded) | Review every change from anyone who is not an Author before it merges |
| Approvers | [rheeloaded](https://github.com/rheeloaded) | Decide whether a given release may be signed |

Contributors whose providers are in the repository, David Rudnick, David
Riordan and Champ, hold none of these roles. Their work is reviewed and
merged by the maintainer.

All roles use multi-factor authentication for GitHub and, once active, for
SignPath.

## Reporting a problem

If a signed binary does not match what this repository builds, or if you
believe a release was signed that should not have been, open an issue or
follow [SECURITY.md](../SECURITY.md).
