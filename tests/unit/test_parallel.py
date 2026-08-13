"""
Unit tests for core/parallel.py (distribution logic only - no real
processes spun up here; that's covered by a live end-to-end run instead,
since ProcessPoolExecutor behavior isn't meaningfully unit-testable).
"""
import pytest

from core.parallel import distribute_round_robin


def test_even_split_across_workers():
    buckets = distribute_round_robin([1, 2, 3, 4, 5, 6], worker_count=3)
    assert buckets == [[1, 4], [2, 5], [3, 6]]


def test_uneven_split_leaves_some_buckets_shorter():
    buckets = distribute_round_robin([1, 2, 3, 4, 5], worker_count=3)
    assert buckets == [[1, 4], [2, 5], [3]]


def test_more_workers_than_items_leaves_empty_buckets():
    buckets = distribute_round_robin([1, 2], worker_count=5)
    assert buckets == [[1], [2], [], [], []]
    assert sum(len(b) for b in buckets) == 2


def test_single_worker_gets_everything_in_order():
    buckets = distribute_round_robin([1, 2, 3], worker_count=1)
    assert buckets == [[1, 2, 3]]


def test_empty_items_returns_empty_buckets():
    buckets = distribute_round_robin([], worker_count=3)
    assert buckets == [[], [], []]


def test_invalid_worker_count_raises():
    with pytest.raises(ValueError):
        distribute_round_robin([1, 2, 3], worker_count=0)


def test_original_order_preserved_within_each_bucket():
    """Round-robin must not reorder items assigned to the same worker -
    this matters because the caller re-sorts by original index afterward,
    and a scrambled-within-bucket order would still pass that resort, but
    is worth pinning down as the intended distribution shape."""
    items = list(range(20))
    buckets = distribute_round_robin(items, worker_count=4)
    for bucket in buckets:
        assert bucket == sorted(bucket)


def test_indexed_reassembly_restores_original_order():
    """Mirrors what tests.runner._run_parallel does: distribute
    (index, item) pairs, simulate out-of-order completion, then sort back
    by original index."""
    items = ["A", "B", "C", "D", "E"]
    indexed = list(enumerate(items))
    buckets = distribute_round_robin(indexed, worker_count=2)

    # Simulate worker 2 finishing before worker 1 (out-of-order completion)
    completion_order = list(reversed(buckets))
    flattened = [pair for bucket in completion_order for pair in bucket]

    flattened.sort(key=lambda pair: pair[0])
    assert [item for _, item in flattened] == items
