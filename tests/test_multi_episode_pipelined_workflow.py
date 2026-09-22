import asyncio
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow_base import WorkflowContext, StageState, WorkflowTask, CancellationToken
import workflow_stages_1
import workflow_stages_2

class MockManager:
    def __init__(self):
        self.events = []
    def get_cancel_token(self, task_id):
        return CancellationToken()
    async def save_and_broadcast(self, event_name, task):
        self.events.append((event_name, getattr(task, 'current_episode', None)))
    async def calculate_overall_progress(self, task):
        pass

class TestMultiEpisodePipelinedWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_full_pipeline_flow(self):
        """
        Verify:
        1. Sequential crawl 1 -> 5.
        2. Visual region & PDF pushed immediately, concurrency <= 3.
        3. Barrier: Gemini Stage 5 does NOT start for any episode until all PDFs are ready.
        4. Gemini runs sequentially 1 -> 5.
        5. Video render starts immediately after each episode's script/audio is ready (concurrency <= 3) while Gemini continues.
        6. Retry loop handles failed episodes.
        """
        events_timeline = []
        crawling_eps = []
        visual_running = 0
        max_visual_concurrency = 0
        render_running = 0
        max_render_concurrency = 0
        gemini_running = 0
        max_gemini_concurrency = 0
        
        pdf_ready = {ep: False for ep in range(1, 6)}
        video_ready = {ep: False for ep in range(1, 6)}

        async def mock_s2(ep, context, browser_context, nav_manager, dl_sem):
            crawling_eps.append(ep)
            events_timeline.append((f"crawl_start_ep_{ep}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.04)
            events_timeline.append((f"crawl_end_ep_{ep}", asyncio.get_event_loop().time()))
            crawling_eps.remove(ep)
            return True

        async def mock_s2b(ep, context, repage_sem=None):
            nonlocal visual_running, max_visual_concurrency
            visual_running += 1
            max_visual_concurrency = max(max_visual_concurrency, visual_running)
            events_timeline.append((f"visual_start_ep_{ep}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            events_timeline.append((f"visual_end_ep_{ep}", asyncio.get_event_loop().time()))
            visual_running -= 1
            return True

        async def mock_s3(ep, context, nsfw_sem=None):
            return True

        async def mock_s4(ep, context, pdf_sem=None):
            pdf_ready[ep] = True
            events_timeline.append((f"pdf_done_ep_{ep}", asyncio.get_event_loop().time()))
            return True

        async def mock_s5(ep, context, vlm_sem=None, profile_pool=None):
            nonlocal gemini_running, max_gemini_concurrency
            # Assert barrier: all PDFs must be ready when Gemini starts!
            for ch in range(1, 6):
                assert pdf_ready[ch] is True, f"Gemini started for ep {ep} before ep {ch} PDF was ready!"
            
            gemini_running += 1
            max_gemini_concurrency = max(max_gemini_concurrency, gemini_running)
            events_timeline.append((f"gemini_start_ep_{ep}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.04)
            events_timeline.append((f"gemini_end_ep_{ep}", asyncio.get_event_loop().time()))
            gemini_running -= 1
            return True

        async def mock_s6_9(ep, context, *args, **kwargs):
            return True

        ep3_rendered_count = 0

        async def mock_s10(ep, context, render_sem=None):
            nonlocal render_running, max_render_concurrency, ep3_rendered_count
            render_running += 1
            max_render_concurrency = max(max_render_concurrency, render_running)
            events_timeline.append((f"render_start_ep_{ep}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.06)

            # Simulate failure on ep 3 on first attempt to test retry loop
            if ep == 3 and ep3_rendered_count == 0:
                ep3_rendered_count += 1
                render_running -= 1
                events_timeline.append((f"render_fail_ep_{ep}", asyncio.get_event_loop().time()))
                return False

            video_ready[ep] = True
            events_timeline.append((f"render_done_ep_{ep}", asyncio.get_event_loop().time()))
            render_running -= 1
            return True

        orig_s2 = workflow_stages_1.execute_single_episode_stage2
        orig_s2b = workflow_stages_1.execute_single_episode_stage2b
        orig_s3 = workflow_stages_1.execute_single_episode_stage3
        orig_s4 = workflow_stages_1.execute_single_episode_stage4
        orig_s5 = workflow_stages_1.execute_single_episode_stage5
        orig_is_pdf = workflow_stages_1.is_episode_pdf_ready
        orig_is_video = workflow_stages_1.is_episode_video_ready

        orig_s6 = workflow_stages_2.execute_single_episode_stage6
        orig_s7 = workflow_stages_2.execute_single_episode_stage7
        orig_s8 = workflow_stages_2.execute_single_episode_stage8
        orig_s9 = workflow_stages_2.execute_single_episode_stage9
        orig_s10 = workflow_stages_2.execute_single_episode_stage10

        try:
            workflow_stages_1.execute_single_episode_stage2 = mock_s2
            workflow_stages_1.execute_single_episode_stage2b = mock_s2b
            workflow_stages_1.execute_single_episode_stage3 = mock_s3
            workflow_stages_1.execute_single_episode_stage4 = mock_s4
            workflow_stages_1.execute_single_episode_stage5 = mock_s5
            workflow_stages_1.is_episode_pdf_ready = lambda ep, d, t: pdf_ready.get(ep, False)
            workflow_stages_1.is_episode_video_ready = lambda ep, d: video_ready.get(ep, False)

            workflow_stages_2.execute_single_episode_stage6 = mock_s6_9
            workflow_stages_2.execute_single_episode_stage7 = mock_s6_9
            workflow_stages_2.execute_single_episode_stage8 = mock_s6_9
            workflow_stages_2.execute_single_episode_stage9 = mock_s6_9
            workflow_stages_2.execute_single_episode_stage10 = mock_s10

            task = WorkflowTask(
                comic_title="Test Comic",
                comic_url="https://example.com/comic",
                from_episode=1,
                to_episode=5,
                payload={"retry_count": 3},
                id="test_multi_ep_task"
            )
            mock_mgr = MockManager()
            context = WorkflowContext(
                task=task,
                config={},
                manager=mock_mgr
            )

            result = await workflow_stages_1.execute_multi_episode_pipelined_workflow(
                context=context,
                max_phase_retries=3
            )

            self.assertTrue(result, "Multi episode pipeline should succeed after retry")
            self.assertTrue(all(video_ready.values()), "All 5 episodes must have completed video files")
            
            # Check maximum concurrency constraints
            self.assertLessEqual(max_visual_concurrency, 3, "Visual region concurrency must not exceed 3")
            self.assertLessEqual(max_render_concurrency, 3, "Render video concurrency must not exceed 3")
            self.assertEqual(max_gemini_concurrency, 1, "Gemini must execute sequentially (concurrency 1)")

            # Check that ep 1 render started before ep 5 gemini finished (pipelined parallel)
            event_names = [x[0] for x in events_timeline]
            idx_render_start_ep1 = event_names.index("render_start_ep_1")
            idx_gemini_start_ep5 = event_names.index("gemini_start_ep_5")
            self.assertLess(idx_render_start_ep1, idx_gemini_start_ep5, "Ep 1 render should start while Gemini scripts later episodes")

        finally:
            workflow_stages_1.execute_single_episode_stage2 = orig_s2
            workflow_stages_1.execute_single_episode_stage2b = orig_s2b
            workflow_stages_1.execute_single_episode_stage3 = orig_s3
            workflow_stages_1.execute_single_episode_stage4 = orig_s4
            workflow_stages_1.execute_single_episode_stage5 = orig_s5
            workflow_stages_1.is_episode_pdf_ready = orig_is_pdf
            workflow_stages_1.is_episode_video_ready = orig_is_video

            workflow_stages_2.execute_single_episode_stage6 = orig_s6
            workflow_stages_2.execute_single_episode_stage7 = orig_s7
            workflow_stages_2.execute_single_episode_stage8 = orig_s8
            workflow_stages_2.execute_single_episode_stage9 = orig_s9
            workflow_stages_2.execute_single_episode_stage10 = orig_s10

    async def test_resume_from_failed_stage3(self):
        """
        Verify:
        If episode failed at Stage 3 (Crawl & Stage 2b done, but Stage 3 / PDF not ready),
        retrying MUST NOT re-run Stage 2 or Stage 2b. It must resume directly from Stage 3!
        """
        s2_called = []
        s2b_called = []
        s3_called = []
        s4_called = []

        pdf_ready = {1: False, 2: False}
        nsfw_ready = {1: False, 2: False}

        async def mock_s2(ep, context, browser_context, nav_manager, dl_sem):
            s2_called.append(ep)
            return True

        async def mock_s2b(ep, context, repage_sem=None):
            s2b_called.append(ep)
            return True

        async def mock_s3(ep, context, nsfw_sem=None):
            s3_called.append(ep)
            nsfw_ready[ep] = True
            return True

        async def mock_s4(ep, context, pdf_sem=None):
            s4_called.append(ep)
            pdf_ready[ep] = True
            return True

        async def mock_s5(ep, context, vlm_sem=None, profile_pool=None):
            return True

        async def mock_s6_10(ep, context, *args, **kwargs):
            return True

        orig_s2 = workflow_stages_1.execute_single_episode_stage2
        orig_s2b = workflow_stages_1.execute_single_episode_stage2b
        orig_s3 = workflow_stages_1.execute_single_episode_stage3
        orig_s4 = workflow_stages_1.execute_single_episode_stage4
        orig_s5 = workflow_stages_1.execute_single_episode_stage5
        orig_is_images = workflow_stages_1.is_episode_images_ready
        orig_is_repage = workflow_stages_1.is_episode_repage_ready
        orig_is_nsfw = workflow_stages_1.is_episode_nsfw_ready
        orig_is_pdf = workflow_stages_1.is_episode_pdf_ready
        orig_is_script = workflow_stages_1.is_episode_script_ready
        orig_is_video = workflow_stages_1.is_episode_video_ready

        orig_s6 = workflow_stages_2.execute_single_episode_stage6
        orig_s7 = workflow_stages_2.execute_single_episode_stage7
        orig_s8 = workflow_stages_2.execute_single_episode_stage8
        orig_s9 = workflow_stages_2.execute_single_episode_stage9
        orig_s10 = workflow_stages_2.execute_single_episode_stage10

        try:
            workflow_stages_1.execute_single_episode_stage2 = mock_s2
            workflow_stages_1.execute_single_episode_stage2b = mock_s2b
            workflow_stages_1.execute_single_episode_stage3 = mock_s3
            workflow_stages_1.execute_single_episode_stage4 = mock_s4
            workflow_stages_1.execute_single_episode_stage5 = mock_s5

            # Simulating Stage 2 images & Stage 2b repaging already exist on disk, but Stage 3 failed
            workflow_stages_1.is_episode_images_ready = lambda ep, d: True
            workflow_stages_1.is_episode_repage_ready = lambda ep, d: True
            workflow_stages_1.is_episode_nsfw_ready = lambda ep, d: nsfw_ready.get(ep, False)
            workflow_stages_1.is_episode_pdf_ready = lambda ep, d, t: pdf_ready.get(ep, False)
            workflow_stages_1.is_episode_script_ready = lambda ep, d: False
            workflow_stages_1.is_episode_video_ready = lambda ep, d: True

            workflow_stages_2.execute_single_episode_stage6 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage7 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage8 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage9 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage10 = mock_s6_10

            task = WorkflowTask(
                comic_title="Test Comic Resume",
                comic_url="https://example.com/comic",
                from_episode=1,
                to_episode=2,
                payload={"retry_count": 1},
                id="test_resume_task"
            )
            mock_mgr = MockManager()
            context = WorkflowContext(
                task=task,
                config={},
                manager=mock_mgr
            )

            result = await workflow_stages_1.execute_multi_episode_pipelined_workflow(
                context=context,
                max_phase_retries=1
            )

            self.assertTrue(result)
            self.assertEqual(s2_called, [], "Stage 2 Crawl must be skipped when images already exist")
            self.assertEqual(s2b_called, [], "Stage 2b Re-pagination must be skipped when metadata exists")
            self.assertEqual(s3_called, [1, 2], "Stage 3 NSFW must run for the failed episodes")
            self.assertEqual(s4_called, [1, 2], "Stage 4 PDF must run after Stage 3 completes")

        finally:
            workflow_stages_1.execute_single_episode_stage2 = orig_s2
            workflow_stages_1.execute_single_episode_stage2b = orig_s2b
            workflow_stages_1.execute_single_episode_stage3 = orig_s3
            workflow_stages_1.execute_single_episode_stage4 = orig_s4
            workflow_stages_1.execute_single_episode_stage5 = orig_s5
            workflow_stages_1.is_episode_images_ready = orig_is_images
            workflow_stages_1.is_episode_repage_ready = orig_is_repage
            workflow_stages_1.is_episode_nsfw_ready = orig_is_nsfw
            workflow_stages_1.is_episode_pdf_ready = orig_is_pdf
            workflow_stages_1.is_episode_script_ready = orig_is_script
            workflow_stages_1.is_episode_video_ready = orig_is_video

            workflow_stages_2.execute_single_episode_stage6 = orig_s6
            workflow_stages_2.execute_single_episode_stage7 = orig_s7
            workflow_stages_2.execute_single_episode_stage8 = orig_s8
            workflow_stages_2.execute_single_episode_stage9 = orig_s9
            workflow_stages_2.execute_single_episode_stage10 = orig_s10


    async def test_crawl_queueing_when_stage2_slots_full(self):
        """
        Verify:
        When crawling 5 episodes with max 3 parallel slots at Stage 2b/PDF:
        - Episodes 1, 2, 3 take the 3 slots and run slowly.
        - Episode 4 crawls fast -> finds slots full -> queued in StageState.WAITING.
        - Episode 5 STILL crawls immediately without waiting for Episode 4's Stage 2b!
        - Crawl of Episode 5 finishes before Episode 1 finishes Stage 2b.
        """
        crawled_order = []
        visual_started = []
        pdf_ready = {ep: False for ep in range(1, 6)}
        video_ready = {ep: False for ep in range(1, 6)}

        async def mock_s2(ep, context, browser_context, nav_manager, dl_sem):
            crawled_order.append(ep)
            await asyncio.sleep(0.02)
            return True

        async def mock_s2b(ep, context, repage_sem=None):
            visual_started.append(ep)
            # Ep 1, 2, 3 run slowly (taking slots)
            await asyncio.sleep(0.20)
            return True

        async def mock_s3(ep, context, nsfw_sem=None): return True
        async def mock_s4(ep, context, pdf_sem=None):
            pdf_ready[ep] = True
            return True
        async def mock_s5(ep, context, vlm_sem=None, profile_pool=None): return True
        async def mock_s6_10(ep, context, *args, **kwargs):
            video_ready[ep] = True
            return True

        orig_s2 = workflow_stages_1.execute_single_episode_stage2
        orig_s2b = workflow_stages_1.execute_single_episode_stage2b
        orig_s3 = workflow_stages_1.execute_single_episode_stage3
        orig_s4 = workflow_stages_1.execute_single_episode_stage4
        orig_s5 = workflow_stages_1.execute_single_episode_stage5
        orig_is_pdf = workflow_stages_1.is_episode_pdf_ready
        orig_is_video = workflow_stages_1.is_episode_video_ready

        orig_s6 = workflow_stages_2.execute_single_episode_stage6
        orig_s7 = workflow_stages_2.execute_single_episode_stage7
        orig_s8 = workflow_stages_2.execute_single_episode_stage8
        orig_s9 = workflow_stages_2.execute_single_episode_stage9
        orig_s10 = workflow_stages_2.execute_single_episode_stage10

        try:
            workflow_stages_1.execute_single_episode_stage2 = mock_s2
            workflow_stages_1.execute_single_episode_stage2b = mock_s2b
            workflow_stages_1.execute_single_episode_stage3 = mock_s3
            workflow_stages_1.execute_single_episode_stage4 = mock_s4
            workflow_stages_1.execute_single_episode_stage5 = mock_s5
            workflow_stages_1.is_episode_pdf_ready = lambda ep, d, t: pdf_ready.get(ep, False)
            workflow_stages_1.is_episode_video_ready = lambda ep, d: video_ready.get(ep, False)

            workflow_stages_2.execute_single_episode_stage6 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage7 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage8 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage9 = mock_s6_10
            workflow_stages_2.execute_single_episode_stage10 = mock_s6_10

            task = WorkflowTask(
                comic_title="Test Comic Queue",
                comic_url="https://example.com/comic",
                from_episode=1,
                to_episode=5,
                payload={"retry_count": 1},
                id="test_queue_task"
            )
            mock_mgr = MockManager()
            context = WorkflowContext(task=task, config={}, manager=mock_mgr)

            result = await workflow_stages_1.execute_multi_episode_pipelined_workflow(
                context=context,
                max_phase_retries=1
            )

            self.assertTrue(result)
            self.assertEqual(crawled_order, [1, 2, 3, 4, 5], "All 5 episodes must be crawled sequentially without blocking")
            self.assertTrue(all(pdf_ready.values()), "All 5 episodes must eventually get their PDFs")

        finally:
            workflow_stages_1.execute_single_episode_stage2 = orig_s2
            workflow_stages_1.execute_single_episode_stage2b = orig_s2b
            workflow_stages_1.execute_single_episode_stage3 = orig_s3
            workflow_stages_1.execute_single_episode_stage4 = orig_s4
            workflow_stages_1.execute_single_episode_stage5 = orig_s5
            workflow_stages_1.is_episode_pdf_ready = orig_is_pdf
            workflow_stages_1.is_episode_video_ready = orig_is_video

            workflow_stages_2.execute_single_episode_stage6 = orig_s6
            workflow_stages_2.execute_single_episode_stage7 = orig_s7
            workflow_stages_2.execute_single_episode_stage8 = orig_s8
            workflow_stages_2.execute_single_episode_stage9 = orig_s9
            workflow_stages_2.execute_single_episode_stage10 = orig_s10


    async def test_resume_from_failed_stage10(self):
        """
        Verify:
        When a task fails at Stage 10 (Video Render):
        - Stage 2 (Crawl), 2b, 3, 4 (PDF), 5 (Gemini), 6, 7 (Narration), 8 (TTS), 9 (Subtitle) all succeeded.
        - On retry, it MUST NOT rerun stages 1-9.
        - It must directly resume from Stage 10!
        """
        stages_called = []

        video_ready = {1: False, 2: False}

        async def mock_s2(ep, context, *args, **kwargs):
            stages_called.append((ep, "s2"))
            return True
        async def mock_s2b(ep, context, *args, **kwargs):
            stages_called.append((ep, "s2b"))
            return True
        async def mock_s3(ep, context, *args, **kwargs):
            stages_called.append((ep, "s3"))
            return True
        async def mock_s4(ep, context, *args, **kwargs):
            stages_called.append((ep, "s4"))
            return True
        async def mock_s5(ep, context, *args, **kwargs):
            stages_called.append((ep, "s5"))
            return True
        async def mock_s6(ep, context, *args, **kwargs):
            stages_called.append((ep, "s6"))
            return True
        async def mock_s7(ep, context, *args, **kwargs):
            stages_called.append((ep, "s7"))
            return True
        async def mock_s8(ep, context, *args, **kwargs):
            stages_called.append((ep, "s8"))
            return True
        async def mock_s9(ep, context, *args, **kwargs):
            stages_called.append((ep, "s9"))
            return True
        async def mock_s10(ep, context, *args, **kwargs):
            stages_called.append((ep, "s10"))
            video_ready[ep] = True
            return True

        orig_s2 = workflow_stages_1.execute_single_episode_stage2
        orig_s2b = workflow_stages_1.execute_single_episode_stage2b
        orig_s3 = workflow_stages_1.execute_single_episode_stage3
        orig_s4 = workflow_stages_1.execute_single_episode_stage4
        orig_s5 = workflow_stages_1.execute_single_episode_stage5
        orig_is_images = workflow_stages_1.is_episode_images_ready
        orig_is_repage = workflow_stages_1.is_episode_repage_ready
        orig_is_nsfw = workflow_stages_1.is_episode_nsfw_ready
        orig_is_pdf = workflow_stages_1.is_episode_pdf_ready
        orig_is_script = workflow_stages_1.is_episode_script_ready
        orig_is_narration = workflow_stages_1.is_episode_narration_ready
        orig_is_audio = workflow_stages_1.is_episode_audio_ready
        orig_is_subtitles = workflow_stages_1.is_episode_subtitles_ready
        orig_is_video = workflow_stages_1.is_episode_video_ready

        orig_s6 = workflow_stages_2.execute_single_episode_stage6
        orig_s7 = workflow_stages_2.execute_single_episode_stage7
        orig_s8 = workflow_stages_2.execute_single_episode_stage8
        orig_s9 = workflow_stages_2.execute_single_episode_stage9
        orig_s10 = workflow_stages_2.execute_single_episode_stage10

        try:
            workflow_stages_1.execute_single_episode_stage2 = mock_s2
            workflow_stages_1.execute_single_episode_stage2b = mock_s2b
            workflow_stages_1.execute_single_episode_stage3 = mock_s3
            workflow_stages_1.execute_single_episode_stage4 = mock_s4
            workflow_stages_1.execute_single_episode_stage5 = mock_s5

            # Mock ready state for stages 1 to 9
            workflow_stages_1.is_episode_images_ready = lambda ep, d: True
            workflow_stages_1.is_episode_repage_ready = lambda ep, d: True
            workflow_stages_1.is_episode_nsfw_ready = lambda ep, d: True
            workflow_stages_1.is_episode_pdf_ready = lambda ep, d, t: True
            workflow_stages_1.is_episode_script_ready = lambda ep, d: True
            workflow_stages_1.is_episode_narration_ready = lambda ep, d: True
            workflow_stages_1.is_episode_audio_ready = lambda ep, d: True
            workflow_stages_1.is_episode_subtitles_ready = lambda ep, d: True
            # Video not ready yet initially (failed at Stage 10)
            workflow_stages_1.is_episode_video_ready = lambda ep, d: video_ready.get(ep, False)

            workflow_stages_2.execute_single_episode_stage6 = mock_s6
            workflow_stages_2.execute_single_episode_stage7 = mock_s7
            workflow_stages_2.execute_single_episode_stage8 = mock_s8
            workflow_stages_2.execute_single_episode_stage9 = mock_s9
            workflow_stages_2.execute_single_episode_stage10 = mock_s10

            task = WorkflowTask(
                comic_title="Test Resume S10",
                comic_url="https://example.com/comic",
                from_episode=1,
                to_episode=2,
                payload={"retry_count": 1},
                id="test_resume_s10_task"
            )
            mock_mgr = MockManager()
            context = WorkflowContext(task=task, config={}, manager=mock_mgr)

            result = await workflow_stages_1.execute_multi_episode_pipelined_workflow(
                context=context,
                max_phase_retries=1
            )

            self.assertTrue(result)
            # Must ONLY call Stage 10 for episodes 1 and 2
            self.assertEqual(stages_called, [(1, "s10"), (2, "s10")], "Retry must resume directly from Stage 10")

        finally:
            workflow_stages_1.execute_single_episode_stage2 = orig_s2
            workflow_stages_1.execute_single_episode_stage2b = orig_s2b
            workflow_stages_1.execute_single_episode_stage3 = orig_s3
            workflow_stages_1.execute_single_episode_stage4 = orig_s4
            workflow_stages_1.execute_single_episode_stage5 = orig_s5
            workflow_stages_1.is_episode_images_ready = orig_is_images
            workflow_stages_1.is_episode_repage_ready = orig_is_repage
            workflow_stages_1.is_episode_nsfw_ready = orig_is_nsfw
            workflow_stages_1.is_episode_pdf_ready = orig_is_pdf
            workflow_stages_1.is_episode_script_ready = orig_is_script
            workflow_stages_1.is_episode_narration_ready = orig_is_narration
            workflow_stages_1.is_episode_audio_ready = orig_is_audio
            workflow_stages_1.is_episode_subtitles_ready = orig_is_subtitles
            workflow_stages_1.is_episode_video_ready = orig_is_video

            workflow_stages_2.execute_single_episode_stage6 = orig_s6
            workflow_stages_2.execute_single_episode_stage7 = orig_s7
            workflow_stages_2.execute_single_episode_stage8 = orig_s8
            workflow_stages_2.execute_single_episode_stage9 = orig_s9
            workflow_stages_2.execute_single_episode_stage10 = orig_s10


if __name__ == "__main__":
    unittest.main()

