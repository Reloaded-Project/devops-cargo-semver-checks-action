#!/usr/bin/env python3
import os
import sys


def normalize(value: str) -> str:
    items = [item.strip() for item in value.split(",") if item.strip()]
    items.sort()
    return ",".join(items)


def main() -> int:
    expected_effective = normalize(os.environ.get("EXPECTED_EFFECTIVE", ""))
    expected_skipped = normalize(os.environ.get("EXPECTED_SKIPPED", ""))
    actual_effective = normalize(os.environ.get("ACTUAL_EFFECTIVE", ""))
    actual_skipped = normalize(os.environ.get("ACTUAL_SKIPPED", ""))

    if actual_effective != expected_effective:
        print(
            "effective-packages mismatch: "
            f"got '{actual_effective}', want '{expected_effective}'",
            file=sys.stderr,
        )
        return 1

    if actual_skipped != expected_skipped:
        print(
            "skipped-packages mismatch: "
            f"got '{actual_skipped}', want '{expected_skipped}'",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
