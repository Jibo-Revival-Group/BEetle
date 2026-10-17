"""Guided recovery/Wi-Fi preparation followed by an external PM script.

No PM implementation, uploads, provisioning API or firmware logic lives here.
The only SSH shell commands are the four commands shown in the PM review.
"""
import base64
import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
import time

for _dependency_root in (Path(__file__).parent / "setup-deps", Path(__file__).parent / ".build/setup-deps"):
    if _dependency_root.is_dir():
        sys.path.insert(0, str(_dependency_root))

PM_URL = "https://scripts.5x1.com/pm"
OOBE_PM_URL = "https://raw.githubusercontent.com/Jibo-Revival-Group/BEach/master/PM/post-oobe-mod.sh"
OOBE_PM_COMPLETE = "5X1_OOBE_PM_COMPLETE"
NORMAL_PM_COMPLETE = "Wait like 2 minutes while the robot reboots... I'm done here."
PM_RECEIPT = "/var/jibo/5x1-pm-oobe-complete.json"
PARTITIONS = ("var", "rootfsA", "rootfsB", "services", "skills")
STAGES = ("backup", "usb", "ssh", "pm", "complete")
PREPARATION_REVIEW = (
    "Save rollback backups, remember whether Jibo is in OOBE, then set int-developer mode, "
    "Wi-Fi and the boot-screen IP display. Connect over SSH after reboot and run the external "
    "PM script, using the GitHub OOBE version for robots originally in OOBE. PM owns software installation and the final reboot. Keep Jibo powered."
)


class SetupError(RuntimeError):
    pass


class Cancelled(SetupError):
    pass


class ConnectionLost(SetupError):
    def __init__(self, message, completed=False):
        super().__init__(message)
        self.completed = completed


def pm_commands(url):
    if url not in (PM_URL, OOBE_PM_URL):
        raise SetupError("Unknown PM script URL.")
    return ("jibo-mount --rw", "curl -fsSL -k " + url + " -o /tmp/pm.sh",
            "chmod +x /tmp/pm.sh", "sh /tmp/pm.sh")


def identity(value):
    keys = ("name", "serial_number", "cpuid", "wifi_mac")
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) and value[k] for k in keys):
        raise SetupError("Factory identity is incomplete; restore or repair var before setup.")
    return {k: value[k] for k in keys}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".setup-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.geteuid() == 0 and os.environ.get("SUDO_UID"):
            os.chown(path, int(os.environ["SUDO_UID"]), int(os.environ.get("SUDO_GID", "-1")))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Session:
    def __init__(self, path):
        requested = Path(path).expanduser()
        if requested.is_symlink():
            raise SetupError("Setup session must be a regular file.")
        self.path = requested.resolve()
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                raise SetupError("Cannot read this session. Restore its saved copy or choose a new session file.") from None
            if not isinstance(self.data, dict) or self.data.get("kind") != "beetle-5x1-setup" or self.data.get("schema") not in (1, 2):
                raise SetupError("Not a BEetle setup session.")
            if not isinstance(self.data.get("done"), list) or not isinstance(self.data.get("fingerprints"), dict):
                raise SetupError("Invalid setup stages or host fingerprints.")
            if self.data["schema"] == 1:
                # Earlier sessions did not install the IP display. Preserve the
                # original OOBE evidence and backups but repeat USB preparation.
                self.data["done"] = ["backup"] if "backup" in self.data["done"] else []
                self.data["schema"] = 2
                self.data["stage"] = "usb" if self.data["done"] else "backup"
                for key in ("pending_updates", "awaiting_reboot", "awaiting_normal_reboot", "verification"):
                    self.data.pop(key, None)
            if self.data.pop("pm_skipped", False):
                # Preparation-only sessions predate the normal PM route.
                self.data["done"] = [p for p in self.data["done"] if p in ("backup", "usb")]
                self.data["stage"] = next(p for p in STAGES if p not in self.data["done"])
            if any(p not in STAGES for p in self.data["done"]):
                raise SetupError("Invalid setup stages.")
        else:
            self.data = {"schema": 2, "kind": "beetle-5x1-setup", "stage": "backup", "done": [], "fingerprints": {}}

    def save(self):
        private_json(self.path, self.data)

    def mark(self, stage):
        if stage not in self.data["done"]:
            self.data["done"].append(stage)
        self.data["stage"] = "complete" if stage == "complete" else next((p for p in STAGES if p not in self.data["done"]), "complete")
        self.save()


