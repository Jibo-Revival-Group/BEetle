"""Exercise the clean docs fixture, including the optional 5x1 setup screens."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("JIBO_GUI_TEST_DISPLAY") != "1",
                                reason="docs captures require Tk and a display")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("setup", [False, True])
def test_docs_fixture_captures_setup_screens(tmp_path, setup):
    args = [sys.executable, str(ROOT / "scripts/docs_screenshots.py"), "--out", str(tmp_path)]
    if setup:
        args.append("--setup")
    run = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=40)
    assert run.returncode == 0, run.stdout + run.stderr
    expected = {"ready.png", "mode-wifi.png", "review.png", "progress.png"}
    if setup:
        expected.update({"setup.png"})
    assert {path.name for path in tmp_path.glob("*.png")} == expected
    assert f"{len(expected)} screens captured at 1080 x 720" in run.stdout


def test_docs_fixture_rejects_visible_fixture_paths_before_capture(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("docs_shots", ROOT / "scripts/docs_screenshots.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.DocsApi, "BACKUP_ROOT", Path("/tmp/forbidden-example"))
    monkeypatch.setattr(sys, "argv", ["docs_screenshots.py", "--setup", "--out", str(tmp_path)])
    with pytest.raises(AssertionError):
        module.main()
    assert not list(tmp_path.glob("*.png"))
