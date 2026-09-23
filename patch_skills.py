"""Bake the sibling BEam tree into the skills (/opt) partition."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import images

SKILL_DIRS = ("@be", "oobe-config", "jibo-diagnostics", "jibo-tbd", "fin-goods-test")
CA_NAME = "isrgrootx1.pem"
CA_HASH_NAME = "4042bcee.0"
REJECT_FROM = "rejectUnauthorized: true"
REJECT_TO = "rejectUnauthorized: false"
REJECT_PATHS = (
    "jibo/Jibo/Skills/@be/be/node_modules/@jibo/jibo-server-client/lib/http/node.js",
    "jibo/Jibo/Skills/oobe-config/node_modules/@jibo/jibo-server-client/lib/http/node.js",
)


class SkillsPatchError(RuntimeError):
    pass


def default_beam_root() -> Path:
    return Path(__file__).resolve().parent.parent / "BEam"


def ca_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / CA_NAME


def patch_reject_unauthorized(text: str) -> str:
    if REJECT_FROM not in text:
        if REJECT_TO in text:
            return text
        raise SkillsPatchError("rejectUnauthorized assignment was not found")
    return text.replace(REJECT_FROM, REJECT_TO)


def _chmod_tree(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o755)
        for name in filenames:
            path = Path(dirpath) / name
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def _ignore_copy(_directory: str, names: list[str]) -> set[str]:
    skip = {".git", ".github", ".DS_Store"}
    return {name for name in names if name in skip}


def apply(image: Path, beam_root: Path | None = None) -> dict:
    beam = (beam_root or default_beam_root()).resolve()
    be_root = beam / "@be" / "be"
    if not be_root.is_dir():
        raise SkillsPatchError(f"BEam skill host not found at {be_root}")
    cert = ca_path()
    if not cert.is_file():
        raise SkillsPatchError(f"ISRG Root X1 certificate is missing: {cert}")

    copied: list[str] = []
    patched: list[str] = []
    with images.mount_rw(image) as root:
        skills = root / "jibo" / "Jibo" / "Skills"
        if not skills.is_dir():
            skills.mkdir(parents=True)
        for name in SKILL_DIRS:
            source = beam / name
            if not source.is_dir():
                if name == "@be":
                    raise SkillsPatchError(f"required skill directory missing: {source}")
                continue
            dest = skills / name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(source, dest, ignore=_ignore_copy, symlinks=True)
            _chmod_tree(dest)
            copied.append(name)
        if not (skills / "@be" / "be" / "index.html").is_file():
            raise SkillsPatchError("baked skills tree is missing @be/be/index.html")
        if not (skills / "@be" / "be" / "setup-screen.js").is_file():
            raise SkillsPatchError(
                "baked @be/be is missing setup-screen.js; update the sibling BEam checkout"
            )

        for relative in (
            "jibo/Knowledge/beacon",
            "jibo/Knowledge/jukebox/music",
            "tmp/beacon",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
            os.chmod(root / relative, 0o777)

        ca_dest = root / "jibo" / "openjibo-ca.crt"
        shutil.copyfile(cert, ca_dest)
        os.chmod(ca_dest, 0o644)

        for relative in REJECT_PATHS:
            target = root / relative
            if not target.is_file():
                continue
            original = target.read_text(encoding="utf-8", errors="replace")
            updated = patch_reject_unauthorized(original)
            if updated != original:
                target.write_text(updated, encoding="utf-8")
                patched.append(relative)

    return {"skills": copied, "reject_unauthorized": patched}
