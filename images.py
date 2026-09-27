"""debugfs and FUSE mount helpers for Jibo ext partitions."""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
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


def is_directory(image: Path, path: str) -> bool:
    result = _debugfs(image, f"stat {path}")
    text = result.stdout.decode("utf-8", errors="replace")
    return "Type: directory" in text


def remove(image: Path, path: str) -> bool:
    if not exists(image, path):
        return False
    result = _debugfs(image, f"rm {path}", write=True)
    if exists(image, path):
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImageError(f"could not remove {path}: {detail}")
    return True


def _debugfs_script(image: Path, commands: list[str]) -> subprocess.CompletedProcess[bytes]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write("\n".join(commands) + "\n")
        script = handle.name
    try:
        return subprocess.run(["debugfs", "-w", "-f", script, str(image)], capture_output=True)
    finally:
        os.unlink(script)


def remove_tree(image: Path, path: str) -> bool:
    """Delete a file or a directory and everything under it."""
    if not exists(image, path):
        return False
    commands: list[str] = []

    def collect(current: str) -> None:
        if is_directory(image, current):
            for name in list_dir(image, current):
                collect(f"{current.rstrip('/')}/{name}")
            commands.append(f"rmdir {current}")
        else:
            commands.append(f"rm {current}")

    collect(path)
    result = _debugfs_script(image, commands)
    if exists(image, path):
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImageError(f"could not remove {path}: {detail}")
    return True


def export_tree(image: Path, src: str, dest_parent: Path) -> Path | None:
    """Copy a file or directory out of an image. Returns the host path, or None if missing."""
    if not exists(image, src):
        return None
    dest_parent.mkdir(parents=True, exist_ok=True)
    name = src.rstrip("/").rsplit("/", 1)[-1]
    created = dest_parent / name
    if created.exists():
        if created.is_dir():
            shutil.rmtree(created)
        else:
            created.unlink()
    result = _debugfs(image, f"rdump {src} {dest_parent}")
    if not created.exists():
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImageError(f"could not export {src}: {detail}")
    return created


def import_tree(host_root: Path, image: Path, dest_dir: str) -> None:
    """Copy a host directory into an image, replacing dest_dir."""
    if exists(image, dest_dir):
        remove_tree(image, dest_dir)
    mkdir(image, dest_dir)
    for dirpath, dirnames, filenames in os.walk(host_root):
        relative = Path(dirpath).relative_to(host_root)
        for directory in dirnames:
            child = dest_dir if relative == Path(".") else f"{dest_dir}/{relative.as_posix()}"
            mkdir(image, f"{child}/{directory}")
        for filename in filenames:
            source = Path(dirpath) / filename
            child = dest_dir if relative == Path(".") else f"{dest_dir}/{relative.as_posix()}"
            target = f"{child}/{filename}"
            if source.is_symlink():
                link = os.readlink(source)
                result = _debugfs(image, f"symlink {target} {link}", write=True)
                if not exists(image, target):
                    detail = result.stderr.decode("utf-8", errors="replace").strip()
                    raise ImageError(f"could not symlink {target}: {detail}")
            elif source.is_file():
                write_bytes(image, target, source.read_bytes())


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


_METADATA_CSUM = 0x400
_CSUM_SEED = 0x2000
_EXTENTS_FL = 0x80000
_EXTENT_MAGIC = 0xF30A


