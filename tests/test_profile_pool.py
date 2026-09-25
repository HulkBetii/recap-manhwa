import pytest
import asyncio
from app import ChromeProfileWorker, ChromeProfilePoolManager

@pytest.mark.asyncio
async def test_chrome_profile_worker_state():
    worker = ChromeProfileWorker(profile_path="C:\\Data\\TestProfile", index=0)
    assert worker.index == 0
    assert worker.profile_path == "C:\\Data\\TestProfile"
    assert not worker.is_busy
    assert not worker.is_limited

@pytest.mark.asyncio
async def test_chrome_profile_pool_manager_singleton():
    pool1 = ChromeProfilePoolManager.get_instance()
    pool2 = ChromeProfilePoolManager.get_instance()
    assert pool1 is pool2

@pytest.mark.asyncio
async def test_chrome_profile_pool_acquire_and_release():
    pool = ChromeProfilePoolManager()
    worker1 = ChromeProfileWorker(profile_path="P1", index=0)
    worker2 = ChromeProfileWorker(profile_path="P2", index=1)
    pool.workers = [worker1, worker2]

    # Acquire first worker
    w1 = await pool.acquire_worker()
    assert w1 is worker1
    assert w1.is_busy

    # Acquire second worker
    w2 = await pool.acquire_worker()
    assert w2 is worker2
    assert w2.is_busy

    # Third acquire should return None (all busy)
    w3 = await pool.acquire_worker()
    assert w3 is None

    # Release worker1
    pool.release_worker(w1)
    assert not w1.is_busy

    # Now acquire should get worker1
    w_reacquired = await pool.acquire_worker()
    assert w_reacquired is worker1
    assert w_reacquired.is_busy
