"""Architecture boundary and dependency validator for RouteForge.

Scans Python files under src/routeforge to enforce module boundary rules
using standard library AST parsing.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# Framework/ORM packages prohibited in domain core modules
PROHIBITED_THIRD_PARTY_CORE: set[str] = {
    "fastapi",
    "pydantic",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "redis",
    "openai",
    "anthropic",
    "openrouter",
}

# Framework/SDK packages prohibited in storage package
PROHIBITED_THIRD_PARTY_STORAGE: set[str] = {
    "fastapi",
    "uvicorn",
    "openai",
    "anthropic",
    "openrouter",
}

# Framework/SDK packages prohibited in gateway package
PROHIBITED_THIRD_PARTY_GATEWAY: set[str] = {
    "uvicorn",
    "httpx",
    "openai",
    "anthropic",
    "openrouter",
}


@dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    """Represents a single architectural import rule violation."""

    source_file: Path
    line_number: int
    imported_module: str
    rule_description: str


def _get_imported_modules(node: ast.AST) -> list[tuple[int, str]]:
    """Extract line numbers and target module names from import/importfrom nodes."""
    imports: list[tuple[int, str]] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            imports.append((node.lineno, alias.name))
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            imports.append((node.lineno, node.module))
    return imports


def check_architecture_dependencies(src_dir: Path) -> list[ArchitectureViolation]:
    """Scan src/routeforge package files for prohibited architecture dependency imports."""
    violations: list[ArchitectureViolation] = []
    routeforge_root = src_dir / "routeforge"

    if not routeforge_root.exists() or not routeforge_root.is_dir():
        print(f"Error: RouteForge source directory '{routeforge_root}' not found.")
        sys.exit(1)

    py_files = sorted(routeforge_root.rglob("*.py"))

    for py_file in py_files:
        rel_path = py_file.relative_to(routeforge_root)
        parts = rel_path.parts

        if not parts:
            continue

        package_submodule = parts[0]

        try:
            with open(py_file, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))
        except Exception as err:
            violations.append(
                ArchitectureViolation(
                    source_file=py_file,
                    line_number=1,
                    imported_module="<syntax_error>",
                    rule_description=f"Failed to parse AST: {err}",
                )
            )
            continue

        for node in ast.walk(tree):
            for lineno, mod_name in _get_imported_modules(node):
                root_pkg = mod_name.split(".")[0]

                # 1. Prohibited Third-Party Checks
                if package_submodule == "gateway":
                    if root_pkg in PROHIBITED_THIRD_PARTY_GATEWAY:
                        violations.append(
                            ArchitectureViolation(
                                source_file=py_file,
                                line_number=lineno,
                                imported_module=mod_name,
                                rule_description=(
                                    f"Gateway package must not import prohibited '{mod_name}'."
                                ),
                            )
                        )
                elif package_submodule == "storage":
                    if root_pkg in PROHIBITED_THIRD_PARTY_STORAGE:
                        violations.append(
                            ArchitectureViolation(
                                source_file=py_file,
                                line_number=lineno,
                                imported_module=mod_name,
                                rule_description=(
                                    f"Storage package must not import prohibited '{mod_name}'."
                                ),
                            )
                        )
                else:
                    if root_pkg in PROHIBITED_THIRD_PARTY_CORE:
                        violations.append(
                            ArchitectureViolation(
                                source_file=py_file,
                                line_number=lineno,
                                imported_module=mod_name,
                                rule_description=(
                                    f"Core domain module '{package_submodule}' must not import "
                                    f"prohibited framework/SDK '{mod_name}'."
                                ),
                            )
                        )

                # 2. Package Boundary Rules
                if mod_name.startswith("routeforge."):
                    target_pkg = mod_name.split(".")[1] if len(mod_name.split(".")) > 1 else ""

                    if package_submodule not in ("gateway", "storage") and target_pkg in (
                        "gateway",
                        "storage",
                    ):
                        violations.append(
                            ArchitectureViolation(
                                source_file=py_file,
                                line_number=lineno,
                                imported_module=mod_name,
                                rule_description=(
                                    f"Core module '{package_submodule}' must not import "
                                    f"higher-level package '{mod_name}'."
                                ),
                            )
                        )

                    if package_submodule == "storage" and target_pkg == "gateway":
                        violations.append(
                            ArchitectureViolation(
                                source_file=py_file,
                                line_number=lineno,
                                imported_module=mod_name,
                                rule_description=(
                                    f"Storage package must not import gateway package '{mod_name}'."
                                ),
                            )
                        )

                    if package_submodule == "contracts":
                        if target_pkg in (
                            "registries",
                            "providers",
                            "routing",
                            "gateway",
                            "storage",
                        ):
                            violations.append(
                                ArchitectureViolation(
                                    source_file=py_file,
                                    line_number=lineno,
                                    imported_module=mod_name,
                                    rule_description=(
                                        f"Contracts package must not import '{mod_name}'."
                                    ),
                                )
                            )

                    elif package_submodule == "registries":
                        if target_pkg in ("providers", "routing", "gateway", "storage"):
                            violations.append(
                                ArchitectureViolation(
                                    source_file=py_file,
                                    line_number=lineno,
                                    imported_module=mod_name,
                                    rule_description=(
                                        f"Registries package must not import '{mod_name}'."
                                    ),
                                )
                            )

                    elif package_submodule == "providers":
                        if target_pkg in ("registries", "routing", "gateway", "storage"):
                            violations.append(
                                ArchitectureViolation(
                                    source_file=py_file,
                                    line_number=lineno,
                                    imported_module=mod_name,
                                    rule_description=(
                                        f"Providers package must not import '{mod_name}'."
                                    ),
                                )
                            )

                    elif package_submodule == "routing":
                        if target_pkg in ("providers", "registries", "gateway", "storage"):
                            violations.append(
                                ArchitectureViolation(
                                    source_file=py_file,
                                    line_number=lineno,
                                    imported_module=mod_name,
                                    rule_description=(
                                        f"Routing package must not import '{mod_name}'."
                                    ),
                                )
                            )

    return sorted(violations, key=lambda v: (str(v.source_file), v.line_number, v.imported_module))


def main() -> None:
    """Run architecture dependency validation and exit with 0 on success, 1 on failure."""
    repo_root = Path(__file__).resolve().parent.parent
    src_dir = repo_root / "src"

    print("=== RouteForge Architecture Validation ===")
    print(f"Scanning source directory: {src_dir / 'routeforge'}")

    violations = check_architecture_dependencies(src_dir)

    if violations:
        print(f"\nFound {len(violations)} architecture rule violation(s):")
        for v in violations:
            print(f"  {v.source_file}:{v.line_number}: [{v.imported_module}] {v.rule_description}")
        print("\nArchitecture validation FAILED.")
        sys.exit(1)

    print("\nArchitecture dependency boundaries are VALID.")
    sys.exit(0)


if __name__ == "__main__":
    main()
