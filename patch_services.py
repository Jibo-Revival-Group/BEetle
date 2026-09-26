"""Services-partition patches that exist on a given robot."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import images
import patch_skills
import patch_var

BACKUP_NEEDLE = "this._backupHelper((bkError, maxError) => {"
BACKUP_MARKER = "this._doLog('Skipping pre-OTA backup');"
BACKUP_REPLACEMENT = (
    BACKUP_MARKER
    + "\n            return callback();\n            "
    + BACKUP_NEEDLE
)
JETSTREAM_PATH = "/etc/jibo-jetstream-service.json"
REJECT_PATH = "/bin/jibo-ssm/node_modules/@jibo/jibo-server-client/lib/http/node.js"
BENCH_DIRS = ("bin", "etc", "lib", "sbin", "share", "var", "BluetopiaPM")
STAMP_VERSION = 1
STAMP_PATH = "etc/beetle-bench.json"
STARTUP_VIEW = "bin/jibo-ssm/startup/startup-view.js"
# Only the success path. The error path has the same mode check with different lines after it.
SUCCESS_MODE_CHECK = """        //nothing gets to be on screen if not in int-developer mode or developer mode
        if (this._mode !== 'int-developer' && this._mode !== 'developer') {
            return;
        }
        //change to green
"""
SUCCESS_MODE_REPLACEMENT = """        var self = this;
        function lanAddress() {
            var ip = null, os, ifs, ns, i, j, a, list;
            try {
                os = require('os');
                ifs = os.networkInterfaces();
                ns = Object.keys(ifs);
                for (i = 0; i < ns.length; i++) {
                    list = ifs[ns[i]] || [];
                    for (j = 0; j < list.length; j++) {
                        a = list[j];
                        if ((a.family === 'IPv4' || a.family === 4) && !a.internal) ip = a.address;
                    }
                }
            } catch (e) {}
            return ip || '\\u2026';
        }
        function drawAddress() {
            self._clearScreen();
            self.X.ChangeGC(self.gc, {foreground:0xffffff});
            self.X.PolyText8(self.wid, self.gc, 80, 380, [lanAddress()]);
        }
        drawAddress();
        if (this._ipTimer) clearInterval(this._ipTimer);
        this._ipTimer = setInterval(drawAddress, 2000);
        if (this._mode !== 'int-developer' && this._mode !== 'developer') {
            return;
        }
        //change to green
"""


class ServicesPatchError(RuntimeError):
    pass


def _contains(image: Path, needle: str) -> bool:
    encoded = needle.encode("utf-8")
    tail = b""
    with image.open("rb") as stream:
        while True:
            chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                return False
            blob = tail + chunk
            if encoded in blob:
                return True
            tail = chunk[-(len(encoded) - 1):] if len(encoded) > 1 else b""


def _patch_jetstream(image: Path) -> bool:
    text = images.read_text(image, JETSTREAM_PATH)
    if text is None:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ServicesPatchError(f"{JETSTREAM_PATH} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ServicesPatchError(f"{JETSTREAM_PATH} is not a JSON object")
    hub = data.get("HubClient")
    if not isinstance(hub, dict):
        hub = {}
        data["HubClient"] = hub
    hub["override"] = {
        "hub_port": patch_var.HUB_PORT,
        "hub_hostname": patch_var.HUB_HOST,
        "entrypoint_hostname": patch_var.HUB_HOST,
    }
    images.write_text(image, JETSTREAM_PATH, json.dumps(data, indent=4))
    return True


def _patch_backup_skip(image: Path) -> list[str]:
    if not _contains(image, BACKUP_NEEDLE):
        return []
    patched: list[str] = []
    with images.mount_rw(image) as root:
        for dirpath, dirnames, filenames in os_walk_skip(root):
            for name in filenames:
                if not name.endswith(".js"):
                    continue
                path = Path(dirpath) / name
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if BACKUP_NEEDLE not in text or BACKUP_MARKER in text:
                    continue
                path.write_text(text.replace(BACKUP_NEEDLE, BACKUP_REPLACEMENT), encoding="utf-8")
                patched.append(str(path.relative_to(root)))
    return patched


def os_walk_skip(root):
    import os
    skip = {"node_modules"}
    for dirpath, dirnames, filenames in os.walk(root):
        # The backup site lives in SSM lib, not inside nested node_modules copies
        # of unrelated packages. Still search jibo-ssm itself; skip only when the
        # directory being walked is named node_modules below a lib folder.
        dirnames[:] = [name for name in dirnames if name not in skip or "jibo-ssm" in dirpath]
        yield dirpath, dirnames, filenames


def _patch_reject(image: Path) -> bool:
    text = images.read_text(image, REJECT_PATH)
    if text is None or "rejectUnauthorized: true" not in text:
        return False
    images.write_text(
        image,
        REJECT_PATH,
        text.replace("rejectUnauthorized: true", "rejectUnauthorized: false"),
    )
    return True


def default_bench_root() -> Path:
    return Path(__file__).resolve().parent.parent / "BEnch"


def show_lan_address(text: str) -> str:
    """Draw the LAN address on the BEnch X11 startup window in normal mode."""
    if "function lanAddress()" in text:
        return text
    if SUCCESS_MODE_CHECK not in text:
        raise ServicesPatchError("BEnch startup view has no normal-mode success check to replace")
    return text.replace(SUCCESS_MODE_CHECK, SUCCESS_MODE_REPLACEMENT, 1)


def _stamp_current(root: Path) -> bool:
    path = root / STAMP_PATH
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("version") == STAMP_VERSION


def install_bench(image: Path, bench_root: Path | None = None) -> bool:
    """Replace /usr/local with the sibling BEnch tree. Returns False when already installed."""
    source_root = (bench_root or default_bench_root()).resolve() / "usr" / "local"
    if not (source_root / "bin").is_dir():
        raise ServicesPatchError(f"BEnch tree not found at {source_root}")
    with images.mount_rw(image) as root:
        if _stamp_current(root):
            return False
        for name in BENCH_DIRS:
            source = source_root / name
            dest = root / name
            if not source.exists():
                continue
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            elif dest.exists() or dest.is_symlink():
                dest.unlink()
            shutil.copytree(source, dest, symlinks=True, ignore=patch_skills._ignore_copy)
        view = root / STARTUP_VIEW
        if view.is_file():
            view.write_text(show_lan_address(view.read_text(encoding="utf-8")), encoding="utf-8")
        stamp = root / STAMP_PATH
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps({"version": STAMP_VERSION}) + "\n", encoding="utf-8")
    return True


def apply(image: Path, bench_root: Path | None = None) -> dict:
    installed = install_bench(image, bench_root)
    return {
        "bench": installed,
        "jetstream": _patch_jetstream(image),
        "backup_skip": _patch_backup_skip(image),
        "reject_unauthorized": _patch_reject(image),
    }
