"""Click Next through BEetle's whole window with a fake toolkit and a fake PM (no USB, no robot)."""
import os
import shutil
import time
import unittest

from tests.test_flow import FakeToolkit

try:
    import tkinter as tk
    tk.Tk().destroy()
    DISPLAY = True
except Exception:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, "needs a display (CI uses xvfb-run)")
class WizardTest(unittest.TestCase):
    def setUp(self):
        from beetle import app, pm
        self.app_module, self.pm = app, pm
        self.api = FakeToolkit(state=None)
        self.addCleanup(shutil.rmtree, self.api.BACKUP_ROOT, True)
        self.original_run_pm = pm.run_pm
        self.addCleanup(setattr, pm, "run_pm", pm.run_pm)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.window = app.App(self.root, self.api)
        self.shots = os.environ.get("BEETLE_SCREENSHOTS")

    def settle(self, page=None, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            if page is None or (self.window.pages[self.window.index] == page and not self.window.busy):
                break
            time.sleep(0.02)
        self.root.update()
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
            name = self.window.pages[self.window.index]
            from PIL import ImageGrab  # screenshots are optional, for reviewing the design
            box = (self.root.winfo_rootx(), self.root.winfo_rooty())
            box += (box[0] + self.root.winfo_width(), box[1] + self.root.winfo_height())
            ImageGrab.grab(box).save("{}/{:02d}-{}.png".format(self.shots, self.window.index, name))
        self.assertEqual(self.window.pages[self.window.index], page or self.window.pages[self.window.index])

    def click_next(self, page_after):
        self.window.next_button.invoke()
        self.settle(page_after)

    def test_click_next_from_rcm_to_5x1(self):
        w = self.window
        self.settle("welcome")
        self.click_next("rcm")
        self.assertEqual(str(w.next_button["state"]), "disabled", "Next waits for Jibo")
        self.api.state = "rcm"
        time.sleep(1.1)
        self.settle("rcm")
        self.assertIn("Found Jibo in RCM", w.status["text"])
        self.click_next("backup")
        self.assertEqual(self.api.calls[0], ("enter_dfu", "1-2", True))
        self.click_next("wifi")
        w.ssid.set("Home")
        w.password.set("short")
        self.click_next("wifi")
        self.assertIn("8 to 63", w.status["text"])
        w.password.set("longenough")
        self.click_next("work")
        self.settle("work")
        self.assertIn("Done", w.status["text"])
        self.assertEqual(self.api.calls[1][0], "backup")
        self.assertEqual(self.api.calls[2][:5], ("mod", "int-developer", "Home", "longenough", False))
        self.assertEqual(w.answers["password"], "", "the Wi-Fi password is not kept after use")
        self.click_next("reboot")
        w.ip.set("http://bad")
        self.click_next("reboot")
        w.ip.set("192.168.1.23")
        self.pm.run_pm = lambda host, output, **kw: (output("PM output\n"), (self.pm.CONVERTED, ""))[1]
        self.click_next("done")
        self.assertIn("Jibo is on 5x1", w.body.winfo_children()[0]["text"])


if __name__ == "__main__":
    unittest.main()
