#!/usr/bin/env python3
"""Patch a JiboAutoMod eMMC dump so an out-of-box Jibo can join Wi-Fi and open BEacon.

BEetle does not dump the robot. Pass the dump AutoMod already wrote.
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import sys
from pathlib import Path

import freshness
import gpt
import images
import patch_rootfs
import patch_services
import patch_skills
import patch_var
import sector_diff
import shofel

REPO = Path(__file__).resolve().parent
PARTITIONS = ("var", "rootfsA", "rootfsB", "services", "skills")


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


def _extract_all(dump: Path, found: dict[str, gpt.Partition], work: Path) -> dict[str, Path]:
    images_out: dict[str, Path] = {}
    for name in PARTITIONS:
        part = found[name]
        dest = work / f"{name}.base.img"
        print(f"Extracting {name} ({part.size_bytes // (1024 * 1024)} MiB)...")
        images.extract_partition(dump, part.start_sector, part.size_sectors, dest)
        images_out[name] = dest
    return images_out


def _patched_path(base: Path) -> Path:
    return base.with_name(base.name.replace(".base.img", ".patched.img"))


def _copy_base(base: Path) -> Path:
    dest = _patched_path(base)
    if dest.exists():
        dest.unlink()
    shutil.copyfile(base, dest)
    return dest


def _apply_one(name: str, patched: Path, ssid: str, psk: str, beam: Path | None) -> dict:
    if name == "var":
        return patch_var.apply(patched, ssid, psk)
    if name in ("rootfsA", "rootfsB"):
        return patch_rootfs.apply(patched, patch_skills.ca_path())
    if name == "services":
        return patch_services.apply(patched)
    if name == "skills":
        return patch_skills.apply(patched, beam)
    raise BeetleError(f"unknown partition {name}")


def _plan_for(part: gpt.Partition, base: Path, patched: Path) -> list[dict]:
    # Diff against whichever image is the unpatched base. After a live rebase
    # that base is the re-read partition, not the original dump.
    ranges = sector_diff.changed_ranges(base, patched)
    return [
        {
            "start_sector": part.start_sector + item.start,
            "count": item.count,
            "image_sector": item.start,
        }
        for item in ranges
    ]


def _write_plan(path: Path, identity: dict, plans: dict) -> None:
    payload = {
        "robot": {
            "name": identity.get("name"),
            "serial_number": identity.get("serial_number"),
            "cpuid": identity.get("cpuid"),
        },
        "hub": f"{patch_var.HUB_HOST}:{patch_var.HUB_PORT}",
        "ota_endpoint": patch_var.OTA_ENDPOINT,
        "partitions": plans,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _slice_to_file(image: Path, image_sector: int, count: int, dest: Path) -> None:
    length = count * gpt.SECTOR_SIZE
    with image.open("rb") as stream:
        stream.seek(image_sector * gpt.SECTOR_SIZE)
        data = stream.read(length)
    if len(data) != length:
        raise BeetleError("short read while building a write payload")
    dest.write_bytes(data)


def _live_superblock(tool: shofel.Shofel, part: gpt.Partition, dest: Path) -> bytes:
    # Superblock starts at byte 1024, which is sector 2 of the partition.
    tool.read(part.start_sector + 2, 2, dest)
    return dest.read_bytes()[:freshness.SUPERBLOCK_LENGTH]


def _dump_superblock(dump: Path, part: gpt.Partition) -> bytes:
    return freshness.superblock(dump, part.byte_offset)


def _range_still_original(tool: shofel.Shofel, dump: Path, item: dict, scratch: Path) -> bool:
    tool.read(item["start_sector"], item["count"], scratch)
    original = freshness.read_dump_range(
        dump,
        item["start_sector"] * gpt.SECTOR_SIZE,
        item["count"] * gpt.SECTOR_SIZE,
    )
    return freshness.live_ranges_match(scratch.read_bytes(), original)


def _rebase_partition(
    tool: shofel.Shofel,
    name: str,
    part: gpt.Partition,
    base: Path,
    ssid: str,
    psk: str,
    beam: Path | None,
    dump_var: Path,
    force: bool,
) -> tuple[Path, dict]:
    print(f"{name} changed after the dump; reading that partition from the robot and reapplying patches...")
    tool.read(part.start_sector, part.size_sectors, base)
    if name == "var":
        freshness.assert_same_robot(dump_var, base)
        if patch_var.assess(base) == "provisioned" and not force:
            raise BeetleError(
                "the live robot is already provisioned (mode normal with credentials). "
                "Re-run with --force only if you mean to overwrite that."
            )
    patched = _copy_base(base)
    summary = _apply_one(name, patched, ssid, psk, beam)
    return patched, summary


def _confirm_or_rebase(
    tool: shofel.Shofel,
    dump: Path,
    found: dict[str, gpt.Partition],
    bases: dict[str, Path],
    patched: dict[str, Path],
    plans: dict[str, list],
    summaries: dict[str, dict],
    ssid: str,
    psk: str,
    beam: Path | None,
    force: bool,
) -> None:
    if not tool.present():
        raise BeetleError("Jibo APX device was not detected. Put the robot in RCM and connect USB.")
    gpt_live = bases["var"].with_name("live-gpt.bin")
    tool.read(0, 4096, gpt_live)
    if not freshness.gpt_matches(dump, gpt_live):
        raise BeetleError(
            "live GPT does not match the dump. That is not a Wi-Fi retry; "
            "check that this dump belongs to the connected robot."
        )

    dump_var_saved = bases["var"].with_name("var.dump-identity.img")
    if not dump_var_saved.exists():
        shutil.copyfile(bases["var"], dump_var_saved)

    scratch = bases["var"].with_name("live-scratch.bin")
    for name in PARTITIONS:
        part = found[name]
        live_sb_path = bases[name].with_name(f"{name}.live-super.bin")
        live_sb = _live_superblock(tool, part, live_sb_path)
        dump_sb = _dump_superblock(dump, part)
        # var is small and a failed OOBE Wi-Fi attempt rewrites files in place,
        # which can leave the free-block count unchanged. Other partitions are
        # re-read only when allocation actually changed.
        if name == "var":
            drifted = freshness.allocation_changed(dump_sb, live_sb) or freshness.mount_stamp_changed(dump_sb, live_sb)
        else:
            drifted = freshness.allocation_changed(dump_sb, live_sb)
        if not drifted and name == "var":
            for item in plans[name]:
                if not _range_still_original(tool, dump, item, scratch):
                    drifted = True
                    break
        if not drifted:
            continue
        new_patched, summary = _rebase_partition(
            tool, name, part, bases[name], ssid, psk, beam, dump_var_saved, force
        )
        patched[name] = new_patched
        summaries[name] = summary
        plans[name] = _plan_for(part, bases[name], new_patched)


def _write_ranges(tool: shofel.Shofel, plans: dict[str, list], patched: dict[str, Path], work: Path) -> None:
    payload = work / "write-payload.bin"
    readback = work / "write-readback.bin"
    for name in PARTITIONS:
        image = patched[name]
        ranges = plans[name]
        total = sum(item["count"] for item in ranges)
        print(f"Writing {name}: {len(ranges)} range(s), {total} sectors")
        for item in ranges:
            _slice_to_file(image, item["image_sector"], item["count"], payload)
            tool.write(item["start_sector"], payload)
            tool.read(item["start_sector"], item["count"], readback)
            if readback.read_bytes() != payload.read_bytes():
                raise BeetleError(
                    f"read-back mismatch on {name} at sector 0x{item['start_sector']:x}"
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare an OOBE Jibo dump and write the changed sectors back.")
    parser.add_argument("--dump-path", required=True, type=Path, help="Full eMMC dump from JiboAutoMod")
    parser.add_argument("--ssid", help="Wi-Fi network name")
    parser.add_argument("--psk", help="Wi-Fi password. Omit to be prompted. Pass an empty string for an open network.")
    parser.add_argument("--write", action="store_true", help="Write changed sectors to the robot in RCM")
    parser.add_argument("--patch-only", action="store_true", help="Patch local images and stop (no device I/O)")
    parser.add_argument("--force", action="store_true", help="Continue even if the robot already looks provisioned")
    parser.add_argument("--work", type=Path, help="Scratch directory (default: BEetle/work)")
    parser.add_argument("--beam", type=Path, help="BEam checkout to bake into skills (default: sibling BEam)")
    parser.add_argument("--shofel", type=Path, help="Path to shofel2_t124")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.write and args.patch_only:
        print("Choose either --write or --patch-only.", file=sys.stderr)
        return 2
    dump = args.dump_path.expanduser().resolve()
    if not dump.is_file():
        print(f"Dump not found: {dump}", file=sys.stderr)
        return 2

    work = (args.work or (REPO / "work")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    ssid, psk = _prompt_wifi(args)

    print(f"Reading GPT from {dump.name}...")
    found = gpt.require_jibo_layout(gpt.load_gpt(dump))
    bases = _extract_all(dump, found, work)
    state = patch_var.assess(bases["var"])
    identity = patch_var.robot_identity(bases["var"])
    print(f"Robot {identity.get('name')} ({identity.get('serial_number')}) looks {state}.")
    if state == "provisioned" and not args.force:
        print(
            "This dump is already provisioned (mode normal with credentials). "
            "BEetle is for out-of-box robots. Pass --force to continue.",
            file=sys.stderr,
        )
        return 1

    # Keep an untouched copy of dump-extracted var for the same-robot check
    # after a live rebase replaces var.base.img.
    shutil.copyfile(bases["var"], work / "var.dump-identity.img")

    patched: dict[str, Path] = {}
    summaries: dict[str, dict] = {}
    for name in PARTITIONS:
        print(f"Patching {name}...")
        patched[name] = _copy_base(bases[name])
        summaries[name] = _apply_one(name, patched[name], ssid, psk, args.beam)

    plans = {
        name: _plan_for(found[name], bases[name], patched[name])
        for name in PARTITIONS
    }
    plan_path = work / "sector-plan.json"
    _write_plan(plan_path, identity, plans)
    changed = sum(sum(item["count"] for item in items) for items in plans.values())
    print(f"Sector plan: {changed} changed sectors. Wrote {plan_path}")

    if not args.write:
        print("Patch-only. Re-run with --write while the robot is in RCM to write these sectors.")
        return 0

    binary = args.shofel or shofel.default_binary()
    if binary is None:
        print(
            "ShofEL binary not found. Pass --shofel or set BEETLE_SHOFEL "
            "(expected ~/JiboAutoMod/Shofel/shofel2_t124).",
            file=sys.stderr,
        )
        return 1
    tool = shofel.Shofel(binary)
    try:
        _confirm_or_rebase(
            tool, dump, found, bases, patched, plans, summaries, ssid, psk, args.beam, args.force
        )
        _write_plan(plan_path, identity, plans)
        _write_ranges(tool, plans, patched, work)
    except (BeetleError, freshness.FreshnessError, shofel.ShofelError, images.ImageError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Write-back verified. Unplug USB, power-cycle, and follow the URL on Jibo's face.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BeetleError, images.ImageError, patch_var.VarPatchError, patch_skills.SkillsPatchError, patch_services.ServicesPatchError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
