<div align="center">
  <a href="https://github.com/Reloaded-Project/devops-cargo-semver-checks-action"
     target="_blank">
    <img src="assets/reloaded-logo.png" alt="Logo" width="100" height="100">
  </a>

  <h1 align="center">Reloaded Cargo Semver Checks GitHub Action</h1>

  <p align="center">
    <a href="LICENSE">
      <img src="https://img.shields.io/badge/License-MIT-blue.svg"
           alt="License">
    </a>
  </p>
</div>

This action wraps `obi1kenobi/cargo-semver-checks-action` with three extras:

- Built-in `actions/checkout`
- `Swatinem/rust-cache` for Cargo caching
- Skips unpublished crates so new workspaces do not fail

Intended for Rust workspaces that want the upstream semver checker with cache
setup and unpublished-crate filtering.

## Features

- Wraps `actions/checkout@v6`
- Runs the official `cargo-semver-checks` action
- Installs and reuses a Rust toolchain by default
- Restores Cargo registry, git, and semver build artifacts with `rust-cache`
- Derives the Cargo workspace root from `manifest-path` when needed
- Skips `publish = false` crates
- Skips unpublished crates by default
- Exposes filtered package lists as action outputs

## Usage

The action can stand on its own. A separate checkout step is not required.

```yaml
- name: Run semver checks for the async surface
  uses: Reloaded-Project/devops-cargo-semver-checks-action@v1
  with:
    manifest-path: src/Cargo.toml
    package: llm-coding-tools-core
    feature-group: only-explicit-features
    features: tokio
    rust-target: x86_64-unknown-linux-gnu
    prefix-key: core-async-tokio
    rust-cache-key-suffix: core-async-tokio
```

## Matrix Usage

Using a job matrix is the recommended way to cover several API surfaces.

```yaml
jobs:
  semver-checks:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - name: core async tokio
            package: llm-coding-tools-core
            feature_group: only-explicit-features
            features: tokio
            prefix_key: core-async-tokio
          - name: core blocking
            package: llm-coding-tools-core
            feature_group: only-explicit-features
            features: blocking
            prefix_key: core-blocking
    name: Semver (${{ matrix.name }})
    steps:
      - uses: Reloaded-Project/devops-cargo-semver-checks-action@v1
        with:
          manifest-path: src/Cargo.toml
          package: ${{ matrix.package }}
          feature-group: ${{ matrix.feature_group }} # see below
          features: ${{ matrix.features }}
          rust-target: x86_64-unknown-linux-gnu
          prefix-key: ${{ matrix.prefix_key }}
          rust-cache-key-suffix: ${{ matrix.prefix_key }}
```

If your workflow already checked out the repository, set `use-checkout: false`.

## Inputs

### Wrapper Inputs

| Input              | Default | Notes                                |
| ------------------ | ------- | ------------------------------------ |
| `skip-unpublished` | `true`  | Skip crates missing from `crates.io` |
| `filter-only`      | `false` | Only resolve/filter packages         |

### Checkout Inputs (`actions/checkout`)

All inputs are prefixed with `checkout-` and forwarded directly. When
`baseline-rev` is set, `fetch-depth` is overridden to `0` for full history.

| Input                                | Default                    | Notes                                           |
| ------------------------------------ | -------------------------- | ----------------------------------------------- |
| `use-checkout`                       | `true`                     | Run `actions/checkout@v6`                       |
| `checkout-repository`                | `${{ github.repository }}` | Repository name with owner                      |
| `checkout-ref`                       | `''`                       | Branch, tag or SHA to checkout                  |
| `checkout-token`                     | `${{ github.token }}`      | PAT for authenticated fetch                     |
| `checkout-ssh-key`                   | `''`                       | SSH key for authenticated fetch                 |
| `checkout-ssh-known-hosts`           | `''`                       | Additional known hosts                          |
| `checkout-ssh-strict`                | `true`                     | Strict host key checking                        |
| `checkout-ssh-user`                  | `git`                      | SSH remote user                                 |
| `checkout-persist-credentials`       | `true`                     | Configure token/SSH key in local git config     |
| `checkout-path`                      | `''`                       | Relative path under `$GITHUB_WORKSPACE`         |
| `checkout-clean`                     | `true`                     | Run `git clean -ffdx && git reset --hard`       |
| `checkout-filter`                    | `''`                       | Partial clone filter; overrides sparse-checkout |
| `checkout-sparse-checkout`           | `''`                       | Sparse checkout patterns (newline-separated)    |
| `checkout-sparse-checkout-cone-mode` | `true`                     | Use cone-mode for sparse checkout               |
| `checkout-fetch-depth`               | `1`                        | Commits to fetch; `0` = all history             |
| `checkout-fetch-tags`                | `false`                    | Fetch tags even when fetch-depth > 0            |
| `checkout-show-progress`             | `true`                     | Show progress output when fetching              |
| `checkout-lfs`                       | `false`                    | Download Git-LFS files                          |
| `checkout-submodules`                | `false`                    | `true` or `recursive`                           |
| `checkout-set-safe-directory`        | `true`                     | Add repo path as `safe.directory`               |
| `checkout-github-server-url`         | `''`                       | Base URL for GHES or other GitHub instances     |

