"""Setup safety and recovery tests; no robot or production cloud is contacted."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
import beetle_setup as setup
import beetle_robot as robot

IDENTITY = {"name": "Fixture-Robot-Only", "serial_number": "BOJW000000000", "cpuid": "fixture-cpu", "wifi_mac": "00:11:22:33:44:55"}
KEYS = {"accessKeyId": "fixture-access", "secretAccessKey": "fixture-secret", "extra": "preserve"}


@pytest.fixture
def filesystem(tmp_path, monkeypatch):
    monkeypatch.setattr(robot, "ROOT", str(tmp_path))
    def write(p, value):
        target = tmp_path / p.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value) if isinstance(value, dict) else value)
        return target
    write("/var/jibo/identity.json", IDENTITY)
    write("/var/jibo/mode.json", {"mode": "oobe"})
    for name in robot.CALIBRATION:
        write("/var/jibo/lps/" + name, {"fixture": name})
    write("/usr/local/etc/jibo-jetstream-service.json", {"HubClient": {"keep": True}})
    client = "/usr/local/bin/jibo-ssm/node_modules/@jibo/jibo-server-client/lib"
    write(client + "/region_config.json", {"patterns": {"other": {"keep": True}}})
    write(client + "/http/node.js", "var options = {rejectUnauthorized: true};")
    write("/usr/local/bin/jibo-ssm/lib/manager.js", "this._backupHelper((bkError, maxError) => {")
    write("/etc/ssl/certs/ca-certificates.crt", "original trust\n")
    cert = Path(setup.__file__).parent / "assets/5x1/isrg-root-x1.pem"
    write("/var/tmp/beetle-isrg-root-x1.pem", cert.read_text())
    write("/opt/jibo/Jibo/Skills/@be/be/package.json", {"name": "@be/be", "version": "1.0.0"})
    write("/etc/init.d/S21firewall", "fixture firewall")
    return tmp_path, write


def test_oobe_has_no_credentials_and_preserves_factory_data(filesystem):
    before = robot.inspect()
    assert not before["has_credentials"] and before["mode"] == "oobe"
    robot.set_credentials({"credentials": KEYS})
    after = robot.inspect()
    assert after["identity"] == before["identity"] and after["calibration"] == before["calibration"]
    assert robot.load("/var/jibo/credentials.json") == setup.credentials(KEYS)
    assert robot.path("/var/jibo/credentials.json")
    assert Path(robot.path("/var/jibo/credentials.json")).stat().st_mode & 0o777 == 0o600


def test_preserve_existing_keys_even_if_new_keys_are_supplied(filesystem):
    robot.set_credentials({"credentials": KEYS})
    robot.set_credentials({"credentials": {"accessKeyId": "other", "secretAccessKey": "other"}})
    assert robot.load("/var/jibo/credentials.json") == setup.credentials(KEYS)


@pytest.mark.parametrize("bad", [None, {}, {"accessKeyId": "one"}, {"accessKeyId": "one", "secretAccessKey": ""}, []])
def test_invalid_credentials_write_nothing(filesystem, bad):
    with pytest.raises(robot.RobotError):
        robot.set_credentials({"credentials": bad})
    assert not Path(robot.path("/var/jibo/credentials.json")).exists()


def test_configuration_is_repeatable_and_reapplies_after_ota(filesystem):
    robot.set_credentials({"credentials": KEYS})
    before = robot.inspect()
    robot.configure()
    bundle = robot.read("/etc/ssl/certs/ca-certificates.crt")
    robot.configure()
    assert robot.read("/etc/ssl/certs/ca-certificates.crt") == bundle
    assert robot.load("/usr/local/etc/jibo-jetstream-service.json")["HubClient"]["keep"]
    assert robot.inspect()["calibration"] == before["calibration"]
    root, write = filesystem
    write("/usr/local/etc/jibo-jetstream-service.json", {"HubClient": {}})
    robot.configure()
    assert robot.load("/usr/local/etc/jibo-jetstream-service.json")["HubClient"]["override"]["hub_hostname"] == setup.HUB
    assert "Skipping pre-OTA backup" in robot.read("/usr/local/bin/jibo-ssm/lib/manager.js").decode()


def test_unknown_patch_target_fails_before_configuration_writes(filesystem):
    robot.set_credentials({"credentials": KEYS})
    root, write = filesystem
    before = robot.read("/usr/local/etc/jibo-jetstream-service.json")
    write("/usr/local/bin/jibo-ssm/lib/manager.js", "unknown SSM")
    with pytest.raises(robot.RobotError, match="Unsupported SSM"):
        robot.configure()
    assert robot.read("/usr/local/etc/jibo-jetstream-service.json") == before


def test_bad_archive_checksum_changes_no_skills(filesystem):
    root, write = filesystem
    write("/opt/tmp/beetle-beam.zip", "bad bytes")
    before = robot.read("/opt/jibo/Jibo/Skills/@be/be/package.json")
    with pytest.raises(robot.RobotError, match="checksum"):
        robot.install_beam({"sha256": "wrong", "revision": setup.BEAM_REVISION})
    assert robot.read("/opt/jibo/Jibo/Skills/@be/be/package.json") == before


def test_beam_install_preserves_custom_skills_and_libraries(filesystem):
    root, write = filesystem
    write("/opt/jibo/Knowledge/beacon/eye/custom.png", "custom eye")
    write("/opt/tmp/jukebox-music/song.mp3", "music")
    write("/opt/jibo/Jibo/Skills/custom/package.json", {"name": "custom", "version": "1"})
    archive = root / "opt/tmp/beetle-beam.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("BEam-" + setup.BEAM_REVISION + "/@be/be/package.json", json.dumps({"name": "@be/be", "version": "13.0.7"}))
    robot.install_beam({"sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "revision": setup.BEAM_REVISION})
    assert robot.load("/opt/jibo/Jibo/Skills/custom/package.json")["name"] == "custom"
    assert robot.read("/opt/jibo/Knowledge/jukebox/music/song.mp3") == b"music"
    assert robot.read("/opt/jibo/Knowledge/beacon/eye/custom.png") == b"custom eye"
    assert robot.load("/opt/jibo/beetle-skills-before-5x1/@be/be/package.json")["version"] == "1.0.0"


def test_provision_uses_prepared_token_and_real_credentials():
    calls = []
    def request(operation, body):
        calls.append((operation, dict(body)))
        return {"token": "fixture-token", "conversionReadiness": {"canWriteRobot": True}} if operation == "PrepareRobot" else KEYS
    assert setup.provision(IDENTITY, "rollback", request) == setup.credentials(KEYS)
    assert [p for p, body in calls] == ["PrepareRobot", "SetupRobot"]
    assert calls[1][1]["token"] == "fixture-token"
    assert calls[0][1]["rollbackSnapshotId"] == "rollback"


def test_provision_stops_if_server_blocks_readiness():
    with pytest.raises(setup.SetupError, match="blocked"):
        setup.provision(IDENTITY, "rollback", lambda *args: {"token": "t", "conversionReadiness": {"canWriteRobot": False}})


class FakeSSH:
    def __init__(self, report, fail=None):
        self.report, self.fail, self.calls = report, fail, []
    def upload_worker(self):
        pass
    def upload(self, *args):
        pass
    def close(self):
        pass
    def call(self, action, payload=None, **kwargs):
        self.calls.append(action)
        if action == self.fail:
            raise setup.SetupError("fixture failure")
        if action in ("inspect", "verify"):
            return self.report
        if action == "ota-check":
            return {"ids": [], "updates": []}
        return {}


def controller(tmp_path, ssh, done=("backup", "usb"), confirm=lambda *args: True):
    image = tmp_path / "backup.img"
    image.write_bytes(b"fixture-backup")
    session = setup.Session(tmp_path / "session.json")
    session.data.update(identity=IDENTITY, calibration={"fixture": "hash"}, backup_set="fixture-set",
        partitions=[{"image": str(image), "size_bytes": image.stat().st_size, "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}], done=list(done))
    session.save()
    answers = iter(("fixture-host", "root", "password"))
    def download(p):
        Path(p).write_bytes(b"fixture archive")
    return setup.SetupController(SimpleNamespace(), session.path, lambda *args, **kwargs: next(answers),
        lambda *args: None, confirm, lambda *args: None, ssh_factory=lambda *args: ssh,
        provisioner=lambda *args: KEYS, downloader=download, sleep=lambda *args: None)


def report(**changes):
    value = {"identity": dict(IDENTITY), "calibration": {"fixture": "hash"}, "has_credentials": False,
             "versions": {"services": "13.0.3"}, "mode": "normal", "hub": setup.HUB, "ota": setup.OTA,
             "services": True, "cloud": True}
    value.update(changes)
    return value


def test_wrong_ssh_robot_prevents_installation(tmp_path):
    wrong = dict(IDENTITY, cpuid="different")
    ssh = FakeSSH(report(identity=wrong))
    with pytest.raises(setup.SetupError, match="does not match"):
        controller(tmp_path, ssh).run()
    assert ssh.calls == ["inspect"]


def test_failure_saves_stage_and_no_keys(tmp_path):
    ssh = FakeSSH(report(), fail="beam")
    c = controller(tmp_path, ssh)
    with pytest.raises(setup.SetupError, match="stage beam"):
        c.run()
    raw = c.session.path.read_text()
    assert "fixture-secret" not in raw and "password" not in raw
    assert json.loads(raw)["stage"] == "beam"


def test_resume_does_not_repeat_completed_install(tmp_path):
    ssh = FakeSSH(report(has_credentials=True))
    c = controller(tmp_path, ssh, ("backup", "usb", "credentials", "beam", "ota", "firmware", "normal"))
    result = c.run()
    assert result["status"] == "verified"
    assert ssh.calls == ["inspect", "configure", "verify"]
    assert c.session.data["stage"] == "complete"


def test_cancel_before_configuration_is_persisted(tmp_path):
    ssh = FakeSSH(report(has_credentials=True))
    c = controller(tmp_path, ssh, ("backup", "usb", "credentials", "beam"), confirm=lambda *args: False)
    assert c.run()["status"] == "cancelled"
    assert ssh.calls == ["inspect"]


def test_changed_rollback_backup_blocks_resume(tmp_path):
    ssh = FakeSSH(report())
    c = controller(tmp_path, ssh)
    Path(c.session.data["partitions"][0]["image"]).write_bytes(b"changed")
    with pytest.raises(setup.SetupError, match="backup changed"):
        c.run()
    assert not ssh.calls


def test_interrupted_ota_requires_target_versions(tmp_path):
    ssh = FakeSSH(report(has_credentials=True))
    c = controller(tmp_path, ssh)
    c.session.data.update(awaiting_reboot=True, pending_updates={"updates": [{"subsystem": "services", "toVersion": "99.0.0"}]})
    c.session.save()
    with pytest.raises(setup.SetupError, match="target version"):
        c.run()
    assert ssh.calls == ["inspect"]


def test_cli_and_gui_share_guided_setup(monkeypatch):
    import jibo_tui
    calls = []
    monkeypatch.setattr(setup, "run_guided", lambda api, flows, port: calls.append((api, flows, port)) or {"status": "cancelled"})
    api = object()
    jibo_tui.execute_action(api, "setup-5x1", jibo_tui.Readiness("none", ()))
    assert calls[0] == (api, jibo_tui, None)
    assert "setup-5x1" in [i.key for i in jibo_tui.build_menu_items(jibo_tui.Readiness("none", ()))]


@pytest.mark.parametrize("body,success", [
    (b'{"status":"working"}\n{"status":"finished"}\n', True),
    (b'{"status":"failed","reason":"checksum does not match"}\n', False),
    (b'{"status":"working"}\n', False),
    (b'{"status":"finished","error":"fixture-secret"}\n', False),
])
def test_download_stream_must_finish_without_errors(monkeypatch, body, success):
    class Response:
        def read(self):
            return body
        def close(self):
            pass
    monkeypatch.setattr(robot, "urlopen", lambda *args, **kwargs: Response())
    if success:
        assert robot.ota_download({"ids": ["fixture"]}) == {"downloaded": True}
    else:
        with pytest.raises(robot.RobotError) as error:
            robot.ota_download({"ids": ["fixture"]})
        assert "fixture-secret" not in str(error.value)


def test_provision_network_error_is_sanitized(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("fixture-secret")
    monkeypatch.setattr(setup.urllib.request, "urlopen", fail)
    with pytest.raises(setup.SetupError) as error:
        setup.protocol_request("SetupRobot", {"secret": "fixture-secret"})
    assert "fixture-secret" not in str(error.value)


@pytest.mark.parametrize("accept,known,success", [(True, None, True), (False, None, False), (True, "different", False)])
def test_ssh_fingerprint_requires_acceptance_and_rejects_changes(tmp_path, monkeypatch, accept, known, success):
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
        setup.SSH("fixture-host", "root", "fixture-secret", s, lambda *args: accept)
        assert s.data["fingerprints"]["fixture-host"].startswith("SHA256:")
        assert "fixture-secret" not in s.path.read_text()
    else:
        with pytest.raises(setup.SetupError):
            setup.SSH("fixture-host", "root", "fixture-secret", s, lambda *args: accept)
        assert s.data["fingerprints"].get("fixture-host") == known


@pytest.mark.parametrize("quick", [True, False, "unsupported-layout"])
def test_fresh_setup_runs_usb_to_normal_without_storing_secrets(tmp_path, monkeypatch, quick):
    calls = []
    class LayoutError(Exception):
        status = 3
    class API:
        FileRpcStatusError = LayoutError
        def backup_partitions(self, partitions, **kwargs):
            entries = []
            for name in partitions:
                p = tmp_path / (name + ".img")
                p.write_bytes(b"fixture")
                entries.append({"name": name, "image": str(p), "size_bytes": 7,
                    "sha256": hashlib.sha256(b"fixture").hexdigest()})
            return {"manifest": "fixture-backup-set", "partitions": entries}
        def tool(self, name):
            return name
        def _live_var_file_available(self, *args):
            return quick is not False
        def set_mode_wifi_file_live(self, *args, **kwargs):
            if quick == "unsupported-layout":
                raise LayoutError()
            calls.append("usb")
            if not kwargs["confirmation"]({}):
                return {"status": "cancelled"}
            return {"status": "verified"}
        def set_mode_wifi_live(self, *args, **kwargs):
            calls.append("full-usb")
            return {"status": "verified"} if kwargs["confirmation"]({}) else {"status": "cancelled"}
    monkeypatch.setattr(setup, "read_factory", lambda *args: (IDENTITY, "oobe", {"fixture": "hash"}))
    answers = iter(("network", "wifi-secret", "wifi-secret", "fixture-host", "root", "ssh-secret", "ssh-secret"))
    ssh = FakeSSH(report())
    def download(p):
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("fixture/package.json", "{}")
    c = setup.SetupController(API(), tmp_path / "session.json", lambda *args, **kwargs: next(answers),
        lambda *args: "protected", lambda *args: True, lambda *args: None,
        ssh_factory=lambda *args: ssh, provisioner=lambda *args: KEYS, downloader=download, sleep=lambda *args: None)
    assert c.run()["status"] == "verified"
    assert calls == (["usb"] if quick is True else ["full-usb"])
    assert all(action in ssh.calls for action in ("credentials", "beam", "configure", "ota-check", "firmware", "normal", "reboot", "verify"))
    raw = c.session.path.read_text()
    assert all(secret not in raw for secret in ("wifi-secret", "ssh-secret", "fixture-secret"))


def test_archive_link_cannot_escape_staging_tree(filesystem):
    root, write = filesystem
    archive = root / "opt/tmp/beetle-beam.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as z:
        entry = zipfile.ZipInfo("BEam-" + setup.BEAM_REVISION + "/escape")
        entry.external_attr = 0o120777 << 16
        z.writestr(entry, "../../outside")
    with pytest.raises(robot.RobotError, match="escapes"):
        robot.install_beam({"sha256": setup.file_sha256(archive), "revision": setup.BEAM_REVISION})
