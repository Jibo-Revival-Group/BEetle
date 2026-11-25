"""BEep's USB helper: the DFU Mod Toolkit's own code (copied into dfu/toolkit at build time),
run as a separate program so the app itself never needs administrator rights.

  beep_dfu.py status          one JSON line: {"robots": [{"port", "state"}], "usb_helper_needed": bool}
  beep_dfu.py int-developer   RCM -> DFU if needed, set int-developer and install the boot-screen Wi-Fi/IP
                              status. No backup is kept (a var copy made for the write is deleted after it verifies).
  beep_dfu.py backup          RCM -> DFU if needed, then back up every partition to ~/Jibo-Backups.
  beep_dfu.py usb-helper      Windows: install the UsbDk driver (Windows asks for permission).
  beep_dfu.py self-check      CI: every bundled tool runs and the toolkit loads.

Progress is plain text; the last line is `BEEP_RESULT {json}`.
"""
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent / "toolkit")
EXE = ".exe" if sys.platform == "win32" else ""
LIBUSB = HERE / "lib" / {"win32": "libusb-1.0.dll", "darwin": "libusb-1.0.dylib"}.get(sys.platform, "libusb-1.0.so.0")
USBDK_MSI = HERE / "windows" / "UsbDk_x64.msi"
MODE = "int-developer"


def configure():
    sys.path.insert(0, str(HERE))
    os.environ["PATH"] = str(HERE / "tools") + os.pathsep + os.environ.get("PATH", "")
    if LIBUSB.is_file():
        os.environ["JIBO_LIBUSB"] = str(LIBUSB)
    if sys.platform == "win32":
        os.environ.setdefault("CYGWIN", "nodosfilewarning")  # the bundled Cygwin debugfs/e2fsck
        # keep dfu-util, ShofEL and debugfs from flashing console windows
        original = subprocess.Popen.__init__

        def init(self, *args, **kwargs):
            kwargs.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
            original(self, *args, **kwargs)
        subprocess.Popen.__init__ = init


def usb_helper_needed():
    """Windows only: libusb reaches Jibo through the signed UsbDk driver, installed once."""
    return sys.platform == "win32" and subprocess.run(["sc", "query", "UsbDk"], capture_output=True).returncode != 0


def install_usb_helper():
    script = ("$p = Start-Process msiexec.exe -ArgumentList '/i','\"{}\"','/qn','/norestart' -Verb RunAs -Wait -PassThru; "
              "exit $p.ExitCode").format(str(USBDK_MSI).replace("'", "''"))
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True)
    if result.returncode not in (0, 3010) or usb_helper_needed():
        raise RuntimeError("The USB driver was not installed. Try again and choose Yes when Windows asks.")
    return {"status": "installed"}


def robot(api):
    """The one Jibo on USB, moved from RCM into the toolkit's RAM DFU loader if needed. Returns its port."""
    found = api.devices()
    if not found:
        raise RuntimeError("No Jibo in RCM or DFU mode was found on USB.")
    if len(found) > 1:
        raise RuntimeError("More than one Jibo is plugged in. Unplug all but one.")
    if found[0]["state"] == "dfu":
        return found[0]["port"]
    # Every retail Jibo has the Meerkat Rev02 board the toolkit's loader is built for.
    return api.enter_shofel_dfu(found[0]["port"], confirm_meerkat_rev02=True)["port"]


