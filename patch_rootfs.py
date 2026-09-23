"""Disable the stock firewall init script on rootfs A and B."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import images

FIREWALL_NAME = re.compile(r"^S\d+firewall$")
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
CA_LINK = "/etc/ssl/certs/4042bcee.0"
REJECT_PATH = "/usr/lib/node_modules/@jibo/jibo-server-client/lib/http/node.js"


def firewall_scripts(image: Path) -> list[str]:
    names = images.list_dir(image, "/etc/init.d")
    return sorted(name for name in names if FIREWALL_NAME.match(name))


def apply(image: Path, ca_file: Path | None = None) -> dict:
    removed = []
    for name in firewall_scripts(image):
        path = f"/etc/init.d/{name}"
        if images.remove(image, path):
            removed.append(path)

    ca_installed = False
    if ca_file is not None and ca_file.is_file() and images.exists(image, "/etc/ssl/certs"):
        pem = ca_file.read_text(encoding="utf-8")
        if "BEGIN CERTIFICATE" not in pem:
            raise images.ImageError(f"{ca_file} is not a PEM certificate")
        bundle = images.read_text(image, CA_BUNDLE) or ""
        if pem.strip() not in bundle:
            images.write_text(image, CA_BUNDLE, bundle.rstrip() + "\n" + pem.strip() + "\n")
        images.write_bytes(image, CA_LINK, pem.encode("utf-8"))
        ca_installed = True

    reject = False
    text = images.read_text(image, REJECT_PATH)
    if text is not None and "rejectUnauthorized: true" in text:
        images.write_text(
            image,
            REJECT_PATH,
            text.replace("rejectUnauthorized: true", "rejectUnauthorized: false"),
        )
        reject = True

    return {"firewall_removed": removed, "ca_installed": ca_installed, "reject_unauthorized": reject}


def copy_image(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
