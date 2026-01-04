#!/usr/bin/env python3
"""
Version Compatibility Checker

Validates that all service versions match the SERVICE_COMPATIBILITY.md matrix.
Run this as part of CI/CD to prevent version drift.

Usage:
    python scripts/check_version_compatibility.py
    python scripts/check_version_compatibility.py --verbose
    python scripts/check_version_compatibility.py --fix  # Show what needs fixing

Exit codes:
    0 - All versions match
    1 - Version mismatch detected
    2 - Parse error
"""

import re
import sys
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

# Use Any for complex nested dict to avoid type checking issues
VersionDict = dict[str, Any]


class VersionSpec(NamedTuple):
    """A version specification from a source file."""
    source: str
    name: str
    version: str
    line: int | None = None


class VersionMismatch(NamedTuple):
    """A version mismatch between two sources."""
    name: str
    expected_source: str
    expected_version: str
    actual_source: str
    actual_version: str


def parse_compatibility_md(path: Path) -> VersionDict:
    """Parse SERVICE_COMPATIBILITY.md and extract version mappings."""
    content = path.read_text()
    versions: VersionDict = {
        "services": {},
        "python": {},
        "images": {},
    }
    
    # Parse service table: | Service | Docker Image | Version | Python Library | Library Version |
    service_pattern = re.compile(
        r"\|\s*(\w+)\s*\|\s*`([^`]+)`\s*\|\s*([\d.]+[^\s|]*)\s*\|\s*`([^`]+)`\s*\|\s*([\d.]+)",
        re.MULTILINE
    )
    for match in service_pattern.finditer(content):
        service_name = match.group(1).lower()
        service_info: dict[str, str] = {
            "image": match.group(2),
            "image_version": match.group(3),
            "library": match.group(4),
            "library_version": match.group(5),
        }
        versions["services"][service_name] = service_info  # type: ignore[index]
    
    # Parse Python dependencies table: | Library | Version | Purpose |
    python_pattern = re.compile(
        r"\|\s*`([^`]+)`\s*\|\s*([\d.]+)\s*\|\s*[^|]+\s*\|",
        re.MULTILINE
    )
    for match in python_pattern.finditer(content):
        lib_name = match.group(1).lower()
        if lib_name not in ["library"]:  # Skip header
            versions["python"][lib_name] = match.group(2)  # type: ignore[index]
    
    # Parse Base Images table: | Image | Version | Used In |
    image_pattern = re.compile(
        r"\|\s*`([^`]+)`\s*\|\s*([\d.]+-?\w*)\s*\|\s*([^|]+)\s*\|",
        re.MULTILINE
    )
    for match in image_pattern.finditer(content):
        image_name = match.group(1).lower()
        if image_name not in ["image"]:  # Skip header
            versions["images"][image_name] = match.group(2)  # type: ignore[index]
    
    return versions


def parse_pyproject_toml(path: Path) -> list[VersionSpec]:
    """Extract pinned versions from pyproject.toml."""
    content = path.read_text()
    data = tomllib.loads(content)
    specs: list[VersionSpec] = []
    
    # Parse dependencies
    deps = data.get("project", {}).get("dependencies", [])
    for dep in deps:
        match = re.match(r"([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?[=<>~!]+([\d.]+)", dep)
        if match:
            name = match.group(1).lower().replace("-", "_").replace("_", "-")
            version = match.group(2)
            specs.append(VersionSpec(str(path), name, version))
    
    # Parse optional-dependencies
    opt_deps = data.get("project", {}).get("optional-dependencies", {})
    for group_deps in opt_deps.values():
        for dep in group_deps:
            match = re.match(r"([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?[=<>~!]+([\d.]+)", dep)
            if match:
                name = match.group(1).lower().replace("-", "_").replace("_", "-")
                version = match.group(2)
                specs.append(VersionSpec(str(path), name, version))
    
    # Parse dependency-groups
    dep_groups = data.get("dependency-groups", {})
    for group_deps in dep_groups.values():
        for dep in group_deps:
            match = re.match(r"([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?[=<>~!]+([\d.]+)", dep)
            if match:
                name = match.group(1).lower().replace("-", "_").replace("_", "-")
                version = match.group(2)
                specs.append(VersionSpec(str(path), name, version))
    
    return specs


def parse_dockerfile(path: Path) -> list[VersionSpec]:
    """Extract FROM image versions from Dockerfile."""
    content = path.read_text()
    specs: list[VersionSpec] = []
    
    for i, line in enumerate(content.split("\n"), 1):
        match = re.match(r"FROM\s+([^:]+):([^\s]+)", line)
        if match:
            image = match.group(1)
            version = match.group(2)
            specs.append(VersionSpec(str(path), image, version, i))
    
    return specs


def parse_docker_compose(path: Path) -> list[VersionSpec]:
    """Extract image versions from docker-compose.yml."""
    content = path.read_text()
    specs: list[VersionSpec] = []
    
    # Match image: name:version patterns
    for i, line in enumerate(content.split("\n"), 1):
        match = re.search(r"image:\s*([^:]+):([^\s]+)", line)
        if match:
            image = match.group(1)
            version = match.group(2)
            if not version.startswith("$"):  # Skip variable references
                specs.append(VersionSpec(str(path), image, version, i))
    
    return specs


