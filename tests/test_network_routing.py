"""Run dependency-free JavaScript routing contracts in the regular test suite."""
from pathlib import Path
import subprocess
import unittest


class NetworkRoutingTests(unittest.TestCase):
    def test_edge_routing_geometry_and_source_preservation(self):
        test = Path(__file__).with_suffix('.js')
        result = subprocess.run(['node', str(test)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
