#!/usr/bin/env python3
"""Fail if a daily run changed any file outside the publication allowlist or leaked IPC sockets."""
from __future__ import annotations

from pathlib import Path
import subprocess

from publication import PUBLICATION_FILES, ROOT


def main() -> None:
    leaked_sockets = sorted(p.name for p in Path(ROOT).glob("kernel-ipc-*"))
    if leaked_sockets:
        raise SystemExit(f"leaked Jupyter IPC socket(s) found in repository root: {leaked_sockets}")
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
    print("All changes are expected public data or savings-report files (committed notebooks remain stripped).")


if __name__ == "__main__":
    main()
