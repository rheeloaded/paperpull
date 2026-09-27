# Code signing

## Status

**macOS is signed and notarized.** The `.dmg` and the app inside it are
signed with the maintainer's Developer ID, notarized by Apple, and stapled,
so they open on any Mac with no warning. Apple Silicon only.

**Windows is signed with Azure Artifact Signing.** From the first release
built after it was set up, the installer and the `PaperPull.exe` inside the
installer, the portable zip and the MSIX are signed with the maintainer's
Artifact Signing certificate and timestamped, so Windows names the publisher
instead of calling it unknown. SmartScreen builds its trust in a publisher
from downloads over time, so a new certificate can still meet its prompt for
a while, and that fades as the signed releases are used. The certificates
Artifact Signing issues last a few days each and are replaced for every
signing, and the timestamp keeps a signature valid after its certificate
has expired.

**The Microsoft Store edition is signed by the Store.** The same build
produces an unsigned `.msix`, and the Store signs it with Microsoft's
certificate on submission, so a Store install shows no warning. That
edition costs $9.99, one time, and is otherwise the same program.

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
3. Between staging and packaging, the workflow signs `PaperPull.exe` with
   Azure Artifact Signing, then builds the zip, the MSIX and the installer
   from the signed stage, and signs the installer. It signs in to Azure
   through OpenID Connect from the repository's `release` environment, so no
   password or key is stored anywhere, and only a workflow run of this
   repository in that environment can ask for a signature. If signing is set
   up and any shipped program comes out unsigned, the job fails.
4. The workflow uploads the signed installer, the portable zip, the MSIX and
   a `SHA256SUMS.txt` taken after signing, as run artifacts.
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

Only this project's own programs, the installer and `PaperPull.exe`, are
signed with its certificate. The upstream components inside keep whatever
signature their publishers gave them.

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
| Approvers | [rheeloaded](https://github.com/rheeloaded) | Push the version tags whose builds are signed, and hold the Azure account that signs them |

Contributors whose providers are in the repository, David Rudnick, David
Riordan and Champ, hold none of these roles. Their work is reviewed and
merged by the maintainer.

All roles use multi-factor authentication for GitHub and for Azure.

## Setting up Windows signing (maintainer, once)

The workflow signs only when the repository is set up for it, and builds
unsigned otherwise, so a fork builds without any of this.

1. In Azure, the Artifact Signing account and a Public Trust certificate
   profile, with the identity validation they need.
2. In Microsoft Entra ID, an app registration for the workflow. On it, a
   federated credential of the GitHub Actions kind for this repository with
   the entity type Environment and the environment name `release`. No client
   secret.
3. On the Artifact Signing account, the role Artifact Signing Certificate
   Profile Signer for that app registration.
4. In the GitHub repository, an environment named `release`, holding the
   secrets `AZURE_CLIENT_ID` (the app registration's client id),
   `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`, and the repository
   variables `ARTIFACT_SIGNING_ENDPOINT` (the account's URI from its
   Overview page, such as `https://eus.codesigning.azure.net/`),
   `ARTIFACT_SIGNING_ACCOUNT` and `ARTIFACT_SIGNING_PROFILE`.
5. Run the Windows package workflow by hand once and check that its step
   named "Check every shipped program is signed" names the certificate.

## Reporting a problem

If a signed binary does not match what this repository builds, or if you
believe a release was signed that should not have been, open an issue or
follow [SECURITY.md](../SECURITY.md).
