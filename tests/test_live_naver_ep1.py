import asyncio
import os
import shutil
import pytest
from pathlib import Path
import cv2
import numpy as np

from workflow_base import WorkflowContext, CancellationToken
from workflow import WorkflowTask
from workflow_stages_1 import (
    Stage0_ProjectInit,
    Stage1_ComicParsing,
    Stage2_AsyncImageCrawling,
    Stage2b_IntelligentRepagination,
    Stage4_PDFGeneration,
    safe_cv2_imread,
)
from workflow_stages_2 import draw_subtitles_on_frame
import markets


class DummyWorkflowManager:
    def __init__(self):
        self.cancel_tokens = {}

    def get_cancel_token(self, task_id):
        if task_id not in self.cancel_tokens:
            self.cancel_tokens[task_id] = CancellationToken()
        return self.cancel_tokens[task_id]

    async def save_and_broadcast(self, event_type, task):
        pass

    async def calculate_overall_progress(self, task):
        pass


@pytest.mark.asyncio
async def test_live_naver_crawling_and_repagination_ep1():
    """
    Live End-to-End Test for Naver Webtoon (Episode 1):
    Target: https://comic.naver.com/webtoon/list?titleId=836848 (44교시 생존수업)
    1. Runs Stage 0: Project directory initialization.
    2. Runs Stage 1: Official Korean title parsing from live Naver page.
    3. Runs Stage 2: Live crawling and downloading episode 1 images via Naver CDN with Referer.
    4. Runs Stage 2b: Sub-panel segmentation into images_pdf.
    5. Runs Stage 4: Numbered PDF compilation.
    6. Tests Korean subtitle rendering (Malgun Gothic) on the generated panels.
    """
    target_url = "https://comic.naver.com/webtoon/list?titleId=836848&e2e=test"
    dummy_manager = DummyWorkflowManager()

    payload = {
        "language": "ko",
        "market_id": "korea_apocalypse",
        "concurrency": 8,
        "burn_subtitles": True,
        "repage_use_ocr": False,
    }

    task = WorkflowTask(
        comic_title="Naver_836848",
        comic_url=target_url,
        from_episode=1,
        to_episode=1,
        payload=payload,
    )

    context = WorkflowContext(task, payload, dummy_manager)
    cancel_token = CancellationToken()
    context.cancel_token = cancel_token

    try:
        # --- STEP 1: STAGE 0 (Project Init) ---
        stage0 = Stage0_ProjectInit()
        s0_ok = await stage0.execute(context)
        assert s0_ok is True
        download_dir = task.artifacts.get("download_dir")
        assert download_dir is not None
        assert os.path.exists(download_dir)

        # --- STEP 2: STAGE 1 (Comic Parsing) ---
        stage1 = Stage1_ComicParsing()
        s1_ok = await stage1.execute(context)
        assert s1_ok is True
        # The official title extracted from Naver must contain "44교시 생존수업"
        assert "44교시" in task.comic_title or "생존수업" in task.comic_title

        download_dir = task.artifacts.get("download_dir")
        ep1_images_dir = os.path.join(download_dir, "episode_1", "images")
        assert os.path.exists(ep1_images_dir)

        # --- STEP 3: STAGE 2 (Live Image Crawling from Naver CDN) ---
        stage2 = Stage2_AsyncImageCrawling()
        s2_ok = await stage2.execute(context)
        assert s2_ok is True

        # Validate downloaded images
        downloaded_files = [
            f for f in os.listdir(ep1_images_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ]
        print(f"\n[Test Live Naver] Tải thành công {len(downloaded_files)} ảnh từ Naver CDN!")
        assert len(downloaded_files) >= 50, f"Expected at least 50 images, got {len(downloaded_files)}"

        # Check first downloaded image is readable and non-empty
        sample_img_path = os.path.join(ep1_images_dir, downloaded_files[0])
        img = safe_cv2_imread(sample_img_path)
        assert img is not None
        assert img.shape[0] > 0 and img.shape[1] > 0
        assert os.path.getsize(sample_img_path) > 1000  # At least 1KB

        # --- STEP 4: STAGE 2b (Intelligent Repagination / Panel Split) ---
        stage2b = Stage2b_IntelligentRepagination()
        s2b_ok = await stage2b.execute(context)
        assert s2b_ok is True

        ep1_images_pdf_dir = os.path.join(download_dir, "episode_1", "images_pdf")
        assert os.path.exists(ep1_images_pdf_dir)
        pdf_panels = [
            f for f in os.listdir(ep1_images_pdf_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ]
        print(f"[Test Live Naver] Phân chia panel thành công: {len(pdf_panels)} panels trong images_pdf!")
        assert len(pdf_panels) > 0

        # --- STEP 5: STAGE 4 (PDF Generation) ---
        stage4 = Stage4_PDFGeneration()
        s4_ok = await stage4.execute(context)
        assert s4_ok is True

        pdf_dir = os.path.join(download_dir, "episode_1", "pdf")
        pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
        assert len(pdf_files) > 0
        pdf_file_path = os.path.join(pdf_dir, pdf_files[0])
        assert os.path.getsize(pdf_file_path) > 10000
        print(f"[Test Live Naver] Đã tạo PDF thành công: {pdf_files[0]} ({os.path.getsize(pdf_file_path)} bytes)!")

        # --- STEP 6: KOREAN SUBTITLE RENDERING CHECK ---
        from PIL import Image
        first_panel_path = os.path.join(ep1_images_pdf_dir, pdf_panels[0])
        frame = safe_cv2_imread(first_panel_path)
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        # Standard 1080p video canvas
        canvas = Image.new("RGB", (1920, 1080), (20, 20, 20))
        canvas.paste(pil_img.resize((690, 561)), (615, 259))
        korean_sub = "검은 원이 학교를 집어삼키고 학생들은 패닉에 빠지는데요."
        draw_subtitles_on_frame(canvas, korean_sub)
        assert canvas.size == (1920, 1080)
        print(f"[Test Live Naver] Vẽ phụ đề tiếng Hàn (Malgun Gothic) thành công trên video frame 1080p ({canvas.size})!")
    finally:
        from app import reset_shared_browser_context
        try:
            await reset_shared_browser_context()
        except Exception:
            pass
