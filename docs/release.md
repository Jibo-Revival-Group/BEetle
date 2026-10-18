# Build native BEetle applications

The release adapters are based on Jibo-DFU-Mod-Toolkit revision
`8f757eedd7cec108508b306b2eb123d5646a354a`. They freeze Python, Tk, Paramiko
and its dependencies, USB tools, ext4 tools, and the pinned RAM recovery loader.
PM remains external: no PM shell script is bundled or translated into installer
commands.

| Build host | Output in `release-out/` |
| --- | --- |
| Linux x86_64 (Ubuntu 22.04 baseline) | `BEetle-Linux-x86_64.AppImage` |
| macOS 15, Apple silicon | `BEetle-macOS-arm64.app.zip` containing `BEetle.app`, plus a DMG |
| macOS 15, Intel | `BEetle-macOS-x86_64.app.zip` containing `BEetle.app`, plus a DMG |
| Windows 11 x64 | `BEetle-Windows-x64.exe` |

Build each target on its native OS and architecture. PyInstaller does not
cross-compile these formats. Separate Mac builds support Intel and Apple
silicon. The Mac app has no Developer ID signature or notarization; the Windows
executable has no publisher signature. The bundled Zadig driver utility retains its original publisher signature.

## GitHub Actions

The manual **BEetle native bundles** workflow builds all four targets, runs
artifact self-checks and GUI smoke checks, and uploads downloadable workflow
artifacts. It does not create a release, publish files, or push source changes.
The Linux job builds the payload used inside the Windows executable.

## Local Linux build

Use a Linux x86_64 build machine with Python 3.12 and Tk installed. Ubuntu 22.04
provides the oldest glibc baseline used by this workflow. Build-time prerequisites:

```sh
sudo apt-get update
sudo apt-get install -y python3-venv python3-tk libusb-1.0-0-dev gcc-arm-none-eabi binutils-arm-none-eabi pkg-config libfuse2 xvfb patchelf
python3.12 -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements-release.txt
.build-venv/bin/python scripts/release/build.py
```

Your Python 3.12 must include a working `tkinter`; installing the system
`python3-tk` alone does not add Tk to an unrelated Python installation.
The builder downloads checksum-pinned tool sources, builds the native USB and
filesystem tools, freezes the application, hides the dependency build prefix,
and verifies the resulting payload before making an AppImage.

```sh
chmod +x release-out/BEetle-Linux-x86_64.AppImage
release-out/BEetle-Linux-x86_64.AppImage
# On systems without FUSE:
release-out/BEetle-Linux-x86_64.AppImage --appimage-extract-and-run
```

USB access may require the desktop administrator prompt or launch from a
terminal with sudo. That host permission does not bypass robot write reviews.

## Local macOS build

On the target Mac, install Xcode Command Line Tools, then:

```sh
brew install --overwrite python@3.12 python-tk@3.12 pkg-config
"$(brew --prefix python@3.12)/bin/python3.12" -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements-release.txt
.build-venv/bin/python scripts/release/build.py --architecture arm64
# Use --architecture x86_64 on an Intel Mac.
```

The app bundles the tools and interpreter. End users do not need Homebrew.
The builder audits Mach-O dependencies for accidental build-machine references,
checks the app signature, and tests GUI startup. Unzip the app ZIP or open the
DMG and copy `BEetle.app` to Applications.

## Local Windows build and portability

The independent **BEetle native Windows** workflow builds and uploads the EXE
without waiting for Linux or macOS. **BEetle native bundles** also includes this
native job. Download its `BEetle-Windows-x64` artifact after the checks pass.
There is no Linux payload, WSL image, USB sharing service or virtualization setup.

For a local Windows build, install Python 3.12 x64 and a **build-only** Cygwin root
with `gcc-core make binutils git patch pkg-config mingw64-x86_64-gcc-core`.
The workflow uses the official Cygwin installation action. Then run:

