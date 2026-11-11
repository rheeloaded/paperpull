# Code signing

## Status

**macOS is signed and notarized.** The `.dmg` and the app inside it are
signed with the maintainer's Developer ID, notarized by Apple, and stapled,
so they open on any Mac with no warning. There is one for Apple Silicon
and one for Intel.

**Windows is signed with Azure Artifact Signing.** From the first release
built after it was set up, the installer and the `PaperPull.exe` inside the
installer, the portable zip and the MSIX are signed with the maintainer's
Artifact Signing certificate and timestamped, so Windows names the publisher
instead of calling it unknown. The bundled Python's own programs and
libraries are signed the same way, from the first release built on
python-build-standalone. SmartScreen builds its trust in a publisher
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
   commit, downloads CPython from python-build-standalone and checks it
   against the SHA-256 its publisher lists, installs the project's
   dependencies from PyPI with pip checking every file against the hash in
   the lock, stages only the files git tracks, refuses to continue if any
   config, download history, browser profile or PDF is found in the stage,
   runs a smoke test under the packaged interpreter that also asks it which
   Python it is, and compiles the installer with Inno Setup.
3. Between staging and packaging, the workflow signs `PaperPull.exe` and
   the bundled Python's own programs and libraries with Azure Artifact
   Signing, then builds the zip, the MSIX and the installer from the signed
   stage, and signs the installer. It signs in to Azure through OpenID
   Connect from the repository's `release` environment, so no password or
   key is stored anywhere, and only a workflow run of this repository in
   that environment can ask for a signature. If signing is set up and any
   file it signs comes out unsigned, or any program or library of the
   bundled Python is left without a valid signature, the job fails.
4. The workflow uploads the signed installer, the portable zip, the MSIX and
   a `SHA256SUMS.txt` taken after signing, as run artifacts.
5. The [macOS package](../.github/workflows/build-macos.yml) workflow runs
   on the same tag, twice side by side, on a clean GitHub-hosted Apple
   Silicon runner for the arm64 dmg and an Intel one for the x86_64 dmg.
   Each builds the bundle from the same commit, signs every binary in it
   with the Developer ID certificate held in the repository's secrets,
   sends the bundle to Apple for notarization, staples the ticket, then does the same
   for the disk image. The certificate lives in a keychain that exists only
   for that job and is deleted when it ends. The Python inside the bundle
   is checked against the SHA-256 its publisher lists before it is used,
   and its packages against the hashes in the Mac lock.
6. A maintainer runs `tools/release.sh`, which waits for a passing Tests
   run of the tag's own commit, takes only package runs built from that
   commit, checks each artifact against the checksums its run published,
   and makes the GitHub release only when every download is there. No step
   in the workflow publishes on its own. Every action a workflow runs is
   named by its full commit, so nobody can change one by moving its tag.

Anyone can rebuild the package themselves with
`python packaging/build_windows.py --installer` and compare checksums.

## What is inside the package, and who wrote it

Everything in the installer is either this project's own source, CPython
as python-build-standalone builds it from the Python Software Foundation's
source, or an open-source Python package installed from PyPI at build time.
The packages are pinned in `packaging/requirements.in`, and
`packaging/lock.py` writes the lock for each system and architecture,
`packaging/requirements-windows-x64.txt` and the rest, with the hash of
every file. There is no proprietary code and nothing that is not also in
this repository, on PyPI or in python-build-standalone's releases.

This project's certificate signs its own programs, the installer and
`PaperPull.exe`, and the bundled Python's own programs and libraries,
`python.exe`, `pythonw.exe`, `python312.dll`, `python3.dll` and the files
in `python\DLLs`. python-build-standalone does not sign those, where the
builds from python.org came signed by the Python Software Foundation, and
Windows features such as Smart App Control trust a signed file more
readily. The archive they come in is checked against its pinned SHA-256,
the build records the SHA-256 of each of these files as the archive held
it, and the workflow signs them only while every one still matches its
record, so the signature goes on exactly the files python-build-standalone
published. Everything else keeps whatever
signature its publisher gave it. The Visual C++ runtime DLLs keep
Microsoft's, and the packages installed from PyPI, with their small
launchers in `python\Scripts`, carry their own or none.

## Privacy

The policy is [PRIVACY.md](../PRIVACY.md). In one sentence, this program does
not transfer any information to other networked systems unless specifically
requested by the user.

Concretely, the only sites it contacts are the providers a user signs in to
themselves, and only when the user starts a run. It does not phone home or
send telemetry. It asks GitHub whether a newer version exists only when the
user has turned that check on in Settings and then presses the button for
it, and never at launch or in the background. The one other download it may
offer is a browser, at sign-in time, only if no usable browser is already on
the machine, and only after the user agrees on screen. Everything it saves stays
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
   secrets `AZURE_CLIENT_ID` (the app registration's client id) and
   `AZURE_TENANT_ID`, and the repository
   variables `ARTIFACT_SIGNING_ENDPOINT` (the account's URI from its
   Overview page, such as `https://eus.codesigning.azure.net/`),
   `ARTIFACT_SIGNING_ACCOUNT` and `ARTIFACT_SIGNING_PROFILE`.
5. Run the Windows package workflow by hand once and check that its step
   named "Check every shipped program is signed" names the certificate.

## Reporting a problem

If a signed binary does not match what this repository builds or the
CPython archive it pins (the signature aside), or if you
believe a release was signed that should not have been, open an issue or
follow [SECURITY.md](../SECURITY.md).
