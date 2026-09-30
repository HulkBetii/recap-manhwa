import os
import sys
import asyncio
import json
import time
import shutil
from pathlib import Path

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
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
    Stage13_Cleanup,
    detect_clean_panel_and_focal_point,
)
from PIL import Image

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

VIETNAMESE_RECAP_DATA = [
    {
        "speech": "Trong khi những chiếc trực thăng quân sự bay lượn tuyệt vọng trên bầu trời, một đại dịch tàn khốc bất ngờ bùng phát khắp Hàn Quốc, biến hàng vạn người dân bình thường thành những con quái vật khát máu chỉ sau một đêm.",
        "images": [{"page": 1, "priority": 0.5}, {"page": 2, "priority": 0.5}]
    },
    {
        "speech": "Các bản tin truyền hình cố trấn an đây chỉ là cuộc bạo loạn quy mô lớn, nhưng bất kỳ ai còn tỉnh táo đều hiểu rằng thế giới văn minh đang sụp đổ hoàn toàn vào biển điên cuồng.",
        "images": [{"page": 3, "priority": 0.5}, {"page": 4, "priority": 0.5}]
    },
    {
        "speech": "Những người dân vô tội gào thét thảm thiết khi bầy xác sống điên cuồng xé toạc mọi tuyến phòng thủ, báo hiệu trật tự xã hội yên bình đã vĩnh viễn chấm dứt.",
        "images": [{"page": 6, "priority": 0.5}, {"page": 7, "priority": 0.5}]
    },
    {
        "speech": "Những sinh vật gớm ghiếc gầm rú tràn ngập khắp các ngõ ngách, biến từng khu phố sầm uất thành những bãi săn mồi đẫm máu.",
        "images": [{"page": 8, "priority": 1.0}]
    },
    {
        "speech": "Chính phủ liên tục kêu gọi mọi người hãy cố thủ trong nhà, nhưng âm thanh những cánh cửa phòng tuyến vỡ vụn cho thấy không còn bất kỳ nơi nào thực sự an toàn.",
        "images": [{"page": 10, "priority": 0.5}, {"page": 11, "priority": 0.5}]
    },
    {
        "speech": "Những chiến tuyến cảnh sát nỗ lực ngăn chặn dòng lũ quái vật bằng hỏa lực súng tự động, nhưng số lượng áp đảo của chúng nhanh chóng nuốt chửng tuyến đầu chỉ trong vài phút.",
        "images": [{"page": 12, "priority": 0.5}, {"page": 13, "priority": 0.5}]
    },
    {
        "speech": "Các sĩ quan tuyệt vọng gào thét lệnh nhắm thẳng vào đầu khi bầy quái vật điên cuồng lao thẳng vào tầm đạn bắn trực diện mà không hề biết sợ hãi.",
        "images": [{"page": 14, "priority": 0.5}, {"page": 15, "priority": 0.5}]
    },
    {
        "speech": "Tiếng súng rền vang xé toạc những đại lộ hoang tàn, chỉ vừa đủ để những người sống sót nhận ra rằng sẽ chẳng còn đội cứu hộ nào đến nữa.",
        "images": [{"page": 16, "priority": 1.0}]
    },
    {
        "speech": "Những cột khói đen kịt cùng ngọn lửa dữ dội thiêu rụi đường chân trời khi toàn bộ trật tự hiện đại hoàn toàn tan biến thành đống tro tàn hỗn loạn.",
        "images": [{"page": 18, "priority": 1.0}]
    },
    {
        "speech": "Bị dồn vào chân tường trong một hành lang đổ nát, nhân vật chính Ki-jin đối mặt với một con xác sống hung hãn đang lao thẳng vào yết hầu của anh.",
        "images": [{"page": 20, "priority": 1.0}]
    },
    {
        "speech": "Với sự lạnh lùng và chuẩn xác đến đáng sợ, anh cắm phập lưỡi dao sắc bén vào hộp sọ con quái vật rồi chém ngọt một đường qua cổ để kết liễu nó ngay tức khắc.",
        "images": [{"page": 21, "priority": 0.5}, {"page": 22, "priority": 0.5}]
    },
    {
        "speech": "Đứng giữa khu phức hợp mua sắm ngập tràn mùi tử khí, Ki-jin khẽ thở dài khi chứng kiến cả tòa nhà đồ sộ đã nhanh chóng biến thành ổ quái vật.",
        "images": [{"page": 24, "priority": 1.0}]
    },
    {
        "speech": "Thay vì hoảng sợ bỏ chạy, Ki-jin lạnh lùng buông lời thách thức bầy thây ma hãy cùng xông lên một lượt, bởi anh không có thời gian lãng phí với lũ tép riu.",
        "images": [{"page": 25, "priority": 1.0}]
    },
    {
        "speech": "Ở một góc khác, một người sống sót đơn độc dùng hết sức bình sinh giữ chặt cánh cổng sắt rào chắn, nghiến răng chống đỡ từng cú va đập dữ dội từ bầy xác sống bên ngoài.",
        "images": [{"page": 26, "priority": 0.5}, {"page": 27, "priority": 0.5}]
    },
    {
        "speech": "Những thường dân mắc kẹt nép mình sau những cánh cửa khóa chặt, run rẩy khi từng đợt công kích mãnh liệt làm rung chuyển những khung gỗ mỏng manh.",
        "images": [{"page": 28, "priority": 0.5}, {"page": 30, "priority": 0.5}]
    },
    {
        "speech": "Nỗi sợ hãi tột cùng lan khắp hành lang bị phong tỏa, trong khi những tiếng va đập kim loại chói tai báo hiệu bầy thây ma chỉ còn cách họ trong gang tấc.",
        "images": [{"page": 33, "priority": 0.5}, {"page": 34, "priority": 0.5}]
    },
    {
        "speech": "Nhịp tim đập loạn xạ trong bầu không khí ngột ngạt đến nghẹt thở, từng rung chấn bất ngờ dọc theo vách tường đẩy tất cả đến bờ vực của sự hoảng loạn.",
        "images": [{"page": 35, "priority": 0.5}, {"page": 36, "priority": 0.5}]
    },
    {
        "speech": "Những người lính đẫm máu điên cuồng siết cò súng lục, chiến đấu đến hơi thở cuối cùng khi bầy nhiễm bệnh tràn qua các chiến hào phòng thủ.",
        "images": [{"page": 37, "priority": 1.0}]
    },
    {
        "speech": "Những người sống sót chen lấn tháo chạy qua cầu thang tối tăm, tuyệt vọng giẫm đạp để thoát khỏi cỗ máy xay thịt đang siết chặt ngay sau lưng.",
        "images": [{"page": 38, "priority": 0.5}, {"page": 40, "priority": 0.5}]
    },
    {
        "speech": "Hơi thở dồn dập cùng adrenaline sục sôi, người cựu binh dày dạn kinh nghiệm ngước nhìn lên lối thoát hiểm duy nhất còn sót lại phía trên.",
        "images": [{"page": 42, "priority": 0.5}, {"page": 43, "priority": 0.5}]
    },
    {
        "speech": "Nâng cao khẩu súng trường với sự tập trung chết chóc tuyệt đối, anh khóa chặt mục tiêu vào cơn ác mộng đang tiến tới, sẵn sàng tiêu diệt bất cứ thứ gì dám bước qua ngưỡng cửa.",
        "images": [{"page": 44, "priority": 1.0}]
    }
]

