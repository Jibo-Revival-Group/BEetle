#!/usr/bin/env python3
"""Flash a Jibo eMMC image over DFU without replacing /var.

Identity, calibration, and the rest of /var stay on the robot.
--setup can write a Wi-Fi network onto the robot's existing var.
"""

from __future__ import annotations

import argparse
import getpass
import shutil
import subprocess
import sys
from pathlib import Path

import dfu_flash
import gpt
import images
import patch_rootfs
import patch_services
import patch_skills
import patch_var

REPO = Path(__file__).resolve().parent


class BeetleError(RuntimeError):
    pass


def _prompt_wifi(args: argparse.Namespace) -> tuple[str, str]:
    ssid = args.ssid
    if not ssid:
        ssid = input("Wi-Fi SSID: ").strip()
    psk = args.psk
    if psk is None:
        psk = getpass.getpass("Wi-Fi password (empty for an open network): ")
    return ssid, psk



SAFE_PARTITIONS = ("rootfsA", "rootfsB", "services", "skills")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Flash a Jibo eMMC image over DFU. /var is left in place unless --setup writes Wi-Fi onto it."
    )
    parser.add_argument("image", type=Path, help="Full eMMC image (.bin) to flash")
    parser.add_argument(
        "--partitions",
        help="Comma-separated subset to write (default: rootfsA,rootfsB,services,skills). var is refused.",
    )
    parser.add_argument(
        "--write-only",
        action="store_true",
        help="Continue an interrupted flash of this same image.",
    )
    parser.add_argument("--work", type=Path, help="Scratch directory (default: BEetle/work)")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Download current BEam and BEnch, remove the firewall, ask for Wi-Fi, "
        "and patch those into the image before writing. Wi-Fi is written onto the robot's existing var.",
    )
    parser.add_argument("--ssid", help="Wi-Fi network name, used with --setup")
    parser.add_argument("--psk", help="Wi-Fi password, used with --setup. Empty string for an open network.")
    return parser


def _partition_list(spec: str | None) -> list[str]:
    if not spec:
        return list(SAFE_PARTITIONS)
    names = [piece.strip() for piece in spec.split(",") if piece.strip()]
    if "var" in names:
        raise BeetleError("Refusing to flash var. That partition stays on the robot.")
    unknown = [name for name in names if name not in SAFE_PARTITIONS]
    if not names or unknown:
        raise BeetleError(
            "Partitions must be chosen from " + ", ".join(SAFE_PARTITIONS) + "."
        )
    return names


def _source_key(image: Path) -> str:
    stat = image.stat()
    return f"{image}:{stat.st_mtime_ns}:{stat.st_size}"


BEAM_GIT = "https://github.com/Jibo-Revival-Group/BEam.git"
BENCH_GIT = "https://github.com/Jibo-Revival-Group/BEnch.git"


