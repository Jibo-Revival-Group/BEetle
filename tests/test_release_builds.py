"""Release-only adapters must leave the source launchers and safety flows alone."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import os
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / 'scripts/release' / (name + '.py')
    assert path.is_file(), 'missing release adapter: ' + name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_native_pipeline_dispatch_only_accepts_embedded_helper(tmp_path):
    module = load_script('native_launcher')
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    helper = runtime / 'jibo_dfu_pipeline.py'
    helper.write_text('')
    assert module.is_pipeline_request([str(helper), '--help'], runtime)
    assert not module.is_pipeline_request(['/tmp/jibo_dfu_pipeline.py'], runtime)
    assert not module.is_pipeline_request(['gui'], runtime)


def test_payload_manifest_detects_corruption(tmp_path):
    module = load_script('manifest')
    (tmp_path / 'tools').mkdir()
    tool = tmp_path / 'tools/dfu-util'
    tool.write_bytes(b'original')
    module.write_manifest(tmp_path, 'test-revision')
    assert module.verify_manifest(tmp_path)['revision'] == 'test-revision'
    tool.write_bytes(b'tampered')
    import pytest
    with pytest.raises(ValueError, match='dfu-util'):
        module.verify_manifest(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="Unix helper semantics tested in Linux CI")
def test_manifest_covers_symlinked_pyinstaller_resource_directories(tmp_path):
    module = load_script('manifest')
    real = tmp_path / 'resources'
    real.mkdir()
    (real / 'helper').write_bytes(b'original')
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    (runtime / 'tools').symlink_to(real, target_is_directory=True)
    module.write_manifest(runtime, 'revision')
    receipt = module.verify_manifest(runtime)
    assert 'tools/helper' in receipt['files']


def test_manifest_can_explicitly_exclude_macho_relocation_outputs(tmp_path):
    module = load_script('manifest')
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools/helper').write_bytes(b'before Mach-O relocation')
    (tmp_path / 'source.py').write_text('unchanged source')
    module.write_manifest(tmp_path, 'revision', exclude=('tools/helper',))
    (tmp_path / 'tools/helper').write_bytes(b'after Mach-O relocation')
    receipt = module.verify_manifest(tmp_path)
    assert receipt['excluded_native_files'] == ['tools/helper']
    assert 'source.py' in receipt['files']
    (tmp_path / 'source.py').write_text('corrupt')
    import pytest
    with pytest.raises(ValueError, match='source.py'):
        module.verify_manifest(tmp_path)


def test_ext4_build_never_installs_host_services():
    module = load_script('build')
    assert hasattr(module, 'configure_flags'), 'missing isolated dependency configuration'
    flags = module.configure_flags('e2fsprogs-1.47.1.tar.gz', Path('/tmp/prefix'))
    assert '--without-udev-rules-dir' in flags
    assert '--without-systemd-unit-dir' in flags
    assert '--without-crond-dir' in flags


@pytest.mark.skipif(os.name == "nt", reason="Unix helper semantics tested in Linux CI")
def test_release_entry_build_omits_unrelated_arm_examples(tmp_path):
    module = load_script('build')
    assert hasattr(module, 'entry_build_env'), 'missing minimal entry build environment'
    makefile = tmp_path / 'Makefile'
    makefile.write_text('BIN_FILES=emmc_server.bin reset_example.bin\nall:\n\t@printf "%s\\n" "$(BIN_FILES)"\n')
    result = subprocess.run(['make', '-f', str(makefile)], env=module.entry_build_env(tmp_path),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'intermezzo.bin dfu_stage2.bin'


def test_macho_audit_rejects_build_machine_libraries():
    module = load_script('build')
    assert hasattr(module, 'external_macho_dependencies'), 'missing Mach-O dependency audit'
    output = 'tool:\n\t@loader_path/libusb.dylib (compatibility version 1.0.0)\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n\t/opt/homebrew/opt/libusb/lib/libusb.dylib (compatibility version 1.0.0)\n'
    assert module.external_macho_dependencies(output) == ['/opt/homebrew/opt/libusb/lib/libusb.dylib']


def test_installed_formula_source_pin_is_preserved():
    module = load_script('build')
    assert hasattr(module, 'formula_source_pin'), 'missing installed-formula source lookup'
    text = 'url "https://example.invalid/component-1.2.tar.xz"\nsha256 "' + 'a' * 64 + '"\n'
    assert module.formula_source_pin(text) == ('https://example.invalid/component-1.2.tar.xz', 'a' * 64)
    import pytest
    with pytest.raises(ValueError, match='source pin'):
        module.formula_source_pin('no url or hash')


def test_source_notices_handle_raw_and_zip_downloads(tmp_path):
    module = load_script('build')
    assert hasattr(module, 'source_notice_contents'), 'missing source-format handling'
    raw = tmp_path / 'cacert.pem'
    raw.write_text('public certificate source fixture')
    assert module.source_notice_contents(raw) == []
    import zipfile
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('component/LICENSE', 'terms fixture')
        stream.writestr('component/source.c', 'source fixture')
    assert module.source_notice_contents(archive) == [('component/LICENSE', b'terms fixture')]


def test_notice_paths_do_not_create_fake_mac_bundles():
    module = load_script('build')
    assert hasattr(module, 'notice_path'), 'missing data-only notice path mapping'
    original = Path('Frameworks/Python.framework/Versions/3.12/LICENSE.txt')
    assert module.notice_path(original) == Path('Frameworks/Python_framework/Versions/3.12/LICENSE.txt')
    assert module.notice_path(Path('docs/example.app/LICENSE')) == Path('docs/example_app/LICENSE')
    assert module.notice_path(Path('COPYING')) == Path('COPYING')


def test_windows_payload_checksum_refuses_corruption(tmp_path, monkeypatch):
    module = load_script('windows_launcher')
    (tmp_path / 'payload.tar.gz').write_bytes(b'corrupt')
    (tmp_path / 'payload.sha256').write_text('0' * 64)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(sys, 'argv', ['bootstrap', '--self-check'])
    import pytest
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        module.main()


@pytest.mark.skipif(os.name == "nt", reason="Unix helper semantics tested in Linux CI")
def test_apprun_diagnostics_do_not_request_administrator(tmp_path):
    import shutil
    shutil.copy2(ROOT / 'scripts/release/AppRun', tmp_path / 'AppRun')
    native = tmp_path / 'jibo-dfu'
    native.write_text('#!/bin/sh\nprintf "native:%s\\n" "$1"\n')
    native.chmod(0o755)
    for flag in ('--version', '--self-check', '--gui-smoke'):
        result = subprocess.run(['bash', str(tmp_path / 'AppRun'), flag], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == 'native:' + flag
        assert 'administrator' not in result.stdout


def test_download_rejects_wrong_source_hash(tmp_path):
    module = load_script('build')
    original = tmp_path / 'source'
    original.write_bytes(b'source fixture')
    import pytest
    with pytest.raises(RuntimeError, match='hash mismatch'):
        module.download(original.as_uri(), tmp_path / 'download', '0' * 64)
    assert not (tmp_path / 'download').exists()


@pytest.mark.skipif(os.name == "nt", reason="Unix helper semantics tested in Linux CI")
def test_windows_usb_permission_helper_only_grants_jibo_nodes(tmp_path):
    script = ROOT / 'scripts/release/wsl-usb-permissions.sh'
    assert script.is_file(), 'missing password-free WSL USB permission helper'
    sysfs = tmp_path / 'sys'
    devfs = tmp_path / 'dev'
    sysfs.mkdir()
    devfs.mkdir()
    for name, vendor, product, bus, device in (
        ('apx', '0955', '7740', '1', '2'),
        ('dfu', '0955', '701a', '1', '3'),
        ('other-product', '0955', '9999', '1', '4'),
        ('other-vendor', '1234', '701a', '1', '5'),
        ('invalid-bus', '0955', '701a', '../../etc', '6'),
    ):
        entry = sysfs / name
        entry.mkdir()
        for field, value in (('idVendor', vendor), ('idProduct', product),
                             ('busnum', bus), ('devnum', device)):
            (entry / field).write_text(value + '\n')
    (devfs / '001').mkdir()
    for number in ('002', '003', '004', '005'):
        (devfs / '001' / number).write_text('synthetic USB node')
    # Model the character-device boundary; chmod/chown are recorded, not executed.
    probe = r'''
source "$1"
test() { if [[ $1 == -c ]]; then [[ -f $2 ]]; else builtin test "$@"; fi; }
chown() { printf 'chown'; printf ' <%s>' "$@"; printf '\n'; }
chmod() { printf 'chmod'; printf ' <%s>' "$@"; printf '\n'; }
grant_jibo_usb "$2" "$3" 1000 1001
'''
    result = subprocess.run(['bash', '-c', probe, 'probe', str(script), str(sysfs), str(devfs)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f'chown <1000:1001> <--no-dereference> <--> <{devfs}/001/002>',
        f'chmod <0600> <--> <{devfs}/001/002>',
        f'chown <1000:1001> <--no-dereference> <--> <{devfs}/001/003>',
        f'chmod <0600> <--> <{devfs}/001/003>',
    ]
    # Hotplug adds DFU and removes APX; the same grant pass must rediscover nodes.
    (devfs / '001/002').unlink()
    result = subprocess.run(['bash', '-c', probe, 'probe', str(script), str(sysfs), str(devfs)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '002' not in result.stdout and '003' in result.stdout
    # Never follow a user/device-path symlink to a different host file.
    (devfs / '001/003').unlink()
    (devfs / '001/003').symlink_to(devfs / '001/004')
    result = subprocess.run(['bash', '-c', probe, 'probe', str(script), str(sysfs), str(devfs)],
                            capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout == '', result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Unix helper semantics tested in Linux CI")
def test_windows_user_wrapper_keeps_uid_home_and_cleans_session(tmp_path):
    import os
    import pytest
    if os.geteuid() == 0:
        pytest.skip('requires the non-root invoking user')
    wrapper = ROOT / 'scripts/release/wsl-user-launch.sh'
    assert wrapper.is_file(), 'missing non-root WSL GUI wrapper'
    native = tmp_path / 'jibo-dfu'
    native.write_text('#!/bin/bash\nprintf "uid:%s home:%s session:%s\\n" "$EUID" "$HOME" "$(<"$SESSION")"\nexit 41\n')
    native.chmod(0o755)
    session = tmp_path / 'session'
    home = tmp_path / 'normal-home'
    env = os.environ.copy()
    env.update(HOME=str(home), SESSION=str(session))
    result = subprocess.run(['bash', str(wrapper), str(native), str(session)],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 41, result.stderr
    assert f'uid:{os.geteuid()} home:{home} session:' in result.stdout
    assert not session.exists(), 'GUI exit must remove the watcher session'


@pytest.mark.skipif(os.name == "nt", reason="Unix helper semantics tested in Linux CI")
def test_windows_usb_session_checks_process_uid_and_liveness(tmp_path):
    import os
    helper = ROOT / 'scripts/release/wsl-usb-permissions.sh'
    session = tmp_path / 'session'
    probe = r'''
source "$1"
printf '%s\n' "$$" > "$2"
usb_session_alive "$2" "$3" || exit 11
usb_session_alive "$2" 999999 && exit 12
printf '0\n' > "$2"
usb_session_alive "$2" "$3" && exit 13
printf 'invalid\n' > "$2"
usb_session_alive "$2" "$3" && exit 14
rm "$2"
usb_session_alive "$2" "$3" && exit 15
exit 0
'''
    result = subprocess.run(['bash', '-c', probe, 'probe', str(helper), str(session), str(os.geteuid())],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Unix helper semantics tested in Linux CI")
def test_windows_usb_grant_failure_is_not_reported_as_success(tmp_path):
    script = ROOT / 'scripts/release/wsl-usb-permissions.sh'
    entry = tmp_path / 'sys/apx'
    entry.mkdir(parents=True)
    for field, value in (('idVendor', '0955'), ('idProduct', '7740'), ('busnum', '1'), ('devnum', '2')):
        (entry / field).write_text(value + '\n')
    node = tmp_path / 'dev/001/002'
    node.parent.mkdir(parents=True)
    node.write_text('synthetic USB node')
    probe = r'''
source "$1"
test() { if [[ $1 == -c ]]; then [[ -f $2 ]]; else builtin test "$@"; fi; }
chown() { return 5; }
grant_jibo_usb "$2" "$3" 1000 1001
'''
    result = subprocess.run(['bash', '-c', probe, 'probe', str(script), str(tmp_path / 'sys'), str(tmp_path / 'dev')],
                            capture_output=True, text=True)
    assert result.returncode != 0, 'live-node permission failure was silently swallowed'
    assert 'Could not grant Jibo USB access' in result.stderr


def test_native_version_needs_no_desktop_or_tools():
    path = ROOT / 'scripts/release/native_launcher.py'
    assert path.is_file(), 'missing native launcher'
    result = subprocess.run([sys.executable, str(path), '--version'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'BEetle' in result.stdout



def test_offline_manifest_verifies_all_components_and_rejects_tampering(tmp_path):
    import hashlib
    import json
    module = load_script('windows_launcher')
    files = {}
    for name in ('ubuntu.wsl', 'wsl.msi', 'usbipd.msi'):
        (tmp_path / name).write_bytes(name.encode())
        files[name] = {'bytes': len(name), 'sha256': hashlib.sha256(name.encode()).hexdigest()}
    (tmp_path / 'offline-manifest.json').write_text(json.dumps({'schema': 1, 'files': files}))
    assert module.verify_offline_dependencies(tmp_path)['files'] == files
    (tmp_path / 'usbipd.msi').write_bytes(b'x' * len('usbipd.msi'))
    with pytest.raises(RuntimeError, match='checksum mismatch: usbipd.msi'):
        module.verify_offline_dependencies(tmp_path)
    (tmp_path / 'usbipd.msi').unlink()
    with pytest.raises(RuntimeError, match='size mismatch: usbipd.msi'):
        module.verify_offline_dependencies(tmp_path)


def test_offline_manifest_requires_all_three_dependencies(tmp_path):
    import json
    module = load_script('windows_launcher')
    (tmp_path / 'offline-manifest.json').write_text(json.dumps({'schema': 1, 'files': {}}))
    with pytest.raises(RuntimeError, match='incomplete'):
        module.verify_offline_dependencies(tmp_path)


def test_build_downloads_offline_components_once_and_checks_cached_files(tmp_path, monkeypatch):
    import hashlib
    import json
    module = load_script('build')
    pins = {name: ('https://example.invalid/' + name, hashlib.sha256(name.encode()).hexdigest())
            for name in ('ubuntu.wsl', 'wsl.msi', 'usbipd.msi')}
    monkeypatch.setattr(module, 'OFFLINE_WINDOWS', pins)
    calls = []
    def download(url, path, expected):
        calls.append(url)
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(module, 'download', download)
    module.prepare_offline_windows(tmp_path)
    assert len(calls) == 3
    manifest = json.loads((tmp_path / 'offline-manifest.json').read_text())
    assert set(manifest['files']) == set(pins)
    module.prepare_offline_windows(tmp_path)
    assert len(calls) == 3
    (tmp_path / 'wsl.msi').write_bytes(b'tampered')
    with pytest.raises(RuntimeError, match='checksum mismatch: wsl.msi'):
        module.prepare_offline_windows(tmp_path)


def test_windows_build_embeds_dependencies_and_keeps_windows_checks(tmp_path, monkeypatch):
    import struct
    from PIL import Image
    module = load_script('build')
    payload = tmp_path / 'payload'
    payload.mkdir()
    (payload / 'payload.tar.gz').write_bytes(b'fixture')
    (payload / 'revision.txt').write_text('a' * 40)
    (payload / 'BEetle-corresponding-source.tar.gz').write_bytes(b'fixture')
    for name in ('LICENSE', 'NOTICE.md', 'THIRD-PARTY-NOTICES.md'):
        (tmp_path / name).write_text('fixture')
    (tmp_path / 'assets/5x1').mkdir(parents=True)
    Image.new('RGBA', (256, 256), 'green').save(tmp_path / 'assets/5x1/logo.png')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'windows_sources', lambda *args: None)
    prepared = []
    monkeypatch.setattr(module, 'prepare_offline_windows', lambda path: prepared.append(path))
    monkeypatch.setattr(module, 'download', lambda *args: None)
    calls = []
    def run(*args, **kwargs):
        calls.append(list(map(str, args)))
        if 'PyInstaller' in args:
            raw = bytearray(256)
            raw[:2] = b'MZ'
            struct.pack_into('<I', raw, 0x3c, 64)
            raw[64:68] = b'PE\0\0'
            struct.pack_into('<H', raw, 64 + 24 + 68, 2)
            (tmp_path / 'release-out/BEetle-Windows-x64.exe').write_bytes(raw)
        if '--output' in args:
            receipt = Path(args[args.index('--output') + 1])
            receipt.write_text('BEetle (build aaaaaaa)\n{"revision":"' + 'a' * 40 + '"}\n')
    monkeypatch.setattr(module, 'run', run)
    module.windows(payload)
    assert prepared == [payload]
    argv = calls[0]
    embedded = [argv[i + 1] for i, item in enumerate(argv) if item == '--add-data']
    for name in ('ubuntu.wsl', 'wsl.msi', 'usbipd.msi', 'offline-manifest.json', 'payload.tar.gz'):
        assert str(payload / name) + ';.' in embedded
    assert str(tmp_path / 'scripts/release/run.ps1') + ';.' in embedded
    assert '--onefile' in argv and '--noconsole' in argv
    assert any('--self-check' in call for call in calls)


def test_windows_bootstrap_has_no_network_install_fallback():
    source = (ROOT / 'scripts/release/bootstrap.ps1').read_text()
    for forbidden in ('Invoke-WebRequest', 'winget', "'--update'", "'--install --no-distribution'"):
        assert forbidden not in source
    assert '/LimitAccess' in source
    assert 'Get-AuthenticodeSignature' in source
    assert "Join-Path $Root 'ubuntu.wsl'" in source
    assert 'Remove-Item -LiteralPath $download' not in source


def test_release_runtime_includes_beetle_and_ssh_without_pm_script():
    source = (ROOT / 'scripts/release/build.py').read_text()
    assert "ROOT.glob('beetle*.py')" in source
    assert "'--collect-all', package" in source
    assert "('paramiko', 'cryptography', 'bcrypt', 'nacl', 'cffi')" in source
    assert 'post-oobe-mod.sh' not in source and 'pm.sh' not in source


def test_windows_scripts_parse_without_running_bootstrap():
    import shutil
    shell = shutil.which('powershell.exe') or shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell not installed; Windows CI runs this check')
    for name in ('bootstrap.ps1', 'console.ps1', 'run.ps1'):
        path = ROOT / 'scripts/release' / name
        command = "[scriptblock]::Create([IO.File]::ReadAllText('" + str(path).replace("'", "''") + "')) | Out-Null"
        env = load_script('windows_launcher').windows_powershell_environment()
        subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', command], check=True, env=env)


def test_workflow_builds_all_formats_without_publishing():
    source = (ROOT / '.github/workflows/release.yml').read_text()
    for target in ('ubuntu-22.04', 'windows-2022', 'macos-15-intel', 'macos-15'):
        assert target in source
    assert 'workflow_dispatch:' in source
    assert 'gh release' not in source and 'contents: write' not in source


@pytest.mark.parametrize("shell_name", ["powershell.exe", "pwsh"])
def test_bundled_msi_reviews_hashes_publishers_and_exit_codes(shell_name):
    import shutil
    shell = shutil.which(shell_name)
    if not shell:
        pytest.skip(shell_name + ' not installed; Windows CI runs both shells')
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File',
                             str(ROOT / 'scripts/release/test-offline.ps1')],
                            capture_output=True, text=True,
                            env=load_script('windows_launcher').windows_powershell_environment())
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout


@pytest.mark.parametrize("packages", [
    ("libtcl8.6", "libtk8.6"),
    ("libtcl8.6t64", "libtk8.6t64"),
    ("tcl8.6", "tk8.6"),
])
def test_linux_notices_accept_shared_libraries_without_cli_packages(tmp_path, packages):
    module = load_script("build")
    docs, licenses = tmp_path / "doc", tmp_path / "licenses"
    licenses.mkdir()
    for name in (*packages, "libx11-6"):
        directory = docs / name
        directory.mkdir(parents=True)
        (directory / "copyright").write_text("Original " + name + " terms")
    target = module.system_library_notices(licenses, docs)
    for name in (*packages, "libx11-6"):
        assert (target / (name + ".txt")).read_text() == "Original " + name + " terms"


@pytest.mark.parametrize("missing", ["libtcl8.6", "libtk8.6"])
def test_linux_notices_still_require_both_original_license_texts(tmp_path, missing):
    module = load_script("build")
    docs, licenses = tmp_path / "doc", tmp_path / "licenses"
    licenses.mkdir()
    for name in ("libtcl8.6", "libtk8.6"):
        directory = docs / name
        directory.mkdir(parents=True)
        if name != missing:
            (directory / "copyright").write_text("Original terms")
    # A leftover output cannot substitute for a missing installed notice.
    target = licenses / "system-library-notices"
    target.mkdir()
    (target / (missing + ".txt")).write_text("Stale terms")
    with pytest.raises(RuntimeError, match="Missing Tcl/Tk license"):
        module.system_library_notices(licenses, docs)


@pytest.mark.parametrize("key", ["PSModulePath", "PSMODULEPATH", "psmodulepath"])
def test_windows_powershell_child_rebuilds_module_path_without_changing_parent(monkeypatch, key):
    module = load_script("windows_launcher")
    monkeypatch.setenv(key, "PowerShell-7-only-modules")
    monkeypatch.setenv("SystemRoot", "original-windows-root")
    child = module.windows_powershell_environment()
    assert not any(name.upper() == "PSMODULEPATH" for name in child)
    assert child["SystemRoot"] == "original-windows-root"
    assert os.environ[key] == "PowerShell-7-only-modules"


def test_packaged_windows_launcher_passes_clean_environment_to_powershell(tmp_path, monkeypatch):
    import hashlib
    module = load_script("windows_launcher")
    (tmp_path / "payload.tar.gz").write_bytes(b"fixture payload")
    (tmp_path / "payload.sha256").write_text(hashlib.sha256(b"fixture payload").hexdigest())
    (tmp_path / "revision.txt").write_text("a" * 40)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PSModulePath", "PowerShell-7-only-modules")
    monkeypatch.setattr(module, "verify_offline_dependencies", lambda root: None)
    calls = []
    monkeypatch.setattr(module.subprocess, "call",
                        lambda command, **kwargs: calls.append((command, kwargs)) or 0)
    assert module._main([]) == 0
    command, options = calls[0]
    assert command[0] == "powershell.exe"
    assert not any(key.upper() == "PSMODULEPATH" for key in options["env"])
    assert os.environ["PSModulePath"] == "PowerShell-7-only-modules"


def test_macos_transient_mount_failure_retries_then_runs_all_checks_and_detaches(tmp_path, monkeypatch):
    from types import SimpleNamespace
    module = load_script("verify_macos")
    image = tmp_path / "release.dmg"
    image.write_bytes(b"fixture")
    calls, delays = [], []
    attempts = 0
    def run(command, **kwargs):
        nonlocal attempts
        calls.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            attempts += 1
            if attempts == 1:
                return SimpleNamespace(returncode=35, stdout="",
                                       stderr="hdiutil: attach failed - Resource temporarily unavailable")
            mount = Path(command[command.index("-mountpoint") + 1])
            (mount / "BEetle.app").mkdir()
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.time, "sleep", delays.append)
    module.verify_dmg(image, temp_root=tmp_path)
    assert attempts == 2 and delays == [1]
    assert calls[0][:2] == ["hdiutil", "verify"]
    assert any(command[0] == "codesign" for command in calls)
    assert any(command[-1] == "--self-check" for command in calls)
    assert any(command[-1] == "--gui-smoke" for command in calls)
    assert calls[-1][:2] == ["hdiutil", "detach"]
    assert not Path(calls[-1][-1]).parent.exists()


@pytest.mark.parametrize("message,expected_attempts", [
    ("Resource temporarily unavailable", 5),
    ("Resource busy", 5),
    ("image not recognized", 1),
])
def test_macos_mount_retries_are_bounded_and_do_not_ignore_invalid_images(
        monkeypatch, message, expected_attempts):
    from types import SimpleNamespace
    module = load_script("verify_macos")
    calls, delays = [], []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stdout="", stderr=message)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.time, "sleep", delays.append)
    with pytest.raises(subprocess.CalledProcessError):
        module.retry_hdiutil(["attach", "fixture.dmg"])
    assert len(calls) == expected_attempts
    assert len(delays) == expected_attempts - 1


def test_macos_app_validation_failure_still_detaches_its_mount(tmp_path, monkeypatch):
    from types import SimpleNamespace
    module = load_script("verify_macos")
    image = tmp_path / "release.dmg"
    image.write_bytes(b"fixture")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount = Path(command[command.index("-mountpoint") + 1])
            (mount / "BEetle.app").mkdir()
        if command[0] == "codesign":
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        module.verify_dmg(image, temp_root=tmp_path)
    assert calls[-1][:2] == ["hdiutil", "detach"]
    assert not any(command[-1] == "--self-check" for command in calls)


def test_macos_workflow_uploads_verified_app_bundle_before_mount_check():
    workflow = (ROOT / ".github/workflows/release.yml").read_text().split("  macos:", 1)[1]
    assert workflow.index("actions/upload-artifact@v4") < workflow.index("name: Verify mounted app")
    assert "scripts/release/verify_macos.py" in workflow
