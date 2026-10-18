"""Assemble portable Windows helpers; Cygwin is used on the build host only.

All distributed executables are Windows PE files. The bundled compatibility DLL
is ordinary user-space code; no WSL, Hyper-V, CPU virtualization or shell install.
"""
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
ZADIG = ('https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe',
         '4ecaa95df3da3621486a043aef8b3050b8bafe7c901402871e816229ef82039b')
DRIVER_SOURCE = ('https://codeload.github.com/pbatard/libwdi/tar.gz/refs/tags/v1.5.1',
                 'a695e93db0977dfdc5c6a99a4ea91b22f9027547d0177b2a0f3075078643c929')
DRIVER_SOURCES = {
    'libusbK-3.1.0.0-source.tar.gz': (
        'https://codeload.github.com/mcuee/libusbk/tar.gz/bbd3aaa7650fd479ac888f33d76a46fd6aac7652',
        '3416b478d1ff7d35d359b695a325859b8aab292001ed4e5e09413ee6c8e72a78'),
    'libusb-win32-1.4.0.0-source.tar.gz': (
        'https://codeload.github.com/mcuee/libusb-win32/tar.gz/6d99cb91fdf6eace83f06d5a6ce4c8b510dbca08',
        '23765c84ef92ac39fdd07495c90e5066260ac17d6b81840d251af29c75f50aeb'),
}
CYGWIN_MIRROR = 'https://mirrors.kernel.org/sourceware/cygwin/'
TOOLS = ('dfu-util', 'shofel2_t124', 'debugfs', 'e2fsck', 'resize2fs', 'dumpe2fs', 'mke2fs')


