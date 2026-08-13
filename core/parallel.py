"""
Pure helper for splitting test cases across worker processes - kept
separate from tests/runner.py's multiprocessing wiring so it's testable
without spinning up real processes (see tests/unit/test_parallel.py).
"""


def distribute_round_robin(items: list, worker_count: int) -> list:
    """Splits items into worker_count buckets, round-robin, preserving each
    bucket's relative order. Returns a list of worker_count lists. Empty
    buckets are possible if there are fewer items than workers."""
    if worker_count < 1:
        raise ValueError(f"worker_count must be >= 1, got {worker_count}")
    buckets = [[] for _ in range(worker_count)]
    for i, item in enumerate(items):
        buckets[i % worker_count].append(item)
    return buckets
