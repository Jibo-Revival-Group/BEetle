#!/usr/bin/env python3
"""Build BEep's USB helper (dfu/beep_dfu.py + the DFU Mod Toolkit + native tools) for one OS on CI.
Adapted from old BEetle v2's build (tag old-beetle-v2); the toolkit is checked out, not copied.

  dfu.py toolkit               clone the toolkit fork at TOOLKIT_COMMIT into dfu/toolkit
  dfu.py windows-tools OUT     (Linux + MinGW) ShofEL host and dfu-util for Windows
  dfu.py tools                 native libusb, dfu-util and ShofEL into dfu/toolkit/{tools,lib}
  dfu.py windows-runtime DIR   (Windows) the cross-built tools and the UsbDk installer
  dfu.py freeze                PyInstaller: dfu/dist/beep-dfu/ (packaged by electron-builder as resources/dfu)
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
DFU = ROOT / "dfu" / "toolkit"
WORK = ROOT / ".build"
TOOLKIT = "https://github.com/Jibo-Revival-Group/Jibo-DFU-Mod-Toolkit.git"
TOOLKIT_COMMIT = "307688b602b25392af3384f6c9437a0203547e04"
SOURCES = {  # the DFU Mod Toolkit's pinned versions
    "libusb": ("https://github.com/libusb/libusb/releases/download/v1.0.27/libusb-1.0.27.tar.bz2",
               "ffaa41d741a8a3bee244ac8e54a72ea05bf2879663c098c82fc5757853441575"),
    "dfu-util": ("https://dfu-util.sourceforge.net/releases/dfu-util-0.11.tar.gz",
                 "b4b53ba21a82ef7e3d4c47df2952adf5fa494f499b6b0b57c58c5d04ae8ff19e"),
}
LIBUSB_WINDOWS = ("https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.7z",
                  "7fb1dfec805b97983763d7d0ae244320da12add1003d4249c96cc4d586398c79")
USBDK = ("https://github.com/daynix/UsbDk/releases/download/v1.00-22/UsbDk_1.0.22_x64.msi",
         "91f6f695e1e13c656024e6d3b55620bf08d8835ef05ee0496935ba6bb62466a5")
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
    if actual != sha:
        raise SystemExit("hash mismatch for {}: {}".format(url, actual))
    return destination


def source(name):
    url, sha = SOURCES[name]
    archive = download(url, sha, WORK / url.rsplit("/", 1)[1])
    with tarfile.open(archive) as tar:
        tar.extractall(WORK, filter="data")
    return WORK / archive.name.split(".tar.")[0]


def toolkit():
    if DFU.is_symlink() or DFU.exists():
        shutil.rmtree(DFU) if not DFU.is_symlink() else DFU.unlink()
    run("git", "clone", "--quiet", "--no-checkout", TOOLKIT, DFU)
    run("git", "checkout", "--quiet", "--detach", TOOLKIT_COMMIT, cwd=DFU)


def windows_tools(out):
    """ShofEL host and dfu-util for Windows, cross-compiled with MinGW (static, UsbDk-enabled)."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(exist_ok=True)
    archive = download(*LIBUSB_WINDOWS, WORK / "libusb-windows.7z")  # libusb's official Windows build
    libusb = WORK / "libusb-windows"
    # Only the MinGW parts: Ubuntu's older 7-Zip can't unpack the ARM64 builds in the archive.
    run("7z", "x", "-y", "-o" + str(libusb), archive, "include", "MinGW64", "-r-")
    run(sys.executable, ROOT / "build/shofel.py", out, "--windows", libusb)
    dfu_util = source("dfu-util")
    run("patch", "-p1", "-i", ROOT / "build/patches/dfu-util-usbdk.patch", cwd=dfu_util)
    run("sh", "./configure", "--host=x86_64-w64-mingw32",
        "USB_CFLAGS=-I{0}/include/libusb-1.0 -I{0}/include".format(libusb),
        "USB_LIBS={}/MinGW64/static/libusb-1.0.a".format(libusb), "LDFLAGS=-static", cwd=dfu_util)
    run("make", "-j4", cwd=dfu_util)
    shutil.copy2(dfu_util / "src/dfu-util.exe", out)
    shutil.copy2(libusb / "MinGW64/dll/libusb-1.0.dll", out)  # for the toolkit's own USB listing


