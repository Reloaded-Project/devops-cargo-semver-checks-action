#!/usr/bin/env python3
"""Resolve which workspace packages should be passed to cargo-semver-checks.

Reads action inputs, runs ``cargo metadata``, filters packages, and writes
outputs for package selection and ``rust-cache`` workspace mapping.

# Environment variables
- ``INPUT_MANIFEST_PATH``: Optional path to a ``Cargo.toml`` manifest.
- ``INPUT_PACKAGE``: Comma-separated package names to check (empty = all).
- ``INPUT_EXCLUDE``: Comma-separated package names to exclude.
- ``INPUT_SKIP_UNPUBLISHED``: Skip packages not on crates.io (``true``/``false``).
- ``INPUT_FAIL_IF_NO_PUBLISHED_PACKAGES``: Fail when no packages remain
  (``true``/``false``).
- ``INPUT_BASELINE_VERSION``, ``INPUT_BASELINE_REV``, ``INPUT_BASELINE_ROOT``:
  Baseline hints. When any is set the registry check is skipped because the
  baseline is provided directly.
- ``GITHUB_OUTPUT``: Path to the GitHub Actions output file.

# Errors
- Exits with code 1 when ``fail_if_empty`` is ``true`` and no effective
  packages remain after filtering.
"""

from dataclasses import dataclass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


@dataclass
class ActionInputs:
    manifest_path: str
    package_input: str
    exclude_input: str
    skip_unpublished: bool
    fail_if_empty: bool
    baseline_version: str
    baseline_rev: str
    baseline_root: str
    github_output: str


@dataclass
class PackageList:
    effective_packages: list[str]
    skipped_packages: list[str]


@dataclass
class CargoPackage:
    id: str
    name: str
    publish: list[str] | bool | None


@dataclass
class CargoMetadata:
    workspace_members: list[str]
    packages: list[CargoPackage]
    workspace_root: str = ""


def main() -> int:
    inputs = _read_inputs()
    metadata = _cargo_metadata(inputs.manifest_path)
    rust_cache_workspaces = _rust_cache_workspaces(metadata)

    packages = _parse_csv(inputs.package_input)
    excludes = _parse_csv(inputs.exclude_input)

    result = _resolve_packages(packages, excludes, metadata)

    has_baseline = bool(
        inputs.baseline_version or inputs.baseline_rev or inputs.baseline_root
    )
    if inputs.skip_unpublished and not has_baseline:
        result = _filter_published(result)

    effective_csv = ",".join(result.effective_packages)
    skipped_csv = ",".join(result.skipped_packages)

    if not effective_csv:
        if inputs.fail_if_empty:
            print("No packages remain after semver filtering.", file=sys.stderr)
            if skipped_csv:
                print(f"Skipped packages: {skipped_csv}", file=sys.stderr)
            return 1

        print(
            "No packages remain after semver filtering. "
            "Skipping upstream cargo-semver-checks action."
        )
        if skipped_csv:
            print(f"Skipped packages: {skipped_csv}")

        _write_output(
            inputs.github_output,
            [
                "did_run=false",
                "effective_packages=",
                f"skipped_packages={skipped_csv}",
                f"rust_cache_workspaces={rust_cache_workspaces}",
            ],
        )
        return 0

    print(f"Effective packages: {effective_csv}")
    if skipped_csv:
        print(f"Skipped packages: {skipped_csv}")

    _write_output(
        inputs.github_output,
        [
            "did_run=true",
            f"effective_packages={effective_csv}",
            f"skipped_packages={skipped_csv}",
            f"rust_cache_workspaces={rust_cache_workspaces}",
        ],
    )
    return 0


def _read_inputs() -> ActionInputs:
    return ActionInputs(
        manifest_path=os.environ.get("INPUT_MANIFEST_PATH", ""),
        package_input=os.environ.get("INPUT_PACKAGE", ""),
        exclude_input=os.environ.get("INPUT_EXCLUDE", ""),
        skip_unpublished=os.environ.get("INPUT_SKIP_UNPUBLISHED", "true") == "true",
        fail_if_empty=os.environ.get("INPUT_FAIL_IF_NO_PUBLISHED_PACKAGES", "false")
        == "true",
        baseline_version=os.environ.get("INPUT_BASELINE_VERSION", ""),
        baseline_rev=os.environ.get("INPUT_BASELINE_REV", ""),
        baseline_root=os.environ.get("INPUT_BASELINE_ROOT", ""),
        github_output=os.environ.get("GITHUB_OUTPUT", "/dev/null"),
    )


def _cargo_metadata(manifest_path: str) -> CargoMetadata:
    """Run ``cargo metadata`` and return the parsed JSON output.

    # Arguments
    - `manifest_path`: Optional path to a ``Cargo.toml``. When empty,
      ``cargo`` auto-discovers the manifest.

    # Errors
    - Propagates `subprocess.CalledProcessError` if ``cargo`` exits non-zero.
    """
    args = ["cargo", "metadata", "--format-version", "1", "--no-deps"]
    if manifest_path:
        args += ["--manifest-path", manifest_path]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    raw = json.loads(result.stdout)
    packages = [
        CargoPackage(
            id=pkg["id"],
            name=pkg["name"],
            publish=pkg.get("publish", None),
        )
        for pkg in raw["packages"]
    ]
    return CargoMetadata(
        workspace_members=raw["workspace_members"],
        packages=packages,
        workspace_root=raw.get("workspace_root", ""),
    )


