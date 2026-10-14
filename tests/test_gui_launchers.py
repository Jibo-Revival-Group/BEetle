"""Launcher checks using command stubs, never sudo/package installs/USB/network."""
import configparser
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch
import zipfile

import pytest
import jibo_dfu
import scripts.check_package as checker
import test_run_sh as linux_tests
import test_macos as mac_tests
import test_package as package_tests

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def linux():
    fixture = linux_tests.RunLauncherTests()
    fixture.setUp()
    fixture.pyz.write_text("fake cached package")
    yield fixture
    fixture.doCleanups()


@pytest.fixture
def mac():
    fixture = mac_tests.MacLauncherTests()
    fixture.setUp()
    yield fixture
    fixture.doCleanups()


def test_linux_gui_flag_selects_gui_not_default_text_menu(linux):
    result = subprocess.run([linux_tests.BASH, str(linux.repo / "run.sh"), "--gui"],
                            env=linux.env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    events = linux.events()
    line = events[linux.launch_index(events)]
    assert line.endswith(".pyz gui"), events


def test_linux_missing_tk_attempts_supported_package_then_explains_fallback(linux):
    result = subprocess.run([linux_tests.BASH, str(linux.repo / "run.sh"), "--gui"],
                            env={**linux.env, "JIBO_TEST_TK_MISSING": "1"},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert any(e == "apt-get install -y python3-tk" for e in linux.events())
    assert "Tk is unavailable" in result.stdout


def test_linux_gui_sudo_preserves_only_display_environment(linux):
    result = subprocess.run([linux_tests.BASH, str(linux.repo / "run.sh"), "--gui"],
                            env={**linux.env, "DISPLAY": ":42", "XAUTHORITY": "/tmp/fake-xauth"},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    if os.geteuid() != 0:
        assert any(e.startswith("sudo --preserve-env=DISPLAY,XAUTHORITY,WAYLAND_DISPLAY,XDG_RUNTIME_DIR python3 ")
                   for e in linux.events())


def test_mac_gui_flag_routes_to_native_source(mac):
    result = mac.launch("--gui")
    assert result.returncode == 0, result.stderr
    assert mac.trace.read_text().splitlines()[-1] == "gui"


def test_mac_missing_tk_hint_uses_selected_python_version(mac):
    mac.stub("python3", '''#!/bin/sh
if [ "$1" = -c ]; then
  if [ "$2" = 'import tkinter' ]; then exit 1; fi
  case "$2" in *sys.version_info*) printf '3.12\\n';; esac
  exit 0
fi
printf '%s\\n' "$@" >> "$JIBO_TEST_TRACE"
''')
    result = mac.launch("--gui")
    assert result.returncode == 0, result.stderr
    assert "brew install python-tk@3.12" in result.stderr
    assert mac.trace.read_text().splitlines()[-1] == "gui"


def test_gui_and_default_tui_cli_dispatch_remain_separate():
    with patch.object(jibo_dfu, "_launch_gui", return_value=13) as gui, \
            patch.object(jibo_dfu, "_launch_menu", return_value=17) as tui:
        assert jibo_dfu.main(["gui"]) == 13
        assert jibo_dfu.main(["--gui"]) == 13
        assert jibo_dfu.main([]) == 17
        assert gui.call_count == 2 and tui.call_count == 1


def test_double_click_shell_wrapper_uses_own_folder_with_spaces(tmp_path):
    repo = tmp_path / "repository with spaces"
    repo.mkdir()
    shutil.copy2(ROOT / "run-gui.sh", repo / "run-gui.sh")
    trace = tmp_path / "trace"
    (repo / "run.sh").write_text('#!/bin/bash\nprintf "%s\\n" "$PWD" "$@" > "$JIBO_TEST_TRACE"\n')
    (repo / "run.sh").chmod(0o755)
    result = subprocess.run(["/bin/bash", str(repo / "run-gui.sh")], cwd=tmp_path,
                            env={**os.environ, "JIBO_TEST_TRACE": str(trace)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert trace.read_text().splitlines() == [str(repo), "--gui"]


def test_desktop_launcher_is_valid_and_passes_its_path_as_argument():
    file = ROOT / "BEetle.desktop"
    if shutil.which("desktop-file-validate"):
        result = subprocess.run(["desktop-file-validate", str(file)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    config = configparser.ConfigParser(interpolation=None)
    config.read(file)
    entry = config["Desktop Entry"]
    assert entry["Terminal"] == "true"
    assert "%k" in entry["Exec"] and "$1" in entry["Exec"]
    assert "run-gui.sh" in entry["Exec"]


def test_desktop_exec_runs_through_real_gio_parser_with_spaces(tmp_path):
    pytest.importorskip("gi")
    Gio = pytest.importorskip("gi.repository.Gio", reason="GObject introspection is unavailable")
    repo = tmp_path / "folder with spaces"
    repo.mkdir()
    desktop = repo / "BEetle.desktop"
    # Only disable Terminal in this throwaway copy; execute the real Exec parser.
    desktop.write_text((ROOT / desktop.name).read_text().replace("Terminal=true", "Terminal=false"))
    trace = repo / "trace"
    (repo / "run-gui.sh").write_text('#!/bin/bash\nprintf "%s" "$PWD" > trace\n')
    info = Gio.DesktopAppInfo.new_from_filename(str(desktop))
    assert info is not None and info.launch([], None)
    import time
    deadline = time.monotonic() + 3
    while not trace.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert trace.read_text() == str(repo)


def test_windows_wrapper_preserves_wsl_helper_and_explicit_gui_switch():
    launcher = (ROOT / "run.ps1").read_text()
    wrapper = (ROOT / "run-gui.cmd").read_text()
    assert "[switch]$Gui" in launcher
    assert "$toolkitArguments = @()" in launcher
    assert "if ($Gui) { $toolkitArguments += '--gui' }" in launcher
    assert "bash ./run.sh @toolkitArguments" in launcher
    assert "-UsbOnly -MonitorUsb" in launcher
    assert "-Gui" in wrapper and '"%~dp0run.ps1"' in wrapper and "%*" in wrapper


def test_mac_double_click_command_calls_shell_wrapper():
    command = (ROOT / "BEetle.command").read_text()
    assert "run-gui.sh" in command
    assert '"$repo_dir/run-gui.sh"' in command
    assert (ROOT / "BEetle.command").stat().st_mode & 0o111


def test_package_contains_gui_and_rejects_stale_view():
    fixture = package_tests.PackageTests()
    fixture.setUp()
    try:
        fixture.run_package()
        with zipfile.ZipFile(fixture.output) as archive:
            assert archive.read("jibo_gui.py") == (ROOT / "jibo_gui.py").read_bytes()
            assert archive.read("jibo_gui_core.py") == (ROOT / "jibo_gui_core.py").read_bytes()
        assert {"jibo_gui.py", "jibo_gui_core.py"} <= set(checker.SOURCES)
        source = fixture.root / "source"
        for name in (*checker.SOURCES, "patches/shofel2-dfu-entry.patch"):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)
        with patch.object(checker, "PINNED_LOADER_SIZE", len(fixture.padded_loader)), \
                patch.object(checker, "PINNED_LOADER_SHA256", hashlib.sha256(fixture.padded_loader).hexdigest()):
            assert checker.check_package(fixture.output, source) == (True, "ready")
            (source / "jibo_gui.py").write_text("changed GUI view")
            ready, reason = checker.check_package(fixture.output, source)
            assert not ready and "jibo_gui.py has changed" in reason
    finally:
        fixture.doCleanups()
