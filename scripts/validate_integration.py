"""Integration validation runner for RouteForge."""

import subprocess
import sys


def main() -> None:
    cmd = [sys.executable, "scripts/validate.py", "integration"]
    result = subprocess.run(cmd, check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
