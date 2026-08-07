"""Configuration validation script for RouteForge.

Loads and validates local model definitions and feature policies from configuration directories.
"""

import sys
from pathlib import Path

from routeforge.contracts.policies import PolicyStatus
from routeforge.registries.errors import RegistryConfigurationError
from routeforge.registries.file_loader import load_registry_snapshot


def main() -> None:
    """Load configuration snapshot from config/ and validate cross-references."""
    repo_root = Path(__file__).resolve().parent.parent
    models_dir = repo_root / "config" / "models"
    policies_dir = repo_root / "config" / "policies"

    print("=== RouteForge Configuration Validation ===")
    print(f"Models directory:   {models_dir}")
    print(f"Policies directory: {policies_dir}")

    try:
        snapshot = load_registry_snapshot(
            models_directory=models_dir,
            policies_directory=policies_dir,
        )
    except RegistryConfigurationError as err:
        print("\nConfiguration validation FAILED with issues:")
        print(str(err))
        sys.exit(1)
    except Exception as err:
        print(f"\nUnexpected error during configuration loading: {err}")
        sys.exit(1)

    all_models = snapshot.models.list_all()
    all_policies = snapshot.policies.list_all()
    active_policies = [p for p in all_policies if p.status == PolicyStatus.ACTIVE]

    print(f"\nLoaded {len(all_models)} model definition(s).")
    print(f"Loaded {len(all_policies)} feature policy(ies).")
    print(f"Found {len(active_policies)} active feature policy(ies).")
    print("\nConfiguration snapshot is VALID.")
    sys.exit(0)


if __name__ == "__main__":
    main()