### Rust Toolchain Inputs (`actions-rust-lang/setup-rust-toolchain`)

| Input                    | Default  | Notes                                  |
| ------------------------ | -------- | -------------------------------------- |
| `install-rust-toolchain` | `true`   | Install toolchain before semver checks |
| `rust-toolchain`         | `stable` | Toolchain specification                |
| `rust-target`            | `''`     | Target triple to install               |

### Rust Cache Inputs (`Swatinem/rust-cache`)

| Input                    | Default | Notes                                   |
| ------------------------ | ------- | --------------------------------------- |
| `setup-rust-cache`       | `true`  | Restore/save `Swatinem/rust-cache`      |
| `rust-cache-key-suffix`  | `''`    | Isolates rust-cache per semver surface  |
| `cache-all-crates`       | `true`  | Cache all crates, not just dependencies |
| `cache-targets`          | `true`  | Cache `target/` directories             |
| `cache-workspace-crates` | `true`  | Cache workspace crates                  |
| `cache-bin`              | `true`  | Cache `~/.cargo/bin`                    |
| `cache-on-failure`       | `true`  | Save cache even after a failed run      |

### Upstream Pass-Through Inputs (`obi1kenobi/cargo-semver-checks-action`)

| Input              | Default               | Notes                                     |
| ------------------ | --------------------- | ----------------------------------------- |
| `manifest-path`    | `''`                  | Path to a crate or workspace `Cargo.toml` |
| `package`          | `''`                  | Comma-separated package list              |
| `exclude`          | `''`                  | Exclude list used when `package` is empty |
| `feature-group`    | `''`                  | Feature selection mode (see below)        |
| `features`         | `''`                  | Comma-separated explicit features         |
| `verbose`          | `false`               | Enables verbose semver output             |
| `release-type`     | `''`                  | Override release type                     |
| `shared-key`       | `''`                  | Passed to upstream rustdoc cache          |
| `prefix-key`       | `''`                  | Prefix for upstream rustdoc cache         |
| `github-token`     | `${{ github.token }}` | Used by upstream binary download          |
| `baseline-version` | `''`                  | Explicit registry baseline                |
| `baseline-rev`     | `''`                  | Explicit git baseline                     |
| `baseline-root`    | `''`                  | Explicit baseline directory               |

`feature-group` controls which features are enabled for semver analysis.
See the [upstream docs][upstream-readme].

| Value                    | Behavior                               |
| ------------------------ | -------------------------------------- |
| `all-features`           | Enable all declared features           |
| `default-features`       | Use only default features              |
| `only-explicit-features` | Enable **only** features in `features` |

When empty, it defaults to `default-features`. Set it explicitly if you want
matrix rows to be clearer.

## Outputs

| Output                  | Meaning                                               |
| ----------------------- | ----------------------------------------------------- |
| `did-run`               | `true` if the upstream action was invoked             |
| `effective-packages`    | Comma-separated package list selected for checking    |
| `skipped-packages`      | Comma-separated package list skipped before execution |
| `rust-cache-workspaces` | Workspace mapping passed to `Swatinem/rust-cache`     |

## Caching Strategy

This action uses two caches:

| Cache                 | Purpose                                                       |
| --------------------- | ------------------------------------------------------------- |
| Upstream cache        | Baseline rustdocs                                             |
| `Swatinem/rust-cache` | Current-build artifacts, Cargo registry, and git dependencies |

The upstream action writes current-build artifacts to:

```text
$GITHUB_WORKSPACE/semver-checks/target
```

This wrapper points `rust-cache` at that directory.

It also enables `cache-workspace-crates` by default because semver checks
rebuild workspace crates repeatedly.

**Note:** `shared-key` must not be reused across different semver targets
(keep it target-specific).

For details, see the [upstream action cache docs], [upstream action inputs],
and [rust-cache docs].

## Unpublished Crates

The upstream action fails if a workspace contains an unpublished crate ([#53]).
This wrapper skips those crates by default.

This filtering is unnecessary when you provide `baseline-version`,
`baseline-rev`, or `baseline-root`, since those inputs already define the
comparison target.

To see what would be checked without running semver checks, set
`filter-only: true` and inspect the `effective-packages` and
`skipped-packages` outputs.

[#53]: https://github.com/obi1kenobi/cargo-semver-checks-action/issues/53

## Testing

The repository includes fixture-based workflow tests that cover:

- Workspace auto-discovery
- `exclude`
- Skipping unpublished crates
- Failing when no published crates remain
- Explicit baseline bypass
- Matrix-friendly output assertions

## License

This GitHub Action is released under the [MIT License](LICENSE).

[upstream action cache docs]: https://github.com/obi1kenobi/cargo-semver-checks-action/blob/af8d009e4808912e00129e9334b6c7b117d92a2b/README.md#customizing-baseline-rustdoc-caching-strategy
[upstream action inputs]: https://github.com/obi1kenobi/cargo-semver-checks-action/blob/af8d009e4808912e00129e9334b6c7b117d92a2b/action.yml
[upstream-readme]: https://github.com/obi1kenobi/cargo-semver-checks-action?tab=readme-ov-file
[rust-cache docs]: https://github.com/Swatinem/rust-cache/blob/f51f967e158417aafa338a1e46ab22095f07aa01/README.md
