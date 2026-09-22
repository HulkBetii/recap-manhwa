# -*- coding: utf-8 -*-
import unittest
import os
import shutil
import tempfile
import json
from fastapi.testclient import TestClient

from app import app
from test_stage_router import (
    parse_folder_and_episode,
    extract_smart_paging_results,
    extract_gemini_automation_results,
    extract_tts_results,
    extract_video_results
)


class TestTestStageRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_parse_folder_and_episode(self):
        # 1. Path with episode_2
        path1 = "downloads/the_forgotten_field_1_2_vi/episode_2"
        comic_dir, folder_name, ep_num = parse_folder_and_episode(path1)
        self.assertEqual(folder_name, "the_forgotten_field_1_2_vi")
        self.assertEqual(ep_num, 2)

        # 2. Path without episode
        path2 = "the_forgotten_field_1_2_vi"
        comic_dir, folder_name, ep_num = parse_folder_and_episode(path2)
        self.assertEqual(folder_name, "the_forgotten_field_1_2_vi")
        self.assertEqual(ep_num, 1)

    def test_get_local_comics(self):
        res = self.client.get("/api/test_stage/local_comics")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("comics", data)
        self.assertIsInstance(data["comics"], list)

    def test_validate_folder(self):
        # 1. Existing local folder if present or dummy
        res = self.client.post("/api/test_stage/validate_folder", json={
            "folder_path": "downloads/the_forgotten_field_1_2_vi/episode_2"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        # Either valid or invalid with clear status
        self.assertIn("valid", data)

        # 2. Non-existent path
        res_fake = self.client.post("/api/test_stage/validate_folder", json={
            "folder_path": "non_existent_folder_xyz_123"
        })
        self.assertEqual(res_fake.status_code, 200)
        data_fake = res_fake.json()
        self.assertFalse(data_fake["valid"])

    def test_run_test_stage_validation(self):
        # 1. Missing inputs
        res = self.client.post("/api/test_stage/run", json={"stage": "stage_2b"})
        self.assertEqual(res.status_code, 400)

    def test_run_smart_paging_queues_task(self):
        res = self.client.post("/api/test_stage/run", json={
            "stage": "stage_2b",
            "comic_url": "https://asurascans.com/comics/test-manhwa"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["stage"], "stage_2b")
        self.assertEqual(data["stop_after_stage"], "Stage 4 - PDF Generation")
        self.assertTrue(len(data["task_id"]) > 0)

        # Query status
        task_id = data["task_id"]
        status_res = self.client.get(f"/api/test_stage/status/{task_id}")
        self.assertEqual(status_res.status_code, 200)
        s_data = status_res.json()
        self.assertEqual(s_data["task_id"], task_id)
        self.assertEqual(s_data["stage_type"], "stage_2b")

    def test_run_gemini_automation_queues_task(self):
        res = self.client.post("/api/test_stage/run", json={
            "stage": "stage_5",
            "comic_url": "https://asurascans.com/comics/test-manhwa"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["stage"], "stage_5")
        self.assertEqual(data["stop_after_stage"], "Stage 6 - JSON Extraction")

    def test_run_with_folder_path_episode_2(self):
        res = self.client.post("/api/test_stage/run", json={
            "stage": "stage_2b",
            "folder_path": "downloads/the_forgotten_field_1_2_vi/episode_2"
        })
        # If folder exists locally, expect 200
        if os.path.exists("downloads/the_forgotten_field_1_2_vi/episode_2"):
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["episode"], 2)
            self.assertEqual(data["target_pipeline"], [
                "Stage 2b - Intelligent Re-pagination",
                "Stage 4 - PDF Generation"
            ])

    def test_extract_smart_paging_results(self):
        temp_comic = tempfile.mkdtemp()
        temp_ep = os.path.join(temp_comic, "episode_2")
        os.makedirs(temp_ep, exist_ok=True)
        try:
            pdf_dir = os.path.join(temp_ep, "pdf")
            images_dir = os.path.join(temp_ep, "images")
            os.makedirs(pdf_dir, exist_ok=True)
            os.makedirs(images_dir, exist_ok=True)

            # Create dummy PDF
            pdf_path = os.path.join(pdf_dir, "test_Tap_2.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 dummy content")

            # Create dummy page image
            img_path = os.path.join(images_dir, "page_001.webp")
            with open(img_path, "wb") as f:
                f.write(b"dummy")

            res = extract_smart_paging_results(temp_ep, "test_folder", ep_num=2)
            self.assertIsNotNone(res)
            self.assertEqual(res["type"], "smart_paging")
            self.assertEqual(res["episode"], 2)
            self.assertTrue(res["has_pdf"])
            self.assertEqual(res["pdf_filename"], "test_Tap_2.pdf")
            self.assertEqual(res["total_pages"], 1)
            self.assertEqual(res["pages"][0]["filename"], "page_001.webp")
            self.assertIn("/downloads/test_folder/episode_2/images/page_001.webp", res["pages"][0]["image_url"])
        finally:
            shutil.rmtree(temp_comic, ignore_errors=True)

    def test_extract_gemini_automation_results(self):
        temp_comic = tempfile.mkdtemp()
        temp_ep = os.path.join(temp_comic, "episode_2")
        os.makedirs(temp_ep, exist_ok=True)
        try:
            images_dir = os.path.join(temp_ep, "images")
            os.makedirs(images_dir, exist_ok=True)

            # Create dummy page image
            img_path = os.path.join(images_dir, "page_001.webp")
            with open(img_path, "wb") as f:
                f.write(b"dummy")

            # Create dummy recap.json
            recap_path = os.path.join(temp_ep, "recap.json")
            sample_recap = [
                {
                    "speech": "Lời dẫn mở đầu câu chuyện tập 2.",
                    "images": [{"page": "1", "priority": 1.0}]
                }
            ]
            with open(recap_path, "w", encoding="utf-8") as f:
                json.dump(sample_recap, f)

            res = extract_gemini_automation_results(temp_ep, "test_folder", ep_num=2)
            self.assertIsNotNone(res)
            self.assertEqual(res["type"], "gemini_automation")
            self.assertEqual(res["episode"], 2)
            self.assertEqual(res["total_segments"], 1)
            seg = res["segments"][0]
            self.assertEqual(seg["speech"], "Lời dẫn mở đầu câu chuyện tập 2.")
            self.assertEqual(seg["page_num"], 1)
            self.assertEqual(seg["image_filename"], "page_001.webp")
            self.assertIn("/downloads/test_folder/episode_2/images/page_001.webp", seg["image_url"])
        finally:
            shutil.rmtree(temp_comic, ignore_errors=True)

    def test_run_with_headless_flag(self):
        res = self.client.post("/api/test_stage/run", json={
            "stage": "stage_2b",
            "comic_url": "https://asurascans.com/comics/test-manhwa",
            "headless": True
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

    def test_api_config_headless_toggle(self):
        # Test toggling headless via /api/config
        res = self.client.post("/api/config", json={
            "headless": True
        })
        self.assertEqual(res.status_code, 200)
        cfg = res.json()["config"]
        self.assertTrue(cfg["headless"])

        # Toggle back to False
        res2 = self.client.post("/api/config", json={
            "headless": False
        })
        self.assertEqual(res2.status_code, 200)
        cfg2 = res2.json()["config"]
        self.assertFalse(cfg2["headless"])


if __name__ == "__main__":
    unittest.main()
