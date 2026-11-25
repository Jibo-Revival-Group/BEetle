"""The USB helper's steps against a fake toolkit (no robot needed): python3 -m unittest discover -s tests -p "test_*.py"."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dfu"))
import beep_dfu  # noqa: E402


class FakeToolkit:
    def __init__(self, state):
        self.state, self.calls = state, []

    def devices(self):
        return [{"port": "1-2", "state": self.state}] if self.state else []

    def enter_shofel_dfu(self, port, confirm_meerkat_rev02=False):
        self.calls.append(("enter", port, confirm_meerkat_rev02))
        return {"port": "1-2"}

    def set_mode_file_live(self, mode, **kwargs):
        self.calls.append(("mode", mode, kwargs["backup"], kwargs["confirmation"]({})))
        return {"status": "verified", "previous_mode": "normal"}

    def available_backup_partitions(self, port):
        return port, "tag", {"var": {}, "services": {}}

    def backup_partitions(self, partitions, port):
        self.calls.append(("backup", partitions, port))
        return {"status": "backup complete", "manifest": "/home/u/Jibo-Backups/Jibo/2026/backup-set.json"}


class StepsTests(unittest.TestCase):
    def test_int_developer_enters_dfu_from_rcm_and_skips_the_backup(self):
        api = FakeToolkit("rcm")
        result = beep_dfu.int_developer(api)
        self.assertEqual(api.calls, [("enter", "1-2", True), ("mode", "int-developer", False, True)])
        self.assertEqual(result, {"status": "verified", "previous_mode": "normal", "mode": "int-developer"})

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