def _rust_cache_workspaces(metadata: CargoMetadata) -> str:
    """Return the ``rust-cache`` ``workspaces`` entry for semver runs.

    The upstream action writes current-build artifacts to
    ``$GITHUB_WORKSPACE/semver-checks/target``. This maps ``rust-cache`` to
    that directory.

    # Returns
    - A ``workspaces`` entry in the form ``workspace -> target``.
    """
    github_workspace = os.path.realpath(os.environ.get("GITHUB_WORKSPACE", os.getcwd()))
    # Use the real workspace root so nested workspaces map correctly.
    workspace_root = os.path.realpath(metadata.workspace_root or github_workspace)
    semver_target_root = os.path.join(github_workspace, "semver-checks", "target")

    workspace_rel = _relative_posix_path(workspace_root, github_workspace)
    semver_target_rel = _relative_posix_path(semver_target_root, workspace_root)
    return f"{workspace_rel} -> {semver_target_rel}"


def _relative_posix_path(path: str, start: str) -> str:
    """Return a relative path normalized to forward slashes."""
    return os.path.relpath(path, start).replace(os.sep, "/")


def _parse_csv(raw: str) -> list[str]:
    """Split a comma-separated string into trimmed, non-empty items.

    # Arguments
    - `raw`: Comma-separated values. Empty string produces an empty list.
    """
    return [item for item in (s.strip() for s in raw.split(",")) if item]


def _resolve_packages(
    packages: list[str], excludes: list[str], metadata: CargoMetadata
) -> PackageList:
    """Determine which packages should be included for semver checking.

    # Arguments
    - `packages`: Requested package names (empty = auto-discover from workspace).
    - `excludes`: Package names to exclude (applied only during auto-discovery).
    - `metadata`: Parsed output of `cargo metadata --format-version 1`.

    # Returns
    - PackageList with `effective_packages` and `skipped_packages` lists.

    # Behavior
    - When `packages` is empty, all workspace members not in `excludes` are
      considered.
    - Packages are skipped when absent from the metadata or when `publish` is
      `false` or an empty list.
    - Duplicate package names are silently de-duplicated.
    """
    requested_excludes = set(excludes)
    package_by_id = {pkg.id: pkg for pkg in metadata.packages}

    if packages:
        candidates = packages
    else:
        candidates = [
            package_by_id[pkg_id].name
            for pkg_id in metadata.workspace_members
            if pkg_id in package_by_id
        ]
        candidates = [name for name in candidates if name not in requested_excludes]

    seen: set[str] = set()
    effective: list[str] = []
    skipped: list[str] = []

    for name in candidates:
        if name in seen:
            continue
        seen.add(name)

        pkg = next((p for p in metadata.packages if p.name == name), None)
        if pkg is None:
            skipped.append(name)
            continue

        if pkg.publish is False or pkg.publish == []:
            skipped.append(name)
            continue

        effective.append(name)

    return PackageList(effective_packages=effective, skipped_packages=skipped)


def _filter_published(payload: PackageList) -> PackageList:
    """Remove unpublished or fully-yanked packages from the effective list.

    # Arguments
    - `payload`: PackageList with `effective_packages` and `skipped_packages` lists.

    # Returns
    - PackageList with updated `effective_packages` and `skipped_packages`.
    """
    effective: list[str] = []
    skipped = list(payload.skipped_packages)

    for crate in payload.effective_packages:
        if _crate_has_non_yanked_release(crate):
            effective.append(crate)
        else:
            skipped.append(crate)

    return PackageList(effective_packages=effective, skipped_packages=skipped)


def _crate_has_non_yanked_release(crate: str) -> bool:
    """Check whether a crate has at least one non-yanked version on crates.io.

    # Arguments
    - `crate`: Crate name to look up.

    # Returns
    - `True` if the crate has at least one non-yanked published version.
    - `False` if the crate is not found (HTTP 404) or all versions are yanked.

    # Errors
    - Re-raises any HTTP error that is not a 404.
    - Propagates network-level errors from `urllib.request.urlopen`.
    """
    url = f"https://index.crates.io/{_sparse_index_path(crate)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Reloaded-Project/devops-cargo-semver-checks-action"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise

    for line in body.splitlines():
        if not line.strip():
            continue
        version = json.loads(line)
        if not version.get("yanked", False):
            return True
    return False


def _sparse_index_path(crate: str) -> str:
    """Compute the crates.io sparse-index path for a crate name.

    # Arguments
    - `crate`: Crate name (non-empty string).

    # Returns
    - The relative path component used by the crates.io HTTP index.
    """
    if len(crate) == 1:
        return f"1/{crate}"
    if len(crate) == 2:
        return f"2/{crate}"
    if len(crate) == 3:
        return f"3/{crate[0]}/{crate}"
    return f"{crate[:2]}/{crate[2:4]}/{crate}"


def _write_output(path: str, lines: list[str]) -> None:
    """Append ``key=value`` lines to the GitHub Actions output file.

    # Arguments
    - `path`: File path (typically ``$GITHUB_OUTPUT``).
    - `lines`: Lines to append, each already formatted as ``key=value``.
    """
    with open(path, "a") as fh:
        for line in lines:
            fh.write(f"{line}\n")


if __name__ == "__main__":
    sys.exit(main())
