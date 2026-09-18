"""The Windows package as an MSIX, for the Microsoft Store.

    python packaging/build_windows.py --msix

WHAT IT PRODUCES

    dist\\PaperPull-<ver>.msix      unsigned. The Store signs it on submission.

HOW IT DIFFERS FROM THE INSTALLER

Same folder, different wrapper. The Inno installer copies the folder into
Local AppData and makes shortcuts. The MSIX declares the same folder as a
full-trust desktop app, and Windows installs it read-only under
WindowsApps, signs it with Microsoft's certificate on the way through the
Store, and updates it from there. No SmartScreen, no certificate of ours.

Two things had to be true of the folder first, and are. Nothing writes
into it at run time (bytecode goes to the user's temp folder, settings to
Roaming AppData), and the entry point is a real executable, because a
manifest cannot name a .bat. PaperPull.exe is a few lines of C# compiled
with the csc.exe that every Windows has, and it does what PaperPull.bat
does. Start the panel, open the browser to it, wait.

IDENTITY

The Store assigns the package identity when the app name is reserved in
Partner Center. Until then the manifest carries placeholders, which is
enough to build and sideload for testing. MSIX_IDENTITY_NAME,
MSIX_PUBLISHER and MSIX_PUBLISHER_DISPLAY in the environment override them,
and the workflow sets them from repository variables once they exist.

The version is the repo's, with a fourth part added and any prerelease
suffix dropped, because the Store wants exactly four numbers.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Placeholders. Partner Center replaces all three when the name is reserved.
DEFAULT_IDENTITY_NAME = "RheeLoaded.PaperPull"
DEFAULT_PUBLISHER = "CN=PaperPull Local Build"
DEFAULT_PUBLISHER_DISPLAY = "PaperPull"
# The app's display name must match a name reserved in Partner Center,
# spelling and case included. MSIX_DISPLAY_NAME overrides it if the reserved
# spelling differs.
DEFAULT_DISPLAY_NAME = "PaperPull"

# Store image assets. Name, size at scale-100. Each is also written at
# scale-200 for high-DPI screens.
ASSETS = {
    "Square44x44Logo": (44, 44),
    "Square150x150Logo": (150, 150),
    "Wide310x150Logo": (310, 150),
    "StoreLogo": (50, 50),
}


def store_version(v: str) -> str:
    """0.19.0 -> 0.19.0.0, 0.19.0-beta.2 -> 0.19.0.0, 1.2 -> 1.2.0.0"""
    m = re.match(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?", v)
    if not m:
        raise SystemExit("VERSION %r does not start with a number" % v)
    parts = [int(x or 0) for x in m.groups()]
    return ".".join(str(p) for p in parts)


def identity() -> dict:
    return {
        "name": os.environ.get("MSIX_IDENTITY_NAME") or DEFAULT_IDENTITY_NAME,
        "publisher": os.environ.get("MSIX_PUBLISHER") or DEFAULT_PUBLISHER,
        "display": os.environ.get("MSIX_PUBLISHER_DISPLAY") or DEFAULT_PUBLISHER_DISPLAY,
        "app": os.environ.get("MSIX_DISPLAY_NAME") or DEFAULT_DISPLAY_NAME,
    }


def manifest(version: str, ident: dict) -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap10 rescap">

  <Identity Name="{name}" Publisher="{publisher}" Version="{version}" ProcessorArchitecture="x64" />

  <Properties>
    <DisplayName>{app}</DisplayName>
    <PublisherDisplayName>{display}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
    <Description>Downloads your own receipts and statements as PDFs from the banks, utilities and stores you already use. You sign in yourself, and it can only read.</Description>
  </Properties>

  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.22631.0" />
  </Dependencies>

  <Resources>
    <Resource Language="en-us" />
  </Resources>

  <Applications>
    <Application Id="PaperPull" Executable="PaperPull.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="{app}"
        Description="Receipt and statement downloader. Read-only, runs on this computer."
        BackgroundColor="transparent"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" />
      </uap:VisualElements>
    </Application>
  </Applications>

  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
""".format(version=version, **ident)


LAUNCHER_CS = r'''// PaperPull.exe. What PaperPull.bat does, as an executable, because an
// MSIX manifest cannot name a batch file. Start the panel under the
// packaged Python, open the browser to it, wait. Closing this window or
// pressing Ctrl+C stops the panel with it.
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

static class PaperPull
{
    static int Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string version = "";
        try { version = File.ReadAllText(Path.Combine(dir, "VERSION")).Trim(); } catch { }
        Console.WriteLine("PaperPull " + version);
        Console.WriteLine("The panel binds 127.0.0.1 only. Nothing is reachable from the network.");
        Console.WriteLine("Close this window to stop it.");
        Console.WriteLine();

        // PAPERPULL_PORT lets a second copy, or a test, run beside one that
        // already holds 8765.
        string port = Environment.GetEnvironmentVariable("PAPERPULL_PORT");
        if (string.IsNullOrEmpty(port)) port = "8765";

        var psi = new ProcessStartInfo(
            Path.Combine(dir, "python", "python.exe"),
            "-m uvicorn app:app --host 127.0.0.1 --port " + port + " --app-dir \"" + Path.Combine(dir, "gui") + "\"");
        psi.UseShellExecute = false;
        psi.WorkingDirectory = dir;
        Process panel;
        try { panel = Process.Start(psi); }
        catch (Exception e)
        {
            Console.WriteLine("Could not start the packaged Python: " + e.Message);
            return 1;
        }

        Thread.Sleep(2000);
        try
        {
            var open = new ProcessStartInfo("http://127.0.0.1:" + port);
            open.UseShellExecute = true;
            Process.Start(open);
        }
        catch { }

        panel.WaitForExit();
        return panel.ExitCode;
    }
}
'''


