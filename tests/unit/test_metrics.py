"""Unit tests for mm.metrics metric modules.

All tests are fully offline — no network calls, no file I/O.

Test matrix:
    contributor_count:
        - returns 0 for empty element list
        - counts unique users across nodes and ways
        - one contributor → count is 1
        - multiple elements from same user not double-counted
    changeset_count:
        - returns 0 for empty element list
        - counts unique changesets
        - multiple elements from same changeset not double-counted
    elements_edited:
        - returns 0 for empty element list
        - equals total element count
    node_count:
        - returns 0 for empty element list
        - counts only nodes
        - mixed types: node_count < elements_edited
    metrics.base registry:
        - registered functions appear in get_metrics_for_source
        - unknown source_type returns empty list
        - compute results from all metrics can be merged
"""

from __future__ import annotations

from typing import Any

import mm.metrics.changeset_count as changeset_count_mod
import mm.metrics.contributor_count as contributor_count_mod
import mm.metrics.elements_edited as elements_edited_mod
import mm.metrics.node_count as node_count_mod
import mm.metrics.relation_count as relation_count_mod
import mm.metrics.way_count as way_count_mod
from mm.metrics.base import get_metrics_for_source

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _node(
    id_: int = 1,
    user: str = "alice",
    uid: int = 10,
    changeset: int = 100,
    timestamp: str = "2026-01-20T20:00:00Z",
    **extra: Any,
) -> dict:
    return {
        "type": "node",
        "id": id_,
        "user": user,
        "uid": uid,
        "changeset": changeset,
        "timestamp": timestamp,
        "tags": {},
        **extra,
    }


def _way(
    id_: int = 50,
    user: str = "alice",
    uid: int = 10,
    changeset: int = 100,
    timestamp: str = "2026-01-20T21:00:00Z",
    **extra: Any,
) -> dict:
    return {
        "type": "way",
        "id": id_,
        "user": user,
        "uid": uid,
        "changeset": changeset,
        "timestamp": timestamp,
        "tags": {},
        "nodes": [],
        **extra,
    }


def _relation(
    id_: int = 200,
    user: str = "alice",
    uid: int = 10,
    changeset: int = 100,
    timestamp: str = "2026-01-20T22:00:00Z",
    **extra: Any,
) -> dict:
    return {
        "type": "relation",
        "id": id_,
        "user": user,
        "uid": uid,
        "changeset": changeset,
        "timestamp": timestamp,
        "tags": {},
        "members": [],
        **extra,
    }


# ---------------------------------------------------------------------------
# contributor_count.compute
# ---------------------------------------------------------------------------


def test_contributor_count_empty() -> None:
    result = contributor_count_mod.compute([])
    assert result == {"contributor_count": 0}


def test_contributor_count_single_element() -> None:
    result = contributor_count_mod.compute([_node()])
    assert result["contributor_count"] == 1


def test_contributor_count_unique_users() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _node(id_=2, user="bob", changeset=101),
        _node(id_=3, user="alice", changeset=102),  # alice again
    ]
    result = contributor_count_mod.compute(elements)
    assert result["contributor_count"] == 2  # alice + bob


def test_contributor_count_mixed_element_types() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _way(id_=50, user="bob", changeset=101),
    ]
    result = contributor_count_mod.compute(elements)
    assert result["contributor_count"] == 2


# ---------------------------------------------------------------------------
# changeset_count.compute
# ---------------------------------------------------------------------------


def test_changeset_count_empty() -> None:
    result = changeset_count_mod.compute([])
    assert result == {"changeset_count": 0}


def test_changeset_count_single_element() -> None:
    result = changeset_count_mod.compute([_node()])
    assert result["changeset_count"] == 1


def test_changeset_count_unique_changesets() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _node(id_=2, user="alice", changeset=100),  # same changeset
        _node(id_=3, user="alice", changeset=101),  # different changeset
    ]
    result = changeset_count_mod.compute(elements)
    assert result["changeset_count"] == 2


def test_changeset_count_mixed_element_types() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _way(id_=50, user="bob", changeset=101),
    ]
    result = changeset_count_mod.compute(elements)
    assert result["changeset_count"] == 2


def test_changeset_count_same_user_multiple_changesets() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _node(id_=2, user="alice", changeset=101),
        _node(id_=3, user="alice", changeset=102),
    ]
    result = changeset_count_mod.compute(elements)
    assert result["changeset_count"] == 3


