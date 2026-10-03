"""Bake the sibling BEam tree into the skills (/opt) partition."""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
import uuid
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
# Version 2 installs the native Jetstream Home Assistant command receiver.
STAMP_VERSION = 2
STAMP_PATH = "jibo/.beetle-skills.json"


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


def _is_human(doc: object) -> bool:
    if not isinstance(doc, dict) or doc.get("type") != "user":
        return False
    data = doc.get("data") or {}
    if not isinstance(data, dict) or data.get("type") == "robot":
        return False
    return bool(data.get("firstName"))


def seed_placeholders(root: Path) -> str:
    """Owner Placeholder, Friend Placeholder, and a robot member with no first name.

    Leave an existing human alone so a later flash does not wipe BEacon edits.
    """
    loop = root / "jibo" / "Knowledge" / "jibo" / "loop"
    loop.mkdir(parents=True, exist_ok=True)
    path = loop / "nodes"
    docs: list[object] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                docs.append(json.loads(line))
            except json.JSONDecodeError:
                docs.append(line)
    if any(_is_human(doc) for doc in docs):
        return "kept"

    now = int(time.time() * 1000)
    owner_id = str(uuid.uuid4())
    robot_id = str(uuid.uuid4())
    friend_id = str(uuid.uuid4())

    def user(node_id: str, data: dict) -> dict:
        return {
            "_id": node_id,
            "type": "user",
            "data": data,
            "created": now,
            "updated": now,
        }

    owner = user(owner_id, {
        "firstName": "Owner",
        "lastName": "Placeholder",
        "gender": "unknown",
        "type": "owner",
        "status": "accepted",
        "enrolled": {"face": False, "voice": False},
    })
    robot = user(robot_id, {
        "type": "robot",
        "status": "accepted",
        "enrolled": {"face": False, "voice": False},
    })
    friend = user(friend_id, {
        "firstName": "Friend",
        "lastName": "Placeholder",
        "gender": "unknown",
        "type": "member",
        "status": "accepted",
        "enrolled": {"face": False, "voice": False},
    })
    roots = [doc for doc in docs if isinstance(doc, dict) and doc.get("type") == "root"]
    if roots:
        root_node = roots[0]
    else:
        root_node = {
            "_id": str(uuid.uuid4()),
            "type": "root",
            "data": {},
            "created": now,
            "updated": now,
            "edges": {},
        }
        docs.append(root_node)
    edges = root_node.setdefault("edges", {})
    users = list(edges.get("user") or [])
    for node_id in (owner_id, robot_id, friend_id):
        if node_id not in users:
            users.append(node_id)
    edges["user"] = users
    edges["owner"] = [owner_id]
    edges["robot"] = [robot_id]
    root_node["updated"] = now
    docs.extend([owner, robot, friend])
    lines = []
    for doc in docs:
        if isinstance(doc, dict):
            lines.append(json.dumps(doc))
        else:
            lines.append(str(doc))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for directory in (
        root / "jibo" / "Knowledge",
        root / "jibo" / "Knowledge" / "jibo",
        loop,
    ):
        os.chmod(directory, 0o777)
    os.chmod(path, 0o666)
    return "seeded"


def _stamp_current(root: Path) -> bool:
    path = root / STAMP_PATH
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("version") == STAMP_VERSION


def _stamp_in_image(image: Path) -> bool:
    text = images.read_text(image, "/" + STAMP_PATH)
    if not text:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    return data.get("version") == STAMP_VERSION


def apply(image: Path, beam_root: Path | None = None) -> dict:
    beam = (beam_root or default_beam_root()).resolve()
    be_root = beam / "@be" / "be"
    if not be_root.is_dir():
        raise SkillsPatchError(f"BEam skill host not found at {be_root}")
    cert = ca_path()
    if not cert.is_file():
        raise SkillsPatchError(f"ISRG Root X1 certificate is missing: {cert}")

    if _stamp_in_image(image):
        print("BEam is already in this skills image.")
        return {
            "skills": [],
            "reject_unauthorized": [],
            "placeholders": "kept",
            "cached": True,
        }

    copied: list[str] = []
    patched: list[str] = []
    print("Mounting skills and copying BEam. This part takes a while.", flush=True)
    with images.mount_rw(image) as root:
        if _stamp_current(root):
            return {
                "skills": copied,
                "reject_unauthorized": patched,
                "placeholders": seed_placeholders(root),
                "cached": True,
            }
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

        placeholders = seed_placeholders(root)
        stamp = root / STAMP_PATH
        stamp.write_text(json.dumps({"version": STAMP_VERSION}) + "\n", encoding="utf-8")
        os.chmod(stamp, 0o644)

    return {
        "skills": copied,
        "reject_unauthorized": patched,
        "placeholders": placeholders,
    }
