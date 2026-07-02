"""
mm.metrics.base — metric module registry.

Each metric module registers itself here at import time so the pipeline
can discover and invoke all applicable metrics without hardcoding a list.

Usage (from a metric module)::

    from mm.metrics.base import register

    @register("workspace")
    def compute(elements: list[dict]) -> dict[str, int | float]:
        ...

Usage (from the pipeline runner)::

    from mm.metrics.base import get_metrics_for_source
    import mm.metrics.contributors  # side-effect: registers the module
    import mm.metrics.edits

    for compute_fn in get_metrics_for_source("workspace"):
        results.update(compute_fn(elements))

Design notes
------------
- A metric module may register under multiple source types if it is
  meaningful for more than one adapter.
- The registry maps source type → ordered list of ``compute`` callables.
  Insertion order is preserved (Python 3.7+ dict guarantee).
- Metric modules are responsible for importing and registering themselves;
  the pipeline runner is responsible for importing the modules it wants.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

# Registry: source_type → list of compute functions registered for that source.
_REGISTRY: dict[str, list[Callable[..., dict[str, int | float]]]] = defaultdict(list)


def register(
    *source_types: str,
) -> Callable:
    """Decorator that registers a ``compute`` function for one or more source
    types.

    Parameters
    ----------
    *source_types:
        One or more source-type strings (e.g. ``"workspace"``).  The
        decorated function is appended to the registry for each.

    Returns
    -------
    Callable
        The original function, unchanged.

    Example
    -------
    ::

        @register("workspace", "tasking_manager")
        def compute(elements: list[dict]) -> dict[str, int | float]:
            ...
    """

    def decorator(fn: Callable) -> Callable:
        for src in source_types:
            _REGISTRY[src].append(fn)
        return fn

    return decorator


def get_metrics_for_source(
    source_type: str,
) -> list[Callable[..., dict[str, int | float]]]:
    """Return all registered ``compute`` callables for *source_type*.

    Parameters
    ----------
    source_type:
        The source type to look up (e.g. ``"workspace"``).

    Returns
    -------
    list[Callable]
        Registered compute functions in registration order.  Returns an
        empty list if no metrics are registered for *source_type*.
    """
    return list(_REGISTRY[source_type])
