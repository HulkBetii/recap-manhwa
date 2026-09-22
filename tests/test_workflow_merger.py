# -*- coding: utf-8 -*-
"""
UNIT & INTEGRATION TESTS: EPISODE SPLITTING AND MERGING (WorkflowMerger)
Tests episode discovery, custom range concatenation, multi-group splitting,
SRT shifting/merging, stream copy merging without re-encoding, and FastAPI API endpoints.
"""
import os
import shutil
import unittest
import asyncio
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from workflow_merger import (
    shift_srt_time,
    merge_srt_files,
    get_task_available_episodes,
    merge_episode_ranges_for_task,
    delete_merged_video_file
)
from app import app, workflow_manager
from workflow import WorkflowTask, WorkflowState


class TestWorkflowMerger(unittest.TestCase):

    def setUp(self):
        self.test_root = os.path.join("tests", "tmp_merger_test")
        os.makedirs(self.test_root, exist_ok=True)
        self.download_dir = os.path.join(self.test_root, "test_comic_1_10")
        os.makedirs(self.download_dir, exist_ok=True)

        # Create dummy episode directories (episode_1 to episode_5)
        for ep in range(1, 6):
            ep_dir = os.path.join(self.download_dir, f"episode_{ep}")
            os.makedirs(ep_dir, exist_ok=True)
            # Create dummy video.mp4
            with open(os.path.join(ep_dir, "video.mp4"), "wb") as f:
                f.write(b"dummy_video_bytes_" + str(ep).encode("utf-8") * 50)
            # Create dummy transcript.srt
            with open(os.path.join(ep_dir, "transcript.srt"), "w", encoding="utf-8") as f:
                f.write(f"1\n00:00:01,000 --> 00:00:04,000\nThoại tập {ep}\n\n")

        # Create dummy workflow task
        self.task = WorkflowTask(
            comic_title="Test Comic",
            comic_url="https://example.com/comic",
            from_episode=1,
            to_episode=5,
            payload={},
            id="task_merger_test_1"
        )
        self.task.status = WorkflowState.SUCCESS
        self.task.artifacts = {
            "download_dir": self.download_dir,
            "download_folder_name": "test_comic_1_10",
            "final_videos": {
                str(ep): f"/downloads/test_comic_1_10/episode_{ep}/video.mp4" for ep in range(1, 6)
            }
        }
        workflow_manager.repository.save(self.task)
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root, ignore_errors=True)
        try:
            workflow_manager.repository.delete(self.task.id)
        except Exception:
            pass

    def test_shift_srt_time(self):
        shifted = shift_srt_time("00:01:15,500", 65.2) # + 1m 5s 200ms -> 00:02:20,700
        self.assertEqual(shifted, "00:02:20,700")

        shifted_zero = shift_srt_time("00:00:00,000", 0.0)
        self.assertEqual(shifted_zero, "00:00:00,000")

    def test_merge_srt_files(self):
        srt1 = os.path.join(self.download_dir, "episode_1", "transcript.srt")
        srt2 = os.path.join(self.download_dir, "episode_2", "transcript.srt")
        out_srt = os.path.join(self.download_dir, "output", "merged.srt")

        durations = [10.0, 15.0]
        success = merge_srt_files([srt1, srt2], durations, out_srt)
        self.assertTrue(success)
        self.assertTrue(os.path.isfile(out_srt))

        with open(out_srt, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Thoại tập 1", content)
        self.assertIn("Thoại tập 2", content)
        # Episode 2 starts at 10.0s + 1.0s = 11.0s
        self.assertIn("00:00:11,000 --> 00:00:14,000", content)

    def test_get_task_available_episodes(self):
        info = get_task_available_episodes(self.task)
        self.assertEqual(info["comic_title"], "Test Comic")
        self.assertEqual(info["available_episodes"], [1, 2, 3, 4, 5])
        self.assertEqual(info["min_episode"], 1)
        self.assertEqual(info["max_episode"], 5)
        self.assertEqual(info["total_rendered"], 5)
        self.assertEqual(len(info["episodes_detail"]), 5)

    @patch("workflow_stages_2.get_video_duration", return_value=12.0)
    def test_merge_single_episode_and_ranges(self, mock_dur):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        ranges = [
            {"from_ep": 1, "to_ep": 1, "custom_name": "Tập 1 Lẻ"},
            {"from_ep": 2, "to_ep": 4, "custom_name": "Phần 2 Đến 4"}
        ]

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = MagicMock()
            mock_proc.communicate = MagicMock(side_effect=lambda: asyncio.sleep(0.01, result=(b"", b"")))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            res = loop.run_until_complete(merge_episode_ranges_for_task(self.task, ranges, ffmpeg_exe="ffmpeg"))

            self.assertEqual(res["status"], "success")
            self.assertEqual(res["created_count"], 2)
            self.assertEqual(len(self.task.artifacts.get("merged_videos", [])), 2)

            mv1 = self.task.artifacts["merged_videos"][0]
            self.assertEqual(mv1["from_ep"], 1)
            self.assertEqual(mv1["to_ep"], 1)
            self.assertEqual(mv1["name"], "Tập 1 Lẻ")

            mv2 = self.task.artifacts["merged_videos"][1]
            self.assertEqual(mv2["from_ep"], 2)
            self.assertEqual(mv2["to_ep"], 4)
            self.assertEqual(mv2["name"], "Phần 2 Đến 4")

        loop.close()

    def test_delete_merged_video_file(self):
        output_dir = os.path.join(self.download_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        dummy_merged = os.path.join(output_dir, "test_comic_1_10_ep1_3.mp4")
        with open(dummy_merged, "wb") as f: f.write(b"merged_video")

        self.task.artifacts["merged_videos"] = [{
            "id": "m1",
            "name": "Ep 1-3",
            "file_name": "test_comic_1_10_ep1_3.mp4",
            "from_ep": 1,
            "to_ep": 3
        }]

        success = delete_merged_video_file(self.task, "test_comic_1_10_ep1_3.mp4")
        self.assertTrue(success)
        self.assertEqual(len(self.task.artifacts["merged_videos"]), 0)
        self.assertFalse(os.path.exists(dummy_merged))

    def test_api_workflow_merge_endpoints(self):
        # 1. GET merge-info
        resp = self.client.get(f"/api/workflows/{self.task.id}/merge-info")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_rendered"], 5)
        self.assertEqual(data["available_episodes"], [1, 2, 3, 4, 5])

        # 2. POST merge-episodes invalid
        bad_resp = self.client.post(f"/api/workflows/{self.task.id}/merge-episodes", json={
            "ranges": [{"from_ep": 10, "to_ep": 20}] # Missing episodes
        })
        self.assertEqual(bad_resp.status_code, 400)

    def test_video_merge_dedicated_page_endpoints(self):
        # Test GET /video_merge page
        page_resp = self.client.get("/video_merge")
        self.assertEqual(page_resp.status_code, 200)
        self.assertIn("Studio Tách & Gộp Video", page_resp.text)

        # Test GET /api/video_merge/comics
        comics_resp = self.client.get("/api/video_merge/comics")
        self.assertEqual(comics_resp.status_code, 200)
        comics_data = comics_resp.json()
        self.assertIn("comics", comics_data)

        # Test GET /api/video_merge/info/{identifier}
        info_resp = self.client.get(f"/api/video_merge/info/{self.task.id}")
        self.assertEqual(info_resp.status_code, 200)
        info_data = info_resp.json()
        self.assertEqual(info_data["total_episodes"], 5)
        self.assertEqual(info_data["title"], "Test Comic")


if __name__ == "__main__":
    unittest.main()

