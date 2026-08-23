#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from jupyter_client import AsyncKernelManager


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = [
    ROOT / "notebooks/bitcoin_savings_plan.ipynb",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute the public notebooks in place")
    parser.add_argument("--timeout", type=int, default=1200, help="Per-cell timeout in seconds")
    arguments = parser.parse_args()
    # Capture figures into notebook output cells so GitHub renders the public
    # notebook. The inline backend is headless and does not require a display.
    os.environ.setdefault("MPLBACKEND", "module://matplotlib_inline.backend_inline")
    os.environ.setdefault("PYTHONHASHSEED", "0")
    # The fallback ``python3`` kernelspec launches ``python`` from PATH. Put the
    # current interpreter first so local runs cannot silently execute notebooks
    # with an unrelated global Python installation.
    interpreter_dir = str(Path(sys.executable).parent)
    os.environ["PATH"] = os.pathsep.join(
        [interpreter_dir, os.environ.get("PATH", "")]
    ).rstrip(os.pathsep)

    for path in NOTEBOOKS:
        print(f"Executing {path.relative_to(ROOT)}")
        notebook = nbformat.read(path, as_version=4)
        # Keep local kernel traffic off TCP where the platform supports Unix
        # domain sockets. Windows does not support Jupyter's IPC transport.
        kernel_manager = AsyncKernelManager(
            kernel_name="python3",
            transport="ipc" if os.name != "nt" else "tcp",
        )
        client = NotebookClient(
            notebook,
            km=kernel_manager,
            timeout=arguments.timeout,
            kernel_name="python3",
            resources={"metadata": {"path": str(ROOT)}},
            allow_errors=False,
        )
        client.execute()
        nbformat.write(notebook, path)
        print(f"  completed {path.name}")


if __name__ == "__main__":
    main()
