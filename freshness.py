"""Decide whether a live partition still matches the dump, or must be re-read."""

from __future__ import annotations

from pathlib import Path

import images
import patch_var

# ext4 superblock lives at byte 1024. A mount updates it, which is how a
# post-dump OOBE Wi-Fi attempt shows up without hashing the whole partition.
SUPERBLOCK_OFFSET = 1024
SUPERBLOCK_LENGTH = 1024


class FreshnessError(RuntimeError):
    pass


def superblock(path: Path, byte_offset: int = 0) -> bytes:
    with path.open("rb") as stream:
        stream.seek(byte_offset + SUPERBLOCK_OFFSET)
        data = stream.read(SUPERBLOCK_LENGTH)
    if len(data) != SUPERBLOCK_LENGTH:
        raise FreshnessError(f"short superblock read from {path}")
    return data


def allocation_changed(dump_superblock: bytes, live_superblock: bytes) -> bool:
    """True when free block or free inode counts differ.

    A boot updates mount time and mount count even when no files change.
    Those fields alone must not force a multi-gigabyte re-read.
    """
    if len(dump_superblock) < 20 or len(live_superblock) < 20:
        return True
    return dump_superblock[12:20] != live_superblock[12:20]


def mount_stamp_changed(dump_superblock: bytes, live_superblock: bytes) -> bool:
    """True when write time or mount count changed (byte 44 through 53)."""
    if len(dump_superblock) < 54 or len(live_superblock) < 54:
        return True
    return dump_superblock[44:54] != live_superblock[44:54]


def assert_same_robot(dump_var: Path, live_var: Path) -> None:
    dump_id = patch_var.robot_identity(dump_var)
    live_id = patch_var.robot_identity(live_var)
    if dump_id.get("serial_number") != live_id.get("serial_number") or dump_id.get("cpuid") != live_id.get("cpuid"):
        raise FreshnessError(
            "live robot identity does not match the dump "
            f"({live_id.get('name')} {live_id.get('serial_number')} vs "
            f"{dump_id.get('name')} {dump_id.get('serial_number')}). "
            "Refusing to write."
        )


def gpt_matches(dump: Path, live_gpt: Path, sectors: int = 4096) -> bool:
    length = sectors * 512
    with dump.open("rb") as dump_stream, live_gpt.open("rb") as live_stream:
        return dump_stream.read(length) == live_stream.read(length)


def live_ranges_match(live_blob: bytes, original: bytes) -> bool:
    if len(live_blob) != len(original):
        return False
    return live_blob == original


def read_dump_range(dump: Path, byte_offset: int, length: int) -> bytes:
    with dump.open("rb") as stream:
        stream.seek(byte_offset)
        data = stream.read(length)
    if len(data) != length:
        raise FreshnessError("short dump read during freshness check")
    return data


def identity_bytes(image: Path) -> bytes:
    data = images.read_bytes(image, "/jibo/identity.json")
    if not data:
        raise FreshnessError("identity.json is missing")
    return data
