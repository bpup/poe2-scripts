import importlib
import importlib.util
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


class RuntimePathTests(unittest.TestCase):
    def test_frozen_app_uses_pyinstaller_bundle_directory_for_resources(self):
        module_name = "src.common.runtime_paths"
        self.assertIsNotNone(
            importlib.util.find_spec(module_name),
            "runtime path helper is required for bundled resources",
        )
        runtime_paths = importlib.import_module(module_name)

        with TemporaryDirectory() as bundle_dir:
            bundle_path = Path(bundle_dir)
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", str(bundle_path), create=True
            ):
                self.assertEqual(runtime_paths.resource_root(), bundle_path)


if __name__ == "__main__":
    unittest.main()