```powershell
python -m venv .build-venv
.build-venv\Scripts\python -m pip install -r requirements-release.txt
.build-venv\Scripts\python scripts/release/build.py --windows-native --cygwin-root C:/cygwin
```

The EXE contains native Windows Python/Tk, SSH dependencies, the pinned recovery
payloads, native libusb, ShofEL/dfu-util, ext4 EXEs and their required DLLs. A small
Cygwin compatibility DLL travels beside helpers inside the extracted bundle; no
Cygwin installation or shell is required on the user's PC. This is user-space
Windows code, not a virtual machine. Every helper's PE DLL imports are traversed;
missing non-system libraries fail the build. Matching source packages and
notices accompany the binaries. The signed Zadig utility is checksum-pinned;
its libusbK/libusb-win32 sources accompany the release as well.

The only persistent host change users may need is the Jibo USB driver, installed
explicitly from **Help → Windows USB driver setup…**. The included utility defaults
to libusbK and excludes hubs. Users review the device (`0955:7740` or `0955:701a`)
and approve Windows elevation. BEetle does not silently change USB drivers.
WinUSB cannot carry Jibo's oversized RCM control request; use libusbK.

Windows backups are ordinary files under `%USERPROFILE%\Jibo-Backups`. Existing
backups inside a legacy WSL installation remain there: retain or copy them before
removing any distribution. `run-wsl.ps1` and the explicit `--windows-payload`
legacy builder remain available for existing installations; they are not called
by the normal Windows launch or build path.

Robot setup still downloads external PM over SSH using the same four commands.
The host bundle does not embed PM or change the OOBE/provisioned selection.

## Verification and distribution

```sh
BEetle-Linux-x86_64.AppImage --appimage-extract-and-run --self-check
BEetle.app/Contents/MacOS/BEetle --self-check
```

```powershell
.\BEetle-Windows-x64.exe --self-check --output check.txt
```

Self-checks do not write to a robot. Native checks cover the manifest, Tcl,
Paramiko, USB/filesystem tool startup, the GUI flow loader and the frozen
pipeline subprocess on Linux/macOS. Windows checks the native helper EXEs,
libusb DLL and private GUI flow loader. `--gui-smoke` opens a synthetic first
window without USB access. Windows `--filesystem-smoke` creates a disposable ext4
image in a path containing spaces and Unicode, edits/readbacks a file, checks
ext4, resizes it and checks again. These diagnostics install nothing.

Distribute the generated corresponding-source archive(s), `LICENSE`, and
`THIRD-PARTY-NOTICES.md` alongside binaries. Runtime licenses and source
snapshots are also included in the native payload. Rebuilds need a fresh
`.build/release` directory; remove that generated directory before rerunning
the native builder. Source archives capture the actual worktree, including
uncommitted changes, while recording its base Git revision.

Cross-platform release builds and driver setup must be exercised
on their respective operating systems. Robot DFU, SSH, PM, firmware and reboot
behavior still need live hardware acceptance; mocked release tests cannot
establish those results.

## CI troubleshooting

If Windows PowerShell reports that built-in commands such as `Get-FileHash`
are missing, ensure the updated build scripts and release tests are
present. Python children of PowerShell 7 can inherit its incompatible module
paths; the driver signature check removes `PSModulePath` only from its Windows PowerShell
child's environment so that 5.1 constructs the correct paths. See
[Microsoft's module-path documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_psmodulepath#starting-windows-powershell-from-powershell-7).

The macOS workflow uploads the built app ZIP and DMG before testing the mounted
DMG. `verify_macos.py` verifies the disk image, retries transient attach/detach
resource errors up to five times, and checks the mounted app's signature,
self-check and GUI startup. Invalid images and app failures still fail the job.
The mountpoint is unique per invocation and is detached even when an app check
fails. If mounting remains unavailable on a runner, its already checked app ZIP
is still available in the workflow's artifacts.

After updating these files on GitHub, start a new workflow run on the updated
branch. Rerunning an older run keeps its original source revision.
