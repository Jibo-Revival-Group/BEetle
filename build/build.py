#!/usr/bin/env python3
"""Build BEetle for one OS on CI: BEetle.exe (Windows), BEetle.app (macOS) or BEetle.AppImage (Linux).

  build.py windows-tools OUT   (Linux + MinGW) ShofEL host and dfu-util for Windows
  build.py tools               native dfu-util, e2fsprogs, libusb and ShofEL into dfu/tools, dfu/lib
  build.py windows-runtime     (Windows + Cygwin) debugfs/e2fsck and the UsbDk driver installer
  build.py freeze              PyInstaller, then the .exe / .app (zipped) / .AppImage in release-out/
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DFU = ROOT / "dfu"
WORK = ROOT / ".build"
OUT = ROOT / "release-out"
SOURCES = {  # the DFU Mod Toolkit's pinned versions
    "libusb": ("https://github.com/libusb/libusb/releases/download/v1.0.27/libusb-1.0.27.tar.bz2",
               "ffaa41d741a8a3bee244ac8e54a72ea05bf2879663c098c82fc5757853441575"),
    "dfu-util": ("https://dfu-util.sourceforge.net/releases/dfu-util-0.11.tar.gz",
                 "b4b53ba21a82ef7e3d4c47df2952adf5fa494f499b6b0b57c58c5d04ae8ff19e"),
    "e2fsprogs": ("https://www.kernel.org/pub/linux/kernel/people/tytso/e2fsprogs/v1.47.1/e2fsprogs-1.47.1.tar.gz",
                  "0d2e0bf80935c3392b73a60dbff82d8a6ef7ea88b806c2eea964b6837d3fd6c2"),
}
LIBUSB_WINDOWS = ("https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.7z",
                  "7fb1dfec805b97983763d7d0ae244320da12add1003d4249c96cc4d586398c79")
USBDK = ("https://github.com/daynix/UsbDk/releases/download/v1.00-22/UsbDk_1.0.22_x64.msi",
         "91f6f695e1e13c656024e6d3b55620bf08d8835ef05ee0496935ba6bb62466a5")
APPIMAGETOOL = ("https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage",
                "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0")
LIBUSB = {"win32": "libusb-1.0.dll", "darwin": "libusb-1.0.dylib"}.get(sys.platform, "libusb-1.0.so.0")


def run(*args, cwd=None, env=None):
    print("+", *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def download(url, sha, destination):
    destination = Path(destination)
    if not destination.is_file():
        with urllib.request.urlopen(url, timeout=300) as response:
            destination.write_bytes(response.read())
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if sha and actual != sha:
        raise SystemExit("hash mismatch for {}: {}".format(url, actual))
    print("downloaded", url, actual, flush=True)
    return destination


def source(name):
    url, sha = SOURCES[name]
    archive = download(url, sha, WORK / url.rsplit("/", 1)[1])
    with tarfile.open(archive) as tar:
        tar.extractall(WORK, filter="data")
    return WORK / archive.name.split(".tar.")[0]


def windows_tools(out):
    """ShofEL host and dfu-util for Windows, cross-compiled with MinGW (static, UsbDk-enabled)."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(exist_ok=True)
    archive = download(*LIBUSB_WINDOWS, WORK / "libusb-windows.7z")  # libusb's official Windows build
    libusb = WORK / "libusb-windows"
    run("7z", "x", "-y", "-o" + str(libusb), archive)
    run(sys.executable, ROOT / "build/shofel.py", out, "--windows", libusb)
    dfu_util = source("dfu-util")
    run("patch", "-p1", "-i", ROOT / "build/patches/dfu-util-usbdk.patch", cwd=dfu_util)
    run("sh", "./configure", "--host=x86_64-w64-mingw32",
        "USB_CFLAGS=-I{0}/include/libusb-1.0 -I{0}/include".format(libusb),
        "USB_LIBS={}/MinGW64/static/libusb-1.0.a".format(libusb), "LDFLAGS=-static", cwd=dfu_util)
    run("make", "-j4", cwd=dfu_util)
    shutil.copy2(dfu_util / "src/dfu-util.exe", out)
    shutil.copy2(libusb / "MinGW64/dll/libusb-1.0.dll", out)  # for BEetle's own USB listing


