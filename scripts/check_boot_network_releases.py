#!/usr/bin/env python3
"""Test every archive receipt/layout and its pinned renderer without hardware.

Expects private evidence from the read-only release scanner, not bundled firmware.
Never mount, flash, contact or configure a robot. Every inventory row is counted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import jibo_images as images


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, **kwargs)
    if result.returncode:
        raise RuntimeError('Command failed: ' + repr(command) + '\n' + result.stdout + result.stderr)
    return result.stdout


def display(node, variant):
    asset = str(ROOT / 'assets/boot-network-status' / variant['asset'])
    if variant['renderer'] == 'dom':
        outputs = [run([node, str(ROOT / 'tests/startup-view-dom.test.js'), asset]),
                   run([node, str(ROOT / 'tests/startup-view.test.js'), asset,
                        '^(default source|source |UTF8)'])]
    else:
        outputs = [run([node, str(ROOT / 'tests/startup-view.test.js'), asset])]
    counts = [int(n) for text in outputs for n in re.findall(r'(?:RESULT |^)([0-9]+)(?: tests,| DOM display tests passed)', text, re.M)]
    assert sum(counts) == 28, counts
    return {'node': node, 'node_version': run([node, '--version']).strip(),
            'tests': sum(counts), 'output': '\n'.join(outputs)}


def test_hook(directory, receipt, variant, node, assets):
    """Use extracted init/interfaces, actual stock bytes and real sha256sum."""
    stock = (directory / 'startup-view.js').read_bytes()
    digest = hashlib.sha256(stock).hexdigest()
    assert digest == receipt['files']['startup-view.js'] == variant['stock_sha256']
    sequence = receipt['init_sequence']
    assert len(sequence) == 3, sequence
    assert 'network' in sequence[0] and 'start-X11' in sequence[1] and 'system-manager' in sequence[2]
    assert sequence == sorted(sequence), sequence
    assert 'ifup -a' in (directory / sequence[0]).read_text()
    assert 'var/etc/network/interfaces' in (directory / 'interfaces-link.txt').read_text()
    assert any('Bind a file' in s or '[r]bind' in s for s in receipt['busybox_evidence'])
    interfaces = (directory / 'interfaces').read_bytes()
    installed = images.build_boot_network_status_startup(interfaces, 'install')
    assert images.build_boot_network_status_startup(installed, 'install') == installed
    assert images.build_boot_network_status_startup(installed, 'remove') == interfaces
    assert installed.count(images.BOOT_NETWORK_STATUS_HOOK.encode()) == 1
    system = json.loads((directory / 'system-manager.json').read_text())
    assert system['SystemManager']['serverPort'] == 8585
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        target = root / 'usr/local/bin/jibo-ssm/startup/startup-view.js'
        target.parent.mkdir(parents=True)
        target.write_bytes(stock)
        asset_dir = root / 'var/jibo/phoenix/network-status'
        asset_dir.mkdir(parents=True)
        for name, content in assets.items():
            (asset_dir / name).write_bytes(content)
        (root / 'var/log').mkdir()
        (root / 'var/etc/network').mkdir(parents=True)
        (root / 'var/etc/network/interfaces').write_bytes(installed)
        (root / 'etc/network').mkdir(parents=True)
        (root / 'etc/network/interfaces').symlink_to('../../var/etc/network/interfaces')
        (root / 'proc/self').mkdir(parents=True)
        (root / 'proc/self/mountinfo').write_text('1 0 1:1 / /usr/local ro - ext4 /dev/svc ro\n')
        (root / 'usr/bin').mkdir()
        (root / 'usr/bin/node').symlink_to(node)
        (root / 'bin').mkdir()
        real_sha = shutil.which('sha256sum')
        assert real_sha
        (root / 'usr/bin/sha256sum').write_text('#!/bin/sh\nexec ' + shlex.quote(real_sha) + ' "$@"\n')
        # Execute the release's real getmode under its matching host-era Node.
        # Only the absolute filename is mapped into the isolated fake root.
        mode_script = (directory / 'jibo-getmode').read_text()
        assert mode_script.count('/var/jibo/mode.json') == 1
        fixture_mode = root / 'var/jibo/mode.json'
        fixture_mode.write_text('{"mode":"int-developer"}')
        body = mode_script.split('\n', 1)[1].replace('/var/jibo/mode.json', str(fixture_mode))
        (root / 'getmode.js').write_text(body)
        (root / 'usr/bin/jibo-getmode').write_text('#!/bin/sh\nexec ' + shlex.quote(node) + ' ' + shlex.quote(str(root / 'getmode.js')) + '\n')
        calls = root / 'calls'
        (root / 'bin/mount').write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(calls)) + '\n')
        for path in (root / 'usr/bin/sha256sum', root / 'usr/bin/jibo-getmode', root / 'bin/mount'):
            path.chmod(0o755)
        dry = run(['busybox', 'ifup', '-n', '-m', '-i', str(root / 'etc/network/interfaces'), 'lo'])
        assert images.BOOT_NETWORK_STATUS_HOOK[len('post-up '):] in dry, dry
        run(['busybox', 'sh', str(asset_dir / 'boot-network-status.sh')],
            env=dict(os.environ, JIBO_NETSTATUS_ROOT=str(root)))
        expected = '-n -o bind ' + str(asset_dir / variant['asset']) + ' ' + str(target)
        assert calls.read_text().splitlines() == [expected]
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
        # Simulate an installed mountpoint; no second bind is allowed.
        (root / 'proc/self/mountinfo').write_text('2 1 1:2 /source ' + str(target) + ' rw - ext4 /dev/var rw\n')
        run(['busybox', 'sh', str(asset_dir / 'boot-network-status.sh')],
            env=dict(os.environ, JIBO_NETSTATUS_ROOT=str(root)))
        assert calls.read_text().splitlines() == [expected]
    return {'status': 'passed', 'init_order': sequence, 'dry_run': dry,
            'stock_sha256': digest, 'patched_sha256': variant['patched_sha256'],
            'secure_log_path': '/var/jibo/phoenix/network-status/boot-network-status.log'}


def validate_inventory(inventory, catalog):
    expected = {(row['name'], row['url']) for row in catalog}
    actual = {(row['name'], row['url']) for row in inventory}
    if not inventory or len(actual) != len(inventory) or actual != expected:
        raise ValueError('release inventory is empty, duplicated, or differs from the pinned catalog')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--node65', required=True)
    parser.add_argument('--era-nodes', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    inventory = json.loads((args.evidence / 'release-inventory.json').read_text())
    catalog = json.loads((ROOT / 'docs/boot-network-releases.json').read_text())
    try:
        validate_inventory(inventory, catalog)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error('invalid release inventory: ' + str(exc))
    catalog = {row['name']: row for row in catalog}
    assets = images.boot_network_status_assets()
    manifest = json.loads(assets['manifest.json'])
    variants = {row['stock_sha256']: row for row in manifest['variants']}
    report = {'inventory_count': len(inventory), 'releases': [], 'hardware_tested': False}
    failures = 0
    for entry in inventory:
        name = entry['name'][:-len('.tar.bz2')]
        directory = args.evidence / 'releases' / name
        row = dict(name=entry['name'], url=entry['url'])
        try:
            receipt = json.loads((directory / 'receipt.json').read_text())
            if receipt['status'] != 'extracted':
                raise RuntimeError(receipt.get('error', receipt['status']))
            expected = catalog[entry['name']]
            assert receipt['archive_sha256'] == expected['archive_sha256'], 'archive checksum'
            assert receipt['ssm_version'] == expected['ssm_version'], 'SSM version'
            assert receipt['files']['startup-view.js'] == expected['startup_view_sha256'], 'stock view checksum'
            mounts = json.loads((directory / 'boot-mounts.json').read_text())
            assert mounts['status'] == 'passed', 'pre-rcS mount layout not verified'
            assert mounts['rootfs_sha256'] == expected['rootfs_sha256'], 'rootfs checksum'
            for filename, key in (('inittab', 'inittab_sha256'), ('fstab', 'fstab_sha256')):
                assert hashlib.sha256((directory / filename).read_bytes()).hexdigest() == expected[key], filename + ' checksum'
            inittab = (directory / 'inittab').read_text()
            assert inittab.index('/bin/mount -a') < inittab.index('/etc/init.d/rcS'), 'pre-rcS mounts'
            assert '/etc/init.d/S??*' in (directory / 'rcS').read_text(), 'rcS ordering'
            assert hashlib.sha256((directory / 'interfaces').read_bytes()).hexdigest() == expected['interfaces_sha256'], 'interfaces checksum'
            row['boot_mounts'] = {'status': 'passed', 'inittab_sha256': expected['inittab_sha256'],
                                  'fstab_sha256': expected['fstab_sha256']}
            digest = receipt['files']['startup-view.js']
            variant = variants[digest]
            binary = (directory / 'node-resolved').read_bytes()
            versions = sorted({v.decode() for v in re.findall(rb'(?:node.js/v|https://nodejs.org/download/release/v)([0-9]+\.[0-9]+\.[0-9]+)', binary)})
            assert len(versions) == 1, versions
            assert versions[0] == expected['compiled_node_version'], 'compiled Node version'
            node = str((args.era_nodes / ('node-v' + versions[0])).resolve())
            row.update(ssm_version=receipt['ssm_version'], variant=variant['renderer'], compiled_node=versions[0])
            row['display'] = [display(args.node65, variant), display(node, variant)]
            row['hook'] = test_hook(directory, receipt, variant, node, assets)
            row['status'] = 'offline passed'
        except Exception as exc:
            failures += 1
            row['status'] = 'not verified'
            row['error'] = str(exc)
        report['releases'].append(row)
        print(row['name'], row['status'], row.get('error', '')[:200], flush=True)
        args.out.write_text(json.dumps(report, indent=2) + '\n')
    assert len(report['releases']) == len(inventory)
    report.update(passed=len(inventory)-failures, not_verified=failures,
                  display_test_executions=sum(d['tests'] for r in report['releases'] for d in r.get('display', [])))
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