def _crc32c(data: bytes, crc: int = 0xFFFFFFFF) -> int:
    table = _crc32c.table  # type: ignore[attr-defined]
    for byte in data:
        crc = table[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFFFFFF


def _crc32c_table() -> list[int]:
    polynomial = 0x82F63B78
    table = []
    for index in range(256):
        value = index
        for _ in range(8):
            value = (value >> 1) ^ polynomial if value & 1 else value >> 1
        table.append(value)
    return table


_crc32c.table = _crc32c_table()  # type: ignore[attr-defined]


def _superblock(image: Path) -> bytes:
    with image.open("rb") as handle:
        handle.seek(1024)
        block = handle.read(1024)
    if len(block) < 0x280 or struct.unpack_from("<H", block, 0x38)[0] != 0xEF53:
        raise ImageError(f"{image.name} is not an ext filesystem")
    return block


def _filesystem_layout(image: Path) -> dict[str, int]:
    block = _superblock(image)
    log_block = struct.unpack_from("<I", block, 0x18)[0]
    incompat = struct.unpack_from("<I", block, 0x60)[0]
    ro_compat = struct.unpack_from("<I", block, 0x64)[0]
    if incompat & _CSUM_SEED:
        seed = struct.unpack_from("<I", block, 0x270)[0]
    elif ro_compat & _METADATA_CSUM:
        seed = _crc32c(block[0x68:0x78])
    else:
        seed = 0
    return {
        "block_size": 1024 << log_block,
        "inode_size": struct.unpack_from("<H", block, 0x58)[0],
        "metadata_csum": int(bool(ro_compat & _METADATA_CSUM)),
        "csum_seed": seed,
    }


def _inode_csum(seed: int, inum: int, raw: bytes) -> int:
    node = bytearray(raw)
    if len(node) >= 0x7E:
        node[0x7C:0x7E] = b"\x00\x00"
    if len(node) >= 0x84:
        node[0x82:0x84] = b"\x00\x00"
    crc = _crc32c(struct.pack("<I", inum), seed)
    crc = _crc32c(node[0x64:0x68], crc)
    return _crc32c(bytes(node), crc)


def _file_blocks(inode: bytes, block_size: int) -> list[int]:
    flags = struct.unpack_from("<I", inode, 0x20)[0]
    if flags & _EXTENTS_FL:
        magic, entries, _limit, depth = struct.unpack_from("<HHHH", inode, 0x28)
        if magic != _EXTENT_MAGIC or depth != 0:
            raise ImageError("this file is not a single extent, so it cannot be edited in place")
        blocks: list[int] = []
        cursor = 0x28 + 12
        for _ in range(entries):
            logical, length, start_hi, start_lo = struct.unpack_from("<IHHI", inode, cursor)
            cursor += 12
            length &= 0x7FFF
            start = start_lo | (start_hi << 32)
            if logical != len(blocks):
                raise ImageError("the file's extents have a hole, so it cannot be edited in place")
            blocks.extend(range(start, start + length))
        return blocks
    blocks = []
    for index in range(12):
        number = struct.unpack_from("<I", inode, 0x28 + index * 4)[0]
        if not number:
            break
        blocks.append(number)
    return blocks


def rewrite_file_bytes(image: Path, path: str, data: bytes) -> None:
    """Replace one file's bytes without allocating blocks or opening the journal.

    The superblock and every other file stay byte-for-byte. This is the edit
    used when the only wanted change is the contents of an existing file.
    """
    if not exists(image, path) or is_directory(image, path):
        raise ImageError(f"{path} is not an existing file")
    layout = _filesystem_layout(image)
    stat = _debugfs(image, f"stat {path}")
    imap = _debugfs(image, f"imap {path}")
    stat_text = stat.stdout.decode("utf-8", errors="replace")
    imap_text = imap.stdout.decode("utf-8", errors="replace")
    inode_match = re.search(r"Inode:\s+(\d+)", stat_text)
    place = re.search(r"located at block (\d+), offset (0x[0-9a-fA-F]+)", imap_text)
    if not inode_match or not place:
        raise ImageError(f"could not locate {path} in the filesystem")
    inum = int(inode_match.group(1))
    inode_at = int(place.group(1)) * layout["block_size"] + int(place.group(2), 16)
    inode_size = layout["inode_size"]
    with image.open("r+b") as handle:
        handle.seek(inode_at)
        inode = bytearray(handle.read(inode_size))
        if len(inode) != inode_size:
            raise ImageError(f"could not read the inode for {path}")
        if layout["metadata_csum"]:
            stored = struct.unpack_from("<H", inode, 0x7C)[0]
            if inode_size >= 0x84:
                stored |= struct.unpack_from("<H", inode, 0x82)[0] << 16
            if stored != _inode_csum(layout["csum_seed"], inum, inode):
                raise ImageError(f"the inode checksum for {path} does not match")
        blocks = _file_blocks(inode, layout["block_size"])
        capacity = len(blocks) * layout["block_size"]
        if len(data) > capacity:
            raise ImageError(f"{path} has no free space left in its existing blocks")
        old_size = struct.unpack_from("<I", inode, 4)[0]
        payload = data + b"\x00" * (min(old_size, capacity) - len(data) if len(data) < old_size else 0)
        offset = 0
        for number in blocks:
            chunk = payload[offset : offset + layout["block_size"]]
            if not chunk:
                break
            handle.seek(number * layout["block_size"])
            handle.write(chunk)
            offset += len(chunk)
        struct.pack_into("<I", inode, 4, len(data))
        if layout["metadata_csum"]:
            checksum = _inode_csum(layout["csum_seed"], inum, inode)
            struct.pack_into("<H", inode, 0x7C, checksum & 0xFFFF)
            if inode_size >= 0x84:
                struct.pack_into("<H", inode, 0x82, (checksum >> 16) & 0xFFFF)
        handle.seek(inode_at)
        handle.write(inode)
    written = read_bytes(image, path)
    if written != data:
        raise ImageError(f"{path} was not updated")


def _e2fsck(image: Path, flag: str) -> int:
    result = subprocess.run(["e2fsck", flag, str(image)], capture_output=True, text=True)
    if result.returncode in (0, 1, 2, 4):
        return result.returncode
    detail = (result.stderr or result.stdout).strip()
    raise ImageError(
        "could not check " + image.name + (": " + detail if detail else f" (e2fsck exit {result.returncode})")
    )


def settle(image: Path) -> bool:
    """Replay an open journal and repair the file table before it is edited.

    A preen that stops on an inconsistency is followed by a full repair.
    Returns whether e2fsck changed the image.
    """
    print(f"Checking {image.name} so its journal is closed.", flush=True)
    code = _e2fsck(image, "-p")
    if code == 4:
        print(f"Repairing {image.name}. The preen check could not finish it.", flush=True)
        code = _e2fsck(image, "-y")
        if code == 4:
            raise ImageError(f"could not repair {image.name}")
    return code != 0


def extract_partition(dump: Path, start_sector: int, size_sectors: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _fs_type(dest.parent) == "btrfs":
        # New images on a compressed btrfs cannot be loop-mounted until they
        # are rewritten. Keep later extracts uncompressed.
        subprocess.run(
            ["btrfs", "property", "set", str(dest.parent), "compression", "none"],
            capture_output=True,
            check=False,
        )
        subprocess.run(["chattr", "+C", str(dest.parent)], capture_output=True, check=False)
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


def _as_root(args: list[str]) -> list[str]:
    if os.geteuid() == 0:
        return args
    return ["sudo", "-n", *args]


def _fs_type(path: Path) -> str:
    result = subprocess.run(
        ["findmnt", "-no", "FSTYPE", "-T", str(path)],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _fuse2fs() -> str:
    """Return fuse2fs. This kernel ships the loop driver as a missing module."""
    found = shutil.which("fuse2fs")
    if found:
        return found
    if os.geteuid() != 0:
        raise ImageError(
            "fuse2fs is not installed, and this kernel has no usable loop devices. "
            "Install it with: sudo pacman -S fuse2fs"
        )
    print("Installing fuse2fs. This kernel has no usable loop devices.")
    result = subprocess.run(["pacman", "-S", "--needed", "--noconfirm", "fuse2fs"])
    if result.returncode != 0:
        raise ImageError("could not install fuse2fs. Install it with: pacman -S fuse2fs")
    found = shutil.which("fuse2fs")
    if not found:
        raise ImageError("fuse2fs is still not on PATH after install")
    return found


def _replay_journal(image: Path) -> None:
    """fuse2fs does not replay an ext4 journal, so e2fsck does that first."""
    print(f"Checking {image.name} before mount. This can take a few minutes...", flush=True)
    result = subprocess.run(
        _as_root(["e2fsck", "-p", str(image)]),
        capture_output=True,
        text=True,
    )
    if result.returncode in (0, 1, 2):
        return
    detail = (result.stderr or result.stdout).strip()
    raise ImageError(
        "could not check " + image.name + " before mounting"
        + (": " + detail if detail else f" (e2fsck exit {result.returncode})")
    )


@contextmanager
def mount_rw(image: Path):
    """Mount an ext image read-write through fuse2fs. Uses sudo when not already root."""
    binary = _fuse2fs()
    mountpoint = Path(tempfile.mkdtemp(prefix="beetle-mnt-"))
    try:
        _replay_journal(image)
        print(f"Mounting {image.name}...", flush=True)
        mounted = subprocess.run(
            _as_root([binary, "-o", "rw", str(image), str(mountpoint)]),
            capture_output=True,
            text=True,
        )
        if mounted.returncode != 0:
            detail = (mounted.stderr or mounted.stdout).strip()
            raise ImageError(
                "could not mount " + image.name + " read-write"
                + (": " + detail if detail else "")
            )
        for _ in range(50):
            if mountpoint.is_mount():
                break
            time.sleep(0.1)
        else:
            raise ImageError("fuse2fs returned before " + image.name + " was mounted")
        yield mountpoint
    finally:
        subprocess.run(_as_root(["umount", str(mountpoint)]), capture_output=True, check=False)
        if mountpoint.is_mount():
            subprocess.run(
                _as_root(["fusermount3", "-u", str(mountpoint)]),
                capture_output=True,
                check=False,
            )
        shutil.rmtree(mountpoint, ignore_errors=True)
