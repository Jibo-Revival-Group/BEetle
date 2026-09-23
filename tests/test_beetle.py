"""Unit tests for BEetle patch helpers. They do not touch a robot."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gpt  # noqa: E402
import images  # noqa: E402
import patch_rootfs  # noqa: E402
import patch_skills  # noqa: E402
import patch_var  # noqa: E402
import sector_diff  # noqa: E402

CELESTE = Path("/home/amber/BEcosystem/Celeste-Modem-Okra-Suede.bin")


class GptTests(unittest.TestCase):
    def test_celeste_layout(self):
        if not CELESTE.is_file():
            self.skipTest("Celeste dump is not on this machine")
        found = gpt.require_jibo_layout(gpt.load_gpt(CELESTE))
        self.assertEqual(found["var"].start_sector, 8294434)
        self.assertEqual(found["rootfsA"].start_sector, 34)
        self.assertIn("skills", found)


class SectorDiffTests(unittest.TestCase):
    def test_only_changed_sectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            patched = Path(tmp) / "patched"
            blob = bytearray(b"\0" * 4096)
            base.write_bytes(blob)
            blob[512] = 1
            blob[1024] = 2
            blob[1025] = 3
            patched.write_bytes(blob)
            ranges = sector_diff.changed_ranges(base, patched)
            self.assertEqual([(item.start, item.count) for item in ranges], [(1, 2)])


class FreshnessTests(unittest.TestCase):
    def test_mount_stamp_is_not_allocation_drift(self):
        import freshness
        dump_sb = bytearray(b"\0" * 128)
        live_sb = bytearray(dump_sb)
        live_sb[48:52] = b"\x01\x00\x00\x00"
        live_sb[52:54] = b"\x02\x00"
        self.assertFalse(freshness.allocation_changed(dump_sb, live_sb))
        self.assertTrue(freshness.mount_stamp_changed(dump_sb, live_sb))
        live_sb[12:16] = b"\x10\x00\x00\x00"
        self.assertTrue(freshness.allocation_changed(dump_sb, live_sb))


class VarPatchTests(unittest.TestCase):
    def test_oobe_var_becomes_normal_without_touching_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "var.img"
            subprocess.run(
                ["dd", "if=/dev/zero", f"of={image}", "bs=1M", "count=32", "status=none"],
                check=True,
            )
            subprocess.run(["mkfs.ext4", "-F", "-b", "4096", str(image)], check=True, capture_output=True)
            identity = {
                "serial_number": "BOJW-TEST-0001",
                "name": "Test-Robot",
                "cpuid": "0011223344556677",
                "wifi_mac": "00:11:22:33:44:55",
            }
            images.mkdir(image, "/jibo/lps")
            images.mkdir(image, "/jibo/keys")
            images.write_text(image, "/jibo/identity.json", json.dumps(identity))
            images.write_text(image, "/jibo/mode.json", json.dumps({"mode": "oobe"}))
            images.write_text(image, "/etc/wpa_supplicant.conf", "country=US\n")
            before = images.read_bytes(image, "/jibo/identity.json")
            self.assertEqual(patch_var.assess(image), "oobe")
            summary = patch_var.apply(image, "HomeNet", "secret-psk")
            self.assertEqual(summary["serial_number"], "BOJW-TEST-0001")
            self.assertEqual(images.read_bytes(image, "/jibo/identity.json"), before)
            self.assertEqual(patch_var.assess(image), "provisioned")
            creds = json.loads(images.read_text(image, "/jibo/credentials.json"))
            self.assertEqual(creds["endpoint"], "http://joap.5x1.com:80")
            self.assertEqual(creds["region"], "api")
            self.assertTrue(creds["accessKeyId"])
            self.assertTrue(creds["secretAccessKey"])
            marker = json.loads(images.read_text(image, "/jibo/beetle-setup.json"))
            self.assertTrue(marker["pending"])
            wpa = images.read_text(image, "/etc/wpa_supplicant.conf")
            self.assertIn('ssid="HomeNet"', wpa)
            self.assertIn('psk="secret-psk"', wpa)
            keys = json.loads(images.read_text(image, "/jibo/keys/keypair.json"))
            self.assertIn("BEGIN RSA PRIVATE KEY", keys["PrivateKey"])
            self.assertIn("BEGIN PUBLIC KEY", keys["PublicKey"])
            lps = images.list_dir(image, "/jibo/lps")
            self.assertEqual(lps, [])


class FirewallTests(unittest.TestCase):
    def test_removes_s30_and_s21(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "root.img"
            subprocess.run(
                ["dd", "if=/dev/zero", f"of={image}", "bs=1M", "count=16", "status=none"],
                check=True,
            )
            subprocess.run(["mkfs.ext4", "-F", str(image)], check=True, capture_output=True)
            images.mkdir(image, "/etc/init.d")
            images.write_text(image, "/etc/init.d/S30firewall", "#!/bin/sh\n")
            images.write_text(image, "/etc/init.d/S21firewall", "#!/bin/sh\n")
            images.write_text(image, "/etc/init.d/S50sshd", "#!/bin/sh\n")
            result = patch_rootfs.apply(image)
            self.assertEqual(result["firewall_removed"], ["/etc/init.d/S21firewall", "/etc/init.d/S30firewall"])
            self.assertFalse(images.exists(image, "/etc/init.d/S30firewall"))
            self.assertTrue(images.exists(image, "/etc/init.d/S50sshd"))


class SkillsTextTests(unittest.TestCase):
    def test_reject_unauthorized_swap(self):
        updated = patch_skills.patch_reject_unauthorized("rejectUnauthorized: true")
        self.assertEqual(updated, "rejectUnauthorized: false")
        self.assertEqual(
            patch_skills.patch_reject_unauthorized("rejectUnauthorized: false"),
            "rejectUnauthorized: false",
        )


class RealRootfsTests(unittest.TestCase):
    def test_celeste_firewall_name(self):
        image = Path("/tmp/celeste-rootfsA.img")
        if not image.is_file():
            self.skipTest("extracted Celeste rootfs is not available")
        names = patch_rootfs.firewall_scripts(image)
        self.assertIn("S30firewall", names)
        self.assertNotIn("S50sshd", names)


if __name__ == "__main__":
    unittest.main()
