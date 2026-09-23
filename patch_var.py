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
OTA_ENDPOINT = "http://joap.5x1.com:80"
SETUP_MARKER = "/jibo/beetle-setup.json"


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
        body = f'    ssid="{quote(ssid)}"\n    psk="{quote(psk)}"\n    key_mgmt=WPA-PSK\n'
    else:
        body = f'    ssid="{quote(ssid)}"\n    key_mgmt=NONE\n'
    return (
        "ctrl_interface=/var/run/wpa_supplicant\n"
        "update_config=1\n"
        "country=US\n"
        "\n"
        "network={\n"
        + body
        + "}\n"
    )


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


def apply(image: Path, ssid: str, psk: str) -> dict:
    """Patch var in place. Identity, LPS calibration, and SSH host keys stay."""
    identity = robot_identity(image)
    before_identity = images.read_bytes(image, "/jibo/identity.json")

    images.write_text(image, "/etc/wpa_supplicant.conf", _wpa_config(ssid, psk))

    creds = _credentials(_load_json(image, "/jibo/credentials.json"))
    images.write_text(image, "/jibo/credentials.json", json.dumps(creds))

    if images.read_bytes(image, "/jibo/keys/keypair.json") is None:
        keypair = _generate_keypair()
        images.write_text(image, "/jibo/keys/keypair.json", json.dumps(keypair))

    images.write_text(image, "/jibo/mode.json", json.dumps({"mode": "normal"}))
    images.write_text(
        image,
        SETUP_MARKER,
        json.dumps({"pending": True, "version": 1}),
    )

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
    marker = _load_json(image, SETUP_MARKER) or {}
    if marker.get("pending") is not True:
        raise VarPatchError("beetle-setup.json was not marked pending")

    return {
        "name": identity.get("name"),
        "serial_number": identity.get("serial_number"),
        "cpuid": identity.get("cpuid"),
        "endpoint": OTA_ENDPOINT,
        "hub": f"{HUB_HOST}:{HUB_PORT}",
    }
