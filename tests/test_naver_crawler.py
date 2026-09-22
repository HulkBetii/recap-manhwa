import asyncio
import os
import sys
import shutil

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import load_config, get_shared_browser_context, reset_shared_browser_context
from workflow import WorkflowTask, WorkflowContext, WorkflowManager, JSONWorkflowRepository, EventBus
from workflow_stages_1 import Stage1_ComicParsing, execute_single_episode_stage2

from workflow_base import CancellationToken

class MockManager:
    def __init__(self):
        self.events = []
        self.cancel_tokens = {}

    def get_cancel_token(self, task_id: str):
        if task_id not in self.cancel_tokens:
            self.cancel_tokens[task_id] = CancellationToken()
        return self.cancel_tokens[task_id]

    async def calculate_overall_progress(self, task):
        pass

    async def save_and_broadcast(self, event_name, task):
        self.events.append((event_name, task.id))

async def test_naver_crawling():
    print("=" * 60)
    print("🚀 BẮT ĐẦU KIỂM THỬ: Naver Webtoon Crawler Integration")
    print("=" * 60)
    
    test_url = "https://comic.naver.com/webtoon/list?titleId=814742"
    cfg = {"language": "vi", "headless": True, "concurrency": 3}
    task = WorkflowTask(
        comic_title="",
        comic_url=test_url,
        from_episode=1,
        to_episode=1,
        payload=cfg
    )
    
    manager = MockManager()
    context = WorkflowContext(task=task, config=cfg, manager=manager)
    
    # 1. Test Stage 1: Comic Parsing
    print(f"\n[1/3] Đang chạy Stage 1 - Comic Parsing cho URL: {test_url}...")
    stage1 = Stage1_ComicParsing()
    ok1 = await stage1.execute(context)
    
    assert ok1, "❌ Stage 1 Comic Parsing thất bại!"
    print(f"✅ Comic Title trích xuất được: {task.comic_title}")
    slugs = task.artifacts.get("chapter_slugs", [])
    print(f"✅ Tổng số tập phát hiện: {len(slugs)} tập (Mẫu: {slugs[:10]}...)")
    print(f"✅ Thư mục Download: {task.artifacts.get('download_dir')}")
    
    assert len(slugs) > 0, "❌ Không tìm thấy chapter nào!"
    assert task.comic_title, "❌ Tiêu đề truyện bị rỗng!"
    
    # 2. Test Stage 2: Single Episode Image Crawling (Ep 1)
    print(f"\n[2/3] Đang chạy Stage 2 - Tải ảnh tập 1...")
    browser, context_pw = await get_shared_browser_context(headless=True)
    from app import NavigationManager
    nav_manager = NavigationManager(context)
    nav_manager.context = context_pw
    nav_manager.browser = browser
    
    ok2 = await execute_single_episode_stage2(
        ep=1,
        context=context,
        context_pw=context_pw,
        nav_manager=nav_manager
    )
    
    assert ok2, "❌ Stage 2 Image Crawling tập 1 thất bại!"
    
    # 3. Test Verify Downloaded Images
    print(f"\n[3/3] Đang kiểm tra tính toàn vẹn của các file ảnh tập 1...")
    download_dir = task.artifacts.get("download_dir")
    ep1_images_dir = os.path.join(download_dir, "episode_1", "images")
    
    assert os.path.exists(ep1_images_dir), f"❌ Không tìm thấy thư mục ảnh: {ep1_images_dir}"
    
    image_files = [f for f in os.listdir(ep1_images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    print(f"✅ Tổng số ảnh đã tải về: {len(image_files)} ảnh")
    assert len(image_files) > 0, "❌ Thư mục ảnh rỗng, không có ảnh nào được tải!"
    
    from PIL import Image
    for idx, img_name in enumerate(sorted(image_files)):
        img_path = os.path.join(ep1_images_dir, img_name)
        size_bytes = os.path.getsize(img_path)
        assert size_bytes > 0, f"❌ File ảnh {img_name} bị 0 bytes!"
        
        # Verify valid image header
        with Image.open(img_path) as im:
            width, height = im.size
            assert width > 0 and height > 0, f"❌ Kích thước ảnh {img_name} không hợp lệ: {width}x{height}"
            if idx < 3 or idx == len(image_files) - 1:
                print(f"   🖼️ {img_name}: {size_bytes / 1024:.1f} KB, Kích thước {width}x{height}, Định dạng: {im.format}")

    print("\n" + "=" * 60)
    print("🎉 TẤT CẢ KIỂM THỬ CHO NAVER WEBTOON CRAWLER ĐÃ THÀNH CÔNG RỰC RỠ!")
    print("=" * 60)
    
    # Cleanup browser
    await reset_shared_browser_context()

if __name__ == "__main__":
    asyncio.run(test_naver_crawling())
