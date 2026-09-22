# -*- coding: utf-8 -*-
"""
Phase 1: Visual Ingestion & Preparation (SOLID Single Responsibility)
Responsible for:
- Comic parsing & URL resolution
- Image crawling with anti-bot throttling
- Smart paging & AI canvas segmentation
- NSFW detection & moderation
- High-quality PDF chapter export
"""

import os
import asyncio
from typing import Optional, Dict, Any, List
from workflow_base import BaseStage, StageState, WorkflowContext
from pipeline.interfaces import IStage, IEpisodeProcessor

from workflow_stages_1 import (
    Stage0_ProjectInit,
    Stage1_ComicParsing,
    Stage2_AsyncImageCrawling,
    Stage2b_IntelligentRepagination,
    Stage3_NSFWModeration,
    Stage4_PDFGeneration,
    execute_single_episode_stage2,
    execute_single_episode_stage2b,
    execute_single_episode_stage3,
    execute_single_episode_stage4,
)

Stage2_ImageCrawling = Stage2_AsyncImageCrawling
Stage2b_Repagination = Stage2b_IntelligentRepagination


class Phase1_VisualPrep(BaseStage, IStage, IEpisodeProcessor):
    """
    Phase 1: Visual Ingestion & Preparation Stage
    Combines project init, comic scraping, and image preparation.
    """
    @property
    def name(self) -> str:
        return "Phase 1 - Thu thập & Xử lý Hình ảnh"

    @property
    def phase_code(self) -> str:
        return "P1_VISUAL"

    @property
    def weight(self) -> float:
        return 0.30

    async def process_episode(self, ep: int, context: WorkflowContext, **kwargs) -> bool:
        crawl_lock = kwargs.get("crawl_lock") or asyncio.Lock()
        browser_context = kwargs.get("browser_context")
        nav_manager = kwargs.get("nav_manager")
        dl_sem = kwargs.get("dl_sem") or asyncio.Semaphore(4)
        repage_sem = kwargs.get("repage_sem") or asyncio.Semaphore(2)
        nsfw_sem = kwargs.get("nsfw_sem") or asyncio.Semaphore(4)
        pdf_sem = kwargs.get("pdf_sem") or asyncio.Semaphore(4)
        return await execute_single_episode_visual(
            ep, context, crawl_lock, browser_context, nav_manager,
            dl_sem, repage_sem, nsfw_sem, pdf_sem
        )

    execute_episode = process_episode

    async def execute(self, context: WorkflowContext) -> bool:
        # 1. Project Init
        s0 = Stage0_ProjectInit()
        ok0 = await s0.execute(context)
        if not ok0:
            return False

        # 2. Comic Parsing (if needed)
        s1 = Stage1_ComicParsing()
        ok1 = await s1.execute(context)
        if not ok1:
            return False

        await context.update_stage_progress(self.name, 100.0)
        return True


Stage1_VisualPrep = Phase1_VisualPrep


async def execute_single_episode_visual(
    ep: int,
    context: WorkflowContext,
    crawl_lock: asyncio.Lock,
    browser_context,
    nav_manager,
    dl_sem: asyncio.Semaphore,
    repage_sem: asyncio.Semaphore,
    nsfw_sem: asyncio.Semaphore,
    pdf_sem: asyncio.Semaphore
) -> bool:
    """
    Executes full Phase 1 processing for a single episode:
    Stage 2 (Crawl) -> Stage 2b (Smart Repaging) -> Stage 3 (NSFW) -> Stage 4 (PDF).
    """
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()

    await context.update_episode_stage(ep, "Phase 1 - Thu thập & Xử lý Hình ảnh", StageState.RUNNING)

    # 1. Image Crawling
    async with crawl_lock:
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        s2_ok = await execute_single_episode_stage2(ep, context, browser_context, nav_manager, dl_sem)
        if not s2_ok:
            await context.fail_episode(ep, f"Tập {ep}: Crawl ảnh thất bại.", stage_name="Phase 1 - Thu thập & Xử lý Hình ảnh")
            return False
        await asyncio.sleep(1.0)

    # 2. Smart Repagination
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()
    s2b_ok = await execute_single_episode_stage2b(ep, context, repage_sem)
    if not s2b_ok:
        await context.fail_episode(ep, f"Tập {ep}: Phân trang ảnh thất bại.", stage_name="Phase 1 - Thu thập & Xử lý Hình ảnh")
        return False

    # 3. NSFW Moderation
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()
    s3_ok = await execute_single_episode_stage3(ep, context, nsfw_sem)
    if not s3_ok:
        await context.fail_episode(ep, f"Tập {ep}: Kiểm duyệt NSFW thất bại.", stage_name="Phase 1 - Thu thập & Xử lý Hình ảnh")
        return False

    # 4. PDF Generation
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()
    s4_ok = await execute_single_episode_stage4(ep, context, pdf_sem)
    if not s4_ok:
        await context.fail_episode(ep, f"Tập {ep}: Tạo PDF thất bại.", stage_name="Phase 1 - Thu thập & Xử lý Hình ảnh")
        return False

    return True
