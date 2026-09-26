"""Flash Jibo partitions over USB DFU.

ShofEL is used only to load the vendored RAM program. Partition reads and
writes then go through dfu-util, which is much faster than raw eMMC poking.
The loader, the GPT reader, and the ShofEL patch come from Jibo-DFU-Mod-Toolkit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import gpt

from dfu import bounded

DFU_DIR = Path(__file__).resolve().parent / "dfu"
LOADER_SHA256 = "8f46062f2d201824337093a1e4c154e3048c019b147930da35b9d62e00c5e689"
RCM = ("0955", "7740")
DFU_IDS = ("0955", "701a")
MARKER = "jibo-dfu-v1"
SKILLS_SECTOR_SIZE = 512
SKILLS_CHUNK_SECTORS = 0x200000
SKILLS_CHUNK_BYTES = SKILLS_SECTOR_SIZE * SKILLS_CHUNK_SECTORS
LAUNCH_LINE = "Starting verified ARM-state SPL at 0x80108000."
PROGRESS_VERSION = 1


class DfuFlashError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_tools(directory: Path | None = None) -> dict[str, Path]:
    root = directory or DFU_DIR
    loader = root / "loader.bin"
    shofel = root / "shofel2_t124"
    dfu_util = root / "dfu-util"
    missing = [
        name
        for name, path in (
            ("loader.bin", loader),
            ("shofel2_t124", shofel),
            ("intermezzo.bin", root / "intermezzo.bin"),
            ("dfu_stage2.bin", root / "dfu_stage2.bin"),
            ("dfu-util", dfu_util),
        )
        if not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        raise DfuFlashError(
            "DFU flash tools are missing ("
            + ", ".join(missing)
            + "). From BEetle, run ./dfu/build.sh once, then flash again."
        )
    if _sha256_file(loader) != LOADER_SHA256:
        raise DfuFlashError("dfu/loader.bin is not the pinned RAM DFU loader.")
    if not os.access(shofel, os.X_OK) or not os.access(dfu_util, os.X_OK):
        raise DfuFlashError("dfu/shofel2_t124 and dfu/dfu-util must be executable. Re-run ./dfu/build.sh.")
    capability = _run([str(shofel), "--dfu-stage-capability"], timeout=5, cwd=root).strip()
    if capability != "dfu-stage-launch=1":
        raise DfuFlashError(
            "The vendored ShofEL helper cannot start the RAM DFU loader. Re-run ./dfu/build.sh."
        )
    return {
        "loader": loader,
        "shofel": shofel,
        "dfu_util": dfu_util,
        "directory": root,
    }


def devices(root: Path = Path("/sys/bus/usb/devices")) -> list[dict[str, str]]:
    found = []
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*")):
        try:
            pair = tuple((path / name).read_text().strip().lower() for name in ("idVendor", "idProduct"))
        except OSError:
            continue
        if pair == RCM:
            found.append({"port": path.name, "state": "rcm"})
        elif pair == DFU_IDS:
            found.append({"port": path.name, "state": "dfu"})
    return found


def _run(argv: list[str], timeout: int | None = None, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DfuFlashError(str(exc)) from exc
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        detail = re.sub(r'(serial=")[^"]*(")', r"\1[redacted]\2", detail)
        raise DfuFlashError(argv[0] + " failed\n" + detail[-2000:])
    return result.stdout + result.stderr


def _run_visible(argv: list[str], cwd: Path | None = None) -> None:
    """Leave dfu-util's own progress on the terminal."""
    try:
        result = subprocess.run(argv, cwd=str(cwd) if cwd else None)
    except OSError as exc:
        raise DfuFlashError(str(exc)) from exc
    if result.returncode:
        raise DfuFlashError(argv[0] + " exited " + str(result.returncode))


def alternatives(dfu_util: Path, port: str) -> tuple[list[str], str]:
    output = _run([str(dfu_util), "-d", "0955:701a", "--path", port, "-l"], timeout=30)
    return re.findall(r'name="([^"]+)"', output), output