def load_entry_builder():
    spec = importlib.util.spec_from_file_location('beetle_entry_build', ROOT / 'scripts/build_file_level_entry.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_cygwin_sources(text):
    result = {}
    for block in text.split('\n@ ')[1:]:
        name = block.split('\n', 1)[0]
        # Keep current and previous entries: a runner can have either installed.
        for section in re.split(r'\n\[(?:prev|test)\]\n', block):
            version = re.search(r'^version: (.+)$', section, re.M)
            source = re.search(r'^source: (\S+) (\d+) ([0-9a-f]{128})$', section, re.M)
            if version and source:
                result[name + '-' + version.group(1)] = source.groups()
    return result


def copy_dll_closure(tools, search, inspect):
    """Resolve all non-system DLL imports rather than guessing runtime names."""
    directories = [Path(p) for p in search]
    system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    copied, visited = {}, set()
    queue = list(Path(tools).glob('*.exe')) + list(Path(tools).glob('*.dll'))
    while queue:
        path = queue.pop()
        if path.name.lower() in visited:
            continue
        visited.add(path.name.lower())
        for name in inspect(path):
            if name.lower().startswith(('api-ms-', 'ext-ms-')):
                continue
            existing = next((p for p in Path(tools).iterdir() if p.name.lower() == name.lower()), None)
            if existing:
                queue.append(existing)
                continue
            found = next((p for directory in directories if directory.is_dir()
                          for p in directory.iterdir() if p.name.lower() == name.lower()), None)
            if found:
                target = Path(tools) / found.name
                shutil.copy2(found, target)
                copied[target.name] = found
                queue.append(target)
            elif not (system / name).is_file():
                raise RuntimeError('Unbundled Windows DLL: ' + name + ' required by ' + path.name)
    return copied


def runtime_sources(cygwin, libraries, destination, download):
    """Ship the exact sources of the installed DLL packages with the release."""
    metadata = lzma.decompress(urllib.request.urlopen(CYGWIN_MIRROR + 'x86_64/setup.xz', timeout=120).read())
    (destination / 'cygwin-setup.ini').write_bytes(metadata)
    sources = parse_cygwin_sources(metadata.decode())
    packages = {}
    for file in libraries:
        owner = subprocess.check_output([str(cygwin / 'bin/cygcheck.exe'), '-f', str(file)], text=True).strip()
        if not owner or owner not in sources:
            raise RuntimeError('No matching corresponding source for bundled DLL: ' + str(file))
        packages[owner] = sources[owner]
    for owner, (url, size, sha512) in packages.items():
        target = destination / Path(url).name
        if not target.exists():
            data = urllib.request.urlopen(CYGWIN_MIRROR + url, timeout=120).read()
            if len(data) != int(size) or hashlib.sha512(data).hexdigest() != sha512:
                raise RuntimeError('Cygwin corresponding-source checksum mismatch: ' + owner)
            target.write_bytes(data)
    (destination / 'CYGWIN-RUNTIME-SOURCES.json').write_text(json.dumps(packages, indent=2) + '\n')


def build_tools(work, licenses, cygwin, build):
    tools = work / 'tools'
    for name, (url, sha) in build.SOURCES.items():
        archive = licenses / name
        build.download(url, archive, sha)
        build.unpack(archive, work)
    entry = load_entry_builder()
    loader = ROOT / 'assets/loader.bin'
    loader_sha = entry.digest(loader)
    patch = ROOT / 'patches/shofel2-dfu-entry.patch'
    payloads = entry.validate_payload_source(ROOT / 'assets/entry-payloads', loader_sha,
                                            entry.digest(patch), entry.SHOFEL_COMMIT)
    entry.prepare_source(entry.SHOFEL_REPOSITORY, work / 'entry', loader.stat().st_size,
                         loader_sha, patch)
    # Cygwin exists on CI/build hosts only; no installer or distribution in the EXE.
    build.run(cygwin / 'bin/bash.exe', '--noprofile', '--norc',
              ROOT / 'scripts/release/build-windows-tools.sh', work)
    for name in entry.ARM_PAYLOADS:
        shutil.copy2(payloads / name, tools / name)
    def imports(file):
        text = subprocess.check_output([str(cygwin / 'bin/objdump.exe'), '-p', str(file)], text=True)
        return re.findall(r'DLL Name:\s*(\S+)', text)
    libraries = copy_dll_closure(tools, [work / 'usb-prefix/bin', cygwin / 'bin',
        cygwin / 'usr/x86_64-w64-mingw32/sys-root/mingw/bin'], imports)
    runtime_sources(cygwin, libraries.values(), licenses, build.download)
    build.download(ZADIG[0], tools / 'zadig.exe', ZADIG[1])
    build.download(DRIVER_SOURCE[0], licenses / 'libwdi-1.5.1.tar.gz', DRIVER_SOURCE[1])
    for name, (url, sha) in DRIVER_SOURCES.items():
        build.download(url, licenses / name, sha)
    # No guessed driver binary or unsigned replacement: preserve the official utility.
    build.run('powershell.exe', '-NoProfile', '-NonInteractive', '-File',
              ROOT / 'scripts/release/verify-driver.ps1', '-Path', tools / 'zadig.exe',
              env={k:v for k,v in os.environ.items() if k.upper() != 'PSMODULEPATH'})
    (tools / 'zadig.ini').write_text('[general]\nadvanced_mode=true\nexit_on_success=true\n'
        '[device]\nlist_all=true\ninclude_hubs=false\n[driver]\ndefault_driver=2\n', encoding='utf-8')
    return tools, work / 'entry'


def build_windows(build, cygwin):
    from manifest import write_manifest
    work = ROOT / '.build/release-windows-native'
    if work.exists():
        raise RuntimeError('Remove .build/release-windows-native before rebuilding.')
    work.mkdir(parents=True)
    runtime = work / 'runtime'
    runtime.mkdir()
    licenses = runtime / 'licenses'
    licenses.mkdir()
    tools, entry = build_tools(work, licenses, Path(cygwin), build)
    shutil.move(str(tools), runtime / 'tools')
    for file in list(ROOT.glob('jibo*.py')) + list(ROOT.glob('beetle*.py')):
        shutil.copy2(file, runtime / file.name)
    shutil.copy2(ROOT / 'assets/loader.bin', runtime / 'loader.bin')
    shutil.copytree(ROOT / 'assets', runtime / 'assets')
    for source in (ROOT / 'tests/gui_fakes.py', ROOT / 'scripts/release/manifest.py'):
        shutil.copy2(source, runtime / source.name)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    build.notices(licenses, entry, revision)
    write_manifest(runtime, revision)
    out = ROOT / 'release-out'
    out.mkdir(exist_ok=True)
    from PIL import Image
    icon = work / 'BEetle.ico'
    with Image.open(ROOT / 'assets/5x1/logo.png') as image:
        image.convert('RGBA').save(icon, sizes=[(16,16),(32,32),(48,48),(128,128),(256,256)])
    args = [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--onefile',
            '--noconsole', '--name', 'BEetle-Windows-x64', '--icon', icon,
            '--distpath', out, '--workpath', work / 'freeze', '--specpath', work,
            '--paths', ROOT, '--paths', ROOT / 'scripts/release', '--paths', ROOT / 'tests',
            '--add-data', str(runtime) + ';runtime']
    for module in list(ROOT.glob('jibo*.py')) + list(ROOT.glob('beetle*.py')):
        args += ['--hidden-import', module.stem]
    for module in ('tkinter', 'tkinter.ttk', 'tkinter.font', 'tkinter.filedialog',
                   'tkinter.messagebox', 'curses', '_curses', '_curses_panel', 'manifest', 'gui_fakes', 'windows_filesystem_smoke'):
        args += ['--hidden-import', module]
    for package in ('paramiko', 'cryptography', 'bcrypt', 'nacl', 'cffi'):
        args += ['--collect-all', package]
    # Keep helper DLLs beside their EXEs, separate from Python extension DLLs.
    build.run(*args, ROOT / 'scripts/release/windows_launcher.py')
    binary = out / 'BEetle-Windows-x64.exe'
    build.verify_windows_executable(binary)
    for mode in ('--version', '--self-check', '--gui-smoke', '--filesystem-smoke'):
        build.run(binary, mode, '--output', out / ('windows-' + mode[2:] + '.txt'))
    shutil.copy2(licenses / 'toolkit-source.tar.gz', out / 'BEetle-corresponding-source.tar.gz')
    with tarfile.open(out / 'BEetle-Windows-sources.tar.gz', 'w:gz') as archive:
        archive.add(licenses, arcname='licenses')
    for name in ('LICENSE', 'NOTICE.md', 'THIRD-PARTY-NOTICES.md'):
        shutil.copy2(ROOT / name, out / name)
    build.artifact_checksums(out)
