"""Parse a Jibo eMMC GUID partition table from a dump file."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


SECTOR_SIZE = 512
EMMC_TOTAL_SECTORS = 0x1D60000
GPT_SIGNATURE = b"EFI PART"
REQUIRED_PARTITIONS = ("rootfsA", "rootfsB", "services", "var", "skills")


class GptError(RuntimeError):
    pass


@dataclass(frozen=True)
class Partition:
    name: str
    start_sector: int
    size_sectors: int

    @property
    def size_bytes(self) -> int:
        return self.size_sectors * SECTOR_SIZE

    @property
    def byte_offset(self) -> int:
        return self.start_sector * SECTOR_SIZE


def parse_gpt(header_blob: bytes) -> list[Partition]:
    """Parse a primary GPT from the start of an eMMC image.

    ``header_blob`` must include the protective MBR, the GPT header, and the
    entry array (the first 4096 sectors is plenty).
    """
    if len(header_blob) < 2 * SECTOR_SIZE or header_blob[SECTOR_SIZE:SECTOR_SIZE + 8] != GPT_SIGNATURE:
        raise GptError("primary GPT signature is missing")
    header = header_blob[SECTOR_SIZE:2 * SECTOR_SIZE]
    header_size = struct.unpack_from("<I", header, 12)[0]
    if not 92 <= header_size <= SECTOR_SIZE:
        raise GptError("invalid GPT header size")
    expected_header_crc = struct.unpack_from("<I", header, 16)[0]
    header_crc = bytearray(header[:header_size])
    header_crc[16:20] = b"\0\0\0\0"
    if zlib.crc32(header_crc) & 0xFFFFFFFF != expected_header_crc:
        raise GptError("GPT header CRC mismatch")

    entries_lba = struct.unpack_from("<Q", header, 72)[0]
    count = struct.unpack_from("<I", header, 80)[0]
    size = struct.unpack_from("<I", header, 84)[0]
    expected_entries_crc = struct.unpack_from("<I", header, 88)[0]
    entries_start = entries_lba * SECTOR_SIZE
    entries_length = count * size
    if count <= 0 or size < 128 or size % 8 or entries_start + entries_length > len(header_blob):
        raise GptError("GPT entry array is outside the bounded read")
    entries = header_blob[entries_start:entries_start + entries_length]
    if zlib.crc32(entries) & 0xFFFFFFFF != expected_entries_crc:
        raise GptError("GPT entry-array CRC mismatch")

    partitions: list[Partition] = []
    seen: set[str] = set()
    for index in range(count):
        entry = entries[index * size:(index + 1) * size]
        if entry[:16] == b"\0" * 16:
            continue
        first_lba, last_lba = struct.unpack_from("<QQ", entry, 32)
        name = entry[56:128].decode("utf-16le", errors="ignore").rstrip("\0")
        if not name:
            raise GptError(f"GPT entry {index + 1} has an empty name")
        if first_lba > last_lba or last_lba >= EMMC_TOTAL_SECTORS:
            raise GptError(f"invalid GPT bounds for {name}")
        if name in seen:
            raise GptError(f"duplicate GPT partition: {name}")
        seen.add(name)
        partitions.append(Partition(name, first_lba, last_lba - first_lba + 1))
    return partitions


def load_gpt(dump: Path, sectors: int = 4096) -> list[Partition]:
    with dump.open("rb") as stream:
        blob = stream.read(sectors * SECTOR_SIZE)
    if len(blob) < sectors * SECTOR_SIZE:
        raise GptError(f"dump is too small to contain a GPT: {dump}")
    return parse_gpt(blob)


def require_jibo_layout(partitions: list[Partition]) -> dict[str, Partition]:
    found = {part.name: part for part in partitions}
    missing = [name for name in REQUIRED_PARTITIONS if name not in found]
    if missing:
        raise GptError(
            "dump is not a Jibo eMMC (missing " + ", ".join(missing) + ")"
        )
    return found
