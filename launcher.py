"""CLI wrapper for PoE2 multi-instance launcher. Delegates to src.core.multi_launcher.

Usage:
    python launcher.py                # Launch 2 instances (default)
    python launcher.py --count 3      # Launch 3 instances
    python launcher.py --standalone   # Use standalone client
    python launcher.py --executable "C:\\Games\\PoE2\\PathOfExile.exe"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.core.multi_launcher import MultiLauncher


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch multiple PoE2 instances with mutex bypass",
    )
    parser.add_argument("--count", type=int, default=2,
                        help="Number of instances to launch (default: 2)")
    parser.add_argument("--executable", type=Path, default=None,
                        help="Path to PoE2 executable (auto-detected if omitted)")
    parser.add_argument("--config-dir", type=Path, default=None,
                        help="Config base directory (default: Documents/My Games/Path of Exile 2)")
    parser.add_argument("--delay", type=float, default=5.0,
                        help="Delay between launches in seconds (default: 5)")
    parser.add_argument("--standalone", action="store_true",
                        help="Prefer standalone over Steam executable")

    args = parser.parse_args()

    if args.standalone and not args.executable:
        probe = MultiLauncher()
        standalone_path = probe.find_standalone_poe2()
        if standalone_path:
            for candidate in [standalone_path / "PathOfExile.exe"]:
                if candidate.exists():
                    args.executable = candidate
                    break

    launcher = MultiLauncher(callback=print)
    results = launcher.launch(
        count=args.count,
        executable=args.executable,
        config_base_dir=args.config_dir,
        wait_between=args.delay,
    )

    failures = [r for r in results if r.pid == 0]
    if failures:
        for f in failures:
            print(f"  Instance {f.instance_index + 1}: FAILED — {f.error}")
        return 1

    print(f"All {len(results)} instances launched successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