def int_developer(api):
    """int-developer, then the boot-screen Wi-Fi/IP status (it needs a developer mode, and new files in
    var, so the toolkit installs it with a whole-var edit that first saves a copy of var)."""
    port, yes = robot(api), lambda plan: True
    copies_before = set(api.BACKUP_ROOT.glob("var-backup-*")) if api.BACKUP_ROOT.is_dir() else set()
    try:
        mode = api.set_mode_file_live(MODE, port=port, confirmation=yes, guided=True, backup=False)
        previous = mode.get("previous_mode")
    except api.FileRpcStatusError as exc:
        if exc.status not in (3, 4):  # same fallback as the toolkit's menu: a layout or journal the loader can't edit
            raise
        print("Jibo's var needs a whole-partition edit for the mode change.", flush=True)
        mode = api.set_mode_live(MODE, port=port, confirmation=yes)
        previous = mode.get("current_mode")
    if mode.get("status") not in ("verified", "already current", "unchanged"):
        raise RuntimeError("The mode was not changed: " + str(mode.get("status")))
    print("Installing the Wi-Fi/IP status on Jibo's boot screen…", flush=True)
    screen = api.boot_network_status_live("install", port=port, confirmation=yes)
    if screen.get("status") not in ("verified", "unchanged"):
        raise RuntimeError("The Wi-Fi screen was not installed: " + str(screen.get("status")))
    # Both writes verified: drop what they left behind, including any var copy made just for them.
    for folder in [mode.get("operation_directory"), screen.get("operation_directory")] + \
            sorted(set(api.BACKUP_ROOT.glob("var-backup-*")) - copies_before):
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
    return {"status": "verified", "previous_mode": previous, "mode": MODE, "wifi_screen": True}


def backup(api):
    port = robot(api)
    _, _, available = api.available_backup_partitions(port)
    result = api.backup_partitions(tuple(available), port)
    if result.get("status") != "backup complete":
        raise RuntimeError("The backup did not finish: " + str(result.get("message") or result.get("status")))
    return {"status": result["status"], "folder": str(Path(result["manifest"]).parent)}


def self_check(api):
    report = {}
    for name, args in (("dfu-util", ("--version",)), ("shofel2_t124", ("--dfu-stage-capability",)),
                       ("debugfs", ("-V",)), ("e2fsck", ("-V",))):
        run = subprocess.run([str(HERE / "tools" / (name + EXE)), *args], capture_output=True, text=True, timeout=30)
        output = (run.stdout + run.stderr).strip()
        if run.returncode or (name == "shofel2_t124" and output != "dfu-stage-launch=1"):
            raise RuntimeError(name + " failed: " + output)
        report[name] = output.splitlines()[0]
    import ctypes
    ctypes.CDLL(str(LIBUSB))
    if not api.DEFAULT_LOADER.is_file():
        raise RuntimeError("the RAM loader is missing: " + str(api.DEFAULT_LOADER))
    if sys.platform != "win32" or not usb_helper_needed():  # listing needs UsbDk on Windows
        report["usb_devices"] = len(api.devices())
    report["no_backup_option"] = "backup" in api.set_mode_file_live.__code__.co_varnames
    import jibo_images
    report["wifi_screen_files"] = len(jibo_images.boot_network_status_assets())
    return report


def main(argv):
    configure()
    if argv and argv[0].endswith("jibo_dfu_pipeline.py"):
        # The toolkit starts its Linux DFU helper as `sys.executable helper.py ...`.
        sys.argv = argv
        runpy.run_path(str(HERE / "jibo_dfu_pipeline.py"), run_name="__main__")
        return 0
    command = argv[0] if argv else ""
    try:
        if command == "usb-helper":
            result = install_usb_helper()
        elif command == "status":
            needed = usb_helper_needed()
            import jibo_dfu as api
            result = {"robots": [] if needed else api.devices(), "usb_helper_needed": needed}
        elif command in ("int-developer", "backup", "self-check"):
            if usb_helper_needed() and command != "self-check":
                raise RuntimeError("Install the USB driver first.")
            import jibo_dfu as api
            api.calibration_service.CALIBRATION_SHARING_AVAILABLE = False  # BEep never shares robot data
            result = {"int-developer": int_developer, "backup": backup, "self-check": self_check}[command](api)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except Exception as exc:  # the toolkit's messages are written for people; pass them on
        print("BEEP_RESULT " + json.dumps({"ok": False, "error": str(exc)}), flush=True)
        return 1
    print("BEEP_RESULT " + json.dumps(dict(result, ok=True)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