def _fetch_latest(url: str, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    print(f"Downloading {url} ...")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", "master", url, str(dest)],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise BeetleError(f"Could not download {url}") from exc
    return dest


def _flash_names(spec: str | None, setup: bool) -> list[str]:
    names = _partition_list(spec)
    if setup:
        return ["var", *[name for name in names if name != "var"]]
    return names


def _prepare_setup(
    paths: dict[str, Path],
    beam: Path,
    bench: Path,
    ssid: str,
    psk: str,
) -> None:
    print("Patching Wi-Fi into this robot's var...")
    patch_var.apply_wifi(paths["var"], ssid, psk)
    images.remove(paths["skills"], patch_skills.STAMP_PATH)
    images.remove(paths["services"], patch_services.STAMP_PATH)
    print("Patching current BEam into skills...")
    patch_skills.apply(paths["skills"], beam)
    print("Patching current BEnch into services...")
    patch_services.apply(paths["services"], bench)
    for name in ("rootfsA", "rootfsB"):
        removed = []
        for script in patch_rootfs.firewall_scripts(paths[name]):
            path = f"/etc/init.d/{script}"
            if images.remove(paths[name], path):
                removed.append(script)
        if removed:
            print(f"Removed {', '.join(removed)} from {name}.")
        else:
            print(f"No firewall script on {name}.")


def _extract_for_flash(image: Path, part: gpt.Partition, work: Path) -> Path:
    dest = work / f"flash-{part.name}.img"
    stamp = work / f"flash-{part.name}.source"
    key = _source_key(image)
    if dest.is_file() and dest.stat().st_size == part.size_bytes and stamp.is_file() and stamp.read_text(encoding="utf-8") == key:
        print(f"Reusing extracted {part.name}.")
        return dest
    print(f"Extracting {part.name} from the image ({part.size_bytes / 1024 / 1024:.0f} MiB)...")
    images.extract_partition(image, part.start_sector, part.size_sectors, dest)
    stamp.write_text(key, encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.setup and args.partitions:
        print("Use either --setup or --partitions.", file=sys.stderr)
        return 2
    try:
        names = _flash_names(args.partitions, args.setup)
    except BeetleError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    image = args.image.expanduser().resolve()
    if not image.is_file():
        print(f"Image not found: {image}", file=sys.stderr)
        return 2
    work = (args.work or (REPO / "work")).resolve()
    work.mkdir(parents=True, exist_ok=True)

    try:
        image_map = gpt.require_jibo_layout(gpt.load_gpt(image))
    except gpt.GptError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        tools = dfu_flash.require_tools()
    except dfu_flash.DfuFlashError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.setup:
        print("Setup writes Wi-Fi onto the robot's existing var. The rest of var stays.")
    else:
        print("Leaving var on the robot alone.")
    print("Will write: " + ", ".join(names))
    ssid = psk = ""
    beam = bench = None
    if args.setup and not args.write_only:
        ssid, psk = _prompt_wifi(args)
        if not ssid.strip():
            print("Wi-Fi SSID is required.", file=sys.stderr)
            return 2
    ready_to_write = not args.setup or args.write_only
    entered = False
    try:
        if args.setup and not args.write_only:
            beam = _fetch_latest(BEAM_GIT, work / "latest-BEam")
            bench = _fetch_latest(BENCH_GIT, work / "latest-BEnch")
        port = dfu_flash.enter(tools)
        entered = True
        live = dfu_flash.read_layout(tools, port)
        check = [name for name in names if name != "var"]
        mismatched = [
            name for name in check if live[name].size_bytes != image_map[name].size_bytes
        ]
        if mismatched:
            raise BeetleError(
                "Refusing to write. The image and the robot disagree on the size of "
                + ", ".join(mismatched)
                + "."
            )
        paths = {
            name: _extract_for_flash(image, image_map[name], work)
            for name in names
            if name != "var"
        }
        if args.setup:
            var_dest = work / "flash-var.img"
            if args.write_only:
                if not var_dest.is_file() or var_dest.stat().st_size != live["var"].size_bytes:
                    raise BeetleError(
                        "Setup was interrupted before Wi-Fi was saved. Re-run with --setup, without --write-only."
                    )
                print("Resuming the interrupted flash.")
            else:
                dfu_flash.read_partition(tools, port, "var", live["var"].size_bytes, var_dest)
                paths["var"] = var_dest
                if beam is None or bench is None:
                    raise BeetleError("BEam and BEnch were not downloaded.")
                _prepare_setup(paths, beam, bench, ssid, psk)
                ready_to_write = True
            paths["var"] = var_dest
        elif args.write_only:
            print("Resuming the interrupted flash.")
        dfu_flash.write_partitions(
            tools,
            port,
            names,
            paths,
            live,
            work,
            resume=args.write_only,
            allow_var=args.setup,
        )
        try:
            dfu_flash.reset_robot(tools, port)
        except dfu_flash.DfuFlashError as exc:
            print(f"The partitions were written. Reboot was not confirmed: {exc}")
            print("Unplug USB and power-cycle.")
    except KeyboardInterrupt:
        if not ready_to_write:
            again = " Power-cycle into RCM first." if entered else ""
            print(f"\nStopped before writing.{again} Re-run the same command with --setup.", file=sys.stderr)
        else:
            print(
                "\nStopped. Power-cycle into RCM and re-run the same command with --write-only.",
                file=sys.stderr,
            )
        return 130
    except (
        BeetleError,
        dfu_flash.DfuFlashError,
        images.ImageError,
        gpt.GptError,
        patch_var.VarPatchError,
        patch_skills.SkillsPatchError,
        patch_services.ServicesPatchError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        if entered:
            print("Power-cycle into RCM before trying again.", file=sys.stderr)
        return 1
    if args.setup:
        print("Flash finished. var was kept, with the Wi-Fi network you entered.")
    else:
        print("Flash finished. var was not written.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BeetleError, images.ImageError, patch_var.VarPatchError, patch_skills.SkillsPatchError, patch_services.ServicesPatchError, dfu_flash.DfuFlashError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
