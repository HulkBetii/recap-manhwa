import os
import sys
import asyncio
import json
import time
import shutil
from pathlib import Path
from PIL import Image

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
    Stage10_EpisodeVideoRendering,
    Stage11_FinalVideoAssembly,
    Stage12_MetadataReports,
    Stage13_Cleanup,
    detect_clean_panel_and_focal_point,
)
from clean_crop_panels import clean_crop_key_panels

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
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": self.task.current_episode
        })
        self._sync_task_db()

    async def start_episode(self, ep: int):
        self.task.current_episode = ep
        await self.log(f"Bắt đầu xử lý tập {ep}...", "info")

    async def complete_episode(self, ep: int):
        await self.log(f"Hoàn thành tập {ep}.", "success")

    async def fail_episode(self, ep: int, error: str):
        await self.log(f"Lỗi tập {ep}: {error}", "error")

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    def _sync_task_db(self):
        try:
            db_path = "tasks_db.json"
            tmp_path = "tasks_db.json.script_tmp"
            db = {}
            if os.path.exists(db_path):
                try:
                    with open(db_path, "r", encoding="utf-8") as f:
                        db = json.load(f)
                except Exception:
                    db = {}
            db[self.task.id] = self.task.to_storage_dict()
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            for _ in range(10):
                try:
                    os.replace(tmp_path, db_path)
                    break
                except (PermissionError, OSError):
                    time.sleep(0.08)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        except Exception:
            pass

OPTIMIZED_VI_RECAP_DATA = [
    {
        "speech": "Giữa ngày tàn của thế giới khi tòa tháp bí ẩn trồi lên nuốt chửng bầu trời đô thị, Jaehwan quyết định dấn thân vào con đường sinh tử.",
        "images": [{"page": 2, "priority": 1.0}]
    },
    {
        "speech": "Toàn thể nhân loại bàng hoàng theo dõi các bản tin truyền hình khẩn cấp, đứng trước sự lựa chọn bước vào cuộc chiến hoặc chấp nhận bị xóa sổ.",
        "images": [{"page": 3, "priority": 1.0}]
    },
    {
        "speech": "Hàng vạn chiến binh tràn đầy dũng khí giương cao ngọn cờ vũ khí, cùng Jaehwan tiến vào cổng tháp vì sự sống còn của đồng loại.",
        "images": [{"page": 8, "priority": 1.0}]
    },
    {
        "speech": "Thế nhưng ngay khi cánh cổng mở ra, bầy quái thú dị hợm gầm rú xông tới, biến giấc mơ anh hùng thành bể máu tàn khốc.",
        "images": [{"page": 9, "priority": 1.0}]
    },
    {
        "speech": "Với ánh mắt sắc lạnh kiên định, anh lao thẳng vào tâm bão kẻ thù mà không một chút do dự hay nao núng.",
        "images": [{"page": 10, "priority": 1.0}]
    },
    {
        "speech": "Từng đường kiếm bão táp xé toạc không gian, Jaehwan đơn thương độc mã chém tan bầy quái vật mở đường xuyên qua các tầng tháp.",
        "images": [{"page": 13, "priority": 1.0}]
    },
    {
        "speech": "Đúng lúc ranh giới sinh tử ngàn cân treo sợi tóc, vật phẩm Hồi Quy Thạch kỳ bí xuất hiện, trao cho họ cơ hội làm lại cuộc đời.",
        "images": [{"page": 14, "priority": 1.0}]
    },
    {
        "speech": "Đứng trước cơ hội bỏ chạy ngọt ngào, một đồng đội không ngần ngại giơ cao viên đá, sẵn sàng từ bỏ tất cả để quay về quá khứ.",
        "images": [{"page": 16, "priority": 1.0}]
    },
    {
        "speech": "Ánh hào quang kích hoạt bùng nổ chói lòa, nuốt chửng những kẻ chấp nhận đầu hàng trước số phận nghiệt ngã.",
        "images": [{"page": 18, "priority": 1.0}]
    },
    {
        "speech": "Toàn bộ đoàn người đứng lặng người trong bàng hoàng khi chứng kiến vết tích đồng đội vĩnh viễn tan biến vào hư không.",
        "images": [{"page": 20, "priority": 1.0}]
    },
    {
        "speech": "Nỗi sợ hãi lan nhanh như một cơn dịch hạch, cuốn phăng ý chí chiến đấu cuối cùng của những người dũng cảm nhất.",
        "images": [{"page": 21, "priority": 1.0}]
    },
    {
        "speech": "Từng đoàn người lần lượt tháo lui, biến chiến trường khốc liệt thành chốn hoang tàn chỉ còn lại bóng tối và xác quái vật.",
        "images": [{"page": 23, "priority": 1.0}]
    },
    {
        "speech": "Cơn thịnh nộ của quái vật tầng cao bất ngờ bùng nổ dữ dội, nham thạch và sấm sét giáng xuống rung chuyển cả mặt đất.",
        "images": [{"page": 24, "priority": 0.5}, {"page": 25, "priority": 0.5}]
    },
    {
        "speech": "Giữa đống đổ nát hoang tàn khi trận chiến vừa dứt, tiếng gọi thảng thốt của người bạn đồng hành vang lên yếu ớt.",
        "images": [{"page": 26, "priority": 0.5}, {"page": 27, "priority": 0.5}]
    },
    {
        "speech": "Bàn tay đẫm máu của người đồng đội run rẩy nâng mảnh đá hồi quy vỡ nát, ánh mắt tràn ngập cay đắng và tiếc nuối.",
        "images": [{"page": 28, "priority": 1.0}]
    },
    {
        "speech": "Nở nụ cười trăn trối đầy chua xót, người bạn khẽ nói lời xin lỗi rồi trút hơi thở cuối cùng trong vòng tay Jaehwan.",
        "images": [{"page": 30, "priority": 1.0}]
    },
    {
        "speech": "Chứng kiến người bạn thân gục ngã, đôi mắt anh co thắt lại trong nỗi căm phẫn tột cùng trước sự tàn độc của trò chơi sinh tồn.",
        "images": [{"page": 31, "priority": 1.0}]
    },
    {
        "speech": "Cánh cổng sấm sét ma mị mở ra, sương đen cuộn trào báo hiệu sự giáng lâm của một thực thể tối cao ngoài sức tưởng tượng.",
        "images": [{"page": 32, "priority": 0.5}, {"page": 33, "priority": 0.5}]
    },
    {
        "speech": "Đối mặt với kẻ thống trị bí ẩn, Jaehwan ngẩng cao đầu với bản lĩnh của kẻ sống sót duy nhất trên chiến trường.",
        "images": [{"page": 34, "priority": 1.0}]
    },
    {
        "speech": "Trên đỉnh tháp tuyết lạnh thấu xương, một con quái thú băng khổng lồ hiện hình, nghênh đón kẻ phàm trần điên rồ dám khiêu chiến tầng thứ chín mươi chín.",
        "images": [{"page": 35, "priority": 1.0}]
    },
    {
        "speech": "Siết chặt thanh bảo kiếm trong tay, anh sẵn sàng tử chiến với thực thể quyền năng để viết nên định mệnh của chính mình.",
        "images": [{"page": 36, "priority": 0.4}, {"page": 37, "priority": 0.6}]
    }
]

