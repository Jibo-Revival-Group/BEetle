"""Offline boot-network-status delivery checks; fixtures are synthetic."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import jibo_images as images


STOCK = (b"# keep stock comments\nauto lo\niface lo inet loopback\n\n"
         b"auto wlan0\niface wlan0 inet dhcp\n\tpost-up wireless-startup\n"
         b"\tpre-down wpa_cli -i wlan0 terminate\n")


class InterfacesTests(unittest.TestCase):
    def test_install_hook_is_in_loopback_not_wifi(self):
        edited = images.build_boot_network_status_startup(STOCK, "install")
        self.assertIn(b"iface lo inet loopback\n\tpost-up /bin/sh ", edited)
        self.assertLess(edited.index(b"boot-network-status.sh"), edited.index(b"auto wlan0"))
        self.assertIn(b"boot-network-status.sh || true\n", edited)


    def test_repeated_install_is_byte_identical(self):
        once = images.build_boot_network_status_startup(STOCK, "install")
        self.assertEqual(images.build_boot_network_status_startup(once, "install"), once)
        self.assertEqual(once.count(b"boot-network-status.sh"), 1)

    def test_removal_restores_original_including_cloud_hook(self):
        stock, _, _ = images.build_stock_wifi_startup(STOCK)
        once = images.build_boot_network_status_startup(stock, "install")
        removed = images.build_boot_network_status_startup(once, "remove")
        self.assertEqual(removed, stock)
        self.assertEqual(images.build_boot_network_status_startup(removed, "remove"), stock)
        self.assertIn(b"testJiboServer = true;", once)
        self.assertIn(b"post-up wireless-startup", once)

    def test_crlf_and_comments_survive_install_remove(self):
        stock = STOCK.replace(b"\n", b"\r\n").replace(
            b"iface lo inet loopback", b"iface  lo  inet  loopback # comment")
        installed = images.build_boot_network_status_startup(stock, "install")
        self.assertNotIn(b"\n", installed.replace(b"\r\n", b""))
        self.assertEqual(images.build_boot_network_status_startup(installed, "remove"), stock)

    def test_unknown_or_ambiguous_layouts_are_refused(self):
        bad = (
            STOCK.replace(b"auto lo", b"auto eth0"),
            STOCK.replace(b"iface lo inet loopback", b"iface lo inet static"),
            STOCK + b"iface lo inet loopback\n",
            STOCK + b"source /etc/network/interfaces.d/*\n",
            STOCK + b"\tpost-up /bin/sh /var/jibo/phoenix/network-status/custom.sh\n",
            STOCK.replace(b"iface lo inet loopback", b"iface lo inet6 loopback"),
            b"not utf8 \xff",
        )
        for stock in bad:
            with self.subTest(stock=stock):
                with self.assertRaises(images.ImageError):
                    images.build_boot_network_status_startup(stock, "install")


@unittest.skipUnless(all(shutil.which(tool) for tool in ("mke2fs", "debugfs", "e2fsck")),
                     "ext4 tools are required")
class ImageInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / "stock.ext4"
        with self.source.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024)
        subprocess.run(["mke2fs", "-F", "-q", "-t", "ext4", "-b", "1024", str(self.source)],
                       check=True, capture_output=True)
        for path in ("/jibo", "/etc", "/etc/network", "/log"):
            images._run_debugfs(self.source, "mkdir " + path, writable=True)
        for path, content in ((images.VAR_MODE_PATH, b'{"mode":"oobe","keep":"synthetic"}\n'),
                              (images.VAR_WIFI_PATH, b"update_config=1\n"),
                              (images.VAR_INTERFACES_PATH, STOCK),
                              ("/jibo/identity.json", b'{"synthetic":"preserve"}\n')):
            local = self.work / "input"
            local.write_bytes(content)
            images._run_debugfs(self.source, "write " + str(local) + " " + path, writable=True)

    def get(self, image, path, optional=False):
        return images._extract(image, path, self.work / "readback", optional=optional)

    def test_combined_install_is_in_the_same_var_image_and_preserves_identity(self):
        before = images.sha256_file(self.source)
        destination = self.work / "installed.ext4"
        result = images.edit_mode_wifi(self.source, destination, "int-developer", "Synthetic Wi-Fi",
                                      open_network=True, network_status="install")
        self.assertEqual(result["boot_network_status"], "install")
        self.assertEqual(images.sha256_file(self.source), before)
        self.assertIn(b"int-developer", self.get(destination, images.VAR_MODE_PATH))
        self.assertIn(b"boot-network-status.sh", self.get(destination, images.VAR_INTERFACES_PATH))
        assets = Path(images.__file__).parent / "assets/boot-network-status"
        for name in images.boot_network_status_assets():
            self.assertEqual(self.get(destination, images.BOOT_NETWORK_STATUS_DIR + "/" + name),
                             (assets / name).read_bytes())
        self.assertEqual(self.get(destination, "/jibo/identity.json"),
                         b'{"synthetic":"preserve"}\n')
        images._check_ext4(destination)


    def test_broken_variant_pin_is_refused_before_an_image_is_written(self):
        import json
        original = images.boot_network_status_assets()
        manifest = json.loads(original["manifest.json"])
        manifest["variants"][0]["stock_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            for name, content in original.items():
                (fixture / name).write_bytes(content)
            (fixture / "manifest.json").write_text(json.dumps(manifest))
            with patch.object(images, "Path") as mocked_path:
                mocked_path.return_value.resolve.return_value.parent.__truediv__.return_value = fixture
                with self.assertRaises(images.ImageError):
                    images.boot_network_status_assets()

    def test_existing_feature_directory_is_normalized_without_touching_parents(self):
        for path in ("/jibo/phoenix", images.BOOT_NETWORK_STATUS_DIR):
            images._run_debugfs(self.source, "mkdir " + path, writable=True)
        images._run_debugfs(self.source, "set_inode_field " + images.BOOT_NETWORK_STATUS_DIR + " mode 040777", writable=True)
        destination = self.work / "normalized.ext4"
        images.edit_mode_wifi(self.source, destination, "int-developer", "Synthetic", open_network=True,
                              network_status="install")
        stat = images._run_debugfs(destination, "stat " + images.BOOT_NETWORK_STATUS_DIR)
        self.assertRegex(stat, r"Mode:\s+0755\b")
        self.assertRegex(stat, r"User:\s+0\s+Group:\s+0\b")

    def test_standalone_remove_preserves_mode_wifi_and_unrelated_files(self):
        installed = self.work / "installed.ext4"
        images.edit_mode_wifi(self.source, installed, "int-developer", "Synthetic Wi-Fi",
                              open_network=True, network_status="install")
        owned_log = images.BOOT_NETWORK_STATUS_DIR + "/boot-network-status.log"
        unrelated_note = images.BOOT_NETWORK_STATUS_DIR + "/operator-note"
        for index, path in enumerate((owned_log, unrelated_note)):
            work = self.work / ("extra-" + str(index))
            work.mkdir()
            images._put_factory_file(installed, path, b"synthetic operator data", work, 0o644)
        removed = self.work / "removed.ext4"
        images.edit_boot_network_status(installed, removed, "remove")
        self.assertIsNone(self.get(removed, owned_log, True))
        self.assertEqual(self.get(removed, unrelated_note), b"synthetic operator data")
        for path in (images.VAR_MODE_PATH, images.VAR_WIFI_PATH, "/jibo/identity.json"):
            self.assertEqual(self.get(removed, path), self.get(installed, path))
        self.assertNotIn(b"boot-network-status.sh", self.get(removed, images.VAR_INTERFACES_PATH))
        for name in images.boot_network_status_assets():
            self.assertIsNone(self.get(removed, images.BOOT_NETWORK_STATUS_DIR + "/" + name, True))
        images._check_ext4(removed)

    def test_install_refuses_nondeveloper_mode_and_discards_candidate(self):
        destination = self.work / "refused.ext4"
        with self.assertRaisesRegex(images.ImageError, "developer mode"):
            images.edit_boot_network_status(self.source, destination, "install")
        self.assertFalse(destination.exists())


from types import SimpleNamespace
from unittest.mock import patch
import jibo_tui


class MenuInstallTests(unittest.TestCase):
    def test_developer_flow_defaults_on_and_uses_one_full_var_transaction(self):
        calls = []
        api = SimpleNamespace(set_mode_wifi_live=lambda *args, **kwargs:
                              calls.append((args, kwargs)) or {"status": "verified"})
        readiness = jibo_tui.Readiness("dfu-ready", (), port="1-1")
        with patch.object(jibo_tui, "_select_mode", return_value="int-developer"), \
                patch.object(jibo_tui, "text_input", return_value="Synthetic Wi-Fi"), \
                patch.object(jibo_tui, "select_option", side_effect=("open", "install")) as select:
            result = jibo_tui.execute_action(api, "set-mode-wifi", readiness)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["network_status"], "install")
        self.assertEqual(select.call_args.kwargs["initial"], "install")
        self.assertIn("Show Wi-Fi status and IP on the boot screen", str(select.call_args.args))

    def test_remove_menu_uses_a_reviewed_full_var_transaction(self):
        calls = []
        api = SimpleNamespace(boot_network_status_live=lambda *args, **kwargs:
                              calls.append((args, kwargs)) or {"status": "verified"})
        readiness = jibo_tui.Readiness("dfu-ready", (), port="1-1")
        result = jibo_tui.execute_action(api, "remove-boot-network-status", readiness)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(calls[0][0], ("remove",))
        self.assertEqual(calls[0][1]["port"], "1-1")
        self.assertTrue(callable(calls[0][1]["confirmation"]))


import jibo_dfu
import io
from contextlib import redirect_stdout


class CommandTests(unittest.TestCase):
    def test_combined_cli_installs_by_default_in_developer_mode(self):
        with patch.object(jibo_dfu, "set_mode_wifi_live", return_value={"status": "verified"}) as live, \
                patch.object(jibo_dfu, "tool", return_value="fake-dfu"), redirect_stdout(io.StringIO()):
            self.assertEqual(jibo_dfu.main(["set-mode-wifi", "--mode", "int-developer",
                                           "--ssid", "Synthetic", "--open-network", "--yes"]), 0)
        self.assertEqual(live.call_args.kwargs["network_status"], "install")
        self.assertEqual(live.call_args.kwargs["confirmation"], "WRITE VAR")

    def test_removal_cli_uses_the_var_only_live_path(self):
        with patch.object(jibo_dfu, "boot_network_status_live", return_value={"status": "verified"}) as live, \
                patch.object(jibo_dfu, "tool", return_value="fake-dfu"), redirect_stdout(io.StringIO()):
            self.assertEqual(jibo_dfu.main(["boot-network-status", "remove", "--yes"]), 0)
        self.assertEqual(live.call_args.args[0], "remove")


if __name__ == "__main__":
    unittest.main()
