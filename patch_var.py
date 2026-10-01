"""Offline /var patches for an OOBE Jibo."""

from __future__ import annotations

import json
import secrets
import string
import subprocess
from pathlib import Path

import images

HUB_HOST = "api.5x1.com"
HUB_PORT = 443
# BEaker. No account login. The same fields BEach writes on a running robot.
OTA_ENDPOINT = "http://joap.5x1.com:80"


class VarPatchError(RuntimeError):
    pass


def _load_json(image: Path, path: str) -> dict | None:
    text = images.read_text(image, path)
    if text is None or not text.strip():
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VarPatchError(f"{path} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise VarPatchError(f"{path} is not a JSON object")
    return data


def robot_identity(image: Path) -> dict:
    data = _load_json(image, "/jibo/identity.json")
    if not data or not data.get("serial_number") or not data.get("cpuid"):
        raise VarPatchError("var image is missing /jibo/identity.json serial_number or cpuid")
    return data


def assess(image: Path) -> str:
    """Return ``oobe`` or ``provisioned``.

    A robot is provisioned only when mode is already ``normal`` and cloud
    keys exist. A failed stock OOBE (Wi-Fi tried, server unreachable) stays
    ``oobe``.
    """
    mode = _load_json(image, "/jibo/mode.json") or {}
    creds = _load_json(image, "/jibo/credentials.json") or {}
    has_keys = bool(creds.get("accessKeyId") and creds.get("secretAccessKey"))
    if mode.get("mode") == "normal" and has_keys:
        return "provisioned"
    return "oobe"


def _random_id(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _wpa_config(ssid: str, psk: str) -> str:
    if not ssid or not ssid.strip():
        raise VarPatchError("Wi-Fi SSID is required")
    if any(char in ssid + (psk or "") for char in ("\n", "\r", "\x00")):
        raise VarPatchError("Wi-Fi SSID and password cannot contain newlines")

    def quote(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    if psk:
        body = (
            f'    ssid="{quote(ssid)}"\n'
            "    scan_ssid=1\n"
            f'    psk="{quote(psk)}"\n'
            "    key_mgmt=WPA-PSK\n"
        )
    else:
        body = f'    ssid="{quote(ssid)}"\n    scan_ssid=1\n    key_mgmt=NONE\n'
    return (
        "ctrl_interface=/var/run/wpa_supplicant\n"
        "update_config=1\n"
        "country=US\n"
        "\n"
        "network={\n"
        + body
        + "}\n"
    )


def bring_wifi_up_before_dhcp(text: str) -> str:
    """wlan0 used to run DHCP before wpa_supplicant, so it never got an address."""
    text = text.replace("\nauto wlp1s0\n", "\n#auto wlp1s0\n")
    old = (
        "auto wlan0\n"
        "iface wlan0 inet dhcp\n"
        "\tpost-up wireless-startup\n"
        "\tpre-down wpa_cli -i wlan0 terminate\n"
        "\tudhcpc_opts -R -b -t 3 -T 5 -A 5\n"
    )
    new = (
        "auto wlan0\n"
        "iface wlan0 inet dhcp\n"
        "\tpre-up wireless-startup\n"
        "\tpre-up sleep 8\n"
        "\tpre-down wpa_cli -i wlan0 terminate\n"
        "\tudhcpc_opts -b -t 30 -T 2 -A 2\n"
    )
    if old in text:
        return text.replace(old, new, 1)
    return text.replace("\tpost-up wireless-startup\n", "\tpre-up wireless-startup\n\tpre-up sleep 8\n", 1)


def _generate_keypair() -> dict[str, str]:
    private_run = subprocess.run(
        ["openssl", "genrsa", "-traditional", "2048"],
        capture_output=True,
    )
    if private_run.returncode != 0:
        private_run = subprocess.run(["openssl", "genrsa", "2048"], capture_output=True, check=True)
    private = private_run.stdout
    if b"PRIVATE KEY" not in private:
        raise VarPatchError("openssl did not produce a private key")
    public = subprocess.run(
        ["openssl", "rsa", "-pubout"],
        input=private,
        capture_output=True,
        check=True,
    ).stdout
    return {
        "PrivateKey": private.decode("ascii").strip() + "\n",
        "PublicKey": public.decode("ascii").strip() + "\n",
    }


def _credentials(existing: dict | None) -> dict:
    creds = dict(existing or {})
    if not creds.get("accessKeyId") or not creds.get("secretAccessKey"):
        creds["accessKeyId"] = _random_id(20)
        creds["secretAccessKey"] = _random_id(40)
    creds["region"] = "api"
    creds["endpoint"] = OTA_ENDPOINT
    ordered = {
        "secretAccessKey": creds["secretAccessKey"],
        "region": "api",
        "endpoint": OTA_ENDPOINT,
        "accessKeyId": creds["accessKeyId"],
    }
    return ordered


def _walk_files(image: Path, directory: str) -> list[str]:
    found: list[str] = []
    for name in images.list_dir(image, directory):
        if name in ("tmp", "lost+found"):
            continue
        child = f"{directory.rstrip('/')}/{name}"
        if images.is_directory(image, child):
            found.extend(_walk_files(image, child))
        elif name == "mode.json":
            found.append(child)
    return found


def find_mode_json(image: Path) -> str:
    """Return the mode.json AutoMod edits, found by listing the var file table."""
    found = _walk_files(image, "/")
    if "/jibo/mode.json" in found:
        return "/jibo/mode.json"
    if len(found) == 1:
        return found[0]
    if not found:
        raise VarPatchError("var has no mode.json")
    raise VarPatchError("var has more than one mode.json: " + ", ".join(found))


def _mode_text(current: dict) -> str:
    text = json.dumps(current)
    if not text.endswith("\n"):
        text += "\n"
    return text


def set_mode_normal(image: Path) -> str:
    """Set mode.json to normal. Other fields in that file stay. Returns its path."""
    path = find_mode_json(image)
    current = _load_json(image, path) or {}
    current["mode"] = "normal"
    images.write_text(image, path, json.dumps(current))
    written = _load_json(image, path) or {}
    if written.get("mode") != "normal":
        raise VarPatchError(f"{path} was not set to normal")
    return path


def set_mode_inplace(image: Path) -> tuple[str, bool]:
    """Change mode.json to normal without allocating blocks or touching other files.

    Returns the path and whether its bytes changed.
    """
    path = find_mode_json(image)
    current = _load_json(image, path) or {}
    if current.get("mode") == "normal":
        return path, False
    current["mode"] = "normal"
    data = _mode_text(current).encode("utf-8")
    existing = images.read_bytes(image, path)
    if existing == data:
        return path, False
    try:
        images.rewrite_file_bytes(image, path, data)
    except images.ImageError as exc:
        raise VarPatchError(str(exc)) from exc
    written = _load_json(image, path) or {}
    if written.get("mode") != "normal":
        raise VarPatchError(f"{path} was not set to normal")
    return path, True


def ensure_credentials(image: Path) -> None:
    """Create cloud credentials and a keypair when they are missing.

    An existing keypair is left alone. Identity is not modified.
    """
    identity = robot_identity(image)
    before_identity = images.read_bytes(image, "/jibo/identity.json")
    creds = _credentials(_load_json(image, "/jibo/credentials.json"))
    images.write_text(image, "/jibo/credentials.json", json.dumps(creds))
    if images.read_bytes(image, "/jibo/keys/keypair.json") is None:
        images.write_text(image, "/jibo/keys/keypair.json", json.dumps(_generate_keypair()))
    if images.read_bytes(image, "/jibo/identity.json") != before_identity:
        raise VarPatchError("identity.json changed while writing credentials; refusing to continue")
    written = _load_json(image, "/jibo/credentials.json")
    if not written or written.get("endpoint") != OTA_ENDPOINT or written.get("region") != "api":
        raise VarPatchError("credentials.json was not written correctly")
    if not written.get("accessKeyId") or not written.get("secretAccessKey"):
        raise VarPatchError("credentials.json is missing keys")
    if not images.read_bytes(image, "/jibo/keys/keypair.json"):
        raise VarPatchError("keypair.json was not written")
    if identity.get("serial_number") != robot_identity(image).get("serial_number"):
        raise VarPatchError("identity.json changed while writing credentials; refusing to continue")


def apply_wifi(image: Path, ssid: str, psk: str) -> None:
    """Write a Wi-Fi network. Does not change identity, keys, or credentials."""
    images.write_text(image, "/etc/wpa_supplicant.conf", _wpa_config(ssid, psk))
    interfaces = images.read_text(image, "/etc/network/interfaces")
    if interfaces and "wlan0" in interfaces:
        images.write_text(image, "/etc/network/interfaces", bring_wifi_up_before_dhcp(interfaces))


def apply(image: Path, ssid: str, psk: str) -> dict:
    """Patch var in place. Identity, LPS calibration, and SSH host keys stay."""
    identity = robot_identity(image)
    before_identity = images.read_bytes(image, "/jibo/identity.json")

    images.write_text(image, "/etc/wpa_supplicant.conf", _wpa_config(ssid, psk))
    interfaces = images.read_text(image, "/etc/network/interfaces")
    if interfaces and "wlan0" in interfaces:
        images.write_text(image, "/etc/network/interfaces", bring_wifi_up_before_dhcp(interfaces))

    ensure_credentials(image)

    images.write_text(image, "/jibo/mode.json", json.dumps({"mode": "normal"}))

    after_identity = images.read_bytes(image, "/jibo/identity.json")
    if after_identity != before_identity:
        raise VarPatchError("identity.json changed during the var patch; refusing to continue")

    written = _load_json(image, "/jibo/credentials.json")
    if not written or written.get("endpoint") != OTA_ENDPOINT or written.get("region") != "api":
        raise VarPatchError("credentials.json was not written correctly")
    if not written.get("accessKeyId") or not written.get("secretAccessKey"):
        raise VarPatchError("credentials.json is missing keys")
    mode = _load_json(image, "/jibo/mode.json") or {}
    if mode.get("mode") != "normal":
        raise VarPatchError("mode.json was not set to normal")

    return {
        "name": identity.get("name"),
        "serial_number": identity.get("serial_number"),
        "cpuid": identity.get("cpuid"),
        "endpoint": OTA_ENDPOINT,
        "hub": f"{HUB_HOST}:{HUB_PORT}",
    }
