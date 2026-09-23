"""debugfs and loop-mount helpers for Jibo ext partitions."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


class ImageError(RuntimeError):
    pass


def _debugfs(image: Path, command: str, write: bool = False) -> subprocess.CompletedProcess[bytes]:
    args = ["debugfs"]
    if write:
        args.append("-w")
    args.extend(["-R", command, str(image)])
    return subprocess.run(args, capture_output=True)


def _missing(stderr: bytes) -> bool:
    text = stderr.decode("utf-8", errors="replace").lower()
    return "file not found" in text or "no such file" in text or "not found" in text


def read_text(image: Path, path: str) -> str | None:
    data = read_bytes(image, path)
    if data is None:
        return None
    return data.decode("utf-8", errors="replace")


def read_bytes(image: Path, path: str) -> bytes | None:
    result = _debugfs(image, f"cat {path}")
    if result.returncode != 0 or _missing(result.stderr):
        return None
    if not result.stdout and _missing(result.stderr):
        return None
    return result.stdout


def exists(image: Path, path: str) -> bool:
    result = _debugfs(image, f"stat {path}")
    if result.returncode != 0 or _missing(result.stderr):
        return False
    text = result.stdout.decode("utf-8", errors="replace")
    return "Inode:" in text


def list_dir(image: Path, path: str) -> list[str]:
    result = _debugfs(image, f"ls -p {path}")
    if result.returncode != 0 or _missing(result.stderr):
        return []
    names: list[str] = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        # debugfs ls -p: /inode/mode/uid/gid/name/size/
        parts = [part for part in line.split("/") if part]
        if len(parts) < 5:
            continue
        name = parts[4]
        if name in ("", ".", ".."):
            continue
        names.append(name)
    return names


def mkdir(image: Path, path: str) -> None:
    if exists(image, path):
        return
    parent = path.rsplit("/", 1)[0]
    if parent and parent != path:
        mkdir(image, parent)
    result = _debugfs(image, f"mkdir {path}", write=True)
    if result.returncode != 0 and not exists(image, path):
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImageError(f"could not mkdir {path}: {detail}")


def remove(image: Path, path: str) -> bool:
    if not exists(image, path):
        return False
    result = _debugfs(image, f"rm {path}", write=True)
    if exists(image, path):
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImageError(f"could not remove {path}: {detail}")
    return True


def write_bytes(image: Path, path: str, data: bytes) -> None:
    parent = path.rsplit("/", 1)[0]
    if parent:
        mkdir(image, parent)
    if exists(image, path):
        remove(image, path)
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(data)
        local = handle.name
    try:
        result = _debugfs(image, f"write {local} {path}", write=True)
        if not exists(image, path):
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ImageError(f"could not write {path}: {detail or 'debugfs write failed'}")
    finally:
        os.unlink(local)


def write_text(image: Path, path: str, text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    write_bytes(image, path, text.encode("utf-8"))


def extract_partition(dump: Path, start_sector: int, size_sectors: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    command = [
        "dd",
        f"if={dump}",
        f"of={dest}",
        "bs=512",
        f"skip={start_sector}",
        f"count={size_sectors}",
        "status=none",
        "conv=fsync",
    ]
    subprocess.run(command, check=True)
    expected = size_sectors * 512
    actual = dest.stat().st_size
    if actual != expected:
        raise ImageError(f"extracted {dest.name} is {actual} bytes, expected {expected}")


@contextmanager
def mount_rw(image: Path):
    """Loop-mount an ext image read-write. Uses sudo when not already root."""
    mountpoint = Path(tempfile.mkdtemp(prefix="beetle-mnt-"))
    mount_cmd = ["mount", "-o", "loop", str(image), str(mountpoint)]
    umount_cmd = ["umount", str(mountpoint)]
    if os.geteuid() != 0:
        mount_cmd = ["sudo", "-n", *mount_cmd]
        umount_cmd = ["sudo", "-n", *umount_cmd]
    try:
        subprocess.run(mount_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(mountpoint, ignore_errors=True)
        detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ImageError(
            "could not mount " + image.name + " read-write. "
            "BEetle needs root (or passwordless sudo) for the skills image. "
            + detail
        ) from exc
    try:
        yield mountpoint
    finally:
        subprocess.run(umount_cmd, check=False)
        shutil.rmtree(mountpoint, ignore_errors=True)