def read_factory(api, backup):
    """Inspect original mode and factory files on a disposable var copy."""
    import jibo_images as images
    entries = {p["name"]: p for p in backup["partitions"]}
    if set(PARTITIONS) - set(entries):
        raise SetupError("Setup requires rollback backups of var, both rootfs slots, services and skills.")
    with tempfile.TemporaryDirectory(prefix="beetle-inspect-") as tmp:
        var = Path(tmp) / "var.ext4"
        shutil.copyfile(entries["var"]["image"], var)
        images._replay_journal_on_copy(var)
        def read(path):
            return images._extract(var, path, Path(tmp) / "file")
        robot = identity(json.loads(read(images.FACTORY_IDENTITY_PATH)))
        mode = json.loads(read(images.VAR_MODE_PATH)).get("mode")
        if mode not in ("oobe", "identified", "normal", "developer", "int-developer"):
            raise SetupError("Cannot determine the original robot mode; PM was not selected.")
        calibration = {}
        for p in images.FACTORY_CAMERA_PATHS:
            raw = read(p)
            if not isinstance(json.loads(raw), dict):
                raise SetupError("Factory camera calibration is invalid.")
            calibration[p] = hashlib.sha256(raw).hexdigest()
    return robot, mode, calibration


class SSH:
    """SFTP reads for identity; exactly four shell commands for PM."""
    def __init__(self, host, username, password, session, confirm):
        try:
            import paramiko
        except ImportError:
            raise SetupError("SSH support is missing. Run scripts/install_setup_deps.py with this Python.") from None
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", host or ""):
            raise SetupError("Enter an IP address or hostname without a port or URL.")
        self.client = paramiko.SSHClient()
        class Policy(paramiko.MissingHostKeyPolicy):
            def missing_host_key(_, client, hostname, key):
                fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
                expected = session.data["fingerprints"].get(host)
                if expected and expected != fingerprint:
                    raise SetupError("SSH host key changed; verify the robot before using this session.")
                if not expected:
                    if not confirm("Trust SSH host key", host + "\n" + fingerprint):
                        raise Cancelled("SSH connection cancelled.")
                    session.data["fingerprints"][host] = fingerprint
                    session.save()
                client.get_host_keys().add(hostname, key.get_name(), key)
        self.client.set_missing_host_key_policy(Policy())
        try:
            self.client.connect(host, username=username, password=password, look_for_keys=False,
                allow_agent=False, timeout=15, banner_timeout=20, auth_timeout=20)
        except SetupError:
            self.client.close()
            raise
        except Exception:
            self.client.close()
            raise SetupError("SSH connection failed. Use the IP shown on Jibo's boot screen and check SSH credentials.") from None

    def inspect(self):
        # No remote worker, uploads or additional SSH shell commands.
        try:
            with self.client.open_sftp() as sftp:
                def load(path):
                    with sftp.open(path, "rb") as stream:
                        raw = stream.read(65537)
                    if len(raw) > 65536:
                        raise SetupError("Robot identity file is oversized.")
                    return json.loads(raw)
                report = {"identity": identity(load("/var/jibo/identity.json")),
                          "mode": load("/var/jibo/mode.json")["mode"], "pm_complete": False}
                try:
                    receipt = load(PM_RECEIPT)
                except IOError as error:
                    if getattr(error, "errno", None) not in (2, None):
                        raise
                else:
                    report["pm_complete"] = (receipt.get("schema") == 1 and receipt.get("status") == "complete"
                        and receipt.get("robot") == report["identity"]["name"])
                return report
        except SetupError:
            raise
        except Exception:
            raise SetupError("Cannot read robot identity over SFTP; no PM command was run.") from None

    def run_pm(self, commands, before_command):
        normal_pm = commands == pm_commands(PM_URL)
        completion_marker = NORMAL_PM_COMPLETE if normal_pm else OOBE_PM_COMPLETE
        for index, command in enumerate(commands):
            before_command(index)
            print("SSH: " + command, flush=True)
            channel = None
            completed = False
            tail = ""
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            try:
                transport = self.client.get_transport()
                if transport is None or not transport.is_active():
                    raise EOFError()
                channel = transport.open_session(timeout=20)
                channel.set_combine_stderr(True)
                if normal_pm and index == 3:
                    # Normal PM calls clear. Supply TERM through SSH's terminal
                    # request while preserving the exact shell command.
                    channel.get_pty(term="xterm")
                # Do not wrap, prefix, chain or otherwise alter this command.
                channel.exec_command(command)
                deadline = time.monotonic() + (7200 if index == 3 else 180)
                while True:
                    if channel.recv_ready():
                        text = decoder.decode(channel.recv(32768))
                        print(text, end="", flush=True)
                        tail = (tail + text)[-4096:]
                        completed = completed or completion_marker in tail
                    elif channel.exit_status_ready():
                        break
                    elif not transport.is_active() or channel.closed:
                        raise EOFError()
                    elif time.monotonic() > deadline:
                        raise socket.timeout()
                    else:
                        time.sleep(0.05)
                status = channel.recv_exit_status()
                if status == -1:
                    raise EOFError()
                if status:
                    raise SetupError("PM command {} failed (exit {}). Later commands were not run.".format(index + 1, status))
                if index == 3 and commands == pm_commands(OOBE_PM_URL) and not completed:
                    raise SetupError("The OOBE script did not report completion. Check that the updated BEach OOBE script is published before retrying.")
            except SetupError:
                raise
            except Exception:
                raise ConnectionLost("SSH was interrupted during PM command {}. Check Jibo before retrying.".format(index + 1),
                                     completed=index == 3 and completed) from None
            finally:
                if channel is not None:
                    channel.close()
        return {"completed": True}

    def close(self):
        self.client.close()


