"""Central validation script for RouteForge.

Executes linting, static typing, architecture checks, config validation, and tests.
Accepts 'integration' argument to run integration test suites explicitly.
"""

import subprocess
import sys


def get_stages(is_integration: bool) -> list[tuple[str, list[str]]]:
    pytest_cmd = (
        ["pytest", "tests/integration/storage", "tests/integration/gateway"]
        if is_integration
        else ["pytest"]
    )
    return [
        ("1. Ruff Format Check", ["ruff", "format", "--check", "."]),
        ("2. Ruff Lint Check", ["ruff", "check", "."]),
        ("3. Mypy Type Check", ["mypy", "src", "tests", "scripts"]),
        (
            "4. Architecture Dependency Validation",
            [sys.executable, "scripts/validate_architecture.py"],
        ),
        ("5. Configuration Validation", [sys.executable, "scripts/validate_config.py"]),
        ("6. Pytest Test Execution", pytest_cmd),
    ]


def run_stage(title: str, command: list[str]) -> int:
    """Print stage header and execute stage command without shell execution."""
    print(f"\n=== {title} ===")
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, check=False)
    return result.returncode


def main() -> None:
    """Run all validation stages sequentially and exit with non-zero on failure."""
    is_integration = len(sys.argv) > 1 and sys.argv[1].lower() == "integration"
    stages = get_stages(is_integration)

    for title, command in stages:
        returncode = run_stage(title, command)
        if returncode != 0:
            print(f"\nValidation failed at stage: {title} (exit code {returncode})")
            sys.exit(returncode)
    print("\nAll validation stages passed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
