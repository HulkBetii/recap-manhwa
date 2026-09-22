# -*- coding: utf-8 -*-
"""
Phase 2: AI VLM Script Generation (SOLID Single Responsibility)
Responsible for:
- Gemini Web Automation & safe vision prompt injection
- Account / Profile rotation when rate limited
- Resilient JSON script parsing & repair
- Narration script formatting & SSML dialog aggregation
"""

import os
import asyncio
from typing import Optional, Dict, Any, List
from workflow_base import BaseStage, StageState, WorkflowContext
from pipeline.interfaces import IStage, IEpisodeProcessor

# Import underlying specialized engine functions
from workflow_stages_1 import (
    Stage5_GeminiAutomation,
    Stage6_JSONExtraction,
    execute_single_episode_stage5,
)
from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    execute_single_episode_stage6,
    execute_single_episode_stage7,
)


class Phase2_AIScripting(BaseStage, IStage, IEpisodeProcessor):
    """
    Phase 2: AI VLM Script Generation Stage
    """
    @property
    def name(self) -> str:
        return "Phase 2 - Tạo Kịch bản AI VLM"

    @property
    def phase_code(self) -> str:
        return "P2_SCRIPT"

    @property
    def weight(self) -> float:
        return 0.25

    async def process_episode(
        self,
        ep: int,
        context: WorkflowContext,
        vlm_sem: Optional[asyncio.Semaphore] = None,
        profile_pool: Optional[Any] = None,
        **kwargs
    ) -> bool:
        sem = vlm_sem or kwargs.get("vlm_sem")
        pool = profile_pool or kwargs.get("profile_pool")
        if not pool and not sem:
            sem = asyncio.Semaphore(1)
        return await execute_single_episode_script(ep, context, vlm_sem=sem, profile_pool=pool)

    execute_episode = process_episode

    async def execute(self, context: WorkflowContext) -> bool:
        await context.update_stage_progress(self.name, 100.0)
        return True


Stage2_AIScripting = Phase2_AIScripting


async def execute_single_episode_script(
    ep: int,
    context: WorkflowContext,
    vlm_sem: Optional[asyncio.Semaphore] = None,
    profile_pool: Optional[Any] = None
) -> bool:
    """
    Executes full Phase 2 processing for a single episode:
    Stage 5 (Gemini VLM) -> Stage 6 (JSON Extraction) -> Stage 7 (Narration Aggregation).
    """
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()

    await context.update_episode_stage(ep, "Phase 2 - Tạo Kịch bản AI VLM", StageState.RUNNING)

    # 1. Gemini VLM Recap Generation
    s5_ok = await execute_single_episode_stage5(ep, context, vlm_sem=vlm_sem, profile_pool=profile_pool)
    if not s5_ok:
        await context.fail_episode(ep, f"Tập {ep}: Tạo kịch bản VLM thất bại.", stage_name="Phase 2 - Tạo Kịch bản AI VLM")
        return False

    # 2. JSON Extraction
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()
    s6_ok = await execute_single_episode_stage6(ep, context)
    if not s6_ok:
        await context.fail_episode(ep, f"Tập {ep}: Bóc tách JSON kịch bản thất bại.", stage_name="Phase 2 - Tạo Kịch bản AI VLM")
        return False

    # 3. Narration Aggregation
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()
    s7_ok = await execute_single_episode_stage7(ep, context)
    if not s7_ok:
        await context.fail_episode(ep, f"Tập {ep}: Tổng hợp lời thoại thất bại.", stage_name="Phase 2 - Tạo Kịch bản AI VLM")
        return False

    return True
