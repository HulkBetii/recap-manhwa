import os
import sys
import asyncio
import json
import time
import shutil
import re
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
from clean_crop_ep2_panels import clean_crop_ep2_key_panels

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

# ---------------------------------------------------------------------------
# KỊCH BẢN TẬP 1 (22 PHÂN ĐOẠN TINH TUYỂN + FORESHADOWING GÃ QUAN SÁT)
# ---------------------------------------------------------------------------
EP1_CURATED_DATA = [
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
    },
    {
        "speech": "Thế nhưng ở một chiều không gian vô định, một thực thể ma quái đang theo dõi từng cử động của anh qua màn hình, nở nụ cười toan tính trước món mồi vô giá sắp sửa rơi vào tay.",
        "images": [{"page": 38, "priority": 0.5}, {"page": 40, "priority": 0.5}]
    }
]

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# KỊCH BẢN TẬP 2 v2.0 (28 PHÂN ĐOẠN ĐIỆN ẢNH, PACING TỐI ƯU & CLIMAX TOÀN DIỆN)
# ---------------------------------------------------------------------------
EP2_CURATED_DATA = [
    {
        "speech": "Trước khi trở thành kẻ độc hành ở tầng chín mươi chín, cuộc đời của Jaehwan bắt đầu từ một buổi chiều yên bình trong cửa hàng tiện lợi.",
        "images": [{"page": 2, "priority": 1.0}]
    },
    {
        "speech": "Bất ngờ, mặt đất dưới chân rung chuyển dữ dội, bản tin khẩn cấp cảnh báo về những chấn động bất thường chưa từng có trong lịch sử.",
        "images": [{"page": 4, "priority": 1.0}]
    },
    {
        "speech": "Mặt đường vỡ toác thành từng mảnh lớn, kính cửa sổ nổ tung giữa tiếng la hét hoảng loạn tột cùng của dòng người tháo chạy.",
        "images": [{"page": 8, "priority": 1.0}]
    },
    {
        "speech": "Giữa đống đổ nát mù mịt khói bụi, Jaehwan vội vàng ôm chặt che chắn cho một bé gái khỏi mảng trần nhà đang đổ sập.",
        "images": [{"page": 12, "priority": 1.0}]
    },
    {
        "speech": "Ngước nhìn ra bên ngoài, mọi người chết lặng khi chứng kiến những khối kiến trúc khổng lồ dị hợm đồng loạt đâm toạc bầu trời.",
        "images": [{"page": 16, "priority": 1.0}]
    },
    {
        "speech": "Không chỉ tại Seoul, hàng loạt tòa tháp bí ẩn xuất hiện khắp các đại lục từ Anh Quốc, Nhật Bản đến châu Mỹ, đẩy văn minh nhân loại vào bế tắc.",
        "images": [{"page": 19, "priority": 1.0}]
    },
    {
        "speech": "Đúng lúc đó, thông điệp ma mị hiện lên trước mắt mọi người, mời gọi những ai dũng cảm bước vào tháp để ngăn chặn ngày tàn.",
        "images": [{"page": 24, "priority": 1.0}]
    },
    {
        "speech": "Chẳng chút ngần ngại, Jaehwan cùng hàng vạn người chạm tay xác nhận lời hiệu triệu, biến mất trong luồng ánh sáng chói lòa.",
        "images": [{"page": 25, "priority": 1.0}]
    },
    {
        "speech": "Đặt chân vào bên trong, mỗi người được trang bị vũ khí, giáp trụ và tiền tệ hệt như đang tham gia vào một trò chơi sinh tử thực tế ảo.",
        "images": [{"page": 26, "priority": 1.0}]
    },
    {
        "speech": "Thế nhưng sự hào hứng nhanh chóng vụt tắt khi hệ thống lạnh lùng tuyên bố: Thảm Họa Va Chạm Tháp sắp sửa giáng thẳng xuống thế giới bên ngoài.",
        "images": [{"page": 30, "priority": 1.0}]
    },
    {
        "speech": "Tại chân tháp ngoài thực tại, một bóng đen quái dị xuất hiện trên gờ tường cao ngất, để lộ móng vuốt sắc lẹm và sát khí rợn người.",
        "images": [{"page": 34, "priority": 1.0}]
    },
    {
        "speech": "Nụ cười ngoác tận mang tai cùng hàm răng nhọn hoắt gầm thét xé toạc không gian, báo hiệu cuộc đại đồ sát chính thức bắt đầu.",
        "images": [{"page": 36, "priority": 1.0}]
    },
    {
        "speech": "Bầu trời bên ngoài biến thành bãi săn khổng lồ khi bầy quái thú có cánh lao xuống cắn xé, san phẳng các đô thị phồn hoa thành tro tàn đổ nát.",
        "images": [{"page": 41, "priority": 1.0}]
    },
    {
        "speech": "Nhìn quê hương chìm trong biển máu qua khung cửa tháp, đoàn người chết lặng trong đau đớn và thề sẽ leo lên đỉnh cao nhất để chấm dứt cơn ác mộng.",
        "images": [{"page": 47, "priority": 1.0}]
    },
    {
        "speech": "Jaehwan cùng đồng đội khoác lên mình chiến bào, dũng cảm xông pha chém giết quái vật mở đường qua từng tầng hiểm nguy.",
        "images": [{"page": 53, "priority": 1.0}]
    },
    {
        "speech": "Sau những trận chiến nghẹt thở, một bức tường đá khổng lồ chắn ngang lối đi như chiếc khóa kiên cố dập tắt nhuệ khí cả đoàn.",
        "images": [{"page": 58, "priority": 1.0}]
    },
    {
        "speech": "Thủ lĩnh Inchan vung chùy tạ đập vỡ tảng đá cản đường, để lộ tia sáng xanh kỳ lạ ẩn giấu bên trong đống gạch vụn.",
        "images": [{"page": 60, "priority": 1.0}]
    },
    {
        "speech": "Vật phẩm phát sáng ấy chính là Đá Quy Hồi—thứ ban cho kẻ sở hữu cơ hội quay ngược thời gian về ngày đầu tiên được triệu hồi.",
        "images": [{"page": 62, "priority": 1.0}]
    },
    {
        "speech": "Không chịu nổi áp lực sinh tử nghẹt thở, thủ lĩnh Inchan lập tức kích hoạt viên đá, bỏ mặc đồng đội để trốn chạy về quá khứ trong ánh sáng chói lòa.",
        "images": [{"page": 64, "priority": 1.0}]
    },
    {
        "speech": "Giữa lúc cả nhóm hoang mang hy vọng thủ lĩnh sẽ quay lại giải cứu, cựu giáo viên Sakamoto khẽ đẩy gọng kính với vẻ mặt cực kỳ nghiêm trọng.",
        "images": [{"page": 71, "priority": 1.0}]
    },
    {
        "speech": "Dựa trên thuyết Đa Vũ Trụ, Sakamoto vạch trần sự thật cay đắng: kẻ hồi quy chỉ tách sang một dòng thời gian khác, bỏ lại thế giới này vĩnh viễn sụp đổ.",
        "images": [{"page": 73, "priority": 1.0}]
    },
    {
        "speech": "Nhận ra Đá Quy Hồi thực chất chỉ là tấm vé bỏ chạy một chiều đầy ích kỷ, tinh thần chiến đấu của mọi người bắt đầu rạn nứt dữ dội.",
        "images": [{"page": 78, "priority": 1.0}]
    },
    {
        "speech": "Bầu trời tháp đột ngột chuyển sang sắc đỏ máu cùng sấm sét rền vang, đợt va chạm tháp thứ hai ập đến với lũ quái thú tàn bạo hơn gấp bội.",
        "images": [{"page": 87, "priority": 1.0}]
    },
    {
        "speech": "Lũ quái thú dị hợm lao vào cắn xé như vũ bão, từng nhát chém gãy vụn và máu nhuộm đỏ thanh gươm của những dũng sĩ xấu số.",
        "images": [{"page": 89, "priority": 0.4}, {"page": 92, "priority": 0.6}]
    },
    {
        "speech": "Trước lằn ranh cái chết, từng người một nghẹn ngào nói lời xin lỗi rồi bóp nát viên đá quy hồi để trốn chạy khỏi hiện thực tàn khốc.",
        "images": [{"page": 94, "priority": 0.4}, {"page": 96, "priority": 0.6}]
    },
    {
        "speech": "Giữa bãi chiến trường hoang phế chỉ còn lại máu và sự phản bội, Jaehwan bắt chéo song kiếm, ánh mắt lóe sáng tử chiến quyết không quay đầu!",
        "images": [{"page": 100, "priority": 1.0}]
    },
    {
        "speech": "Từng đường kiếm cuồng phong rực sáng xé toạc không gian, Jaehwan dồn toàn bộ sức mạnh chém nát đầu lâu con quái thú khổng lồ giữa tiếng gầm rú kinh hoàng!",
        "images": [{"page": 102, "priority": 1.0}]
    },
    {
        "speech": "Nhưng khi khói bụi lắng xuống, xung quanh anh chỉ còn lại sự im lặng đến rợn người. Toàn bộ đồng đội đã bỏ chạy hết, chỉ còn lại mình anh đơn độc bước tiếp trên con đường của kẻ không bao giờ lùi bước.",
        "images": [{"page": 107, "priority": 0.5}, {"page": 114, "priority": 0.5}]
    }
]

