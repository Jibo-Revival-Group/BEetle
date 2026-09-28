"""Publish-script checks. They do not read an eMMC dump."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "BEetle"))

import images  # noqa: E402

spec = importlib.util.spec_from_file_location("publish_auburn", ROOT / "publish-auburn.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class KnowledgePlaceholderTests(unittest.TestCase):
    def test_catalogs_stay_and_robot_identity_is_placeholder(self):
        identity = publish.PLACEHOLDER_IDENTITY
        self.assertIsNone(publish.knowledge_placeholder("/jibo/Knowledge/skills/be/idle/mims/nodes", identity))
        self.assertIsNone(publish.knowledge_placeholder("/jibo/Knowledge/error-codes/nodes", identity))
        self.assertIsNone(publish.knowledge_placeholder("/jibo/Knowledge/jibo/loop/nodes", identity))
        robot = json.loads(publish.knowledge_placeholder("/jibo/Knowledge/jibo/robot/nodes", identity))
        self.assertEqual(robot["data"]["serialNumber"], "BOJW-0000-0000-0000-0000")
        self.assertEqual(robot["data"]["id"], "Jibo")
        self.assertEqual(robot["data"]["cpuid"], "0000000000000000")
        self.assertNotIn("locationOverride", robot["data"])
        self.assertNotIn("SSID", robot["data"])
        media = json.loads(publish.knowledge_placeholder("/jibo/Knowledge/jibo/media/nodes", identity))
        self.assertEqual(media["edges"]["media"], [])
        self.assertEqual(media["type"], "root")
        other = json.loads(publish.knowledge_placeholder("/jibo/Knowledge/jibo/location/nodes", identity))
        self.assertEqual(other["data"], {})

    def test_strip_skills_rewrites_knowledge_without_old_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "skills.img"
            subprocess.run(
                ["dd", "if=/dev/zero", f"of={image}", "bs=1M", "count=32", "status=none"],
                check=True,
            )
            subprocess.run(["mkfs.ext4", "-F", "-b", "1024", str(image)], check=True, capture_output=True)
            old_robot = {
                "_id": "old",
                "type": "root",
                "data": {
                    "serialNumber": "BOJW-1000-0017-1011-0282",
                    "id": "Rust-Zero-Cabbage-Tweed",
                    "SSID": "vettestyle01",
                    "locationOverride": {"city": "Barrington"},
                },
            }
            old_media_root = {
                "_id": "media-root",
                "type": "root",
                "edges": {"media": ["photo-1"], "pending-upload": ["photo-1"], "pending-delete": []},
                "data": {},
            }
            old_media = {"_id": "photo-1", "type": "media", "data": {"path": "/jibo/Photos/cache/a.jpg", "type": "image"}}
            images.write_text(image, "/jibo/Knowledge/jibo/robot/nodes", json.dumps(old_robot))
            images.write_text(
                image,
                "/jibo/Knowledge/jibo/media/nodes",
                json.dumps(old_media_root) + "\n" + json.dumps(old_media),
            )
            images.write_text(image, "/jibo/Knowledge/jibo/location/nodes", json.dumps({"data": {"city": "Barrington"}}))
            images.write_text(image, "/jibo/Knowledge/skills/be/idle/mims/nodes", "KEEP\n")
            images.write_text(image, "/jibo/Knowledge/error-codes/nodes", "KEEP-CODES\n")
            publish.strip_skills(image)
            robot = json.loads(images.read_text(image, "/jibo/Knowledge/jibo/robot/nodes") or "")
            self.assertEqual(robot["data"]["serialNumber"], "BOJW-0000-0000-0000-0000")
            self.assertEqual(robot["data"]["id"], "Jibo")
            self.assertNotIn("Barrington", images.read_text(image, "/jibo/Knowledge/jibo/robot/nodes") or "")
            media_text = images.read_text(image, "/jibo/Knowledge/jibo/media/nodes") or ""
            self.assertNotIn("photo-1", media_text)
            self.assertNotIn("Photos", media_text)
            media = [json.loads(line) for line in media_text.splitlines() if line.strip()]
            self.assertEqual([doc["type"] for doc in media], ["root"])
            self.assertEqual(media[0]["edges"]["media"], [])
            location = images.read_text(image, "/jibo/Knowledge/jibo/location/nodes") or ""
            self.assertNotIn("Barrington", location)
            self.assertEqual(images.read_text(image, "/jibo/Knowledge/skills/be/idle/mims/nodes"), "KEEP\n")
            self.assertEqual(images.read_text(image, "/jibo/Knowledge/error-codes/nodes"), "KEEP-CODES\n")
            loop = images.read_text(image, "/jibo/Knowledge/jibo/loop/nodes") or ""
            self.assertIn("Owner", loop)
            self.assertIn("Friend", loop)


if __name__ == "__main__":
    unittest.main()
