#!/usr/bin/env python3
"""Execute the notebooks into a build directory and export rendered HTML.

Committed notebooks in ``notebooks/`` stay stripped of outputs to keep Git history small.
The savings and supply notebooks are 100% offline and mandatory. The demand notebook reads
CoinGecko live; only transient CoinGecko network/rate-limit errors are downgraded to a
warning with a full traceback. Any other error fails the run.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

from jupyter_client import AsyncKernelManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError
import nbformat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bitcoin_investment_strategy.notebook_html import export_notebooks_html  # noqa: E402
from bitcoin_investment_strategy.release_files import DATA_MANIFEST  # noqa: E402

NOTEBOOKS = [
    ROOT / "notebooks/bitcoin_savings_plan.ipynb",
    ROOT / "notebooks/bitcoin_supply_dynamics.ipynb",
]
OPTIONAL_NOTEBOOKS = [
    ROOT / "notebooks/bitcoin_demand_dynamics.ipynb",
]

COINGECKO_TRANSIENT_ERROR_NAMES = frozenset({
    "CoinGeckoTransientError",
    "TransientRequestError",
})


def is_coingecko_transient_error(error: BaseException) -> bool:
    """True only when a cell execution failed on a transient CoinGecko network/429 error."""
    if not isinstance(error, CellExecutionError):
        return False
    ename = getattr(error, "ename", "") or ""
    if ename in COINGECKO_TRANSIENT_ERROR_NAMES:
        return True
    evalue = getattr(error, "evalue", "") or ""
    tb = getattr(error, "traceback", "") or ""
    combined = f"{evalue}\n{tb}".lower()
    if "coingecko" in combined and any(
        marker in combined for marker in ("429", "too many requests", "timed out", "connectionerror", "connection reset")
    ):
        return True
    return False


def execute_single_notebook(path: Path, *, timeout: int) -> nbformat.NotebookNode:
    notebook = nbformat.read(path, as_version=4)
    # Scope Jupyter IPC sockets inside an ephemeral directory so zero kernel-ipc-* files
    # ever leak into the repository root. Windows falls back to TCP.
    with tempfile.TemporaryDirectory(prefix="jupyter-ipc-") as ipc_dir:
        km_kwargs: dict[str, object] = {
            "kernel_name": "python3",
            "transport": "ipc" if os.name != "nt" else "tcp",
        }
        if os.name != "nt":
            km_kwargs["ip"] = str(Path(ipc_dir) / "kernel")
        kernel_manager = AsyncKernelManager(**km_kwargs)
        client = NotebookClient(
            notebook,
            km=kernel_manager,
            timeout=timeout,
            kernel_name="python3",
            resources={"metadata": {"path": str(ROOT)}},
            allow_errors=False,
        )
        client.execute()
    return notebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=1200, help="Per-cell timeout in seconds")
    parser.add_argument(
        "--executed-dir",
        type=Path,
        default=ROOT / "build/executed-notebooks",
        help="Directory where executed .ipynb copies are written (committed notebooks stay stripped)",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=ROOT / "build/pages",
        help="Directory where daily rendered HTML pages are written",
    )
    arguments = parser.parse_args()
    # Capture figures into notebook output cells for HTML export. The inline backend is
    # headless and does not require a display.
    os.environ.setdefault("MPLBACKEND", "module://matplotlib_inline.backend_inline")
    os.environ.setdefault("PYTHONHASHSEED", "0")
    # Put the current interpreter first so local runs cannot silently execute notebooks
    # with an unrelated global Python installation.
    interpreter_dir = str(Path(sys.executable).parent)
    os.environ["PATH"] = os.pathsep.join(
        [interpreter_dir, os.environ.get("PATH", "")]
    ).rstrip(os.pathsep)

    arguments.executed_dir.mkdir(parents=True, exist_ok=True)
    executed_paths: list[Path] = []
    skipped_optional: list[str] = []

    for path in NOTEBOOKS + OPTIONAL_NOTEBOOKS:
        print(f"Executing {path.relative_to(ROOT)}")
        try:
            notebook = execute_single_notebook(path, timeout=arguments.timeout)
        except CellExecutionError as error:
            if path in OPTIONAL_NOTEBOOKS and is_coingecko_transient_error(error):
                traceback.print_exc()
                if getattr(error, "traceback", None):
                    print(error.traceback, file=sys.stderr)
                print(
                    f"::warning file=notebooks/{path.name}::CoinGecko transient error while executing "
                    f"{path.name} ({error.ename}: {error.evalue}); skipping optional demand HTML refresh"
                )
                skipped_optional.append(path.name)
                continue
            raise
        target = arguments.executed_dir / path.name
        nbformat.write(notebook, target)
        executed_paths.append(target)
        print(f"  completed {path.name} -> {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")

    data_manifest = json.loads((ROOT / DATA_MANIFEST).read_text(encoding="utf-8"))
    data_end = data_manifest["core_data_end"]
    if arguments.html_dir is not None:
        exported = export_notebooks_html(executed_paths, arguments.html_dir, data_end=data_end)
        print(f"Exported {len(exported)} HTML files to {arguments.html_dir}")
    if skipped_optional:
        print(f"Optional notebooks skipped due to CoinGecko transient errors: {skipped_optional}")


if __name__ == "__main__":
    main()
