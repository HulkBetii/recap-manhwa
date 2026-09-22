# -*- coding: utf-8 -*-
"""
Phase 4: Episode Video Rendering
Renders comic panels with adaptive camera motions (pan/zoom), AI upscaling, 
visual effects (grain, vignette, tint), and multiplexes with audio/subtitles.
"""

import os
import asyncio
import logging
from typing import Optional

from workflow_base import BaseStage, WorkflowContext, StageState
from pipeline.interfaces import IEpisodeProcessor, IStage
from workflow_stages_2 import execute_single_episode_stage10, Stage10_EpisodeVideoRendering

logger = logging.getLogger("Phase4_EpisodeRender")


async def execute_single_episode_render(
    ep: int,
    context: WorkflowContext,
    render_sem: Optional[asyncio.Semaphore] = None
) -> bool:
    """
    Executes Phase 4: Video rendering for a single episode.
    Maps to Phase 4 (Episode Video Rendering) and Stage 10.
    """
    return await execute_single_episode_stage10(ep, context, render_sem)


class Phase4_EpisodeRender(BaseStage, IStage, IEpisodeProcessor):
    """
    Phase 4: Episode Video Rendering Stage.
    Handles parallel video rendering for all episodes.
    """
    @property
    def name(self) -> str:
        return "Phase 4 - Episode Video Rendering"

    @property
    def phase_code(self) -> str:
        return "P4_RENDER"

    @property
    def weight(self) -> float:
        return 0.17

    async def process_episode(
        self,
        ep: int,
        context: WorkflowContext,
        render_sem: Optional[asyncio.Semaphore] = None,
        **kwargs
    ) -> bool:
        sem = render_sem or kwargs.get("render_sem")
        return await execute_single_episode_render(ep, context, sem)

    execute_episode = process_episode

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        concurrency = task.payload.get("concurrency", 3)
        await context.log(f"Phase 4 (Render): Bắt đầu render video song song với tối đa {concurrency} luồng.", "info")
        sem = asyncio.Semaphore(concurrency)

        async def run_ep(ep):
            if context.cancel_token.is_cancelled():
                raise asyncio.CancelledError()
            await context.start_episode(ep)
            ok = await self.execute_episode(ep, context, sem)
            if ok:
                await context.complete_episode(ep)
            else:
                await context.fail_episode(ep, "Lỗi render video tập truyện.")
            return ok

        episodes = list(range(from_ep, to_ep + 1))
        tasks = [run_ep(ep) for ep in episodes]
        results = await asyncio.gather(*tasks)
        return all(results)


# Backward compatibility aliases
Stage4_EpisodeRender = Phase4_EpisodeRender
