# scripts

[`filter_packages.py`](filter_packages.py) resolves and filters workspace
packages for the `cargo-semver-checks-action` wrapper before handing off to
the upstream [cargo-semver-checks-action](https://github.com/obi1kanobi/cargo-semver-checks-action).

## How it works

`filter_packages.py` is called by the GitHub Action's "Resolve packages to
check" step. It reads action inputs from environment variables and runs the
following steps in order:

1. Run `cargo metadata --format-version 1 --no-deps` to get the full list of
   workspace packages.
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
   - This step is skipped when a baseline is explicitly provided
     (`baseline-version`, `baseline-rev`, or `baseline-root`), because the
     comparison target is already known.
5. Write `effective_packages` and `skipped_packages` as comma-separated strings
   to `$GITHUB_OUTPUT`.

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
