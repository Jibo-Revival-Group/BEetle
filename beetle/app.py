"""BEetle's window: a click-Next wizard that mods a Jibo and runs 5x1's PM."""
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from . import VERSION, flow, pm, runtime

BG, PANEL, TEXT, MUTED, GREEN, LINE, RED = "#111513", "#161c18", "#eef1ec", "#b0bbb2", "#29d780", "#303b33", "#ff6b6b"

RCM_STEPS = (
    "Turn Jibo off completely.",
    "Open the hatch on the back of his head. Under it are the round button panel and a micro-USB port.",
    "Plug a USB cable from this computer into that micro-USB port.",
    "Press and hold the RCM button (the lower of the two small buttons in the photo). Keep holding it "
    "while you turn Jibo on with his power button, then let go.",
    "In RCM mode the red light on his forehead stays on and he doesn't chime. If he chimes or starts "
    "normally, turn him off and try again.",
)


class Output:
    """Sends print() output from the toolkit to the window's log."""
    def __init__(self, post):
        self.post = post

    def write(self, text):
        if text:
            self.post(("log", text))
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


class App:
    def __init__(self, root, api):
        self.root, self.api = root, api
        self.events = queue.Queue()
        self.port = None
        self.backup_folder = None
        self.answers = {"backup": True, "ssid": "", "password": "", "open": False, "ip": ""}
        self.busy = False
        root.title("BEetle " + VERSION)
        root.configure(bg=BG)
        root.geometry("820x680")
        root.minsize(720, 640)
        family = next((f for f in ("Noto Sans", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu", "DejaVu Sans")
                       if f in tkfont.families(root)), "TkDefaultFont")
        self.font = lambda size, weight="normal": (family, size, weight)

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=32, pady=(24, 0))
        tk.Label(header, text="BEetle", font=self.font(20, "bold"), fg=GREEN, bg=BG).pack(side="left")
        self.step_label = tk.Label(header, text="", font=self.font(11), fg=MUTED, bg=BG)
        self.step_label.pack(side="right")
        tk.Frame(root, bg=LINE, height=1).pack(fill="x", padx=32, pady=(14, 0))

        footer = tk.Frame(root, bg=BG)
        footer.pack(side="bottom", fill="x", padx=32, pady=(0, 24))
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=32, pady=20)
        self.next_button = self.button(footer, "Next", self.next, primary=True)
        self.next_button.pack(side="right")
        self.back_button = self.button(footer, "Back", self.back)
        self.back_button.pack(side="right", padx=(0, 10))

        self.pages = ["welcome"] + (["usb_helper"] if runtime.usb_helper_needed() else []) + \
                     ["rcm", "dfu", "backup", "wifi", "work", "reboot", "pm", "done"]
        self.index = 0
        sys.stdout = sys.stderr = Output(self.events.put)
        root.after(100, self.pump)
        self.show()

    # ---------- widgets ----------
    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, font=self.font(12, "bold" if primary else "normal"),
                         fg=BG if primary else TEXT, bg=GREEN if primary else PANEL,
                         activebackground="#5ee6a1" if primary else LINE, activeforeground=BG if primary else TEXT,
                         disabledforeground="#4d5a51", relief="flat", bd=0, padx=22, pady=9, cursor="hand2",
                         highlightthickness=0)

    def title(self, text, sub=None):
        tk.Label(self.body, text=text, font=self.font(18, "bold"), fg=TEXT, bg=BG, anchor="w",
                 justify="left").pack(fill="x")
        if sub:
            self.text(sub, pady=(6, 14))

    def text(self, text, color=MUTED, size=12, pady=(0, 8), parent=None):
        label = tk.Label(parent or self.body, text=text, font=self.font(size), fg=color, bg=BG if parent is None else parent["bg"],
                         anchor="w", justify="left", wraplength=740)
        label.pack(fill="x", pady=pady)
        return label

    def entry(self, label, value, show=None):
        self.text(label, TEXT, 12, (8, 4))
        var = tk.StringVar(value=value)
        box = tk.Entry(self.body, textvariable=var, font=self.font(13), fg=TEXT, bg=PANEL, insertbackground=TEXT,
                       relief="flat", highlightthickness=1, highlightbackground=LINE, highlightcolor=GREEN, show=show or "")
        box.pack(fill="x", ipady=7, ipadx=8)
        return var, box

    def choice(self, var, value, text, detail):
        frame = tk.Frame(self.body, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        frame.pack(fill="x", pady=5)
        tk.Radiobutton(frame, text=text, variable=var, value=value, font=self.font(13, "bold"), fg=TEXT, bg=PANEL,
                       selectcolor=BG, activebackground=PANEL, activeforeground=TEXT, anchor="w",
                       highlightthickness=0, bd=0).pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(frame, text=detail, font=self.font(11), fg=MUTED, bg=PANEL, anchor="w", justify="left",
                 wraplength=640).pack(fill="x", padx=40, pady=(0, 12))

    def log_box(self):
        box = tk.Text(self.body, height=10, font=("Courier", 10), fg=MUTED, bg=PANEL, relief="flat", wrap="word",
                      highlightthickness=0, padx=10, pady=8, state="disabled")
        box.pack(fill="both", expand=True, pady=(10, 0))
        self.log = box
        return box

    # ---------- page flow ----------
    def show(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.log = None
        self.status = None
        name = self.pages[self.index]
        steps = [p for p in self.pages if p not in ("welcome", "usb_helper", "done")]
        self.step_label.config(text="Step {} of {}".format(steps.index(name) + 1, len(steps)) if name in steps else "")
        self.next_button.config(text="Next", state="normal")
        self.back_button.config(state="normal" if name == "wifi" else "disabled")
        getattr(self, "page_" + name)()

    def go(self, name):
        self.index = self.pages.index(name)
        self.show()

    def next(self):
        if self.busy or str(self.next_button["state"]) == "disabled":
            return
        name = self.pages[self.index]
        leave = getattr(self, "leave_" + name, None)
        if leave and leave() is False:
            return
        self.index += 1
        self.show()

    def back(self):
        if not self.busy and self.index:
            self.index -= 1
            self.show()

    def pump(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log" and self.log is not None:
                self.log.config(state="normal")
                self.log.insert("end", value)
                self.log.see("end")
                self.log.config(state="disabled")
            elif kind == "status" and self.status is not None:
                self.status.config(text=value)
            elif kind == "call":
                value()
        self.root.after(100, self.pump)

    def run(self, work, done, failed):
        """Run `work` off the window's thread; then call done(result) or failed(message)."""
        self.busy = True
        self.next_button.config(state="disabled")
        self.back_button.config(state="disabled")

        def target():
            try:
                result = work()
            except Exception as exc:  # shown to the user, never swallowed
                message = str(exc) or exc.__class__.__name__
                self.events.put(("call", lambda: (self.finish(), failed(message))))
            else:
                self.events.put(("call", lambda: (self.finish(), done(result))))
        threading.Thread(target=target, daemon=True).start()

    def finish(self):
        self.busy = False

    def say(self, text):
        self.events.put(("status", text))

    def failed(self, message, retry_page):
        self.status.config(text=message, fg=RED)
        self.next_button.config(text="Try again", state="normal", command=lambda: (
            self.next_button.config(command=self.next), self.go(retry_page)))

    # ---------- pages ----------
    def page_welcome(self):
        self.title("Mod your Jibo for 5x1", "BEetle sets your Jibo up for 5x1. You'll plug him into this computer, "
                   "enter your Wi-Fi, and mostly click Next.")
        for item in ("A USB cable for the micro-USB port under the hatch on the back of Jibo's head",
                     "Your Wi-Fi name and password (Jibo needs 2.4 GHz Wi-Fi)",
                     "About 30 minutes, or about an hour if you back Jibo up first"):
            self.text("•  " + item, TEXT)

    def page_usb_helper(self):
        self.title("Install the USB helper", "Windows needs a small USB driver (UsbDk, made by Red Hat) to talk to "
                   "Jibo. You only install it once.")
        self.text("Click Next, then choose Yes when Windows asks for permission.", TEXT)
        self.status = self.text("", MUTED)

    def leave_usb_helper(self):
        self.status.config(text="Installing… choose Yes if Windows asks.", fg=MUTED)
        self.run(runtime.install_usb_helper, lambda _: self.go("rcm"), lambda m: self.status.config(text=m, fg=RED))
        return False

    def page_rcm(self):
        self.title("Plug Jibo in, in RCM mode")
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x")
        steps = tk.Frame(row, bg=BG)
        steps.pack(side="left", fill="both", expand=True)
        for number, step in enumerate(RCM_STEPS, 1):
            tk.Label(steps, text="{}.  {}".format(number, step), font=self.font(12), fg=TEXT, bg=BG, anchor="w",
                     justify="left", wraplength=400).pack(fill="x", pady=4)
        photo = runtime.DFU / "assets" / "help" / "rcm-buttons.png"
        if photo.is_file():
            self.photo = tk.PhotoImage(file=str(photo)).subsample(2)
            tk.Label(row, image=self.photo, bg=BG).pack(side="right", padx=(16, 0))
            tk.Label(self.body, text="RESET is the upper small button; RCM is the lower one.", font=self.font(10),
                     fg=MUTED, bg=BG, anchor="e").pack(fill="x")
        self.status = self.text("Looking for Jibo…", MUTED, 12, (14, 0))
        self.next_button.config(state="disabled")
        self.watch_usb()

    def watch_usb(self):
        if self.pages[self.index] != "rcm" or self.busy:
            return
        try:
            robot = flow.find_robot(self.api)
        except Exception as exc:
            robot, message = None, str(exc)
        else:
            message = "Looking for Jibo…"
        if robot:
            self.robot = robot
            self.status.config(text="✓  Found Jibo in {} mode. Click Next.".format(
                "RCM" if robot["state"] == "rcm" else "DFU"), fg=GREEN)
            self.next_button.config(state="normal")
        else:
            self.status.config(text=message, fg=MUTED)
            self.next_button.config(state="disabled")
        self.root.after(1000, self.watch_usb)

    def page_dfu(self):
        self.title("Getting Jibo ready", "BEetle is starting DFU mode, so it can read and change Jibo's settings.")
        self.status = self.text("Starting DFU mode…", TEXT)
        self.log_box()
        self.run(lambda: flow.enter_dfu(self.api, self.robot), self.dfu_ready,
                 lambda m: self.failed(m + "\n\nTurn Jibo off, put him back in RCM mode, and try again.", "rcm"))

    def dfu_ready(self, port):
        self.port = port
        self.go("backup")

    def page_backup(self):
        self.title("Back up your Jibo?", "A backup is a copy of everything on Jibo, saved on this computer. "
                   "With it, Jibo can be put back exactly as he is now.")
        self.backup_var = tk.StringVar(value="yes" if self.answers["backup"] else "no")
        self.choice(self.backup_var, "yes", "Yes, back him up (recommended)",
                    "Saved to " + str(self.api.BACKUP_ROOT) + ". Takes about 30 minutes and a few GB of space.")
        self.choice(self.backup_var, "no", "No, skip the backup", "Faster, but there's no way to undo the changes later.")

    def leave_backup(self):
        self.answers["backup"] = self.backup_var.get() == "yes"

    def page_wifi(self):
        self.title("Jibo's Wi-Fi", "Jibo connects to this network. Use 2.4 GHz Wi-Fi; Jibo can't see 5 GHz networks.")
        self.ssid, _ = self.entry("Wi-Fi name", self.answers["ssid"])
        self.password, self.password_box = self.entry("Password", self.answers["password"], show="•")
        self.open_var = tk.BooleanVar(value=self.answers["open"])
        tk.Checkbutton(self.body, text="This network has no password", variable=self.open_var, font=self.font(11),
                       fg=MUTED, bg=BG, selectcolor=PANEL, activebackground=BG, activeforeground=TEXT,
                       highlightthickness=0, bd=0, command=lambda: self.password_box.config(
                           state="disabled" if self.open_var.get() else "normal")).pack(anchor="w", pady=(10, 0))
        if self.open_var.get():
            self.password_box.config(state="disabled")
        self.status = self.text("", RED, 11, (10, 0))

    def leave_wifi(self):
        ssid, password, is_open = self.ssid.get(), self.password.get(), self.open_var.get()
        problem = None
        if not ssid.strip():
            problem = "Enter the Wi-Fi name."
        elif len(ssid.encode("utf-8")) > 32:
            problem = "Wi-Fi names are at most 32 characters."
        elif not is_open and not 8 <= len(password) <= 63:
            problem = "Wi-Fi passwords are 8 to 63 characters."
        if problem:
            self.status.config(text=problem)
            return False
        self.answers.update(ssid=ssid, password="" if is_open else password, open=is_open)

    def page_work(self):
        backing_up = self.answers["backup"]
        self.title("Modding Jibo", "Keep Jibo plugged in and powered. " +
                   ("This takes about 40 minutes." if backing_up else "This takes about 10 minutes."))
        self.status = self.text("", TEXT)
        self.log_box()

        def work():
            if backing_up:
                self.say("Backing Jibo up (1 of 2)…")
                self.backup_folder = flow.backup(self.api, self.port,
                                                 progress=lambda message: print(message, flush=True))
            self.say("Setting int-developer mode, Wi-Fi and the boot-screen IP" + (" (2 of 2)…" if backing_up else "…"))
            return flow.mod(self.api, self.port, self.answers["ssid"], self.answers["password"] or None,
                            self.answers["open"], keep_rollback=backing_up)

        def done(_):
            self.answers["password"] = ""
            self.status.config(text="✓  Done. Click Next.", fg=GREEN)
            self.next_button.config(state="normal")
        self.run(work, done, lambda m: self.failed(m + "\n\nTurn Jibo off, put him back in RCM mode, and try again.", "rcm"))

    def page_reboot(self):
        self.title("Restart Jibo", "Jibo's settings are saved. Now restart him:")
        for number, step in enumerate((
                "Unplug the USB cable and Jibo's power cable.",
                "Wait 10 seconds, then plug his power back in.",
                "When he starts up, his screen shows his Wi-Fi status and IP address (it looks like 192.168.1.23).",
                "Type that IP address below."), 1):
            self.text("{}.  {}".format(number, step), TEXT)
        self.ip, _ = self.entry("Jibo's IP address", self.answers["ip"])
        self.status = self.text("", RED, 11, (10, 0))

    def leave_reboot(self):
        ip = self.ip.get().strip()
        if not pm.valid_host(ip):
            self.status.config(text="Enter the IP address shown on Jibo's screen, like 192.168.1.23.")
            return False
        self.answers["ip"] = ip

    def page_pm(self):
        self.title("Installing 5x1", "BEetle is running 5x1's setup script (PM) on Jibo over Wi-Fi. "
                   "This takes about 15 minutes. Keep Jibo plugged in.")
        self.status = self.text("Connecting to Jibo…", TEXT)
        self.log_box()
        output = lambda text: self.events.put(("log", text))
        self.run(lambda: pm.run_pm(self.answers["ip"], output, status=self.say), self.pm_done,
                 lambda m: self.failed(m, "pm"))

    def pm_done(self, result):
        kind, detail = result
        if kind == pm.CONVERTED:
            self.go("done")
        elif kind == pm.UPDATING:
            self.status.config(text="Jibo updated his system first. Unplug his power, wait 10 seconds, plug it back in, "
                                    "wait until he has started up, then click Run again.", fg=TEXT)
            self.next_button.config(text="Run again", state="normal", command=lambda: (
                self.next_button.config(command=self.next), self.go("pm")))
        else:
            self.failed(detail, "pm")

    def page_done(self):
        self.title("Jibo is on 5x1!")
        self.text("Unplug Jibo's power, wait 10 seconds, and plug him back in. He takes about 2 minutes to start up.", TEXT)
        if self.backup_folder:
            self.text("Your backup is in " + str(self.backup_folder) + ". Keep it somewhere safe.")
        self.text("Need help? Visit jibo.guide.")
        self.back_button.config(state="disabled")
        self.next_button.config(text="Close", command=self.root.destroy)


def main(api=None):
    api = api or runtime.load_toolkit()
    root = tk.Tk()
    App(root, api)
    root.mainloop()
