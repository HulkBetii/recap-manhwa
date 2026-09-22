# -*- coding: utf-8 -*-
"""
Phase 5: Assembly & Final Export
Concatenates rendered episode videos into a full season movie, merges subtitles with timecode offsets,
generates metadata/reports, and cleans up temporary files.
"""

import os
import asyncio
import logging
from typing import Optional

from workflow_base import BaseStage, WorkflowContext, StageState
from pipeline.interfaces import IStage
from workflow_stages_2 import (
    Stage11_FinalVideoAssembly,
    Stage12_MetadataReports,
    Stage13_Cleanup,
    merge_srt_files,
    shift_srt_time,
    get_video_duration
)

logger = logging.getLogger("Phase5_FinalExport")


class Phase5_FinalExport(BaseStage, IStage):
    """
    Phase 5: Assembly & Final Export Stage.
    Composes Stage 11 (Video Assembly), Stage 12 (Metadata Reports), and Stage 13 (Cleanup).
    """
    def __init__(self):
        self.stage11 = Stage11_FinalVideoAssembly()
        self.stage12 = Stage12_MetadataReports()
        self.stage13 = Stage13_Cleanup()

    @property
    def name(self) -> str:
        return "Phase 5 - Assembly & Export"

    @property
    def phase_code(self) -> str:
        return "P5_EXPORT"

    @property
    def weight(self) -> float:
        return 0.10

    async def execute(self, context: WorkflowContext) -> bool:
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()

        # Step 1: Stage 11 - Final Video Assembly
        await context.log("Phase 5: Bắt đầu ghép nối video và phụ đề hoàn chỉnh...", "info")
        ok11 = await self.stage11.execute(context)
        if not ok11:
            await context.log("Phase 5: Ghép nối video thất bại.", "error")
            return False

        # Step 2: Stage 12 - Metadata & Reports
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.log("Phase 5: Đang tạo siêu dữ liệu và báo cáo tổng kết...", "info")
        ok12 = await self.stage12.execute(context)
        if not ok12:
            await context.log("Phase 5: Tạo báo cáo thất bại.", "warning")

        # Step 3: Stage 13 - Cleanup
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.log("Phase 5: Dọn dẹp tệp tạm thời và giải phóng tài nguyên...", "info")
        await self.stage13.execute(context)

        await context.update_stage_progress(self.name, 100.0)
        return True


# Backward compatibility aliases
Stage5_FinalExport = Phase5_FinalExport
