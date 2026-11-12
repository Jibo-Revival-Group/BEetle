#!/usr/bin/env python3
"""Build the ShofEL RCM host for this OS (or Windows, cross-compiled on Linux) the way the
DFU Mod Toolkit does: pinned ShofEL commit + the toolkit's patch, with the stage protocol pinned
to BEetle's RAM loader. The ARM payloads are the toolkit's prebuilt, manifest-checked ones.

usage: shofel.py OUT [--windows LIBUSB_DIR] [--libusb-prefix PREFIX]
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DFU = ROOT / "dfu"
COMMIT = "31ac3a260c8a1501869aff6690b3b9ad4904ef58"
REPOSITORY = "https://github.com/devsparx/ShofEL2-for-T124.git"
PINNED_SIZE = "#define DFU_STAGE2_LOADER_SIZE 415088u"
PINNED_HASH = ("    0x8f, 0x46, 0x06, 0x2f, 0x2d, 0x20, 0x18, 0x24,\n"
               "    0x33, 0x70, 0x93, 0xa1, 0xe4, 0xc1, 0x54, 0xe3,\n"
               "    0x04, 0x8c, 0x01, 0x9b, 0x14, 0x79, 0x30, 0xda,\n"
               "    0x35, 0xb9, 0xd6, 0x2e, 0x00, 0xc5, 0xe6, 0x89")
PAYLOADS = ("intermezzo.bin", "dfu_stage2.bin")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(*command, cwd=None):
    print("+", *command, flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--windows", type=Path, metavar="LIBUSB_DIR",
                        help="cross-compile for Windows with MinGW against libusb's official release folder")
    parser.add_argument("--libusb-prefix", type=Path, help="libusb prefix for the macOS build")
    args = parser.parse_args()

    loader = DFU / "loader.bin"
    loader_sha, size = sha256(loader), loader.stat().st_size
    patch = ROOT / "build/patches/shofel2-dfu-entry.patch"
    payloads = DFU / "assets/entry-payloads"
    manifest = json.loads((payloads / "manifest.json").read_text())
    if (manifest["shofel_commit"], manifest["patch_sha256"], manifest["loader_sha256"]) != (COMMIT, sha256(patch), loader_sha):
        raise SystemExit("the prebuilt ARM payloads do not match this loader, patch and ShofEL commit")
    for name in PAYLOADS:
        if sha256(payloads / name) != manifest["files_sha256"][name]:
            raise SystemExit(name + " does not match its manifest")

    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp) / "shofel"
        run("git", "clone", "--quiet", "--no-checkout", REPOSITORY, str(work))
        run("git", "checkout", "--quiet", "--detach", COMMIT, cwd=work)
        run("git", "apply", str(patch), cwd=work)
        if args.windows:
            run("git", "apply", str(ROOT / "build/patches/shofel2-windows.patch"), cwd=work)

        # Pin the stage protocol to this loader (same edit as the toolkit's build_file_level_entry.py).
        header = work / "include/dfu_stage2_protocol.h"
        text = header.read_text()
        if text.count(PINNED_SIZE) != 1 or text.count(PINNED_HASH) != 1:
            raise SystemExit("the ShofEL stage protocol does not match the pinned baseline")
        new_hash = ",\n".join("    " + ", ".join("0x" + loader_sha[i:i + 2] for i in range(start, start + 16, 2))
                              for start in range(0, 64, 16))
        header.write_text(text.replace(PINNED_SIZE, "#define DFU_STAGE2_LOADER_SIZE {}u".format(size))
                          .replace(PINNED_HASH, new_hash))

        if args.windows:
            usb = args.windows
            make = ["CC_x86=x86_64-w64-mingw32-gcc",
                    "CFLAGS_x86=-Wall -Werror -I include -MMD -include win_compat.h -DJIBO_LIBUSB_BACKEND=1 "
                    "-DDFU_STAGE2_ENABLE_LAUNCH=1 -I{0}/include -I{0}/include/libusb-1.0".format(usb),
                    "LIBS_x86={}/MinGW64/static/libusb-1.0.a -l:binmode.o -static -lpthread".format(usb)]
        elif sys.platform == "darwin":
            prefix = args.libusb_prefix
            make = ["CC_x86=cc",
                    "CFLAGS_x86=-Wall -Werror -I include -MMD -DJIBO_LIBUSB_BACKEND=1 -DDFU_STAGE2_ENABLE_LAUNCH=1 "
                    "-I{0}/include -I{0}/include/libusb-1.0".format(prefix),
                    "LIBS_x86=-L{}/lib -lusb-1.0".format(prefix)]
        else:
            make = ["DFU_STAGE2_ENABLE_LAUNCH=1"]  # Linux: the toolkit's usbfs backend, no libusb
        (work / "build/obj_x86").mkdir(parents=True, exist_ok=True)
        run("make", "-B", "shofel2_t124", *make, cwd=work)
        host = work / ("shofel2_t124.exe" if args.windows else "shofel2_t124")
        if host.read_bytes().count(bytes.fromhex(loader_sha)) != 1:
            raise SystemExit("the built host does not carry the loader hash")
        if not args.windows:
            capability = subprocess.check_output([str(host), "--dfu-stage-capability"], text=True).strip()
            if capability != "dfu-stage-launch=1":
                raise SystemExit("the built host cannot launch the RAM loader")
        args.out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host, args.out / host.name)
        for name in PAYLOADS:
            shutil.copy2(payloads / name, args.out / name)
    print("ShofEL host and payloads in", args.out)


if __name__ == "__main__":
    main()
