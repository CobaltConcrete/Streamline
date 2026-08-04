from codirector.core.backpressure import BoundedDropOldestQueue


async def test_bounded_queue_drops_oldest():
    q = BoundedDropOldestQueue(maxsize=3)
    for i in range(5):
        q.put_nowait(i)
    assert q.drop_count == 2
    assert q.qsize() == 3
    remaining = [await q.get() for _ in range(3)]
    assert remaining == [2, 3, 4]  # 0 and 1 were dropped as oldest
