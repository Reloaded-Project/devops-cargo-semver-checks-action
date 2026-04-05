# scripts

[`filter_packages.py`](filter_packages.py) resolves and filters workspace
packages for the wrapper before calling the upstream
[cargo-semver-checks-action](https://github.com/obi1kanobi/cargo-semver-checks-action).

## How it works

`filter_packages.py` is called by the GitHub Action's "Resolve packages to
check" step. It reads action inputs from environment variables and runs the
following steps in order:

1. Run `cargo metadata --format-version 1 --no-deps` to list workspace
   packages.
2. Parse the `package` and `exclude` action inputs (comma-separated strings)
   into lists.
3. Resolve which packages to check:
   - If packages were explicitly requested, use those.
   - Otherwise, auto-discover all workspace members and remove any listed in
     `exclude`.
   - Skip packages that don't exist in the metadata or have `publish = false`.
4. Optionally filter out unpublished crates:
    - Query the crates.io sparse index for each remaining package.
    - Move packages with no non-yanked published version to the skipped list.
    - Skip this step when `baseline-version`, `baseline-rev`, or
      `baseline-root` is set.
5. Derive the `rust-cache` workspace mapping for the upstream action's
   `semver-checks/target` directory.
6. Write `effective_packages`, `skipped_packages`, and
   `rust_cache_workspaces` to `$GITHUB_OUTPUT`.

If no effective packages remain and `fail-if-no-published-packages` is `true`,
the script exits with code 1. Otherwise it writes `did_run=false` and exits 0.

## Running tests

```sh
python3 -m unittest scripts/test_filter_packages.py -v
```

This runs 21 unit tests covering every function in `filter_packages.py`,
including the full `main()` pipeline with mocked `cargo` and network calls.

## Integration tests

End-to-end tests that exercise the full GitHub Action live in
[`tests/`](../tests/) alongside their fixtures. These are run by the CI
workflow (`.github/workflows/test-cargo-semver-checks-workflow.yml`) and are
not intended to be run locally.
