"""Fake device boundary shared by headless and real-Tk tests; never touches USB."""
from pathlib import Path
from types import SimpleNamespace


class FileLayoutError(Exception):
    def __init__(self, status=3):
        self.status = status
        super().__init__("Fake unsupported file layout" if status == 3 else "Fake dirty journal")


class FakeApi:
    MARKER = "jibo-dfu-v1"
    BACKUP_ROOT = Path("/tmp/fake-jibo-backups")
    FileRpcStatusError = FileLayoutError

    def __init__(self, state="dfu", quick=True):
        self.state = state
        self.alts = [self.MARKER, "var", "rootfsA", "rootfsB", "services", "skills", "emmc-000"]
        if quick:
            self.alts += ["jibo-file-v1", "jibo-file-var-in", "jibo-file-var-out"]
        self.packages = [Path("updates/official-test.tar.bz2")]
        self.calls = []
        self.writes = []
        self.fail = None
        self.images = SimpleNamespace(inspect_var=self.inspect_var, edit_mode=self.edit_mode,
                                      edit_wifi=self.edit_wifi)
        self.plan = {"operation": "fake var transaction", "usb_port": "1-1", "partition": "var",
                     "size_bytes": 524288000, "before_sha256": "a" * 64,
                     "candidate_sha256": "b" * 64, "baseline_backup": "/tmp/fake-jibo-backups/var.img",
                     "baseline_sha256": "a" * 64}

    def devices(self):
        if self.state == "multiple":
            return [{"port": "1-1", "state": "dfu"}, {"port": "1-2", "state": "rcm"}]
        return [] if self.state == "none" else [{"port": "1-1", "state": self.state}]

    def tool(self, name):
        return "fake-" + name

    def dfu_alternatives(self, *args):
        return self.alts, ""

    def shofel_dfu_available(self):
        return True

    def _update_candidates(self, folder):
        return self.packages

    def _default_edit_path(self, source):
        return str(Path(source).with_name("edited-var.img"))

    def _edit(self, name, args, kwargs):
        self.calls.append((name, args, {k: v for k, v in kwargs.items() if k != "confirmation"}))
        if self.fail:
            raise self.fail
        assert callable(kwargs.get("confirmation")), "GUI must pass a review callback, not True/--yes"
        plan = dict(self.plan)
        if name.endswith("file_live"):
            plan = {"usb_port": "1-1", "changes": [
                {"partition": "var", "path": "/jibo/mode.json", "description": "Fake file change",
                 "before_size_bytes": 17, "candidate_size_bytes": 26}]}
        elif name == "flash_update":
            plan = {"package": str(args[0]), "version": "13.0.0", "usb_port": "1-1",
                    "var_policy": "preserve current configuration" if kwargs["preserve_var"] else "fresh setup",
                    "rollback_backup": "var only; other partitions are restored from the package",
                    "partitions": [{"name": n, "bytes": 524288000} for n in ("rootfsA", "rootfsB", "services", "skills")]}
        elif name == "restore_partitions":
            plan = {"operation": "restore selected partitions", "usb_port": "1-1",
                    "source_manifest": str(args[0]), "partitions": [{"name": n, "bytes": 524288000} for n in args[1]]}
        if not kwargs["confirmation"](plan):
            return {"status": "cancelled", "message": "No fake write was made."}
        self.writes.append(name)
        result = {"status": "verified", "operation_directory": "/tmp/fake-operation"}
        if "mode" in name:
            result["mode"] = args[0]
        if "wifi" in name:
            result["ssid"] = args[1] if name.startswith("set_mode") else args[0]
        if name == "restore_partitions":
            result.update(partitions=list(args[1]), manifest="/tmp/fake-restore.json")
        return result

    def set_mode_file_live(self, *args, **kwargs):
        return self._edit("set_mode_file_live", args, kwargs)

    def set_mode_live(self, *args, **kwargs):
        return self._edit("set_mode_live", args, kwargs)

    def configure_wifi_file_live(self, *args, **kwargs):
        # Deliberately do not retain passwords in the fake's records.
        return self._edit("configure_wifi_file_live", (args[0], None, args[2]), kwargs)

    def configure_wifi_live(self, *args, **kwargs):
        return self._edit("configure_wifi_live", (args[0], None, args[2]), kwargs)

    def set_mode_wifi_file_live(self, *args, **kwargs):
        return self._edit("set_mode_wifi_file_live", (args[0], args[1], None, args[3]), kwargs)

    def set_mode_wifi_live(self, *args, **kwargs):
        return self._edit("set_mode_wifi_live", (args[0], args[1], None, args[3]), kwargs)

    def boot_network_status_live(self, *args, **kwargs):
        return self._edit("boot_network_status_live", args, kwargs)

    def flash_update(self, *args, **kwargs):
        return self._edit("flash_update", args, kwargs)

    def restore_partitions(self, *args, **kwargs):
        return self._edit("restore_partitions", args, kwargs)

    def write_var(self, *args, **kwargs):
        return self._edit("write_var", args, kwargs)

    def enter_shofel_dfu(self, **kwargs):
        assert kwargs == {"port": "1-1", "confirm_meerkat_rev02": True}
        self.calls.append(("enter_shofel_dfu", (), kwargs))
        self.state = "dfu"
        return {"state": "dfu"}

    def backup_var(self, **kwargs):
        self.calls.append(("backup_var", (), kwargs))
        if self.fail:
            raise self.fail
        return {"status": "backup complete", "image": "/tmp/fake-jibo-backups/var.img"}

    def available_backup_partitions(self, **kwargs):
        return "1-1", "fake-identity", {n: {"size_bytes": 524288000} for n in ("var", "services")}

    def backup_partitions(self, selected, **kwargs):
        self.calls.append(("backup_partitions", (selected,), kwargs))
        return {"status": "backup complete", "partitions": list(selected), "manifest": "/tmp/fake-set.json"}

    def probe_dfu_gpt(self, **kwargs):
        self.calls.append(("probe_dfu_gpt", (), kwargs))
        return {"partition_sizes_bytes": {"var": 524288000}}

    def inspect_var(self, source):
        self.calls.append(("inspect_var", (source,), {}))
        return {"mode": "developer", "wifi_configured": True, "wifi_network_count": 1}

    def edit_mode(self, *args):
        self.calls.append(("edit_mode", args, {}))
        return {"image": args[1]}

    def edit_wifi(self, *args):
        self.calls.append(("edit_wifi", args[:3], {}))
        return {"image": args[1]}
