import subprocess
import sys
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WindowRegistryImportTests(unittest.TestCase):
    def test_window_registry_imports_without_deleted_party_state_module(self):
        result = subprocess.run(
            [sys.executable, "-c", "import src.core.window_registry"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