async def main():
    target_url = "https://www.webtoons.com/en/action/zombie-revelation-82-08/list?title_no=6065"
    target_dir = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\downloads\zombie_revelation_8208_1_1_vi_350203a9"
    ep_dir = os.path.join(target_dir, "episode_1")
    output_dir = os.path.join(target_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(ep_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(ep_dir, "images_blur"), exist_ok=True)
    os.makedirs(os.path.join(ep_dir, "images_pdf"), exist_ok=True)
    os.makedirs(os.path.join(ep_dir, "pdf"), exist_ok=True)

    print("=" * 80)
    print("  Zombie Revelation: 82-08 - Episode 1 (Tiếng Việt - v1.6.2)")
    print(f"  Target Dir: {target_dir}")
    print(f"  Voice: OmniVoice ({config.DEFAULT_VI_VOICE})")
    print(f"  Motion: v1.6.2 Hybrid Motion (Adaptive Framing, 0% Horiz Pan, Ken Burns Zoom)")
    print("=" * 80)

    # 1. Reuse existing crawled images from zombie_revelation_8208_1_120_en_350203a9
    src_ep1 = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\downloads\zombie_revelation_8208_1_120_en_350203a9\episode_1"
    for subdir in ["images", "images_pdf", "images_blur", "pdf"]:
        src_sub = os.path.join(src_ep1, subdir)
        dst_sub = os.path.join(ep_dir, subdir)
        if os.path.exists(src_sub):
            for fname in os.listdir(src_sub):
                src_f = os.path.join(src_sub, fname)
                dst_f = os.path.join(dst_sub, fname)
                if not os.path.exists(dst_f):
                    shutil.copy2(src_f, dst_f)
    print(f"[CACHE] Đã đồng bộ toàn bộ tài nguyên hình ảnh vào {ep_dir}")

    # 2. Write Vietnamese recap.json and narration.txt
    recap_path = os.path.join(ep_dir, "recap.json")
    narration_path = os.path.join(ep_dir, "narration.txt")
    with open(recap_path, "w", encoding="utf-8") as f:
        json.dump(VIETNAMESE_RECAP_DATA, f, ensure_ascii=False, indent=2)
    print(f"[INIT] Đã ghi {len(VIETNAMESE_RECAP_DATA)} câu kịch bản tiếng Việt vào recap.json")

    narration_text = " ".join([item["speech"] for item in VIETNAMESE_RECAP_DATA])
    with open(narration_path, "w", encoding="utf-8") as f:
        f.write(narration_text)
    print(f"[INIT] Đã ghi narration.txt ({len(narration_text)} ký tự)")

    # 3. Precompute content_bounds_cache.json with true focal points and bubble repulsion
    bounds_cache_path = os.path.join(ep_dir, "content_bounds_cache.json")
    img_pdf_dir = os.path.join(ep_dir, "images_pdf")
    new_cache = {}
    files = [f for f in os.listdir(img_pdf_dir) if f.endswith(('.webp', '.png', '.jpg'))]
    files.sort()
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
    print(f"[CACHE] Đã khởi tạo content_bounds_cache.json với {len(new_cache)} frames chuẩn xác.")

    # 4. Clean old render outputs if any
    files_to_clean = [
        os.path.join(ep_dir, "video.mp4"),
        os.path.join(output_dir, "zombie_revelation_8208_1_1_vi_350203a9.mp4"),
    ]
    for fc in files_to_clean:
        if os.path.exists(fc):
            try:
                os.remove(fc)
            except Exception:
                pass

    # 5. Create WorkflowTask and execute Stages 7 -> 13
    task_id = f"zombie-revelation-8208-ep1-vi-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Zombie Revelation 82-08",
        comic_url=target_url,
        from_episode=1,
        to_episode=1,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": config.DEFAULT_VI_VOICE_ID,
            "ref_audio_path": config.DEFAULT_VI_REF_AUDIO,
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
    task.artifacts["download_folder_name"] = "zombie_revelation_8208_1_1_vi_350203a9"
    task.artifacts["comic_title"] = "Zombie Revelation 82-08"

    ctx = ConsoleContext(task)

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

    final_video = os.path.join(output_dir, "zombie_revelation_8208_1_1_vi_350203a9.mp4")
    print("\n" + "=" * 75)
    print("  [SUCCESS] HOÀN TẤT TẠO VIDEO RECAP TIẾNG VIỆT CHO TẬP 1")
    print(f"  Final Video: {final_video}")
    print(f"  Thư mục kết quả: {output_dir}")
    print("=" * 75)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
