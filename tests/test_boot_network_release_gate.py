"""The release gate must reject an empty/duplicated sweep, not bless 0 tests."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InventoryGateTests(unittest.TestCase):
    def invoke(self, inventory):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'release-inventory.json').write_text(json.dumps(inventory))
            return subprocess.run([
                sys.executable, str(ROOT / 'scripts/check_boot_network_releases.py'),
                '--evidence', str(directory), '--node65', sys.executable,
                '--era-nodes', str(directory), '--out', str(directory / 'out.json'),
            ], capture_output=True, text=True, timeout=20)

    def test_empty_inventory_cannot_pass(self):
        result = self.invoke([])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inventory', result.stderr.lower())

    def test_duplicate_inventory_is_rejected_before_the_sweep(self):
        entry = json.loads((ROOT / 'docs/boot-network-releases.json').read_text())[0]
        result = self.invoke([entry, entry])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inventory', result.stderr.lower())


if __name__ == '__main__':
    unittest.main()
