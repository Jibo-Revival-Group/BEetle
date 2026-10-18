"""Real disposable ext4 probe for the Windows artifact; never accesses USB."""
import json
from pathlib import Path
import subprocess
import tempfile


def filesystem_smoke(runtime):
    import jibo_images
    tools = Path(runtime) / 'tools'
    exe = '.exe' if (tools / 'mke2fs.exe').is_file() else ''
    # Space and Unicode paths are typical Windows profiles and must work.
    with tempfile.TemporaryDirectory(prefix='BEetle native é ') as temporary:
        folder = Path(temporary)
        image = folder / 'disposable var.img'
        with image.open('wb') as stream:
            stream.truncate(32 * 1024 * 1024)
        subprocess.run([str(tools / ('mke2fs' + exe)), '-q', '-F', '-t', 'ext4',
                        '-O', '^orphan_file', str(image)], check=True)
        source = folder / 'fixture identity.json'
        source.write_text('{"fixture":"synthetic-only"}\n', encoding='utf-8')
        jibo_images._run_debugfs(image, 'mkdir /jibo', writable=True)
        jibo_images._run_debugfs(image, 'write ' + jibo_images._debugfs_path(source) + ' /jibo/mode.json', writable=True)
        changed = b'{"mode":"int-developer","fixture":"synthetic-only"}\n'
        jibo_images._replace_file(image, '/jibo/mode.json', changed, folder)
        assert jibo_images._extract(image, '/jibo/mode.json', folder / 'read back.json') == changed
        jibo_images._check_ext4(image)
        subprocess.run([str(tools / ('resize2fs' + exe)), '-f', str(image), '16384K'], check=True)
        jibo_images._check_ext4(image)
        assert jibo_images._extract(image, '/jibo/mode.json', folder / 'after resize.json') == changed
    print(json.dumps({'filesystem_smoke': True, 'unicode_and_spaces': True,
                      'checked_resize': True, 'usb_access': False}))