def enter(tools: dict[str, Path], timeout: int = 120) -> str:
    """Return the USB port of a robot that is already in DFU, or load the RAM program from RCM."""
    found = devices()
    dfu = [item for item in found if item["state"] == "dfu"]
    rcm = [item for item in found if item["state"] == "rcm"]
    if len(dfu) > 1 or len(rcm) > 1:
        raise DfuFlashError("More than one Jibo is connected. Unplug the extra one.")
    if dfu:
        port = dfu[0]["port"]
        names, _output = alternatives(tools["dfu_util"], port)
        if MARKER not in names:
            raise DfuFlashError("A DFU device is connected, but it is not the Jibo RAM loader.")
        print(f"Robot is already in DFU on USB port {port}.")
        return port
    if not rcm:
        raise DfuFlashError(
            "No Jibo in RCM or DFU. Hold the RCM button, press power, and release when the red LED is on."
        )
    port = rcm[0]["port"]
    print(
        "Loading the RAM DFU program through ShofEL "
        "(Meerkat Rev02 RAM profile, the one this loader was verified with)."
    )
    output = _run(
        [
            str(tools["shofel"]),
            "--usb-port-path",
            port,
            "DFU_STAGE",
            str(tools["loader"]),
            "--confirm-meerkat-rev02",
            "--launch",
        ],
        timeout=180,
        cwd=tools["directory"],
    )
    if LAUNCH_LINE not in output:
        raise DfuFlashError("ShofEL did not confirm that the RAM loader started.")
    print(f"Waiting for DFU on USB port {port}...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = devices()
        dfu = [item for item in current if item["state"] == "dfu"]
        same = [item for item in dfu if item["port"] == port]
        chosen = same[0] if same else (dfu[0] if len(dfu) == 1 else None)
        if chosen:
            names, _output = alternatives(tools["dfu_util"], chosen["port"])
            if MARKER not in names or "var" not in names:
                raise DfuFlashError("DFU appeared, but the loader is missing the Jibo partition names.")
            print(f"DFU is ready on USB port {chosen['port']}.")
            return chosen["port"]
        time.sleep(0.25)
    raise DfuFlashError("The RAM loader started, but the robot did not reappear as a DFU device.")


def read_layout(tools: dict[str, Path], port: str) -> dict[str, gpt.Partition]:
    try:
        raw = bounded.read_dfu_alt_prefix(port)
    except bounded.BoundedDfuError as exc:
        raise DfuFlashError(f"Could not read the partition map over DFU: {exc}") from exc
    try:
        return gpt.require_jibo_layout(gpt.parse_gpt(raw))
    except gpt.GptError as exc:
        raise DfuFlashError(f"The DFU partition map is not a Jibo layout: {exc}") from exc


def read_partition(tools: dict[str, Path], port: str, name: str, size: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    print(f"Reading {name} over DFU ({size / 1024 / 1024:.0f} MiB)...")
    try:
        _run_visible(
            [
                str(tools["dfu_util"]),
                "-d",
                "0955:701a",
                "--path",
                port,
                "-a",
                name,
                "-U",
                str(dest),
                "-Z",
                str(size),
            ]
        )
    except DfuFlashError:
        dest.unlink(missing_ok=True)
        raise
    if not dest.is_file() or dest.stat().st_size != size:
        actual = dest.stat().st_size if dest.is_file() else 0
        dest.unlink(missing_ok=True)
        raise DfuFlashError(f"DFU read of {name} returned {actual} bytes, expected {size}.")


def skills_chunks(capacity: int) -> list[dict[str, int | str]]:
    if capacity <= 0 or capacity % SKILLS_SECTOR_SIZE:
        raise DfuFlashError("The skills partition size is not a whole number of 512-byte sectors.")
    count = (capacity + SKILLS_CHUNK_BYTES - 1) // SKILLS_CHUNK_BYTES
    chunks = []
    for index in range(count):
        offset = index * SKILLS_CHUNK_BYTES
        chunks.append(
            {
                "name": f"skills-{index:03d}",
                "offset_bytes": offset,
                "size_bytes": min(SKILLS_CHUNK_BYTES, capacity - offset),
            }
        )
    return chunks


def _slice(source: Path, offset: int, size: int, dest: Path) -> None:
    with source.open("rb") as infile, dest.open("wb") as outfile:
        infile.seek(offset)
        remaining = size
        while remaining:
            block = infile.read(min(1024 * 1024, remaining))
            if not block:
                raise DfuFlashError("The skills image ended before this chunk.")
            outfile.write(block)
            remaining -= len(block)


def _download(tools: dict[str, Path], port: str, alt: str, image: Path) -> None:
    print(f"Writing {alt} over DFU ({image.stat().st_size / 1024 / 1024:.0f} MiB)...")
    _run_visible(
        [str(tools["dfu_util"]), "-d", "0955:701a", "--path", port, "-a", alt, "-D", str(image)]
    )


def _progress_path(work: Path) -> Path:
    return work / "dfu-write-progress.json"


def load_progress(work: Path) -> dict:
    path = _progress_path(work)
    if not path.is_file():
        return {"version": PROGRESS_VERSION, "done": [], "skills_chunks": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": PROGRESS_VERSION, "done": [], "skills_chunks": []}
    if data.get("version") != PROGRESS_VERSION:
        return {"version": PROGRESS_VERSION, "done": [], "skills_chunks": []}
    return {
        "version": PROGRESS_VERSION,
        "done": [name for name in data.get("done", []) if isinstance(name, str)],
        "skills_chunks": [name for name in data.get("skills_chunks", []) if isinstance(name, str)],
    }


def save_progress(work: Path, progress: dict) -> None:
    _progress_path(work).write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")


def write_partitions(
    tools: dict[str, Path],
    port: str,
    names: list[str],
    images: dict[str, Path],
    layout: dict[str, gpt.Partition],
    work: Path,
    resume: bool,
    allow_var: bool = False,
) -> None:
    if "var" in names and not allow_var:
        raise DfuFlashError("Refusing to write var. That partition stays on the robot.")
    alt_names, _output = alternatives(tools["dfu_util"], port)
    progress = load_progress(work) if resume else {"version": PROGRESS_VERSION, "done": [], "skills_chunks": []}
    if not resume:
        save_progress(work, progress)
    print("Writing over DFU. Skills is the long part; let the flash finish before unplugging.")
    for name in names:
        image = images[name]
        part = layout[name]
        if not image.is_file() or image.stat().st_size != part.size_bytes:
            raise DfuFlashError(f"{image} is missing or is not the live size of {name}.")
        if name in progress["done"]:
            print(f"{name} is already written. Skipping.")
            continue
        if name == "skills" and any(alt.startswith("skills-") for alt in alt_names):
            if "skills" in alt_names:
                raise DfuFlashError("The DFU loader lists both a full skills target and skills chunks.")
            _write_skills_chunks(tools, port, image, part.size_bytes, alt_names, work, progress)
        elif name in alt_names:
            _download(tools, port, name, image)
        else:
            raise DfuFlashError(f"The DFU loader does not expose {name}.")
        progress["done"].append(name)
        save_progress(work, progress)
        print(f"{name} write complete.")


def _write_skills_chunks(
    tools: dict[str, Path],
    port: str,
    image: Path,
    capacity: int,
    alt_names: list[str],
    work: Path,
    progress: dict,
) -> None:
    expected = skills_chunks(capacity)
    expected_names = [chunk["name"] for chunk in expected]
    found = [name for name in alt_names if name.startswith("skills-")]
    if set(found) != set(expected_names):
        raise DfuFlashError(
            "The skills chunk list does not match the partition size. "
            "Wanted " + ", ".join(expected_names) + "."
        )
    finished = set(progress["skills_chunks"])
    with tempfile.TemporaryDirectory(prefix="skills-chunk-", dir=work) as temporary:
        piece = Path(temporary) / "chunk.img"
        for index, chunk in enumerate(expected, 1):
            alt = str(chunk["name"])
            if alt in finished:
                print(f"Skipping finished {alt}.")
                continue
            _slice(image, int(chunk["offset_bytes"]), int(chunk["size_bytes"]), piece)
            print(f"Writing skills chunk {index}/{len(expected)} ({alt})...")
            _download(tools, port, alt, piece)
            progress["skills_chunks"].append(alt)
            save_progress(work, progress)
            piece.unlink(missing_ok=True)


def reset_robot(tools: dict[str, Path], port: str) -> None:
    print("Asking the robot to leave DFU and reboot.")
    _run_visible([str(tools["dfu_util"]), "-d", "0955:701a", "--path", port, "-e", "-R"])
