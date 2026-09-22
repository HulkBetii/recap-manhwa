# -*- coding: utf-8 -*-
"""
Pipeline Stages Package:
- stage1_visual: Phase 1 (Visual Ingestion & Preparation)
- stage2_script: Phase 2 (AI VLM Script Generation)
- stage3_audio: Phase 3 (Voice Synthesis & Subtitles)
- stage4_render: Phase 4 (Episode Video Rendering)
- stage5_export: Phase 5 (Assembly & Final Export)
"""

from .stage1_visual import (
    Phase1_VisualPrep,
    Stage1_VisualPrep,
    execute_single_episode_visual,
    execute_single_episode_stage2,
    execute_single_episode_stage2b,
    execute_single_episode_stage3,
    execute_single_episode_stage4,
)
from .stage2_script import (
    Phase2_AIScripting,
    Stage2_AIScripting,
    execute_single_episode_script,
    execute_single_episode_stage5,
    execute_single_episode_stage6,
    execute_single_episode_stage7,
)
from .stage3_audio import (
    Phase3_VoiceSubtitles,
    Stage3_VoiceSubtitles,
    execute_single_episode_audio,
    execute_single_episode_stage8,
    execute_single_episode_stage9,
)
from .stage4_render import (
    Phase4_EpisodeRender,
    Stage4_EpisodeRender,
    execute_single_episode_render,
    execute_single_episode_stage10,
)
from .stage5_export import (
    Phase5_FinalExport,
    Stage5_FinalExport,
    Stage11_FinalVideoAssembly,
    Stage12_MetadataReports,
    Stage13_Cleanup,
)
