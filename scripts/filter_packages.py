#!/usr/bin/env python3
"""Resolve which workspace packages should be passed to cargo-semver-checks.

Reads action inputs from environment variables, runs ``cargo metadata``, then
filters packages through several steps to produce the final list of effective
and skipped packages. Results are written to ``GITHUB_OUTPUT``.

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

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


def main() -> int:
    manifest_path = os.environ.get("INPUT_MANIFEST_PATH", "")
    package_input = os.environ.get("INPUT_PACKAGE", "")
    exclude_input = os.environ.get("INPUT_EXCLUDE", "")
    skip_unpublished = os.environ.get("INPUT_SKIP_UNPUBLISHED", "true")
    fail_if_empty = os.environ.get("INPUT_FAIL_IF_NO_PUBLISHED_PACKAGES", "false")
    baseline_version = os.environ.get("INPUT_BASELINE_VERSION", "")
    baseline_rev = os.environ.get("INPUT_BASELINE_REV", "")
    baseline_root = os.environ.get("INPUT_BASELINE_ROOT", "")
    github_output = os.environ.get("GITHUB_OUTPUT", "/dev/null")

    metadata = _cargo_metadata(manifest_path)

    packages = _parse_csv(package_input)
    excludes = _parse_csv(exclude_input)

    result = _resolve_packages(packages, excludes, metadata)

    has_baseline = bool(baseline_version or baseline_rev or baseline_root)
    if skip_unpublished == "true" and not has_baseline:
        result = _filter_published(result)

    effective_csv = ",".join(result["effective_packages"])
    skipped_csv = ",".join(result["skipped_packages"])

    if not effective_csv:
        if fail_if_empty == "true":
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
            github_output,
            [
                "did_run=false",
                "effective_packages=",
                f"skipped_packages={skipped_csv}",
            ],
        )
        return 0

    print(f"Effective packages: {effective_csv}")
    if skipped_csv:
        print(f"Skipped packages: {skipped_csv}")

    _write_output(
        github_output,
        [
            "did_run=true",
            f"effective_packages={effective_csv}",
            f"skipped_packages={skipped_csv}",
        ],
    )
    return 0


def _parse_csv(raw: str) -> list[str]:
    """Split a comma-separated string into trimmed, non-empty items.

    # Arguments
    - `raw`: Comma-separated values. Empty string produces an empty list.
    """
    return [item for item in (s.strip() for s in raw.split(",")) if item]


def _cargo_metadata(manifest_path: str) -> dict:
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
    return json.loads(result.stdout)


def _resolve_packages(packages: list[str], excludes: list[str], metadata: dict) -> dict:
    """Determine which packages should be included for semver checking.

    # Arguments
    - `packages`: Requested package names (empty = auto-discover from workspace).
    - `excludes`: Package names to exclude (applied only during auto-discovery).
    - `metadata`: Parsed output of `cargo metadata --format-version 1`.

    # Returns
    - Dict with keys `effective_packages` and `skipped_packages`, each a list
      of package name strings.

    # Behavior
    - When `packages` is empty, all workspace members not in `excludes` are
      considered.
    - Packages are skipped when absent from the metadata or when `publish` is
      `false` or an empty list.
    - Duplicate package names are silently de-duplicated.
    """
    requested_excludes = set(excludes)
    package_by_id = {pkg["id"]: pkg for pkg in metadata["packages"]}

    if packages:
        candidates = packages
    else:
        candidates = [
            package_by_id[pkg_id]["name"]
            for pkg_id in metadata["workspace_members"]
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

        pkg = next((p for p in metadata["packages"] if p["name"] == name), None)
        if pkg is None:
            skipped.append(name)
            continue

        publish = pkg.get("publish", None)
        if publish is False or publish == []:
            skipped.append(name)
            continue

        effective.append(name)

    return {"effective_packages": effective, "skipped_packages": skipped}


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


def _filter_published(payload: dict) -> dict:
    """Remove unpublished or fully-yanked packages from the effective list.

    # Arguments
    - `payload`: Dict with `effective_packages` and `skipped_packages` lists.

    # Returns
    - Dict with updated `effective_packages` and `skipped_packages`.
    """
    effective: list[str] = []
    skipped = list(payload.get("skipped_packages", []))

    for crate in payload.get("effective_packages", []):
        if _crate_has_non_yanked_release(crate):
            effective.append(crate)
        else:
            skipped.append(crate)

    return {"effective_packages": effective, "skipped_packages": skipped}


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
