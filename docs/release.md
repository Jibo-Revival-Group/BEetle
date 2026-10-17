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
executable has no publisher signature. The original bundled dependency MSIs
retain their publisher signatures.

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

First build the Linux payload above. Copy `release-out/` to a Windows x64
build machine as `linux-stage/`, preserving `payload.tar.gz`, `revision.txt`
and the corresponding-source archive. With Python 3.12 x64:

```powershell
python -m venv .build-venv
.build-venv\Scripts\python -m pip install -r requirements-release.txt
.build-venv\Scripts\python scripts/release/build.py --windows-payload linux-stage
```

The build machine needs internet. The end user's single EXE includes:

- The frozen Linux GUI, Python, Tk, SSH dependencies, USB/ext4 tools and loader.
- The official Ubuntu 22.04.5 filesystem (about 344 MiB compressed).
- Microsoft WSL 2.6.3 including its kernel and WSLg.
- The original usbipd-win 5.3.0 x64 installer.

There is no first-launch Python installation, pip, Git clone, Ubuntu download,
winget invocation, or WSL update download. SHA-256 checks protect the embedded
files; MSI publisher signatures are checked before installation. Keep the EXE
on a local drive with enough space for extraction and the private Linux
filesystem. The large bundled prerequisites make this considerably larger than
the upstream bootstrapper.

Windows USB access needs WSL 2 and usbipd's system service/driver. If absent,
BEetle offers to install the included packages and enable Virtual Machine
Platform with Windows Update access disabled. This requires administrator
approval, BIOS/UEFI virtualization, and possibly a reboot. An OS missing its
feature files or blocked by organization policy must be repaired/configured
separately; BEetle does not download replacement Windows components.

The EXE is self-contained for toolkit dependencies, but Windows setup creates
persistent OS components and a private `BEetle-5x1` WSL distribution under
`%LOCALAPPDATA%\BEetle-5x1\wsl`. Robot backups remain in that Linux user's
`~/Jibo-Backups`; retain them before removing the distribution. Existing
compatible Ubuntu WSL distributions can also be selected with `-Distro NAME`.
Do not remove a distribution containing backups you still need.

Robot setup still needs Wi-Fi/internet to download and run the selected PM
script and contact 5x1. Bundling host dependencies does not change those four
SSH commands or replace the PM download.

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
pipeline subprocess. The Windows check verifies embedded files without
enabling WSL or installing anything. `--gui-smoke` on the native payload opens
a synthetic first window without USB access.

Distribute the generated corresponding-source archive(s), `LICENSE`, and
`THIRD-PARTY-NOTICES.md` alongside binaries. Runtime licenses and source
snapshots are also included in the native payload. Rebuilds need a fresh
`.build/release` directory; remove that generated directory before rerunning
the native builder. Source archives capture the actual worktree, including
uncommitted changes, while recording its base Git revision.

Cross-platform release builds and offline first-run setup must be exercised
on their respective operating systems. Robot DFU, SSH, PM, firmware and reboot
behavior still need live hardware acceptance; mocked release tests cannot
establish those results.
