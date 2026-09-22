import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow_base import WorkflowContext, StageState, WorkflowTask, CancellationToken
from workflow_stages_1 import execute_single_episode_stage5

class MockManager:
    def __init__(self):
        self.events = []
    def get_cancel_token(self, task_id):
        return CancellationToken()
    async def save_and_broadcast(self, event_name, task):
        self.events.append((event_name, getattr(task, 'current_episode', None)))
    async def calculate_overall_progress(self, task):
        pass

class TestStage5RetryMechanism(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.download_dir = os.path.abspath("tests_scratch_stage5")
        os.makedirs(os.path.join(self.download_dir, "episode_1", "pdf"), exist_ok=True)
        os.makedirs(os.path.join(self.download_dir, "episode_1", "images"), exist_ok=True)
        os.makedirs(os.path.join(self.download_dir, "episode_1", "images_pdf"), exist_ok=True)
        with open(os.path.join(self.download_dir, "episode_1", "images", "001.jpg"), "wb") as f:
            f.write(b"dummy")
        with open(os.path.join(self.download_dir, "episode_1", "images_pdf", "001.jpg"), "wb") as f:
            f.write(b"dummy")
        with open(os.path.join(self.download_dir, "episode_1", "pdf", "Test_Comic_Tap_1.pdf"), "wb") as f:
            f.write(b"%PDF-dummy")

        task = WorkflowTask(
            comic_title="Test Comic",
            comic_url="http://example.com",
            from_episode=1,
            to_episode=1,
            payload={"language": "vi", "timeout": 3, "headless": True},
            id="test_task"
        )
        task.artifacts = {"download_dir": self.download_dir, "comic_title": "Test Comic"}
        manager = MockManager()
        self.context = WorkflowContext(task=task, config={}, manager=manager)

    async def asyncTearDown(self):
        import shutil
        if os.path.exists(self.download_dir):
            shutil.rmtree(self.download_dir)

    async def test_tool_and_web_retry_ladder_with_safe_mode(self):
        safe_mode_called = []
        poll_count = 0

        async def mock_sanitize(*args, **kwargs):
            safe_mode_called.append(True)
            return True

        async def create_page():
            p = MagicMock()
            p.url = "https://gemini.google.com/app"
            p.goto = AsyncMock()
            p.keyboard = MagicMock()
            p.keyboard.insert_text = AsyncMock()
            p.keyboard.press = AsyncMock()
            p.query_selector = AsyncMock(return_value=True)

            async def eval_fn(script, *args, **kwargs):
                nonlocal poll_count
                if isinstance(script, str):
                    if "attachmentSelectors" in script or "file-preview" in script or "attached:" in script:
                        return {"attached": True}
                    if "JS_GET_TEXTBOX_TEXT" in script or "contenteditable" in script or "rich-textarea" in script:
                        return "Mocked valid long prompt text content to pass verification check in tests"
                    if "isVis" in script or "isGenerating" in script or "is_generating" in script or "modelResponses" in script:
                        poll_count += 1
                        return {
                            "text": "Short response",
                            "is_generating": False,
                            "has_action_bar": True
                        }
                    if "length" in script:
                        return 100
                return True

            p.evaluate = AsyncMock(side_effect=eval_fn)

            loc = MagicMock()
            loc.count = AsyncMock(return_value=1)
            loc.is_visible = AsyncMock(return_value=True)
            loc.is_enabled = AsyncMock(return_value=True)
            loc.click = AsyncMock()
            loc.inner_text = AsyncMock(return_value="Short response")
            loc.first = loc
            loc.last = loc
            loc.nth = MagicMock(return_value=loc)
            p.locator.return_value = loc
            return p

        mock_br_ctx = MagicMock()
        mock_br_ctx.pages = []
        mock_br_ctx.new_page = AsyncMock(side_effect=create_page)

        with patch("app.check_and_rotate_profiles_until_ready", return_value=(MagicMock(), mock_br_ctx)), \
             patch("app.sanitize_episode_images", side_effect=mock_sanitize), \
             patch("workflow_stages_1.generate_chapter_pdf", return_value=None):

            result = await execute_single_episode_stage5(1, self.context)

            self.assertFalse(result)
            self.assertGreaterEqual(poll_count, 9)

if __name__ == "__main__":
    unittest.main()
