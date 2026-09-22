import asyncio
import unittest
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chrome_profile_pool import ChromeProfilePool, ProfileSession


class TestChromeProfilePool(unittest.IsolatedAsyncioTestCase):
    async def test_pool_initialization_and_deduplication(self):
        profiles = ["/path/to/profile1", "/path/to/profile2", "/path/to/profile1", "/path/to/profile3"]
        pool = ChromeProfilePool(profiles=profiles, headless=True)
        
        self.assertEqual(pool.total_profiles, 3)
        self.assertEqual(pool.available_count, 3)
        self.assertEqual(pool.profiles, ["/path/to/profile1", "/path/to/profile2", "/path/to/profile3"])

    async def test_concurrent_profile_acquisition(self):
        """Verify that N tasks acquire N distinct profiles simultaneously."""
        profiles = ["/tmp/prof_a", "/tmp/prof_b", "/tmp/prof_c"]
        pool = ChromeProfilePool(profiles=profiles, headless=True)

        # Mock _launch_profile_context so it doesn't actually launch Chrome
        async def mock_launch(profile_path, headless=None):
            return "mock_browser", f"mock_ctx_{profile_path}"

        pool._launch_profile_context = mock_launch

        acquired_profiles = []
        active_at_same_time = []

        async def worker(worker_id):
            async with pool.acquire() as session:
                acquired_profiles.append((worker_id, session.profile_path))
                active_at_same_time.append(session.profile_path)
                await asyncio.sleep(0.05)
                active_at_same_time.remove(session.profile_path)

        tasks = [worker(i) for i in range(3)]
        await asyncio.gather(*tasks)

        # All 3 workers must have acquired 3 distinct profiles
        assigned_profiles = [p[1] for p in acquired_profiles]
        self.assertEqual(len(set(assigned_profiles)), 3)
        self.assertEqual(pool.available_count, 3)

    async def test_profile_reuse_and_fifo_queue(self):
        """Verify that when 4 tasks compete for 2 profiles, they run in 2 batches."""
        profiles = ["/tmp/prof_1", "/tmp/prof_2"]
        pool = ChromeProfilePool(profiles=profiles, headless=True)

        async def mock_launch(profile_path, headless=None):
            return "mock_browser", f"mock_ctx_{profile_path}"

        pool._launch_profile_context = mock_launch

        history = []

        async def worker(worker_id):
            async with pool.acquire() as session:
                history.append((f"start_w_{worker_id}", session.profile_path, time.time()))
                await asyncio.sleep(0.04)
                history.append((f"end_w_{worker_id}", session.profile_path, time.time()))

        tasks = [worker(i) for i in range(4)]
        await asyncio.gather(*tasks)

        self.assertEqual(len(history), 8)
        self.assertEqual(pool.available_count, 2)

    async def test_cooldown_and_rate_limit_rotation(self):
        """Verify that rate limited profiles are bypassed in favor of ready profiles."""
        profiles = ["/tmp/prof_limited", "/tmp/prof_ready"]
        pool = ChromeProfilePool(profiles=profiles, headless=True)

        async def mock_launch(profile_path, headless=None):
            return "mock_browser", f"mock_ctx_{profile_path}"

        pool._launch_profile_context = mock_launch

        # Mark first profile as rate limited
        pool.mark_rate_limited("/tmp/prof_limited", cooldown_seconds=300)
        self.assertTrue(pool.is_in_cooldown("/tmp/prof_limited"))
        self.assertFalse(pool.is_in_cooldown("/tmp/prof_ready"))

        async with pool.acquire() as session:
            # Should automatically skip the limited profile and acquire the ready one!
            self.assertEqual(session.profile_path, "/tmp/prof_ready")

    async def test_close_all_cleanup(self):
        profiles = ["/tmp/prof_1"]
        pool = ChromeProfilePool(profiles=profiles, headless=True)
        
        class MockCtx:
            def __init__(self):
                self.closed = False
            async def close(self):
                self.closed = True

        mock_c = MockCtx()
        pool._contexts["/tmp/prof_1"] = ("mock_b", mock_c)

        await pool.close_all()
        self.assertTrue(mock_c.closed)
        self.assertEqual(len(pool._contexts), 0)


if __name__ == "__main__":
    unittest.main()
