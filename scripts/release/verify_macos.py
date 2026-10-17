#!/usr/bin/env python3
"""Check a release DMG, retrying transient hdiutil resource errors."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time


def retry_hdiutil(arguments, attempts=5):
    command = ['hdiutil', *map(str, arguments)]
    for attempt in range(attempts):
        print('+', *command, flush=True)
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.stdout:
            print(result.stdout, end='', flush=True)
        if result.stderr:
            print(result.stderr, end='', flush=True)
        if result.returncode == 0:
            return result
        message = (result.stdout + result.stderr).lower()
        transient = any(reason in message for reason in
                        ('resource temporarily unavailable', 'resource busy'))
        if not transient or attempt == attempts - 1:
            raise subprocess.CalledProcessError(result.returncode, command,
                                                output=result.stdout, stderr=result.stderr)
        delay = min(2 ** attempt, 8)
        print('Temporary hdiutil resource error; retrying in {}s ({}/{}).'.format(
            delay, attempt + 1, attempts), flush=True)
        time.sleep(delay)


def checked(command):
    command = list(map(str, command))
    print('+', *command, flush=True)
    subprocess.run(command, check=True, timeout=180)


def verify_dmg(image, temp_root=None):
    image = Path(image).resolve(strict=True)
    # Corrupt images fail here; retries never bypass verification.
    checked(['hdiutil', 'verify', image])
    with tempfile.TemporaryDirectory(prefix='beetle-dmg-', dir=temp_root) as directory:
        mountpoint = Path(directory) / 'volume'
        mountpoint.mkdir()
        mounted = False
        try:
            retry_hdiutil(['attach', '-readonly', '-nobrowse', '-mountpoint', mountpoint, image])
            mounted = True
            app = mountpoint / 'BEetle.app'
            if not app.is_dir():
                raise RuntimeError('Mounted DMG does not contain BEetle.app')
            checked(['codesign', '--verify', '--all-architectures', '--deep', '--strict', app])
            binary = app / 'Contents/MacOS/BEetle'
            checked([binary, '--self-check'])
            checked([binary, '--gui-smoke'])
        finally:
            # Only detach the unique mountpoint created by this invocation.
            # Also handle an attach that returned an error after mounting.
            if mounted or os.path.ismount(mountpoint):
                retry_hdiutil(['detach', mountpoint])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    args = parser.parse_args()
    verify_dmg(args.image, temp_root=os.environ.get('RUNNER_TEMP'))
