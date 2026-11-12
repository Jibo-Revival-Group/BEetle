"""The robot steps BEetle runs, in order. The DFU work is the DFU Mod Toolkit's own code (dfu/).

Every function takes the toolkit module as `api` so tests can pass a fake one.
"""
import shutil
import time
from pathlib import Path

MODE = "int-developer"


class BeetleError(RuntimeError):
    pass


def find_robot(api):
    """The one Jibo on USB as {"port", "state"} ("rcm" or "dfu"), or None."""
    found = api.devices()
    if len(found) > 1:
        raise BeetleError("More than one Jibo is plugged in. Unplug all but one.")
    return found[0] if found else None


def wait_for_robot(api, cancelled=lambda: False, interval=1.0):
    while not cancelled():
        robot = find_robot(api)
        if robot:
            return robot
        time.sleep(interval)
    return None


def enter_dfu(api, robot):
    """RCM -> DFU with ShofEL and the toolkit's RAM loader. Returns the DFU port."""
    if robot["state"] == "dfu":
        return robot["port"]
    # Every retail Jibo has the Meerkat Rev02 board the loader is built for.
    result = api.enter_shofel_dfu(robot["port"], confirm_meerkat_rev02=True)
    return result["port"]


def backup(api, port, progress=None):
    """Save every partition the robot offers to the user's Jibo-Backups folder."""
    dfu_util = api.tool("dfu-util")
    _, _, available = api.available_backup_partitions(port, dfu_util)
    result = api.backup_partitions(tuple(available), port, dfu_util, progress=progress)
    if result.get("status") != "backup complete":
        raise BeetleError("The backup did not finish: " + str(result.get("message") or result.get("status")))
    return Path(result["manifest"]).parent


def mod(api, port, ssid, password, open_network, keep_rollback):
    """Set int-developer mode, save Wi-Fi and install the boot-screen Wi-Fi/IP status in one
    verified var write. The toolkit always saves the current var first so a failed write can be
    undone; when the user turned down backups, BEetle deletes that copy after a verified write."""
    before = set(api.BACKUP_ROOT.glob("var-backup-*")) if api.BACKUP_ROOT.is_dir() else set()
    result = api.set_mode_wifi_live(MODE, ssid, password, open_network, port=port,
                                    confirmation=lambda plan: True, network_status="install")
    if result.get("status") not in ("verified", "unchanged"):
        raise BeetleError("Jibo's settings were not written: " + str(result.get("message") or result.get("status")))
    shutil.rmtree(result["operation_directory"], ignore_errors=True)
    if not keep_rollback:
        for created in set(api.BACKUP_ROOT.glob("var-backup-*")) - before:
            shutil.rmtree(created, ignore_errors=True)
    return result
