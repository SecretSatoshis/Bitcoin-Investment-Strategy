#!/usr/bin/env python3
from __future__ import annotations

import subprocess


ALLOWED_PREFIXES = ("data/", "notebooks/")


def main() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"], check=True, capture_output=True, text=True
    )
    unexpected = []
    for line in result.stdout.splitlines():
        path = line[3:].split(" -> ")[-1]
        if not path.startswith(ALLOWED_PREFIXES):
            unexpected.append(path)
    if unexpected:
        raise SystemExit(f"daily update changed files outside the publish allowlist: {unexpected}")
    print("All changes are inside data/ or notebooks/.")


if __name__ == "__main__":
    main()
