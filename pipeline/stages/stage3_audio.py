# -*- coding: utf-8 -*-
"""
Phase 3: Voice Synthesis & Subtitles (SOLID Single Responsibility)
Responsible for:
- Local TTS synthesis (Edge-TTS / Kokoro)
- Audio stitching, padding & volume normalization
- Dynamic Visual Timeline calculation
- Subtitle (.srt) generation & sync
"""

import os
import asyncio
from typing import Optional, Dict, Any, List
from workflow_base import BaseStage, StageState, WorkflowContext
from pipeline.interfaces import IStage, IEpisodeProcessor

# Import underlying specialized engine functions
from workflow_stages_2 import (
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
    execute_single_episode_stage8,
    execute_single_episode_stage9,
)


class Phase3_VoiceSubtitles(BaseStage, IStage, IEpisodeProcessor):
    """
    Phase 3: Voice Synthesis & Subtitles Stage
    """
    @property
    def name(self) -> str:
        return "Phase 3 - Giọng đọc TTS & Phụ đề"

    @property
    def phase_code(self) -> str:
        return "P3_AUDIO"

    @property
    def weight(self) -> float:
        return 0.20

    async def process_episode(
        self,
        ep: int,
        context: WorkflowContext,
        tts_sem: Optional[asyncio.Semaphore] = None,
        **kwargs
    ) -> bool:
        sem = tts_sem or kwargs.get("tts_sem") or asyncio.Semaphore(5)
        return await execute_single_episode_audio(ep, context, sem)

    execute_episode = process_episode

    async def execute(self, context: WorkflowContext) -> bool:
        await context.update_stage_progress(self.name, 100.0)
        return True


Stage3_VoiceSubtitles = Phase3_VoiceSubtitles


async def execute_single_episode_audio(
    ep: int,
    context: WorkflowContext,
    tts_sem: asyncio.Semaphore
) -> bool:
    """
    Executes full Phase 3 processing for a single episode:
    Stage 8 (Local TTS) -> Stage 9 (Subtitle Normalization & Timeline).
    """
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()

    await context.update_episode_stage(ep, "Phase 3 - Giọng đọc TTS & Phụ đề", StageState.RUNNING)

    # 1. Local TTS Audio Generation
    s8_ok = await execute_single_episode_stage8(ep, context, tts_sem)
    if not s8_ok:
        await context.fail_episode(ep, f"Tập {ep}: Tạo âm thanh TTS thất bại.", stage_name="Phase 3 - Giọng đọc TTS & Phụ đề")
        return False

    # 2. Subtitle Normalization & Timeline
    if context.cancel_token.is_cancelled():
        raise asyncio.CancelledError()
    s9_ok = await execute_single_episode_stage9(ep, context)
    if not s9_ok:
        await context.fail_episode(ep, f"Tập {ep}: Tạo phụ đề và timeline thất bại.", stage_name="Phase 3 - Giọng đọc TTS & Phụ đề")
        return False

    return True