def find_csc() -> Path | None:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for arch in ("Framework64", "Framework"):
        cands = sorted((windir / "Microsoft.NET" / arch).glob("v4*/csc.exe"), reverse=True)
        if cands:
            return cands[0]
    return None


def compile_launcher(stage: Path, icon: Path | None, say) -> bool:
    csc = find_csc()
    if csc is None:
        say("  csc.exe not found, PaperPull.exe not built (the .bat still works)")
        return False
    src = stage.parent / "cache" / "launcher.cs"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(LAUNCHER_CS, encoding="utf-8")
    args = [str(csc), "/nologo", "/target:exe", "/optimize+",
            "/out:" + str(stage / "PaperPull.exe")]
    if icon and icon.is_file():
        args.append("/win32icon:" + str(icon))
    args.append(str(src))
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("PaperPull.exe did not compile:\n" + r.stdout + r.stderr)
    say("  PaperPull.exe")
    return True


def write_assets(dest: Path, png256: bytes, say) -> None:
    """Every size the Store wants, resized from the 256px icon by the
    System.Drawing that ships with Windows PowerShell. No Pillow needed."""
    dest.mkdir(parents=True, exist_ok=True)
    src = dest.parent / "icon-256.png"
    src.write_bytes(png256)
    jobs = []
    for name, (w, h) in ASSETS.items():
        # The plain name is what the manifest references and what Windows
        # finds without a resources.pri. The scale-200 twin is picked up by
        # the same lookup on high-DPI screens.
        jobs.append((dest / (name + ".png"), w, h))
        jobs.append((dest / (name + ".scale-200.png"), w * 2, h * 2))
    script = ["Add-Type -AssemblyName System.Drawing",
              "$src = [System.Drawing.Image]::FromFile('%s')" % src]
    for out, w, h in jobs:
        # Square sizes scale the icon to fit. The wide tile centres it on a
        # transparent canvas, which is what the Store's wide tile expects.
        side = min(w, h)
        script.append(
            "$bmp = New-Object System.Drawing.Bitmap %d, %d; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            "$g.Clear([System.Drawing.Color]::Transparent); "
            "$g.InterpolationMode = 'HighQualityBicubic'; "
            "$g.DrawImage($src, [int](%d), [int](%d), %d, %d); "
            "$g.Dispose(); $bmp.Save('%s', [System.Drawing.Imaging.ImageFormat]::Png); "
            "$bmp.Dispose()" % (w, h, (w - side) // 2, (h - side) // 2, side, side, out))
    script.append("$src.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "; ".join(script)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("could not render the Store assets:\n" + r.stderr[-1500:])
    src.unlink()
    say("  %d Store images" % len(jobs))


def find_makeappx() -> Path | None:
    for base in (r"C:\Program Files (x86)\Windows Kits\10\bin",
                 r"C:\Program Files\Windows Kits\10\bin"):
        cands = sorted(Path(base).glob("10.*/x64/makeappx.exe"), reverse=True)
        if cands:
            return cands[0]
    return None


def pack(stage: Path, dist: Path, version_str: str, png256: bytes, say) -> Path | None:
    """Stage the folder again with a manifest and assets beside it, and pack.
    Returns the .msix path, or None when makeappx is not on this machine."""
    say("MSIX")
    if not (stage / "PaperPull.exe").is_file():
        raise SystemExit("PaperPull.exe is missing, so there is nothing for the manifest to name")
    ident = identity()
    ver = store_version(version_str)
    if ver != version_str + ".0":
        say("  version %s becomes %s (four numbers, no suffix)" % (version_str, ver))
    root = dist / "msix"
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(stage, root)
    # The installer's own launcher and readme have no place in a Store
    # package. The exe and the code are what ship.
    for extra in ("PaperPull.bat", "README-FIRST.txt"):
        p = root / extra
        if p.exists():
            p.unlink()
    (root / "AppxManifest.xml").write_text(manifest(ver, ident), encoding="utf-8")
    write_assets(root / "Assets", png256, say)
    say("  identity %s, publisher %s" % (ident["name"], ident["publisher"]))

    makeappx = find_makeappx()
    if makeappx is None:
        say("  makeappx.exe (Windows SDK) not found. The folder is ready at dist\\msix,")
        say("  the package was not built.")
        return None
    out = dist / ("PaperPull-%s.msix" % version_str)
    if out.exists():
        out.unlink()
    r = subprocess.run([str(makeappx), "pack", "/o", "/d", str(root), "/p", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("makeappx failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    say("  %s  %.1f MB, unsigned" % (out.name, out.stat().st_size / 1048576))
    return out