# ---------------------------------------------------------------------------
# contributors.compute
# ---------------------------------------------------------------------------


def test_contributors_empty() -> None:
    result = contributor_count_mod.compute([])
    assert result == {"contributor_count": 0}


def test_contributors_single_element() -> None:
    result = contributor_count_mod.compute([_node()])
    assert result["contributor_count"] == 1


def test_contributors_unique_users() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _node(id_=2, user="bob", changeset=101),
        _node(id_=3, user="alice", changeset=102),  # alice again
    ]
    result = contributor_count_mod.compute(elements)
    assert result["contributor_count"] == 2  # alice + bob


def test_contributors_unique_changesets() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _node(id_=2, user="alice", changeset=100),  # same changeset
        _node(id_=3, user="alice", changeset=101),  # different changeset
    ]
    result = changeset_count_mod.compute(elements)
    assert result["changeset_count"] == 2


def test_contributors_mixed_element_types() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _way(id_=50, user="bob", changeset=101),
    ]
    result = contributor_count_mod.compute(elements)
    assert result["contributor_count"] == 2


def test_contributors_same_user_multiple_changesets() -> None:
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _node(id_=2, user="alice", changeset=101),
        _node(id_=3, user="alice", changeset=102),
    ]
    result = changeset_count_mod.compute(elements)
    assert result["changeset_count"] == 3


# ---------------------------------------------------------------------------
# elements_edited.compute
# ---------------------------------------------------------------------------


def test_elements_edited_empty() -> None:
    result = elements_edited_mod.compute([])
    assert result == {"elements_edited": 0}


def test_elements_edited_single_node() -> None:
    result = elements_edited_mod.compute([_node()])
    assert result["elements_edited"] == 1


def test_elements_edited_single_way() -> None:
    result = elements_edited_mod.compute([_way()])
    assert result["elements_edited"] == 1


def test_elements_edited_mixed_types() -> None:
    elements = [
        _node(id_=1),
        _node(id_=2),
        _way(id_=50),
    ]
    result = elements_edited_mod.compute(elements)
    assert result["elements_edited"] == 3


# ---------------------------------------------------------------------------
# node_count.compute
# ---------------------------------------------------------------------------


def test_node_count_empty() -> None:
    result = node_count_mod.compute([])
    assert result == {"node_count": 0}


def test_node_count_single_node() -> None:
    result = node_count_mod.compute([_node()])
    assert result["node_count"] == 1


def test_node_count_single_way() -> None:
    result = node_count_mod.compute([_way()])
    assert result["node_count"] == 0


def test_node_count_mixed_types() -> None:
    elements = [
        _node(id_=1),
        _node(id_=2),
        _way(id_=50),
    ]
    result = node_count_mod.compute(elements)
    assert result["node_count"] == 2


# ---------------------------------------------------------------------------
# way_count.compute
# ---------------------------------------------------------------------------


def test_way_count_empty() -> None:
    result = way_count_mod.compute([])
    assert result == {"way_count": 0}


def test_way_count_single_way() -> None:
    result = way_count_mod.compute([_way()])
    assert result["way_count"] == 1


def test_way_count_single_node() -> None:
    result = way_count_mod.compute([_node()])
    assert result["way_count"] == 0


def test_way_count_mixed_types() -> None:
    elements = [
        _node(id_=1),
        _way(id_=50),
        _way(id_=51),
        _relation(id_=200),
    ]
    result = way_count_mod.compute(elements)
    assert result["way_count"] == 2


# ---------------------------------------------------------------------------
# relation_count.compute
# ---------------------------------------------------------------------------


def test_relation_count_empty() -> None:
    result = relation_count_mod.compute([])
    assert result == {"relation_count": 0}


def test_relation_count_single_relation() -> None:
    result = relation_count_mod.compute([_relation()])
    assert result["relation_count"] == 1


def test_relation_count_single_node() -> None:
    result = relation_count_mod.compute([_node()])
    assert result["relation_count"] == 0


def test_relation_count_mixed_types() -> None:
    elements = [
        _node(id_=1),
        _way(id_=50),
        _relation(id_=200),
        _relation(id_=201),
    ]
    result = relation_count_mod.compute(elements)
    assert result["relation_count"] == 2


# ---------------------------------------------------------------------------
# Element type counts sum to elements_edited
# ---------------------------------------------------------------------------


