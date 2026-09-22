import asyncio
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow_base import WorkflowContext, StageState, WorkflowTask, EventBus, CancellationToken
from workflow_stages_1 import execute_episode_full_pipeline

class MockManager:
    def __init__(self):
        self.events = []
    def get_cancel_token(self, task_id):
        return CancellationToken()
    async def save_and_broadcast(self, event_name, task):
        self.events.append((event_name, getattr(task, 'current_episode', None)))
    async def calculate_overall_progress(self, task):
        pass

class TestCascadingPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_cascading_execution_order(self):
        """Verify that episode N+1 only starts after episode N finishes Stage 2."""
        episodes = [1, 2, 3]
        s2_events = [asyncio.Event() for _ in episodes]
        
        execution_order = []
        
        async def mock_s2(ep, context, browser_context, nav_manager, dl_sem):
            execution_order.append((f"start_s2_ep_{ep}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05) # simulate crawl time
            execution_order.append((f"end_s2_ep_{ep}", asyncio.get_event_loop().time()))
            return True

        async def mock_subsequent_stages(ep, context, sem=None):
            execution_order.append((f"start_later_stages_ep_{ep}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.1) # simulate later stages time
            execution_order.append((f"end_later_stages_ep_{ep}", asyncio.get_event_loop().time()))
            return True

        import workflow_stages_1
        import workflow_stages_2
        
        orig_s2 = workflow_stages_1.execute_single_episode_stage2
        orig_s2b = workflow_stages_1.execute_single_episode_stage2b
        orig_s3 = workflow_stages_1.execute_single_episode_stage3
        orig_s4 = workflow_stages_1.execute_single_episode_stage4
        orig_s5 = workflow_stages_1.execute_single_episode_stage5
        orig_s6 = workflow_stages_2.execute_single_episode_stage6
        orig_s7 = workflow_stages_2.execute_single_episode_stage7
        orig_s8 = workflow_stages_2.execute_single_episode_stage8
        orig_s9 = workflow_stages_2.execute_single_episode_stage9
        orig_s10 = workflow_stages_2.execute_single_episode_stage10

        try:
            workflow_stages_1.execute_single_episode_stage2 = mock_s2
            workflow_stages_1.execute_single_episode_stage2b = mock_subsequent_stages
            workflow_stages_1.execute_single_episode_stage3 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)
            workflow_stages_1.execute_single_episode_stage4 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)
            workflow_stages_1.execute_single_episode_stage5 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)
            workflow_stages_2.execute_single_episode_stage6 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)
            workflow_stages_2.execute_single_episode_stage7 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)
            workflow_stages_2.execute_single_episode_stage8 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)
            workflow_stages_2.execute_single_episode_stage9 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)
            workflow_stages_2.execute_single_episode_stage10 = lambda ep, ctx, *args, **kwargs: asyncio.sleep(0.01, result=True)

            task = WorkflowTask(
                comic_title="Test Comic",
                comic_url="https://example.com/comic",
                from_episode=1,
                to_episode=3,
                payload={},
                id="test_cascade_task"
            )
            mock_mgr = MockManager()
            context = WorkflowContext(
                task=task,
                config={},
                manager=mock_mgr
            )

            crawl_lock = asyncio.Lock()
            sem = asyncio.Semaphore(5)

            pipe_tasks = []
            for idx, ep in enumerate(episodes):
                prev_event = s2_events[idx - 1] if idx > 0 else None
                curr_event = s2_events[idx]
                pipe_tasks.append(
                    execute_episode_full_pipeline(
                        ep, context, crawl_lock, None, None,
                        sem, sem, sem, sem, sem, sem, sem,
                        prev_s2_done_event=prev_event,
                        s2_done_event=curr_event
                    )
                )

            results = await asyncio.gather(*pipe_tasks)
            self.assertTrue(all(results))

            action_names = [x[0] for x in execution_order]
            
            # 1. Ep 1 starts S2 first
            self.assertEqual(action_names[0], "start_s2_ep_1")
            
            # 2. Ep 2 starts S2 ONLY AFTER Ep 1 finishes S2
            idx_end_s2_ep1 = action_names.index("end_s2_ep_1")
            idx_start_s2_ep2 = action_names.index("start_s2_ep_2")
            self.assertGreater(idx_start_s2_ep2, idx_end_s2_ep1, "Ep 2 should start S2 after Ep 1 finishes S2")

            # 3. Ep 3 starts S2 ONLY AFTER Ep 2 finishes S2
            idx_end_s2_ep2 = action_names.index("end_s2_ep_2")
            idx_start_s2_ep3 = action_names.index("start_s2_ep_3")
            self.assertGreater(idx_start_s2_ep3, idx_end_s2_ep2, "Ep 3 should start S2 after Ep 2 finishes S2")

            # 4. While Ep 2 is running S2, Ep 1 is running later stages in parallel!
            idx_start_later_ep1 = action_names.index("start_later_stages_ep_1")
            self.assertLess(idx_start_later_ep1, idx_end_s2_ep2)

            print("\nCascading order verified:")
            for a, t in execution_order:
                print(f"  {a}")

        finally:
            workflow_stages_1.execute_single_episode_stage2 = orig_s2
            workflow_stages_1.execute_single_episode_stage2b = orig_s2b
            workflow_stages_1.execute_single_episode_stage3 = orig_s3
            workflow_stages_1.execute_single_episode_stage4 = orig_s4
            workflow_stages_1.execute_single_episode_stage5 = orig_s5
            workflow_stages_2.execute_single_episode_stage6 = orig_s6
            workflow_stages_2.execute_single_episode_stage7 = orig_s7
            workflow_stages_2.execute_single_episode_stage8 = orig_s8
            workflow_stages_2.execute_single_episode_stage9 = orig_s9
            workflow_stages_2.execute_single_episode_stage10 = orig_s10

if __name__ == "__main__":
    unittest.main()