def tools():
    """Native tools for Linux or macOS, built from the toolkit's pinned sources."""
    WORK.mkdir(exist_ok=True)
    prefix = WORK / "prefix"
    env = dict(os.environ, PKG_CONFIG_PATH=str(prefix / "lib/pkgconfig"),
               CPPFLAGS="-I" + str(prefix / "include"), LDFLAGS="-L" + str(prefix / "lib"))
    flags = {"libusb": ["--disable-static"] + ([] if sys.platform == "darwin" else ["--disable-udev"]),
             "dfu-util": ["--disable-nls"]}
    for name in ("libusb", "dfu-util"):
        folder = source(name)
        run("./configure", "--prefix=" + str(prefix), *flags[name], cwd=folder, env=env)
        run("make", "-j4", cwd=folder, env=env)
        run("make", "install", cwd=folder, env=env)
    (DFU / "tools").mkdir(exist_ok=True)
    (DFU / "lib").mkdir(exist_ok=True)
    shutil.copy2(prefix / "bin/dfu-util", DFU / "tools/dfu-util")
    shutil.copy2(prefix / "lib" / LIBUSB, DFU / "lib" / LIBUSB)
    shofel = [sys.executable, ROOT / "build/shofel.py", DFU / "tools"]
    if sys.platform == "darwin":
        shofel += ["--libusb-prefix", prefix]
    run(*shofel)
    if sys.platform == "darwin":
        # Point the tools at the bundled libusb instead of the build folder, then re-sign them.
        bundled = "@executable_path/../lib/" + LIBUSB
        run("install_name_tool", "-id", bundled, DFU / "lib" / LIBUSB)
        run("codesign", "-f", "-s", "-", DFU / "lib" / LIBUSB)
        for name in ("dfu-util", "shofel2_t124"):
            binary = DFU / "tools" / name
            for line in subprocess.check_output(["otool", "-L", str(binary)], text=True).splitlines()[1:]:
                linked = line.strip().split(" (")[0]
                if "libusb" in linked:
                    run("install_name_tool", "-change", linked, bundled, binary)
            run("codesign", "-f", "-s", "-", binary)


def windows_runtime(windows_tools_dir):
    """On the Windows runner: the cross-built tools and the UsbDk installer."""
    (DFU / "tools").mkdir(exist_ok=True)
    (DFU / "lib").mkdir(exist_ok=True)
    built = Path(windows_tools_dir)
    for name in ("shofel2_t124.exe", "intermezzo.bin", "dfu_stage2.bin", "dfu-util.exe"):
        shutil.copy2(built / name, DFU / "tools")
    shutil.copy2(built / "libusb-1.0.dll", DFU / "lib")
    (DFU / "windows").mkdir(exist_ok=True)
    download(*USBDK, DFU / "windows/UsbDk_x64.msi")


def freeze():
    sep = ";" if sys.platform == "win32" else ":"
    data = lambda src, dest: ["--add-data", str(src) + sep + dest]
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--name", "beep-dfu",
            "--distpath", ROOT / "dfu/dist", "--workpath", WORK / "freeze", "--specpath", WORK, "--paths", DFU]
    for module in DFU.glob("jibo_*.py"):
        if not module.stem.startswith("jibo_gui"):  # the toolkit's Tk window; BEep is the window
            args += ["--hidden-import", module.stem]
    args += ["--exclude-module", "tkinter", "--exclude-module", "jibo_gui", "--exclude-module", "jibo_gui_core"]
    if sys.platform != "win32":
        args.append("--strip")
    # The toolkit finds its files next to its modules, which PyInstaller puts at the bundle's top.
    args += data(DFU / "assets", "assets") + data(DFU / "jibo_dfu_pipeline.py", ".") + \
        data(DFU / "tools", "tools") + data(DFU / "lib", "lib")
    if (DFU / "windows").is_dir():
        args += data(DFU / "windows", "windows")
    run(*args, ROOT / "dfu/beep_dfu.py")


if __name__ == "__main__":
    command, rest = sys.argv[1], sys.argv[2:]
    {"toolkit": toolkit, "windows-tools": windows_tools, "tools": tools, "windows-runtime": windows_runtime,
     "freeze": freeze}[command](*rest)