async def main():
    target_url = "https://www.webtoons.com/en/action/the-world-after-the-fall/list?title_no=4011"
    target_dir = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\downloads\the_world_after_the_fall_1_1_vi_be5d3841"
    ep_dir = os.path.join(target_dir, "episode_1")
    output_dir = os.path.join(target_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 80)
    print("  The World After The Fall - Episode 1 (Tiếng Việt v1.6.5 PURE ARTWORK ULTIMATE)")
    print(f"  Target Dir: {target_dir}")
    print(f"  Voice: OmniVoice ({config.DEFAULT_VI_VOICE})")
    print(f"  Motion: v1.6.5 Hybrid Motion (Bubble-Exclusion Pan, Ken Burns Zoom, 0% Horiz Pan)")
    print(f"  Clean-Cropping: 100% Pure Artwork (Đã cắt sạch bóng thoại 13 panel trọng điểm)")
    print("=" * 80)

    img_pdf_dir = os.path.join(ep_dir, "images_pdf")
    recap_path = os.path.join(ep_dir, "recap.json")
    narration_path = os.path.join(ep_dir, "narration.txt")

    # 1. Ensure clean cropping is executed on key panels
    clean_crop_key_panels(img_pdf_dir)

    # 2. Update recap.json and narration.txt with curated 21 segments
    with open(recap_path, "w", encoding="utf-8") as f:
        json.dump(OPTIMIZED_VI_RECAP_DATA, f, ensure_ascii=False, indent=2)
    print(f"[RECAP] Đã cập nhật 21 phân cảnh tinh tuyển vào recap.json")

    narration_text = " ".join([seg["speech"] for seg in OPTIMIZED_VI_RECAP_DATA])
    with open(narration_path, "w", encoding="utf-8") as f:
        f.write(narration_text)
    print(f"[NARRATION] Đã cập nhật narration.txt ({len(narration_text)} ký tự)")

    # 3. Compute content_bounds_cache.json with clean cropped dimensions
    files = [f for f in os.listdir(img_pdf_dir) if f.endswith(('.webp', '.png', '.jpg')) and not f.endswith('_orig.webp')]
    files.sort()
    bounds_cache_path = os.path.join(ep_dir, "content_bounds_cache.json")
    new_cache = {}
    for f in files:
        p_path = os.path.join(img_pdf_dir, f)
        with Image.open(p_path) as im:
            bounds, focal_pt, skin_r, bubble_c, bubble_cov = detect_clean_panel_and_focal_point(im)
            new_cache[f] = {
                "bounds": list(bounds),
                "focal_point": list(focal_pt),
                "skin_ratio": skin_r,
                "bubble_centroid": list(bubble_c),
                "bubble_coverage_ratio": bubble_cov
            }
    with open(bounds_cache_path, "w", encoding="utf-8") as cf:
        json.dump(new_cache, cf, indent=4)
    print(f"[CACHE] Đã cập nhật content_bounds_cache.json cho {len(new_cache)} frames sau Clean Crop.")

    # 4. Clean old render outputs (keep audio.mp3 and transcript.srt if intact)
    files_to_clean = [
        os.path.join(ep_dir, "video.mp4"),
        os.path.join(output_dir, "the_world_after_the_fall_1_1_vi_be5d3841.mp4"),
    ]
    for fc in files_to_clean:
        if os.path.exists(fc):
            try:
                os.remove(fc)
            except Exception:
                pass

    # 5. Create WorkflowTask and execute Stages 10 -> 12
    task_id = f"the-world-after-the-fall-ep1-vi-clean-{int(time.time())}"
    task = WorkflowTask(
        comic_title="The World After The Fall",
        comic_url=target_url,
        from_episode=1,
        to_episode=1,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": config.DEFAULT_VI_VOICE_ID,
            "ref_audio_path": config.DEFAULT_VI_REF_AUDIO,
            "bgm_genre": "apocalypse",
            "enable_bgm": False,
            "enable_flash_forward_intro": False,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 4,
            "burn_subtitles": False,
            "remove_text": False,
        },
        id=task_id
    )

    task.artifacts["download_dir"] = target_dir
    task.artifacts["download_folder_name"] = "the_world_after_the_fall_1_1_vi_be5d3841"
    task.artifacts["comic_title"] = "The World After The Fall"

    ctx = ConsoleContext(task)

    # If audio exists, jump directly to high-speed rendering
    audio_file = os.path.join(ep_dir, "audio.mp3")
    srt_file = os.path.join(ep_dir, "transcript.srt")
    if os.path.exists(audio_file) and os.path.exists(srt_file) and os.path.getsize(audio_file) > 100000:
        pipeline = [
            Stage10_EpisodeVideoRendering(),
            Stage11_FinalVideoAssembly(),
            Stage12_MetadataReports(),
        ]
    else:
        pipeline = [
            Stage7_NarrationAggregation(),
            Stage8_LocalTTS(),
            Stage9_SubtitleNormalization(),
            Stage10_EpisodeVideoRendering(),
            Stage11_FinalVideoAssembly(),
            Stage12_MetadataReports(),
            Stage13_Cleanup(),
        ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n>>> {stage.name}", flush=True)
        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        ok = await stage.execute(ctx)
        if not ok:
            print(f"[FATAL] Giai đoạn {stage.name} thất bại. Dừng quy trình.", flush=True)
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.FAILED
            task.status = WorkflowState.FAILED
            ctx._sync_task_db()
            return 2

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.SUCCESS
                s["progress"] = 100.0
        ctx._sync_task_db()
        print(f"[DONE] {stage.name}", flush=True)

    task.status = WorkflowState.SUCCESS
    task.current_stage = "Completed"
    task.overall_progress = 100.0
    ctx._sync_task_db()

    final_video = os.path.join(output_dir, "the_world_after_the_fall_1_1_vi_be5d3841.mp4")
    print("\n" + "=" * 75)
    print("  [SUCCESS] HOÀN TẤT TẠO VIDEO RECAP TIẾNG VIỆT v1.6.5 PURE ARTWORK CHO TẬP 1")
    print(f"  Final Video: {final_video}")
    print(f"  Thư mục kết quả: {output_dir}")
    print("=" * 75)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