def update_content_bounds(img_pdf_dir: str, cache_path: str):
    files = [f for f in os.listdir(img_pdf_dir) if f.endswith(('.webp', '.png', '.jpg')) and not f.endswith('_orig.webp')]
    files.sort()
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
    with open(cache_path, "w", encoding="utf-8") as cf:
        json.dump(new_cache, cf, indent=4)
    print(f"[CACHE] Đã cập nhật {cache_path} cho {len(new_cache)} frames.")

async def main():
    target_url = "https://www.webtoons.com/en/action/the-world-after-the-fall/list?title_no=4011"
    target_dir = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\downloads\the_world_after_the_fall_1_2_vi_be5d3841"
    ep1_dir = os.path.join(target_dir, "episode_1")
    ep2_dir = os.path.join(target_dir, "episode_2")
    output_dir = os.path.join(target_dir, "output")

    os.makedirs(ep1_dir, exist_ok=True)
    os.makedirs(ep2_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 80)
    print("  The World After The Fall - BATCH RECAP SERIES (Tập 1 + Tập 2 Tiếng Việt)")
    print(f"  Target Dir: {target_dir}")
    print(f"  Voice: OmniVoice ({config.DEFAULT_VI_VOICE})")
    print(f"  Motion: v1.6.5 Hybrid Motion (Bubble-Exclusion Pan, Ken Burns Zoom, 0% Horiz Pan)")
    print(f"  Pure Artwork: Clean-Crop Pixel-Perfect trên cả 2 tập")
    print("=" * 80)

    # -------------------------------------------------------------
    # 1. SETUP EPISODE 1 ASSETS
    # -------------------------------------------------------------
    src_ep1 = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\downloads\the_world_after_the_fall_1_1_vi_be5d3841\episode_1"
    ep1_img_pdf = os.path.join(ep1_dir, "images_pdf")
    if not os.path.exists(ep1_img_pdf) or len(os.listdir(ep1_img_pdf)) < 30:
        print(f"[SETUP] Sao chép dữ liệu hoàn chỉnh của Tập 1 sang {ep1_dir}...")
        for sub in ["images_pdf", "images_blur", "backup_orig"]:
            s = os.path.join(src_ep1, sub)
            d = os.path.join(ep1_dir, sub)
            if os.path.exists(s):
                if os.path.exists(d): shutil.rmtree(d)
                shutil.copytree(s, d)

    # Clean crop Ep 1 key panels (now including P38 and P40)
    clean_crop_key_panels(ep1_img_pdf)

    # Update Ep 1 recap.json and narration.txt
    ep1_recap_path = os.path.join(ep1_dir, "recap.json")
    with open(ep1_recap_path, "w", encoding="utf-8") as f:
        json.dump(EP1_CURATED_DATA, f, ensure_ascii=False, indent=2)
    ep1_narration_path = os.path.join(ep1_dir, "narration.txt")
    ep1_narration = " ".join([seg["speech"] for seg in EP1_CURATED_DATA])
    with open(ep1_narration_path, "w", encoding="utf-8") as f:
        f.write(ep1_narration)
    update_content_bounds(ep1_img_pdf, os.path.join(ep1_dir, "content_bounds_cache.json"))

    # -------------------------------------------------------------
    # 2. SETUP EPISODE 2 ASSETS
    # -------------------------------------------------------------
    src_ep2 = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\downloads\the_world_after_the_fall_1_3_vi_be5d3841\episode_2"
    ep2_img_pdf = os.path.join(ep2_dir, "images_pdf")
    if not os.path.exists(ep2_img_pdf) or len(os.listdir(ep2_img_pdf)) < 50:
        print(f"[SETUP] Sao chép dữ liệu của Tập 2 sang {ep2_dir}...")
        for sub in ["images_pdf", "images_blur"]:
            s = os.path.join(src_ep2, sub)
            d = os.path.join(ep2_dir, sub)
            if os.path.exists(s):
                if os.path.exists(d): shutil.rmtree(d)
                shutil.copytree(s, d)

    # Clean crop Ep 2 key panels
    clean_crop_ep2_key_panels(ep2_img_pdf)

    # Update Ep 2 recap.json and narration.txt
    ep2_recap_path = os.path.join(ep2_dir, "recap.json")
    with open(ep2_recap_path, "w", encoding="utf-8") as f:
        json.dump(EP2_CURATED_DATA, f, ensure_ascii=False, indent=2)
    ep2_narration_path = os.path.join(ep2_dir, "narration.txt")
    ep2_narration = " ".join([seg["speech"] for seg in EP2_CURATED_DATA])
    with open(ep2_narration_path, "w", encoding="utf-8") as f:
        f.write(ep2_narration)
    update_content_bounds(ep2_img_pdf, os.path.join(ep2_dir, "content_bounds_cache.json"))

    # Dọn dẹp cache cũ của Episode 2 để render kịch bản v2.0 mới
    print("[SETUP] Dọn dẹp cache cũ của Tập 2 để sinh lại TTS và render video v2.0...")
    for cf in ["audio.mp3", "transcript.srt", "video.mp4", "artifact_manifest.json"]:
        cp = os.path.join(ep2_dir, cf)
        if os.path.exists(cp):
            os.remove(cp)
    ep2_cache_dir = os.path.join(ep2_dir, ".stage_cache")
    if os.path.exists(ep2_cache_dir):
        shutil.rmtree(ep2_cache_dir)
    for out_f in os.listdir(output_dir):
        try:
            os.remove(os.path.join(output_dir, out_f))
        except Exception:
            pass

    # -------------------------------------------------------------
    # 3. CONFIGURE WORKFLOW TASK (FROM EPISODE 1 TO 2)
    # -------------------------------------------------------------
    task_id = f"the-world-after-the-fall-ep1-2-vi-{int(time.time())}"
    task = WorkflowTask(
        comic_title="The World After The Fall",
        comic_url=target_url,
        from_episode=1,
        to_episode=2,
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
    task.artifacts["download_folder_name"] = "the_world_after_the_fall_1_2_vi_be5d3841"
    task.artifacts["comic_title"] = "The World After The Fall"

    ctx = ConsoleContext(task)

    # Execution pipeline:
    # Ep 1 has 22 segments (Seg 22 added), Ep 2 has 26 segments.
    # Stage 7 (Aggregation) -> Stage 8 (TTS) -> Stage 9 (Whisper) -> Stage 10 (Render Video) -> Stage 11 (Assembly) -> Stage 12 (Metadata)
    pipeline = [
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
        Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
    ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n>>> BẮT ĐẦU: {stage.name}", flush=True)
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

    # -------------------------------------------------------------
    # 4. UPDATE STORY MEMORY JSON
    # -------------------------------------------------------------
    story_mem_path = os.path.join(target_dir, "story_memory.json")
    story_memory = {
        "comic_title": "The World After The Fall",
        "language": "vi",
        "protagonist_name": "Jaehwan",
        "protagonist_gender": "male",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_episodes_recorded": 2,
        "episodes": {
            "1": {
                "episode": 1,
                "opening": "Giữa ngày tàn của thế giới khi tòa tháp bí ẩn trồi lên nuốt chửng bầu trời đô thị, Jaehwan quyết định dấn thân vào con đường sinh tử.",
                "closing_cliffhanger": "Thế nhưng ở một chiều không gian vô định, một thực thể ma quái đang theo dõi từng cử động của anh qua màn hình, nở nụ cười toan tính trước món mồi vô giá sắp sửa rơi vào tay.",
                "summary": "Tòa tháp bí ẩn trồi lên giữa đô thị. Jaehwan dẫn đầu hàng vạn chiến binh vượt qua các tầng tháp. Khi Hồi Quy Thạch xuất hiện, đồng đội lần lượt bỏ chạy về quá khứ. Người bạn thân Yunhwan qua đời với mảnh đá vỡ nát. Jaehwan từ chối hồi quy, xông lên tầng 99 quyết tử với quái thú rồng tuyết, trong sự theo dõi của một thực thể ma quái cõi ngoài.",
                "segment_count": len(EP1_CURATED_DATA),
                "timestamp": time.time()
            },
            "2": {
                "episode": 2,
                "opening": "Trước khi trở thành kẻ độc hành ở tầng chín mươi chín, cuộc đời của Jaehwan bắt đầu từ một buổi chiều yên bình trong cửa hàng tiện lợi.",
                "closing_cliffhanger": "Nhưng khi khói bụi lắng xuống, xung quanh anh chỉ còn lại sự im lặng đến rợn người. Toàn bộ đồng đội đã bỏ chạy hết, chỉ còn lại mình anh đơn độc bước tiếp trên con đường của kẻ không bao giờ lùi bước.",
                "summary": "Hồi tưởng về ngày đầu tiên khi tòa tháp trồi lên toàn cầu. Thảm Họa Va Chạm Tháp khiến quái vật tàn sát thế giới bên ngoài. Jaehwan cùng nhóm chiến binh bước vào tháp và tìm thấy Đá Quy Hồi. Thủ lĩnh Inchan trốn chạy. Cựu giáo viên Sakamoto vạch trần thuyết Đa Vũ Trụ: hồi quy là sự ích kỷ bỏ mặc thế giới này sụp đổ. Đợt quái vật thứ hai giáng xuống, đồng đội lần lượt bóp đá tháo lui. Jaehwan chém nát đầu quái thú khổng lồ, nhưng rồi nhận ra toàn bộ đồng đội đều đã bỏ chạy, mở đầu cho định mệnh cô độc của anh.",
                "segment_count": len(EP2_CURATED_DATA),
                "timestamp": time.time()
            }
        },
        "cumulative_glossary": {
            "Jaehwan": "Nhân vật chính, kẻ duy nhất kiên định không bao giờ dùng Đá Quy Hồi",
            "Đá Quy Hồi / Hồi Quy Thạch": "Vật phẩm đưa người dùng quay về quá khứ nhưng thực chất tạo ra một dòng thời gian song song, bỏ lại thế giới gốc",
            "Thảm Họa Va Chạm Tháp (Tower Impact)": "Hiện tượng quái vật từ tháp tràn ra tàn sát thế giới loài người bên ngoài",
            "Walker / Người Đi Tháp": "Những người được triệu hồi vào bên trong tháp",
            "Inchan": "Thủ lĩnh đầu tiên của nhóm người đi tháp, kẻ đầu tiên dùng đá quy hồi để trốn chạy",
            "Sakamoto": "Cựu giáo viên khoa học, người phân tích thuyết Đa Vũ Trụ lật tẩy bản chất của Đá Quy Hồi"
        }
    }
    with open(story_mem_path, "w", encoding="utf-8") as smf:
        json.dump(story_memory, smf, ensure_ascii=False, indent=2)
    print(f"[MEMORY] Đã cập nhật story_memory.json chuẩn xác cho chuỗi series tại {story_mem_path}")

    task.status = WorkflowState.SUCCESS
    task.current_stage = "Completed"
    task.overall_progress = 100.0
    ctx._sync_task_db()

    final_merged_video = os.path.join(output_dir, "the_world_after_the_fall_1_2_vi_be5d3841.mp4")
    print("\n" + "=" * 80)
    print("  [SUCCESS] HOÀN TẤT TẠO CHUỖI SERIES RECAP TẬP 1 + TẬP 2 TIẾNG VIỆT!")
    print(f"  Merged Series Video: {final_merged_video}")
    print(f"  Ep 1 Video: {os.path.join(ep1_dir, 'video.mp4')}")
    print(f"  Ep 2 Video: {os.path.join(ep2_dir, 'video.mp4')}")
    print(f"  Output Directory: {output_dir}")
    print("=" * 80)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
