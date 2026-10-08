"""Real Pixi display-object state and shared-resource lifetime contracts."""
from pathlib import Path
import subprocess
import unittest


class NetworkPixiTests(unittest.TestCase):
    def test_focus_continuity_and_shared_resources(self):
        test = Path(__file__).with_suffix('.js')
        result = subprocess.run(['node', str(test)], cwd=test.resolve().parents[1], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
