import os
import sys
import asyncio
import json
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.chdir(r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")
sys.path.insert(0, r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import (
    Stage0_ProjectInit, Stage1_ComicParsing, Stage2_AsyncImageCrawling,
    Stage2b_IntelligentRepagination, Stage3_NSFWModeration, Stage4_PDFGeneration,
    Stage5_GeminiAutomation, Stage6_JSONExtraction,
)
from workflow_stages_2 import (
    Stage7_NarrationAggregation, Stage8_LocalTTS, Stage9_SubtitleNormalization,
    Stage10_EpisodeVideoRendering, Stage11_FinalVideoAssembly,
    Stage12_MetadataReports, Stage13_Cleanup,
)

class SimpleCancelToken:
    def is_cancelled(self): return False

class ConsoleContext:
    def __init__(self, task):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload
    async def log(self, message, level="info", *a, **kw):
        print(f"[{level.upper()}] {message}", flush=True)
        self.task.logs.append({"timestamp": time.strftime("%H:%M:%S"), "level": level, "message": message, "stage": self.task.current_stage, "episode": self.task.current_episode})
        self._sync_task_db()
    async def start_episode(self, ep): self.task.current_episode = ep; await self.log(f"Starting episode {ep}...", "info")
    async def complete_episode(self, ep): await self.log(f"Completed episode {ep}.", "success")
    async def fail_episode(self, ep, error): await self.log(f"Episode {ep} error: {error}", "error")
    async def update_stage_progress(self, stage_name, progress):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True); self._sync_task_db()
    async def update_progress(self, progress, stage_name=None, episode=None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True); self._sync_task_db()
    def _sync_task_db(self):
        try:
            db_path = "tasks_db.json"; tmp = db_path + ".tmp"
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f: db = json.load(f)
                db[self.task.id] = self.task.to_storage_dict()
                with open(tmp, "w", encoding="utf-8") as f: json.dump(db, f, ensure_ascii=False, indent=2)
                for _ in range(10):
                    try: os.replace(tmp, db_path); break
                    except: time.sleep(0.08)
        except: pass

VIETNAMESE_RECAP_DATA = [
    {
        "speech": "Kẹt trong một cuộc sống ngột ngạt và cô độc, Seou chợt nhớ về cậu bé năm xưa từng ngỏ lời rủ cô cùng trốn chạy vào bóng tối.",
        "images": [{"page": 4, "priority": 0.5}, {"page": 5, "priority": 0.5}]
    },
    {
        "speech": "Cậu từng tha thiết bảo cô hãy ở lại dưới lòng đất cùng mình, chỉ tay về phía một cánh cửa nơi ánh sáng vĩnh viễn không thể chạm tới.",
        "images": [{"page": 6, "priority": 1.0}]
    },
    {
        "speech": "Hoảng sợ trước khoảng không tăm tối và bí ẩn toát ra từ cậu, cô đã vội vã tháo chạy trở lại dưới cái nắng gay gắt của mùa hè.",
        "images": [{"page": 8, "priority": 0.5}, {"page": 9, "priority": 0.5}]
    },
    {
        "speech": "Cô chạy thục mạng bằng tất cả sức lực của đôi chân, tuyệt đối không một lần dám ngoái đầu nhìn lại.",
        "images": [{"page": 10, "priority": 1.0}]
    },
    {
        "speech": "Nhiều năm trôi qua, một cơn mưa rào mùa hạ xối xả trút xuống trường trung học, trong khi những tiếng xì xào bàn tán vang khắp lớp học ồn ào.",
        "images": [{"page": 12, "priority": 0.5}, {"page": 13, "priority": 0.5}]
    },
    {
        "speech": "Đám bạn cùng lớp liên tục chế giễu bức tường bê tông đổ nát sừng sững bên kia đường, xem nó như một chướng ngại vật xấu xí cần biến mất.",
        "images": [{"page": 14, "priority": 0.5}, {"page": 15, "priority": 0.5}]
    },
    {
        "speech": "Những rào chắn giao thông được dựng lên kín mít xung quanh, phong tỏa hoàn toàn rào chắn mục nát trước ngày tháo dỡ định sẵn.",
        "images": [{"page": 16, "priority": 1.0}]
    },
    {
        "speech": "Mấy đứa con gái khúc khích bàn tán về những tin đồn rùng rợn, tự hỏi liệu có phải ai đó vừa nhảy lầu từ trên đỉnh xuống để thúc ép thành phố phá dỡ.",
        "images": [{"page": 17, "priority": 0.5}, {"page": 18, "priority": 0.5}]
    },
    {
        "speech": "Một cú huých thô bạo bất ngờ làm chiếc bàn rung lắc mạnh, đập tan mọi nỗ lực thu mình vô hình trong góc tối của cô.",
        "images": [{"page": 19, "priority": 0.5}, {"page": 20, "priority": 0.5}]
    },
    {
        "speech": "Đứa con gái loạng choạng bước tới trong ngỡ ngàng, đột nhiên nhìn thấy kẻ bị ruồng bỏ đang co ro lặng lẽ ở dãy bàn đầu.",
        "images": [{"page": 22, "priority": 0.5}, {"page": 23, "priority": 0.5}]
    },
    {
        "speech": "Một tiếng nạt nộ hung hăng lập tức vang lên, gằn giọng chất vấn tại sao cô lại dám ngồi chình ình ở vị trí này.",
        "images": [{"page": 24, "priority": 1.0}]
    },
    {
        "speech": "Những lời thì thầm ác ý lập tức biến cô thành một bóng ma vô hình lẩn khuất nơi góc phòng học.",
        "images": [{"page": 25, "priority": 1.0}]
    },
    {
        "speech": "Thay vì đứng ra can ngăn sự tàn nhẫn ấy, đứa em kế Jiwon chỉ thản nhiên bấm điện thoại và bảo kẻ bắt nạt cứ lờ cô đi.",
        "images": [{"page": 26, "priority": 0.5}, {"page": 27, "priority": 0.5}]
    },
    {
        "speech": "Seou nắm chặt các đốt ngón tay đến trắng bệch dưới gầm bàn, cắn răng nuốt cay đắng và nỗi sỉ nhục trước đám đông trong im lặng.",
        "images": [{"page": 28, "priority": 0.5}, {"page": 29, "priority": 0.5}]
    },
    {
        "speech": "Những căn hầm quân sự tàn tích và rào chắn biên giới lãng quên nằm rải rác khắp thị trấn, như những vết tích sót lại của một thời chiến sự xa xôi.",
        "images": [{"page": 30, "priority": 0.5}, {"page": 33, "priority": 0.5}]
    },
    {
        "speech": "Người dân trong thị trấn chỉ cảm thấy chướng mắt với những công trình bỏ hoang, xem chúng như những vết sẹo vô dụng hơn là di tích lịch sử.",
        "images": [{"page": 35, "priority": 0.5}, {"page": 37, "priority": 0.5}]
    },
    {
        "speech": "Tan học sớm hơn thường lệ, Seou ngập ngừng thật lâu trước khi bấm mật mã ổ khóa điện tử để bước vào căn hộ của gia đình.",
        "images": [{"page": 39, "priority": 0.5}, {"page": 40, "priority": 0.5}]
    },
    {
        "speech": "Người mẹ kế lạnh nhạt chào hỏi từ chiếc sofa phòng khách, trong khi người cha dượng chỉ ngồi trầm ngâm im lặng gần đó.",
        "images": [{"page": 41, "priority": 0.5}, {"page": 42, "priority": 0.5}]
    },
    {
        "speech": "Một lời nhận xét buốt giá từ người cha dượng nhắc nhở cô ngay tức khắc rằng cô đã trở về nhà quá sớm.",
        "images": [{"page": 43, "priority": 1.0}]
    },
    {
        "speech": "Cô ngoan ngoãn cúi đầu bước nhanh về phòng riêng để tránh khỏi tầm mắt khó chịu của hai người.",
        "images": [{"page": 44, "priority": 1.0}]
    },
    {
        "speech": "Mẹ kế lập tức quay ngoắt sang niềm nở với Jiwon, săn đón đứa con gái cưng ngay giây phút nó vừa bước chân vào cửa.",
        "images": [{"page": 45, "priority": 0.5}, {"page": 46, "priority": 0.5}]
    },
    {
        "speech": "Bước vào căn phòng ngủ chật chội dùng chung, Seou chỉ nhận lại một ánh nhìn tràn ngập sự khinh bỉ và ghẻ lạnh.",
        "images": [{"page": 47, "priority": 0.5}, {"page": 48, "priority": 0.5}]
    },
    {
        "speech": "Jiwon hung hăng huých mạnh vào vai cô, thô bạo gạt cô sang một bên mà không hề tỏ ra chút ăn năn nào.",
        "images": [{"page": 49, "priority": 1.0}]
    },
    {
        "speech": "Một cơn thịnh nộ giận dữ bùng nổ ngoài hành lang khi Jiwon gào lên phàn nàn về việc phải sống chung phòng với một gánh nặng thừa thãi.",
        "images": [{"page": 50, "priority": 1.0}]
    },
    {
        "speech": "Từng lời cay độc xuyên thẳng qua bức tường mỏng manh, chất vấn tại sao gia đình họ lại phải cưu mang và nuôi nấng cô.",
        "images": [{"page": 51, "priority": 0.5}, {"page": 52, "priority": 0.5}]
    },
    {
        "speech": "Đứng chết trân bên khung cửa phòng ngủ, cô cắn răng đối diện với sự thật chua chát rằng chẳng có bất kỳ ai trong ngôi nhà này muốn thấy sự tồn tại của cô.",
        "images": [{"page": 53, "priority": 0.5}, {"page": 54, "priority": 0.5}]
    },
    {
        "speech": "Khi người mẹ kế bắt gặp cô đang đứng lặng bên khung cửa, một thoáng bối rối xen lẫn hoảng sợ hiện rõ trên khuôn mặt bà ta.",
        "images": [{"page": 55, "priority": 0.5}, {"page": 56, "priority": 0.5}]
    },
    {
        "speech": "Giả vờ quan tâm một cách lịch thiệp, người giám hộ xua đi sự tàn nhẫn bằng những lời viện cớ sáo rỗng về tính khí thất thường của Jiwon.",
        "images": [{"page": 57, "priority": 0.5}, {"page": 58, "priority": 0.5}]
    },
    {
        "speech": "Một chiếc túi xách qua đêm đã được soạn sẵn bị dúi vào tay cô, kèm theo lời đề nghị khe khẽ bảo cô hãy ra ngoài tìm chỗ ngủ nhờ đêm nay.",
        "images": [{"page": 59, "priority": 0.5}, {"page": 60, "priority": 0.5}]
    },
    {
        "speech": "Gạt đi lòng tự trọng bị chà đạp, Seou khẽ nói lời cảm ơn rồi nhận lấy chiếc túi và bước lầm lũi quay trở lại màn mưa bão.",
        "images": [{"page": 61, "priority": 0.5}, {"page": 62, "priority": 0.5}]
    },
    {
        "speech": "Mở chiếc túi ngoài trời mưa, hơi thở cô nghẹn lại khi bất ngờ phát hiện một cọc tiền mặt dày cộp được nhét vội bên trong.",
        "images": [{"page": 64, "priority": 0.5}, {"page": 65, "priority": 0.5}]
    },
    {
        "speech": "Bị bỏ rơi trơ trọi giữa cơn mưa tầm tã xối xả, cô lê từng bước chân nặng trĩu bước lên những bậc thang dẫn tới bức tường bê tông hoang vắng.",
        "images": [{"page": 64, "priority": 0.5}, {"page": 65, "priority": 0.5}]
    },
    {
        "speech": "Nhìn xuống qua khe lan can kim loại, cô bất ngờ phát hiện một cánh cửa nắp hầm trú ẩn rỉ sét nằm ẩn mình ngay bên dưới mép đường nhựa.",
        "images": [{"page": 72, "priority": 0.5}, {"page": 75, "priority": 0.5}]
    },
    {
        "speech": "Kiệt sức hoàn toàn sau chuỗi ngày chịu đựng, Seou dùng hết sức kéo mở chiếc nắp nặng nề rồi bước xuống lòng đất tăm tối.",
        "images": [{"page": 75, "priority": 0.5}, {"page": 81, "priority": 0.5}]
    },
    {
        "speech": "Bên trong căn phòng ngầm, nguồn điện bất ngờ chớp sáng, thắp lên một không gian trú ẩn đầy đủ tiện nghi ngoài sức tưởng tượng.",
        "images": [{"page": 86, "priority": 1.0}]
    },
    {
        "speech": "Một chiếc giường đôi tinh tươm, những kệ hàng đầy ắp thực phẩm và vật dụng tươi mới đã biến tàn tích bỏ hoang này thành một tổ ấm thực thụ.",
        "images": [{"page": 86, "priority": 0.5}, {"page": 88, "priority": 0.5}]
    },
    {
        "speech": "Ánh mắt cô dừng lại ở một khung ảnh gia đình nhỏ được đặt lặng lẽ ngay trên kệ sách.",
        "images": [{"page": 88, "priority": 0.5}, {"page": 89, "priority": 0.5}]
    },
    {
        "speech": "Khuôn mặt một đứa trẻ quen thuộc mỉm cười qua lớp kính, chính là cậu bé năm xưa từng biến mất không dấu vết sau khi ngỏ lời cho cô nơi trú ẩn.",
        "images": [{"page": 89, "priority": 0.5}, {"page": 91, "priority": 0.5}]
    },
    {
        "speech": "Ớn lạnh đến tận xương tủy, cô chợt bàng hoàng nhận ra căn hầm kiên cố này không hề vô chủ; suốt bấy lâu nay, luôn có một người bí mật sinh sống tại đây.",
        "images": [{"page": 93, "priority": 0.5}, {"page": 94, "priority": 0.5}]
    },
    {
        "speech": "Bất thình lình, những tiếng bước chân dồn dập vang lên từ đường ống thông phía trên khi nắp thép bị kéo mở.",
        "images": [{"page": 97, "priority": 0.5}, {"page": 98, "priority": 0.5}]
    },
    {
        "speech": "Tiếng ủng da nện từng bước chắc nịch xuống các bậc thang sắt khi một kẻ đột nhập đầy uy lực bắt đầu hạ mình xuống căn hầm.",
        "images": [{"page": 99, "priority": 0.5}, {"page": 100, "priority": 0.5}]
    },
    {
        "speech": "Một chàng trai cao lớn với vẻ ngoài phong trần, từng trải bước chân xuống sàn, ánh mắt sắc lẹm đảo quanh căn phòng mờ ảo.",
        "images": [{"page": 98, "priority": 0.5}, {"page": 105, "priority": 0.5}]
    },
    {
        "speech": "Paran buông chiếc túi xách rơi phịch xuống sàn nhà, ánh mắt khóa chặt vào kẻ xâm nhập lạ mặt đang run rẩy co rúm trong thánh địa riêng tư của mình.",
        "images": [{"page": 105, "priority": 0.5}, {"page": 108, "priority": 0.5}]
    },
    {
        "speech": "Đứng chết lặng trong nỗi sợ hãi tột cùng sát bức tường phía sau, cô tuyệt vọng đối diện với sự thật lạnh lùng rằng không còn lối thoát nào nữa.",
        "images": [{"page": 111, "priority": 1.0}]
    },
    {
        "speech": "Cậu sừng sững đứng áp đảo ngay trước mặt cô, phá vỡ bầu không khí căng thẳng bằng lời gặng hỏi xem cô nghĩ mình đang làm cái quái gì trong hầm của cậu.",
        "images": [{"page": 120, "priority": 0.5}, {"page": 126, "priority": 0.5}]
    },
    {
        "speech": "Khi cô vừa nghẹn ngào nhận ra thân phận của người bạn thời thơ ấu, Paran chỉ đáp lại bằng ánh nhìn lạnh băng, hoàn toàn vô cảm.",
        "images": [{"page": 125, "priority": 0.5}, {"page": 126, "priority": 0.5}]
    },
    {
        "speech": "Thay vì một cuộc hội ngộ ấm áp đầy xúc động, cậu thẳng thừng ra lệnh đuổi cô cút ngay ra ngoài trước khi hoàn toàn khép chặt lòng mình.",
        "images": [{"page": 127, "priority": 0.5}, {"page": 128, "priority": 0.5}]
    },
    {
        "speech": "Mặc cho cơn bão bên ngoài vẫn gầm thét dữ dội, cậu đứng trước mặt cô tựa như một người xa lạ, khóa chặt cánh cửa thế giới ngầm bao quanh hai người.",
        "images": [{"page": 130, "priority": 0.5}, {"page": 133, "priority": 0.5}]
    }
]

async def main():
    target_url = "https://www.webtoons.com/en/drama/daytime-in-the-bunker/list?title_no=9842"
    target_dir = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\downloads\daytime_in_the_bunker_1_1_en_0c1945fd"
    ep_dir = os.path.join(target_dir, "episode_1")
    output_dir = os.path.join(target_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 75)
    print("  Daytime in the Bunker - Episode 1 (Tiếng Việt - v1.6.0)")
    print(f"  Target Dir: {target_dir}")
    print(f"  Voice ID: {config.DEFAULT_VI_VOICE_ID} (OmniVoice Voice Cloning)")
    print(f"  Ref Audio: {config.DEFAULT_VI_REF_AUDIO}")
    print(f"  Motion: Continuous Vertical Pan Glide (soft_linear_glide)")
    print("=" * 75)

    # 1. Write Vietnamese recap.json and narration.txt
    recap_path = os.path.join(ep_dir, "recap.json")
    narration_path = os.path.join(ep_dir, "narration.txt")

    with open(recap_path, "w", encoding="utf-8") as f:
        json.dump(VIETNAMESE_RECAP_DATA, f, ensure_ascii=False, indent=2)
    print(f"[INIT] Đã ghi {len(VIETNAMESE_RECAP_DATA)} câu kịch bản tiếng Việt vào recap.json")

    narration_text = " ".join([item["speech"] for item in VIETNAMESE_RECAP_DATA])
    with open(narration_path, "w", encoding="utf-8") as f:
        f.write(narration_text)
    print(f"[INIT] Đã ghi narration.txt ({len(narration_text)} ký tự)")

    # 2. Clean old video renders to force fresh Stage 10 video rendering with v1.6.1 Hybrid Motion
    files_to_clean = [
        os.path.join(ep_dir, "video.mp4"),
        os.path.join(output_dir, "daytime_in_the_bunker_1_1_en_0c1945fd.mp4"),
    ]
    cache_meta = os.path.join(ep_dir, ".cache", "stage_cache.json")
    if os.path.exists(cache_meta):
        files_to_clean.append(cache_meta)

    for fc in files_to_clean:
        if os.path.exists(fc):
            try:
                os.remove(fc)
                print(f"[CLEAN] Đã xóa cache cũ: {os.path.basename(fc)}")
            except Exception as e:
                print(f"[WARN] Không thể xóa {fc}: {e}")

    task_id = f"daytime-in-the-bunker-ep1-vi-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Daytime in the Bunker",
        comic_url=target_url,
        from_episode=1,
        to_episode=1,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": config.DEFAULT_VI_VOICE_ID,
            "ref_audio_path": config.DEFAULT_VI_REF_AUDIO,
            "bgm_genre": "drama",
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

    # Attach directory artifacts directly to use the specified folder
    task.artifacts["download_dir"] = target_dir
    task.artifacts["download_folder_name"] = os.path.basename(target_dir)
    task.artifacts["comic_title"] = "Daytime in the Bunker"

    ctx = ConsoleContext(task)

    # Pipeline stages to run for Vietnamese generation and video rendering
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
            print(f"[FATAL] {stage.name} thất bại.", flush=True)
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
    print("\n" + "=" * 75)
    print("  [SUCCESS] HOÀN TẤT TẠO VIDEO RECAP TIẾNG VIỆT CHO TẬP 1")
    print(f"  Final Video: {task.artifacts.get('final_video_url')}")
    print(f"  Thư mục kết quả: {output_dir}")
    print("=" * 75)
    return 0

exit_code = asyncio.run(main())
sys.exit(exit_code)

