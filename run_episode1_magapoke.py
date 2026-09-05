import os
import sys
import asyncio
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Ensure working directory is project root
os.chdir(Path(__file__).resolve().parent)

from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import (
    Stage0_ProjectInit,
    Stage1_ComicParsing,
    Stage2_AsyncImageCrawling,
    Stage2b_IntelligentRepagination,
    Stage3_NSFWModeration,
    Stage4_PDFGeneration,
    Stage5_GeminiAutomation,
    Stage6_JSONExtraction,
)
from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
    Stage10_EpisodeVideoRendering,
    Stage11_FinalVideoAssembly,
    Stage12_MetadataReports,
)

class SimpleCancelToken:
    def is_cancelled(self) -> bool:
        return False

class ConsoleContext:
    def __init__(self, task: WorkflowTask):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload

    async def log(self, message: str, level: str = "info", *args, **kwargs):
        prefix = f"[{level.upper()}]"
        print(f"{prefix} {message}", flush=True)
        self.task.logs.append({"level": level, "message": message})

    async def start_episode(self, ep: int):
        print(f"[INFO] Bat dau xu ly tap {ep}...", flush=True)

    async def complete_episode(self, ep: int):
        print(f"[SUCCESS] Hoan thanh xu ly tap {ep}.", flush=True)

    async def fail_episode(self, ep: int, error: str):
        print(f"[ERROR] That bai tap {ep}: {error}", flush=True)

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)

async def main():
    task = WorkflowTask(
        comic_title="転生貴族、鑑定スキルで成り上がる",
        comic_url="https://pocket.shonenmagazine.com/title/01152/episode/308806",
        from_episode=1,
        to_episode=1,
        payload={
            "market_id": "japan_isekai_territory",
            "language": "ja",
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 4,
            "voice_id": "edge-tts_ja-JP-KeitaNeural",
            "rate": "+8%",
            "pitch": "-1Hz",
            "burn_subtitles": False,
            "remove_text": False,
        },
        id="live-magapoke-ep1"
    )

    ctx = ConsoleContext(task)

    pipeline = [
        Stage0_ProjectInit(),
        Stage1_ComicParsing(),
        Stage2_AsyncImageCrawling(),
        Stage2b_IntelligentRepagination(),
        Stage3_NSFWModeration(),
        Stage4_PDFGeneration(),
        Stage5_GeminiAutomation(),
        Stage6_JSONExtraction(),
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
        Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
    ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n=======================================================")
        print(f"  Stage: {stage.name}")
        print(f"=======================================================")
        ok = await stage.execute(ctx)
        if not ok:
            print(f"[FATAL] Giai doan {stage.name} that bai. Dung workflow.")
            return 2
        print(f"[DONE] Giai doan {stage.name} thanh cong.")

    print("\n=======================================================")
    print("  TAT CA GIAI DOAN RECAP MAGAPOKE TAP 1 DA HOAN TAT!")
    print("=======================================================")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