class SetupController:
    def __init__(self, api, session, text, select, confirm, message, ssh_factory=SSH):
        self.api, self.session = api, Session(session)
        self.text, self.select, self.confirm, self.message = text, select, confirm, message
        self.ssh_factory = ssh_factory

    def approved(self, title, detail):
        if not self.confirm(title, detail):
            raise Cancelled("Wizard paused. Resume this session to continue.")

    def input(self, title, prompt, **kwargs):
        value = self.text(title, prompt, **kwargs)
        if value is None:
            raise Cancelled("Wizard paused. Resume this session to continue.")
        return value

    def recovery(self, port):
        import jibo_tui
        # The same shared prompts work in GUI, TUI and CLI.
        while True:
            found = tuple(self.api.devices())
            if len(found) > 1:
                raise SetupError("Connect only one robot before continuing the wizard.")
            ready = jibo_tui.inspect_readiness(self.api, found)
            if port and found and ready.port != port:
                raise SetupError("The connected robot is on a different USB port.")
            if ready.state == "dfu-ready":
                return ready.port
            if ready.state == "rcm":
                self.approved("Step 1 of 5 — Start recovery", "Load the RAM DFU program using the Meerkat Rev02 SDRAM profile. No partition is changed during recovery entry.")
                entered = self.api.enter_shofel_dfu(port=ready.port, confirm_meerkat_rev02=True)
                return entered["port"]
            instructions = ("Connect a micro-USB data cable. Power Jibo off, hold the lower RCM button behind the rear hatch, "
                            "and press Power. Keep holding RCM until the red light stays on. Then retry USB detection.")
            if ready.state != "none":
                instructions = ready.detail + "\nRestart into RCM/APX with the data cable attached, then retry."
            choice = self.select("Step 1 of 5 — Connect Jibo", (("retry", "Check USB again"), ("cancel", "Pause wizard")),
                                 detail=instructions, initial="retry")
            if choice != "retry":
                raise Cancelled("Recovery setup paused.")

    def run(self, port=None):
        s, ssh = self.session, None
        try:
            if "complete" in s.data["done"]:
                return self.result()
            if "usb" not in s.data["done"]:
                port = self.recovery(port)
            if "backup" not in s.data["done"]:
                self.approved("Step 2 of 5 — Back up and prepare", PREPARATION_REVIEW)
                backup = self.api.backup_partitions(PARTITIONS, port=port)
                # Partition backups can reuse an older baseline. OOBE gating must
                # inspect the live pre-change var, not that earlier mode file.
                current = self.api.backup_var(port=port, refresh=True)
                live_view = {"partitions": [dict(entry, image=current["image"]) if entry["name"] == "var" else entry
                                            for entry in backup["partitions"]]}
                robot, mode, calibration = read_factory(self.api, live_view)
                s.data.update(identity=robot, original_mode=mode, calibration=calibration, current_var_backup=current["manifest"],
                              backup_set=backup["manifest"], partitions=backup["partitions"])
                s.mark("backup")
            else:
                for entry in s.data["partitions"]:
                    image = Path(entry["image"])
                    if image.stat().st_size != entry["size_bytes"] or file_sha256(image) != entry["sha256"]:
                        raise SetupError("Rollback backup changed; restore its verified copy before resuming.")
            # Never infer OOBE from the temporary int-developer mode or missing keys.
            if s.data.get("original_mode") not in ("oobe", "identified", "normal", "developer", "int-developer"):
                raise SetupError("Original OOBE status is unavailable. Start with a verified original var backup.")
            s.data["is_oobe"] = s.data["original_mode"] in ("oobe", "identified")
            s.save()
            if "usb" not in s.data["done"]:
                ssid = self.input("Step 2 of 5 — Wi-Fi", "Wi-Fi network name (SSID):")
                kind = self.select("Network security", (("protected", "WPA/WPA2"), ("open", "Open network")))
                if kind not in ("protected", "open"):
                    raise Cancelled("Wi-Fi setup paused.")
                password = None
                try:
                    if kind == "protected":
                        password = self.input("Wi-Fi password", "Wi-Fi password:", password=True)
                        if password != self.input("Wi-Fi password", "Repeat Wi-Fi password:", password=True):
                            raise SetupError("Wi-Fi passwords do not match.")
                    result = self.api.set_mode_wifi_live("int-developer", ssid, password, kind == "open", port=port,
                        network_status="install", confirmation=lambda plan: self.confirm("Confirm USB preparation",
                            "Set int-developer mode, save Wi-Fi and install the boot-screen Wi-Fi/IP display. "
                            "This uses one full var transfer with rollback and readback verification."))
                finally:
                    password = None
                if result.get("status") not in ("verified", "already current"):
                    raise Cancelled("USB preparation did not complete.")
                s.mark("usb")
            self.message("Step 3 of 5 — Restart and read the IP", [
                "Power-cycle Jibo out of recovery mode. Wait for the boot screen to show Wi-Fi and an IP address.",
                "Keep Jibo powered; USB is no longer needed. Use the IP shown on his screen in the next step.",
                "If the stock software cannot display the IP, use your router's device list; do not run PM until Wi-Fi is connected."])
            host = self.input("Step 4 of 5 — Connect over SSH", "IP shown on Jibo's screen:", default=s.data.get("host", ""))
            username = self.input("SSH user", "SSH username:", default="root")
            password = self.input("SSH password", "SSH password (default jibo):", default="jibo", password=True)
            try:
                ssh = self.ssh_factory(host, username, password, s, self.confirm)
            finally:
                password = None
            report = ssh.inspect()
            if identity(report["identity"]) != s.data["identity"]:
                raise SetupError("SSH robot does not match the USB backup. No PM command was run.")
            s.data["host"] = host
            s.mark("ssh")
            if s.data.get("pm_started"):
                if s.data["is_oobe"] and report.get("pm_complete") and report.get("mode") == "normal":
                    s.mark("pm")
                    s.mark("complete")
                    return self.result()
                choice = self.select("PM was interrupted", (("pause", "Pause and inspect Jibo"), ("retry", "Run PM again")),
                    detail="A previous attempt started PM. Its result is unknown. Retrying runs the same four commands again.", initial="pause")
                if choice != "retry":
                    raise Cancelled("PM result is unknown. Inspect Jibo before retrying.")
            url = OOBE_PM_URL if s.data["is_oobe"] else PM_URL
            label = "OOBE PM" if s.data["is_oobe"] else "PM"
            commands = pm_commands(url)
            self.approved("Step 5 of 5 — Run external " + label,
                          "Original mode: " + s.data["original_mode"] + ". Run exactly these four SSH commands:\n\n" + "\n".join(commands))
            def before_command(index):
                s.data.update(pm_url=url, pm_command=index + 1, pm_started=index == 3)
                s.save()
            try:
                ssh.run_pm(commands, before_command)
            except ConnectionLost as error:
                if not error.completed:
                    raise
                # The external script printed its completion marker before reboot.
            s.mark("pm")
            s.mark("complete")
            return self.result()
        except Cancelled as error:
            s.save()
            return {"status": "cancelled", "message": str(error), "session": str(s.path)}
        except Exception as error:
            s.save()
            message = str(error) if isinstance(error, SetupError) else "Wizard failed while checking or preparing Jibo. Review the rollback records."
            raise SetupError(message + " Resume " + str(s.path) + " at step " + s.data["stage"] + ".") from None
        finally:
            if ssh is not None:
                ssh.close()

    def result(self):
        s = self.session
        return {"status": "complete", "mode": "normal",
            "message": "PM finished. Jibo is rebooting; allow a few minutes for BEam to start.",
            "session": str(s.path), "backup": s.data.get("backup_set", "")}


