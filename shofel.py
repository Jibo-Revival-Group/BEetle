"""ShofEL eMMC reads and writes. BEetle never dumps a full image."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SECTOR_SIZE = 512
EMMC_TOTAL_SECTORS = 0x1D60000
APX_ID = "0955:7740"


class ShofelError(RuntimeError):
    pass


def default_binary() -> Path | None:
    candidates = []
    override = os.environ.get("BEETLE_SHOFEL")
    if override:
        candidates.append(Path(override))
    home = Path.home()
    candidates.extend([
        home / "JiboAutoMod" / "Shofel" / "shofel2_t124",
        home / "JiboAutoMod" / "Exploits" / "Shofel" / "shofel2_t124",
    ])
    for path in candidates:
        if path.is_file():
            return path
    return None


class Shofel:
    def __init__(self, binary: Path):
        self.binary = binary.resolve()
        if not self.binary.is_file():
            raise ShofelError(f"ShofEL binary not found: {self.binary}")
        self.cwd = self.binary.parent

    def present(self) -> bool:
        try:
            result = subprocess.run(["lsusb"], capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise ShofelError("lsusb failed; install usbutils") from exc
        return APX_ID in result.stdout

    def _run(self, operation: str, *arguments: str) -> None:
        command = [str(self.binary), operation, *arguments]
        if os.geteuid() != 0:
            command.insert(0, "sudo")
        subprocess.run(command, cwd=self.cwd, check=True)

    def read(self, start_sector: int, sector_count: int, output: Path) -> None:
        if start_sector < 0 or sector_count <= 0 or start_sector + sector_count > EMMC_TOTAL_SECTORS:
            raise ShofelError(
                f"invalid eMMC range start=0x{start_sector:x} count=0x{sector_count:x}"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        self._run("EMMC_READ", f"0x{start_sector:x}", f"0x{sector_count:x}", str(output.resolve()))
        expected = sector_count * SECTOR_SIZE
        actual = output.stat().st_size if output.exists() else -1
        if actual != expected:
            raise ShofelError(f"eMMC read size mismatch: expected {expected}, got {actual}")

    def write(self, start_sector: int, payload: Path) -> None:
        size = payload.stat().st_size
        if size <= 0 or size % SECTOR_SIZE:
            raise ShofelError("write payload must be non-empty and sector aligned")
        sector_count = size // SECTOR_SIZE
        if start_sector < 0 or start_sector + sector_count > EMMC_TOTAL_SECTORS:
            raise ShofelError("write range exceeds eMMC bounds")
        self._run("EMMC_WRITE", f"0x{start_sector:x}", str(payload.resolve()))
