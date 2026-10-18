"""Direct Windows packaging/portability checks; no USB writes or driver installs."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location('native_test_' + name, ROOT / 'scripts/release' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_launches_same_gui_directly_without_system_setup(tmp_path, monkeypatch):
    launcher, manifest = load('windows_launcher'), load('manifest')
    (tmp_path / 'jibo_dfu.py').write_text('# synthetic runtime')
    manifest.write_manifest(tmp_path, 'a' * 40)
    monkeypatch.setattr(launcher, 'runtime_path', lambda: tmp_path)
    monkeypatch.setitem(sys.modules, 'manifest', manifest)
    calls = []
    monkeypatch.setitem(sys.modules, 'native_launcher', SimpleNamespace(main=lambda **args: calls.append(args) or 0))
    assert launcher._main([]) == 0
    assert calls == [{'runtime': tmp_path, 'arguments': ['gui']}]
    (tmp_path / 'jibo_dfu.py').write_text('tampered')
    with pytest.raises(ValueError, match='integrity check'):
        launcher._main([])
    assert len(calls) == 1


def test_windowed_diagnostics_write_receipt_without_powershell(tmp_path, monkeypatch):
    launcher = load('windows_launcher')
    receipt = tmp_path / 'receipt.txt'
    monkeypatch.setattr(launcher.sys, 'argv', ['BEetle.exe','--self-check','--output',str(receipt)])
    def check(args):
        assert args == ['--self-check']
        print('{"platform":"windows-native","virtualization_required":false}')
        return 0
    monkeypatch.setattr(launcher, '_main', check)
    assert launcher.main() == 0
    assert json.loads(receipt.read_text())['virtualization_required'] is False


def test_native_tools_use_exe_names_and_bundled_libusb(tmp_path, monkeypatch):
    launcher = load('native_launcher')
    (tmp_path / 'tools').mkdir()
    env = os.environ.copy()
    try:
        monkeypatch.setattr(launcher.sys, 'platform', 'win32')
        # Real Windows CI executes add_dll_directory with actual DLLs in the artifact.
        monkeypatch.delattr(os, 'add_dll_directory', raising=False)
        monkeypatch.setattr(launcher.subprocess,'CREATE_NO_WINDOW',0,raising=False)
        monkeypatch.setattr(launcher.subprocess,'Popen',launcher.subprocess.Popen)
        launcher.configure(tmp_path)
        assert os.environ['JIBO_DFU_UTIL'].endswith('dfu-util.exe')
        assert os.environ['JIBO_SHOFEL2'].endswith('shofel2_t124.exe')
        assert os.environ['JIBO_LIBUSB'].endswith('libusb-1.0.dll')
        assert os.environ['PATH'].split(os.pathsep)[0] == str(tmp_path / 'tools')
    finally:
        os.environ.clear();os.environ.update(env)


def test_windows_uses_libusb_device_enumeration_instead_of_sysfs(monkeypatch):
    import jibo_dfu
    expected = [{'port':'1-2','state':'rcm'}]
    with patch.object(jibo_dfu.sys,'platform','win32'), patch.object(jibo_dfu.bounded,'list_recovery_devices',return_value=expected):
        assert jibo_dfu.devices() == expected


def test_tools_resolve_windows_exe_suffix(tmp_path):
    import jibo_dfu
    (tmp_path / 'tools').mkdir()
    executable = tmp_path / 'tools/dfu-util.exe'
    executable.write_bytes(b'fixture')
    with patch.object(jibo_dfu,'ROOT',tmp_path), patch.object(jibo_dfu.sys,'platform','win32'), patch.dict(os.environ,{},clear=True):
        assert Path(jibo_dfu.tool('dfu-util')) == executable


def test_debugfs_quotes_windows_drive_spaces_and_unicode():
    import jibo_images
    with patch.object(jibo_images.os,'name','nt'):
        assert jibo_images._debugfs_path('C:\\Users\\Test Name é\\replacement') == '"C:/Users/Test Name é/replacement"'
    with pytest.raises(jibo_images.ImageError):
        jibo_images._debugfs_path('bad\npath')


def test_dll_closure_copies_transitive_imports_and_rejects_missing(tmp_path):
    builder = load('windows_native_build')
    tools, libraries = tmp_path / 'tools', tmp_path / 'libs'
    tools.mkdir();libraries.mkdir()
    (tools / 'helper.exe').write_bytes(b'fixture')
    for name in ('cygwin1.dll','extra.dll'):
        (libraries / name).write_bytes(b'fixture')
    imports = {'helper.exe':['cygwin1.dll'],'cygwin1.dll':['extra.dll'],'extra.dll':[]}
    copied = builder.copy_dll_closure(tools,[libraries],lambda file: imports[file.name])
    assert set(copied) == {'cygwin1.dll','extra.dll'}
    with pytest.raises(RuntimeError,match='Unbundled Windows DLL'):
        builder.copy_dll_closure(tools,[libraries],lambda _: ['nonexistent.dll'])


def test_runtime_source_parser_matches_current_and_previous_installed_versions():
    builder = load('windows_native_build')
    text = '\n@ cygwin\nversion: 3.6.11-1\nsource: src/new.tar.xz 123 ' + 'a'*128 + '\n[prev]\nversion: 3.6.10-1\nsource: src/old.tar.xz 111 ' + 'b'*128 + '\n'
    parsed = builder.parse_cygwin_sources(text)
    assert parsed['cygwin-3.6.11-1'][0] == 'src/new.tar.xz'
    assert parsed['cygwin-3.6.10-1'][0] == 'src/old.tar.xz'


def test_driver_help_does_not_launch_or_elevate_without_explicit_choice(tmp_path, monkeypatch):
    import jibo_windows
    messagebox = SimpleNamespace(askyesno=lambda *a,**kw:False, showwarning=lambda *a,**kw:None, showerror=lambda *a,**kw:None)
    monkeypatch.setitem(sys.modules,'tkinter',SimpleNamespace(messagebox=messagebox))
    (tmp_path / 'tools').mkdir();(tmp_path / 'tools/zadig.exe').write_bytes(b'fixture')
    called = []
    monkeypatch.setattr(messagebox,'askyesno',lambda *a,**kw:False)
    monkeypatch.setattr(os,'startfile',lambda *a,**kw:called.append((a,kw)),raising=False)
    jibo_windows.show_driver_help(tmp_path)
    assert called == []
    monkeypatch.setattr(messagebox,'showwarning',lambda *a,**kw:called.append('busy'))
    jibo_windows.show_driver_help(tmp_path,busy=True)
    assert called == ['busy']


def test_direct_launchers_and_workflow_have_no_wsl_requirements():
    for name in ('run.ps1','scripts/release/windows_launcher.py','.github/workflows/windows-native.yml'):
        source = (ROOT / name).read_text()
        assert 'wsl.exe' not in source
        assert 'Enable-WindowsOptionalFeature' not in source
        assert 'usbipd' not in source
    workflow = (ROOT / '.github/workflows/release.yml').read_text().split('  windows:\n',1)[1].split('  macos:\n',1)[0]
    assert 'needs: linux' not in workflow and '--windows-native' in workflow


def test_filesystem_smoke_uses_disposable_images_with_spaces_and_unicode(tmp_path, monkeypatch):
    smoke = load('windows_filesystem_smoke')
    tools = tmp_path / 'tools';tools.mkdir()
    names = ('mke2fs','debugfs','e2fsck','resize2fs')
    system = Path('/run/host/usr/bin')
    if os.name == 'nt':
        pytest.skip('Real Windows artifact runs --filesystem-smoke after freezing')
    for name in names:
        path = shutil.which(name) or str(system / name)
        if not Path(path).is_file():pytest.skip('native e2fsprogs required')
        (tools / name).symlink_to(path)
    monkeypatch.setenv('PATH',str(tools)+os.pathsep+os.environ['PATH'])
    smoke.filesystem_smoke(tmp_path)