def run_guided(api, flows, port=None):
    session = api.BACKUP_ROOT / "beetle-5x1-session.json"
    if session.expanduser().exists():
        choice = flows.select_option("Saved setup found", (("resume", "Resume saved setup"), ("new", "Start setup for another robot")),
                                     initial="resume")
        if choice == "new":
            import uuid
            session = api.BACKUP_ROOT / ("beetle-5x1-session-" + uuid.uuid4().hex[:12] + ".json")
        elif choice != "resume":
            return {"status": "cancelled", "message": "Wizard paused."}
    return SetupController(api, session, flows.text_input, flows.select_option,
                           flows.confirm_action, flows.show_screen).run(port)


def cli(api, args):
    import getpass
    def text(title, prompt, default="", password=False, **kwargs):
        print(title)
        value = getpass.getpass(prompt) if password else input(prompt + (" [" + default + "] " if default else " "))
        return value or default
    def select(title, options, **kwargs):
        print(title + "\n" + kwargs.get("detail", ""))
        for key, label in options:
            print(key + ": " + label)
        value = input("Choice (blank pauses): ")
        return value if value in dict(options) else None
    def confirm(title, detail):
        print(title + "\n" + detail)
        return input("Type YES to continue: ") == "YES"
    return SetupController(api, args.session or api.BACKUP_ROOT / "beetle-5x1-session.json",
        text, select, confirm, lambda title, lines: print(title + "\n" + "\n".join(lines))).run(args.port)
