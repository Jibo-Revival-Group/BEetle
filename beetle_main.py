"""BEetle's entry point (also the frozen app's)."""
import json
import os
import runpy
import subprocess
import sys

from beetle import VERSION, runtime


def self_check(out=None):
    """CI check of a built app: every bundled tool runs and the toolkit loads. Only lists USB devices."""
    api = runtime.load_toolkit()
    report = {"version": VERSION, "tools": {}}
    probes = {"dfu-util": ("--version",), "shofel2_t124": ("--dfu-stage-capability",),
              "debugfs": ("-V",), "e2fsck": ("-V",)}
    for name, args in probes.items():
        path = runtime.TOOLS / (name + runtime.EXE)
        result = subprocess.run([str(path), *args], capture_output=True, text=True, timeout=30)
        output = (result.stdout + result.stderr).strip()
        if result.returncode or (name == "shofel2_t124" and output != "dfu-stage-launch=1"):
            raise RuntimeError(name + " failed: " + output)
        report["tools"][name] = output.splitlines()[0]
    import ctypes
    ctypes.CDLL(os.environ["JIBO_LIBUSB"])
    import paramiko
    import tkinter
    import jibo_images
    if not api.DEFAULT_LOADER.is_file():
        raise RuntimeError("the RAM loader is missing: " + str(api.DEFAULT_LOADER))
    report.update(tk=tkinter.Tcl().eval("info patchlevel"), paramiko=paramiko.__version__,
                  wifi_screen_patch_files=len(jibo_images.boot_network_status_assets()),
                  rcm_photo=(runtime.DFU / "assets/help/rcm-buttons.png").is_file(), usb_devices=len(api.devices()))
    text = json.dumps(report, indent=2)
    if out:  # the Windows app has no console to print to
        with open(out, "w") as stream:
            stream.write(text + "\n")
    else:
        print(text)


def main():
    arguments = sys.argv[1:]
    runtime.configure()
    if arguments == ["--version"]:
        print("BEetle " + VERSION)
    elif arguments[:1] == ["--self-check"]:
        self_check(*arguments[1:2])
    elif arguments and arguments[0].endswith("jibo_dfu_pipeline.py"):
        # The toolkit starts its Linux DFU helper as `sys.executable helper.py ...`.
        sys.argv = arguments
        runpy.run_path(str(runtime.DFU / "jibo_dfu_pipeline.py"), run_name="__main__")
    else:
        from beetle import app
        app.main()


if __name__ == "__main__":
    main()