def check_for_floating_versions(specs: list[VersionSpec]) -> list[str]:
    """Check for floating version specifiers."""
    issues = []
    floating_patterns = ["latest", "stable", "^", "~", ">=", ">", "*"]
    
    # Local images that are built from source (not from registries)
    local_images = ["gofr-base", "gofr-iq-base", "gofr-iq-prod", "gofr-chroma", "gofr-neo4j", "gofr-iq-vault"]
    
    for spec in specs:
        # Skip local build images
        image_base = spec.name.split("/")[-1].lower()
        if image_base in local_images:
            continue
        
        for pattern in floating_patterns:
            if pattern in spec.version:
                loc = f"{spec.source}:{spec.line}" if spec.line else spec.source
                issues.append(f"Floating version '{spec.version}' for {spec.name} in {loc}")
    
    return issues


def validate_versions(
    compat_versions: VersionDict,
    pyproject_specs: list[VersionSpec],
    dockerfile_specs: list[VersionSpec],
) -> list[VersionMismatch]:
    """Validate all versions against SERVICE_COMPATIBILITY.md."""
    mismatches: list[VersionMismatch] = []
    
    # Check service library versions
    for service, info in compat_versions.get("services", {}).items():
        # info is dict[str, str], so we can access keys directly
        lib_name = info.get("library", "").lower()
        expected_version = info.get("library_version", "")
        
        for spec in pyproject_specs:
            # Normalize names for comparison
            spec_name = spec.name.lower().replace("-", "_")
            lib_name_normalized = lib_name.replace("-", "_")
            
            if spec_name == lib_name_normalized and spec.version != expected_version:
                mismatches.append(VersionMismatch(
                    name=lib_name,
                    expected_source="SERVICE_COMPATIBILITY.md",
                    expected_version=expected_version,
                    actual_source=spec.source,
                    actual_version=spec.version,
                ))
    
    # Check Docker image versions
    for image_name, expected_version in compat_versions.get("images", {}).items():
        for spec in dockerfile_specs:
            # Match by image base name
            spec_base = spec.name.split("/")[-1].lower()
            if spec_base == image_name or image_name in spec.name.lower():
                if spec.version != expected_version:
                    mismatches.append(VersionMismatch(
                        name=spec.name,
                        expected_source="SERVICE_COMPATIBILITY.md",
                        expected_version=expected_version,
                        actual_source=f"{spec.source}:{spec.line}" if spec.line else spec.source,
                        actual_version=spec.version,
                    ))
    
    return mismatches


def main() -> int:
    """Main entry point."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    
    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Check for SERVICE_COMPATIBILITY.md
    compat_file = project_root / "SERVICE_COMPATIBILITY.md"
    if not compat_file.exists():
        print(f"ERROR: {compat_file} not found")
        print("Create this file using the version_policy.md template")
        return 2
    
    print("=" * 70)
    print("Version Compatibility Check")
    print("=" * 70)
    
    # Parse all sources
    try:
        compat_versions = parse_compatibility_md(compat_file)
        if verbose:
            print(f"\nParsed {len(compat_versions['services'])} services from SERVICE_COMPATIBILITY.md")
            print(f"Parsed {len(compat_versions['python'])} Python deps from SERVICE_COMPATIBILITY.md")
            print(f"Parsed {len(compat_versions['images'])} images from SERVICE_COMPATIBILITY.md")
    except Exception as e:
        print(f"ERROR: Failed to parse {compat_file}: {e}")
        return 2
    
    # Collect all version specs
    pyproject_specs: list[VersionSpec] = []
    dockerfile_specs: list[VersionSpec] = []
    
    # Parse pyproject.toml files
    pyproject_files = [
        project_root / "pyproject.toml",
        project_root / "lib" / "gofr-common" / "pyproject.toml",
    ]
    for pf in pyproject_files:
        if pf.exists():
            specs = parse_pyproject_toml(pf)
            pyproject_specs.extend(specs)
            if verbose:
                print(f"Parsed {len(specs)} deps from {pf.relative_to(project_root)}")
    
    # Parse Dockerfiles
    docker_dir = project_root / "docker"
    for df in docker_dir.glob("Dockerfile.*"):
        specs = parse_dockerfile(df)
        dockerfile_specs.extend(specs)
        if verbose:
            print(f"Parsed {len(specs)} images from {df.relative_to(project_root)}")
    
    # Check for floating versions
    all_specs = pyproject_specs + dockerfile_specs
    floating_issues = check_for_floating_versions(all_specs)
    
    # Validate against compatibility matrix
    mismatches = validate_versions(compat_versions, pyproject_specs, dockerfile_specs)
    
    # Report results
    print()
    if floating_issues:
        print("FLOATING VERSION VIOLATIONS:")
        for issue in floating_issues:
            print(f"  ❌ {issue}")
        print()
    
    if mismatches:
        print("VERSION MISMATCHES:")
        for m in mismatches:
            print(f"  ❌ {m.name}:")
            print(f"      Expected: {m.expected_version} (from {m.expected_source})")
            print(f"      Actual:   {m.actual_version} (in {m.actual_source})")
        print()
    
    total_issues = len(floating_issues) + len(mismatches)
    
    if total_issues == 0:
        print("✅ All versions are compatible and pinned correctly")
        return 0
    else:
        print(f"❌ Found {total_issues} issue(s)")
        print("\nTo fix:")
        print("  1. Update SERVICE_COMPATIBILITY.md with correct versions")
        print("  2. Update pyproject.toml files to match")
        print("  3. Update Dockerfiles to match")
        print("  4. Run this check again")
        return 1


if __name__ == "__main__":
    sys.exit(main())
