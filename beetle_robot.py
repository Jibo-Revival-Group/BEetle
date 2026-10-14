"""Checked on-robot setup worker; Python 2.7/3 compatible, standard library only.

Read one request from stdin and return one sanitized JSON result. ROOT is only
overridden by fixture tests; deployed requests cannot select a filesystem root.
"""
from __future__ import print_function
import glob
import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen

ROOT = ""
HUB = "api.5x1.com"
OTA = "http://joap.5x1.com:80"
SKILLS = "/opt/jibo/Jibo/Skills"
CALIBRATION = ("CameraModelParamsL.json", "CameraModelParamsR.json", "InterCameraTransform.json")


class RobotError(Exception):
    pass


def path(p):
    return ROOT + p


def read(p):
    with open(path(p), "rb") as stream:
        return stream.read()


def load(p):
    return json.loads(read(p).decode("utf-8"))


def atomic(p, content, mode=None):
    target = path(p)
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        os.makedirs(parent, 0o755)
    if os.path.islink(target):
        raise RobotError("Refusing to replace a symbolic-link configuration file: " + p)
    old = os.stat(target) if os.path.exists(target) else None
    fd, tmp = tempfile.mkstemp(prefix=".beetle-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content if isinstance(content, bytes) else content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, mode if mode is not None else stat.S_IMODE(old.st_mode) if old else 0o644)
        if old and os.geteuid() == 0:
            os.chown(tmp, old.st_uid, old.st_gid)
        os.rename(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(p, value, mode=None):
    atomic(p, json.dumps(value, indent=2) + "\n", mode)


def run(argv, allow_failure=False):
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = child.communicate()
    if child.returncode and not allow_failure:
        # Raw subprocess output can include account information.
        raise RobotError("Robot command failed: " + os.path.basename(argv[0]))
    return out.decode("utf-8", "replace")


def remount():
    if not ROOT:
        run(["jibo-mount", "--rw"])


def validate_credentials(value):
    if not isinstance(value, dict) or not all(isinstance(value.get(k), type(u"")) and value[k].strip()
            for k in ("accessKeyId", "secretAccessKey")):
        raise RobotError("Missing or malformed robot credentials; restore var or provision through BEefy.")
    result = dict(value)
    result.update(region="api", endpoint=OTA)
    return result


def versions():
    result = {}
    if ROOT:
        result["services"] = "fixture"
    else:
        value = run(["jibo-service-version"])
        match = re.search(r"(?:Release-)?(\d+\.\d+\.\d+)", value)
        if not match:
            raise RobotError("Could not read the installed services version.")
        result["services"] = match.group(1)
    for package in glob.glob(path(SKILLS + "/*/package.json")) + glob.glob(path(SKILLS + "/@*/*/package.json")):
        with open(package) as stream:
            value = json.load(stream)
        if value.get("name") and value.get("version"):
            result[value["name"]] = value["version"]
    return result


def inspect():
    value = load("/var/jibo/identity.json")
    keys = ("name", "serial_number", "cpuid", "wifi_mac")
    if not all(value.get(k) for k in keys):
        raise RobotError("Robot factory identity is incomplete.")
    existing = os.path.isfile(path("/var/jibo/credentials.json"))
    if existing:
        validate_credentials(load("/var/jibo/credentials.json"))
    return {"identity": dict((k, value[k]) for k in keys), "mode": load("/var/jibo/mode.json")["mode"],
        "has_credentials": existing, "versions": versions(), "calibration": dict(
        ("/jibo/lps/" + n, hashlib.sha256(read("/var/jibo/lps/" + n)).hexdigest()) for n in CALIBRATION)}


def set_credentials(payload):
    p = "/var/jibo/credentials.json"
    existing = load(p) if os.path.isfile(path(p)) else payload.get("credentials")
    value = validate_credentials(existing)
    remount()
    write_json(p, value, 0o600)
    if load(p) != value:
        raise RobotError("Credential readback failed.")
    return {"endpoint": OTA, "preserved_existing_keys": existing is not payload.get("credentials")}


def migrate_library():
    knowledge = "/opt/jibo/Knowledge"
    music = knowledge + "/jukebox/music"
    eyes = knowledge + "/beacon"
    for p in (music, eyes):
        if not os.path.isdir(path(p)):
            os.makedirs(path(p), 0o777)
    candidates = ("/opt/tmp/jukebox-music", SKILLS + "/@be/be/skills/jukebox/music",
        SKILLS + "/@be/be/node_modules/@be/jukebox/music", SKILLS + "/@be/jukebox/music",
        SKILLS + "/@be/Skills/Jukebox/Music", SKILLS + "/@be/skills/jukebox/music", SKILLS + "/skills/jukebox/music")
    def merge(source, target):
        for directory, dirs, files in os.walk(path(source), followlinks=False):
            for name in files:
                src = os.path.join(directory, name)
                if os.path.islink(src):
                    continue
                dst = os.path.join(path(target), os.path.relpath(src, path(source)))
                if os.path.exists(dst):
                    continue
                if not os.path.isdir(os.path.dirname(dst)):
                    os.makedirs(os.path.dirname(dst), 0o777)
                shutil.copy2(src, dst)
    for candidate in candidates:
        if os.path.isdir(path(candidate)):
            merge(candidate, music)
    if os.path.isdir(path("/opt/tmp/beacon")):
        merge("/opt/tmp/beacon", eyes)


def install_beam(payload):
    archive_path = path("/opt/tmp/beetle-beam.zip")
    digest = hashlib.sha256()
    with open(archive_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != payload.get("sha256"):
        raise RobotError("BEam archive checksum mismatch; no skills were changed.")
    revision = payload.get("revision", "")
    if not re.match(r"^[0-9a-f]{40}$", revision):
        raise RobotError("BEam revision must be pinned.")
    remount()
    parent = path("/opt/jibo/Jibo")
    if not os.path.isdir(parent):
        raise RobotError("Jibo skills parent is missing; install a supported stock image first.")
    temporary = tempfile.mkdtemp(prefix=".beetle-beam-", dir=parent)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            root = None
            links = []
            for info in archive.infolist():
                parts = info.filename.split("/")
                if parts[0] != "BEam-" + revision and parts[0] != "Beam-" + revision:
                    raise RobotError("BEam archive does not match the pinned revision.")
                root = parts[0]
                if any(p in ("..", "") for p in parts[:-1]) or info.filename.startswith("/") or "\\" in info.filename:
                    raise RobotError("Unsafe path in BEam archive.")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    target = archive.read(info).decode("utf-8")
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(info.filename), target))
                    if target.startswith("/") or not resolved.startswith(parts[0] + "/"):
                        raise RobotError("BEam symbolic link escapes the archive.")
                    links.append((info.filename, target))
            # Extract regular members before links so a link cannot redirect writes.
            for info in archive.infolist():
                if not stat.S_ISLNK(info.external_attr >> 16):
                    archive.extract(info, temporary)
                    destination = os.path.join(temporary, info.filename)
                    if os.path.isfile(destination):
                        os.chmod(destination, (info.external_attr >> 16) & 0o777 or 0o644)
            for name, target in links:
                destination = os.path.join(temporary, name)
                if not os.path.isdir(os.path.dirname(destination)):
                    os.makedirs(os.path.dirname(destination))
                os.symlink(target, destination)
        prepared = os.path.join(temporary, root or "missing")
        if not os.path.isfile(os.path.join(prepared, "@be", "be", "package.json")):
            raise RobotError("BEam archive lacks @be/be.")
        migrate_library()
        # Keep unrelated custom skills and a repeatable rollback of overwritten entries.
        rollback = path("/opt/jibo/beetle-skills-before-5x1")
        if not os.path.isdir(rollback):
            os.makedirs(rollback, 0o700)
        if not ROOT:
            run(["curl", "-fsS", "--max-time", "30", "-X", "POST", "http://127.0.0.1:8779/terminate",
                 "-H", "Content-Type: application/x-www-form-urlencoded", "--data-raw", '{"command":"@be/be"}'])
        for name in os.listdir(prepared):
            src = os.path.join(prepared, name)
            if name.startswith(".") or name in ("README.md", "LICENSE", "LICENSE.md") or not os.path.isdir(src):
                continue
            if name.startswith("@"):
                pairs = [(os.path.join(src, child), SKILLS + "/" + name + "/" + child)
                         for child in os.listdir(src) if os.path.isdir(os.path.join(src, child))]
            else:
                pairs = [(src, SKILLS + "/" + name)]
            for source, destination in pairs:
                target = path(destination)
                saved = os.path.join(rollback, destination[len(SKILLS)+1:])
                for folder in (os.path.dirname(target), os.path.dirname(saved)):
                    if not os.path.isdir(folder):
                        os.makedirs(folder, 0o755)
                if os.path.exists(target):
                    if not os.path.exists(saved):
                        os.rename(target, saved)
                    else:
                        shutil.rmtree(target)
                os.rename(source, target)
                for directory, dirs, files in os.walk(target):
                    os.chmod(directory, 0o755)
                    for filename in files:
                        p = os.path.join(directory, filename)
                        if not os.path.islink(p):
                            os.chmod(p, stat.S_IMODE(os.stat(p).st_mode) | 0o444)
        atomic("/var/jibo/beetle-beam-revision", revision + "\n", 0o644)
        os.unlink(archive_path)
        return {"revision": revision, "versions": versions()}
    finally:
        shutil.rmtree(temporary)


def configuration_changes():
    """Prepare every transformation before writing any of them."""
    changes = []
    p = "/usr/local/etc/jibo-jetstream-service.json"
    jetstream = load(p)
    jetstream.setdefault("HubClient", {})["override"] = {
        "hub_port": 443, "hub_hostname": HUB, "entrypoint_hostname": HUB}
    changes.append((p, json.dumps(jetstream, indent=2) + "\n", None))
    changes.append(("/var/jibo/credentials.json", json.dumps(validate_credentials(load("/var/jibo/credentials.json"))) + "\n", 0o600))
    roots = ("/usr/local/bin/jibo-ssm", "/usr/lib/node_modules", SKILLS + "/@be/be", SKILLS + "/oobe-config")
    clients = []
    for root in roots:
        for p in glob.glob(path(root + "/node_modules/@jibo/jibo-server-client/lib/region_config.json")) + glob.glob(path(root + "/@jibo/jibo-server-client/lib/region_config.json")):
            clients.append(p[len(ROOT):] if ROOT else p)
    if not clients:
        raise RobotError("No supported jibo-server-client region configuration found.")
    for p in sorted(set(clients)):
        value = load(p)
        value.setdefault("patterns", {})["globalSSL"] = {"endpoint": "https://" + HUB,
            "wsendpoint": "wss://" + HUB, "globalEndpoint": True}
        changes.append((p, json.dumps(value, indent=2) + "\n", None))
        http = os.path.dirname(p) + "/http/node.js"
        text = read(http).decode("utf-8")
        if "rejectUnauthorized: true" not in text and "rejectUnauthorized: false" not in text:
            raise RobotError("Unknown legacy TLS target: " + http)
        changes.append((http, text.replace("rejectUnauthorized: true", "rejectUnauthorized: false"), None))
    needle = "this._backupHelper((bkError, maxError) => {"
    marker = "this._doLog('Skipping pre-OTA backup');"
    matched = False
    for root in ("/usr/local/bin/jibo-ssm", "/opt/jibo/Jibo/jibo-ssm"):
        for directory, dirs, files in os.walk(path(root)):
            dirs[:] = [d for d in dirs if d != "node_modules"]
            for name in files:
                if not name.endswith(".js"):
                    continue
                disk = os.path.join(directory, name)
                p = disk[len(ROOT):] if ROOT else disk
                text = read(p).decode("utf-8")
                if needle not in text:
                    continue
                matched = True
                if marker not in text:
                    text = text.replace(needle, marker + "\n            return callback();\n            " + needle)
                changes.append((p, text, None))
    if not matched:
        raise RobotError("Unsupported SSM pre-OTA backup layout; no configuration was written.")
    cert = read("/var/tmp/beetle-isrg-root-x1.pem")
    if b"BEGIN CERTIFICATE" not in cert:
        raise RobotError("ISRG Root X1 certificate asset is missing or invalid.")
    changes.append(("/opt/jibo/openjibo-ca.crt", cert, 0o644))
    bundle = read("/etc/ssl/certs/ca-certificates.crt")
    if cert.strip() not in bundle:
        changes.append(("/etc/ssl/certs/ca-certificates.crt", bundle.rstrip() + b"\n" + cert, None))
    return changes


def configure():
    changes = configuration_changes()
    remount()
    for p, value, mode in changes:
        atomic(p, value, mode)
    link = path("/etc/ssl/certs/4042bcee.0")
    if os.path.lexists(link):
        if not os.path.islink(link) or os.readlink(link) != "/opt/jibo/openjibo-ca.crt":
            raise RobotError("Unexpected existing ISRG certificate hash target.")
    else:
        os.symlink("/opt/jibo/openjibo-ca.crt", link)
    # Match BEach's final normal-mode bring-up; partition rollback covers removal.
    firewall = path("/etc/init.d/S21firewall")
    if os.path.isfile(firewall):
        os.unlink(firewall)
    if not ROOT:
        run(["pkill", "-f", "jibo-jetstream-service"], True)
        run(["pkill", "-f", "jibo-ssm"], True)
        time.sleep(15)
    return {"hub": HUB, "ota": OTA, "changed_files": [p for p, value, mode in changes]}


def local_http(p, method="GET", data=None, timeout=120):
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = Request("http://127.0.0.1:8585" + p, data=body, headers={"Content-Type": "application/json"})
    req.get_method = lambda: method
    try:
        response = urlopen(req, timeout=timeout)
        raw = response.read()
        response.close()
        text = raw.decode("utf-8")
        if p == "/update" and method == "PUT" and text.strip():
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
            if any(isinstance(v, dict) and (v.get("error") or v.get("status") in ("Error", "failed")) for v in records):
                raise RobotError("Robot OTA download failed; no apply was requested.")
            value = records[-1]
            if not isinstance(value, dict) or value.get("status") != "finished":
                raise RobotError("Robot OTA download did not finish; no apply was requested.")
        else:
            value = json.loads(text) if text.strip() else {}
        if isinstance(value, dict) and (value.get("error") or value.get("status") in ("Error", "failed")):
            raise RobotError("Robot OTA reported a failure; inspect its local update status.")
        return value
    except RobotError:
        raise
    except Exception:
        raise RobotError("Robot OTA request failed; check Wi-Fi, free space, checksum and update status.")


def ota_check():
    value = local_http("/update/fcs")
    updates = value.get("updates") or []
    required = ("id", "subsystem", "toVersion")
    if any(not all(u.get(k) for k in required) for u in updates):
        raise RobotError("Malformed robot OTA catalog.")
    return {"ids": [u["id"] for u in updates], "updates": [dict((k, u[k]) for k in required) for u in updates]}


def ota_download(payload):
    value = local_http("/update", "PUT", {"ids": payload["ids"]}, timeout=7200)
    # System Manager may stream newline-delimited progress; local_http handles it below.
    return {"downloaded": True}


def verify():
    value = inspect()
    config = load("/usr/local/etc/jibo-jetstream-service.json")["HubClient"]["override"]
    creds = load("/var/jibo/credentials.json")
    if value["mode"] != "normal" or config != {"hub_port": 443, "hub_hostname": HUB, "entrypoint_hostname": HUB} or creds.get("endpoint") != OTA:
        raise RobotError("Normal-mode endpoint verification failed; resume configuration.")
    if "@be/be" not in value["versions"]:
        raise RobotError("BEam is not installed.")
    for p, expected, mode in configuration_changes():
        expected = expected if isinstance(expected, bytes) else expected.encode("utf-8")
        if read(p) != expected:
            raise RobotError("5x1 configuration changed after reboot: " + p)
    if not ROOT:
        processes = run(["ps"])
        if "jibo-ssm" not in processes or "jibo-jetstream" not in processes:
            raise RobotError("Robot services are not running yet; retry verification.")
        # Node follows the same legacy TLS path as the robot client.
        js = "require('https').get({hostname:'api.5x1.com',path:'/health',rejectUnauthorized:false},function(r){var b='';r.on('data',function(d){b+=d});r.on('end',function(){try{process.exit(r.statusCode===200&&JSON.parse(b).ok===true?0:1)}catch(e){process.exit(1)}})}).on('error',function(){process.exit(1)});setTimeout(function(){process.exit(1)},15000);"
        run(["node", "-e", js])
        local_http("/update/fcs")
    value.update(hub=HUB, ota=OTA, services=True, cloud="BEefy health reachable")
    return value


def dispatch(action, payload):
    if action == "inspect":
        return inspect()
    if action == "credentials":
        return set_credentials(payload)
    if action == "stage-archive":
        available = os.statvfs(path("/opt"))
        if available.f_bavail * available.f_frsize < payload["required_bytes"]:
            raise RobotError("Not enough space on /opt for the BEam download and staged extraction.")
        if not os.path.isdir(path("/opt/tmp")):
            os.makedirs(path("/opt/tmp"), 0o755)
        return {"ready": True}
    if action == "beam":
        return install_beam(payload)
    if action == "configure":
        return configure()
    if action == "ota-check":
        return ota_check()
    if action == "ota-download":
        return ota_download(payload)
    if action == "ota-apply":
        return local_http("/update", "POST", {"ids": payload["ids"]})
    if action == "firmware":
        run(["pkill", "-f", "jibo"], True)
        time.sleep(2)
        run(["jibo-bbfw-update"])
        return {"updated": True}
    if action == "normal":
        remount()
        run(["jibo-setmode", "normal"])
        if load("/var/jibo/mode.json")["mode"] != "normal":
            raise RobotError("Normal mode did not persist.")
        return {"mode": "normal"}
    if action == "reboot":
        subprocess.Popen(["sh", "-c", "sleep 2; reboot"], stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)
        return {"rebooting": True}
    if action == "verify":
        return verify()
    raise RobotError("Unknown setup action.")


def main():
    try:
        request = json.loads(sys.stdin.readline())
        result = dispatch(request["action"], request.get("payload", {}))
        print(json.dumps({"ok": True, "result": result}))
        return 0
    except Exception as error:
        message = str(error) if isinstance(error, RobotError) else "Robot setup failed; inspect the backup and resume the current stage."
        print(json.dumps({"ok": False, "error": message}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
