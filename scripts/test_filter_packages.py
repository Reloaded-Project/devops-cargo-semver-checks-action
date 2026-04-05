#!/usr/bin/env python3
"""Unit tests for filter_packages.py using the built-in ``unittest`` framework.

Each test class covers one function from ``filter_packages.py``. Tests mock
external dependencies - ``subprocess.run`` and network requests via
``unittest.mock.patch`` - so they run instantly without requiring ``cargo`` or
internet access.

Run from the project root:

    python3 -m unittest scripts/test_filter_packages.py -v
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import filter_packages
from filter_packages import CargoMetadata, CargoPackage, PackageList


class TestParseCsv(unittest.TestCase):
    """Tests for ``filter_packages._parse_csv`` - CSV input splitting and whitespace handling."""

    def test_single_item(self):
        self.assertEqual(filter_packages._parse_csv("serde"), ["serde"])

    def test_multiple_items(self):
        self.assertEqual(
            filter_packages._parse_csv("serde, anyhow, clap"),
            ["serde", "anyhow", "clap"],
        )

    def test_empty_string(self):
        self.assertEqual(filter_packages._parse_csv(""), [])

    def test_trailing_commas_and_whitespace(self):
        self.assertEqual(filter_packages._parse_csv("  a , b, , c "), ["a", "b", "c"])


class TestResolvePackages(unittest.TestCase):
    """Tests for ``filter_packages._resolve_packages`` - discovery, selection, and exclusion."""

    METADATA = CargoMetadata(
        workspace_members=[
            "pkg-a 0.1.0 (path+file:///repo/a)",
            "pkg-b 0.1.0 (path+file:///repo/b)",
        ],
        packages=[
            CargoPackage(
                id="pkg-a 0.1.0 (path+file:///repo/a)",
                name="pkg-a",
                publish=None,
            ),
            CargoPackage(
                id="pkg-b 0.1.0 (path+file:///repo/b)",
                name="pkg-b",
                publish=False,
            ),
        ],
    )

    def test_auto_discovery_skips_unpublishable(self):
        out = filter_packages._resolve_packages([], [], self.METADATA)
        self.assertEqual(out.effective_packages, ["pkg-a"])
        self.assertEqual(out.skipped_packages, ["pkg-b"])

    def test_explicit_package(self):
        out = filter_packages._resolve_packages(["pkg-a"], [], self.METADATA)
        self.assertEqual(out.effective_packages, ["pkg-a"])
        self.assertEqual(out.skipped_packages, [])

    def test_exclude(self):
        out = filter_packages._resolve_packages([], ["pkg-a"], self.METADATA)
        self.assertEqual(out.effective_packages, [])
        self.assertIn("pkg-b", out.skipped_packages)

    def test_unknown_package_skipped(self):
        out = filter_packages._resolve_packages(["nope"], [], self.METADATA)
        self.assertEqual(out.effective_packages, [])
        self.assertEqual(out.skipped_packages, ["nope"])

    def test_deduplication(self):
        out = filter_packages._resolve_packages(["pkg-a", "pkg-a"], [], self.METADATA)
        self.assertEqual(out.effective_packages, ["pkg-a"])

    def test_empty_publish_list_skips(self):
        metadata = CargoMetadata(
            workspace_members=["x 0.1.0 (path+file:///x)"],
            packages=[
                CargoPackage(id="x 0.1.0 (path+file:///x)", name="x", publish=[]),
            ],
        )
        out = filter_packages._resolve_packages([], [], metadata)
        self.assertEqual(out.skipped_packages, ["x"])


class TestSparseIndexPath(unittest.TestCase):
    """Tests for ``filter_packages._sparse_index_path`` - segment layout per name-length bucket."""

    def test_single_char(self):
        self.assertEqual(filter_packages._sparse_index_path("a"), "1/a")

    def test_two_chars(self):
        self.assertEqual(filter_packages._sparse_index_path("ab"), "2/ab")

    def test_three_chars(self):
        self.assertEqual(filter_packages._sparse_index_path("abc"), "3/a/abc")

    def test_four_or_more(self):
        self.assertEqual(filter_packages._sparse_index_path("serde"), "se/rd/serde")

    def test_long_name(self):
        self.assertEqual(
            filter_packages._sparse_index_path("cargo-semver-checks"),
            "ca/rg/cargo-semver-checks",
        )


class TestFilterPublished(unittest.TestCase):
    """Tests for ``filter_packages._filter_published`` - moving unpublished crates to the skipped list."""

    def test_moves_unpublished_to_skipped(self):
        with patch.object(
            filter_packages, "_crate_has_non_yanked_release", return_value=False
        ):
            out = filter_packages._filter_published(
                PackageList(effective_packages=["fake-crate"], skipped_packages=[])
            )
        self.assertEqual(out.effective_packages, [])
        self.assertEqual(out.skipped_packages, ["fake-crate"])

    def test_keeps_published(self):
        with patch.object(
            filter_packages, "_crate_has_non_yanked_release", return_value=True
        ):
            out = filter_packages._filter_published(
                PackageList(effective_packages=["serde"], skipped_packages=[])
            )
        self.assertEqual(out.effective_packages, ["serde"])
        self.assertEqual(out.skipped_packages, [])


class TestRustCacheWorkspaces(unittest.TestCase):
    """Tests for rust-cache workspace mapping derived from cargo metadata."""

    def test_nested_workspace_points_at_semver_target(self):
        metadata = CargoMetadata(
            workspace_members=[],
            packages=[],
            workspace_root="/repo/src",
        )

        with patch.dict(
            os.environ,
            {"GITHUB_WORKSPACE": "/repo"},
            clear=False,
        ):
            self.assertEqual(
                filter_packages._rust_cache_workspaces(metadata),
                "src -> ../semver-checks/target",
            )

    def test_repo_root_workspace_points_at_semver_target(self):
        metadata = CargoMetadata(
            workspace_members=[],
            packages=[],
            workspace_root="/repo",
        )

        with patch.dict(
            os.environ,
            {"GITHUB_WORKSPACE": "/repo"},
            clear=False,
        ):
            self.assertEqual(
                filter_packages._rust_cache_workspaces(metadata),
                ". -> semver-checks/target",
            )

    def test_falls_back_to_current_directory_without_github_workspace(self):
        metadata = CargoMetadata(
            workspace_members=[],
            packages=[],
            workspace_root="/tmp/project/workspace",
        )

        with patch.dict(os.environ, {}, clear=True):
            with patch("os.getcwd", return_value="/tmp/project"):
                self.assertEqual(
                    filter_packages._rust_cache_workspaces(metadata),
                    "workspace -> ../semver-checks/target",
                )


CARGO_METADATA_STUB = json.dumps(
    {
        "workspace_members": [
            "my-pkg 0.1.0 (path+file:///repo/my-pkg)",
        ],
        "packages": [
            {
                "id": "my-pkg 0.1.0 (path+file:///repo/my-pkg)",
                "name": "my-pkg",
                "publish": None,
            },
        ],
    }
)


class TestMain(unittest.TestCase):
    """Integration tests for ``filter_packages.main`` - mocked subprocess and registry lookups."""

    def _run_main(self, env: dict) -> tuple[int, str, str]:
        """Execute ``main`` under the given action inputs.

        Patches ``subprocess.run`` with stubbed ``cargo metadata`` output,
        mocks the registry check, captures stdout/stderr, and writes
        ``GITHUB_OUTPUT`` to a temporary file.

        Arguments:
            env: Action inputs to overlay (``INPUT_*`` variables).

        Returns:
            A tuple of ``(exit_code, captured_stdout, github_output_content)``.
        """
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".env") as tmp:
            full_env = {**os.environ, "GITHUB_OUTPUT": tmp.name, **env}
            with patch.dict(os.environ, full_env, clear=False):
                mock_run = MagicMock()
                mock_run.stdout = CARGO_METADATA_STUB
                mock_run.stderr = ""
                with patch("subprocess.run", return_value=mock_run):
                    with patch(
                        "filter_packages._crate_has_non_yanked_release",
                        return_value=True,
                    ):
                        captured_out = io.StringIO()
                        captured_err = io.StringIO()
                        with patch("sys.stdout", captured_out):
                            with patch("sys.stderr", captured_err):
                                code = filter_packages.main()

            tmp.seek(0)
            output = tmp.read()
        return code, captured_out.getvalue(), output

    def test_did_run_true(self):
        code, _, output = self._run_main(
            {
                "INPUT_PACKAGE": "my-pkg",
                "INPUT_SKIP_UNPUBLISHED": "false",
                "INPUT_FAIL_IF_NO_PUBLISHED_PACKAGES": "false",
            }
        )
        self.assertEqual(code, 0)
        self.assertIn("did_run=true", output)
        self.assertIn("effective_packages=my-pkg", output)

    def test_did_run_false_when_empty(self):
        code, _, output = self._run_main(
            {
                "INPUT_PACKAGE": "",
                "INPUT_EXCLUDE": "my-pkg",
                "INPUT_SKIP_UNPUBLISHED": "false",
                "INPUT_FAIL_IF_NO_PUBLISHED_PACKAGES": "false",
            }
        )
        self.assertEqual(code, 0)
        self.assertIn("did_run=false", output)
        self.assertIn("effective_packages=", output)

    def test_fail_if_empty(self):
        code, _, _ = self._run_main(
            {
                "INPUT_PACKAGE": "nonexistent",
                "INPUT_SKIP_UNPUBLISHED": "false",
                "INPUT_FAIL_IF_NO_PUBLISHED_PACKAGES": "true",
            }
        )
        self.assertEqual(code, 1)

    def test_baseline_skips_registry_check(self):
        code, _, output = self._run_main(
            {
                "INPUT_PACKAGE": "my-pkg",
                "INPUT_SKIP_UNPUBLISHED": "true",
                "INPUT_BASELINE_ROOT": "/some/path",
                "INPUT_FAIL_IF_NO_PUBLISHED_PACKAGES": "false",
            }
        )
        self.assertEqual(code, 0)
        self.assertIn("did_run=true", output)
        self.assertIn("effective_packages=my-pkg", output)


if __name__ == "__main__":
    unittest.main()