def tools():
    """Native tools for Linux or macOS, built from the toolkit's pinned sources."""
    WORK.mkdir(exist_ok=True)
    prefix = WORK / "prefix"
    env = dict(os.environ, PKG_CONFIG_PATH=str(prefix / "lib/pkgconfig"),
               CPPFLAGS="-I" + str(prefix / "include"), LDFLAGS="-L" + str(prefix / "lib"))
    flags = {"libusb": ["--disable-static"] + ([] if sys.platform == "darwin" else ["--disable-udev"]),
             "dfu-util": ["--disable-nls"],
             "e2fsprogs": ["--disable-nls", "--disable-fuse2fs", "--without-udev-rules-dir",
                           "--without-systemd-unit-dir", "--without-crond-dir"]}
    for name in ("libusb", "dfu-util", "e2fsprogs"):
        folder = source(name)
        # e2fsprogs 1.47.1 predates C23 (newer compilers' default).
        configure_env = dict(env, CFLAGS="-O2 -std=gnu17") if name == "e2fsprogs" else env
        run("./configure", "--prefix=" + str(prefix), *flags[name], cwd=folder, env=configure_env)
        run("make", "-j4", cwd=folder, env=env)
        run("make", "install", cwd=folder, env=env)
    (DFU / "tools").mkdir(exist_ok=True)
    (DFU / "lib").mkdir(exist_ok=True)
    for name in ("dfu-util", "debugfs", "e2fsck"):
        found = next(p for p in (prefix / "bin" / name, prefix / "sbin" / name) if p.is_file())
        shutil.copy2(found, DFU / "tools" / name)
    shutil.copy2(prefix / "lib" / LIBUSB, DFU / "lib" / LIBUSB)
    shofel = [sys.executable, ROOT / "build/shofel.py", DFU / "tools"]
    if sys.platform == "darwin":
        shofel += ["--libusb-prefix", prefix]
    run(*shofel)


def windows_runtime(windows_tools_dir):
    """On the Windows runner: the cross-built tools, Cygwin's debugfs/e2fsck with their DLLs, and UsbDk."""
    tools_dir, lib = DFU / "tools", DFU / "lib"
    tools_dir.mkdir(exist_ok=True)
    lib.mkdir(exist_ok=True)
    built = Path(windows_tools_dir)
    for name in ("shofel2_t124.exe", "intermezzo.bin", "dfu_stage2.bin", "dfu-util.exe"):
        shutil.copy2(built / name, tools_dir)
    shutil.copy2(built / "libusb-1.0.dll", lib)
    cygwin = Path(os.environ.get("CYGWIN_ROOT", r"C:\cygwin"))
    for name in ("debugfs.exe", "e2fsck.exe"):
        exe = next(p for p in (cygwin / "usr/sbin" / name, cygwin / "sbin" / name, cygwin / "bin" / name) if p.is_file())
        shutil.copy2(exe, tools_dir)
        listing = subprocess.check_output([str(cygwin / "bin/cygcheck.exe"), str(exe)], text=True)
        for line in listing.splitlines():
            dll = Path(line.strip())
            if dll.suffix.lower() == ".dll" and str(cygwin).lower() in str(dll).lower():
                shutil.copy2(dll, tools_dir)
    (ROOT / "windows").mkdir(exist_ok=True)
    download(*USBDK, ROOT / "windows/UsbDk_x64.msi")


def freeze():
    OUT.mkdir(exist_ok=True)
    sep = ";" if sys.platform == "win32" else ":"
    data = lambda src, dest: ["--add-data", str(src) + sep + dest]
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "BEetle",
            "--distpath", WORK / "dist", "--workpath", WORK / "freeze", "--specpath", WORK,
            "--paths", ROOT, "--paths", DFU, "--hidden-import", "paramiko", "--icon", ROOT / "build/beetle.png"]
    for module in DFU.glob("jibo_*.py"):
        args += ["--hidden-import", module.stem]
    # The toolkit finds its files next to its modules, which PyInstaller puts at the bundle's top.
    args += data(DFU / "assets", "assets") + data(DFU / "loader.bin", ".") + \
        data(DFU / "jibo_dfu_pipeline.py", ".") + data(DFU / "tools", "tools") + data(DFU / "lib", "lib")
    if sys.platform == "win32":
        args += ["--onefile"] + data(ROOT / "windows", "windows")
    else:
        args += ["--onedir"]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "com.jiborevival.beetle"]
    run(*args, ROOT / "beetle_main.py")
    if sys.platform == "win32":
        shutil.copy2(WORK / "dist/BEetle.exe", OUT / "BEetle.exe")
    elif sys.platform == "darwin":
        arch = os.uname().machine
        run("ditto", "-c", "-k", "--keepParent", WORK / "dist/BEetle.app", OUT / "BEetle-macOS-{}.app.zip".format(arch))
    else:
        appdir = WORK / "dist/BEetle"
        shutil.copy2(ROOT / "build/AppRun", appdir / "AppRun")
        (appdir / "AppRun").chmod(0o755)
        (appdir / "BEetle.desktop").write_text("[Desktop Entry]\nType=Application\nName=BEetle\nExec=AppRun\n"
                                               "Icon=beetle\nCategories=Utility;\nTerminal=false\n")
        shutil.copy2(ROOT / "build/beetle.png", appdir / "beetle.png")
        tool = download(*APPIMAGETOOL, WORK / "appimagetool.AppImage")
        tool.chmod(0o755)
        run(tool, "--appimage-extract-and-run", appdir, OUT / "BEetle-x86_64.AppImage", env=dict(os.environ, ARCH="x86_64"))


if __name__ == "__main__":
    command, rest = sys.argv[1], sys.argv[2:]
    {"windows-tools": windows_tools, "tools": tools, "windows-runtime": windows_runtime, "freeze": freeze}[command](*rest)
