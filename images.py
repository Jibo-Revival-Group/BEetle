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
