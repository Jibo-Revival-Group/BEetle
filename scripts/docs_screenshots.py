#!/usr/bin/env python3
"""Capture the README's four Tk screens using docs-only example data, never USB.

Run with Tk and Pillow under Xvfb:
    xvfb-run -a -s '-screen 0 1400x1000x24' python3 scripts/docs_screenshots.py
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from gui_fakes import FakeApi


class DocsApi(FakeApi):
    """Presentation values stay separate from the shared test fixtures."""

    BACKUP_ROOT = Path("~/Jibo-Backups")

    def __init__(self):
        super().__init__("dfu")
        self.packages = [Path("updates/jibo-13.0.0.tar.bz2")]
        baseline = hashlib.sha256(b"documentation baseline image").hexdigest()
        self.plan.update(
            operation="Set mode and Wi-Fi",
            before_sha256=baseline,
            candidate_sha256=hashlib.sha256(b"documentation edited image").hexdigest(),
            baseline_backup=str(self.BACKUP_ROOT / "var.img"),
            baseline_sha256=baseline,
        )
        self.progress_gate = threading.Event()

    def tool(self, name):
        return name

    def _edit(self, name, args, kwargs):
        confirmation = kwargs["confirmation"]

        def review(plan):
            plan = dict(plan)
            if plan.get("changes"):
                plan["changes"] = [dict(change, description="Update robot settings")
                                   for change in plan["changes"]]
            return confirmation(plan)

        result = super()._edit(name, args, dict(kwargs, confirmation=review))
        if result["status"] == "cancelled":
            result["message"] = "No changes were made."
        else:
            result["operation_directory"] = str(self.BACKUP_ROOT / "mode-wifi")
        return result

    def backup_var(self, **kwargs):
        self.calls.append(("backup_var", (), kwargs))
        print("Reading the 500 MiB var partition from USB", flush=True)
        sys.stderr.write("\r[##########----------] 50.0% | 250.0/500.0 MiB")
        sys.stderr.flush()
        if not self.progress_gate.wait(15):
            raise TimeoutError("Documentation capture did not release progress")
        return {"status": "backup complete", "image": str(self.BACKUP_ROOT / "var.img")}


def clean_png(path):
    """Keep identical RGB pixels, with no metadata or trailing payload."""
    from PIL import Image

    with Image.open(path) as source:
        pixels = source.convert("RGB")
        size, data = pixels.size, pixels.tobytes()
    assert size == (1080, 720), size
    Image.frombytes("RGB", size, data).save(path, optimize=True)
    with Image.open(path) as image:
        assert image.size == size and image.tobytes() == data
    payload = path.read_bytes()
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    offset, chunks = 8, []
    while offset < len(payload):
        length = struct.unpack_from(">I", payload, offset)[0]
        kind = payload[offset + 4:offset + 8]
        chunks.append(kind)
        offset += length + 12
        if kind == b"IEND":
            break
    assert chunks[0] == b"IHDR" and chunks[-1] == b"IEND"
    assert set(chunks) == {b"IHDR", b"IDAT", b"IEND"} and offset == len(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/images/gui")
    parser.add_argument("--setup", action="store_true",
                        help="Also capture the shared 5x1 setup review")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    import jibo_gui as gui
    import jibo_gui_core as core

    api = DocsApi()
    opened = []
    controller = core.GuiController(api, browser_opener=lambda url: opened.append(url) or True)
    root = gui.create_root()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(
        "".join(traceback.format_exception(*exc)))
    window = gui.ToolkitWindow(root, controller)
    captured = []

    def pump_until(predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            assert not errors, errors
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("GUI state timed out: " + window.page_name)

    def visible_text(widget):
        if not widget.winfo_viewable():
            return ""
        parts = []
        if "text" in widget.keys():
            parts.append(str(widget.cget("text")))
        if widget.winfo_class() == "Text":
            parts.append(widget.get("1.0", "end-1c"))
        parts.extend(visible_text(child) for child in widget.winfo_children())
        return "\n".join(parts)

    def capture(name):
        root.update()
        assert root.winfo_viewable() and not errors
        visible = visible_text(root).replace("/tmp/pm.sh", "PM destination")
        assert not re.search(r"\bfake\b|\btest(?:ing)?\b|/tmp", visible, re.I)
        path = out / (name + ".png")
        from PIL import ImageGrab
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()),
                       xdisplay=os.environ.get("DISPLAY")).save(path)
        clean_png(path)
        captured.append(path)

    def answer(value):
        prompt = window.prompt
        assert prompt is not None
        if prompt.kind == "text":
            window.controls["value"].set(value)
        elif "boot_enabled" in window.controls:
            assert value == "install" and window.controls["boot_enabled"].get()
        else:
            window.controls["choose"](value)
        window.controls["primary"].invoke()
        pump_until(lambda: window.prompt is not prompt and window.prompt is not None)

    try:
        with core.capture_output(controller):
            pump_until(lambda: controller.snapshot().checked)
            assert controller.snapshot().readiness.state == "dfu-ready"
            window.render_state()
            capture("ready")
            if args.setup:
                assert window.setup_entry.winfo_viewable()
                import beetle_setup
                window.show_prompt(core.Prompt("confirm", "Step 5 of 5 — Run external OOBE PM",
                    detail="The original mode was OOBE. Run exactly these four SSH commands:\n\n" + "\n".join(beetle_setup.pm_commands(beetle_setup.OOBE_PM_URL)),
                    items=(controller.flows.MenuItem("cancel", "Cancel"), controller.flows.MenuItem("confirm", "Confirm")), initial="cancel"))
                capture("setup")
                window.show_home()

            window.open_action("set-mode-wifi")
            pump_until(lambda: window.prompt is not None)
            assert window.prompt.title == "Set mode and configure Wi-Fi"
            window.controls["choose"]("int-developer")
            capture("mode-wifi")
            answer("int-developer")
            answer("Example network")
            answer("open")
            answer("install")

            assert window.prompt.kind == "confirm" and window.prompt.initial == "cancel"
            assert root.focus_get() is window.controls["cancel"]
            pump_until(lambda: not window.controls["primary"].instate(["disabled"]))
            capture("review")
            window.controls["cancel"].invoke()
            pump_until(lambda: not controller.busy and window.page_name == "result")
            window.show_home()
            window.open_action("backup-var")
            pump_until(lambda: float(window.progress_bar.cget("value")) == 50)
            capture("progress")
            api.progress_gate.set()
            pump_until(lambda: not controller.busy and window.page_name == "result")
    finally:
        api.progress_gate.set()
        controller.shutdown()
        if not window.closed:
            window.close()

    expected = ["ready.png", "mode-wifi.png", "review.png", "progress.png"]
    if args.setup:
        expected.insert(1, "setup.png")
    assert [path.name for path in captured] == expected
    assert not opened, "Screenshot capture must never open a browser"
    for path in captured:
        print(str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))
    print(f"{len(captured)} screens captured at 1080 x 720; PNG metadata removed; no Tk callback errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
