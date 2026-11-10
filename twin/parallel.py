"""Per-sweep parallelism with ordered results, and a fast npz writer."""

from __future__ import annotations

import multiprocessing
import os
import zipfile
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from numpy.lib import format as npy_format

# DECISION: leave 4 cores for other box jobs, cap at 16 (diminishing returns past that).
MAX_DEFAULT_WORKERS = 16


def default_workers() -> int:
    return max(1, min((os.cpu_count() or 1) - 4, MAX_DEFAULT_WORKERS))


def pmap(fn: Callable[[Any], Any], items: Iterable[Any], workers: int | None) -> list:
    """`list(map(fn, items))`, spread over `workers` forked processes. Results keep the item order.

    Fork lets `fn` read module-level data set before the call without pickling it. With one
    worker, or one item, nothing is forked, so output never depends on the worker count.
    """
    items = list(items)
    n = default_workers() if workers is None else workers
    n = min(n, len(items))
    if n <= 1:
        return [fn(i) for i in items]
    with ProcessPoolExecutor(n, mp_context=multiprocessing.get_context("fork")) as pool:
        return list(pool.map(fn, items, chunksize=max(1, len(items) // (n * 4))))


def savez_fast(path: Path, **arrays: np.ndarray) -> None:
    """Like np.savez_compressed, but deflate level 1: about 3x faster for ~3% more bytes."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for name, arr in arrays.items():
            with z.open(name + ".npy", "w", force_zip64=True) as fp:
                npy_format.write_array(fp, np.asanyarray(arr))