def test_element_type_counts_sum_to_elements_edited_empty() -> None:
    elements: list = []
    total = elements_edited_mod.compute(elements)["elements_edited"]
    part_sum = (
        node_count_mod.compute(elements)["node_count"]
        + way_count_mod.compute(elements)["way_count"]
        + relation_count_mod.compute(elements)["relation_count"]
    )
    assert part_sum == total


def test_element_type_counts_sum_to_elements_edited_nodes_only() -> None:
    elements = [_node(id_=1), _node(id_=2), _node(id_=3)]
    total = elements_edited_mod.compute(elements)["elements_edited"]
    part_sum = (
        node_count_mod.compute(elements)["node_count"]
        + way_count_mod.compute(elements)["way_count"]
        + relation_count_mod.compute(elements)["relation_count"]
    )
    assert part_sum == total == 3


def test_element_type_counts_sum_to_elements_edited_all_types() -> None:
    elements = [
        _node(id_=1),
        _node(id_=2),
        _way(id_=50),
        _relation(id_=200),
    ]
    total = elements_edited_mod.compute(elements)["elements_edited"]
    part_sum = (
        node_count_mod.compute(elements)["node_count"]
        + way_count_mod.compute(elements)["way_count"]
        + relation_count_mod.compute(elements)["relation_count"]
    )
    assert part_sum == total == 4


# ---------------------------------------------------------------------------
# edits.compute
# ---------------------------------------------------------------------------


def test_edits_empty() -> None:
    result = elements_edited_mod.compute([])
    assert result == {"elements_edited": 0}


def test_edits_single_node() -> None:
    result = elements_edited_mod.compute([_node()])
    assert result["elements_edited"] == 1
    assert node_count_mod.compute([_node()])["node_count"] == 1


def test_edits_single_way() -> None:
    result = elements_edited_mod.compute([_way()])
    assert result["elements_edited"] == 1
    assert node_count_mod.compute([_way()])["node_count"] == 0


def test_edits_mixed_types() -> None:
    elements = [
        _node(id_=1),
        _node(id_=2),
        _way(id_=50),
    ]
    result = elements_edited_mod.compute(elements)
    assert result["elements_edited"] == 3
    assert node_count_mod.compute(elements)["node_count"] == 2


# ---------------------------------------------------------------------------
# mm.metrics.base registry
# ---------------------------------------------------------------------------


def test_registry_contributor_count_registered_for_workspace() -> None:
    fns = get_metrics_for_source("workspace")
    assert contributor_count_mod.compute in fns


def test_registry_changeset_count_registered_for_workspace() -> None:
    fns = get_metrics_for_source("workspace")
    assert changeset_count_mod.compute in fns


def test_registry_elements_edited_registered_for_workspace() -> None:
    fns = get_metrics_for_source("workspace")
    assert elements_edited_mod.compute in fns


def test_registry_node_count_registered_for_workspace() -> None:
    fns = get_metrics_for_source("workspace")
    assert node_count_mod.compute in fns


def test_registry_way_count_registered_for_workspace() -> None:
    fns = get_metrics_for_source("workspace")
    assert way_count_mod.compute in fns


def test_registry_relation_count_registered_for_workspace() -> None:
    fns = get_metrics_for_source("workspace")
    assert relation_count_mod.compute in fns


def test_registry_unknown_source_returns_empty() -> None:
    fns = get_metrics_for_source("tasking_manager")
    # No tasking_manager metrics are registered in v1.
    assert fns == []


def test_registry_compute_results_merge() -> None:
    """Running all registered workspace metrics and merging dicts works."""
    elements = [
        _node(id_=1, user="alice", changeset=100),
        _node(id_=2, user="bob", changeset=101),
        _way(id_=50, user="alice", changeset=100),
        _relation(id_=200, user="bob", changeset=101),
    ]
    merged: dict = {}
    for compute_fn in get_metrics_for_source("workspace"):
        merged.update(compute_fn(elements))

    assert merged["contributor_count"] == 2
    assert merged["changeset_count"] == 2
    assert merged["elements_edited"] == 4
    assert merged["node_count"] == 2
    assert merged["way_count"] == 1
    assert merged["relation_count"] == 1
    assert (
        merged["node_count"] + merged["way_count"] + merged["relation_count"]
        == merged["elements_edited"]
    )
