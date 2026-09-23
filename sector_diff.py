"""Compare two partition images and return changed 512-byte ranges."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SECTOR_SIZE = 512


@dataclass(frozen=True)
class SectorRange:
    """Partition-relative sector range (not an absolute eMMC LBA)."""

    start: int
    count: int

    @property
    def byte_offset(self) -> int:
        return self.start * SECTOR_SIZE

    @property
    def byte_length(self) -> int:
        return self.count * SECTOR_SIZE


def changed_ranges(
    base: Path,
    patched: Path,
    base_offset: int = 0,
    chunk_sectors: int = 2048,
) -> list[SectorRange]:
    """Return coalesced sector ranges where ``patched`` differs from ``base``.

    ``base_offset`` is a byte offset into ``base`` (use the partition's
    location when ``base`` is a full eMMC dump). ``patched`` is a standalone
    partition image and must be the same length as the compared span.
    """
    if chunk_sectors <= 0:
        raise ValueError("chunk_sectors must be positive")
    base_size = base.stat().st_size
    patched_size = patched.stat().st_size
    if patched_size % SECTOR_SIZE:
        raise ValueError("patched image is not sector aligned")
    if base_offset < 0 or base_offset + patched_size > base_size:
        raise ValueError("patched image does not fit inside the base image")

    chunk_bytes = chunk_sectors * SECTOR_SIZE
    ranges: list[SectorRange] = []
    open_start: int | None = None
    open_count = 0
    sector_index = 0

    def close() -> None:
        nonlocal open_start, open_count
        if open_start is not None and open_count:
            ranges.append(SectorRange(open_start, open_count))
        open_start = None
        open_count = 0

    with base.open("rb") as base_stream, patched.open("rb") as patched_stream:
        base_stream.seek(base_offset)
        remaining = patched_size
        while remaining:
            take = min(chunk_bytes, remaining)
            base_chunk = base_stream.read(take)
            patched_chunk = patched_stream.read(take)
            if len(base_chunk) != take or len(patched_chunk) != take:
                raise IOError("short read while diffing partition images")
            if take % SECTOR_SIZE:
                raise ValueError("diff chunk is not sector aligned")
            sectors = take // SECTOR_SIZE
            for offset in range(sectors):
                start = offset * SECTOR_SIZE
                end = start + SECTOR_SIZE
                same = base_chunk[start:end] == patched_chunk[start:end]
                if same:
                    close()
                elif open_start is None:
                    open_start = sector_index + offset
                    open_count = 1
                else:
                    open_count += 1
            sector_index += sectors
            remaining -= take
    close()
    return ranges
