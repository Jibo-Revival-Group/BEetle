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

CELESTE = Path("/home/amber/BEcosystem/Celeste-Modem-Okra-Suede.bin")


class GptTests(unittest.TestCase):
    def test_celeste_layout(self):
        if not CELESTE.is_file():
            self.skipTest("Celeste dump is not on this machine")
        found = gpt.require_jibo_layout(gpt.load_gpt(CELESTE))
        self.assertEqual(found["var"].start_sector, 8294434)
        self.assertEqual(found["rootfsA"].start_sector, 34)
        self.assertIn("skills", found)

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
            wpa = images.read_text(image, "/etc/wpa_supplicant.conf")
            self.assertIn('ssid="HomeNet"', wpa)
            self.assertIn('psk="secret-psk"', wpa)
            keys = json.loads(images.read_text(image, "/jibo/keys/keypair.json"))
            self.assertIn("BEGIN RSA PRIVATE KEY", keys["PrivateKey"])
            self.assertIn("BEGIN PUBLIC KEY", keys["PublicKey"])
            lps = images.list_dir(image, "/jibo/lps")
            self.assertEqual(lps, [])

    def test_apply_wifi_does_not_touch_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "var.img"
            subprocess.run(
                ["dd", "if=/dev/zero", f"of={image}", "bs=1M", "count=16", "status=none"],
                check=True,
            )
            subprocess.run(["mkfs.ext4", "-F", "-b", "1024", str(image)], check=True, capture_output=True)
            identity = '{"serial_number":"BOJW-1","cpuid":"ABCDEF0123456789","name":"Celeste"}\n'
            images.write_text(image, "/jibo/identity.json", identity)
            images.write_text(
                image,
                "/etc/network/interfaces",
                "auto wlan0\niface wlan0 inet dhcp\n\tpost-up wireless-startup\n",
            )
            patch_var.apply_wifi(image, "WIFI", "secret")
            written = images.read_text(image, "/etc/wpa_supplicant.conf") or ""
            self.assertIn('ssid="WIFI"', written)
            self.assertIn('psk="secret"', written)
            self.assertIn("pre-up wireless-startup", images.read_text(image, "/etc/network/interfaces") or "")
            self.assertEqual(images.read_text(image, "/jibo/identity.json"), identity)
            self.assertIsNone(images.read_text(image, "/jibo/credentials.json"))


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

    def test_placeholder_people_seed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(patch_skills.seed_placeholders(root), "seeded")
            nodes = (root / "jibo" / "Knowledge" / "jibo" / "loop" / "nodes").read_text()
            docs = [json.loads(line) for line in nodes.splitlines() if line.strip()]
            names = [
                (doc.get("data") or {}).get("firstName")
                for doc in docs
                if doc.get("type") == "user"
            ]
            self.assertEqual(names, ["Owner", None, "Friend"])
            robot = next(doc for doc in docs if (doc.get("data") or {}).get("type") == "robot")
            self.assertNotIn("firstName", robot["data"])
            self.assertEqual(patch_skills.seed_placeholders(root), "kept")

    def test_startup_view_draws_lan_address(self):
        import patch_services
        source = Path(__file__).resolve().parents[2] / "BEnch" / "usr" / "local" / "bin" / "jibo-ssm" / "startup" / "startup-view.js"
        if not source.is_file():
            self.skipTest("BEnch startup view is not on this machine")
        updated = patch_services.show_lan_address(source.read_text(encoding="utf-8"))
        self.assertIn("function lanAddress()", updated)
        self.assertEqual(updated, patch_services.show_lan_address(updated))


class RealRootfsTests(unittest.TestCase):
    def test_celeste_firewall_name(self):
        image = Path("/tmp/celeste-rootfsA.img")
        if not image.is_file():
            self.skipTest("extracted Celeste rootfs is not available")
        names = patch_rootfs.firewall_scripts(image)
        self.assertIn("S30firewall", names)
        self.assertNotIn("S50sshd", names)



class FlashTests(unittest.TestCase):
    def test_var_is_never_a_flash_target(self):
        import beetle
        import dfu_flash

        self.assertEqual(
            beetle._partition_list(None),
            ["rootfsA", "rootfsB", "services", "skills"],
        )
        self.assertEqual(
            beetle._flash_names(None, True),
            ["var", "rootfsA", "rootfsB", "services", "skills"],
        )
        with self.assertRaises(beetle.BeetleError):
            beetle._partition_list("rootfsA,var")
        self.assertEqual(beetle.main(["--partitions", "var", "/tmp/does-not-matter.bin"]), 2)
        self.assertEqual(beetle.main(["--setup", "--partitions", "skills", "/tmp/does-not-matter.bin"]), 2)
        self.assertEqual(beetle.main([]), 2)
        self.assertEqual(beetle.main(["--dump", "--dump-var"]), 2)
        self.assertEqual(beetle.main(["--dump", "/tmp/does-not-matter.bin"]), 2)
        self.assertEqual(beetle.main(["--dump-var", "--setup"]), 2)

    def test_splice_places_bytes_at_the_partition_offset(self):
        import dfu_flash

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "piece"
            dest = root / "image"
            source.write_bytes(b"abc")
            dest.write_bytes(b"\0" * 8)
            dfu_flash._splice(source, dest, 3)
            self.assertEqual(dest.read_bytes(), b"\0\0\0abc\0\0")
        with self.assertRaises(dfu_flash.DfuFlashError):
            dfu_flash.write_partitions({}, "", ["var"], {}, {}, Path("/tmp"), False)

    def test_skills_chunks_cover_the_partition(self):
        import dfu_flash

        capacity = (10 * 1024 * 1024 * 1024) + (100 * 512)
        chunks = dfu_flash.skills_chunks(capacity)
        self.assertEqual(chunks[0]["name"], "skills-000")
        self.assertEqual(chunks[0]["offset_bytes"], 0)
        self.assertEqual(sum(chunk["size_bytes"] for chunk in chunks), capacity)
        self.assertLess(chunks[-1]["size_bytes"], dfu_flash.SKILLS_CHUNK_BYTES)

    def test_missing_dfu_tools_say_how_to_build(self):
        import dfu_flash

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(dfu_flash.DfuFlashError) as caught:
                dfu_flash.require_tools(Path(tmp))
        self.assertIn("./dfu/build.sh", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
