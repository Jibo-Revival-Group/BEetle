"""Where BEetle's bundled tools live and how each OS gets USB access."""
import os
import subprocess
import sys
from pathlib import Path

FROZEN = getattr(sys, "_MEIPASS", None)
HERE = Path(FROZEN or Path(__file__).resolve().parent.parent)
# The toolkit finds its files next to its own modules: dfu/ in source, the bundle's top when frozen.
DFU = HERE if FROZEN else HERE / "dfu"
TOOLS = DFU / "tools"
EXE = ".exe" if sys.platform == "win32" else ""
LIBUSB = DFU / "lib" / {"win32": "libusb-1.0.dll", "darwin": "libusb-1.0.dylib"}.get(sys.platform, "libusb-1.0.so.0")
USBDK_MSI = HERE / "windows" / "UsbDk_x64.msi"


def configure():
    """Point the DFU toolkit at the bundled tools. Call before importing jibo_dfu."""
    sys.path.insert(0, str(DFU))
    os.environ["PATH"] = str(TOOLS) + os.pathsep + os.environ.get("PATH", "")
    if (TOOLS / ("dfu-util" + EXE)).is_file():
        os.environ["JIBO_DFU_UTIL"] = str(TOOLS / ("dfu-util" + EXE))
    if LIBUSB.is_file():
        os.environ["JIBO_LIBUSB"] = str(LIBUSB)
    if sys.platform == "win32":
        os.environ.setdefault("CYGWIN", "nodosfilewarning")  # the bundled Cygwin debugfs/e2fsck
        _no_console_windows()


def _no_console_windows():
    """BEetle is a window app; keep its helper programs from flashing console windows."""
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        kwargs.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
        original(self, *args, **kwargs)
    subprocess.Popen.__init__ = init


def load_toolkit():
    import jibo_dfu
    # BEetle never shares robot data with anyone (the toolkit can offer calibration sharing).
    jibo_dfu.calibration_service.CALIBRATION_SHARING_AVAILABLE = False
    return jibo_dfu


def usb_helper_needed():
    """Windows only: libusb reaches Jibo through the signed UsbDk driver, installed once."""
    if sys.platform != "win32":
        return False
    return subprocess.run(["sc", "query", "UsbDk"], capture_output=True).returncode != 0


def install_usb_helper():
    """Install UsbDk; Windows asks the user for permission."""
    msi = str(USBDK_MSI)
    script = ("$p = Start-Process msiexec.exe -ArgumentList '/i','\"{}\"','/qn','/norestart' -Verb RunAs -Wait -PassThru; "
              "exit $p.ExitCode").format(msi.replace("'", "''"))
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True)
    if result.returncode not in (0, 3010) or usb_helper_needed():
        raise RuntimeError("The USB helper was not installed (Windows said: {}). Click Next to try again, "
                           "and choose Yes when Windows asks.".format((result.stderr or str(result.returncode)).strip()[-300:]))
