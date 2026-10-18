#!/usr/bin/env python3
"""Build self-contained BEetle releases on a native build host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from manifest import write_manifest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    'libusb-1.0.27.tar.bz2': ('https://github.com/libusb/libusb/releases/download/v1.0.27/libusb-1.0.27.tar.bz2',
                            'ffaa41d741a8a3bee244ac8e54a72ea05bf2879663c098c82fc5757853441575'),
    'dfu-util-0.11.tar.gz': ('https://dfu-util.sourceforge.net/releases/dfu-util-0.11.tar.gz',
                          'b4b53ba21a82ef7e3d4c47df2952adf5fa494f499b6b0b57c58c5d04ae8ff19e'),
    'e2fsprogs-1.47.1.tar.gz': ('https://www.kernel.org/pub/linux/kernel/people/tytso/e2fsprogs/v1.47.1/e2fsprogs-1.47.1.tar.gz',
                              '0d2e0bf80935c3392b73a60dbff82d8a6ef7ea88b806c2eea964b6837d3fd6c2'),
}
APPIMAGETOOL = ('https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage',
                'ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0')
TOOLS = ('dfu-util', 'debugfs', 'e2fsck', 'resize2fs', 'dumpe2fs', 'mke2fs')


def run(*args, cwd=None, env=None):
    print('+', *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def download(url, destination, expected=None):
    destination = Path(destination)
    temporary = destination.with_name(destination.name + '.partial')
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as stream:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                stream.write(block)
        actual = digest.hexdigest()
        if expected and actual != expected:
            raise RuntimeError('Download hash mismatch: ' + url)
        temporary.replace(destination)
        return actual
    finally:
        temporary.unlink(missing_ok=True)


def unpack(archive, directory):
    # Only SHA256-pinned build-time upstream archives, never end-user archives.
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            path = (directory / member.name).resolve()
            if directory.resolve() not in path.parents:
                raise RuntimeError('Unsafe source archive path: ' + member.name)
        source.extractall(directory)


def configure_flags(name, prefix):
    flags = ['--prefix=' + str(prefix), '--disable-nls']
    if name.startswith('libusb'):
        flags = ['--prefix=' + str(prefix), '--disable-static']
        if sys.platform != 'darwin':
            flags += ['--disable-udev']
    elif name.startswith('e2fsprogs'):
        flags += ['--disable-fuse2fs', '--without-udev-rules-dir',
                  '--without-systemd-unit-dir', '--without-crond-dir']
    return flags


def dependencies(work, licenses):
    prefix = work / 'prefix'
    prefix.mkdir()
    env = os.environ.copy()
    env.update(PKG_CONFIG_PATH=str(prefix / 'lib/pkgconfig'),
               CPPFLAGS='-I' + str(prefix / 'include'), LDFLAGS='-L' + str(prefix / 'lib'))
    for name, (url, sha) in SOURCES.items():
        archive = licenses / name
        download(url, archive, sha)
        unpack(archive, work)
        source = work / name.split('.tar.')[0]
        flags = configure_flags(name, prefix)
        run(source / 'configure', *flags, cwd=source, env=env)
        run('make', '-j4', cwd=source, env=env)
        run('make', 'install', cwd=source, env=env)
        for license_name in ('COPYING', 'COPYING.LIB', 'NOTICE', 'LICENSE'):
            file = source / license_name
            if file.is_file():
                shutil.copy2(file, licenses / (source.name + '-' + license_name))
    return prefix


def formula_source_pin(text):
    url = re.search(r'^\s*url\s+"(https://[^"#]+)"', text, re.MULTILINE)
    sha = re.search(r'^\s*sha256\s+"([0-9a-f]{64})"', text, re.MULTILINE)
    if not url or not sha:
        raise ValueError('Installed formula has no literal stable source pin')
    return url.group(1), sha.group(1)


def source_notice_contents(archive):
    def is_notice(name):
        return any(Path(name).name.lower().startswith(k) for k in
                   ('license', 'licence', 'copying', 'copyright', 'notice'))
    contents = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            contents = [(name, source.read(name)) for name in source.namelist() if is_notice(name)]
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                if member.isfile() and is_notice(member.name):
                    extracted = source.extractfile(member)
                    if extracted is not None:
                        contents.append((member.name, extracted.read()))
    # Some formula sources are raw data (e.g. ca-certificates' cacert.pem).
    return contents


def notice_path(relative):
    # License-only copies must not masquerade as executable macOS bundles.
    suffixes = ('.framework', '.app', '.bundle', '.xpc', '.appex')
    parts = list(Path(relative).parts)
    for index, part in enumerate(parts[:-1]):
        for suffix in suffixes:
            if part.endswith(suffix):
                parts[index] = part[:-len(suffix)] + suffix.replace('.', '_')
    return Path(*parts)


def mac_dependency_notices(licenses):
    # A superset of runtime dependencies is deliberate: include all installed
    # interpreter dependency notices, and corresponding sources for GPL/LGPL libs.
    names = set()
    for formula_name in ('python@3.12', 'python-tk@3.12'):
        names.update(subprocess.check_output(['brew', 'deps', '--formula', formula_name],
                                            text=True).splitlines())
    inventory = {}
    for name in sorted(names):
        keg = Path(subprocess.check_output(['brew', '--prefix', name], text=True).strip()).resolve()
        target = licenses / 'Homebrew-dependencies' / name
        target.mkdir(parents=True)
        formula = next((keg / '.brew').glob('*.rb'))
        text = formula.read_text()
        shutil.copy2(formula, target)
        receipt = keg / 'INSTALL_RECEIPT.json'
        if receipt.is_file():
            shutil.copy2(receipt, target)
        copied = []
        for file in keg.rglob('*'):
            if file.is_file() and any(file.name.lower().startswith(k) for k in
                                     ('license', 'licence', 'copying', 'copyright', 'notice')):
                relative = file.relative_to(keg)
                bundle_path = notice_path(relative)
                destination = target / bundle_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, destination)
                copied.append({'source_path': relative.as_posix(), 'bundle_path': bundle_path.as_posix()})
        copyleft = bool(re.search(r'\bL?GPL-', text))
        item = {'keg_version': keg.name, 'notices': copied, 'source_included': False}
        if copyleft or not copied:
            url, sha = formula_source_pin(text)
            archive = target / ('corresponding-source-' + Path(url.split('?', 1)[0]).name)
            print('Preserving dependency source:', name, url, flush=True)
            download(url, archive, sha)
            item.update(source_included=True, source_url=url, source_sha256=sha)
            # Archives themselves contain all original attribution/license texts.
            for member_name, content in source_notice_contents(archive):
                destination = target / 'source-notices' / notice_path(member_name)
                if target.resolve() not in destination.resolve().parents:
                    raise RuntimeError('Unsafe source notice path: ' + member_name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            if not tarfile.is_tarfile(archive) and not zipfile.is_zipfile(archive):
                # Preserve full terms for source inputs distributed as raw data.
                license_id = re.search(r'^\s*license\s+"([A-Za-z0-9.-]+)"', text, re.MULTILINE)
                if license_id:
                    download('https://raw.githubusercontent.com/spdx/license-list-data/main/text/' +
                             license_id.group(1) + '.txt', target / 'LICENSE.txt')
        inventory[name] = item
    (licenses / 'Homebrew-dependencies.json').write_text(json.dumps(inventory, indent=2) + '\n')
    print('Bundled interpreter dependency notices:', json.dumps(inventory, indent=2))


def notices(licenses, entry, revision):
    for name in ('LICENSE', 'NOTICE.md', 'THIRD-PARTY-NOTICES.md', 'vendor/jibo-ram-dfu-v1-source.tar.gz'):
        shutil.copy2(ROOT / name, licenses / Path(name).name)
    shutil.copytree(ROOT / 'firmware', licenses / 'firmware')
    for name in ('build_loader.py', 'build_file_level_entry.py'):
        shutil.copy2(ROOT / 'scripts' / name, licenses / name)
    shutil.copy2(ROOT / 'patches/shofel2-dfu-entry.patch', licenses)
    shutil.copy2(ROOT / 'docs/loader-build.md', licenses)
    # Include the actual patched ShofEL source and protocol header used to compile.
    with tarfile.open(licenses / 'ShofEL2-corresponding-source.tar.gz', 'w:gz') as archive:
        for file in sorted(entry.rglob('*')):
            if file.is_file() and '.git' not in file.parts and file.suffix not in ('.o', '.d') and file.name not in ('shofel2_t124', 'intermezzo.bin', 'dfu_stage2.bin'):
                archive.add(file, arcname='ShofEL2/' + file.relative_to(entry).as_posix())
    # Preserve component file headers as well as any top-level license files.
    for file in entry.iterdir():
        if file.is_file() and any(x in file.name.upper() for x in ('COPYING', 'LICENSE', 'NOTICE')):
            shutil.copy2(file, licenses / ('ShofEL2-' + file.name))
    paths = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
    with tarfile.open(licenses / 'toolkit-source.tar.gz', 'w:gz') as archive:
        for name in sorted(set(paths)):
            path = ROOT / name
            if name and path.is_file() and not path.is_symlink():
                archive.add(path, arcname=name)
    packages = ('paramiko', 'bcrypt', 'PyNaCl', 'cffi', 'pycparser') + (('windows-curses',) if sys.platform == 'win32' else ())
    for package_name in packages:
        import importlib.metadata
        dist = importlib.metadata.distribution(package_name)
        for file in dist.files or ():
            if any(term in str(file).lower() for term in ('license', 'copying', 'notice')):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = licenses / package_name / Path(*[part for part in file.parts if part not in ('..', '.')])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        if package_name == 'windows-curses':
            # PyPI publishes wheels only; preserve the matching tagged source and
            # its exact PDCurses submodule, in addition to wheel license texts.
            if dist.version != '2.4.1':
                raise RuntimeError('Unexpected windows-curses version')
            download('https://codeload.github.com/zephyrproject-rtos/windows-curses/tar.gz/refs/tags/v2.4.1',
                     licenses / 'windows-curses-2.4.1-source.tar.gz',
                     '7ae72796f76884ace8a1c4e9cc798a0550baead4a48d62a596021c2dca5124ed')
            download('https://codeload.github.com/zephyrproject-rtos/PDCurses/tar.gz/5c62af03e9a05e3a3ae8c8354c1234b772dcf4b0',
                     licenses / 'PDCurses-5c62af03-source.tar.gz',
                     'e5a0819807ea4f5ff11d89048b177a915c2081832155303fb0989600fdc71769')
            continue
        metadata = json.loads(urllib.request.urlopen(
            'https://pypi.org/pypi/' + package_name + '/' + dist.version + '/json').read())
        source = next(item for item in metadata['urls'] if item['packagetype'] == 'sdist')
        download(source['url'], licenses / source['filename'], source['digests']['sha256'])
    import PyInstaller
    package = Path(PyInstaller.__file__).parent
    candidates = [package / 'COPYING.txt', package.parent / 'pyinstaller' / 'COPYING.txt']
    found = next((p for p in candidates if p.is_file()), None)
    if found:
        shutil.copy2(found, licenses / 'PyInstaller-COPYING.txt')
    else:
        download('https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.16.0/COPYING.txt', licenses / 'PyInstaller-COPYING.txt')
    import importlib.metadata
    crypto = importlib.metadata.distribution('cryptography')
    if crypto.version != '46.0.3':
        raise RuntimeError('Unexpected cryptography version')
    for file in crypto.files or ():
        if '.dist-info/licenses/' in str(file):
            source = Path(crypto.locate_file(file))
            if source.is_file():
                shutil.copy2(source, licenses / ('cryptography-' + source.name))
    download('https://files.pythonhosted.org/packages/9f/33/c00162f49c0e2fe8064a62cb92b93e50c74a72bc370ab92f86112b33ff62/cryptography-46.0.3.tar.gz',
             licenses / 'cryptography-46.0.3.tar.gz',
             'a8b17438104fed022ce745b362294d9ce35b4c2e45c1d958ad4a4b019285f4a1')
    version = '.'.join(map(str, sys.version_info[:3]))
    download('https://raw.githubusercontent.com/python/cpython/v' + version + '/LICENSE', licenses / 'Python-LICENSE.txt')
    if sys.platform == 'darwin':
        mac_dependency_notices(licenses)
        prefix = Path(subprocess.check_output(['brew', '--prefix', 'tcl-tk'], text=True).strip())
        terms = [p for p in prefix.rglob('*') if p.is_file() and p.name.lower() in ('license.terms', 'license', 'license.txt', 'copying')]
        if not terms:
            # Homebrew uses tcl-tk@8 for python-tk@3.12 on some runner revisions.
            prefix = Path(subprocess.check_output(['brew', '--prefix', 'tcl-tk@8'], text=True).strip())
            terms = [p for p in prefix.rglob('*') if p.is_file() and p.name.lower() in ('license.terms', 'license', 'license.txt', 'copying')]
        for i, path in enumerate(terms):
            shutil.copy2(path, licenses / ('TclTk-' + str(i) + '-' + path.name))
        if not terms:
            raise RuntimeError('Tcl/Tk license texts are missing')
    elif sys.platform == "linux":
        system_library_notices(licenses)
    elif sys.platform == "win32":
        for path in Path(sys.base_prefix).glob("tcl/*/license.terms"):
            shutil.copy2(path, licenses / ("TclTk-" + path.parent.name + "-license.terms"))
    download('https://raw.githubusercontent.com/AppImage/type2-runtime/main/LICENSE', licenses / 'AppImage-runtime-LICENSE.txt')
    (licenses / 'BUILD-SOURCES.json').write_text(json.dumps({'revision': revision, 'sources': SOURCES,
        'python': sys.version, 'pyinstaller': PyInstaller.__version__,
        'ssh_dependencies': {name: importlib.metadata.version(name)
            for name in ('paramiko', 'cryptography', 'bcrypt', 'PyNaCl', 'cffi', 'pycparser')}}, indent=2) + '\n')


def system_library_notices(licenses, doc_root=Path('/usr/share/doc')):
    """Preserve Debian/Ubuntu notices, including library-only Tcl/Tk installs."""
    target = Path(licenses) / 'system-library-notices'
    target.mkdir(exist_ok=True)
    for path in Path(doc_root).glob('*/copyright'):
        if path.is_file():
            shutil.copy2(path, target / (path.parent.name + '.txt'))
    # python3-tk needs the shared libraries, not the optional tclsh/wish
    # command packages. Accept their original notices without requiring the CLIs.
    for component in ('tcl8.6', 'tk8.6'):
        packages = (component, 'lib' + component, 'lib' + component + 't64')
        if not any((Path(doc_root) / package / 'copyright').is_file() for package in packages):
            raise RuntimeError('Missing Tcl/Tk license: ' + component +
                               '; expected /usr/share/doc/{' + ','.join(packages) + '}/copyright')
    return target



def entry_build_env(prefix):
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = str(prefix / 'lib')
    env['LIBRARY_PATH'] = str(prefix / 'lib')
    env['CPATH'] = str(prefix / 'include/libusb-1.0')
    if sys.platform != 'darwin':
        # Build only the two payloads actually distributed, not unrelated examples
        # that need newer C dialects than Ubuntu's ARM GCC. Source launcher unchanged.
        env['MAKEFLAGS'] = 'BIN_FILES=intermezzo.bin\\ dfu_stage2.bin'
    return env


def external_macho_dependencies(output):
    dependencies = []
    for line in output.splitlines()[1:]:
        name = line.strip().split(' (', 1)[0]
        if name and not name.startswith(('@', '/usr/lib/', '/System/Library/')):
            dependencies.append(name)
    return dependencies


def audit_macho(root):
    seen = set()
    for directory, _, names in os.walk(root, followlinks=True):
        for name in names:
            path = Path(directory) / name
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic not in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
                continue
            output = subprocess.check_output(['otool', '-L', str(path)], text=True)
            external = external_macho_dependencies(output)
            if external:
                raise RuntimeError('Unbundled Mach-O dependency in ' + str(path) + ': ' + str(external))
    print('PASS: Mach-O dependencies contain only bundle-relative or macOS system references')


def native(architecture):
    import platform
    actual = {'AMD64': 'x86_64', 'aarch64': 'arm64'}.get(platform.machine(), platform.machine())
    if architecture != actual or (sys.platform == 'linux' and architecture != 'x86_64'):
        raise RuntimeError('Build on the requested native architecture; Linux currently supports x86_64.')
    work = ROOT / '.build/release'
    if work.exists():
        raise RuntimeError('Build directory already exists. Remove .build/release before rebuilding.')
    work.mkdir(parents=True)
    runtime = work / 'runtime'
    runtime.mkdir()
    licenses = runtime / 'licenses'
    licenses.mkdir()
    prefix = dependencies(work, licenses)
    env = entry_build_env(prefix)
    entry = work / 'entry'
    args = [sys.executable, ROOT / 'scripts/build_file_level_entry.py', '--out', entry]
    if sys.platform == 'darwin':
        args += ['--libusb-prefix', prefix]
    run(*args, env=env)
    tools = runtime / 'tools'
    tools.mkdir()
    for name in TOOLS:
        path = next((prefix / d / name for d in ('bin', 'sbin') if (prefix / d / name).is_file()), None)
        if path is None:
            raise RuntimeError('Missing prebuilt tool: ' + name)
        shutil.copy2(path, tools / name)
    for name in ('shofel2_t124', 'intermezzo.bin', 'dfu_stage2.bin'):
        shutil.copy2(entry / name, tools / name)
    lib = runtime / 'lib'
    lib.mkdir()
    library_name = 'libusb-1.0.dylib' if sys.platform == 'darwin' else 'libusb-1.0.so.0'
    shutil.copy2(prefix / 'lib' / library_name, lib / library_name)
    for path in list(ROOT.glob('jibo*.py')) + list(ROOT.glob('beetle*.py')):
        shutil.copy2(path, runtime / path.name)
    shutil.copytree(ROOT / 'assets', runtime / 'assets')
    shutil.copy2(ROOT / 'assets/loader.bin', runtime / 'loader.bin')
    shutil.copy2(ROOT / 'tests/gui_fakes.py', runtime / 'gui_fakes.py')
    shutil.copy2(ROOT / 'scripts/release/manifest.py', runtime / 'manifest.py')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    notices(licenses, entry, revision)
    # Mach-O relocation/ad-hoc preparation changes binary bytes during freezing.
    # Hash data before freezing, then NEVER edit the sealed .app afterward.
    excluded = (['tools/' + name for name in TOOLS + ('shofel2_t124',)] +
                ['lib/' + library_name]) if sys.platform == 'darwin' else []
    write_manifest(runtime, revision, exclude=excluded)
    from PIL import Image
    icon = work / ('BEetle.icns' if sys.platform == 'darwin' else 'BEetle.png')
    with Image.open(ROOT / 'assets/5x1/logo.png') as image:
        image.convert('RGBA').save(icon)
    name = 'BEetle' if sys.platform == 'darwin' else 'jibo-dfu'
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', name,
            '--icon', icon, '--distpath', work / 'dist', '--workpath', work / 'freeze', '--specpath', work,
            '--paths', ROOT, '--paths', ROOT / 'tests',
            '--add-data', str(runtime) + ':runtime', '--hidden-import', 'tkinter',
            '--hidden-import', 'tkinter.ttk', '--hidden-import', 'tkinter.font',
            '--hidden-import', 'tkinter.filedialog', '--hidden-import', 'tkinter.messagebox',
            '--hidden-import', 'gui_fakes', '--hidden-import', 'manifest']
    for module in list(ROOT.glob('jibo*.py')) + list(ROOT.glob('beetle*.py')):
        args += ['--hidden-import', module.stem]
    for package in ('paramiko', 'cryptography', 'bcrypt', 'nacl', 'cffi'):
        args += ['--collect-all', package]
    for name in TOOLS + ('shofel2_t124',):
        args += ['--add-binary', str(tools / name) + ':runtime/tools']
    args += ['--add-binary', str(lib / library_name) + ':runtime/lib']
    if sys.platform == 'darwin':
        args += ['--windowed', '--osx-bundle-identifier', 'com.5x1.beetle']
    args += [ROOT / 'scripts/release/native_launcher.py']
    run(*args, env=env)
    # Prove tools do not accidentally execute from/link to the build prefix.
    prefix.rename(work / 'build-prefix-hidden')
    out = ROOT / 'release-out'
    out.mkdir(exist_ok=True)
    if sys.platform == 'darwin':
        app = work / 'dist/BEetle.app'
        run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app,
            out / ('BEetle-macOS-' + architecture + '.app.zip'))
        audit_macho(app)
        # Verification only: no identity signing/notarization step is added.
        run('codesign', '--verify', '--all-architectures', '--deep', '--strict', app)
        binary = app / 'Contents/MacOS/BEetle'
        run(binary, '--self-check')
        run(binary, '--gui-smoke')
        image_root = work / 'dmg-root'
        image_root.mkdir()
        shutil.copytree(app, image_root / app.name, symlinks=True)
        (image_root / 'Applications').symlink_to('/Applications')
        shutil.copy2(ROOT / 'LICENSE', image_root)
        shutil.copy2(ROOT / 'THIRD-PARTY-NOTICES.md', image_root)
        dmg = out / ('BEetle-macOS-' + architecture + '.dmg')
        run('hdiutil', 'create', '-volname', 'BEetle', '-srcfolder', image_root, '-format', 'UDZO', dmg)
        with tarfile.open(out / ('BEetle-macOS-' + architecture + '-corresponding-source.tar.gz'), 'w:gz') as archive:
            archive.add(licenses, arcname='licenses')
    else:
        appdir = work / 'dist/jibo-dfu'
        write_manifest(appdir / '_internal/runtime', revision)
        shutil.copy2(ROOT / 'scripts/release/AppRun', appdir / 'AppRun')
        (appdir / 'AppRun').chmod(0o755)
        run(appdir / 'jibo-dfu', '--self-check')
        run('xvfb-run', '-a', appdir / 'jibo-dfu', '--gui-smoke')
        # The same verified onedir payload is embedded in the Windows bootstrapper.
        with tarfile.open(out / 'payload.tar.gz', 'w:gz') as archive:
            for path in sorted(appdir.iterdir()):
                archive.add(path, arcname=path.name)
        (out / 'revision.txt').write_text(revision + '\n')
        (appdir / 'jibo-dfu.desktop').write_text('[Desktop Entry]\nType=Application\nName=BEetle\nExec=AppRun\nIcon=jibo-dfu\nCategories=Utility;\nTerminal=false\n')
        shutil.copy2(ROOT / 'assets/5x1/logo.svg', appdir / 'jibo-dfu.svg')
        appimagetool = work / 'appimagetool.AppImage'
        download(*[APPIMAGETOOL[0], appimagetool, APPIMAGETOOL[1]])
        appimagetool.chmod(0o755)
        image = out / 'BEetle-Linux-x86_64.AppImage'
        tool_env = os.environ.copy()
        tool_env['ARCH'] = 'x86_64'
        run(appimagetool, '--appimage-extract-and-run', appdir, image, env=tool_env)
        run(image, '--appimage-extract-and-run', '--self-check')
        run('xvfb-run', '-a', image, '--appimage-extract-and-run', '--gui-smoke')
        with tarfile.open(out / 'BEetle-corresponding-source.tar.gz', 'w:gz') as archive:
            archive.add(licenses, arcname='licenses')
        shutil.copy2(ROOT / 'LICENSE', out)
        shutil.copy2(ROOT / 'THIRD-PARTY-NOTICES.md', out)
    artifact_checksums(out)
    print('Release files:', [(p.name, p.stat().st_size) for p in out.iterdir()])


def verify_windows_executable(path):
    import struct
    raw = Path(path).read_bytes()
    pe = struct.unpack_from("<I", raw, 0x3c)[0]
    if raw[:2] != b"MZ" or raw[pe:pe+4] != b"PE\0\0" or struct.unpack_from("<H", raw, pe + 24 + 68)[0] != 2:
        raise RuntimeError("Windows EXE must use WINDOWS_GUI subsystem (2)")
    print("Verified Windows PE Subsystem == 2 (WINDOWS_GUI)", flush=True)


OFFLINE_WINDOWS = {
    'ubuntu.wsl': (
        'https://releases.ubuntu.com/jammy/ubuntu-22.04.5-wsl-amd64.wsl',
        '4499c4fe257f2fc83145b429ce211a0a43fd590e70d6261ede616210947d9f8f'),
    'wsl.msi': (
        'https://github.com/microsoft/WSL/releases/download/2.6.3/wsl.2.6.3.0.x64.msi',
        '562c79aba6ce9b6e9170f069d31e3717f10d76dd8bfbee39b07eae0ca4a02ca0'),
    'usbipd.msi': (
        'https://github.com/dorssel/usbipd-win/releases/download/v5.3.0/usbipd-win_5.3.0_x64.msi',
        '1c984914aec944de19b64eff232421439629699f8138e3ddc29301175bc6d938'),
}


def prepare_offline_windows(payload):
    files = {}
    for name, (url, sha) in OFFLINE_WINDOWS.items():
        path = payload / name
        if not path.exists():
            download(url, path, sha)
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != sha:
            raise RuntimeError('Offline dependency checksum mismatch: ' + name)
        files[name] = {'sha256': sha, 'url': url, 'bytes': path.stat().st_size}
    (payload / 'offline-manifest.json').write_text(json.dumps(
        {'schema': 1, 'files': files}, indent=2) + '\n')


WINDOWS_SOURCES = {
    'WSL-source.tar.gz': (
        'https://codeload.github.com/microsoft/WSL/tar.gz/eb7b0cff015998c199f62b2150c1cd8b5fcfe7b3',
        '1376948e9e5467401cdada7ab396c55759f2cb2c0cd31f8b52da309871c9e678'),
    'usbipd-source.tar.gz': (
        'https://codeload.github.com/dorssel/usbipd-win/tar.gz/aa3db8b82c4cb5071fd31bc54211606c70886912',
        'd9c38b84f281ac1557b550a58275563bc93ee6943b2a4578878c97125ef42101'),
}


def windows_sources(payload, out):
    # Keep the native corresponding source and original installer source notices
    # alongside the EXE. The Ubuntu filesystem carries its own package notices.
    native_source = payload / 'BEetle-corresponding-source.tar.gz'
    if not native_source.is_file():
        raise RuntimeError('Missing Linux corresponding-source archive in Windows payload.')
    for name, (url, sha) in WINDOWS_SOURCES.items():
        download(url, payload / name, sha)
    with tarfile.open(out / 'BEetle-Windows-corresponding-source.tar.gz', 'w:gz') as archive:
        archive.add(native_source, arcname=native_source.name)
        archive.add(ROOT / 'THIRD-PARTY-NOTICES.md', arcname='THIRD-PARTY-NOTICES.md')
        archive.add(payload / 'offline-manifest.json', arcname='offline-manifest.json')
        for name in WINDOWS_SOURCES:
            archive.add(payload / name, arcname=name)


def artifact_checksums(out):
    files = {}
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name != 'SHA256SUMS':
            with path.open('rb') as stream:
                files[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (out / 'SHA256SUMS').write_text(''.join(sha + '  ' + name + '\n' for name, sha in files.items()))



def windows_legacy(payload):
    out = ROOT / 'release-out'
    out.mkdir(exist_ok=True)
    payload = Path(payload).resolve()
    for name in ('payload.tar.gz', 'revision.txt', 'BEetle-corresponding-source.tar.gz'):
        if not (payload / name).is_file():
            raise RuntimeError('Missing Windows build input: ' + name)
    prepare_offline_windows(payload)
    windows_sources(payload, out)
    sha = hashlib.sha256((payload / 'payload.tar.gz').read_bytes()).hexdigest()
    (payload / 'payload.sha256').write_text(sha + '\n')
    windows_license = payload / 'Windows-Python-LICENSE.txt'
    version = '.'.join(map(str, sys.version_info[:3]))
    download('https://raw.githubusercontent.com/python/cpython/v' + version + '/LICENSE', windows_license)
    from PIL import Image
    icon = payload / 'BEetle.ico'
    with Image.open(ROOT / 'assets/5x1/logo.png') as image:
        image.convert('RGBA').save(icon, sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
            '--noconsole', '--icon', icon, '--name', 'BEetle-Windows-x64', '--distpath', out,
            '--workpath', ROOT / '.build/release-windows', '--specpath', ROOT / '.build/release-windows']
    for file in ('payload.tar.gz', 'payload.sha256', 'revision.txt', 'Windows-Python-LICENSE.txt',
                 'ubuntu.wsl', 'wsl.msi', 'usbipd.msi', 'offline-manifest.json'):
        args += ['--add-data', str(payload / file) + ';.']
    for file in ('scripts/release/bootstrap.ps1', 'scripts/release/console.ps1', 'scripts/release/wsl-usb-permissions.sh',
                 'scripts/release/wsl-user-launch.sh', 'scripts/release/wsl-provision.sh', 'scripts/release/run.ps1', 'LICENSE', 'NOTICE.md',
                 'THIRD-PARTY-NOTICES.md'):
        args += ['--add-data', str(ROOT / file) + ';.']
    run(*args, ROOT / 'scripts/release/legacy_wsl_launcher.py')
    binary = out / 'BEetle-Windows-x64.exe'
    verify_windows_executable(binary)
    for mode in ('--version', '--self-check'):
        receipt = out / ('windows-' + mode[2:] + '.txt')
        run(binary, mode, '--output', receipt)
        text = receipt.read_text(encoding='utf-8')
        print(text, flush=True)
        revision = (payload / 'revision.txt').read_text().strip()
        if not text.startswith('BEetle (build ' + revision[:7] + ')'):
            raise RuntimeError('Windows diagnostic banner missing: ' + mode)
        if mode == '--self-check' and json.loads(text.splitlines()[-1])['revision'] != revision:
            raise RuntimeError('Windows self-check revision mismatch')
    for name in ('LICENSE', 'NOTICE.md', 'THIRD-PARTY-NOTICES.md'):
        shutil.copy2(ROOT / name, out)
    artifact_checksums(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    import platform
    default_arch = 'arm64' if platform.machine() in ('arm64', 'aarch64') else 'x86_64'
    parser.add_argument('--architecture', choices=('arm64', 'x86_64'), default=default_arch)
    parser.add_argument('--windows-payload', type=Path, help='Legacy WSL package only')
    parser.add_argument('--windows-native', action='store_true', help='Build the direct, portable Windows EXE')
    parser.add_argument('--cygwin-root', type=Path, default=Path('C:/cygwin'))
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Release builds need Python 3.11 or newer; Python 3.12 is recommended.')
    if args.windows_native or (sys.platform == 'win32' and not args.windows_payload):
        if sys.platform != 'win32':
            parser.error('Build the Windows EXE on Windows x64.')
        from windows_native_build import build_windows
        build_windows(sys.modules[__name__], args.cygwin_root)
    elif args.windows_payload:
        if sys.platform != 'win32':
            parser.error('Build the Windows EXE on Windows x64.')
        windows_legacy(args.windows_payload)
    else:
        if sys.platform not in ('linux', 'darwin'):
            parser.error('Build AppImage on Linux or .app on macOS.')
        native(args.architecture)
