"""BEetle's robot steps against a fake DFU toolkit (no USB)."""
import shutil
import tempfile
import unittest
from pathlib import Path

from beetle import flow


class FakeToolkit:
    def __init__(self, state="rcm", root=None):
        self.state, self.calls = state, []
        self.BACKUP_ROOT = Path(root or tempfile.mkdtemp())

    def devices(self):
        return [{"port": "1-2", "state": self.state}] if self.state else []

    def tool(self, name):
        return "/bin/" + name

    def enter_shofel_dfu(self, port, confirm_meerkat_rev02=False):
        self.calls.append(("enter_dfu", port, confirm_meerkat_rev02))
        self.state = "dfu"
        return {"port": port, "state": "dfu"}

    def available_backup_partitions(self, port, dfu_util):
        return port, None, {"var": 1, "rootfsA": 2}

    def backup_partitions(self, partitions, port, dfu_util, progress=None):
        self.calls.append(("backup", partitions, port))
        folder = self.BACKUP_ROOT / "partition-backup-1"
        folder.mkdir(parents=True)
        return {"status": "backup complete", "manifest": str(folder / "backup-manifest.json")}

    def set_mode_wifi_live(self, mode, ssid, password, open_network, port=None, confirmation=None,
                           network_status=None):
        self.calls.append(("mod", mode, ssid, password, open_network, port, network_status, confirmation({})))
        rollback = self.BACKUP_ROOT / "var-backup-new"
        rollback.mkdir(parents=True)
        operation = self.BACKUP_ROOT / "set-mode-wifi-1"
        operation.mkdir()
        return {"status": "verified", "operation_directory": str(operation), "backup": str(rollback / "var.img")}


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeToolkit()
        self.addCleanup(shutil.rmtree, self.api.BACKUP_ROOT, True)

    def test_rcm_robot_is_put_in_dfu_with_the_toolkit_loader(self):
        robot = flow.find_robot(self.api)
        self.assertEqual(flow.enter_dfu(self.api, robot), "1-2")
        self.assertEqual(self.api.calls, [("enter_dfu", "1-2", True)])

    def test_robot_already_in_dfu_is_used_as_is(self):
        self.api.state = "dfu"
        self.assertEqual(flow.enter_dfu(self.api, flow.find_robot(self.api)), "1-2")
        self.assertEqual(self.api.calls, [])

    def test_two_robots_are_refused(self):
        self.api.devices = lambda: [{"port": "1", "state": "rcm"}, {"port": "2", "state": "rcm"}]
        with self.assertRaises(flow.BeetleError):
            flow.find_robot(self.api)

    def test_backup_saves_every_partition(self):
        folder = flow.backup(self.api, "1-2")
        self.assertEqual(self.api.calls, [("backup", ("var", "rootfsA"), "1-2")])
        self.assertEqual(folder.name, "partition-backup-1")

    def test_mod_sets_int_developer_wifi_and_boot_screen_ip(self):
        flow.mod(self.api, "1-2", "Home", "secret123", False, keep_rollback=True)
        self.assertEqual(self.api.calls, [("mod", "int-developer", "Home", "secret123", False, "1-2", "install", True)])
        self.assertTrue((self.api.BACKUP_ROOT / "var-backup-new").is_dir())
        self.assertFalse((self.api.BACKUP_ROOT / "set-mode-wifi-1").exists())

    def test_declined_backup_leaves_no_copy_of_the_robot(self):
        earlier = self.api.BACKUP_ROOT / "var-backup-earlier"
        earlier.mkdir()
        flow.mod(self.api, "1-2", "Home", None, True, keep_rollback=False)
        self.assertFalse((self.api.BACKUP_ROOT / "var-backup-new").exists())
        self.assertTrue(earlier.is_dir(), "an older backup the user made must stay")


if __name__ == "__main__":
    unittest.main()
