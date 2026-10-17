"""Guided preparation and exact external-PM handoff; no robot/network calls."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
import beetle_setup as setup

IDENTITY = {"name": "Fixture-Robot-Only", "serial_number": "BOJW000000000", "cpuid": "fixture-cpu", "wifi_mac": "00:11:22:33:44:55"}
EXPECTED_OOBE = (
    "jibo-mount --rw",
    "curl -fsSL -k https://raw.githubusercontent.com/Jibo-Revival-Group/BEach/master/PM/post-oobe-mod.sh -o /tmp/pm.sh",
    "chmod +x /tmp/pm.sh",
    "sh /tmp/pm.sh",
)

EXPECTED_NORMAL = ("jibo-mount --rw", "curl -fsSL -k https://scripts.5x1.com/pm -o /tmp/pm.sh",
                   "chmod +x /tmp/pm.sh", "sh /tmp/pm.sh")


class FakeAPI:
    MARKER = "jibo-ram-dfu"
    def __init__(self, tmp_path, state="dfu"):
        self.tmp_path, self.state, self.calls = tmp_path, state, []
    def devices(self):
        return [] if self.state == "none" else [{"port": "1-1", "state": self.state}]
    def tool(self, name):
        return name
    def dfu_alternatives(self, *args):
        return (self.MARKER, "var"), ""
    def shofel_dfu_available(self):
        return True
    def enter_shofel_dfu(self, **kwargs):
        self.calls.append(("enter-dfu", kwargs))
        self.state = "dfu"
        return {"port": "1-1"}
    def backup_partitions(self, partitions, **kwargs):
        self.calls.append(("backup", partitions))
        entries = []
        for name in partitions:
            p = self.tmp_path / (name + ".img")
            p.write_bytes(b"fixture")
            entries.append({"name": name, "image": str(p), "size_bytes": 7,
                            "sha256": hashlib.sha256(b"fixture").hexdigest()})
        return {"manifest": "fixture-backup-set", "partitions": entries}
    def backup_var(self, **kwargs):
        assert kwargs["refresh"] is True
        self.calls.append(("live-var", kwargs))
        return {"image": str(self.tmp_path / "var.img"), "manifest": "current-var-manifest"}
    def set_mode_wifi_live(self, *args, **kwargs):
        self.calls.append(("usb", args, kwargs))
        return {"status": "verified"} if kwargs["confirmation"]({}) else {"status": "cancelled"}


class FakeSSH:
    def __init__(self, robot=None, fail_command=None, completed=False):
        self.robot = robot or IDENTITY
        self.calls, self.fail_command, self.completed = [], fail_command, completed
    def inspect(self):
        self.calls.append("inspect")
        return {"identity": self.robot, "mode": "normal" if self.completed else "int-developer", "pm_complete": self.completed}
    def run_pm(self, commands, before_command):
        for i, command in enumerate(commands):
            before_command(i)
            self.calls.append(command)
            if i == self.fail_command:
                raise setup.ConnectionLost("Connection interrupted.")
        return {"completed": True}
    def close(self):
        self.calls.append("close")


def controller(tmp_path, monkeypatch, mode="oobe", state="dfu", ssh=None, confirmations=True):
    api, ssh = FakeAPI(tmp_path, state), ssh or FakeSSH()
    monkeypatch.setattr(setup, "read_factory", lambda *args: (IDENTITY, mode, {"calibration": "hash"}))
    answers = iter(("network", "wifi-secret", "wifi-secret", "192.0.2.4", "root", "ssh-secret"))
    selections = iter((["retry"] if state == "none" else []) + ["protected"])
    messages = []
    reviews = []
    def select(*args, **kwargs):
        if api.state == "none":
            api.state = "rcm"
        return next(selections, None)
    def confirm(title, detail):
        reviews.append((title, detail))
        return confirmations
    c = setup.SetupController(api, tmp_path / "session.json", lambda *args, **kwargs: next(answers),
        select, confirm, lambda *args: messages.append(args), ssh_factory=lambda *args: ssh)
    return c, api, ssh, messages, reviews


@pytest.mark.parametrize("mode", ["oobe", "identified"])
def test_oobe_runs_exact_four_commands_and_ip_display(tmp_path, monkeypatch, mode):
    c, api, ssh, messages, reviews = controller(tmp_path, monkeypatch, mode=mode)
    assert c.run()["status"] == "complete"
    usb = next(call for call in api.calls if call[0] == "usb")
    assert usb[1] == ("int-developer", "network", "wifi-secret", False)
    assert usb[2]["network_status"] == "install"
    assert c.session.data["current_var_backup"] == "current-var-manifest"
    assert ssh.calls == ["inspect", *EXPECTED_OOBE, "close"]
    assert any("screen" in " ".join(lines) for title, lines in messages)
    assert "\n".join(EXPECTED_OOBE) in reviews[-1][1]
    saved = c.session.path.read_text()
    assert "wifi-secret" not in saved and "ssh-secret" not in saved
    assert c.session.data["original_mode"] == mode and c.session.data["is_oobe"]


@pytest.mark.parametrize("mode", ["normal", "developer", "int-developer"])
def test_provisioned_robot_runs_exact_normal_pm(tmp_path, monkeypatch, mode):
    c, api, ssh, messages, reviews = controller(tmp_path, monkeypatch, mode=mode)
    result = c.run()
    assert result["mode"] == "normal" and result["status"] == "complete"
    assert ssh.calls == ["inspect", *EXPECTED_NORMAL, "close"]
    assert c.session.data["pm_url"] == setup.PM_URL
    assert c.session.data["original_mode"] == mode and not c.session.data["is_oobe"]
    assert "\n".join(EXPECTED_NORMAL) in reviews[-1][1]


def test_wizard_handles_connect_then_rcm_entry(tmp_path, monkeypatch):
    c, api, ssh, messages, reviews = controller(tmp_path, monkeypatch, state="none")
    c.run()
    entry = next(call for call in api.calls if call[0] == "enter-dfu")
    assert entry[1] == {"port": "1-1", "confirm_meerkat_rev02": True}
    assert api.calls.index(entry) < next(i for i, call in enumerate(api.calls) if call[0] == "backup")


def test_wrong_robot_never_runs_pm(tmp_path, monkeypatch):
    ssh = FakeSSH(dict(IDENTITY, cpuid="wrong"))
    c, *_ = controller(tmp_path, monkeypatch, ssh=ssh)
    with pytest.raises(setup.SetupError, match="does not match"):
        c.run()
    assert ssh.calls == ["inspect", "close"]


def test_cancellation_before_backup_changes_nothing(tmp_path, monkeypatch):
    c, api, ssh, *_ = controller(tmp_path, monkeypatch, confirmations=False)
    assert c.run()["status"] == "cancelled"
    assert not api.calls and not ssh.calls


def test_interrupted_pm_is_not_automatically_repeated(tmp_path, monkeypatch):
    c, api, ssh, *_ = controller(tmp_path, monkeypatch, ssh=FakeSSH(fail_command=3))
    with pytest.raises(setup.SetupError, match="interrupted"):
        c.run()
    assert c.session.data["pm_started"]
    ssh.calls.clear()
    answers = iter(("192.0.2.4", "root", "ssh-secret"))
    c.text = lambda *args, **kwargs: next(answers)
    c.select = lambda *args, **kwargs: "pause"
    assert c.run()["status"] == "cancelled"
    assert ssh.calls == ["inspect", "close"]


def test_external_receipt_can_finish_interrupted_session(tmp_path, monkeypatch):
    ssh = FakeSSH(fail_command=3)
    c, *_ = controller(tmp_path, monkeypatch, ssh=ssh)
    with pytest.raises(setup.SetupError):
        c.run()
    ssh.calls.clear()
    ssh.completed = True
    answers = iter(("192.0.2.4", "root", "ssh-secret"))
    c.text = lambda *args, **kwargs: next(answers)
    assert c.run()["status"] == "complete"
    assert ssh.calls == ["inspect", "close"]


def test_completed_wizard_does_not_repeat_pm(tmp_path, monkeypatch):
    c, api, ssh, *_ = controller(tmp_path, monkeypatch)
    c.run()
    before = list(ssh.calls)
    assert c.run()["status"] == "complete"
    assert ssh.calls == before


def test_original_oobe_survives_old_session_migration(tmp_path):
    p = tmp_path / "session.json"
    p.write_text(json.dumps({"schema": 1, "kind": "beetle-5x1-setup", "done": ["backup", "usb", "normal"],
        "original_mode": "oobe", "fingerprints": {}}))
    session = setup.Session(p)
    assert session.data["schema"] == 2 and session.data["done"] == ["backup"]
    assert session.data["original_mode"] == "oobe"


def test_standard_pm_sequence_is_unchanged():
    assert setup.pm_commands(setup.PM_URL) == (
        "jibo-mount --rw", "curl -fsSL -k https://scripts.5x1.com/pm -o /tmp/pm.sh", "chmod +x /tmp/pm.sh", "sh /tmp/pm.sh")
    with pytest.raises(setup.SetupError):
        setup.pm_commands("https://other.example/script")


class Channel:
    def __init__(self, output=b"PM output\n", status=0):
        self.output, self.status, self.closed, self.commands = output, status, False, []
    def set_combine_stderr(self, value):
        assert value
    def get_pty(self, **kwargs):
        self.pty = kwargs
    def exec_command(self, command):
        self.commands.append(command)
    def recv_ready(self):
        return bool(self.output)
    def recv(self, size):
        value, self.output = self.output, b""
        return value
    def exit_status_ready(self):
        return True
    def recv_exit_status(self):
        return self.status
    def close(self):
        self.closed = True


def transport(channels):
    pending = iter(channels)
    return SimpleNamespace(is_active=lambda: True, open_session=lambda **kwargs: next(pending))


def test_actual_ssh_transport_sends_only_exact_commands(capsys):
    channels = [Channel(), Channel(), Channel(), Channel(output=b"5X1_OOBE_PM_COMPLETE\n")]
    ssh = setup.SSH.__new__(setup.SSH)
    ssh.client = SimpleNamespace(get_transport=lambda: transport(channels))
    current = transport(channels)
    ssh.client.get_transport = lambda: current
    steps = []
    ssh.run_pm(EXPECTED_OOBE, steps.append)
    assert [channel.commands[0] for channel in channels] == list(EXPECTED_OOBE)
    assert steps == [0, 1, 2, 3]
    assert "PM output" in capsys.readouterr().out


def test_failed_download_stops_before_chmod_or_pm():
    channels = [Channel(), Channel(status=22), Channel(), Channel()]
    ssh = setup.SSH.__new__(setup.SSH)
    current = transport(channels)
    ssh.client = SimpleNamespace(get_transport=lambda: current)
    with pytest.raises(setup.SetupError, match="command 2 failed"):
        ssh.run_pm(EXPECTED_OOBE, lambda index: None)
    assert not channels[2].commands and not channels[3].commands


def test_only_completion_marker_allows_disconnect_at_final_command():
    channels = [Channel(), Channel(), Channel(), Channel(output=b"5X1_OOBE_PM_COMPLETE\n", status=-1)]
    ssh = setup.SSH.__new__(setup.SSH)
    current = transport(channels)
    ssh.client = SimpleNamespace(get_transport=lambda: current)
    with pytest.raises(setup.ConnectionLost) as result:
        ssh.run_pm(EXPECTED_OOBE, lambda index: None)
    assert result.value.completed


@pytest.mark.parametrize("accept,known,success", [(True, None, True), (False, None, False), (True, "different", False)])
def test_ssh_key_acceptance_and_changed_key_rejection(tmp_path, monkeypatch, accept, known, success):
    import paramiko
    class Key:
        def asbytes(self):
            return b"fixture-key"
        def get_name(self):
            return "ssh-rsa"
    class Client:
        def set_missing_host_key_policy(self, policy):
            self.policy = policy
        def get_host_keys(self):
            return SimpleNamespace(add=lambda *args: None)
        def connect(self, host, **kwargs):
            self.policy.missing_host_key(self, host, Key())
        def close(self):
            pass
    monkeypatch.setattr(paramiko, "SSHClient", Client)
    s = setup.Session(tmp_path / "session.json")
    if known:
        s.data["fingerprints"]["fixture-host"] = known
    if success:
        setup.SSH("fixture-host", "root", "ssh-secret", s, lambda *args: accept)
        assert s.data["fingerprints"]["fixture-host"].startswith("SHA256:")
        assert "ssh-secret" not in s.path.read_text()
    else:
        with pytest.raises(setup.SetupError):
            setup.SSH("fixture-host", "root", "ssh-secret", s, lambda *args: accept)


def test_source_contains_no_embedded_pm_implementation():
    source = Path(setup.__file__).read_text()
    assert not Path(setup.__file__).with_name("beetle_robot.py").exists()
    assert all(text not in source for text in ("jibo-bbfw-update", "rejectUnauthorized", "PrepareRobot", "SetupRobot", "beam.zip"))
    assert not hasattr(setup.SSH, "upload") and not hasattr(setup.SSH, "upload_worker")


def test_gui_and_tui_share_wizard(monkeypatch):
    import jibo_tui
    calls = []
    monkeypatch.setattr(setup, "run_guided", lambda api, flows, port: calls.append((api, flows, port)) or {"status": "cancelled"})
    api = object()
    jibo_tui.execute_action(api, "setup-5x1", jibo_tui.Readiness("none", ()))
    assert calls == [(api, jibo_tui, None)]


def test_old_oobe_script_without_completion_is_not_accepted():
    channels = [Channel() for _ in range(4)]
    ssh = setup.SSH.__new__(setup.SSH)
    current = transport(channels)
    ssh.client = SimpleNamespace(get_transport=lambda: current)
    with pytest.raises(setup.SetupError, match="did not report completion"):
        ssh.run_pm(EXPECTED_OOBE, lambda index: None)


def test_oobe_detection_uses_current_snapshot_instead_of_reused_baseline(tmp_path, monkeypatch):
    c, api, ssh, *_ = controller(tmp_path, monkeypatch)
    fresh = tmp_path / "fresh-var.img"
    fresh.write_bytes(b"current OOBE fixture")
    monkeypatch.setattr(api, "backup_var", lambda **kwargs: {"image": str(fresh), "manifest": "fresh-manifest"})
    def inspect(api, backup):
        assert next(p for p in backup["partitions"] if p["name"] == "var")["image"] == str(fresh)
        return IDENTITY, "oobe", {"calibration": "hash"}
    monkeypatch.setattr(setup, "read_factory", inspect)
    c.run()
    assert c.session.data["is_oobe"] and c.session.data["current_var_backup"] == "fresh-manifest"


def test_preparation_only_session_resumes_at_ssh(tmp_path, monkeypatch):
    c, api, ssh, *_ = controller(tmp_path, monkeypatch, mode="normal")
    c.run()
    c.session.data.update(pm_skipped=True, done=["backup", "usb", "complete"])
    for key in ("pm_started", "pm_command", "pm_url"):
        c.session.data.pop(key, None)
    c.session.save()
    c.session = setup.Session(c.session.path)
    assert c.session.data["stage"] == "ssh"
    assert "complete" not in c.session.data["done"]
    api.calls.clear()
    ssh.calls.clear()
    answers = iter(("192.0.2.4", "root", "ssh-secret"))
    c.text = lambda *args, **kwargs: next(answers)
    assert c.run()["status"] == "complete"
    assert not api.calls
    assert ssh.calls == ["inspect", *EXPECTED_NORMAL, "close"]


def test_stale_oobe_receipt_does_not_finish_interrupted_normal_pm(tmp_path, monkeypatch):
    ssh = FakeSSH(fail_command=3)
    c, *_ = controller(tmp_path, monkeypatch, mode="normal", ssh=ssh)
    with pytest.raises(setup.SetupError):
        c.run()
    ssh.calls.clear()
    ssh.completed = True
    answers = iter(("192.0.2.4", "root", "ssh-secret"))
    c.text = lambda *args, **kwargs: next(answers)
    c.select = lambda *args, **kwargs: "pause"
    assert c.run()["status"] == "cancelled"
    assert ssh.calls == ["inspect", "close"]


@pytest.mark.parametrize("output,completed", [
    (setup.NORMAL_PM_COMPLETE.encode() + b"\r\n", True),
    (b"5X1_OOBE_PM_COMPLETE\n", False),
    (b"installation interrupted\n", False),
])
def test_normal_pm_terminal_and_reboot_completion(output, completed):
    channels = [Channel(), Channel(), Channel(), Channel(output=output, status=-1)]
    ssh = setup.SSH.__new__(setup.SSH)
    current = transport(channels)
    ssh.client = SimpleNamespace(get_transport=lambda: current)
    with pytest.raises(setup.ConnectionLost) as result:
        ssh.run_pm(EXPECTED_NORMAL, lambda index: None)
    assert result.value.completed is completed
    assert [channel.commands[0] for channel in channels] == list(EXPECTED_NORMAL)
    assert channels[3].pty == {"term": "xterm"}
    assert all(not hasattr(channel, "pty") for channel in channels[:3])
