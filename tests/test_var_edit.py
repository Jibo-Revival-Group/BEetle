"""BEetle's exact var edit (int-developer, Wi-Fi with a password, the Wi-Fi screen patch) on a small
ext4 image, with real debugfs/e2fsck. On Windows CI these are the Cygwin builds BEetle bundles."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dfu"))
import jibo_images as images  # noqa: E402


HAVE_E2FS = all(shutil.which(tool) for tool in ("mke2fs", "debugfs", "e2fsck"))
if not HAVE_E2FS and os.environ.get("BEETLE_REQUIRE_E2FS"):
    raise RuntimeError("e2fsprogs is not on PATH")


@unittest.skipUnless(HAVE_E2FS, "needs e2fsprogs")
class VarEditTest(unittest.TestCase):
    def test_int_developer_wifi_and_boot_screen_status_in_one_copy(self):
        # A folder name with a space, like many Windows user folders.
        with tempfile.TemporaryDirectory(prefix="beetle var ") as temporary:
            work = Path(temporary)
            source, edited = work / "source.ext4", work / "edited.ext4"
            with source.open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
            subprocess.run(("mke2fs", "-F", "-q", "-t", "ext4", "-b", "1024", images._host_path(source)),
                           check=True, capture_output=True)
            for folder in ("/jibo", "/etc", "/etc/network"):
                images._run_debugfs(source, "mkdir " + folder, writable=True)
            files = {images.VAR_MODE_PATH: b'{"mode":"oobe"}\n',
                     images.VAR_WIFI_PATH: b"update_config=1\nnetwork={\n    ssid=4a49424f\n    key_mgmt=NONE\n}\n",
                     images.VAR_INTERFACES_PATH: b"auto lo\niface lo inet loopback\n\nauto wlan0\niface wlan0 inet dhcp\n"
                                                 b"\tpost-up wpa_supplicant -B -i wlan0 -c /var/etc/wpa_supplicant.conf\n"}
            for index, (path, content) in enumerate(files.items()):
                local = work / "file{}".format(index)
                local.write_bytes(content)
                images._run_debugfs(source, "write " + images._debugfs_arg(local) + " " + path, writable=True)
            original = images.sha256_file(source)

            result = images.edit_mode_wifi(source, edited, "int-developer", "Home Wi-Fi", "correct horse",
                                           False, network_status="install")

            self.assertEqual(result["previous_mode"], "oobe")
            self.assertEqual(images.sha256_file(source), original, "the original copy is never changed")
            mode = images._extract(edited, images.VAR_MODE_PATH, work / "check-mode")
            wifi = images._extract(edited, images.VAR_WIFI_PATH, work / "check-wifi")
            self.assertEqual(json.loads(mode)["mode"], "int-developer")
            self.assertIn(b"ssid=486f6d652057692d4669", wifi)
            self.assertNotIn(b"correct horse", wifi, "the password is saved as a key, not as typed")
            interfaces = images._extract(edited, images.VAR_INTERFACES_PATH, work / "check-interfaces")
            self.assertIn(images.BOOT_NETWORK_STATUS_HOOK.encode(), interfaces)
            script = images._extract(edited, images.BOOT_NETWORK_STATUS_DIR + "/boot-network-status.sh", work / "check-status")
            self.assertEqual(script, images.boot_network_status_assets()["boot-network-status.sh"])


if __name__ == "__main__":
    unittest.main()
