"""The USB helper's steps against a fake toolkit (no robot needed): python3 -m unittest discover -s tests -p "test_*.py"."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dfu"))
import beep_dfu  # noqa: E402


class FakeToolkit:
    class FileRpcStatusError(Exception):
        def __init__(self, status):
            super().__init__(status)
            self.status = status

    def __init__(self, state, root=None, journal=False):
        self.state, self.calls, self.journal = state, [], journal
        self.BACKUP_ROOT = Path(root or tempfile.mkdtemp())

    def devices(self):
        return [{"port": "1-2", "state": self.state}] if self.state else []

    def enter_shofel_dfu(self, port, confirm_meerkat_rev02=False):
        self.calls.append(("enter", port, confirm_meerkat_rev02))
        return {"port": "1-2"}

    def _operation(self, prefix):
        folder = self.BACKUP_ROOT / (prefix + "-x")
        folder.mkdir(parents=True)
        return str(folder)

    def set_mode_file_live(self, mode, **kwargs):
        if self.journal:
            raise self.FileRpcStatusError(4)
        self.calls.append(("mode", mode, kwargs["backup"], kwargs["confirmation"]({})))
        return {"status": "verified", "previous_mode": "normal", "operation_directory": self._operation("file-transaction")}

    def set_mode_live(self, mode, port, confirmation):
        self.calls.append(("mode-full", mode))
        (self.BACKUP_ROOT / "var-backup-mode").mkdir(parents=True)  # the toolkit's automatic copy
        return {"status": "verified", "current_mode": "normal", "operation_directory": self._operation("set-mode")}

    def configure_wifi_file_live(self, ssid, password, open_network, port, confirmation, guided):
        if self.journal:
            raise self.FileRpcStatusError(4)
        self.calls.append(("wifi-file", ssid, password, open_network, confirmation({})))
        return {"status": "verified", "wifi_server_check_hook_added": True}

    def configure_wifi_live(self, ssid, password, open_network, port, confirmation):
        self.calls.append(("wifi-full", ssid, password, open_network))
        return {"status": "verified"}

    def boot_network_status_live(self, action, port, confirmation):
        self.calls.append(("wifi-screen", action, confirmation({})))
        if not (self.BACKUP_ROOT / "var-backup-mode").exists():
            (self.BACKUP_ROOT / "var-backup-screen").mkdir()
        return {"status": "verified", "operation_directory": self._operation("boot-network-status")}

    def available_backup_partitions(self, port):
        return port, "tag", {"var": {}, "services": {}}

    def backup_partitions(self, partitions, port):
        self.calls.append(("backup", partitions, port))
        return {"status": "backup complete", "manifest": "/home/u/Jibo-Backups/Jibo/2026/backup-set.json"}


class StepsTests(unittest.TestCase):
    def test_int_developer_enters_dfu_sets_the_mode_without_backup_and_installs_the_wifi_screen(self):
        api = FakeToolkit("rcm")
        (api.BACKUP_ROOT / "var-backup-earlier").mkdir()  # the user's own older copy stays
        result = beep_dfu.int_developer(api)
        self.assertEqual(api.calls, [("enter", "1-2", True), ("mode", "int-developer", False, True),
                                     ("wifi-screen", "install", True)])
        self.assertEqual(result, {"status": "verified", "previous_mode": "normal", "mode": "int-developer", "wifi_screen": True})
        self.assertEqual([p.name for p in api.BACKUP_ROOT.iterdir()], ["var-backup-earlier"])

    def test_dirty_journal_falls_back_to_the_whole_var_mode_change(self):
        api = FakeToolkit("dfu", journal=True)
        result = beep_dfu.int_developer(api)
        self.assertEqual(api.calls, [("mode-full", "int-developer"), ("wifi-screen", "install", True)])
        self.assertEqual(result["previous_mode"], "normal")
        self.assertEqual(list(api.BACKUP_ROOT.iterdir()), [])

    def test_a_failed_wifi_screen_keeps_the_var_copy(self):
        api = FakeToolkit("dfu")
        api.boot_network_status_live = lambda *a, **k: ((api.BACKUP_ROOT / "var-backup-screen").mkdir(), {"status": "failed"})[1]
        with self.assertRaisesRegex(RuntimeError, "Wi-Fi screen was not installed"):
            beep_dfu.int_developer(api)
        self.assertTrue((api.BACKUP_ROOT / "var-backup-screen").is_dir())

    def test_wifi_uses_the_toolkits_quick_write_with_its_startup_fixes(self):
        api = FakeToolkit("rcm")
        result = beep_dfu.wifi(api, {"ssid": "Home", "password": "hunter22", "open": False})
        self.assertEqual(api.calls, [("enter", "1-2", True), ("wifi-file", "Home", "hunter22", False, True)])
        self.assertEqual(result, {"status": "verified", "ssid": "Home", "startup_fixed": True})

    def test_wifi_falls_back_to_the_whole_var_write_and_open_networks_send_no_password(self):
        api = FakeToolkit("dfu", journal=True)
        beep_dfu.wifi(api, {"ssid": "Cafe", "password": "ignored", "open": True})
        self.assertEqual(api.calls, [("wifi-full", "Cafe", None, True)])

    def test_backup_saves_every_partition_without_reentering_dfu(self):
        api = FakeToolkit("dfu")
        result = beep_dfu.backup(api)
        self.assertEqual(api.calls, [("backup", ("var", "services"), "1-2")])
        self.assertEqual(Path(result["folder"]), Path("/home/u/Jibo-Backups/Jibo/2026"))

    def test_no_robot_is_a_plain_message(self):
        with self.assertRaisesRegex(RuntimeError, "No Jibo"):
            beep_dfu.int_developer(FakeToolkit(None))


if __name__ == "__main__":
    unittest.main()
