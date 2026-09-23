"""Services-partition patches that exist on a given robot."""

from __future__ import annotations

import json
from pathlib import Path

import images
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


def apply(image: Path) -> dict:
    return {
        "jetstream": _patch_jetstream(image),
        "backup_skip": _patch_backup_skip(image),
        "reject_unauthorized": _patch_reject(image),
    }
