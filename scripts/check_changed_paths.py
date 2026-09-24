#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from publication import PUBLICATION_FILES


def main() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"], check=True, capture_output=True, text=True
    )
    unexpected = []
    for line in result.stdout.splitlines():
        path = line[3:].split(" -> ")[-1]
        if path not in PUBLICATION_FILES:
            unexpected.append(path)
    if unexpected:
        raise SystemExit(f"daily update changed files outside the publish allowlist: {unexpected}")
    print("All changes are expected public data, savings notebook, or savings-report files.")


if __name__ == "__main__":
    main()
