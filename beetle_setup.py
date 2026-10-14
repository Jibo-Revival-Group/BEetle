"""Shared, resumable 5x1 setup. Network and device writes require a review.

Only public robot identity, host fingerprints and backup references are persisted.
The worker receives credentials on SSH stdin, never on the command line.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import time
import urllib.request
import zipfile
import sys

for _dependency_root in (Path(__file__).parent / "setup-deps", Path(__file__).parent / ".build/setup-deps"):
    if _dependency_root.is_dir():
        sys.path.insert(0, str(_dependency_root))

HUB = "api.5x1.com"
OTA = "http://joap.5x1.com:80"
BEAM_REVISION = "25d2b8cbf85b101aad3b2ab537a9c3f5a3b459ae"
BEAM_URL = "https://github.com/Jibo-Revival-Group/BEam/archive/" + BEAM_REVISION + ".zip"
PARTITIONS = ("var", "rootfsA", "rootfsB", "services", "skills")
STAGES = ("backup", "usb", "ssh", "credentials", "beam", "configure", "ota", "firmware", "normal", "verify", "complete")


class SetupError(RuntimeError):
    pass


class Cancelled(SetupError):
    pass


def identity(value):
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) and value[k]
            for k in ("name", "serial_number", "cpuid", "wifi_mac")):
        raise SetupError("Factory identity is incomplete; restore or repair var before setup.")
    return {k: value[k] for k in ("name", "serial_number", "cpuid", "wifi_mac")}


def credentials(value):
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) and value[k].strip()
            for k in ("accessKeyId", "secretAccessKey")):
        raise SetupError("Credentials are incomplete; no credential file was written.")
    result = dict(value)
    result.update(region="api", endpoint=OTA)
    return result


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
        # USB launchers run as root; keep the resume record usable by its owner.
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
                raise SetupError("Setup session cannot be read. Restore its saved copy or choose a new session file.") from None
            if not isinstance(self.data, dict) or self.data.get("schema") != 1 or self.data.get("kind") != "beetle-5x1-setup":
                raise SetupError("Not a BEetle setup session.")
            if not isinstance(self.data.get("done"), list) or any(p not in STAGES for p in self.data["done"]) or not isinstance(self.data.get("fingerprints"), dict):
                raise SetupError("Setup session has invalid stages or host fingerprints.")
        else:
            self.data = {"schema": 1, "kind": "beetle-5x1-setup", "stage": "backup", "done": [], "fingerprints": {}}

    def save(self):
        private_json(self.path, self.data)

    def mark(self, stage):
        if stage not in self.data["done"]:
            self.data["done"].append(stage)
        self.data["stage"] = next((p for p in STAGES if p not in self.data["done"]), "complete")
        self.save()


def read_factory(api, backup):
    """Use e2fsprogs on a copy: handles meta_bg and journal recovery safely."""
    import jibo_images as images
    entries = {p["name"]: p for p in backup["partitions"]}
    if set(PARTITIONS) - set(entries):
        raise SetupError("Setup requires rollback backups of var, both rootfs slots, services and skills.")
    with tempfile.TemporaryDirectory(prefix="beetle-inspect-") as tmp:
        var = Path(tmp) / "var.ext4"
        shutil.copyfile(entries["var"]["image"], var)
        images._replay_journal_on_copy(var)
        def read(path, optional=False):
            return images._extract(var, path, Path(tmp) / "file", optional=optional)
        robot = identity(json.loads(read(images.FACTORY_IDENTITY_PATH)))
        mode = json.loads(read(images.VAR_MODE_PATH)).get("mode")
        calibration = {}
        for p in images.FACTORY_CAMERA_PATHS:
            raw = read(p)
            if not isinstance(json.loads(raw), dict):
                raise SetupError("Factory camera calibration is invalid.")
            calibration[p] = hashlib.sha256(raw).hexdigest()
        raw = read("/jibo/credentials.json", optional=True)
        if raw is not None:
            credentials(json.loads(raw))
    return robot, mode, calibration


def provision(robot, rollback, request=None):
    request = request or protocol_request
    body = {"deviceId": robot["name"], "robotId": robot["name"], "targetMode": "open-jibo",
            "targetHost": HUB, "rollbackSnapshotId": str(rollback)}
    prepared = request("PrepareRobot", body)
    if not isinstance(prepared.get("token"), str) or not prepared["token"]:
        raise SetupError("BEefy did not return a prepared OOBE token.")
    if prepared.get("conversionReadiness", {}).get("canWriteRobot") is False:
        raise SetupError("BEefy blocked setup readiness; keep the rollback backup and retry.")
    body["token"] = prepared["token"]
    return credentials(request("SetupRobot", body))


def protocol_request(operation, body):
    req = urllib.request.Request("https://" + HUB + "/", json.dumps(body).encode(),
        {"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "OOBE_20161026." + operation})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            value = json.loads(response.read(1024 * 1024))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except Exception:
        # Do not expose HTTP response bodies (they may contain keys).
        raise SetupError("BEefy provisioning failed. Check connectivity and retry this session.") from None


def download_beam(destination):
    try:
        with urllib.request.urlopen(BEAM_URL, timeout=120) as response, Path(destination).open("wb") as out:
            print("Downloading pinned BEam archive…", flush=True)
            total = int(response.headers.get("Content-Length", "0"))
            received, reported = 0, 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                out.write(block)
                received += len(block)
                if received - reported >= 10 * 1024 * 1024:
                    print("BEam download: {:.0f}%".format(100 * received / total) if total else
                          "BEam download: {} MiB".format(received // (1024 * 1024)), flush=True)
                    reported = received
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is not None:
                raise ValueError()
            if not any(n.endswith("/@be/be/package.json") for n in archive.namelist()):
                raise ValueError()
    except Exception:
        raise SetupError("Could not download the pinned BEam archive; retry before installing.") from None


class SSH:
    """One transport; first host-key acceptance is explicit and persisted."""
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
            raise SetupError("SSH connection failed. Check IP, root/jibo credentials, and developer-mode boot.") from None
        self.worker = "/var/tmp/beetle-5x1-worker.py"

    def upload_worker(self):
        with self.client.open_sftp() as sftp:
            sftp.put(str(Path(__file__).with_name("beetle_robot.py")), self.worker)
            sftp.chmod(self.worker, 0o600)
            sftp.put(str(Path(__file__).parent / "assets/5x1/isrg-root-x1.pem"), "/var/tmp/beetle-isrg-root-x1.pem")
            sftp.chmod("/var/tmp/beetle-isrg-root-x1.pem", 0o644)

    def upload(self, local, remote):
        with self.client.open_sftp() as sftp:
            sftp.put(str(local), remote)
            sftp.chmod(remote, 0o600)

    def call(self, action, payload=None, timeout=180):
        print("5x1 setup: " + action.replace("-", " "), flush=True)
        stdin, stdout, stderr = self.client.exec_command("python " + self.worker, timeout=timeout)
        stdin.write(json.dumps({"action": action, "payload": payload or {}}) + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
        try:
            raw = stdout.read(1024 * 1024)
            value = json.loads(raw)
            if stdout.channel.recv_exit_status() or not value.get("ok"):
                raise SetupError(value.get("error", "Robot setup step failed."))
            return value["result"]
        except (ValueError, OSError, socket.timeout, EOFError):
            raise SetupError("Robot connection interrupted. Reconnect and resume this session.") from None
        finally:
            stdin.close()
            stdout.close()
            stderr.close()

    def close(self):
        self.client.close()


class SetupController:
    def __init__(self, api, session, text, select, confirm, message, ssh_factory=SSH,
                 provisioner=provision, downloader=download_beam, sleep=time.sleep):
        self.api, self.session = api, Session(session)
        self.text, self.select, self.confirm, self.message = text, select, confirm, message
        self.ssh_factory, self.provisioner, self.downloader, self.sleep = ssh_factory, provisioner, downloader, sleep

    def approved(self, title, detail):
        if not self.confirm(title, detail):
            raise Cancelled("Setup paused. Resume this session to continue.")

    def input(self, title, prompt, **kwargs):
        value = self.text(title, prompt, **kwargs)
        if value is None:
            raise Cancelled("Setup paused. Resume this session to continue.")
        return value

    def check_robot(self, report):
        if identity(report["identity"]) != self.session.data["identity"]:
            raise SetupError("SSH robot does not match the USB backup. No installation was attempted.")
        expected = self.session.data["calibration"]
        if report.get("calibration") != expected:
            raise SetupError("Camera calibration changed. Check the rollback backup before continuing.")

    def run(self, port=None):
        s = self.session
        ssh = None
        try:
            if "backup" not in s.data["done"]:
                self.approved("Prepare 5x1 setup", "Back up var, both rootfs slots, services and skills. "
                    "Then configure developer mode and Wi-Fi, install BEam/BEnch, provision missing credentials, "
                    "update body firmware and finish in normal mode. Keep power connected.")
                backup = self.api.backup_partitions(PARTITIONS, port=port)
                robot, mode, calibration = read_factory(self.api, backup)
                s.data.update(identity=robot, original_mode=mode, calibration=calibration,
                              backup_set=backup["manifest"], partitions=backup["partitions"])
                s.mark("backup")
            else:
                for entry in s.data["partitions"]:
                    image = Path(entry["image"])
                    digest = hashlib.sha256()
                    with image.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                    if image.stat().st_size != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]:
                        raise SetupError("Rollback backup changed; restore its verified copy before resuming.")
            if "usb" not in s.data["done"]:
                ssid = self.input("5x1 Wi-Fi", "Wi-Fi network name (SSID):")
                kind = self.select("Network security", (("protected", "WPA/WPA2"), ("open", "Open network")))
                if kind is None:
                    raise Cancelled("Wi-Fi setup paused.")
                password = None if kind == "open" else self.input("5x1 Wi-Fi", "Wi-Fi password:", password=True)
                if kind != "open" and password != self.input("5x1 Wi-Fi", "Repeat Wi-Fi password:", password=True):
                    raise SetupError("Wi-Fi passwords do not match.")
                confirm = lambda plan: self.confirm("Confirm USB preparation", "Configure int-developer mode and Wi-Fi using the verified var backup.")
                try:
                    if self.api._live_var_file_available(port, self.api.tool("dfu-util")):
                        result = self.api.set_mode_wifi_file_live("int-developer", ssid, password, kind == "open",
                            port=port, confirmation=confirm, guided=True)
                    else:
                        self.approved("Full var preparation", "This loader does not expose the fast file editor. Use the full backed-up var transfer and readback verification?")
                        result = self.api.set_mode_wifi_live("int-developer", ssid, password, kind == "open", port=port, confirmation=confirm)
                except self.api.FileRpcStatusError as error:
                    if error.status not in (3, 4):
                        raise
                    self.approved("Full var fallback", "The fast writer cannot handle this filesystem. Use a full backed-up var transfer and readback verification?")
                    result = self.api.set_mode_wifi_live("int-developer", ssid, password, kind == "open", port=port, confirmation=confirm)
                finally:
                    password = None
                if result.get("status") not in ("verified", "already current"):
                    raise Cancelled("USB preparation did not complete.")
                s.mark("usb")
                self.message("Restart Jibo", ["Power-cycle out of recovery mode. Wait for Wi-Fi, then enter the IP from your router's device list."])
            host = self.input("Connect over Wi-Fi", "Robot IP or hostname:", default=s.data.get("host", ""))
            username = self.input("SSH user", "SSH username:", default="root")
            password = self.input("SSH password", "SSH password (default jibo):", default="jibo", password=True)
            ssh = self.ssh_factory(host, username, password, s, self.confirm)
            password = None
            ssh.upload_worker()
            report = ssh.call("inspect")
            self.check_robot(report)
            if s.data.get("awaiting_reboot"):
                for update in s.data["pending_updates"]["updates"]:
                    if report["versions"].get(update["subsystem"]) != update["toVersion"]:
                        raise SetupError("An interrupted OTA has not reached its target version. Check the robot's update status before resuming.")
                s.data.pop("awaiting_reboot", None)
                s.data.pop("pending_updates", None)
                s.save()
            s.data["host"] = host
            s.data["versions"] = report["versions"]
            s.mark("ssh")
            if "credentials" not in s.data["done"] or not report["has_credentials"]:
                self.approved("Configure robot credentials", "Preserve existing keys; request credentials from BEefy only if this robot has none. Point OTA at " + OTA + ".")
                supplied = None if report["has_credentials"] else self.provisioner(s.data["identity"], s.data["backup_set"])
                ssh.call("credentials", {"credentials": supplied})
                supplied = None
                s.mark("credentials")
            if "beam" not in s.data["done"]:
                self.approved("Install BEam", "Install revision " + BEAM_REVISION + "; preserve Knowledge, eyes, music and calibration. The current skills partition is backed up.")
                with tempfile.TemporaryDirectory(prefix="beetle-beam-") as tmp:
                    archive = Path(tmp) / "beam.zip"
                    self.downloader(archive)
                    digest = file_sha256(archive)
                    with zipfile.ZipFile(archive) as package:
                        expanded = sum(info.file_size for info in package.infolist())
                    ssh.call("stage-archive", {"required_bytes": archive.stat().st_size + expanded + 128 * 1024 * 1024})
                    ssh.upload(archive, "/opt/tmp/beetle-beam.zip")
                    ssh.call("beam", {"sha256": digest, "revision": BEAM_REVISION}, timeout=1800)
                s.mark("beam")
            # Always reapply after reconnect: services OTA can replace these files.
            self.approved("Configure 5x1 services", "Set hub and OTA endpoints, install legacy TLS compatibility, skip pre-OTA backup, and allow SSH during installation.")
            ssh.call("configure")
            s.mark("configure")
            if "ota" not in s.data["done"]:
                self.approved("Install BEaker updates", "Check and install applicable BEam/BEnch updates using the robot's checksum-verified OTA path. Jibo may reboot several times.")
                for attempt in range(5):
                    checked = ssh.call("ota-check", timeout=180)
                    if not checked["ids"]:
                        s.mark("ota")
                        break
                    s.data["pending_updates"] = checked
                    s.save()
                    ssh.call("ota-download", {"ids": checked["ids"]}, timeout=7200)
                    # Journal before apply; connection loss during reboot is expected.
                    s.data["awaiting_reboot"] = True
                    s.save()
                    try:
                        ssh.call("ota-apply", {"ids": checked["ids"]}, timeout=180)
                    except SetupError:
                        pass
                    ssh.close()
                    ssh = self.reconnect(host, username, s)
                    report = ssh.call("inspect")
                    self.check_robot(report)
                    for update in checked["updates"]:
                        if report["versions"].get(update["subsystem"]) != update["toVersion"]:
                            raise SetupError("An OTA target version was not installed. Check robot update status and resume.")
                    ssh.call("configure")
                    s.data.pop("awaiting_reboot", None)
                    s.data.pop("pending_updates", None)
                    s.save()
                else:
                    raise SetupError("Updates did not converge after five checks; inspect BEaker catalog before retrying.")
            if "firmware" not in s.data["done"]:
                self.approved("Update body firmware", "Stop robot processes and run jibo-bbfw-update with its board detection. Keep Jibo connected to power.")
                ssh.call("firmware", timeout=900)
                s.mark("firmware")
            if "normal" not in s.data["done"]:
                self.approved("Finish in normal mode", "Start BEam in normal mode and reboot. SSH remains available for verification and recovery.")
                ssh.call("normal")
                s.data["awaiting_normal_reboot"] = True
                s.mark("normal")
            if s.data.get("awaiting_normal_reboot"):
                try:
                    ssh.call("reboot")
                except SetupError:
                    pass
                ssh.close()
                ssh = self.reconnect(host, username, s)
                s.data.pop("awaiting_normal_reboot", None)
                s.save()
            verified = ssh.call("verify", timeout=180)
            self.check_robot(verified)
            s.data["verification"] = {k: verified[k] for k in ("versions", "mode", "hub", "ota", "services", "cloud")}
            s.mark("verify")
            s.mark("complete")
            return {"status": "verified", "mode": "normal", "message": "5x1 setup complete; Jibo is running BEam.", "session": str(s.path), "backup": s.data["backup_set"]}
        except Cancelled as error:
            return {"status": "cancelled", "message": str(error), "session": str(s.path)}
        except Exception as error:
            s.save()
            # Network subprocess errors must not serialize payloads or keys.
            message = str(error) if isinstance(error, SetupError) else "Setup failed while checking or changing the robot. Review the toolkit backup records."
            raise SetupError(message + " Resume " + str(s.path) + " at stage " + s.data["stage"] + ".") from None
        finally:
            if ssh is not None:
                ssh.close()

    def reconnect(self, host, username, session):
        # Ask once; retries keep the password only in memory.
        password = self.input("Reconnect after reboot", "SSH password:", default="jibo", password=True)
        self.sleep(20)
        try:
            for attempt in range(30):
                try:
                    print("Waiting for Jibo after reboot ({}/30)…".format(attempt + 1), flush=True)
                    ssh = self.ssh_factory(host, username, password, session, self.confirm)
                    ssh.upload_worker()
                    return ssh
                except Cancelled:
                    raise
                except SetupError:
                    self.sleep(10)
            raise SetupError("Jibo did not reconnect in five minutes. Check its IP and resume.")
        finally:
            password = None


def run_guided(api, flows, port=None):
    default = str(api.BACKUP_ROOT / "beetle-5x1-session.json")
    session = flows.text_input("5x1 setup session", "Session file (reuse it to resume):", default=default)
    if session is None:
        return {"status": "cancelled", "message": "Setup cancelled."}
    return SetupController(api, session, flows.text_input, flows.select_option,
        flows.confirm_action, flows.show_screen).run(port)


def cli(api, args):
    import getpass
    def text(title, prompt, default="", password=False, **kwargs):
        value = getpass.getpass(prompt) if password else input(prompt + (" [" + default + "] " if default else " "))
        return value or default
    def select(title, options, **kwargs):
        print(title)
        for key, label in options:
            print(key + ": " + label)
        value = input("Choice (blank cancels): ")
        return value if value in dict(options) else None
    def confirm(title, detail):
        print(title + "\n" + detail)
        return input("Type YES to continue: ") == "YES"
    return SetupController(api, args.session or api.BACKUP_ROOT / "beetle-5x1-session.json",
        text, select, confirm, lambda title, lines: print(title + "\n" + "\n".join(lines))).run(args.port)
