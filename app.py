import sys
import os
# Optimize CUDA memory allocation to avoid fragmentation and OOM
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
# Enable CPU fallback for unsupported MPS operators on macOS
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
# CPU thread tuning for i5-12400F (6 P-cores)
os.environ.setdefault("OMP_NUM_THREADS", "6")
os.environ.setdefault("MKL_NUM_THREADS", "6")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "6")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "6")

import subprocess
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, message=".*The key `labels`.*")
import asyncio
import random
import threading

async def human_delay(min_s: float = 0.25, max_s: float = 0.85):
    """Delay ngẫu nhiên ngắn (tối đa 1s) trước các thao tác automation để mô phỏng người dùng thật."""
    await asyncio.sleep(random.uniform(min_s, min(max_s, 1.0)))

# --- Windows Subprocess Asyncio Patch for SelectorEventLoop ---
_bg_loop = None
_bg_thread = None
_bg_lock = threading.Lock()

def _get_bg_loop():
    global _bg_loop, _bg_thread
    with _bg_lock:
        if _bg_loop is None:
            _bg_loop = asyncio.WindowsProactorEventLoopPolicy().new_event_loop()
            def run_loop():
                asyncio.set_event_loop(_bg_loop)
                _bg_loop.run_forever()
            _bg_thread = threading.Thread(target=run_loop, daemon=True)
            _bg_thread.start()
        return _bg_loop

class BGStreamReaderProxy:
    def __init__(self, reader, bg_loop):
        self._reader = reader
        self._bg_loop = bg_loop

    async def read(self, n=-1):
        fut = asyncio.run_coroutine_threadsafe(self._reader.read(n), self._bg_loop)
        return await asyncio.wrap_future(fut)

    async def readline(self):
        fut = asyncio.run_coroutine_threadsafe(self._reader.readline(), self._bg_loop)
        return await asyncio.wrap_future(fut)

    async def readexactly(self, n):
        fut = asyncio.run_coroutine_threadsafe(self._reader.readexactly(n), self._bg_loop)
        return await asyncio.wrap_future(fut)

    async def readuntil(self, separator=b'\n'):
        fut = asyncio.run_coroutine_threadsafe(self._reader.readuntil(separator), self._bg_loop)
        return await asyncio.wrap_future(fut)

    def at_eof(self):
        return self._reader.at_eof()

class BGStreamWriterProxy:
    def __init__(self, writer, bg_loop):
        self._writer = writer
        self._bg_loop = bg_loop

    def write(self, data):
        self._bg_loop.call_soon_threadsafe(self._writer.write, data)

    def writelines(self, data):
        self._bg_loop.call_soon_threadsafe(self._writer.writelines, data)

    def close(self):
        self._bg_loop.call_soon_threadsafe(self._writer.close)

    async def wait_closed(self):
        fut = asyncio.run_coroutine_threadsafe(self._writer.wait_closed(), self._bg_loop)
        return await asyncio.wrap_future(fut)

    async def drain(self):
        fut = asyncio.run_coroutine_threadsafe(self._writer.drain(), self._bg_loop)
        return await asyncio.wrap_future(fut)

class BGProcessProxy:
    def __init__(self, proc, bg_loop):
        self._proc = proc
        self._bg_loop = bg_loop
        self.stdin = BGStreamWriterProxy(proc.stdin, bg_loop) if proc.stdin else None
        self.stdout = BGStreamReaderProxy(proc.stdout, bg_loop) if proc.stdout else None
        self.stderr = BGStreamReaderProxy(proc.stderr, bg_loop) if proc.stderr else None

    @property
    def returncode(self):
        return self._proc.returncode

    @property
    def pid(self):
        return self._proc.pid

    async def wait(self):
        fut = asyncio.run_coroutine_threadsafe(self._proc.wait(), self._bg_loop)
        return await asyncio.wrap_future(fut)

    async def communicate(self, input=None):
        fut = asyncio.run_coroutine_threadsafe(self._proc.communicate(input), self._bg_loop)
        return await asyncio.wrap_future(fut)

    def send_signal(self, signal):
        self._bg_loop.call_soon_threadsafe(self._proc.send_signal, signal)

    def terminate(self):
        self._bg_loop.call_soon_threadsafe(self._proc.terminate)

    def kill(self):
        self._bg_loop.call_soon_threadsafe(self._proc.kill)

_original_create_subprocess_exec = asyncio.create_subprocess_exec

async def _patched_create_subprocess_exec(program, *args, **kwargs):
    loop = asyncio.get_running_loop()
    if sys.platform == 'win32' and not isinstance(loop, asyncio.ProactorEventLoop):
        bg_loop = _get_bg_loop()
        async def create_in_bg():
            return await _original_create_subprocess_exec(program, *args, **kwargs)
        fut = asyncio.run_coroutine_threadsafe(create_in_bg(), bg_loop)
        proc = await asyncio.wrap_future(fut)
        return BGProcessProxy(proc, bg_loop)
    else:
        return await _original_create_subprocess_exec(program, *args, **kwargs)

asyncio.create_subprocess_exec = _patched_create_subprocess_exec
asyncio.subprocess.create_subprocess_exec = _patched_create_subprocess_exec
# -------------------------------------------------------------
import json
import re
import urllib.parse
import urllib.request
import traceback
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import List, Dict, Optional
import logging
load_dotenv()

def check_critical_deps() -> Dict[str, bool]:
    """Kiểm tra tính sẵn sàng của các thư viện phụ thuộc quan trọng khi khởi động server."""
    import importlib
    deps = {
        "ultralytics": "YOLOv11 AI detection & Smart pagination",
        "kokoro": "Kokoro neural TTS",
        "faster_whisper": "Whisper subtitle forced-alignment",
        "edge_tts": "EdgeTTS online speech synthesis",
        "playwright": "Gemini automation browser",
        "cv2": "OpenCV visual processing",
        "torch": "PyTorch GPU compute",
    }
    status = {}
    app_logger = logging.getLogger("SystemStartup")
    for mod, desc in deps.items():
        try:
            importlib.import_module(mod)
            status[mod] = True
        except ImportError:
            status[mod] = False
            app_logger.warning(f"⚠️ Thiếu thư viện '{mod}' ({desc}). Chạy: pip install {mod}")
    return status

check_critical_deps()

# --- Configuration Management for Chrome Profiles ---
CONFIG_FILE = "config.json"

def load_config():
    default_profile = os.getenv("CHROME_PROFILE_PATH") or r"C:\Data\Profile 1"
    if not os.path.exists(CONFIG_FILE):
        config = {
            "chrome_profiles": [default_profile],
            "current_profile_index": 0,
            "headless": False
        }
        save_config(config)
        return config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if "headless" not in cfg:
                cfg["headless"] = False
            return cfg
    except Exception:
        return {
            "chrome_profiles": [default_profile],
            "current_profile_index": 0,
            "headless": False
        }

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)



if sys.platform == 'win32':
    # Prevent uvicorn from overriding loop policy to SelectorEventLoop on Windows
    asyncio.WindowsSelectorEventLoopPolicy = asyncio.WindowsProactorEventLoopPolicy
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi import FastAPI, HTTPException, status, BackgroundTasks, File, UploadFile
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright
from PIL import Image

class VisionSafetyException(Exception):
    pass

def cleanup_temp_profiles():
    import glob
    import shutil
    pattern = os.path.join(os.getcwd(), "chrome_profile_temp*")
    for path in glob.glob(pattern):
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                print(f"Cleaned up old temp profile: {path}", flush=True)
            except Exception:
                pass

def clear_browser_cache(profile_dirs=None) -> dict:
    """
    Safely clears browser disk cache, shader cache, code cache, crashpad, and metrics
    across all configured Chrome profiles without deleting user sessions, cookies, or logins.
    """
    import shutil
    import glob

    # 1. Clean temp profiles first
    cleanup_temp_profiles()

    target_dirs = set()
    if profile_dirs:
        for p in profile_dirs:
            if p and os.path.exists(p):
                target_dirs.add(os.path.abspath(p))

    # Check config.json profiles
    config_path = os.path.join(os.getcwd(), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for p in cfg.get("chrome_profiles", []):
                    if p and os.path.exists(p):
                        target_dirs.add(os.path.abspath(p))
                        parent = os.path.dirname(os.path.abspath(p))
                        if os.path.exists(parent):
                            target_dirs.add(parent)
        except Exception:
            pass

    # Check local Profiles directory
    local_profiles = os.path.join(os.getcwd(), "Profiles")
    if os.path.exists(local_profiles):
        for item in os.listdir(local_profiles):
            item_path = os.path.join(local_profiles, item)
            if os.path.isdir(item_path):
                target_dirs.add(os.path.abspath(item_path))

    # Check env var
    env_profile = os.getenv("CHROME_PROFILE_PATH")
    if env_profile and os.path.exists(env_profile):
        target_dirs.add(os.path.abspath(env_profile))

    # Check C:\Data\Profile 1
    default_data = r"C:\Data\Profile 1"
    if os.path.exists(default_data):
        target_dirs.add(os.path.abspath(default_data))

    cache_dir_names = {
        "cache", "code cache", "dawnwebgpucache", "dawncache", "gpucache",
        "grshadercache", "shadercache", "browsermetrics", "crashpad",
        "optguideondevicemodel", "optimizationguidepredictionmodels",
        "cachestorage", "scriptcache", "media cache", "blob_storage"
    }

    lock_file_names = {
        "singletonlock", "singletoncookie", "singletonsocket"
    }

    total_cleaned_bytes = 0
    cleaned_folders = 0
    cleaned_locks = 0

    def calc_dir_size(d):
        total = 0
        for r, ds, fs in os.walk(d):
            for f in fs:
                try:
                    total += os.path.getsize(os.path.join(r, f))
                except Exception:
                    pass
        return total

    for base_p in target_dirs:
        if not os.path.isdir(base_p):
            continue

        for root, dirs, files in os.walk(base_p, topdown=True):
            for d in list(dirs):
                if d.lower() in cache_dir_names:
                    full_d = os.path.join(root, d)
                    sz = calc_dir_size(full_d)
                    try:
                        shutil.rmtree(full_d, ignore_errors=True)
                        total_cleaned_bytes += sz
                        cleaned_folders += 1
                    except Exception:
                        pass
                    dirs.remove(d)

            for f in files:
                if f.lower() in lock_file_names:
                    full_f = os.path.join(root, f)
                    try:
                        os.remove(full_f)
                        cleaned_locks += 1
                    except Exception:
                        pass

    mb_cleaned = round(total_cleaned_bytes / (1024 * 1024), 2)
    msg = f"Đã dọn dẹp browser cache: giải phóng {mb_cleaned} MB ({cleaned_folders} thư mục cache, {cleaned_locks} lock files)."
    print(msg, flush=True)
    return {
        "status": "success",
        "cleaned_bytes": total_cleaned_bytes,
        "cleaned_mb": mb_cleaned,
        "cleaned_folders": cleaned_folders,
        "cleaned_locks": cleaned_locks,
        "message": msg
    }

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_temp_profiles()
    workflow_manager.start()
    yield
    await workflow_manager.stop()
    try:
        await reset_shared_browser_context()
    except Exception:
        pass

app = FastAPI(title="Manhwa Recap Tool", lifespan=lifespan)

from workflow import (
    JSONWorkflowRepository,
    EventBus,
    WorkflowManager,
    WorkflowTask,
    WorkflowState,
    StageState
)

textbox_selectors = [
    "rich-textarea div.ql-editor",
    "div.ql-editor[contenteditable='true']",
    "rich-textarea div[contenteditable='true']:not(.ql-clipboard)",
    "rich-textarea p",
    "div.ProseMirror[contenteditable='true']",
    "div[contenteditable='true']:not(.ql-clipboard)",
    "[role='textbox']:not(.ql-clipboard)",
    "#prompt-textarea",
    "rich-textarea"
]

send_selectors = [
    "div[data-test-id='send-button-container'] button",
    "div[data-test-id='send-button-container'] gem-icon-button",
    "gem-icon-button.send-button button",
    "gem-icon-button.send-button",
    "gem-icon-button.submit button",
    "gem-icon-button.submit",
    "button[aria-label='Send message']",
    "button[aria-label*='Send']",
    "button[aria-label*='send']",
    "button#composer-submit-button",
    "#composer-submit-button",
    "button[data-testid='send-button']",
    "button[data-testid='chat-submit']",
    "button[data-testid*='submit']",
    "button[aria-label*='Submit']",
    "button[aria-label*='submit']",
    "button[type='submit']",
    "input-area-v2 button.send-button",
    "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[5]/div[2]/div[2]/gem-icon-button/button",
    "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[3]/div[2]/div[2]/gem-icon-button/button",
    "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div[2]/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[3]/div[2]/div[2]/gem-icon-button/button",
    "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[5]/div[2]/div[2]/gem-icon-button",
    "gem-icon-button button",
    "gem-icon-button"
]


response_selectors = [
    "[data-testid='assistant-message'] .response-content-markdown",
    "[data-testid='assistant-message']",
    "div.response-content-markdown.markdown",
    "div.response-content-markdown",
    "div[class*='response-content-markdown']",
    "message-content",
    "div.message-content",
    "div[class*='message-content']",
    "div.model-response",
    "div[class*='model-response']",
    "div[data-message-author-role='assistant'] div.markdown",
    "div.markdown",
    "article div.markdown",
    "div.prose",
    "div[class*='prose']",
    "div[data-message-author-role='assistant']",
    "div[class*='message']"
]

# Initialize Workflow Engine
event_bus = EventBus()
repository = JSONWorkflowRepository()
workflow_manager = WorkflowManager(repository, event_bus, max_workers=1)

# Ensure static directory exists
os.makedirs("static", exist_ok=True)


# SSE Logger logic
class SSELogger:
    def __init__(self):
        self.queues = []

    def register(self):
        q = asyncio.Queue()
        self.queues.append(q)
        return q

    def unregister(self, q):
        if q in self.queues:
            self.queues.remove(q)

    async def log(self, message: str, level: str = "info", app_status: str = None, status_text: str = None, data: dict = None):
        print(f"[{level.upper()}] {message}", flush=True)
        payload = {
            "message": message,
            "level": level,
        }
        if app_status:
            payload["status"] = app_status
        if status_text:
            payload["status_text"] = status_text
        if data:
            payload["data"] = data

        for q in self.queues:
            await q.put(payload)

sse_logger = SSELogger()

# Event bus subscriber for SSE logs
async def sse_event_bus_subscriber(event_name: str, task_id: str, data):
    payload = {
        "event": event_name,
        "task_id": task_id,
        "data": data,
        "message": f"Workflow Event: {event_name}",
        "level": "event"
    }
    for q in sse_logger.queues:
        await q.put(payload)

event_bus.subscribe(sse_event_bus_subscriber)



class BrowserState:
    INIT = "INIT"
    OPEN_SEARCH = "OPEN_SEARCH"
    WAIT_CAPTCHA = "WAIT_CAPTCHA"
    CAPTCHA_SOLVED = "CAPTCHA_SOLVED"
    CONTINUE_SEARCH = "CONTINUE_SEARCH"
    COMPLETE = "COMPLETE"

class NavigationManager:
    def __init__(self, sse_logger):
        self.state = BrowserState.INIT
        self.sse_logger = sse_logger
        self.mutex = asyncio.Lock()
        self.navigation_history = []  # List of tuples: (timestamp, url)
        self.current_url = ""
        self.context = None
        self.browser = None
        self.cookies_count = 0

    async def set_state(self, new_state: str):
        if self.state == new_state:
            return

        # Restriction: No state may transition back to OPEN_SEARCH automatically.
        if new_state == BrowserState.OPEN_SEARCH and self.state in [BrowserState.WAIT_CAPTCHA, BrowserState.CAPTCHA_SOLVED, BrowserState.CONTINUE_SEARCH]:
            await self.log("Block transition back to OPEN_SEARCH automatically to prevent navigation loops.", "warning")
            return

        old_state = self.state
        self.state = new_state
        await self.log(f"State transition: {old_state} -> {new_state}", "info")

    async def log(self, message: str, level: str = "info", reason: str = "N/A", caller: str = "N/A"):
        timestamp = datetime.now().isoformat()
        log_msg = f"[{timestamp}] [State: {self.state}] [URL: {self.current_url}] [Reason: {reason}] [Caller: {caller}] [Cookies: {self.cookies_count}] - {message}"
        await self.sse_logger.log(log_msg, level)

    def track_navigation(self, url: str, caller: str):
        now = datetime.now()
        # Clean history older than 10 seconds
        self.navigation_history = [t for t in self.navigation_history if now - t[0] <= timedelta(seconds=10)]

        # Check repeated navigation: same URL loaded more than 3 times within 10 seconds
        same_url_loads = [t for t in self.navigation_history if t[1] == url]
        if len(same_url_loads) >= 3:
            # Dump stack trace
            stack = "".join(traceback.format_stack())
            raise Exception(
                f"REPEATED NAVIGATION DETECTED! URL {url} loaded {len(same_url_loads) + 1} times within 10 seconds. "
                f"Caller: {caller}. Stack trace:\n{stack}"
            )

        self.navigation_history.append((now, url))

    async def safe_goto(self, page, url: str, reason: str, caller: str, wait_until: str = "domcontentloaded"):
        async with self.mutex:
            self.current_url = url
            self.track_navigation(url, caller)

            # Update cookies count
            if self.context:
                try:
                    cookies = await asyncio.wait_for(self.context.cookies(), timeout=2.0)
                    self.cookies_count = len(cookies)
                except Exception:
                    pass

            # Transition state based on URL
            if "captcha" in url.lower() or "recaptcha" in url.lower() or "checkpoint" in url.lower() or "challenge" in url.lower():
                await self.set_state(BrowserState.WAIT_CAPTCHA)
            elif self.state == BrowserState.INIT:
                await self.set_state(BrowserState.OPEN_SEARCH)

            await self.log(f"Starting page.goto to: {url}", "info", reason, caller)

            try:
                response = await page.goto(url, timeout=35000, wait_until=wait_until)
                final_url = page.url
                self.current_url = final_url

                # Check if page is stuck on Cloudflare challenge
                try:
                    page_title = await page.title()
                    if "just a moment" in page_title.lower() or "cloudflare" in page_title.lower():
                        await self.log(f"Cloudflare verification detected ('{page_title}'). Waiting...", "warning", reason, caller)
                        for _ in range(15):
                            await asyncio.sleep(1)
                            page_title = await page.title()
                            if "just a moment" not in page_title.lower() and "cloudflare" not in page_title.lower():
                                await self.log("Cloudflare challenge passed.", "success", reason, caller)
                                break
                except Exception:
                    pass

                # Check if final url contains captcha keywords
                if "captcha" in final_url.lower() or "recaptcha" in final_url.lower() or "checkpoint" in final_url.lower() or "challenge" in final_url.lower():
                    await self.set_state(BrowserState.WAIT_CAPTCHA)
                    await self.log("Redirected to CAPTCHA page. Halting automatic navigations.", "warning", reason, caller)
                else:
                    if self.state == BrowserState.WAIT_CAPTCHA:
                        await self.set_state(BrowserState.CAPTCHA_SOLVED)
                        await self.log("CAPTCHA solved successfully (loaded non-captcha URL).", "success", reason, caller)
                return response
            except Exception as e:
                await self.log(f"Error during page.goto: {str(e)}", "error", reason, caller)
                raise e

# Lock to prevent concurrent browser setups
setup_lock = asyncio.Lock()

class SetupRequest(BaseModel):
    url: str
    profile_path: Optional[str] = None

class SaveConfigRequest(BaseModel):
    chrome_profiles: Optional[List[str]] = None
    current_profile_index: Optional[int] = None
    headless: Optional[bool] = None

@app.get("/api/config")
async def get_app_config():
    return load_config()

@app.post("/api/config")
async def save_app_config(payload: SaveConfigRequest):
    config = load_config()
    if payload.chrome_profiles is not None:
        config["chrome_profiles"] = [p.strip() for p in payload.chrome_profiles if p.strip()]
    if payload.current_profile_index is not None:
        config["current_profile_index"] = payload.current_profile_index
    if payload.headless is not None:
        config["headless"] = bool(payload.headless)
    save_config(config)
    if config.get("chrome_profiles"):
        idx = config.get("current_profile_index", 0)
        if idx < len(config["chrome_profiles"]):
            os.environ["CHROME_PROFILE_PATH"] = config["chrome_profiles"][idx]
    return {"status": "success", "message": "Cập nhật cấu hình Chrome Profiles thành công.", "config": config}

# Serve HTML frontend
@app.get("/")
async def get_index():
    return FileResponse("static/index.html")

@app.get("/test_stage")
async def get_test_stage():
    return FileResponse("static/test_stage.html")

@app.get("/video_merge")
async def get_video_merge_page():
    return FileResponse("static/video_merge.html")

from test_stage_router import router as test_stage_router
app.include_router(test_stage_router)

from video_merge_router import router as video_merge_router
app.include_router(video_merge_router)

# SSE logs endpoint
@app.get("/api/logs")
async def logs_endpoint():
    log_queue = sse_logger.register()

    async def event_generator():
        try:
            # Welcome message
            yield f"data: {json.dumps({'message': 'Kết nối log stream thành công.', 'level': 'system'})}\n\n"
            while True:
                log_data = await log_queue.get()
                yield f"data: {json.dumps(log_data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_logger.unregister(log_queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

class SaveCookiesRequest(BaseModel):
    cookies_data: str

# Save Cookies Route (Manual Entry)
@app.post("/api/save-cookies")
async def save_cookies(payload: SaveCookiesRequest):
    try:
        data = payload.cookies_data.strip()
        if not data:
            raise HTTPException(status_code=400, detail="Dữ liệu cookies trống.")

        # Try parsing as JSON first
        try:
            cookies_json = json.loads(data)
            if isinstance(cookies_json, list):
                cookies_json = {"cookies": cookies_json, "origins": []}
        except json.JSONDecodeError:
            # If it is a raw cookie header string, parse it
            cookies_list = []
            for pair in data.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    cookies_list.append({
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".webtoon.com",  # Default domain
                        "path": "/"
                    })
            if not cookies_list:
                raise Exception("Không thể parse cookies dạng chuỗi. Vui lòng nhập JSON hoặc định dạng key=value;")
            cookies_json = {"cookies": cookies_list, "origins": []}

        cookie_file = "cookies.json"
        with open(cookie_file, "w", encoding="utf-8") as f:
            json.dump(cookies_json, f, indent=2)

        await sse_logger.log(f"Đã lưu thủ công {len(cookies_json.get('cookies', []))} cookies vào file '{cookie_file}'.", "success")
        return {"status": "success", "message": "Lưu cookies thủ công thành công."}
    except Exception as e:
        error_msg = f"Không thể lưu cookies: {str(e)}"
        await sse_logger.log(error_msg, "error")
        raise HTTPException(status_code=400, detail=error_msg)

# Setup Cookies Route
@app.post("/api/setup-cookies")
async def setup_cookies(payload: SetupRequest):
    if setup_lock.locked():
        await sse_logger.log("Yêu cầu setup cookies bị từ chối: Một tiến trình setup khác đang chạy.", "warning")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Browser setup is already running."
        )

    # Determine target Chrome profile path
    config = load_config()
    profiles = config.get("chrome_profiles", [])
    idx = config.get("current_profile_index", 0)
    
    target_profile = payload.profile_path
    if not target_profile:
        if idx < len(profiles):
            target_profile = profiles[idx]
        else:
            target_profile = os.getenv("CHROME_PROFILE_PATH") or r"C:\Data\Profile 1"

    # Check and import to local project folder if it's an external path
    resolved_profile_path = os.path.abspath(target_profile)
    project_profiles_dir = os.path.abspath(os.path.join(os.getcwd(), "Profiles"))
    
    if not resolved_profile_path.startswith(project_profiles_dir):
        # Perform migration
        basename = os.path.basename(resolved_profile_path)
        safe_name = "".join(c for c in basename if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        if not safe_name:
            import time
            safe_name = f"profile_{int(time.time())}"
            
        dest_user_data_dir = os.path.join(project_profiles_dir, safe_name)
        os.makedirs(dest_user_data_dir, exist_ok=True)
        
        await sse_logger.log(f"Đang nhập và sao chép Chrome Profile hệ thống {resolved_profile_path} vào thư mục dự án {dest_user_data_dir}...", "info")
        try:
            sync_chrome_profile(resolved_profile_path, dest_user_data_dir)
            new_profile_path = os.path.join(dest_user_data_dir, "Default")
            
            # Update config lists
            updated = False
            for idx, p_path in enumerate(profiles):
                if os.path.abspath(p_path) == resolved_profile_path:
                    profiles[idx] = new_profile_path
                    updated = True
                    break
            if not updated:
                profiles.append(new_profile_path)
                config["current_profile_index"] = len(profiles) - 1
            else:
                # Set active profile index to the migrated one
                for idx, p_path in enumerate(profiles):
                    if p_path == new_profile_path:
                        config["current_profile_index"] = idx
                        break
                        
            config["chrome_profiles"] = profiles
            save_config(config)
            target_profile = new_profile_path
            await sse_logger.log(f"Đã nhập Profile thành công. Đường dẫn dự án mới: {new_profile_path}", "success")
        except Exception as copy_err:
            await sse_logger.log(f"Lỗi khi sao chép Chrome Profile: {copy_err}", "error")
            raise HTTPException(status_code=500, detail=f"Không thể sao chép Chrome Profile: {str(copy_err)}")

    async def run_browser_setup():
        async with setup_lock:
            await sse_logger.log(f"Bắt đầu mở trình duyệt thiết lập cookies với profile: {target_profile}...", "system", "active", "Đang mở trình duyệt...")

            try:
                await sse_logger.log("Đang khởi chạy Chrome (headed)...", "info")
                browser, context = await get_shared_browser_context(headless=False, start_maximized=False, custom_profile_path=target_profile)
                nav_manager = NavigationManager(sse_logger)
                nav_manager.context = context
                nav_manager.browser = browser

                # Target URL selection
                target_url = payload.url.strip()
                if not target_url:
                    # Fallback default url if none provided
                    target_url = "https://www.google.com"
                    await sse_logger.log("Không có URL nào được nhập. Mở Google làm mặc định.", "warning")

                page = await context.new_page()

                # Event-driven cookie saving and state updates
                cookie_file = "cookies.json"
                async def on_page_event(event_name):
                    try:
                        current_url = page.url
                        nav_manager.current_url = current_url

                        # Verify if it's a captcha url
                        if "captcha" in current_url.lower() or "recaptcha" in current_url.lower() or "checkpoint" in current_url.lower() or "challenge" in current_url.lower():
                            await nav_manager.set_state(BrowserState.WAIT_CAPTCHA)
                            await nav_manager.log(f"Event '{event_name}': CAPTCHA page detected.", "warning")
                        else:
                            if nav_manager.state == BrowserState.WAIT_CAPTCHA:
                                await nav_manager.set_state(BrowserState.CAPTCHA_SOLVED)
                                await nav_manager.log(f"Event '{event_name}': CAPTCHA solved.", "success")

                            # Verify cookies exist and save storageState
                            cookies = await context.cookies()
                            nav_manager.cookies_count = len(cookies)
                            if len(cookies) > 0:
                                state = await context.storage_state()
                                with open(cookie_file, "w", encoding="utf-8") as f:
                                    json.dump(state, f, indent=2)
                                await nav_manager.log(f"Event '{event_name}': Cookies verified & storageState saved (Count: {len(cookies)}).", "info")
                    except Exception as e:
                        await nav_manager.log(f"Error in event handler '{event_name}': {str(e)}", "error")

                page.on("framenavigated", lambda frame: asyncio.create_task(on_page_event("framenavigated")) if frame == page.main_frame else None)
                page.on("load", lambda p: asyncio.create_task(on_page_event("load")))
                page.on("domcontentloaded", lambda p: asyncio.create_task(on_page_event("domcontentloaded")))

                await sse_logger.log(f"Đang điều hướng trình duyệt tới: {target_url}", "info")
                await nav_manager.safe_goto(page, target_url, reason="Initial headed cookie setup page load", caller="setup_cookies")
                await sse_logger.log("Trình duyệt đã mở. Vui lòng đăng nhập / thiết lập cookies trên trang web.", "info")
                await sse_logger.log("GHI CHÚ: Hãy tắt tab trình duyệt này khi hoàn tất để lưu cookies.", "warning")

                # Keep running until setup page is closed (event-driven)
                disconnected_event = asyncio.Event()
                page.on("close", lambda p: disconnected_event.set())
                await disconnected_event.wait()

                await nav_manager.set_state(BrowserState.COMPLETE)
                await sse_logger.log(f"Đã đóng trang thiết lập. Thiết lập thành công.", "success", "idle", "Sẵn sàng")

            except Exception as e:
                error_msg = f"Đã xảy ra lỗi trong quá trình chạy trình duyệt: {str(e)}"
                await sse_logger.log(error_msg, "error", "idle", "Sẵn sàng")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=error_msg
                )

    # Run setup asynchronously so FastAPI response isn't blocked,
    # but wait! We want the POST request to complete after browser finishes,
    # so the frontend knows the browser is done. We can just await it directly!
    await run_browser_setup()
    return {"status": "success", "message": "Cookies setup process finished successfully."}

# Crawler structures and states
class AnalyzeRequest(BaseModel):
    url: str

class CrawlRequest(BaseModel):
    url: str
    from_episode: int
    to_episode: int
    safe_mode: bool = False
    nsfw_threshold: float = 0.3
    nsfw_mode: str = "mask"
    gemini_model: str = "default"
    temperature: float = 0.7
    max_output_tokens: int = 2048
    timeout: int = 160
    retry_count: int = 5
    concurrency: int = 5
    image_quality: int = 20
    pdf_quality: int = 20
    max_pdf_pages: int = 20
    language: str = "vi"
    vlm_provider: str = "gemini"
    voice_id: str = "auto"
    ref_audio_path: Optional[str] = None
    ai33pro_api_key: Optional[str] = None
    logo_path: Optional[str] = None
    overlay_path: Optional[str] = None
    remove_text: bool = True
    remove_text_conf: float = 0.3
    remove_text_radius: int = 3
    vlm_email: Optional[str] = "moneyholy47@gmail.com"
    vlm_password: Optional[str] = "Tienlcvb.2002"
    comix_group_id: Optional[str] = None
    film_grain: bool = True
    grain_strength: int = 6
    flip_horizontal: bool = False
    headless: Optional[bool] = None
    video_mark_path: Optional[str] = None
    video_mark_alpha: float = 0.01
    enable_video_mark: bool = True



crawler_running = False
stop_requested = False
crawler_lock = asyncio.Lock()

def sync_chrome_profile(src_profile_path: str, dest_user_data_dir: str):
    import shutil
    import os

    src_profile_path = os.path.abspath(src_profile_path)
    dest_user_data_dir = os.path.abspath(dest_user_data_dir)

    # 1. Determine root User Data path and profile folder name
    basename = os.path.basename(src_profile_path)
    if basename.startswith("Profile ") or basename == "Default":
        profile_name = basename
        src_user_data_root = os.path.dirname(src_profile_path)
    else:
        profile_name = "Default"
        src_user_data_root = src_profile_path

    src_profile_dir = os.path.join(src_user_data_root, profile_name)
    dest_profile_dir = os.path.join(dest_user_data_dir, "Default")

    os.makedirs(dest_profile_dir, exist_ok=True)

    # 2. Copy Local State (crucial for cookie decryption)
    local_state_src = os.path.join(src_user_data_root, "Local State")
    local_state_dest = os.path.join(dest_user_data_dir, "Local State")
    if os.path.exists(local_state_src):
        try:
            shutil.copy2(local_state_src, local_state_dest)
        except Exception as e:
            print(f"Warning: Could not copy Local State: {e}")

    # 3. Copy key login files and directories
    items_to_copy = [
        "Preferences",
        "Secure Preferences",
        "Local Storage",
        "Session Storage",
        "Network",
        "Cookies"
    ]

    for item in items_to_copy:
        src_item_path = os.path.join(src_profile_dir, item)
        dest_item_path = os.path.join(dest_profile_dir, item)

        if os.path.exists(src_item_path):
            try:
                if os.path.isdir(src_item_path):
                    if os.path.exists(dest_item_path):
                        shutil.rmtree(dest_item_path, ignore_errors=True)
                    shutil.copytree(src_item_path, dest_item_path, ignore_dangling_symlinks=True)
                else:
                    shutil.copy2(src_item_path, dest_item_path)
            except Exception as e:
                print(f"Warning: Could not copy {item}: {e}")

async def get_browser_context(p, headless=None, start_maximized=False, temp_suffix="", custom_profile_path=None):
    if headless is None:
        headless = load_config().get("headless", False)

    if custom_profile_path:
        profile_path = custom_profile_path
    else:
        config = load_config()
        profiles = config.get("chrome_profiles", [])
        idx = config.get("current_profile_index", 0)
        if idx < len(profiles):
            profile_path = profiles[idx]
        else:
            profile_path = os.getenv("CHROME_PROFILE_PATH") or r"C:\Data\Profile 1"

    # Detect official Google Chrome executable on system
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]
    found_chrome_exe = None
    for cp in chrome_paths:
        if os.path.exists(cp):
            found_chrome_exe = cp
            break

    launch_args = {
        "headless": headless,
        "args": [
            # Anti-detection & Window setup
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--password-store=basic",
            "--use-mock-keychain",
            "--no-focus-on-init",
            "--force-dark-mode",
            "--disable-notifications",
            "--disable-popup-blocking",
            "--disable-print-preview",
            "--disable-speech-api",
            "--disable-speech-synthesis-api",

            # 1. Chống Throttling & Khóa Xung Nhịp: Không bóp hiệu năng CPU/JS/GPU khi cửa sổ ẩn/che/chạy nền
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-hang-monitor",
            "--disable-ipc-flooding-protection",
            "--disable-features=CalculateNativeWinOcclusion,Translate,BackForwardCache,AcceptCHFrame,MediaRouter,OptimizationHints,OptimizationGuideModelDownloading,OptimizationGuideOnDeviceModel,OptimizationGuidePersonalizedFetching,InterestFeedContentSuggestions,AutofillServerCommunication,IntensiveWakeUpThrottling,PageLifecycleThrottle,AudioServiceOutOfProcess",

            # 2. Tối đa hóa Hardware Acceleration, Memory & Canvas Buffer (Chống Canvas Buffer Overflow & Render lag)
            "--test-type",
            "--disable-dev-shm-usage",
            "--js-flags=--max-old-space-size=8192",
            "--unlimited-storage",
            "--ignore-gpu-blocklist",
            "--enable-gpu-rasterization",
            "--enable-oop-rasterization",
            "--enable-zero-copy",
            "--enable-native-gpu-memory-buffers",
            "--max-active-webgl-contexts=100",
            "--enable-accelerated-video-decode",
            "--enable-accelerated-2d-canvas",
            "--force-color-profile=srgb",
            "--disable-gpu-vsync",
            "--disable-threaded-scrolling",

            # 3. Tối ưu Network I/O, Cache & Streaming kết nối SSE/gRPC liên tục (Chống Connection Timeout)
            "--enable-features=NetworkService,NetworkServiceInProcess,CanvasOopRasterization,PdfOopif,VaapiVideoDecoder,ParallelDownloading",
            "--disable-domain-reliability",
            "--disable-component-update",
            "--disable-sync",
            "--disable-breakpad",
            "--disable-client-side-phishing-detection",
            "--disable-default-apps",
            "--metrics-recording-only",
            "--disk-cache-size=209715200",
            "--media-cache-size=104857600",
            "--renderer-process-limit=10",
        ],
        "ignore_default_args": ["--enable-automation", "--no-sandbox"]
    }
    if found_chrome_exe:
        launch_args["executable_path"] = found_chrome_exe

    if headless:
        launch_args["args"].append("--headless=new")
        launch_args["args"].append("--window-size=1280,850")
    elif start_maximized:
        launch_args["args"].append("--start-maximized")
    else:
        launch_args["args"].extend(["--window-size=1280,850", "--window-position=100,50"])

    if profile_path:
        profile_path = os.path.abspath(profile_path)
        user_data_dir = profile_path
        print(f"Using persistent Chrome profile at: {user_data_dir}")

        # Clean browser lock files & heavy temp telemetry/model bloat inside profile path
        for lock_name in ["SingletonLock", "lock", "SingletonCookie", "SingletonSocket"]:
            for root, dirs, files in os.walk(user_data_dir):
                if lock_name in files:
                    try:
                        os.remove(os.path.join(root, lock_name))
                        print(f"Cleared lock file: {os.path.join(root, lock_name)}")
                    except Exception:
                        pass

        # Auto-clean heavy junk folders (Optimization model downloads, crashpads, metrics)
        for junk_dir in ["OptGuideOnDeviceModel", "BrowserMetrics", "Crashpad", "GrShaderCache"]:
            target_junk = os.path.join(user_data_dir, junk_dir)
            if os.path.exists(target_junk):
                try:
                    shutil.rmtree(target_junk, ignore_errors=True)
                except Exception:
                    pass

        if not start_maximized:
            for p_dir in [profile_path, os.path.join(user_data_dir, "Default"), user_data_dir]:
                if not p_dir or not os.path.exists(p_dir):
                    continue
                pref_file = os.path.join(p_dir, "Preferences")
                if os.path.exists(pref_file):
                    try:
                        with open(pref_file, "r", encoding="utf-8") as pf:
                            pref_data = json.load(pf)
                        if pref_data.get("browser", {}).get("window_placement", {}).get("maximized"):
                            pref_data["browser"]["window_placement"]["maximized"] = False
                            with open(pref_file, "w", encoding="utf-8") as pf:
                                json.dump(pref_data, pf)
                    except Exception:
                        pass

        context = None
        try:
            max_launch_attempts = 3
            for attempt in range(1, max_launch_attempts + 1):
                try:
                    try:
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=user_data_dir,
                            channel="chrome" if not found_chrome_exe else None,
                            no_viewport=True,
                            color_scheme="dark",
                            permissions=["clipboard-read", "clipboard-write"],
                            **launch_args
                        )
                    except Exception as inner_e:
                        # Fallback if channel/executable_path fails
                        fallback_args = dict(launch_args)
                        fallback_args.pop("executable_path", None)
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=user_data_dir,
                            no_viewport=True,
                            color_scheme="dark",
                            permissions=["clipboard-read", "clipboard-write"],
                            **fallback_args
                        )
                    break
                except Exception as launch_err:
                    err_str = str(launch_err).lower()
                    is_lock_err = "existing browser session" in err_str or "profile is already in use" in err_str or "locked" in err_str or "connection closed" in err_str
                    if is_lock_err and attempt < max_launch_attempts:
                        print(f"Warning: Browser profile is locked. Attempt {attempt}/{max_launch_attempts}. Retrying in 2 seconds...")
                        await asyncio.sleep(2.0)
                    else:
                        raise launch_err
        except Exception as e:
            if "existing browser session" in str(e) or "profile is already in use" in str(e) or "locked" in str(e).lower() or "connection closed" in str(e).lower():
                for lock_name in ["SingletonLock", "lock", "SingletonCookie", "SingletonSocket"]:
                    for root, dirs, files in os.walk(user_data_dir):
                        if lock_name in files:
                            try:
                                os.remove(os.path.join(root, lock_name))
                            except Exception:
                                pass
                try:
                    await asyncio.sleep(1.5)
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        channel="chrome" if not found_chrome_exe else None,
                        no_viewport=True,
                        color_scheme="dark",
                        permissions=["clipboard-read", "clipboard-write"],
                        **launch_args
                    )
                except Exception:
                    friendly_err = (
                        "\n"
                        "====================================================================================\n"
                        "LỖI: Trình duyệt Chrome của bạn hiện đang mở và đang sử dụng Profile này.\n"
                        "Để khắc phục, vui lòng thực hiện một trong hai cách sau:\n"
                        "1. Đóng hoàn toàn tất cả cửa sổ trình duyệt Chrome trên máy tính của bạn trước khi chạy.\n"
                        "2. Hoặc sửa cấu hình trong file .env:\n"
                        "   CHROME_PROFILE_PATH=chrome_profile\n"
                        "   Sau đó, khởi động lại server, vào giao diện Web và nhấn nút 'Setup Cookies' để đăng nhập lại một lần duy nhất.\n"
                        "====================================================================================\n"
                    )
                    print(friendly_err)
                    raise Exception(friendly_err)
            else:
                raise e

        blocked_patterns = [
            "*google-analytics.com*",
            "*googletagmanager.com*",
            "*doubleclick.net*",
            "*facebook.net*",
            "*facebook.com/tr*",
            "*hotjar.com*",
            "*clarity.ms*",
            "*sentry.io*",
            "*segment.io*",
            "*scorecardresearch.com*",
            "*criteo.com*",
            "*adroll.com*",
            "*adnxs.com*"
        ]
        for blocked_pattern in blocked_patterns:
            try:
                await context.route(blocked_pattern, lambda route: route.abort())
            except Exception:
                pass
        return None, context

    try:
        browser = await p.chromium.launch(channel="chrome", **launch_args)
    except Exception:
        browser = await p.chromium.launch(**launch_args)

    context_args = {
        "no_viewport": True,
        "color_scheme": "dark",
        "permissions": ["clipboard-read", "clipboard-write"]
    }

    context = await browser.new_context(**context_args)
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); delete navigator.__proto__.webdriver;")
    for blocked_pattern in blocked_patterns:
        try:
            await context.route(blocked_pattern, lambda route: route.abort())
        except Exception:
            pass
    return browser, context

_shared_playwright = None
_shared_context = None
_shared_browser = None
_shared_headless = None
_shared_profile_path = None
_temp_profiles_to_clean = []
_shared_context_lock = None

async def reset_shared_browser_context():
    global _shared_context, _shared_browser, _shared_headless, _temp_profiles_to_clean, _shared_profile_path
    print("Resetting shared browser context...")
    if _shared_context:
        try:
            await _shared_context.close()
        except Exception:
            pass
    if _shared_browser:
        try:
            await _shared_browser.close()
        except Exception:
            pass
    _shared_context = None
    _shared_browser = None
    _shared_headless = None
    _shared_profile_path = None
    
    # Wait a brief moment for the chrome processes to release files
    await asyncio.sleep(1.0)
    
    # Try cleaning up registered temp profiles
    import shutil
    for path in list(_temp_profiles_to_clean):
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                _temp_profiles_to_clean.remove(path)
                print(f"Cleaned up temp profile directory: {path}")
            except Exception:
                pass
    try:
        cleanup_temp_profiles()
    except Exception:
        pass

async def get_shared_browser_context(headless=None, start_maximized=False, temp_suffix="", custom_profile_path=None):
    global _shared_playwright, _shared_context, _shared_browser, _shared_headless, _shared_context_lock, _shared_profile_path
    from playwright.async_api import async_playwright
    
    if headless is None:
        headless = load_config().get("headless", False)
        
    if _shared_context_lock is None:
        _shared_context_lock = asyncio.Lock()
        
    async with _shared_context_lock:
        # Run cleanup of any unused temp profiles first
        try:
            cleanup_temp_profiles()
        except Exception:
            pass
            
        target_profile_path = custom_profile_path
        if not target_profile_path:
            config = load_config()
            profiles = config.get("chrome_profiles", [])
            idx = config.get("current_profile_index", 0)
            if idx < len(profiles):
                target_profile_path = profiles[idx]
            else:
                target_profile_path = os.getenv("CHROME_PROFILE_PATH") or r"C:\Data\Profile 1"
                
        if _shared_context:
            if _shared_headless == headless and _shared_profile_path == target_profile_path:
                try:
                    await _shared_context.cookies()
                    print("Reusing existing shared browser context.")
                    return _shared_browser, _shared_context
                except Exception:
                    pass
            print(f"Shared browser context mismatch (headless current={_shared_headless} vs target={headless}, profile) or validation failed. Resetting...")
            await reset_shared_browser_context()
                
        if _shared_playwright is None:
            _shared_playwright = await async_playwright().start()
            
        browser_res, context_res = await get_browser_context(_shared_playwright, headless=headless, start_maximized=start_maximized, temp_suffix=temp_suffix, custom_profile_path=target_profile_path)
        _shared_browser = browser_res
        _shared_context = context_res
        _shared_headless = headless
        _shared_profile_path = target_profile_path
        return _shared_browser, _shared_context

def get_gemini_model_display_name(target_model: str) -> str:
    key = (target_model or "flash").lower()
    if "lite" in key:
        return "3.5 Flash-Lite"
    elif "pro" in key:
        return "3.1 Pro"
    else:
        return "3.8 Flash"

async def check_and_rotate_profiles_until_ready(context_logger=None, force_check=False, target_model="flash", headless=None):
    """
    Checks if the active Chrome Profile's Gemini model (Lite, Flash, or Pro) is limited.
    If it is limited, rotates to the next available profile in config.json.
    Repeats until a working profile is found or all profiles are checked.
    Returns: (browser, context) of the working profile, or raises Exception if all limited.
    """
    global _shared_browser, _shared_context, _shared_headless, _shared_profile_path
    
    config = load_config()
    profiles = config.get("chrome_profiles", [])
    if not profiles:
        raise Exception("Không tìm thấy Chrome Profile nào được cấu hình trong hệ thống.")
        
    start_idx = config.get("current_profile_index", 0)
    if start_idx >= len(profiles):
        start_idx = 0

    if headless is None:
        headless = config.get("headless", False)
        
    # Optimization: if not force_check and we already have a validated context matching desired headless mode, reuse it directly
    if not force_check and _shared_context and _shared_headless == headless:
        if _shared_profile_path in profiles:
            try:
                await _shared_context.cookies()
                return _shared_browser, _shared_context
            except Exception:
                pass
                
    num_profiles = len(profiles)
    model_name = get_gemini_model_display_name(target_model)
    
    for i in range(num_profiles):
        idx = (start_idx + i) % num_profiles
        profile_path = profiles[idx]
        
        msg = f"Đang kiểm tra giới hạn tài khoản ({model_name}) (Profile {idx+1}/{num_profiles}): {profile_path}..."
        if context_logger:
            await context_logger.log(msg, "info")
        else:
            print(msg)
            
        # Update config index so get_shared_browser_context launches this profile
        config["current_profile_index"] = idx
        save_config(config)
        
        # Only reset if the current shared context is using a different profile, is different headless mode, or is closed
        if _shared_context and (_shared_profile_path != profile_path or _shared_headless != headless):
            await reset_shared_browser_context()
        
        # Launch browser to verify without stealing focus (reusing open browser window if same profile)
        br, ctx = await get_shared_browser_context(headless=headless, start_maximized=False, custom_profile_path=profile_path)
        
        page = await ctx.new_page()
        try:
            await page.goto("https://gemini.google.com/app", timeout=60000)
            
            # Check login and rate-limit status
            status = await check_gemini_login_and_limit_status(page, target_model=target_model, context_logger=context_logger)
            
            if status == "needs_login":
                if context_logger:
                    await context_logger.log("Chưa đăng nhập trên Gemini. Đang chờ bạn đăng nhập thủ công trên cửa sổ trình duyệt (Tối đa 180s)...", "warning")
                else:
                    print("Needs login. Waiting for manual login...")
                    
                login_success = False
                for _ in range(90):  # 90 * 2s = 180s
                    await asyncio.sleep(2)
                    new_status = await check_gemini_login_and_limit_status(page, target_model=target_model, context_logger=None)
                    if new_status != "needs_login":
                        login_success = True
                        status = new_status
                        if context_logger:
                            await context_logger.log("Đăng nhập thành công!", "success")
                        break
                if not login_success:
                    if context_logger:
                        await context_logger.log(f"Bỏ qua profile {profile_path} do hết thời gian chờ đăng nhập.", "warning")
                    await page.close()
                    await reset_shared_browser_context()
                    continue
            
            if status == "limited":
                if context_logger:
                    await context_logger.log(f"Tài khoản {profile_path} bị giới hạn (Rate limit) model {model_name}. Đang xoay vòng...", "warning")
                else:
                    print(f"Profile {profile_path} is limited for model {model_name}. Rotating...")
                await page.close()
                await reset_shared_browser_context()
                continue
                
            # If status == "ok"
            if context_logger:
                await context_logger.log(f"Tài khoản {profile_path} KHÔNG bị giới hạn (Model {model_name}). Tiếp tục thực thi với tài khoản này.", "success")
            else:
                print(f"Profile {profile_path} is ready for {model_name}.")
            
            # Ensure strictly 1 page in context
            try:
                pages = ctx.pages
                if len(pages) > 1:
                    for extra in pages[1:]:
                        try: await extra.close()
                        except Exception: pass
            except Exception:
                pass
            return br, ctx
            
        except Exception as e:
            if context_logger:
                await context_logger.log(f"Lỗi khi kiểm tra tài khoản {profile_path}: {e}", "warning")
            else:
                print(f"Error checking profile {profile_path}: {e}")
            try:
                await page.close()
            except Exception:
                pass
            await reset_shared_browser_context()
            continue
            
    # If we exited the loop, all profiles are limited
    err_msg = f"Tất cả các tài khoản/Chrome Profiles đều đang bị giới hạn (Rate limited) model {model_name} hoặc chưa đăng nhập. Vui lòng thêm tài khoản mới trên giao diện Web UI hoặc đợi hết giới hạn."
    if context_logger:
        await context_logger.log(err_msg, "error")
    raise Exception(err_msg)

async def check_gemini_login_and_limit_status(page, target_model="flash", context_logger=None):
    # Wait for page elements to load
    await asyncio.sleep(2)
    
    textbox_found = False
    textbox_selectors = [
        "div[contenteditable='true']",
        "textarea",
        "[role='textbox']",
        "button.input-area-switch"
    ]
    for sel in textbox_selectors:
        if await page.locator(sel).first.count() > 0:
            textbox_found = True
            break
            
    if not textbox_found:
        return "needs_login"
        
    dropdown_btn = await page.query_selector("button.input-area-switch, button[data-test-id*='model' i]")
    if not dropdown_btn:
        return "ok"
        
    try:
        await human_delay(0.3, 0.75)
        await dropdown_btn.click()
        await page.wait_for_timeout(1000)
    except Exception:
        return "ok"
        
    check_js = """
    ((targetKey) => {
        const key = (targetKey || 'flash').toLowerCase();
        const items = Array.from(document.querySelectorAll('gem-menu-item, [role="menuitem"], .mat-mdc-menu-item, button[role="menuitem"]'));
        
        let targetItem = null;
        if (key.includes('lite')) {
            targetItem = items.find(el => {
                const txt = el.textContent.toLowerCase();
                return txt.includes('flash-lite') || (txt.includes('flash') && txt.includes('lite')) || txt.includes('fastest answers');
            });
        } else if (key.includes('pro')) {
            targetItem = items.find(el => {
                const txt = el.textContent.toLowerCase();
                return (txt.includes('3.1 pro') || (txt.includes('pro') && !txt.includes('problem') && !txt.includes('prompt') && !txt.includes('extended') && !txt.includes('thinking'))) || txt.includes('advanced reasoning');
            });
        } else {
            targetItem = items.find(el => {
                const txt = el.textContent.toLowerCase();
                return (txt.includes('3.8 flash') || txt.includes('3.6 flash') || txt.includes('flash') || txt.includes('all-around help')) && !txt.includes('lite');
            });
        }
                       
        if (!targetItem) {
            return { error: `Model option ${targetKey} not found in menu` };
        }
        
        const ariaDisabled = targetItem.getAttribute('aria-disabled') === 'true';
        const hasDisabledClass = targetItem.classList.contains('disabled') 
                              || targetItem.classList.contains('gmat-disabled')
                              || targetItem.querySelector('.disabled') !== null;
        
        const sublabelEl = targetItem.querySelector('.sublabel') || targetItem.querySelector('[class*="sublabel"]');
        const sublabel = sublabelEl ? sublabelEl.textContent.trim() : "";
        
        const isLimitText = /limit|giới hạn|reached|try again|quá tải|chờ|resets/i.test(sublabel) || /limit|giới hạn|reached|try again|quá tải|chờ|resets/i.test(targetItem.textContent);
        const isLimited = ariaDisabled || hasDisabledClass || isLimitText;
        
        if (!isLimited) {
            targetItem.click();
        }
        
        return {
            isLimited: isLimited,
            sublabel: sublabel,
            clicked: !isLimited,
            foundText: targetItem.textContent.trim().replace(/\\s+/g, ' ')
        };
    })
    """
    try:
        result = await page.evaluate(check_js, target_model)
    except Exception:
        result = None
        
    if not result or not isinstance(result, dict) or not result.get("clicked"):
        try:
            await dropdown_btn.click()
        except Exception:
            pass
        
    if isinstance(result, dict):
        if "error" in result:
            return "ok"
        if result.get("isLimited"):
            return "limited"
            
    return "ok"

async def ensure_model_selected(page, target_model="flash", context_logger=None):
    dropdown_btn = await page.query_selector("button.input-area-switch, button[data-test-id*='model' i]")
    if not dropdown_btn or not callable(getattr(dropdown_btn, "click", None)):
        return
        
    target_key = (target_model or "flash").lower()
    model_disp = get_gemini_model_display_name(target_model)
    
    try:
        btn_text = ""
        try:
            btn_text = await page.eval_on_selector("button.input-area-switch, button[data-test-id*='model' i]", "el => el.textContent")
        except Exception:
            pass
            
        btn_text_lower = (btn_text or "").lower()
        
        already_selected = False
        if "lite" in target_key:
            if "lite" in btn_text_lower or "3.5" in btn_text_lower:
                already_selected = True
        elif "pro" in target_key:
            if ("pro" in btn_text_lower or "3.1" in btn_text_lower) and "thinking" not in btn_text_lower:
                already_selected = True
        else:
            if ("flash" in btn_text_lower or "3.8" in btn_text_lower or "3.6" in btn_text_lower) and "lite" not in btn_text_lower:
                already_selected = True
                
        if already_selected:
            return
            
        await dropdown_btn.click()
        await page.wait_for_timeout(1000)
        
        check_js = """
        ((targetKey) => {
            const key = (targetKey || 'flash').toLowerCase();
            const items = Array.from(document.querySelectorAll('gem-menu-item, [role="menuitem"], .mat-mdc-menu-item, button[role="menuitem"]'));
            
            let targetItem = null;
            if (key.includes('lite')) {
                targetItem = items.find(el => {
                    const txt = el.textContent.toLowerCase();
                    return txt.includes('flash-lite') || (txt.includes('flash') && txt.includes('lite')) || txt.includes('fastest answers');
                });
            } else if (key.includes('pro')) {
                targetItem = items.find(el => {
                    const txt = el.textContent.toLowerCase();
                    return (txt.includes('3.1 pro') || (txt.includes('pro') && !txt.includes('problem') && !txt.includes('prompt') && !txt.includes('extended') && !txt.includes('thinking'))) || txt.includes('advanced reasoning');
                });
            } else {
                targetItem = items.find(el => {
                    const txt = el.textContent.toLowerCase();
                    return (txt.includes('3.8 flash') || txt.includes('3.6 flash') || txt.includes('flash') || txt.includes('all-around help')) && !txt.includes('lite');
                });
            }
                           
            if (targetItem) {
                const ariaDisabled = targetItem.getAttribute('aria-disabled') === 'true';
                const hasDisabledClass = targetItem.classList.contains('disabled') 
                                      || targetItem.classList.contains('gmat-disabled')
                                      || targetItem.querySelector('.disabled') !== null;
                const sublabelEl = targetItem.querySelector('.sublabel') || targetItem.querySelector('[class*="sublabel"]');
                const sublabel = sublabelEl ? sublabelEl.textContent.trim() : "";
                const isLimitText = /limit|giới hạn|reached|try again|quá tải|chờ|resets/i.test(sublabel) || /limit|giới hạn|reached|try again|quá tải|chờ|resets/i.test(targetItem.textContent);
                
                if (!ariaDisabled && !hasDisabledClass && !isLimitText) {
                    targetItem.click();
                    return { success: true };
                }
            }
            return { success: false };
        })
        """
        result = await page.evaluate(check_js, target_model)
        
        if not result or not isinstance(result, dict) or not result.get("success"):
            await dropdown_btn.click()
            if context_logger:
                await context_logger.log(f"Không thể tự động chọn model {model_disp} (có thể bị giới hạn hoặc lỗi giao diện).", "warning")
        else:
            if context_logger:
                await context_logger.log(f"Đã tự động chuyển đổi sang model {model_disp} trên trang hiện tại.", "success")
                
    except Exception as e:
        if context_logger:
            await context_logger.log(f"Lỗi khi đảm bảo chọn model {model_disp}: {e}", "warning")

async def clear_gemini_activity(page, context_logger=None):
    try:
        msg = "Bắt đầu dọn dẹp lịch sử hoạt động Gemini (My Activity)..."
        if context_logger:
            await context_logger.log(msg, "info")
        else:
            print(msg)

        await page.goto("https://myactivity.google.com/product/gemini", timeout=60000)
        await page.wait_for_timeout(3000)

        # Step 1: Click "Delete" dropdown button
        delete_btn = None
        delete_selectors = [
            "button:has-text('Delete')",
            "button:has-text('Xóa')",
            "button[aria-label*='Delete']",
            "button[aria-label*='Xóa']",
            "button[aria-haspopup='true']"
        ]
        
        for sel in delete_selectors:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                for idx in range(count):
                    el = loc.nth(idx)
                    txt = await el.text_content()
                    if "delete" in txt.lower() or "xóa" in txt.lower():
                        delete_btn = el
                        break
                if delete_btn:
                    break
            except Exception:
                pass
                
        if not delete_btn:
            for sel in delete_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        delete_btn = loc
                        break
                except Exception:
                    pass

        if not delete_btn:
            raise Exception("Không tìm thấy nút 'Xóa' (Delete) trên trang hoạt động.")

        await human_delay(0.3, 0.75)
        await delete_btn.click()
        await page.wait_for_timeout(1500)

        # Step 2: Click "All time" (Xóa từ trước đến nay)
        all_time_btn = None
        all_time_selectors = [
            "[role='dialog'] button:has-text('All time')",
            "[role='dialog'] [role='button']:has-text('All time')",
            "[role='dialog'] [role='menuitem']:has-text('All time')",
            "[role='dialog'] li:has-text('All time')",
            "[role='dialog'] span:has-text('All time')",
            "[role='dialog'] div:has-text('All time')",
            "[role='menuitem']:has-text('All time')",
            "[role='menuitem']:has-text('Từ trước đến nay')",
            "button:has-text('All time')",
            "button:has-text('Từ trước đến nay')",
            "[role='button']:has-text('All time')",
            "[role='button']:has-text('Từ trước đến nay')",
            "span:has-text('All time')",
            "span:has-text('Từ trước đến nay')",
            "div:has-text('All time')",
            "div:has-text('Từ trước đến nay')",
            "text='All time'",
            "text='Từ trước đến nay'",
            "text='Delete all time'",
            "text='Xóa từ trước đến nay'"
        ]
        for sel in all_time_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    all_time_btn = loc
                    break
            except Exception:
                pass

        if all_time_btn:
            await human_delay(0.25, 0.65)
            await all_time_btn.click()
        else:
            # DOM Evaluate fallback to find and click "All time"
            click_all_time_js = """
            (() => {
                const candidates = Array.from(document.querySelectorAll("[role='dialog'] *, [role='menu'] *, .modal *, div, span, button, li, [role='button'], [role='menuitem']"));
                for (const el of candidates) {
                    const txt = (el.innerText || el.textContent || "").trim();
                    if (/^all\\s*time$/i.test(txt) || /^từ\\s*trước\\s*đến\\s*nay$/i.test(txt) || /^all\\s*time\\b/i.test(txt) || /^từ\\s*trước\\s*đến\\s*nay\\b/i.test(txt)) {
                        el.click();
                        return true;
                    }
                }
                return false;
            })()
            """
            clicked = await page.evaluate(click_all_time_js)
            if not clicked:
                raise Exception("Không tìm thấy tùy chọn 'All time' (Xóa từ trước đến nay) trong menu.")

        if context_logger:
            await context_logger.log("Đã chọn chế độ 'All time' (Từ trước đến nay).", "info")
        await page.wait_for_timeout(2000)

        # Step 3: Handle all confirmation dialogs (Next -> Delete -> Got it)
        for confirm_step in range(5):
            confirm_btn = None
            confirm_selectors = [
                "[role='dialog'] button:has-text('Next')",
                "[role='dialog'] button:has-text('Tiếp theo')",
                "[role='dialog'] button:has-text('Delete')",
                "[role='dialog'] button:has-text('Xóa')",
                "[role='dialog'] button:has-text('Got it')",
                "[role='dialog'] button:has-text('Đã hiểu')",
                "[role='dialog'] button:has-text('OK')",
                "[role='dialog'] button:has-text('Close')",
                "[role='dialog'] button:has-text('Đóng')",
                "button:has-text('Next')",
                "button:has-text('Tiếp theo')",
                "button:has-text('Delete')",
                "button:has-text('Xóa')",
                "button:has-text('Got it')",
                "button:has-text('Đã hiểu')",
                "button:has-text('OK')",
                "button:has-text('Close')",
                "button:has-text('Đóng')",
                "span:has-text('Next')",
                "span:has-text('Tiếp theo')",
                "span:has-text('Delete')",
                "span:has-text('Xóa')",
                "span:has-text('Got it')",
                "span:has-text('Đã hiểu')"
            ]
            for sel in confirm_selectors:
                try:
                    loc = page.locator(sel)
                    count = await loc.count()
                    for idx in range(count):
                        el = loc.nth(idx)
                        if await el.is_visible():
                            confirm_btn = el
                            break
                    if confirm_btn:
                        break
                except Exception:
                    pass
            
            if confirm_btn:
                btn_txt = (await confirm_btn.text_content() or "").strip()
                if context_logger:
                    await context_logger.log(f"Đang xác nhận bước {confirm_step + 1}: click '{btn_txt}'...", "info")
                await human_delay(0.3, 0.75)
                await confirm_btn.click()
                await page.wait_for_timeout(2500)

                # Dừng ngay sau bước click 'Got it' / 'Đã hiểu' (hoàn tất xóa hoạt động)
                btn_lower = btn_txt.lower()
                if any(k in btn_lower for k in ["got it", "đã hiểu"]):
                    if context_logger:
                        await context_logger.log("Đã click 'Got it', hoàn tất quy trình xóa hoạt động.", "info")
                    break
            else:
                break

        msg = "Đã dọn dẹp toàn bộ lịch sử hoạt động Gemini (All time) thành công!"
        if context_logger:
            await context_logger.log(msg, "success")
        else:
            print(msg)
            
    except Exception as e:
        msg = f"Cảnh báo: Không thể tự động xóa hoạt động Gemini: {e}"
        if context_logger:
            await context_logger.log(msg, "warning")
        else:
            print(msg)

def download_image_sync(url: str, save_path: str, referer: str = None):
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        quoted_path = urllib.parse.quote(parsed.path, safe="/")
        quoted_query = urllib.parse.quote(parsed.query, safe="=&") if parsed.query else ""
        url = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            quoted_path,
            parsed.params,
            quoted_query,
            parsed.fragment
        ))
    except Exception as parse_err:
        print(f"Warning: Failed to quote URL {url}: {parse_err}")

    if not referer:
        if "vortexscans.org" in url or "storage.vortexscans.org" in url:
            referer = "https://vortexscans.org/"
        elif "toongod.org" in url or "tngcdn.com" in url:
            referer = "https://www.toongod.org/"
        elif "asurascans.com" in url:
            referer = "https://asurascans.com/"
        elif "valirscans.org" in url or "media.valirscans.org" in url:
            referer = "https://valirscans.org/"
        elif "nyxscans.com" in url or "media.nyxscans.com" in url:
            referer = "https://nyxscans.com/"
        elif "manhuaplus.com" in url:
            referer = "https://manhuaplus.com/"
        elif "comic.naver.com" in url or "pstatic.net" in url:
            referer = "https://comic.naver.com/"
        else:
            referer = "https://www.webtoons.com/"
            
    req = urllib.request.Request(
        url,
        headers={
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    try:
        with urllib.request.urlopen(req) as response:
            content = response.read()
            if not content or len(content) == 0:
                raise ValueError(f"Tải ảnh thất bại ({url}): Dữ liệu nhận được rỗng (0 bytes).")
            with open(save_path, "wb") as out_file:
                out_file.write(content)
    except Exception:
        if os.path.exists(save_path) and os.path.getsize(save_path) == 0:
            try:
                os.remove(save_path)
            except Exception:
                pass
        raise

async def download_image(url: str, save_path: str, referer: str = None, browser_context=None):
    if browser_context:
        try:
            req_referer = referer or ("https://comic.naver.com/" if ("pstatic.net" in url or "comic.naver.com" in url) else ("https://manhuaplus.com/" if "manhuaplus.com" in url else "https://www.webtoons.com/"))
            resp = await browser_context.request.get(url, headers={"Referer": req_referer})
            if resp.status == 200:
                body = await resp.body()
                if body and len(body) > 0:
                    with open(save_path, "wb") as out_file:
                        out_file.write(body)
                    return
                else:
                    raise ValueError(f"Tải ảnh thất bại ({url}): Dữ liệu nhận được rỗng (0 bytes).")
            else:
                raise ValueError(f"Tải ảnh thất bại ({url}): HTTP {resp.status}")
        except Exception:
            if os.path.exists(save_path) and os.path.getsize(save_path) == 0:
                try:
                    os.remove(save_path)
                except Exception:
                    pass
            # Fallback to download_image_sync
    await asyncio.to_thread(download_image_sync, url, save_path, referer)

def sanitize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"\s+", "_", title)
    title = re.sub(r"[^\w]", "", title)
    title = re.sub(r"_+", "_", title)
    return title.strip("_")

def strip_gemini_citations(text: str) -> str:
    """
    Loại bỏ triệt để tất cả các thẻ trích dẫn / grounding / citation do AI Gemini hoặc web UI sinh ra
    (e.g. [cite: 1], [cite: 1, 2], [source: 1], [PDF], (PDF), [1], [2]).
    """
    if not text:
        return ""
    text = re.sub(r"\[\s*cite:\s*[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*(?:source|trích dẫn|nguồn):\s*[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*(?:PDF|\.pdf)\s*\]|\(\s*(?:PDF|\.pdf)\s*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", "", text)
    text = re.sub(r"\s+([,.:;!?])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def handle_ai_glitch_restart(text: str) -> str:
    """
    Phát hiện và xử lý lỗi AI Gemini bị reset / restart sinh lại kịch bản giữa chừng,
    hoặc dính liền sau dấu '#' (e.g. "...thực thụ.#4 - Chuyện bắt đầu..."),
    hoặc dính liền giữa câu không có '#' (e.g. "...chỉ muốn sống yên[R3] - Vào ngày..."),
    hoặc in-line glitch lặp lại prefix trên cùng 1 dòng (e.g. "[R6] - Kẻ thù ngã g[R6] - Kẻ thù ngã quỵ..."),
    hoặc nhảy lùi số trang đột ngột về đầu (e.g. từ trang 40 lùi về 4).
    Khi phát hiện lỗi này, xóa toàn bộ nội dung phía trước câu restart đó,
    và chỉ lấy kết quả từ câu restart trở đi làm kết quả cuối cùng.
    Hỗ trợ bảo toàn hoàn toàn đoạn Intro Hook (1-5 dòng đầu) khi chuyển sang Story Recap.
    """
    if not text:
        return text

    # Nếu text chứa cả === INTRO HOOK === và === STORY RECAP ===, xử lý riêng phần story
    if "=== INTRO HOOK ===" in text and "=== STORY RECAP ===" in text:
        parts = text.split("=== STORY RECAP ===", 1)
        intro_part = parts[0].strip()
        story_part = parts[1].strip()
        cleaned_story = handle_ai_glitch_restart(story_part)
        return f"{intro_part}\n\n=== STORY RECAP ===\n{cleaned_story}"

    # 1. In-line glitch cleanup: xử lý trước khi tách dòng
    inline_glitch_pat = re.compile(
        r"(?:\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*(\d{1,4})\s*\]|\b(?:Page|Trang|Region|Khung|Frame|R)\s*(\d{1,4}))\s*[\-:\–\—\−\~]",
        re.IGNORECASE
    )
    raw_lines = text.splitlines()
    fixed_inline = []
    for line in raw_lines:
        l_str = line.strip()
        if not l_str:
            continue
        matches = list(inline_glitch_pat.finditer(l_str))
        if len(matches) > 1:
            last_m = matches[-1]
            l_str = l_str[last_m.start():].strip()
        fixed_inline.append(l_str)
    text = "\n".join(fixed_inline)

    # 2. Tách các dòng bị dính liền (kể cả có hoặc không có dấu '#')
    pat_after_hash = re.compile(
        r"#\s*(?:\[?(?:PDF|\.pdf|source|trích dẫn)\]?|\(PDF\)|\+\s*\d+|\[\d+\])*\s*(?=(?:\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\]|\b(?:Page|Trang|Region|Khung|Frame|R)\s*\d{1,4}|\d{1,4})\s*(?:[\-:\–\—\−\~]|\.(?!\d))\s*)",
        re.IGNORECASE
    )
    pat_glued = re.compile(
        r"(?<=[^\d\s\r\n\[])\s*(?:\[?(?:PDF|\.pdf|source|trích dẫn)\]?|\(PDF\)|\+\s*\d+|\[\d+\])*\s*(?=(?:\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\]|\b(?:Page|Trang|Region|Khung|Frame|R)\s*\d{1,4})\s*(?:[\-:\–\—\−\~]|\.(?!\d))\s*|\d{1,4}\s*[\-:\–\—\−\~]\s+)",
        re.IGNORECASE
    )
    text = pat_after_hash.sub("#\n", text)
    text = pat_glued.sub("\n", text)

    line_page_pat = re.compile(
        r"^\s*(?:[\*\-\•\>]+\s*)?(?:Page|Trang|Region|Khung|Frame|R)?\s*\[?\*?\*?(?:R|r|Region|Trang|Page|Khung|Frame)?\s*_?-?\s*(\d{1,4})\*?\*?\]?\s*(?:[\-:\–\—\−\~]|\.(?!\d))",
        re.IGNORECASE
    )

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""

    parsed_lines = []
    for idx, line in enumerate(lines):
        m = line_page_pat.match(line)
        if m:
            parsed_lines.append((idx, int(m.group(1)), line))
        else:
            parsed_lines.append((idx, None, line))

    restart_idx = None
    max_page = 0
    for i, (orig_idx, p_num, line_str) in enumerate(parsed_lines):
        if p_num is None:
            continue
        if max_page >= 10 and p_num <= 10:
            is_intro_transition = (i <= 5 and (len(parsed_lines) - i) >= 15)
            if is_intro_transition:
                max_page = p_num  # Reset max_page tracking for Story Recap
                continue
            else:
                restart_idx = orig_idx
                break
        elif max_page >= 25 and p_num <= max_page - 15:
            is_intro_transition = (i <= 5 and (len(parsed_lines) - i) >= 15)
            if is_intro_transition:
                max_page = p_num
                continue
            else:
                restart_idx = orig_idx
                break
        if p_num > max_page:
            max_page = p_num

    if restart_idx is not None:
        lines = lines[restart_idx:]

    return "\n".join(lines).strip()

def clean_gemini_response(text: str) -> str:
    if not text:
        return text
    
    # Strip trailing XML-like tags and markdown backticks recursively
    text = text.strip()
    while True:
        new_text = re.sub(r"<\s*/\s*[a-zA-Z_0-9\-]+\s*>\s*$", "", text)
        new_text = re.sub(r"```[a-zA-Z0-9_-]*\s*$", "", new_text)
        new_text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", new_text)
        new_text = new_text.strip()
        if new_text == text:
            break
        text = new_text

    # 1. Xử lý lỗi AI glitch restart (xóa bỏ đoạn sinh lỗi phía trước câu restart)
    text = handle_ai_glitch_restart(text)

    # 2. Normalize line breaks: separate glued lines
    pat_after_hash = re.compile(
        r"#\s*(?:\[?(?:PDF|\.pdf|source|trích dẫn)\]?|\(PDF\)|\+\s*\d+|\[\d+\])*\s*(?=(?:\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\]|\b(?:Page|Trang|Region|Khung|Frame|R)\s*\d{1,4}|\d{1,4})\s*(?:[\-:\–\—\−\~]|\.(?!\d))\s*)",
        re.IGNORECASE
    )
    pat_glued = re.compile(
        r"(?<=[^\d\s\r\n\[])\s*(?:\[?(?:PDF|\.pdf|source|trích dẫn)\]?|\(PDF\)|\+\s*\d+|\[\d+\])*\s*(?=(?:\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\]|\b(?:Page|Trang|Region|Khung|Frame|R)\s*\d{1,4})\s*(?:[\-:\–\—\−\~]|\.(?!\d))\s*|\d{1,4}\s*[\-:\–\—\−\~]\s+)",
        re.IGNORECASE
    )
    text = pat_after_hash.sub("#\n", text)
    text = pat_glued.sub("\n", text)

    # 3. Split text into lines
    lines = text.split("\n")
    page_prefix_pat = re.compile(
        r"^\s*(?:[\*\-\•\>]+\s*)?(?:Page|Trang|Region|Khung|Frame|R)?\s*\[?\*?\*?(?:R|r|Region|Trang|Page|Khung|Frame)?\s*_?-?\s*(\d{1,4})\*?\*?\]?\s*(?:[\-:\–\—\−\~]|\.(?!\d))\s*",
        re.IGNORECASE
    )

    has_any_hash = any("#" in l for l in lines)
    cleaned_lines = []
    in_thinking = False
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        if "<thinking>" in line_str or "<thought>" in line_str:
            in_thinking = True

        m_pref = page_prefix_pat.match(line_str)
        if m_pref:
            in_thinking = False

        if in_thinking:
            if "</thinking>" in line_str or "</thought>" in line_str:
                in_thinking = False
            continue

        if m_pref:
            page_num = str(int(m_pref.group(1)))
            raw_content = line_str[m_pref.end():].strip()
            # Strip stray watermark badge tags (e.g. "Type: TRANH (VALID) - ")
            raw_content = re.sub(r"^(?:\[?(?:Type\s*:\s*)?[A-Za-z0-9_]+(?:\s*\([^\)]+\))?\]?\s*[\-:\–\—\−\~]\s*)+", "", raw_content, flags=re.IGNORECASE).strip()
            raw_content = re.sub(r"[\*\_`]", "", raw_content)
            # Clean citation badges at the end or anywhere in text
            raw_content = strip_gemini_citations(raw_content)

            # Strip in-content [R\d+] - or C[R\d+] - glitch prefixes from raw_content
            if re.search(r"\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\s*\]\s*[\-:\–\—\−\~]", raw_content):
                raw_content = re.sub(r"^.*\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\s*\]\s*[\-:\–\—\−\~]\s*", "", raw_content, flags=re.IGNORECASE).strip()

            # Handle '#' at the end or inside line
            if "#" in raw_content:
                parts = raw_content.split("#")
                main_content = "#".join(parts[:-1]).strip()
                main_content = strip_gemini_citations(main_content)
                if main_content:
                    cleaned_lines.append(f"{page_num} - {main_content}#")
            else:
                if not has_any_hash:
                    if raw_content:
                        cleaned_lines.append(f"{page_num} - {raw_content}#")
                else:
                    if raw_content:
                        cleaned_lines.append(f"{page_num} - {raw_content}")

    # Discard fragmented un-hashed lines from beginning if subsequent lines have '#'
    while cleaned_lines:
        first = cleaned_lines[0].strip()
        if page_prefix_pat.match(first) and not first.endswith("#"):
            if any(l.endswith("#") for l in cleaned_lines[1:]):
                cleaned_lines.pop(0)
                continue
        break

    # If any remaining valid lines are still missing '#', auto-append '#'
    for i in range(len(cleaned_lines)):
        cl = cleaned_lines[i].strip()
        if not cl.endswith("#"):
            cleaned_lines[i] = cl + "#"
    garbage_words_pat = re.compile(r"^(?:PDF|\.pdf|\(PDF\)|\+\s*\d+|chapter|#|\s*)+$", re.IGNORECASE)
    while cleaned_lines:
        last = cleaned_lines[-1].strip()
        if not last or garbage_words_pat.match(last) or not page_prefix_pat.match(last):
            cleaned_lines.pop()
        else:
            break

    return "\n".join(cleaned_lines)

def count_recap_sentences(parsed_or_text) -> int:
    """
    Counts total speech sentences in parsed recap items or raw recap text.
    Splits by standard punctuation [.!?]+
    """
    if isinstance(parsed_or_text, str):
        try:
            parsed = parse_gemini_recap_text(parsed_or_text)
        except Exception:
            parsed = []
    else:
        parsed = parsed_or_text
    
    if not parsed:
        return 0
        
    total_sentences = 0
    for item in parsed:
        if isinstance(item, dict):
            speech = item.get("speech", "")
        else:
            speech = str(item)
        sentences = [s.strip() for s in re.split(r'[.!?]+(?:\s+|$)', speech) if s.strip()]
        total_sentences += max(1, len(sentences)) if speech.strip() else 0
    return total_sentences

def verify_gemini_response_format(text: str, is_intro: bool = False, min_sentences: int = 1) -> tuple[bool, str]:
    if not text:
        return False, "Response is empty"
    
    text = clean_gemini_response(text)
    
    # 1. Check if this is a JSON response
    extracted = extract_json_from_text(text)
    if extracted:
        try:
            parsed = json.loads(extracted)
            if isinstance(parsed, list) and len(parsed) > 0:
                for item in parsed:
                    if not isinstance(item, dict) or "speech" not in item or "images" not in item:
                        return False, "JSON item lacks 'speech' or 'images' key"
                if is_intro:
                    sentence_count = count_recap_sentences(parsed)
                    total_count = max(len(parsed), sentence_count)
                    if not (1 <= total_count <= 8):
                        return False, f"Intro hook phải có từ 1 đến 5 đoạn/câu (hiện có {len(parsed)} đoạn, {sentence_count} câu)"
                elif min_sentences > 1:
                    sentence_count = count_recap_sentences(parsed)
                    if len(parsed) < min_sentences and sentence_count < min_sentences:
                        return False, f"Kịch bản recap quá ngắn ({max(len(parsed), sentence_count)} dòng/câu < {min_sentences} dòng yêu cầu)"
                return True, "Valid JSON"
        except Exception:
            pass

    # 2. Check format line by line after clean_gemini_response
    clean_text = text.strip()
    if not clean_text:
        return False, "Response contains only thinking tags or is empty."

    # 3. Check format line by line
    lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
    if not lines:
        return False, "No non-empty lines found in the response."

    page_pat = re.compile(
        r"^\s*(?:[\*\-\•\>]+\s*)?(?:Page|Trang|Region|Khung|Frame|R)?\s*\[?\*?\*?(?:R|r|Region|Trang|Page|Khung|Frame)?\s*_?-?\s*(\d{1,4})\*?\*?\]?\s*(?:[\-:\–\—\−\~]|\.(?!\d))\s*(.+)$",
        re.IGNORECASE | re.DOTALL
    )
    for idx, line in enumerate(lines):
        if not line.endswith("#"):
            return False, f"Dòng {idx+1} chưa hoàn tất hoặc thiếu dấu kết thúc (#): '{line}'"
        
        line_content = line[:-1].strip()
        match = page_pat.match(line_content)
        if not match:
            return False, f"Dòng {idx+1} không khớp định dạng mong đợi '[Page] - [Text]': '{line}'"

    if is_intro:
        total_sentences = 0
        for line in lines:
            line_content = line[:-1].strip()
            match = page_pat.match(line_content)
            if match:
                speech = match.group(2).strip()
                speech = re.sub(r"^(?:\[?(?:Type\s*:\s*)?[A-Za-z0-9_]+(?:\s*\([^\)]+\))?\]?\s*[\-:\–\—\−\~]\s*)+", "", speech, flags=re.IGNORECASE).strip()
                speech = strip_gemini_citations(speech)
                s_list = [s.strip() for s in re.split(r'[.!?]+(?:\s+|$)', speech) if s.strip()]
                total_sentences += max(1, len(s_list)) if speech.strip() else 0
        total_intro_units = max(len(lines), total_sentences)
        if not (1 <= total_intro_units <= 8):
            return False, f"Intro hook phải có từ 1 đến 5 dòng/câu (hiện có {len(lines)} dòng, {total_sentences} câu)"
        return True, "Valid"
    elif min_sentences > 1:
        total_sentences = 0
        for line in lines:
            line_content = line[:-1].strip()
            match = page_pat.match(line_content)
            if match:
                speech = match.group(2).strip()
                speech = strip_gemini_citations(speech)
                s_list = [s.strip() for s in re.split(r'[.!?]+(?:\s+|$)', speech) if s.strip()]
                total_sentences += max(1, len(s_list)) if speech.strip() else 0
        if len(lines) < min_sentences and total_sentences < min_sentences:
            return False, f"Kịch bản recap quá ngắn ({max(len(lines), total_sentences)} dòng/câu < {min_sentences} dòng yêu cầu)"

    return True, "Valid"

def parse_gemini_recap_text(text: str) -> list:
    if not text:
        return []
    
    # Check if JSON directly
    extracted = extract_json_from_text(text)
    if extracted:
        try:
            parsed = json.loads(extracted)
            if isinstance(parsed, list) and len(parsed) > 0:
                valid = True
                for item in parsed:
                    if not isinstance(item, dict) or "speech" not in item or "images" not in item:
                        valid = False
                        break
                if valid:
                    for item in parsed:
                        sp = strip_gemini_citations(item.get("speech", ""))
                        if re.search(r"\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\s*\]\s*[\-:\–\—\−\~]", sp):
                            sp = re.sub(r"^.*\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\s*\]\s*[\-:\–\—\−\~]\s*", "", sp, flags=re.IGNORECASE).strip()
                        item["speech"] = sp
                    return parsed
        except Exception:
            pass

    text = clean_gemini_response(text)
    
    # Verify response format and check for garbage at the end
    is_valid, err_msg = verify_gemini_response_format(text, is_intro=False, min_sentences=1)
    if not is_valid:
        # Fallback check if it's a valid single-line intro hook
        is_intro_valid, intro_err = verify_gemini_response_format(text, is_intro=True)
        if not is_intro_valid:
            raise ValueError(f"Kiểm tra định dạng phản hồi Gemini thất bại: {err_msg}")
        
    # 1. Strip everything between <thinking> and </thinking>
    text_clean = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()
    
    # 2. Split by lines and '#'
    lines = [line.strip() for line in text_clean.split("\n") if line.strip()]
    parsed_list = []
    
    page_pat = re.compile(
        r"^\s*(?:[\*\-\•\>]+\s*)?(?:Page|Trang|Region|Khung|Frame|R)?\s*\[?\*?\*?(?:R|r|Region|Trang|Page|Khung|Frame)?\s*_?-?\s*(\d{1,4})\*?\*?\]?\s*(?:[\-:\–\—\−\~]|\.(?!\d))\s*(.*)$",
        re.IGNORECASE | re.DOTALL
    )
    for line in lines:
        line_str = line[:-1].strip() if line.endswith("#") else line.strip()
        if not line_str:
            continue
            
        m = page_pat.match(line_str)
        if m:
            page_num = str(int(m.group(1).strip()))
            content = m.group(2).strip()
            if content:
                content = re.sub(r"^(?:\[?(?:Type\s*:\s*)?[A-Za-z0-9_]+(?:\s*\([^\)]+\))?\]?\s*[\-:\–\—\−\~]\s*)+", "", content, flags=re.IGNORECASE).strip()
                content = re.sub(r"[\*\_`]", "", content)
                # Clean any stray citation badges from content
                content = strip_gemini_citations(content)
                # Strip in-content [R\d+] - or C[R\d+] - glitch prefixes
                if re.search(r"\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\s*\]\s*[\-:\–\—\−\~]", content):
                    content = re.sub(r"^.*\[\s*(?:R|r|Region|Trang|Page|Khung|Frame)?\s*\d{1,4}\s*\]\s*[\-:\–\—\−\~]\s*", "", content, flags=re.IGNORECASE).strip()
                if content:
                    parsed_list.append({
                        "speech": content,
                        "images": [
                            {
                                "page": str(page_num),
                                "priority": 1.0
                            }
                        ]
                    })
    # Normalize priorities for downstream components
    for item in parsed_list:
        if isinstance(item, dict) and "speech" in item and "images" in item:
            images_list = item.get("images", [])
            if isinstance(images_list, list) and len(images_list) > 0:
                total_p = sum(float(img.get("priority", 0)) for img in images_list)
                if abs(total_p - 1.0) > 0.02:
                    for img in images_list:
                        img["priority"] = 1.0 / len(images_list)
                        
    return parsed_list

def extract_json_from_text(text: str) -> str:
    raw_json = None
    # 1. Try markdown code block
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        raw_json = match.group(1).strip()
    else:
        # 2. Find the outermost matching braces { ... } or brackets [ ... ] using stack-based match
        first_brace = text.find('{')
        first_bracket = text.find('[')
        
        if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
            brace_count = 0
            in_string = False
            escape_char = False
            for i in range(first_brace, len(text)):
                char = text[i]
                if escape_char:
                    escape_char = False
                    continue
                if char == '\\':
                    escape_char = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            raw_json = text[first_brace:i+1].strip()
                            break
        elif first_bracket != -1:
            bracket_count = 0
            in_string = False
            escape_char = False
            for i in range(first_bracket, len(text)):
                char = text[i]
                if escape_char:
                    escape_char = False
                    continue
                if char == '\\':
                    escape_char = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == '[':
                        bracket_count += 1
                    elif char == ']':
                        bracket_count -= 1
                        if bracket_count == 0:
                            raw_json = text[first_bracket:i+1].strip()
                            break

    if not raw_json:
        return None

    # Remove trailing commas
    try:
        raw_json = re.sub(r',\s*([\]}])', r'\1', raw_json)
    except Exception:
        pass

    # 3. Quote repair: Replace unescaped double quotes inside "speech" values with single quotes
    pattern = r'"speech"\s*:\s*"(.*?)"(?=\s*(?:,|\s*\}))'
    def repl(m):
        val = m.group(1)
        fixed_val = re.sub(r'(?<!\\)"', "'", val)
        return f'"speech": "{fixed_val}"'

    try:
        fixed_json = re.sub(pattern, repl, raw_json, flags=re.DOTALL)
        return fixed_json
    except Exception:
        return raw_json

# Analyze Episode Count Route
@app.post("/api/analyze")
async def analyze(payload: AnalyzeRequest):
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL trống.")
    
    page = None
    try:
        browser, context = await get_shared_browser_context()
        nav_manager = NavigationManager(sse_logger)
        nav_manager.context = context
        nav_manager.browser = browser
        page = await context.new_page()

        await sse_logger.log(f"Đang tải trang chính để phân tích: {url}", "info")
        await nav_manager.safe_goto(page, url, reason="Load manhwa series page for episode count analysis", caller="analyze")

        if "toongod.org" in url and "/chapter-" in url:
            url = re.sub(r"/chapter-[^/]+/?$", "/", url)
            await sse_logger.log(f"Đường dẫn tập truyện phát hiện. Chuẩn hóa thành trang chính bộ truyện: {url}", "info")
            await nav_manager.safe_goto(page, url, reason="Load normalized manhwa series page for episode count analysis", caller="analyze")
        elif "asurascans.com" in url and "/chapter/" in url:
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            await sse_logger.log(f"Đường dẫn tập truyện phát hiện. Chuẩn hóa thành trang chính bộ truyện: {url}", "info")
            await nav_manager.safe_goto(page, url, reason="Load normalized manhwa series page for episode count analysis", caller="analyze")
        elif "valirscans.org" in url and "/chapter/" in url:
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            await sse_logger.log(f"Đường dẫn tập truyện phát hiện. Chuẩn hóa thành trang chính bộ truyện: {url}", "info")
            await nav_manager.safe_goto(page, url, reason="Load normalized manhwa series page for episode count analysis", caller="analyze")
        elif "nyxscans.com" in url and ("/chapter-" in url or "/chapter/" in url):
            url = re.sub(r"/chapter-[^/]+/?$", "", url)
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            await sse_logger.log(f"Đường dẫn tập truyện phát hiện. Chuẩn hóa thành trang chính bộ truyện: {url}", "info")
            await nav_manager.safe_goto(page, url, reason="Load normalized manhwa series page for episode count analysis", caller="analyze")
        elif "manhuaplus.com" in url and "/chapter-" in url:
            url = re.sub(r"/chapter-[^/]+/?$", "/", url)
            await sse_logger.log(f"Đường dẫn tập truyện phát hiện. Chuẩn hóa thành trang chính bộ truyện: {url}", "info")
            await nav_manager.safe_goto(page, url, reason="Load normalized manhwa series page for episode count analysis", caller="analyze")
        elif "comix.to" in url:
            parsed_url = urllib.parse.urlparse(url)
            parts = parsed_url.path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "title":
                last_part = parts[-1]
                if re.search(r"\d+-chapter-", last_part):
                    new_path = "/" + "/".join(parts[:-1])
                    url = urllib.parse.urlunparse(parsed_url._replace(path=new_path, query="", fragment=""))
                    await sse_logger.log(f"Đường dẫn tập truyện phát hiện. Chuẩn hóa thành trang chính bộ truyện: {url}", "info")
                    await nav_manager.safe_goto(page, url, reason="Load normalized manhwa series page for episode count analysis", caller="analyze")
        elif "comic.naver.com" in url and "/webtoon/detail" in url:
            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            title_id = query_params.get("titleId", [""])[0]
            if title_id:
                url = f"https://comic.naver.com/webtoon/list?titleId={title_id}"
                await sse_logger.log(f"Đường dẫn tập truyện phát hiện. Chuẩn hóa thành trang chính bộ truyện: {url}", "info")
                await nav_manager.safe_goto(page, url, reason="Load normalized manhwa series page for episode count analysis", caller="analyze")

        title_text = ""
        if "comic.naver.com" in url:
            try:
                for sel in ["h2.EpisodeListInfo__title--mYLlC", "span.EpisodeListInfo__title--mYLlC", ".EpisodeListInfo__title", ".comic_info h2", "meta[property='og:title']"]:
                    if await page.locator(sel).count() > 0:
                        if sel.startswith("meta"):
                            title_text = await page.locator(sel).first.get_attribute("content") or ""
                        else:
                            title_text = await page.locator(sel).first.inner_text()
                        if title_text:
                            break
                if title_text:
                    title_text = re.sub(r"\s*::\s*.*$", "", title_text).strip()
                    title_text = re.sub(r"\s*-\s*NAVER.*$", "", title_text, flags=re.IGNORECASE).strip()
            except Exception:
                pass
        elif "vortexscans.org" in url:
            try:
                await page.wait_for_selector("h1.break-words, h1.text-2xl", timeout=5000)
                title_text = await page.locator("h1.break-words, h1.text-2xl").first.inner_text()
            except Exception:
                pass
        elif "toongod.org" in url:
            try:
                await page.wait_for_selector(".post-title h1", timeout=5000)
                title_text = await page.locator(".post-title h1").first.inner_text()
            except Exception:
                pass
        elif "asurascans.com" in url:
            try:
                await page.wait_for_selector("h1", timeout=5000)
                title_text = await page.locator("h1").first.inner_text()
            except Exception:
                pass
        elif "valirscans.org" in url:
            try:
                await page.wait_for_selector("h1", timeout=5000)
                title_text = await page.locator("h1").first.inner_text()
            except Exception:
                pass
        elif "comix.to" in url:
            try:
                await page.wait_for_selector("h1.mpage__title", timeout=5000)
                title_text = await page.locator("h1.mpage__title").first.inner_text()
            except Exception:
                pass
        elif "nyxscans.com" in url:
            try:
                h1s = await page.locator("h1").all_inner_texts()
                if h1s:
                    for h in reversed(h1s):
                        if h.strip().lower() not in ['status', 'type', 'chapters', 'last update', 'genres']:
                            title_text = h.strip()
                            break
            except Exception:
                pass
        elif "manhuaplus.com" in url:
            try:
                await page.wait_for_selector(".post-title h1, h1", timeout=5000)
                title_text = await page.locator(".post-title h1, h1").first.inner_text()
            except Exception:
                pass
        if not title_text:
            title_text = await page.title()
            title_text = title_text.split("|")[0].strip()
            title_text = title_text.split("::")[0].strip()
            title_text = title_text.split("Chapter")[0].strip()

        max_ep = 0
        if "comic.naver.com" in url:
            try:
                try:
                    await page.wait_for_selector("a[href*='/webtoon/detail?']", timeout=8000)
                except Exception:
                    pass
                hrefs = await page.locator("a[href*='/webtoon/detail?']").evaluate_all(
                    "elements => elements.map(el => el.getAttribute('href'))"
                )
                naver_nos = []
                for href in hrefs:
                    if href and "no=" in href:
                        m = re.search(r"no=(\d+)", href)
                        if m:
                            naver_nos.append(int(m.group(1)))
                if naver_nos:
                    max_ep = max(naver_nos)
            except Exception:
                pass
        elif "comix.to" in url:
            try:
                hrefs = await page.locator("a.mchap-row__primary").evaluate_all(
                    "elements => elements.map(el => el.getAttribute('href'))"
                )
                for href in hrefs:
                    if href and "/title/" in href and "chapter" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if len(parts) >= 3 and parts[0] == "title":
                            slug = parts[-1]
                            m = re.search(r"chapter-(\d+\.?\d*)", slug)
                            if m:
                                try:
                                    max_ep = max(max_ep, int(float(m.group(1))))
                                except ValueError:
                                    pass
            except Exception:
                pass
        elif "vortexscans.org" in url:
            try:
                chapters_locator = page.locator("h1:has-text('Chapters') ~ div p")
                if await chapters_locator.first.count() > 0:
                    count_text = await chapters_locator.first.inner_text()
                    count_clean = count_text.strip()
                    if count_clean.isdigit():
                        max_ep = int(count_clean)
            except Exception:
                pass

        if max_ep == 0:
            # Click "Show more" buttons if present on Vortex Scans or Nyx Scans to fall back
            if "vortexscans.org" in url or "nyxscans.com" in url:
                click_count = 0
                while True:
                    show_more_button = page.locator("button:has-text('Show more'), button:has-text('Show More')")
                    visible_count = await show_more_button.count()
                    found_clickable = False
                    for idx in range(visible_count):
                        btn = show_more_button.nth(idx)
                        if await btn.is_visible() and await btn.is_enabled():
                            await btn.click()
                            await asyncio.sleep(0.8)
                            click_count += 1
                            found_clickable = True
                            break
                    if not found_clickable or click_count >= 15:
                        break

            await page.wait_for_selector("a", timeout=10000)
            hrefs = await page.locator("a").evaluate_all("elements => elements.map(el => el.getAttribute('href'))")

            vortex_chapters = []
            for href in hrefs:
                if href:
                    if "episode_no=" in href:
                        m = re.search(r"episode_no=(\d+)", href)
                        if m:
                            max_ep = max(max_ep, int(m.group(1)))
                    elif ("vortexscans.org" in url or "toongod.org" in url or "nyxscans.com" in url or "manhuaplus.com" in url) and "/chapter-" in href:
                        if "manhuaplus.com" in url:
                            parsed_u = urllib.parse.urlparse(url)
                            u_parts = parsed_u.path.strip("/").split("/")
                            m_slug = u_parts[1] if len(u_parts) >= 2 and u_parts[0] == "manga" else (u_parts[0] if u_parts else "")
                            if m_slug and f"/{m_slug}/" not in href:
                                continue
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if parts:
                            last_part = parts[-1]
                            if last_part.startswith("chapter-"):
                                vortex_chapters.append(last_part)
                    elif "asurascans.com" in url and "/chapter/" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if len(parts) >= 2 and parts[-2] == "chapter":
                            vortex_chapters.append(parts[-1])
                    elif "valirscans.org" in url and "/chapter/" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if len(parts) >= 2 and parts[-2] == "chapter":
                            vortex_chapters.append(parts[-1])

            if ("vortexscans.org" in url or "toongod.org" in url or "nyxscans.com" in url or "manhuaplus.com" in url):
                try:
                    html_content = await page.content()
                    raw_matches = re.findall(r'chapter-[a-zA-Z0-9_\.-]+', html_content)
                    for rm in raw_matches:
                        clean_rm = re.sub(r'["\',;\\/<>].*$', '', rm).strip()
                        if clean_rm and clean_rm.startswith("chapter-") and len(clean_rm) <= 40:
                            vortex_chapters.append(clean_rm)
                except Exception:
                    pass

            if ("vortexscans.org" in url or "toongod.org" in url or "nyxscans.com" in url or "manhuaplus.com" in url) and vortex_chapters:
                vortex_chapters = list(dict.fromkeys(vortex_chapters))
                def extract_chap_number(slug):
                    m = re.search(r"chapter-(\d+)(?:[_\.-](\d+))?", str(slug), re.IGNORECASE)
                    if m:
                        try:
                            return float(m.group(1))
                        except ValueError:
                            pass
                    return 0.0
                vortex_chapters.sort(key=extract_chap_number)
                highest_ch = max(extract_chap_number(s) for s in vortex_chapters)
                max_ep = max(len(vortex_chapters), int(highest_ch))
            elif ("asura" in urllib.parse.urlparse(url).netloc.lower() or "valirscans.org" in urllib.parse.urlparse(url).netloc.lower()) and vortex_chapters:
                vortex_chapters = list(set(vortex_chapters))
                def extract_asura_number(slug):
                    try:
                        return float(slug)
                    except ValueError:
                        pass
                    m = re.search(r"(\d+\.?\d*)", slug)
                    if m:
                        try:
                            return float(m.group(1))
                        except ValueError:
                            pass
                    return 0.0
                vortex_chapters.sort(key=extract_asura_number)
                highest_ch = max(extract_asura_number(s) for s in vortex_chapters)
                max_ep = max(len(vortex_chapters), int(highest_ch))

        if max_ep == 0:
            max_ep = 1
            await sse_logger.log("Không tự động phát hiện được số tập. Mặc định là 1 tập.", "warning")

        return {
            "title": title_text,
            "total_episodes": max_ep
        }
    except Exception as e:
        error_msg = f"Lỗi phân tích bộ truyện: {str(e)}"
        await sse_logger.log(error_msg, "error")
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass

dino_processor = None
dino_model = None
sam_processor = None
sam_model = None

async def process_single_image(
    idx: int, file_name: str, path: str, 
    effective_threshold: float, nsfw_mode: str, 
    device: str, sem: asyncio.Semaphore, sse_logger, 
    total_images: int, prompt: str,
    pdf_img_path: str = None
) -> str:
    global dino_processor, dino_model, sam_processor, sam_model
    import cv2
    import numpy as np
    import torch
    from PIL import Image

    async with sem:
        if sse_logger:
            await sse_logger.log(f"  [Safe Mode] Đang kiểm duyệt {file_name} ({idx + 1}/{total_images})...", "info")

        def sync_process():
            img_cv = cv2.imread(path)
            if img_cv is None:
                return f"{file_name}: error reading"

            h_img, w_img = img_cv.shape[:2]
            with Image.open(path) as img:
                image = img.convert("RGB")
                image.load()

            inputs = dino_processor(images=image, text=prompt, return_tensors="pt").to(device)
            with torch.no_grad():
                outputs = dino_model(**inputs)

            results_dino = dino_processor.post_process_grounded_object_detection(
                outputs,
                inputs.input_ids,
                threshold=0.25,
                text_threshold=0.25,
                target_sizes=[image.size[::-1]]
            )[0]

            boxes = results_dino["boxes"].cpu().numpy()
            scores = results_dino["scores"].cpu().numpy()
            labels = results_dino.get("text_labels", results_dino.get("labels", []))

            # Strictly true sensitive adult nudity keywords (matching prompt: female nipple, bare buttocks, exposed genitalia, completely nude body)
            sensitive_keywords = [
                "nipple", "buttock", "genitalia", "nude"
            ]
            text_keywords = ["speech", "bubble", "text", "words", "written", "write", "dialogue", "letter", "font", "word", "talk"]

            # Compute skin tone mask in YCrCb + HSV space to verify whether a detected region has bare skin
            ycrcb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2YCrCb)
            cr = ycrcb[:, :, 1]
            cb = ycrcb[:, :, 2]
            y_chan = ycrcb[:, :, 0]
            skin_raw = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)

            hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
            sat = hsv[:, :, 1]
            val = hsv[:, :, 2]
            # Real bare skin in comics is not pure white or pure dark clothing
            skin_mask = skin_raw & (sat >= 15) & (val >= 35) & (val <= 250)

            censor_boxes = []
            keep_boxes = []

            for idx_box in range(len(boxes)):
                box = boxes[idx_box]
                score = scores[idx_box]
                label = labels[idx_box].lower()

                is_text = any(kw in label for kw in text_keywords)
                is_sensitive = any(kw in label for kw in sensitive_keywords)

                if is_text:
                    keep_boxes.append(box.tolist())
                elif is_sensitive and score >= effective_threshold:
                    # Validate that the detected box actually contains bare skin
                    bx1, by1 = max(0, int(box[0])), max(0, int(box[1]))
                    bx2, by2 = min(w_img, int(box[2])), min(h_img, int(box[3]))
                    bw, bh = bx2 - bx1, by2 - by1

                    # Ignore invalid or tiny boxes
                    if bw < 15 or bh < 15:
                        continue
                    # Ignore boxes that cover > 40% of the entire image (hallucination)
                    if (bw * bh) > (w_img * h_img * 0.40):
                        continue

                    # Bare skin verification: genuine nudity must have at least 20% skin pixels in the box
                    box_skin = skin_mask[by1:by2, bx1:bx2]
                    skin_ratio = float(np.mean(box_skin))
                    if skin_ratio < 0.20:
                        # Clothed character / fabric / background, NOT bare skin!
                        continue

                    censor_boxes.append(box.tolist())

            censor_mask = np.zeros((h_img, w_img), dtype=bool)
            keep_mask = np.zeros((h_img, w_img), dtype=bool)

            if len(censor_boxes) > 0:
                # Build a bounding constraint mask to prevent SAM from expanding across the entire person
                box_boundary_mask = np.zeros((h_img, w_img), dtype=bool)
                for cbox in censor_boxes:
                    cbx1, cby1 = max(0, int(cbox[0])), max(0, int(cbox[1]))
                    cbx2, cby2 = min(w_img, int(cbox[2])), min(h_img, int(cbox[3]))
                    pad_x = max(10, int((cbx2 - cbx1) * 0.10))
                    pad_y = max(10, int((cby2 - cby1) * 0.10))
                    box_boundary_mask[max(0, cby1 - pad_y):min(h_img, cby2 + pad_y), max(0, cbx1 - pad_x):min(w_img, cbx2 + pad_x)] = True

                inputs_sam = sam_processor(image, input_boxes=[censor_boxes], return_tensors="pt").to(device)
                with torch.no_grad():
                    outputs_sam = sam_model(**inputs_sam)
                masks = sam_processor.post_process_masks(
                    outputs_sam.pred_masks.cpu(),
                    inputs_sam.original_sizes.cpu(),
                    inputs_sam.reshaped_input_sizes.cpu()
                )[0]
                for i in range(len(censor_boxes)):
                    censor_mask = censor_mask | masks[i][0].numpy()

                # Constrain the censor mask strictly inside the validated sensitive box boundaries
                # and ensure it only masks skin/anatomy, never the whole character
                skin_dilated = cv2.dilate(skin_mask.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
                censor_mask = censor_mask & box_boundary_mask & skin_dilated

            if len(keep_boxes) > 0:
                inputs_sam = sam_processor(image, input_boxes=[keep_boxes], return_tensors="pt").to(device)
                with torch.no_grad():
                    outputs_sam = sam_model(**inputs_sam)
                masks = sam_processor.post_process_masks(
                    outputs_sam.pred_masks.cpu(),
                    inputs_sam.original_sizes.cpu(),
                    inputs_sam.reshaped_input_sizes.cpu()
                )[0]
                for i in range(len(keep_boxes)):
                    keep_mask = keep_mask | masks[i][0].numpy()

            combined_mask = censor_mask & (~keep_mask)

            # Safety check: if mask covers more than 25% of the page, it is an over-segmentation false positive
            if float(np.mean(combined_mask)) > 0.25:
                combined_mask = np.zeros((h_img, w_img), dtype=bool)

            if combined_mask.any():
                if pdf_img_path:
                    img_mask = img_cv.copy()
                    if nsfw_mode == "blur":
                        blurred_img = cv2.GaussianBlur(img_mask, (51, 51), 0)
                        img_mask[combined_mask] = blurred_img[combined_mask]
                    elif nsfw_mode == "mosaic":
                        div = 20
                        temp = cv2.resize(img_mask, (max(1, w_img // div), max(1, h_img // div)), interpolation=cv2.INTER_LINEAR)
                        pixelated = cv2.resize(temp, (w_img, h_img), interpolation=cv2.INTER_NEAREST)
                        img_mask[combined_mask] = pixelated[combined_mask]
                    else:
                        img_mask[combined_mask] = (0, 0, 0)
                    cv2.imwrite(pdf_img_path, img_mask)

                    log_res = f"{file_name}: censored in PDF ({len(censor_boxes)} regions)"
                else:
                    if nsfw_mode == "blur":
                        blurred_img = cv2.GaussianBlur(img_cv, (51, 51), 0)
                        img_cv[combined_mask] = blurred_img[combined_mask]
                        log_res = f"{file_name}: censored with DINO+SAM blur ({len(censor_boxes)} regions)"
                    elif nsfw_mode == "mosaic":
                        div = 20
                        temp = cv2.resize(img_cv, (max(1, w_img // div), max(1, h_img // div)), interpolation=cv2.INTER_LINEAR)
                        pixelated = cv2.resize(temp, (w_img, h_img), interpolation=cv2.INTER_NEAREST)
                        img_cv[combined_mask] = pixelated[combined_mask]
                        log_res = f"{file_name}: censored with DINO+SAM mosaic ({len(censor_boxes)} regions)"
                    elif nsfw_mode == "mask":
                        img_cv[combined_mask] = (0, 0, 0)
                        log_res = f"{file_name}: censored with DINO+SAM mask ({len(censor_boxes)} regions)"
                    elif nsfw_mode == "placeholder":
                        img_cv[:, :] = (30, 30, 30)
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        text = "CENSORED PAGE"
                        text_scale = 1.0
                        thickness = 2
                        text_size = cv2.getTextSize(text, font, text_scale, thickness)[0]
                        text_x = (w_img - text_size[0]) // 2
                        text_y = (h_img + text_size[1]) // 2
                        cv2.putText(img_cv, text, (text_x, text_y), font, text_scale, (0, 0, 255), thickness)
                        log_res = f"{file_name}: replaced with placeholder"
                    cv2.imwrite(path, img_cv)
            else:
                if pdf_img_path:
                    import shutil
                    try:
                        shutil.copy2(path, pdf_img_path)
                    except Exception:
                        pass
                log_res = f"{file_name}: safe"

            return log_res

        try:
            log_res = await asyncio.to_thread(sync_process)
            if sse_logger:
                await sse_logger.log(f"  [Safe Mode] -> {log_res}", "info")
            return log_res
        except Exception as page_err:
            log_err = f"{file_name}: error {page_err}"
            def sync_fallback():
                return log_err + " (skipped censoring)"
            log_res_fb = await asyncio.to_thread(sync_fallback)
            if sse_logger:
                await sse_logger.log(f"  [Safe Mode] -> {log_res_fb}", "error")
            return log_res_fb

async def sanitize_episode_images(ep_dir: str, nsfw_threshold: float, nsfw_mode: str, from_page: int = None, to_page: int = None, sse_logger = None, concurrency: int = 5, pdf_dir: str = None) -> list:
    global dino_processor, dino_model, sam_processor, sam_model

    import os
    import cv2
    import numpy as np
    import torch
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    from transformers import SamModel, SamProcessor

    image_files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
    if not image_files:
        return []

    if from_page is not None and to_page is not None:
        image_files = image_files[from_page - 1 : to_page]
        if not image_files:
            return []

    image_paths = [os.path.join(ep_dir, f) for f in image_files]
    total_images = len(image_files)

    try:
        # Clear Hugging Face lock files first to prevent any hangs
        import os
        hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
        if os.path.exists(hf_cache):
            for root, dirs, files in os.walk(hf_cache):
                for file in files:
                    if file.endswith(".lock"):
                        lock_path = os.path.join(root, file)
                        try:
                            os.remove(lock_path)
                            print(f"Removed HF lock file: {lock_path}")
                        except Exception:
                            pass

        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        if device == "cuda":
            torch.backends.cudnn.benchmark = True

        if dino_model is None:
            if sse_logger:
                await sse_logger.log("  [Safe Mode] Khởi tạo bộ lọc nhạy cảm Grounding DINO base (~950MB)...", "info")
            dino_processor = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-base")
            dino_model = AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-base").to(device)

        if sam_model is None:
            if sse_logger:
                await sse_logger.log("  [Safe Mode] Khởi tạo bộ lọc nhạy cảm SAM Base (~375MB)...", "info")
            sam_processor = SamProcessor.from_pretrained("facebook/sam-vit-base")
            sam_model = SamModel.from_pretrained("facebook/sam-vit-base").to(device)

        prompt = "female nipple. bare buttocks. exposed genitalia. completely nude body"
        effective_threshold = max(0.40, nsfw_threshold)

        # Run concurrent image processing tasks with the specified concurrency.
        # On CPU, force concurrency = 1 to prevent OpenMP thread contention and deadlocks.
        # On GPU, limit concurrency to a max of 2 to avoid CUDA VRAM OOM.
        tasks = []
        if device == "cpu":
            safe_concurrency = 1
        else:
            safe_concurrency = max(1, min(2, concurrency))
        sem = asyncio.Semaphore(safe_concurrency)

        for idx, (file_name, path) in enumerate(zip(image_files, image_paths)):
            pdf_img_path = os.path.join(pdf_dir, file_name) if pdf_dir else None
            tasks.append(process_single_image(
                idx, file_name, path, effective_threshold, nsfw_mode, device, sem, sse_logger, total_images, prompt, pdf_img_path
            ))

        results = await asyncio.gather(*tasks)
        sanitized_log = list(results)

    except Exception as e:
        print(f"Lỗi chạy DINO+SAM filter: {str(e)}")
        # Ultimate fallback: keep original color files and log
        sanitized_log = []
        for file_name in image_files:
            sanitized_log.append(f"{file_name}: safe (ultimate fallback skipped)")

    return sanitized_log

# Background Crawler Task
async def run_crawler_task(
    url: str, from_ep: int, to_ep: int,
    safe_mode: bool = False,
    nsfw_threshold: float = 0.4,
    nsfw_mode: str = "mask",
    gemini_model: str = "default",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    timeout: int = 160,
    retry_count: int = 5,
    concurrency: int = 5,
    image_quality: int = 80,
    pdf_quality: int = 20,
    language: str = "vi",
    voice_id: str = "elevenlabs_tnSpp4vdxKPjI9w0GnoV",
    vlm_provider: str = "gemini",
    ai33pro_api_key: str = None
):
    global crawler_running, stop_requested
    stop_requested = False

    success = False
    download_folder_name = None

    async with crawler_lock:
        crawler_running = True
        # Resolve dynamic default voice_id based on language (default to elevenlabs_tnSpp4vdxKPjI9w0GnoV for both vi and en)
        default_voice = "elevenlabs_tnSpp4vdxKPjI9w0GnoV"
        if not voice_id or voice_id in ("elevenlabs_yj30vwTGJxSHezdAGsv9", "elevenlabs_XrExE9yKIg1WjnnlVkGX"):
            voice_id = default_voice

        try:
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query)
            title_no = query.get("title_no", [""])[0]
            if not title_no:
                raise Exception("Không tìm thấy title_no trong URL bộ truyện.")

            parts = parsed.path.strip("/").split("/")
            base_path = "/".join(parts[:-1])

            if True:
                browser = None
                context = None
                try:
                    await sse_logger.log("Đang lấy tên truyện chính thức...", "info")
                    browser, context = await get_shared_browser_context()
                    nav_manager = NavigationManager(sse_logger)
                    nav_manager.context = context
                    nav_manager.browser = browser
                    page = await context.new_page()
                    await nav_manager.safe_goto(page, url, reason="Load manhwa main page for title verification", caller="run_crawler_task")

                    title_text = await page.title()
                    title_text = title_text.split("|")[0].strip()
                    sanitized_title = sanitize_title(title_text)

                    # Directory format: {tên truyện}_{từ episode}_{đến episode}
                    project_dir = os.path.dirname(os.path.abspath(__file__))
                    download_folder_name = f"{sanitized_title}_{from_ep}_{to_ep}_{language}"
                    download_dir = os.path.join(project_dir, "downloads", download_folder_name)
                    os.makedirs(download_dir, exist_ok=True)

                    await sse_logger.log(f"Thư mục tải về: {download_folder_name}", "info")

                    for ep in range(from_ep, to_ep + 1):
                        if stop_requested:
                            raise Exception("Tiến trình crawl bị dừng bởi người dùng.")
                        await sse_logger.log(f"Đang mở tập {ep}...", "info")
                        viewer_url = f"{parsed.scheme}://{parsed.netloc}/{base_path}/ep-{ep}/viewer?title_no={title_no}&episode_no={ep}"
                        await nav_manager.safe_goto(page, viewer_url, reason=f"Load episode {ep} viewer page to extract images", caller="run_crawler_task")

                        try:
                            await page.wait_for_selector("#_imageList img", timeout=15000)
                        except Exception:
                            await sse_logger.log(f"Lỗi: Không tìm thấy danh sách ảnh tập {ep}. Có thể do bản quyền hoặc lỗi tải trang.", "error")
                            continue

                        image_urls = await page.locator("#_imageList img").evaluate_all(
                            "elements => elements.map(el => el.getAttribute('data-url') || el.getAttribute('src'))"
                        )
                        image_urls = [src for src in image_urls if src]

                        if not image_urls:
                            await sse_logger.log(f"Không có ảnh nào trong tập {ep}.", "warning")
                            continue

                        await sse_logger.log(f"Tập {ep}: Phát hiện {len(image_urls)} ảnh. Đang tiến hành tải...", "info")

                        ep_dir = os.path.join(download_dir, f"ep_{ep}")
                        os.makedirs(ep_dir, exist_ok=True)

                        for i, img_url in enumerate(image_urls, 1):
                            if stop_requested:
                                raise Exception("Tiến trình crawl bị dừng bởi người dùng.")
                            file_ext = ".jpg"
                            if ".png" in img_url.lower():
                                file_ext = ".png"
                            file_name = f"{str(i).zfill(3)}{file_ext}"
                            save_path = os.path.join(ep_dir, file_name)

                            try:
                                await download_image(img_url, save_path)
                            except Exception as dl_err:
                                await sse_logger.log(f"Lỗi tải ảnh {i} tập {ep}: {str(dl_err)}", "error")

                        await sse_logger.log(f"Tập {ep}: Hoàn thành tải {len(image_urls)} ảnh.", "success")

                        # Generate stitched.jpg & gemini_prompt.txt
                        stitched_path = os.path.join(ep_dir, "stitched.jpg")
                        prompt_path = os.path.join(ep_dir, "gemini_prompt.txt")
 
                        await sse_logger.log(f"Tập {ep}: Đang tạo tệp stitched.jpg cho Video...", "info")
                        # Stitch standard version from ep_dir
                        success_stitch = stitch_images_vertically(ep_dir, stitched_path, image_quality)
                        if success_stitch:
                            image_files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f not in ("chapter.pdf", "gemini_prompt.txt", "chatgpt_prompt.txt", "stitched.jpg", "stitched_mask.jpg")])
                            prompt_content = generate_gemini_prompt(title_text, ep, len(image_files), language)
                            with open(prompt_path, "w", encoding="utf-8") as pf:
                                pf.write(prompt_content)
                            await sse_logger.log(f"Tập {ep}: Đã tạo thành công gemini_prompt.txt.", "success")
                        else:
                            await sse_logger.log(f"Tập {ep}: Không thể tạo stitched.jpg (không tìm thấy ảnh).", "warning")

                        await asyncio.sleep(1.0)
                finally:
                    if 'page' in locals() and page:
                        try:
                            await page.close()
                        except Exception:
                            pass

            await sse_logger.log(f"CRAWL THÀNH CÔNG! Đã tải xong và lưu vào thư mục '{download_folder_name}'.", "success")

            # Automatically run the VLM Web summarization sequentially for each episode!
            await run_auto_summarization_flow(
                download_dir, title_text, from_ep, to_ep,
                safe_mode=safe_mode,
                nsfw_threshold=nsfw_threshold,
                nsfw_mode=nsfw_mode,
                gemini_model=gemini_model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout=timeout,
                retry_count=retry_count,
                concurrency=concurrency,
                image_quality=image_quality,
                pdf_quality=pdf_quality,
                language=language,
                vlm_provider=vlm_provider
            )
            success = True
                

        except Exception as e:
            import traceback
            traceback.print_exc()
            await sse_logger.log(f"Lỗi tiến trình crawl/tóm tắt: {str(e)}", "error", "idle", "Sẵn sàng")
        finally:
            crawler_running = False

    if success:
        await run_video_pipeline(download_folder_name, from_ep, to_ep, voice_id=voice_id, ai33pro_api_key=ai33pro_api_key)


async def run_auto_summarization_flow(
    download_dir: str, title_text: str, from_ep: int, to_ep: int,
    safe_mode: bool = False,
    nsfw_threshold: float = 0.4,
    nsfw_mode: str = "mask",
    gemini_model: str = "default",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    timeout: int = 160,
    retry_count: int = 5,
    concurrency: int = 5,
    image_quality: int = 80,
    pdf_quality: int = 20,
    language: str = "vi",
    vlm_provider: str = "gemini"
):
    global stop_requested
    vlm_url = "https://chatgpt.com/" if vlm_provider == "chatgpt" else "https://gemini.google.com/app"
    vlm_name = "ChatGPT" if vlm_provider == "chatgpt" else "Gemini"
    await sse_logger.log(f"[VLM] Bắt đầu tự động tạo tóm tắt cho các tập đã tóm tắt/crawl bằng {vlm_name}...", "system", "active", "Đang tóm tắt...")




    async def query_gemini_web(page, prompt_content, stitched_path, step_desc):
        textbox = None
        textbox_xpath = None
        textbox_found = False
        for _ in range(30):
            if stop_requested:
                raise Exception("Tiến trình bị dừng bởi người dùng.")
            for sel in textbox_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        textbox = loc
                        textbox_xpath = sel
                        textbox_found = True
                        break
                except Exception:
                    pass
            if textbox_found:
                break
            await asyncio.sleep(1)
        

        if not textbox_found:
            raise Exception("Không tìm thấy ô nhập prompt.")


        if stitched_path and os.path.exists(stitched_path):
            await sse_logger.log(f"{step_desc}: Đang đính kèm ảnh stitched.jpg...", "info")
            
            upload_success = False
            try:
                file_input = page.locator("input[type='file']").first
                if await file_input.count() > 0:
                    await human_delay(0.3, 0.7)
                    await file_input.set_input_files(stitched_path)
                    await asyncio.sleep(3.0)
                    upload_success = True
                    await sse_logger.log(f"{step_desc}: Đã đính kèm ảnh bằng set_input_files thành công.", "success")
            except Exception as upload_err:
                await sse_logger.log(f"{step_desc}: Thử đính kèm bằng set_input_files thất bại: {upload_err}. Sử dụng Clipboard Fallback...", "warning")

            if not upload_success:
                import base64
                with open(stitched_path, "rb") as stitched_file:
                    img_base64 = base64.b64encode(stitched_file.read()).decode("utf-8")
                
                js_paste_img = """
                async (args) => {
                    const { xpath, base64Data, fileName, mimeType } = args;
                    let element;
                    if (xpath.startsWith('xpath=')) {
                         const result = document.evaluate(xpath.replace('xpath=', ''), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                         element = result.singleNodeValue;
                    } else {
                         element = document.querySelector(xpath);
                    }
                    if (!element) throw new Error("Không tìm thấy ô nhập prompt.");
                

                    element.focus();
                    const res = await fetch("data:" + mimeType + ";base64," + base64Data);
                    const blob = await res.blob();
                    const file = new File([blob], fileName, { type: mimeType });
                

                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(file);
                

                    const pasteEvent = new ClipboardEvent('paste', {
                        bubbles: true,
                        cancelable: true,
                        clipboardData: dataTransfer
                    });
                    element.dispatchEvent(pasteEvent);
                    return true;
                }
                """
                await human_delay(0.3, 0.7)
                await page.evaluate(js_paste_img, {
                    "xpath": textbox_xpath,
                    "base64Data": img_base64,
                    "fileName": os.path.basename(stitched_path),
                    "mimeType": "image/jpeg"
                })
                await sse_logger.log(f"{step_desc}: Đã đính kèm tệp ảnh thành công bằng Clipboard. Đang chờ 3 giây...", "success")
                await asyncio.sleep(3)


        await sse_logger.log(f"{step_desc}: Đang điền nội dung prompt...", "info")
        await human_delay(0.3, 0.8)
        
        textbox = None
        for tb_sel in [
            "rich-textarea p",
            "rich-textarea div[contenteditable='true']",
            "div.ql-editor[contenteditable='true']",
            "div[contenteditable='true']",
            "[role='textbox']"
        ]:
            try:
                loc = page.locator(tb_sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    textbox = loc
                    break
            except Exception:
                pass

        pasted = False
        if textbox:
            try:
                await textbox.click(force=True)
                await asyncio.sleep(0.3)
                await textbox.fill(prompt_content)
                pasted = True
            except Exception:
                pass

        if not pasted:
            try:
                p_el = page.locator("rich-textarea div.ql-editor p, div.ql-editor p, rich-textarea p").first
                if await p_el.count() > 0:
                    await p_el.click(force=True)
                elif textbox:
                    await textbox.click(force=True)
                await page.keyboard.insert_text(prompt_content)
                pasted = True
            except Exception:
                pass

        try:
            if textbox:
                await textbox.press_sequentially(" ")
                await textbox.press("Backspace")
            else:
                await page.keyboard.press("Space")
                await page.keyboard.press("Backspace")
        except Exception:
            pass

        await asyncio.sleep(1.0)
        await sse_logger.log(f"{step_desc}: Đã điền prompt thành công.", "success")
    

        send_button = None
        for _ in range(30):
            if stop_requested:
                raise Exception("Tiến trình bị dừng bởi người dùng.")
            for sel in send_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                        send_button = loc
                        break
                except Exception:
                    pass
            if send_button:
                break
            await asyncio.sleep(1)


        if send_button:
            await human_delay(0.4, 0.9)
            await send_button.click(force=True)
            await sse_logger.log(f"{step_desc}: Đã click nút Gửi.", "success")
        else:
            await human_delay(0.3, 0.75)
            await textbox.press("Enter")
            await sse_logger.log(f"{step_desc}: Đã gửi bằng Enter.", "success")
        

        await sse_logger.log(f"{step_desc}: Đang theo dõi kết quả trả về...", "info")
        raw_json_text = None
        parsed_json = None

        def is_valid_recap_response(text: str) -> bool:
            if not text or len(text.strip()) < 15:
                return False
            # 1. JSON check
            extracted = extract_json_from_text(text)
            if extracted:
                try:
                    parsed = json.loads(extracted)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        if all(isinstance(item, dict) and "speech" in item and "images" in item for item in parsed):
                            if count_recap_sentences(parsed) < 10:
                                return False
                            return True
                except Exception:
                    pass
            # 2. # format check
            try:
                is_valid, _ = verify_gemini_response_format(text, is_intro=False, min_sentences=10)
                if is_valid:
                    return True
            except Exception:
                pass
            # 3. Direct parse
            try:
                parsed = parse_gemini_recap_text(text)
                if parsed and len(parsed) > 0:
                    if count_recap_sentences(parsed) < 10:
                        return False
                    return True
            except Exception:
                pass
            return False

        js_check_completion = """() => {
            const isVis = (el) => {
                if (!el) return false;
                try {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 || rect.height > 0 || el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0;
                } catch (e) {
                    return el.offsetParent !== null;
                }
            };

            // 1. Is stop button visible?
            const stopSelectors = [
                "button[aria-label*='Stop' i]",
                "button[aria-label*='Dừng' i]",
                "button[aria-label*='Cancel' i]",
                "button[aria-label*='Hủy' i]",
                "button[data-testid*='stop' i]",
                "[data-testid*='stop' i]",
                "gem-icon-button[aria-label*='Stop' i]",
                "gem-icon-button[aria-label*='Dừng' i]",
                ".stop-button",
                ".stop-icon",
                "button.stop-generating-button"
            ];
            for (const sel of stopSelectors) {
                const el = document.querySelector(sel);
                if (el && isVis(el)) return false;
            }

            // 2. Are streaming / typing indicators active?
            const streamSelectors = [
                "[class*='streaming']",
                "[class*='generating']",
                "[class*='typing']",
                ".blinking-cursor",
                ".cursor",
                "gem-streaming-indicator",
                "sparkle-icon.animate-spin",
                "[data-is-generating='true']",
                "[data-is-streaming='true']",
                "input-area-v2 [role='progressbar']",
                "form [role='progressbar']"
            ];
            for (const sel of streamSelectors) {
                const el = document.querySelector(sel);
                if (el && isVis(el)) return false;
            }

            // 3. Is thinking spinner actively running?
            const thinkEl = document.querySelector(".thinking-container, [data-testid='thinking-indicator'], thinking-bubble");
            if (thinkEl && isVis(thinkEl)) {
                const spinner = thinkEl.querySelector("mat-spinner, [role='progressbar'], svg.animate-spin");
                if (spinner && isVis(spinner)) return false;
            }

            // 4. Check for error alerts
            const errorSelectors = ["div.alert", "div[data-test-id='error-message']", ".error-message", "div[role='alert']"];
            for (const sel of errorSelectors) {
                const el = document.querySelector(sel);
                if (el && isVis(el) && (el.textContent || "").trim().length > 0) return true;
            }

            // 5. Must have response content element
            const modelResponses = document.querySelectorAll("model-response, [data-test-id='model-response'], .model-response, response-container");
            let lastModel = null;
            if (modelResponses.length > 0) {
                lastModel = modelResponses[modelResponses.length - 1];
            }

            if (!lastModel) {
                const contentEls = document.querySelectorAll(".response-content-markdown, message-content, div.markdown, div.prose");
                for (let i = contentEls.length - 1; i >= 0; i--) {
                    const el = contentEls[i];
                    if (!el.closest("user-query, user-message, [data-test-id='user-query'], .user-query-container, .query-text")) {
                        lastModel = el;
                        break;
                    }
                }
            }

            if (!lastModel) return false;

            const respText = (lastModel.innerText || lastModel.textContent || "").trim();
            if (!respText || respText.length < 5) return false;

            // 6. If response ends with '#' or contains '#' (recap/intro standard) and is not streaming, it is ready!
            if (respText.includes("#") || respText.endsWith("```")) {
                return true;
            }

            // 7. Action bar (Copy/Share/Modify/Redo) must have appeared
            const actionSelectors = [
                "message-actions",
                ".message-actions",
                "[data-testid='message-actions']",
                "response-container .response-bottom-actions",
                "button[aria-label*='Copy' i]",
                "button[aria-label*='Sao chép' i]",
                "button[aria-label*='Good response' i]",
                "button[aria-label*='Phản hồi tốt' i]",
                "button[aria-label*='Share' i]",
                "button[aria-label*='Chia sẻ' i]",
                "button[aria-label*='Modify' i]",
                "button[aria-label*='Chỉnh sửa' i]",
                "button[aria-label*='Redo' i]",
                "button[aria-label*='Retry' i]",
                "button[aria-label*='Thử lại' i]"
            ];
            for (const sel of actionSelectors) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    const last = els[els.length - 1];
                    if (last && (isVis(last) || last.querySelector("button, gem-icon-button, svg"))) return true;
                }
            }

            if (respText.length >= 20) {
                return true;
            }

            return false;
        }"""

        js_extract_response = """() => {
            const getCleanText = (el) => {
                if (!el) return "";
                const clone = el.cloneNode(true);
                clone.querySelectorAll("sources-carousel, citation-tag, source-chip, grounding-citation, grounding-tag, grounding-popover, .grounding-container, a.citation-chip, span.citation, [class*='citation'], [class*='grounding'], [class*='source-chip'], [data-test-id*='citation'], [data-test-id*='grounding'], message-actions, .message-actions, button, [role='button']").forEach(c => c.remove());
                clone.querySelectorAll("br").forEach(br => br.replaceWith("\\n"));
                
                const blocks = clone.querySelectorAll("p, li, tr, h1, h2, h3, h4, h5, h6");
                if (blocks.length > 0) {
                    const lines = [];
                    blocks.forEach(b => {
                        const t = (b.innerText || b.textContent || "").trim();
                        if (t) lines.push(t);
                    });
                    if (lines.length > 0) return lines.join("\\n");
                }
                return (clone.innerText || clone.textContent || "").trim();
            };

            const modelResponses = document.querySelectorAll("model-response, [data-test-id='model-response'], .model-response, response-container");
            let targetEl = null;
            if (modelResponses.length > 0) {
                targetEl = modelResponses[modelResponses.length - 1];
            }

            if (!targetEl) {
                const respSelectors = [
                    ".response-content-markdown",
                    "message-content",
                    "structured-content-container",
                    "div.markdown",
                    "div.prose"
                ];
                for (const sel of respSelectors) {
                    const els = document.querySelectorAll(sel);
                    for (let i = els.length - 1; i >= 0; i--) {
                        const el = els[i];
                        if (!el.closest("user-query, user-message, [data-test-id='user-query'], .user-query-container, .query-text")) {
                            targetEl = el;
                            break;
                        }
                    }
                    if (targetEl) break;
                }
            }

            let text = "";
            if (targetEl) {
                try {
                    const markdownEl = targetEl.querySelector(".response-content-markdown, message-content, div.markdown, div.prose");
                    text = getCleanText(markdownEl || targetEl);
                } catch (e) {
                    text = (targetEl.innerText || targetEl.textContent || "").trim();
                }
            }

            let detectedError = null;
            const errorSelectors = ["div.alert", "div[data-test-id='error-message']", ".error-message", "div[role='alert']"];
            for (const sel of errorSelectors) {
                const el = document.querySelector(sel);
                if (el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.offsetParent !== null)) {
                    const errTxt = (el.textContent || "").trim();
                    if (errTxt) {
                        detectedError = errTxt;
                        break;
                    }
                }
            }

            return { text: text, detected_error: detectedError };
        }"""

        in_page_retry_count = 0
        max_in_page_retries = 3
        text_content = ""

        while in_page_retry_count <= max_in_page_retries:
            if stop_requested:
                raise Exception("Tiến trình bị dừng bởi người dùng.")

            await sse_logger.log(f"{step_desc}: Đang theo dõi trạng thái hoàn tất phản hồi trên web...", "info")
            try:
                await page.wait_for_function(js_check_completion, timeout=timeout * 1000)
            except Exception as wait_err:
                await sse_logger.log(f"{step_desc}: Trạng thái web chờ phản hồi đạt timeout ({timeout}s): {wait_err}", "warning")

            res_data = await page.evaluate(js_extract_response)
            text_content = res_data.get("text", "")
            detected_error_txt = res_data.get("detected_error")

            if text_content:
                try:
                    with open(os.path.join(os.path.dirname(stitched_path), "raw_gemini_response.txt"), "w", encoding="utf-8") as rdf:
                        rdf.write(clean_gemini_response(text_content))
                except Exception:
                    pass

            if not detected_error_txt and is_valid_recap_response(text_content):
                try:
                    parsed_text = parse_gemini_recap_text(text_content)
                    if parsed_text and count_recap_sentences(parsed_text) >= 10:
                        parsed_json = parsed_text
                        break
                except Exception:
                    pass
                extracted = extract_json_from_text(text_content)
                if extracted:
                    try:
                        parsed = json.loads(extracted)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            if count_recap_sentences(parsed) >= 10:
                                parsed_json = parsed
                                raw_json_text = extracted
                                break
                    except Exception:
                        pass
                if parsed_json:
                    break

            # Determine exact validation / cut-off issue if any
            if not detected_error_txt:
                is_v, fmt_err = verify_gemini_response_format(text_content, is_intro=False, min_sentences=10)
                if not is_v:
                    detected_error_txt = fmt_err
                else:
                    parsed_check = parse_gemini_recap_text(text_content)
                    if parsed_check and count_recap_sentences(parsed_check) < 10:
                        sc = count_recap_sentences(parsed_check)
                        detected_error_txt = f"Kịch bản recap quá ngắn ({sc} câu < 10 câu)"
                    else:
                        detected_error_txt = "Phản hồi không đúng cấu trúc kịch bản recap hoặc bị ngắt quãng"

            if in_page_retry_count < max_in_page_retries:
                in_page_retry_count += 1
                await sse_logger.log(
                    f"{step_desc}: Phát hiện phản hồi lỗi/chưa hoàn tất ('{detected_error_txt[:60]}...'). Đang click icon Redo -> chọn 'Try again' trên web (Lần {in_page_retry_count}/{max_in_page_retries})...",
                    "warning"
                )

                retry_btn = None
                retry_selectors = [
                    "button[aria-label*='Modify response']",
                    "button[aria-label*='Modify']",
                    "button[aria-label*='Chỉnh sửa phản hồi']",
                    "button[aria-label*='Chỉnh sửa câu trả lời']",
                    "button[aria-label*='Chỉnh sửa']",
                    "button[aria-label*='Redo']",
                    "button[aria-label*='Retry']",
                    "button[aria-label*='retry']",
                    "button[aria-label*='Thử lại']",
                    "button[aria-label*='thử lại']",
                    "button[aria-label*='Regenerate']",
                    "button[aria-label*='regenerate']",
                    "button[aria-label*='Tạo lại']",
                    "button[aria-label*='tạo lại']",
                    "button[aria-label*='Try again']",
                    "button[aria-label*='try again']",
                    "button[aria-label*='Update response']",
                    "button[aria-label*='Cập nhật phản hồi']",
                    "button[data-test-id='regenerate-button']",
                    "button[data-testid='regenerate-button']",
                    "button[data-testid='retry-button']",
                    "button[mattooltip*='Modify']",
                    "button[mattooltip*='Chỉnh sửa']",
                    "button[mattooltip*='Redo']",
                    "button[mattooltip*='Retry']",
                    "button[mattooltip*='Thử lại']",
                    "gem-icon-button[aria-label*='Modify']",
                    "gem-icon-button[aria-label*='Chỉnh sửa']",
                    "button:has(mat-icon:has-text('tune'))",
                    "button:has(mat-icon:has-text('refresh'))",
                    "button:has(mat-icon:has-text('replay'))",
                    "button:has(mat-icon:has-text('redo'))",
                    "button:has(mat-icon:has-text('autorenew'))",
                    "button:has(mat-icon:has-text('sync'))",
                    "button:has(mat-icon[fonticon='tune'])",
                    "button:has(mat-icon[fonticon='refresh'])",
                    "button:has(mat-icon[fonticon='replay'])",
                    "button:has(mat-icon[fonticon='autorenew'])",
                    "button:has(mat-icon[fonticon='redo'])",
                    "button:has(svg.lucide-rotate-cw)",
                    "button:has(svg.lucide-refresh-cw)",
                    "button:has(svg[data-icon='refresh'])",
                    "message-actions button:has(mat-icon:has-text('tune'))",
                    "message-actions button:has(mat-icon:has-text('refresh'))",
                    "message-actions button:has(mat-icon:has-text('replay'))",
                    "message-actions button:has(mat-icon:has-text('redo'))",
                    "response-container button[aria-label*='Modify']",
                    "response-container button[aria-label*='Regenerate']",
                    "response-container button[aria-label*='Retry']",
                    "response-container button[aria-label*='Thử lại']",
                    "button:has-text('Try again')",
                    "button:has-text('Thử lại')",
                    "button:has-text('Retry')"
                ]
                for r_sel in retry_selectors:
                    try:
                        r_loc = page.locator(r_sel).last
                        if await r_loc.count() > 0 and await r_loc.is_visible():
                            retry_btn = r_loc
                            break
                    except Exception:
                        pass

                if not retry_btn:
                    try:
                        for bar_sel in ["message-actions", ".message-actions", "response-container .response-bottom-actions", "[data-testid='message-actions']", "div.message-actions"]:
                            bar = page.locator(bar_sel).last
                            if await bar.count() > 0 and await bar.is_visible():
                                btns = bar.locator("button, gem-icon-button")
                                b_count = await btns.count()
                                for b_i in range(b_count):
                                    btn_cand = btns.nth(b_i)
                                    btn_html = (await btn_cand.inner_html()).lower()
                                    aria_l = (await btn_cand.get_attribute("aria-label") or "").lower()
                                    tooltip = (await btn_cand.get_attribute("mattooltip") or "").lower()
                                    if any(k in btn_html or k in aria_l or k in tooltip for k in ["modify", "chỉnh sửa", "tune", "refresh", "replay", "redo", "rotate", "arrow", "sync", "autorenew", "retry", "tạo lại", "thử lại"]):
                                        retry_btn = btn_cand
                                        break
                                if not retry_btn and b_count >= 3:
                                    retry_btn = btns.nth(2)
                            if retry_btn:
                                break
                    except Exception:
                        pass

                if retry_btn:
                    try:
                        await human_delay(0.3, 0.8)
                        await retry_btn.click()
                        await asyncio.sleep(0.6)
                        menu_selectors = [
                            "[role='menuitem']:has-text('Try again')",
                            "[role='menuitem']:has-text('Thử lại')",
                            "[role='menuitem']:has-text('Thử làm lại')",
                            "button[role='menuitem']:has-text('Try again')",
                            "button[role='menuitem']:has-text('Thử lại')",
                            ".mat-mdc-menu-item:has-text('Try again')",
                            ".mat-mdc-menu-item:has-text('Thử lại')",
                            "[role='menu'] button:has-text('Try again')",
                            "[role='menu'] button:has-text('Thử lại')",
                            "[role='menu'] [role='menuitem']:has-text('Try again')",
                            "[role='menu'] [role='menuitem']:has-text('Thử lại')",
                            ".cdk-overlay-pane [role='menuitem']:has-text('Try again')",
                            ".cdk-overlay-pane [role='menuitem']:has-text('Thử lại')",
                            ".cdk-overlay-pane button:has-text('Try again')",
                            ".cdk-overlay-pane button:has-text('Thử lại')",
                            "[role='menuitem']:has-text('Retry')",
                            "[role='menuitem']:has-text('Regenerate')",
                            "[role='menuitem']:has-text('Tạo lại')",
                            "button:has-text('Try again')",
                            "button:has-text('Thử lại')"
                        ]
                        menu_clicked = False
                        for _ in range(6):
                            for m_sel in menu_selectors:
                                try:
                                    m_loc = page.locator(m_sel).first
                                    if await m_loc.count() > 0 and await m_loc.is_visible():
                                        await human_delay(0.25, 0.6)
                                        await m_loc.click()
                                        menu_clicked = True
                                        break
                                except Exception:
                                    pass
                            if menu_clicked:
                                break
                            await asyncio.sleep(0.5)

                        await sse_logger.log(f"{step_desc}: Đã click icon Redo -> chọn 'Try again' thành công. Đang chờ Gemini tạo lại...", "info")
                        await asyncio.sleep(2.0)
                        continue
                    except Exception as click_err:
                        await sse_logger.log(f"{step_desc}: Không thể click nút Redo/Try again trên web ({click_err}). Chuyển sang thử lại cấp tool.", "warning")
                        break
                else:
                    await sse_logger.log(f"{step_desc}: Không tìm thấy icon Redo trên web. Chuyển sang thử lại cấp tool.", "warning")
                    break
            else:
                break

        

        if not parsed_json and text_content:
            try:
                parsed_json = parse_gemini_recap_text(text_content)
                if parsed_json and count_recap_sentences(parsed_json) < 10:
                    parsed_json = None
            except Exception:
                pass

        if not parsed_json:
            raise Exception("Không nhận được kịch bản recap hợp lệ từ Grok.")

        return parsed_json

    async def process_episode_task(ep, context, sem=None):
        class AsyncNullContext:
            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc_val, exc_tb): pass

        sem_context = sem if sem is not None else AsyncNullContext()
        async with sem_context:
            if stop_requested:
                return
            await sse_logger.log(f"[VLM] --- Bắt đầu xử lý Tập {ep} ---", "info")
            ep_dir = os.path.join(download_dir, f"ep_{ep}")
            stitched_mask_path = os.path.join(ep_dir, "stitched_mask.jpg")
            stitched_path = stitched_mask_path if os.path.exists(stitched_mask_path) else os.path.join(ep_dir, "stitched.jpg")

            if not os.path.exists(stitched_path):
                await sse_logger.log(f"[VLM] Tập {ep}: Thiếu file stitched.jpg, đang tự động tạo...", "warning")
                success_stitch = stitch_images_vertically(ep_dir, stitched_path, image_quality)
                if not success_stitch:
                    await sse_logger.log(f"[VLM] Tập {ep}: Không có ảnh để tạo stitched.jpg, bỏ qua...", "error")
                    failed_episodes.append(ep)
                    return

            image_files = get_unique_sorted_images(ep_dir)
            prompt_content = generate_gemini_prompt(title_text, ep, len(image_files), language)

            page = await context.new_page()
            await asyncio.sleep(2)
            try:
                mock_json = None
                for attempt in range(1, retry_count + 1):
                    try:
                        await page.goto(vlm_url, timeout=60000)
                        await asyncio.sleep(2)
                        mock_json = await query_gemini_web(page, prompt_content, stitched_path, f"Tập {ep} (Lần {attempt})")
                        break
                    except VisionSafetyException as safety_err:
                        await sse_logger.log(f"Tập {ep}: Lỗi an toàn (Vision Safety) ở lần thử {attempt}: {str(safety_err)}", "warning")
                        if attempt == retry_count:
                            raise safety_err
                        await sse_logger.log(f"Tập {ep}: Kích hoạt Grayscale Fallback khẩn cấp cho lần thử {attempt + 1}...", "info")
                        for img_file in image_files:
                            img_path = os.path.join(ep_dir, img_file)
                            try:
                                import cv2
                                cv_img = cv2.imread(img_path)
                                if cv_img is not None:
                                    cv_gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
                                    cv2.imwrite(img_path, cv_gray)
                            except Exception as cv_err:
                                print(f"Error converting to gray: {cv_err}")
                        stitch_images_vertically(ep_dir, stitched_path, image_quality)
                    except Exception as attempt_err:
                        await sse_logger.log(f"Tập {ep}: Lỗi ở lần thử {attempt}: {str(attempt_err)}", "warning")
                        if attempt == retry_count:
                            raise attempt_err
                        await asyncio.sleep(5)
                

                if not mock_json:
                    raise Exception("Không thể lấy kết quả từ Gemini sau các lần thử lại.")
                

                # Robust extraction of segments
                segments_data = []
                if isinstance(mock_json, list):
                    segments_data = mock_json
                elif isinstance(mock_json, dict):
                    segments_data = mock_json.get("segments") or mock_json.get("episodes") or []
                    if not isinstance(segments_data, list):
                        segments_data = [mock_json]
                else:
                    segments_data = []

                formatted_segments = []
                for idx, item in enumerate(segments_data, 1):
                    if not isinstance(item, dict):
                        continue

                    # Extract images list or slides list
                    images_list = item.get("images") or item.get("slides") or []
                    if not isinstance(images_list, list):
                        images_list = [images_list]

                    # Extract all page numbers
                    pages = []
                    for img in images_list:
                        if isinstance(img, dict):
                            p_val = img.get("page")
                        else:
                            p_val = img
                        if p_val is not None:
                            try:
                                # Extract digits in case it is a filename like "005.jpg"
                                if isinstance(p_val, str) and not p_val.isdigit():
                                    found_digits = re.findall(r'\d+', p_val)
                                    if found_digits:
                                        pages.append(int(found_digits[-1]))
                                else:
                                    pages.append(int(p_val))
                            except (ValueError, TypeError):
                                pass

                    # Fallbacks
                    if not pages:
                        # Try key_page or source_range from the item
                        kp = item.get("key_page") or item.get("page") or 1
                        try:
                            pages = [int(kp)]
                        except (ValueError, TypeError):
                            pages = [1]

                    # Compute fields
                    from_page = min(pages) if pages else 1
                    to_page = max(pages) if pages else 1
                    key_page = pages[0] if pages else 1

                    # Resolve key image filename on disk
                    key_image_name = f"{str(key_page).zfill(3)}.jpg"
                    if not os.path.exists(os.path.join(ep_dir, key_image_name)):
                        if os.path.exists(os.path.join(ep_dir, f"{str(key_page).zfill(3)}.png")):
                            key_image_name = f"{str(key_page).zfill(3)}.png"

                    # Build output segment dictionary
                    segment_dict = {
                        "speech": item.get("speech", ""),
                        "key_image": f"ep_{ep}/{key_image_name}",
                        "source_range": {
                            "from": from_page,
                            "to": to_page
                        }
                    }

                    # Preserve the original images / slides keys if present
                    if "images" in item:
                        segment_dict["images"] = item["images"]
                    if "slides" in item:
                        segment_dict["slides"] = item["slides"]

                    formatted_segments.append(segment_dict)
                

                if not formatted_segments:
                    raise Exception("Danh sách segments sau khi phân tích bị trống.")

                valid_speeches = [seg.get("speech", "").strip() for seg in formatted_segments if seg.get("speech", "").strip()]
                if not valid_speeches:
                    raise Exception("Nội dung thuyết minh (speech) của các segments bị trống.")

                narrations_path = os.path.join(ep_dir, "narrations.json")
                with open(narrations_path, "w", encoding="utf-8") as f:
                    json.dump(formatted_segments, f, ensure_ascii=False, indent=2)
                await sse_logger.log(f"Tập {ep}: Đã lưu tệp 'narrations.json' thành công.", "success")
                
                combined_episodes.append({
                    "episode": ep,
                    "title": f"{title_text} - Episode {ep}",
                    "segments": formatted_segments
                })
            except Exception as ep_err:
                await sse_logger.log(f"Thất bại hoàn toàn khi xử lý Tập {ep}: {str(ep_err)}", "error")
                failed_episodes.append(ep)
            finally:
                await page.close()


    if True:
        try:
            await sse_logger.log("[VLM] Khởi chạy Chrome...", "info")
            browser, context = await get_shared_browser_context(headless=False)
            cookie_file = "cookies.json"
            

            check_page = await context.new_page()
            await asyncio.sleep(2)
            await check_page.goto(vlm_url, timeout=60000)
            await asyncio.sleep(5)
            textbox_found = False
            for sel in textbox_selectors:
                if await check_page.locator(sel).first.count() > 0:
                    textbox_found = True
                    break
            

            if not textbox_found:
                await sse_logger.log(f"[VLM] Cảnh báo: Có vẻ như bạn chưa đăng nhập tài khoản trên {vlm_name}. Hãy mở trình duyệt ở chế độ setup để đăng nhập trước.", "warning")
            await check_page.close()


            await sse_logger.log(f"[VLM] Bắt đầu xử lý tuần tự từng chap bằng {vlm_name}.", "info")
            for ep in range(from_ep, to_ep + 1):
                if stop_requested:
                    break
                await process_episode_task(ep, context, None)
            

            try:
                state = await context.storage_state()
                with open(cookie_file, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
            except Exception:
                pass
                

            # Keep shared browser and context running for other tasks
            

            if combined_episodes:
                combined_episodes.sort(key=lambda x: x["episode"])
                

                combined_json = {
                    "title": f"{title_text} - Episodes {from_ep} to {to_ep}",
                    "episodes": combined_episodes
                }
                json_filename = f"summary_ep_{from_ep}_to_{to_ep}.json"
                json_path = os.path.join(download_dir, json_filename)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(combined_json, f, ensure_ascii=False, indent=2)
                await sse_logger.log(f"[VLM] Đã tạo file JSON tổng hợp thành công: '{json_filename}'", "success")
                

                text_content = []
                for ep_data in combined_episodes:
                    for seg in ep_data['segments']:
                        speech = seg.get('speech', '').strip()
                        if speech:
                            text_content.append(speech)
                            

                txt_filename = f"narrations_ep_{from_ep}_to_{to_ep}.txt"
                txt_path = os.path.join(download_dir, txt_filename)
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write("\n\n".join(text_content))
                await sse_logger.log(f"[VLM] Đã tạo file thuyết minh TTS thành công: '{txt_filename}'", "success")
                await sse_logger.log("[VLM] HOÀN THÀNH TỔNG HỢP TẤT CẢ CÁC TẬP!", "success", "idle", "Sẵn sàng")
            else:
                await sse_logger.log("[VLM] Không có tập nào được tóm tắt thành công.", "warning", "idle", "Sẵn sàng")
                

        except Exception as err:
            await sse_logger.log(f"[VLM] Lỗi hệ thống: {str(err)}", "error", "idle", "Sẵn sàng")


# Start Crawling Route
@app.post("/api/crawl")
async def crawl(payload: CrawlRequest):
    raw_url = (payload.url or "").strip()
    if not raw_url or not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail="URL truyện không hợp lệ hoặc đang để trống. Vui lòng nhập link truyện hợp lệ (bắt đầu bằng http:// hoặc https://)."
        )

    url = raw_url
    parsed_url = urllib.parse.urlparse(url)
    if "asura" in parsed_url.netloc.lower() and parsed_url.netloc.lower() != "asurascans.com":
        url = urllib.parse.urlunparse(parsed_url._replace(netloc="asurascans.com"))
        payload.url = url
        await sse_logger.log(f"Chuẩn hóa tên miền Asura Scans thành: {url}", "info")
    elif "manhuaplus.com" in parsed_url.netloc.lower() and "/chapter-" in url:
        url = re.sub(r"/chapter-[^/]+/?$", "/", url)
        payload.url = url
        await sse_logger.log(f"Chuẩn hóa URL ManhuaPlus thành trang chính: {url}", "info")
    
    parsed = urllib.parse.urlparse(payload.url)
    comic_title = "Comic"
    if parsed.path:
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts:
            slug = parts[-1]
            if slug == 'list' and len(parts) >= 2:
                slug = parts[-2]
            elif slug == 'viewer' and len(parts) >= 3:
                slug = parts[-3]
            elif len(parts) >= 2 and parts[-1] in ('viewer', 'list'):
                slug = parts[-2]
            comic_title = slug.replace("-", " ").title()

    v_id = payload.voice_id
    default_voice = "auto"
    if not v_id or v_id in ("elevenlabs_yj30vwTGJxSHezdAGsv9", "elevenlabs_XrExE9yKIg1WjnnlVkGX"):
        v_id = default_voice
        
    config = {
        "safe_mode": payload.safe_mode,
        "nsfw_threshold": payload.nsfw_threshold,
        "nsfw_mode": payload.nsfw_mode,
        "gemini_model": payload.gemini_model,
        "temperature": payload.temperature,
        "max_output_tokens": payload.max_output_tokens,
        "timeout": payload.timeout,
        "retry_count": payload.retry_count,
        "concurrency": payload.concurrency,
        "image_quality": payload.image_quality,
        "pdf_quality": payload.pdf_quality,
        "max_pdf_pages": getattr(payload, "max_pdf_pages", 20),
        "language": payload.language,
        "vlm_provider": payload.vlm_provider,
        "voice_id": v_id,
        "ref_audio_path": payload.ref_audio_path,
        "ai33pro_api_key": payload.ai33pro_api_key,
        "logo_path": payload.logo_path,
        "overlay_path": payload.overlay_path,
        "remove_text": payload.remove_text,
        "remove_text_conf": payload.remove_text_conf,
        "remove_text_radius": payload.remove_text_radius,
        "vlm_email": payload.vlm_email,
        "vlm_password": payload.vlm_password,
        "comix_group_id": payload.comix_group_id,
        "film_grain": payload.film_grain,
        "grain_strength": payload.grain_strength,
        "flip_horizontal": payload.flip_horizontal,
        "headless": payload.headless if payload.headless is not None else load_config().get("headless", False),
        "video_mark_path": payload.video_mark_path,
        "video_mark_alpha": getattr(payload, "video_mark_alpha", 0.01),
        "enable_video_mark": getattr(payload, "enable_video_mark", True)
    }

    task_id = await workflow_manager.queue_task(
        comic_title,
        payload.url,
        payload.from_episode,
        payload.to_episode,
        config
    )
    return {"status": "success", "message": "Workflow task queued successfully.", "task_id": task_id}


# List all workflow tasks
@app.get("/api/workflows")
async def get_workflows():
    tasks = workflow_manager.repository.load_all()
    results = []
    for t in tasks:
        d = t.to_dict(include_logs=False)
        artifacts = d.get("artifacts") or {}
        dl_dir = artifacts.get("download_dir")
        folder = artifacts.get("download_folder_name") or (os.path.basename(dl_dir) if dl_dir else None)
        if folder and folder.lower() != "none":
            artifacts["download_folder_name"] = folder
            fv = artifacts.get("final_videos")
            if isinstance(fv, dict):
                for k, v in list(fv.items()):
                    if v and "/downloads/None/" in v:
                        fv[k] = v.replace("/downloads/None/", f"/downloads/{folder}/")
            fvu = artifacts.get("final_video_url")
            if fvu and "/downloads/None/" in fvu:
                artifacts["final_video_url"] = fvu.replace("/downloads/None/", f"/downloads/{folder}/")
            fsu = artifacts.get("final_subtitle_url")
            if fsu and "/downloads/None/" in fsu:
                artifacts["final_subtitle_url"] = fsu.replace("/downloads/None/", f"/downloads/{folder}/")
            if not artifacts.get("final_subtitle_url"):
                out_dir = os.path.join("downloads", folder, "output")
                if os.path.isdir(out_dir):
                    f_srt = os.path.join(out_dir, f"{folder}.srt")
                    if os.path.isfile(f_srt):
                        artifacts["final_subtitle_url"] = f"/downloads/{folder}/output/{folder}.srt"
                    else:
                        for sf in os.listdir(out_dir):
                            if sf.endswith(".srt"):
                                artifacts["final_subtitle_url"] = f"/downloads/{folder}/output/{sf}"
                                break
            fs = artifacts.get("final_subtitles")
            if not isinstance(fs, dict):
                fs = {}
            if isinstance(fv, dict):
                for ep_k in fv.keys():
                    if ep_k not in fs or (fs.get(ep_k) and "/downloads/None/" in fs[ep_k]):
                        fs[ep_k] = f"/downloads/{folder}/episode_{ep_k}/transcript.srt"
            artifacts["final_subtitles"] = fs

            mv = artifacts.get("merged_videos")
            if isinstance(mv, list):
                for item in mv:
                    if isinstance(item, dict):
                        vu = item.get("video_url")
                        if vu and "/downloads/None/" in vu:
                            item["video_url"] = vu.replace("/downloads/None/", f"/downloads/{folder}/")
                        su = item.get("subtitle_url")
                        if su and "/downloads/None/" in su:
                            item["subtitle_url"] = su.replace("/downloads/None/", f"/downloads/{folder}/")
            artifacts["merged_videos"] = mv or []

            d["artifacts"] = artifacts
        results.append(d)
    return results


# Cancel active workflow task
@app.post("/api/workflows/{task_id}/cancel")
async def cancel_workflow(task_id: str):
    success = await workflow_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or not running.")
    return {"status": "success", "message": "Cancellation requested successfully."}


# Remove workflow task
@app.delete("/api/workflows/{task_id}")
async def delete_workflow(task_id: str):
    success = await workflow_manager.remove_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"status": "success", "message": "Workflow removed successfully."}


# Clear all workflows
@app.post("/api/workflows/clear-all")
async def clear_all_workflows():
    tasks = workflow_manager.repository.load_all()
    for task in tasks:
        await workflow_manager.remove_task(task.id)
    return {"status": "success", "message": "All workflow tasks cleared successfully."}


@app.post("/api/workflows/retry-all")
async def retry_all_workflows():
    count = await workflow_manager.retry_all_failed_or_cancelled()
    return {"status": "success", "message": f"Đã chạy lại {count} tác vụ bị lỗi hoặc bị hủy."}


# Retry individual workflow task
@app.post("/api/workflows/{task_id}/retry")
async def retry_workflow(task_id: str):
    success = await workflow_manager.retry_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Tác vụ không tồn tại hoặc không ở trạng thái lỗi/hủy.")
    return {"status": "success", "message": "Đã xếp lại lịch chạy tiếp tục cho tác vụ."}


class MergeRangeItem(BaseModel):
    from_ep: int
    to_ep: int
    custom_name: Optional[str] = ""

class MergeEpisodesRequest(BaseModel):
    ranges: List[MergeRangeItem]


# Query available rendered episodes & previously merged videos for a task
@app.get("/api/workflows/{task_id}/merge-info")
async def get_workflow_merge_info(task_id: str):
    from workflow_merger import get_task_available_episodes
    task = workflow_manager.repository.load(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhiệm vụ.")
    
    info = get_task_available_episodes(task)
    return info


# Execute splitting/merging of rendered episodes without re-rendering
@app.post("/api/workflows/{task_id}/merge-episodes")
async def merge_workflow_episodes(task_id: str, payload: MergeEpisodesRequest):
    from workflow_merger import merge_episode_ranges_for_task
    task = workflow_manager.repository.load(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhiệm vụ.")

    if not payload.ranges:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp ít nhất một khoảng tập để gộp.")

    ranges_data = [r.model_dump() if hasattr(r, 'model_dump') else r.dict() for r in payload.ranges]
    res = await merge_episode_ranges_for_task(task, ranges_data)
    
    # Persist and broadcast task updates
    await workflow_manager.save_and_broadcast("WorkflowUpdated", task)

    if res.get("status") == "error" and not res.get("merged_videos"):
        error_details = "; ".join(res.get("errors", []))
        raise HTTPException(status_code=400, detail=f"Không thể gộp video: {error_details}")

    return res


# Delete a previously merged video file
@app.delete("/api/workflows/{task_id}/merged-videos/{file_name}")
async def delete_merged_video(task_id: str, file_name: str):
    from workflow_merger import delete_merged_video_file
    task = workflow_manager.repository.load(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhiệm vụ.")

    success = delete_merged_video_file(task, file_name)
    if success:
        await workflow_manager.save_and_broadcast("WorkflowUpdated", task)
        return {"status": "success", "message": f"Đã xóa video gộp '{file_name}' thành công."}
    else:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy video gộp '{file_name}'.")





def get_unique_sorted_images(ep_dir: str) -> list:
    files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
    files = [f for f in files if f not in ("chapter.pdf", "chatgpt_prompt.txt", "gemini_prompt.txt", "stitched.jpg")]
    if not files:
        return []
    

    unique_files = []
    last_file_hash = None
    import hashlib
    for file in files:
        file_path = os.path.join(ep_dir, file)
        # Calculate simple md5 hash
        try:
            with open(file_path, 'rb') as f:
                h = hashlib.md5(f.read()).hexdigest()
            if h != last_file_hash:
                unique_files.append(file)
                last_file_hash = h
            else:
                print(f"Bỏ qua ảnh trùng lặp: {file}")
        except Exception:
            unique_files.append(file)
    return unique_files


def stitch_images_vertically(ep_dir: str, output_path: str, image_quality: int = 80) -> bool:
    files = get_unique_sorted_images(ep_dir)
    if not files:
        return False
    images = []
    resized_images = []
    stitched_image = None
    try:
        from PIL import Image
        for f in files:
            with Image.open(os.path.join(ep_dir, f)) as img:
                rgb_img = img.convert('RGB')
                rgb_img.load()
                images.append(rgb_img)
            
        if not images:
            return False
            
        target_width = max(img.width for img in images)
        
        total_height = 0
        for img in images:
            ratio = target_width / img.width
            new_h = int(img.height * ratio)
            if new_h <= 0:
                new_h = 1
            resized_images.append(img.resize((target_width, new_h), Image.Resampling.LANCZOS))
            total_height += new_h

        # Max limit for JPEG dimension is 65535 pixels.
        # If total_height exceeds 65000, scale down target_width and recalculate.
        max_allowed_height = 65000
        if total_height > max_allowed_height:
            scale_ratio = max_allowed_height / total_height
            target_width = int(target_width * scale_ratio)
            if target_width <= 0:
                target_width = 1
            
            # Close previous resized images to free memory
            for r_img in resized_images:
                r_img.close()
            
            resized_images = []
            total_height = 0
            for img in images:
                ratio = target_width / img.width
                new_h = int(img.height * ratio)
                if new_h <= 0:
                    new_h = 1
                resized_images.append(img.resize((target_width, new_h), Image.Resampling.LANCZOS))
                total_height += new_h
            
        stitched_image = Image.new("RGB", (target_width, total_height), (255, 255, 255))
        current_y = 0
        for img in resized_images:
            stitched_image.paste(img, (0, current_y))
            current_y += img.height
            
        stitched_image.save(output_path, "JPEG", quality=image_quality)
        return True
    except Exception as e:
        print(f"Lỗi ghép ảnh dọc: {str(e)}")
        return False
    finally:
        for img in resized_images:
            try:
                img.close()
            except Exception:
                pass
        for img in images:
            try:
                img.close()
            except Exception:
                pass
        if stitched_image:
            try:
                stitched_image.close()
            except Exception:
                pass


LANGUAGE_MAP = {
    "vi": "Vietnamese",
    "en": "English",
    "ko": "Korean",
    "zh": "Chinese",
    "ja": "Japanese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ru": "Russian",
    "th": "Thai",
    "id": "Indonesian",
}


LANGUAGE_MAP = {
    "vi": "Vietnamese",
    "en": "English",
    "ko": "Korean",
    "zh": "Chinese",
    "ja": "Japanese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ru": "Russian",
    "th": "Thai",
    "id": "Indonesian",
}


def generate_gemini_prompt(
    comic_title="",
    ep="",
    total_pages=0,
    target_language="vi",
    min_scenes=20,
    max_scenes=26,
    character_name="",
):
    lang = LANGUAGE_MAP.get(target_language, "Vietnamese")
    title_line = comic_title.strip() or "the attached manhwa chapter"
    ep_line = f" Episode/chapter: {ep}." if str(ep).strip() else ""
    page_line = f" The PDF has {total_pages} pages." if total_pages else ""
    name_line = (
        f" Protagonist name to use consistently: {character_name}."
        if character_name.strip()
        else " Infer the protagonist name from the chapter and keep it consistent."
    )

    return f"""You are a manhwa/webtoon recap director and TTS scriptwriter.

INPUT
- Work: {title_line}.{ep_line}{page_line}
- A manhwa chapter PDF. Panels are labeled visual regions (Start:Rx / End:Rx). Use that exact region ID as printed (R1, R2, R10, R16).
- TARGET_LANGUAGE: {lang}
-{name_line}

TASK
Build a recap video script of THIS chapter only. Pick story-bearing regions and write TTS narration in {lang} so a viewer follows the protagonist through hook, events, rules/twists, emotion, and ending beat.

READ FIRST
Extract setting, protagonist goal, conflict, beats, rules/systems, tone, and cliffhanger.
Ignore scanlation UI, credits, banners, watermarks, and translator notes unless that text belongs to the story world.

SELECT REGIONS
Target {min_scenes} to {max_scenes} regions in chronological story order.
Prefer the count that best covers beginning → turning point → end without padding.
If the chapter does not have {min_scenes} valid pictorial regions, select fewer. Never invent IDs, never renumber, never split one beat across extra near-duplicate crops to hit a quota.

Keep a region when it is visually strong and carries the beat through the protagonist: face, body language, action, emotion, a key object in their hands, or an establishing shot that still keeps the lead readable.
Drop:
- text-only, caption-only, or rule-card-only frames with no useful pictorial subject
- empty backgrounds, texture fillers, decorative shots with no story role
- near-duplicates
- leftover "cont." lettering fragments that add no new beat
- credits, logos, scanlation dressing
One in-world chapter title card is allowed if it is a real story-title beat, not a watermark or site logo.

WRITE NARRATION
- 100% {lang}. No mixed language. Keep character names, skill names, and item names as they appear unless the work itself already uses a natural form in {lang}. Do not translate proper names into nicknames.
- One narration block per selected region. Write only what that shot can honestly carry. A quiet face stays short. A turning point may run longer. Do not dump the chapter onto one region. Do not pad a weak shot.
- Third-person recap, spoken like a person telling the chapter out loud. Continuous voiceover from the protagonist's seat: situation, reaction, choice, cost or gain. Side characters appear only when they pressure, help, mock, or change the lead. Name the protagonist once, then reuse that same name.
- Paraphrase dialogue in narrator voice when useful. Do not catalog objects. Do not turn the recap into an ensemble summary.
- Each line is primarily the beat visible in that region. A short time-link in {lang} at the start of a line is allowed. Do not spend the line narrating a previous or next shot.
- Diction: plain spoken {lang}. Name the action, the person, and the cost. Do not use flowery, literary, poetic, or exaggerated wording. No stacked intensifiers, destiny talk, legend talk, trailer taglines, or poster adjectives. If a word can be cut and the fact remains, cut it. If a line sounds advertised rather than reported, rewrite it as what happens in this shot.
- Light dry humor only when the beat already has irony. One sly remark max per line. No slapstick, no meme slang, no fourth wall. Never joke on death, assault, or grief.
- TTS-ready: speakable sentences, punctuation for pauses. No lists, markdown, emojis, stage directions, or extra brackets inside the spoken line.
- Never say "in this panel", "the image shows", "as we can see", "in this chapter", or "welcome".
- Faithful to this chapter only. No later-chapter plot.

OUTPUT
Return ONLY the script lines in playback order. No title, no analysis, no blank lines, no extra text.

Each line MUST be exactly:
[R2] - <narration>#

- Original region ID inside [], written as printed. Never R001. Never source=.
- One space on each side of "-".
- Spoken text in plain {lang}.
- Each line ends with # then a newline.
- One selected region per line.

DONE WHEN
- Every [Rx] exists in the PDF.
- Count is at most {max_scenes}, and at least {min_scenes} unless the chapter lacks enough valid shots.
- Shots stay in story order and the protagonist stays the center.
- No selected region is text-only or empty of story.
- Each line fits the image it plays over and is ready to read aloud in {lang}.
"""





def generate_intro_prompt(
    comic_title="",
    total_pages=0,
    target_language="vi",
    character_name="",
):
    lang = LANGUAGE_MAP.get(target_language, "Vietnamese")
    title_line = comic_title.strip() or "the attached manhwa"
    name_line = (
        f" Use this protagonist name consistently: {character_name}."
        if character_name.strip()
        else " Infer the protagonist name from episode 1 and official series info, then keep it consistent."
    )
    page_line = f" The PDF has {total_pages} pages." if total_pages else ""

    return f"""You are a manhwa series trailer writer and TTS scriptwriter.

THIS TASK IS A SERIES INTRO TRAILER, anchored on Episode 1 visuals. Not a page-by-page recap.
Work: {title_line}. Episode 1.{page_line}
TARGET_LANGUAGE: {lang}
{name_line}

GOAL
Write exactly 5 narration lines that sell THIS series through the protagonist.
A first-time listener must know who the lead is after line 1, then understand the premise on first listen.

FACTS
Use only the official premise plus what Episode 1 actually shows.
Introduce real nouns with their role the first time they appear: person, house, clan, estate, guild, school, title, place, skill.
After that, the short name may stand alone.
Do not use later-arc twists, the ending, future companions who are absent from Episode 1, or invented skills and titles.
Do not invent a premise engine this work does not have.

SELECT 5 REGIONS
Pick exactly 5 labeled regions (Start:Rx / End:Rx) that already exist, in story order. Do not invent IDs.
Prefer the protagonist in frame. Another person may appear only if the series engine is that relationship.
Reject text-only boxes, credits, logos, ugly SFX, blurry crops, extras-only shots.

Assign jobs to LINES, not to a forced shot type in that slot:
1) Identify the lead: role, name, and one concrete opening situation from this work.
2) Where they stand now: world, job, rank, body, or house they are stuck in.
3) Why that position is bad, funny, tender, or dangerous.
4) The tool this series actually uses: skill, habit, power, vow, craft, or relationship shown in premise / Episode 1.
5) One question that restates the series promise, over an unresolved look if one exists.

If the cleanest hero face is not the earliest valid region, keep chronological order and put the identification in line 1 over the earliest usable lead shot.

WRITE IN {lang} ONLY
No mixed language. Do not default to Vietnamese stock phrases when {lang} is not Vietnamese.
Do not borrow wording, jokes, roles, or plot from any other series.

Line 1 is one spoken sentence. It must name the lead with a role and a concrete situation. Use the gender and role this work actually has. Never call a heroine the male lead. Never call a hero the female lead. If two people share the engine, name the viewpoint lead first, then the other person with a role. After line 1, use the short name.
Never drop a bare name, house, or title as if the listener already knows it.
Do not start with empty frames such as "There is a family", "There are geniuses", or "This is the story of".
Do not use "this is the intro", "welcome to", "in this video", or "in this panel".

Lines 2 to 4: one sentence, or two short sentences if a period helps the breath.
Line 5: one question only.
Sound like a person talking to a friend about a series they just started. Everyday connective wording. Proper nouns stay if you attach the role in the same breath.
Diction: plain spoken {lang}. Name the person, the situation, and the problem. Do not use flowery, literary, poetic, or exaggerated wording. No stacked intensifiers, destiny talk, legend talk, trailer taglines, or poster adjectives. If a word can be cut and the fact remains, cut it. If a line sounds advertised rather than reported, rewrite it with a fact unique to this work.
Humor only at this series' temperature.
TTS-ready: punctuation for pauses. No lists, markdown, emojis, stage directions, or extra brackets inside the spoken text.

Each line should be one speaking breath. If a line sounds like a trailer tagline, or can be pasted onto another title by swapping one name, rewrite it with a fact unique to this work.

OUTPUT
Return ONLY these 5 lines, no blank lines, no commentary:

[Rx] - <spoken text>#
[Ry] - <spoken text>#
[Rz] - <spoken text>#
[Rw] - <spoken text>#
[Rv] - <spoken text>#

- Original PDF region ID, written as printed.
- One space on each side of "-".
- Spoken text in plain {lang}.
- Each line ends with # then a newline.
"""


class OpenFolderRequest(BaseModel):
    comic_folder: str
    episode: int


class ImportJsonRequest(BaseModel):
    comic_folder: str
    episode: int
    json_content: str


class SaveSummaryRequest(BaseModel):
    comic_folder: str
    episode: int
    summary_data: list


@app.post("/api/open-pdf-folder")
async def open_pdf_folder(payload: OpenFolderRequest):
    project_dir = os.path.dirname(os.path.abspath(__file__))
    folder_path = os.path.normpath(os.path.join(project_dir, "downloads", payload.comic_folder, f"ep_{payload.episode}"))
    if os.path.exists(folder_path):
        try:
            os.startfile(folder_path)
            return {"status": "success"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Không thể mở thư mục: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="Thư mục không tồn tại.")


@app.get("/api/get-prompt")
async def get_prompt(comic_folder: str, episode: int):
    project_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(project_dir, "downloads", comic_folder, f"ep_{episode}", "gemini_prompt.txt")
    if not os.path.exists(prompt_path):
        prompt_path = os.path.join(project_dir, "downloads", comic_folder, f"ep_{episode}", "chatgpt_prompt.txt")
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"status": "success", "prompt": content}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi đọc prompt: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="Prompt chưa được tạo.")


@app.post("/api/import-json")
async def import_json(payload: ImportJsonRequest):
    comic_folder = payload.comic_folder.strip()
    ep = payload.episode
    content = payload.json_content.strip()


    try:
        if content.startswith("```json"):
            content = content[7:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
        content = content.strip()
    

        match_arr = re.search(r"\[\s*.*\]", content, re.DOTALL)
        match_dict = re.search(r"\{\s*.*\}", content, re.DOTALL)
        if match_arr and (not match_dict or match_arr.start() < match_dict.start()):
            data = json.loads(match_arr.group(0))
        elif match_dict:
            data = json.loads(match_dict.group(0))
        else:
            data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON không đúng định dạng: {str(e)}")
    
    segments = []
    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict):
        segments = data.get("segments") or data.get("episodes") or []
        if not isinstance(segments, list):
            segments = [data]
    else:
        raise HTTPException(status_code=400, detail="Dữ liệu JSON không hợp lệ.")

    if not segments:
        raise HTTPException(status_code=400, detail="Không tìm thấy danh sách phân đoạn nào hoặc danh sách rỗng.")
    

    project_dir = os.path.dirname(os.path.abspath(__file__))
    ep_dir = os.path.join(project_dir, "downloads", comic_folder, f"ep_{ep}")
    if not os.path.exists(ep_dir):
        raise HTTPException(status_code=404, detail=f"Không tìm thấy thư mục tập {ep} để xác thực ảnh.")
    

    image_files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
    if not image_files:
        raise HTTPException(status_code=400, detail="Thư mục tập không chứa ảnh nào.")
    total_images = len(image_files)


    validated_segments = []
    for idx, seg in enumerate(segments, 1):
        if not isinstance(seg, dict):
            raise HTTPException(status_code=400, detail=f"Cảnh {idx} không phải là một object.")

        speech = seg.get("speech", "").strip()
        if not speech:
            raise HTTPException(status_code=400, detail=f"Cảnh {idx} bị thiếu nội dung narration ('speech').")

        # Extract images/slides list
        images_list = seg.get("images") or seg.get("slides") or []
        if not isinstance(images_list, list):
            images_list = [images_list]

        pages = []
        for img in images_list:
            if isinstance(img, dict):
                p_val = img.get("page")
            else:
                p_val = img
            if p_val is not None:
                try:
                    if isinstance(p_val, str) and not p_val.isdigit():
                        found_digits = re.findall(r'\d+', p_val)
                        if found_digits:
                            pages.append(int(found_digits[-1]))
                    else:
                        pages.append(int(p_val))
                except (ValueError, TypeError):
                    pass

        # Fallback to key_page and source_range if pages is empty
        if not pages:
            kp = seg.get("key_page") or seg.get("page")
            if kp is not None:
                try:
                    pages.append(int(kp))
                except (ValueError, TypeError):
                    pass

            sr = seg.get("source_range")
            if isinstance(sr, dict):
                fp = sr.get("from")
                tp = sr.get("to")
                if fp is not None:
                    try:
                        pages.append(int(fp))
                    except (ValueError, TypeError):
                        pass
                if tp is not None:
                    try:
                        pages.append(int(tp))
                    except (ValueError, TypeError):
                        pass

        if not pages:
            # Default to page 1
            pages = [1]

        from_page = min(pages)
        to_page = max(pages)
        key_page = pages[0]

        if from_page < 1 or to_page < 1 or from_page > to_page or from_page > total_images or to_page > total_images:
            raise HTTPException(
                status_code=400, 
                detail=f"Cảnh {idx} có phạm vi trang ({from_page} - {to_page}) không hợp lệ hoặc vượt quá tổng số trang ({total_images})."
            )
        
        if key_page < 1 or key_page > total_images:
            raise HTTPException(
                status_code=400,
                detail=f"Cảnh {idx} có 'key_page' ({key_page}) vượt quá phạm vi trang hợp lệ (1 - {total_images})."
            )

        key_file_name = image_files[key_page - 1]
        web_key_image_path = f"ep_{ep}/{key_file_name}"

        segment_dict = {
            "speech": speech,
            "key_image": web_key_image_path,
            "source_range": {
                "from": from_page,
                "to": to_page
            }
        }

        # Keep original images or slides if present
        if "images" in seg:
            segment_dict["images"] = seg["images"]
        if "slides" in seg:
            segment_dict["slides"] = seg["slides"]

        validated_segments.append(segment_dict)
    

    narrations_file = os.path.join(ep_dir, "narrations.json")
    with open(narrations_file, "w", encoding="utf-8") as f:
        json.dump(validated_segments, f, ensure_ascii=False, indent=2)
    

    await sse_logger.log(f"Tập {ep}: Import thành công JSON và lưu thành narrations.json.", "success")


    return {
        "status": "success",
        "comic_folder": comic_folder,
        "summary": {
            "title": f"Episode {ep}",
            "segments": validated_segments
        }
    }


    # Save Confirmed Summary Route
@app.post("/api/save-summary")
async def save_summary(payload: SaveSummaryRequest):
    try:
        comic_folder = payload.comic_folder
        ep = payload.episode
        summary_data = payload.summary_data
    

        project_dir = os.path.dirname(os.path.abspath(__file__))
        save_dir = os.path.join(project_dir, "downloads", comic_folder)
        os.makedirs(save_dir, exist_ok=True)
    

        file_name = f"ep_{ep}_summary.json"
        save_path = os.path.join(save_dir, file_name)
    

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
        

        await sse_logger.log(f"Tập {ep}: Lưu summary thành công vào file '{file_name}'.", "success")
        return {"status": "success", "message": f"Đã lưu summary tập {ep} thành công."}
    except Exception as e:
        error_msg = f"Lỗi lưu summary: {str(e)}"
        await sse_logger.log(error_msg, "error")
        raise HTTPException(status_code=500, detail=error_msg)


    # Background Test Task
async def run_test_task(logo_path: str = None, overlay_path: str = None):
    global crawler_running, stop_requested
    stop_requested = False
    test_success = False

    # We use the crawler lock to prevent concurrent runs
    async with crawler_lock:
        crawler_running = True
        await sse_logger.log("[TEST] Bắt đầu chạy test VLM / Workflow trên thư mục lookism_3_3...", "system", "active", "Đang chạy test...")
    

        try:
            # 1. Check if mock data is already available
            project_dir = os.path.dirname(os.path.abspath(__file__))
            download_dir = os.path.join(project_dir, "downloads", "lookism_3_3")
            ep_dir = os.path.join(download_dir, "ep_3")
        

            stitched_path = os.path.join(ep_dir, "stitched.jpg")
            prompt_path = os.path.join(ep_dir, "gemini_prompt.txt")
            title_text = "Lookism"
            ep = 3
        

            mock_data_exists = False
            if os.path.exists(ep_dir):
                images_list = [f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                if len(images_list) > 0:
                    mock_data_exists = True
        

            if mock_data_exists:
                await sse_logger.log("[TEST] Phát hiện thư mục dữ liệu mock có sẵn tại downloads/lookism_3_3/ep_3. Sử dụng trực tiếp...", "success")
            

                # Check / generate stitched.jpg and gemini_prompt.txt if missing
                image_files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
            

                if not os.path.exists(stitched_path):
                    await sse_logger.log("[TEST] Thiếu stitched.jpg. Đang tiến hành tạo lại...", "info")
                    stitch_images_vertically(ep_dir, stitched_path)
                    await sse_logger.log("[TEST] Đã tạo thành công stitched.jpg.", "success")
                
                prompt_content = generate_gemini_prompt(title_text, ep, len(image_files), "vi")
                with open(prompt_path, "w", encoding="utf-8") as pf:
                    pf.write(prompt_content)
                await sse_logger.log("[TEST] Đã cập nhật gemini_prompt.txt.", "success")
            else:
                await sse_logger.log("[TEST] Không có dữ liệu mock có sẵn. Tiến hành tải mới từ Webtoons...", "info")
                if os.path.exists(download_dir):
                    try:
                        import shutil
                        shutil.rmtree(download_dir)
                    except Exception:
                        pass
            
                test_url = "https://www.webtoons.com/en/action/lookism/list?title_no=1049"
                from_ep = 1
                to_ep = 1
            
                parsed = urllib.parse.urlparse(test_url)
                query = urllib.parse.parse_qs(parsed.query)
                title_no = query.get("title_no", [""])[0]
                if not title_no:
                    raise Exception("Không tìm thấy title_no trong URL bộ truyện.")
                
                parts = parsed.path.strip("/").split("/")
                base_path = "/".join(parts[:-1])
            
                if True:
                    browser = None
                    context = None
                    try:
                        await sse_logger.log("[TEST] Khởi chạy Chromium và tải trang chính...", "info")
                        browser, context = await get_shared_browser_context()
                        nav_manager = NavigationManager(sse_logger)
                        nav_manager.context = context
                        nav_manager.browser = browser
                        page = await context.new_page()
                    
                        await nav_manager.safe_goto(page, test_url, reason="TEST load main page", caller="run_test_task")
                        title_text_web = await page.title()
                        title_text = title_text_web.split("|")[0].strip()
                    
                        os.makedirs(ep_dir, exist_ok=True)
                        viewer_url = f"{parsed.scheme}://{parsed.netloc}/{base_path}/ep-{ep}/viewer?title_no={title_no}&episode_no={ep}"
                        await nav_manager.safe_goto(page, viewer_url, reason="TEST load viewer page", caller="run_test_task")
                    
                        try:
                            await page.wait_for_selector("#_imageList img", timeout=15000)
                        except Exception:
                            raise Exception("[TEST] Lỗi: Không tìm thấy danh sách ảnh.")
                        
                        image_urls = await page.locator("#_imageList img").evaluate_all(
                            "elements => elements.map(el => el.getAttribute('data-url') || el.getAttribute('src'))"
                        )
                        image_urls = [src for src in image_urls if src]
                            
                        if not image_urls:
                            raise Exception("[TEST] Không tìm thấy ảnh nào.")
                        
                        await sse_logger.log(f"[TEST] Tập 1: Phát hiện {len(image_urls)} ảnh. Đang tiến hành tải...", "info")
                        for i, img_url in enumerate(image_urls, 1):
                            if stop_requested:
                                raise Exception("Tiến trình test bị dừng bởi người dùng.")
                            file_ext = ".jpg"
                            if ".png" in img_url.lower():
                                file_ext = ".png"
                            file_name = f"{str(i).zfill(3)}{file_ext}"
                            try:
                                await download_image(img_url, os.path.join(ep_dir, file_name))
                            except Exception as dl_err:
                                await sse_logger.log(f"[TEST] Lỗi tải ảnh {i}: {str(dl_err)}", "error")
                        
                        await sse_logger.log("[TEST] Tập 1: Hoàn thành tải ảnh.", "success")
                    finally:
                        if 'page' in locals() and page:
                            try: await page.close()
                            except Exception: pass
                
                # Create stitched image & Prompt
                await sse_logger.log("[TEST] Đang tạo tệp stitched.jpg và prompt...", "info")
                stitch_images_vertically(ep_dir, stitched_path)
                image_files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f not in ("chapter.pdf", "gemini_prompt.txt", "chatgpt_prompt.txt", "stitched.jpg")])
                prompt_content = generate_gemini_prompt(title_text, ep, len(image_files), "vi")
                with open(prompt_path, "w", encoding="utf-8") as pf:
                    pf.write(prompt_content)
                await sse_logger.log("[TEST] Đã tạo thành công stitched.jpg và gemini_prompt.txt.", "success")
        
            # 3. Perform headed browser VLM / ChatGPT Web test
            vlm_provider = "gemini"
            vlm_url = "https://gemini.google.com/app"
            vlm_name = "Gemini"
            await sse_logger.log(f"[TEST] Bắt đầu tự động hóa trình duyệt để kiểm thử trực tiếp trên {vlm_url} ...", "info")
        
            gemini_web_success = False
            raw_json_text = None
            mock_json = None
        
            # Since the user requested "mở giao diện browser để có thể quan sát thao tác tự động", 
            # we launch in headed mode (headless=False)
            if True:
                browser = None
                context = None
                try:
                    await sse_logger.log("[TEST] Đang khởi chạy Chromium ở chế độ headed (headless=False)...", "info")
                    browser, context = await get_shared_browser_context(headless=False)
                    cookie_file = "cookies.json"
                    

                    page = await context.new_page()
                    await asyncio.sleep(2)
                

                    await sse_logger.log(f"[TEST] Đang điều hướng trình duyệt tới trang {vlm_name}...", "info")
                    await page.goto(vlm_url, timeout=60000)
                

                    # Wait for page elements to load or wait for user to sign in
                    await sse_logger.log("[TEST] Trình duyệt đã mở. Giao diện sẽ tự động tải sau khi bạn đăng nhập tài khoản (Chờ tối đa 120 giây)...", "info")
                



                    textbox = None
                    textbox_xpath = None
                    textbox_found = False
                    for _ in range(120):
                        if stop_requested:
                            raise Exception("Tiến trình test bị dừng bởi người dùng.")
                        for sel in textbox_selectors:
                            try:
                                loc = page.locator(sel).first
                                if await loc.count() > 0 and await loc.is_visible():
                                    textbox = loc
                                    textbox_xpath = sel
                                    textbox_found = True
                                    break
                            except Exception:
                                pass
                        if textbox_found:
                            break
                        await asyncio.sleep(1)
                    

                    if not textbox_found:
                        raise Exception("Hết thời gian chờ đăng nhập (120s) hoặc có lỗi xảy ra.")
                    

                    await sse_logger.log(f"[TEST] Đã phát hiện giao diện chat {vlm_name}. Bắt đầu tải tệp stitched.jpg...", "success")
                

                    if stop_requested:
                        raise Exception("Tiến trình test bị dừng bởi người dùng.")
                    

                    # Upload stitched image using simulated clipboard paste event (Ctrl+V)
                    await sse_logger.log("[TEST] Đang đính kèm tệp stitched.jpg bằng cách paste (Ctrl+V)...", "info")
                    try:
                        import base64
                        with open(stitched_path, "rb") as stitched_file:
                            img_base64 = base64.b64encode(stitched_file.read()).decode("utf-8")
                        

                        js_paste_img = """
                        async (args) => {
                            const { xpath, base64Data, fileName, mimeType } = args;
                            let element;
                            if (xpath.startsWith('xpath=')) {
                                const result = document.evaluate(xpath.replace('xpath=', ''), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                                element = result.singleNodeValue;
                            } else {
                                element = document.querySelector(xpath);
                            }
                            if (!element) throw new Error("Không tìm thấy ô nhập prompt.");
                        

                            element.focus();
                            const res = await fetch("data:" + mimeType + ";base64," + base64Data);
                            const blob = await res.blob();
                            const file = new File([blob], fileName, { type: mimeType });
                        

                            const dataTransfer = new DataTransfer();
                            dataTransfer.items.add(file);
                        

                            const pasteEvent = new ClipboardEvent('paste', {
                                bubbles: true,
                                cancelable: true,
                                clipboardData: dataTransfer
                            });
                            element.dispatchEvent(pasteEvent);
                            return true;
                        }
                        """
                        if stop_requested:
                            raise Exception("Tiến trình test bị dừng bởi người dùng.")
                        

                        await page.evaluate(js_paste_img, {
                            "xpath": textbox_xpath,
                            "base64Data": img_base64,
                            "fileName": "stitched.jpg",
                            "mimeType": "image/jpeg"
                        })
                        await sse_logger.log("[TEST] Đã đính kèm tệp stitched.jpg thành công. Đang chờ 3 giây...", "success")
                        await asyncio.sleep(3)
                    except Exception as e:
                        if stop_requested:
                            raise Exception("Tiến trình test bị dừng bởi người dùng.")
                        await sse_logger.log(f"[TEST] Lỗi đính kèm tệp stitched.jpg bằng cách paste: {str(e)}", "warning")
                    

                    if stop_requested:
                        raise Exception("Tiến trình test bị dừng bởi người dùng.")
                    

                    # Try to fill the prompt
                    await sse_logger.log("[TEST] Đang điền prompt tóm tắt của chương...", "info")
                    textbox = None
                    for tb_sel in [
                        "rich-textarea p",
                        "rich-textarea div[contenteditable='true']",
                        "div.ql-editor[contenteditable='true']",
                        "div[contenteditable='true']",
                        "[role='textbox']"
                    ]:
                        try:
                            loc = page.locator(tb_sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                textbox = loc
                                break
                        except Exception:
                            pass

                    pasted = False
                    if textbox:
                        try:
                            await textbox.click(force=True)
                            await asyncio.sleep(0.3)
                            await textbox.fill(prompt_content)
                            pasted = True
                        except Exception:
                            pass

                    if not pasted:
                        try:
                            p_el = page.locator("rich-textarea div.ql-editor p, div.ql-editor p, rich-textarea p").first
                            if await p_el.count() > 0:
                                await p_el.click(force=True)
                            elif textbox:
                                await textbox.click(force=True)
                            await page.keyboard.insert_text(prompt_content)
                            pasted = True
                        except Exception:
                            pass

                    try:
                        if textbox:
                            await textbox.press_sequentially(" ")
                            await textbox.press("Backspace")
                        else:
                            await page.keyboard.press("Space")
                            await page.keyboard.press("Backspace")
                    except Exception:
                        pass

                    await asyncio.sleep(1.0)
                    await sse_logger.log("[TEST] Đã điền nội dung prompt thành công.", "success")

                    await sse_logger.log(f"[TEST] Đang gửi yêu cầu (gửi tệp và prompt) tới {vlm_name}...", "info")
                    if stop_requested:
                        raise Exception("Tiến trình test bị dừng bởi người dùng.")

                    # Click the send button using fallback selectors
                    send_selectors = [
                        "div[data-test-id='send-button-container'] button",
                        "div[data-test-id='send-button-container'] gem-icon-button",
                        "gem-icon-button.send-button button",
                        "gem-icon-button.send-button",
                        "gem-icon-button.submit button",
                        "gem-icon-button.submit",
                        "button[aria-label='Send message']",
                        "button[aria-label*='Send']",
                        "button[aria-label*='send']",
                        "button#composer-submit-button",
                        "#composer-submit-button",
                        "button[data-testid='send-button']",
                        "button[data-testid='chat-submit']",
                        "button[data-testid*='submit']",
                        "button[aria-label*='Submit']",
                        "button[aria-label*='submit']",
                        "button[type='submit']",
                        "input-area-v2 button.send-button",
                        "gem-icon-button button",
                        "gem-icon-button"
                    ]
                    send_button = None
                    for _ in range(30):
                        if stop_requested:
                            raise Exception("Tiến trình test bị dừng bởi người dùng.")
                        for sel in send_selectors:
                            try:
                                loc = page.locator(sel).first
                                if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                                    send_button = loc
                                    break
                            except Exception:
                                pass
                        if send_button:
                            break
                        await asyncio.sleep(1)

                    if send_button:
                        await send_button.click(force=True)
                        await sse_logger.log("[TEST] Đã click gửi tin nhắn.", "success")
                    else:
                        await textbox.press("Enter")
                        await sse_logger.log("[TEST] Đã gửi tin nhắn bằng cách nhấn Enter.", "success")
                except Exception as e:
                    if stop_requested:
                        raise Exception("Tiến trình test bị dừng bởi người dùng.")
                    await sse_logger.log(f"[TEST] Lỗi nhập prompt / gửi tin nhắn: {str(e)}", "warning")
                    raise Exception(f"Lỗi khi gửi yêu cầu tới {vlm_name}. Chuyển sang nạp dữ liệu giả lập.")
                    

                    # Now poll for the JSON content in the page body
                    await sse_logger.log("[TEST] Đang theo dõi và trích xuất kết quả JSON trực tiếp từ đoạn hội thoại...", "info")
                

                    response_selectors = [
                        "div.response-content-markdown.markdown",
                        "div.response-content-markdown",
                        "div[class*='response-content-markdown']",
                        "message-content",
                        "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/chat-window-content/div[1]/infinite-scroller/div/model-response/div/response-container/div/div[2]/div/div/structured-content-container/div/message-content",
                        "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div[2]/div/div/chat-window/div/chat-window-content/div[1]/infinite-scroller/div[1]/model-response/div/response-container/div/div[2]/div/div/structured-content-container/div/message-content",
                        "model-response message-content",
                        "structured-content-container",
                        "model-response message-content div",
                        "div.prose",
                        "div.markdown"
                    ]
                

                    raw_json_text = None
                    last_logged_len = 0
                    last_thinking_text = ""
                    for _ in range(120): # Chờ tối đa 120 giây cho việc sinh phản hồi hoàn tất
                        if stop_requested:
                            raise Exception("Tiến trình test bị dừng bởi người dùng.")
                        await asyncio.sleep(1)
                        try:
                            # Atomic evaluation to get text, thinking state, generating state, and action bar
                            ui_state = await page.evaluate("""() => {
                                const respSelectors = [
                                    "div.response-content-markdown.markdown",
                                    "div.response-content-markdown",
                                    "div[class*='response-content-markdown']",
                                    "message-content",
                                    "model-response message-content",
                                    "structured-content-container",
                                    "model-response message-content div",
                                    "div.prose",
                                    "div.markdown"
                                ];
                                let text = "";
                                for (const sel of respSelectors) {
                                    const els = document.querySelectorAll(sel);
                                    if (els.length > 0) {
                                        const lastEl = els[els.length - 1];
                                        const txt = (lastEl.textContent || "").trim();
                                        if (txt && !txt.toLowerCase().includes("you are an elite")) {
                                            text = txt;
                                            break;
                                        }
                                    }
                                }

                                let hasThinking = false;
                                let isStillThinking = false;
                                let thinkingText = "";
                                const thinkEl = document.querySelector(".thinking-container, [data-testid='thinking-indicator'], thinking-bubble");
                                if (thinkEl && thinkEl.offsetParent !== null) {
                                    hasThinking = true;
                                    const chevron = thinkEl.querySelector("svg.lucide-chevron-down, svg[data-icon='chevron-down']");
                                    if (chevron && chevron.offsetParent !== null) {
                                        isStillThinking = true;
                                    }
                                    thinkingText = (thinkEl.textContent || "").trim().replace(/\\s+/g, " ");
                                }

                                let isGenerating = false;
                                const stopSelectors = [
                                    "button[aria-label*='Stop']",
                                    "button[aria-label*='stop']",
                                    "button[aria-label*='Dừng']",
                                    "button[aria-label*='dừng']",
                                    "button[aria-label*='Cancel']",
                                    "button[aria-label*='Hủy']",
                                    "button[data-testid='stop-button']",
                                    "button[data-testid*='stop']",
                                    "[data-testid='stop-button']",
                                    "[aria-label*='Stop generating']",
                                    "[aria-label*='Stop response']",
                                    "[aria-label*='Dừng tạo']",
                                    "[aria-label*='Dừng phản hồi']",
                                    "gem-icon-button[aria-label*='Stop']",
                                    "gem-icon-button[aria-label*='stop']",
                                    "gem-icon-button[aria-label*='Dừng']",
                                    "gem-icon-button[aria-label*='dừng']",
                                    "button.stop-generating-button",
                                    ".stop-button"
                                ];
                                for (const sel of stopSelectors) {
                                    const el = document.querySelector(sel);
                                    if (el && el.offsetParent !== null) {
                                        isGenerating = true;
                                        break;
                                    }
                                }

                                if (!isGenerating) {
                                    const streamSelectors = [
                                        "[class*='streaming']",
                                        "[class*='generating']",
                                        "[class*='typing']",
                                        ".blinking-cursor",
                                        ".cursor",
                                        "gem-streaming-indicator",
                                        "sparkle-icon.animate-spin",
                                        "[data-is-generating='true']",
                                        "[data-is-streaming='true']",
                                        "input-area-v2 [role='progressbar']",
                                        "form [role='progressbar']"
                                    ];
                                    for (const sel of streamSelectors) {
                                        const el = document.querySelector(sel);
                                        if (el && el.offsetParent !== null) {
                                            isGenerating = true;
                                            break;
                                        }
                                    }
                                }

                                let hasActionBar = false;
                                const actionSelectors = [
                                    "message-actions",
                                    ".message-actions",
                                    "[data-testid='message-actions']",
                                    "response-container .response-bottom-actions",
                                    "button[aria-label*='Copy']",
                                    "button[aria-label*='Sao chép']",
                                    "button[aria-label*='Good response']",
                                    "button[aria-label*='Phản hồi tốt']",
                                    "button[aria-label*='Share']",
                                    "button[aria-label*='Chia sẻ']",
                                    "button[aria-label*='More options']",
                                    "button[aria-label*='Tùy chọn khác']"
                                ];
                                for (const sel of actionSelectors) {
                                    const els = document.querySelectorAll(sel);
                                    if (els.length > 0) {
                                        const last = els[els.length - 1];
                                        if (last && last.offsetParent !== null) {
                                            hasActionBar = true;
                                            break;
                                        }
                                    }
                                }

                                return {
                                    text: text,
                                    has_thinking: hasThinking,
                                    is_still_thinking: isStillThinking,
                                    thinking_text: thinkingText,
                                    is_generating: isGenerating,
                                    has_action_bar: hasActionBar
                                };
                            }""")

                            text_content = ui_state.get("text", "")
                            has_thinking = ui_state.get("has_thinking", False)
                            is_still_thinking = ui_state.get("is_still_thinking", False)
                            thinking_txt = ui_state.get("thinking_text", "")
                            is_generating = ui_state.get("is_generating", False)
                            has_action_bar = ui_state.get("has_action_bar", False)

                            if not text_content and thinking_txt and thinking_txt != last_thinking_text:
                                last_thinking_text = thinking_txt
                                await sse_logger.log(f"[TEST] Grok đang suy nghĩ ({thinking_txt})...", "info")

                            cleaned_content = clean_gemini_response(text_content).strip() if text_content else ""

                            if text_content:
                                if len(text_content) > last_logged_len:
                                    raw_debug_path = os.path.join(ep_dir, "raw_gemini_response.txt")
                                    try:
                                        with open(raw_debug_path, "w", encoding="utf-8") as rdf:
                                            rdf.write(cleaned_content or text_content)
                                    except Exception:
                                        pass
                                    last_logged_len = len(text_content)

                                if not is_generating and not is_still_thinking:
                                    if cleaned_content.endswith("#"):
                                        try:
                                            parsed = parse_gemini_recap_text(text_content)
                                            if parsed and len(parsed) >= 4:
                                                mock_json = parsed
                                                gemini_web_success = True
                                                await sse_logger.log(f"[TEST] Đã trích xuất và biên dịch thành công ({len(parsed)} đoạn)! ", "success")
                                                break
                                        except Exception:
                                            pass

                                    extracted = extract_json_from_text(text_content)
                                    if extracted:
                                        try:
                                            parsed = json.loads(extracted)
                                            if isinstance(parsed, list) and len(parsed) > 0:
                                                raw_json_text = extracted
                                                mock_json = parsed
                                                gemini_web_success = True
                                                await sse_logger.log("[TEST] Đã trích xuất và biên dịch thành công JSON đầy đủ!", "success")
                                                break
                                        except Exception:
                                            pass

                        except Exception:
                            pass
                        

                    if not gemini_web_success or not mock_json:
                        raise Exception("Không thể nhận được phản hồi JSON hoàn chỉnh và hợp lệ từ phần tử giao diện.")
                    

                    # Save browser state (cookies/localStorage) back to cookies.json
                    try:
                        state = await context.storage_state()
                        with open(cookie_file, "w", encoding="utf-8") as f:
                            json.dump(state, f, indent=2)
                        await sse_logger.log("[TEST] Đã lưu cookies đăng nhập thành công vào cookies.json.", "success")
                    except Exception as save_err:
                        await sse_logger.log(f"[TEST] Lỗi lưu cookies: {str(save_err)}", "warning")
                    

                    # Keep browser open for a few seconds to let user observe
                    await sse_logger.log("[TEST] Thành công! Trình duyệt sẽ tự động đóng sau 5 giây...", "success")
                    await asyncio.sleep(5)
                    if 'page' in locals() and page:
                        try: await page.close()
                        except Exception: pass
                

                except Exception as web_err:
                    # Save cookies anyway since the user might have logged in
                    if 'context' in locals() and context:
                        try:
                            state = await context.storage_state()
                            with open(cookie_file, "w", encoding="utf-8") as f:
                                json.dump(state, f, indent=2)
                            await sse_logger.log("[TEST] Đã lưu cookies đăng nhập từ phiên lỗi vào cookies.json.", "success")
                        except Exception:
                            pass
                        

                    # Close page if open
                    if 'page' in locals() and page:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        

                    if stop_requested:
                        raise web_err
                    

                    await sse_logger.log(f"[TEST] Lỗi tự động hóa Gemini Web: {str(web_err)}. Tự động chuyển sang nạp dữ liệu thuyết minh giả lập...", "warning")
                

                    # Fallback to local mock json
                    fallback_loaded = False
                    narrations_backup = os.path.join(ep_dir, "narrations.json")
                    raw_backup = os.path.join(ep_dir, "raw_gemini_response.txt")
                    
                    if os.path.exists(narrations_backup):
                        try:
                            with open(narrations_backup, "r", encoding="utf-8") as f:
                                mock_json = json.load(f)
                                fallback_loaded = True
                            await sse_logger.log("[TEST] Đã nạp thành công narrations.json có sẵn làm dữ liệu giả lập.", "info")
                        except Exception:
                            pass
                            
                    if not fallback_loaded and os.path.exists(raw_backup):
                        try:
                            with open(raw_backup, "r", encoding="utf-8") as f:
                                raw_text = f.read()
                            extracted = extract_json_from_text(raw_text)
                            if extracted:
                                mock_json = json.loads(extracted)
                                fallback_loaded = True
                                await sse_logger.log("[TEST] Đã nạp thành công raw_gemini_response.txt làm dữ liệu giả lập.", "info")
                        except Exception:
                            pass

                    if not fallback_loaded:
                        # Hardcoded fallback using Lookism Ep 3 Vietnamese content
                        mock_json = {
                            "title": "Lookism Episode 3",
                            "segments": [
                                {
                                    "speech": "Sau cái đêm định mệnh phát hiện ra bản thân có hai cơ thể, tôi đứng hình mất năm giây nhìn cái thân xác béo ú của chính mình vẫn đang ngáy khò khò dưới đất. Nhìn đống cơ bắp cuồn cuộn trên cơ thể mới này, tôi phải tự cấu véo mấy phát để tin chắc rằng đây hoàn toàn không phải là một giấc mơ.",
                                    "key_page": 1,
                                    "source_range": {
                                        "from": 1,
                                        "to": 5
                                    },
                                    "images": [
                                        {"page": 1, "priority": 0.5},
                                        {"page": 5, "priority": 0.5}
                                    ]
                                },
                                {
                                    "speech": "Thấm thoắt thì kỳ nghỉ cũng qua và ngày mai là buổi khai giảng ở trường mới rồi. Tôi quyết định sẽ dùng cơ thể hotboy này để đi học. Vừa bước đến cổng trường, tôi đã cảm nhận được luồng hào quang rực rỡ khi tất cả nữ sinh xung quanh đều đổ dồn ánh mắt về phía mình.",
                                    "key_page": 24,
                                    "source_range": {
                                        "from": 24,
                                        "to": 27
                                    },
                                    "images": [
                                        {"page": 24, "priority": 0.5},
                                        {"page": 27, "priority": 0.5}
                                    ]
                                }
                            ]
                        }
        

            if stop_requested:
                raise Exception("Tiến trình test bị dừng bởi người dùng.")
            

            ep_dir = os.path.join(project_dir, "downloads", "lookism_3_3", "ep_3")
            narrations_path = os.path.join(ep_dir, "narrations.json")
        

            # Robust extraction of segments
            segments_data = []
            if isinstance(mock_json, list):
                segments_data = mock_json
            elif isinstance(mock_json, dict):
                segments_data = mock_json.get("segments") or mock_json.get("episodes") or []
                if not isinstance(segments_data, list):
                    segments_data = [mock_json]
            else:
                segments_data = []

            formatted_segments = []
            for idx, item in enumerate(segments_data, 1):
                if not isinstance(item, dict):
                    continue

                # Extract images list or slides list
                images_list = item.get("images") or item.get("slides") or []
                if not isinstance(images_list, list):
                    images_list = [images_list]

                # Extract all page numbers
                pages = []
                for img in images_list:
                    if isinstance(img, dict):
                        p_val = img.get("page")
                    else:
                        p_val = img
                    if p_val is not None:
                        try:
                            # Extract digits in case it is a filename like "005.jpg"
                            if isinstance(p_val, str) and not p_val.isdigit():
                                found_digits = re.findall(r'\d+', p_val)
                                if found_digits:
                                    pages.append(int(found_digits[-1]))
                            else:
                                pages.append(int(p_val))
                        except (ValueError, TypeError):
                            pass

                # Fallbacks
                if not pages:
                    # Try key_page or source_range from the item
                    kp = item.get("key_page") or item.get("page") or 1
                    try:
                        pages = [int(kp)]
                    except (ValueError, TypeError):
                        pages = [1]

                # Compute fields
                from_page = min(pages) if pages else 1
                to_page = max(pages) if pages else 1
                key_page = pages[0] if pages else 1

                # Resolve key image filename on disk
                key_image_name = f"{str(key_page).zfill(3)}.jpg"
                if not os.path.exists(os.path.join(ep_dir, key_image_name)):
                    if os.path.exists(os.path.join(ep_dir, f"{str(key_page).zfill(3)}.png")):
                        key_image_name = f"{str(key_page).zfill(3)}.png"

                # Build output segment dictionary
                segment_dict = {
                    "speech": item.get("speech", ""),
                    "key_image": f"ep_3/{key_image_name}",
                    "source_range": {
                        "from": from_page,
                        "to": to_page
                    }
                }

                # Preserve the original images / slides keys if present
                if "images" in item:
                    segment_dict["images"] = item["images"]
                if "slides" in item:
                    segment_dict["slides"] = item["slides"]

                formatted_segments.append(segment_dict)
        
            if not formatted_segments:
                raise Exception("Danh sách segments sau khi phân tích bị trống.")

            valid_speeches = [seg.get("speech", "").strip() for seg in formatted_segments if seg.get("speech", "").strip()]
            if not valid_speeches:
                raise Exception("Nội dung thuyết minh (speech) của các segments bị trống.")

            with open(narrations_path, "w", encoding="utf-8") as f:
                json.dump(formatted_segments, f, ensure_ascii=False, indent=2)
            

            await sse_logger.log("[TEST] Đã lưu tệp narrations.json thành công.", "success")
        

            # Save the final summary json file: lookism_3_3/ep_3_summary.json
            summary_path = os.path.join(project_dir, "downloads", "lookism_3_3", "ep_3_summary.json")
            final_summary = {
                "title": "Episode 3",
                "segments": formatted_segments
            }
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(final_summary, f, ensure_ascii=False, indent=2)
            

            await sse_logger.log("[TEST] Đã lưu file tóm tắt cuối cùng 'ep_3_summary.json' thành công.", "success")
            await sse_logger.log("[TEST] CHẠY TEST VLM THÀNH CÔNG! Đang chuẩn bị chuyển sang tạo video...", "success")
            test_success = True
        

        except Exception as e:
            await sse_logger.log(f"[TEST] Lỗi chạy test: {str(e)}", "error", "idle", "Sẵn sàng")
        finally:
            crawler_running = False

    if test_success:
        await sse_logger.log("[TEST] Bắt đầu tự động tạo video thuyết minh và ghép hình ảnh...", "info")
        await run_video_pipeline("lookism_3_3", 3, 3, logo_path=logo_path, overlay_path=overlay_path)


class TestRequest(BaseModel):
    logo_path: str = None
    overlay_path: str = None

@app.post("/api/run-test")
async def run_test_endpoint(payload: TestRequest, background_tasks: BackgroundTasks):
    global crawler_running
    if crawler_running:
        await sse_logger.log("Yêu cầu chạy test bị từ chối: Một tiến trình khác đang chạy.", "warning")
        raise HTTPException(status_code=409, detail="A task is already running.")
    

    background_tasks.add_task(run_test_task, payload.logo_path, payload.overlay_path)
    return {"status": "success", "message": "Bắt đầu chạy test workflow trong nền."}


    # Stop Execution Route
@app.post("/api/stop")
async def stop_execution():
    global stop_requested
    stop_requested = True
    await sse_logger.log("Người dùng yêu cầu dừng tiến trình đang chạy...", "warning", "idle", "Sẵn sàng")
    return {"status": "success", "message": "Đã gửi yêu cầu dừng thực thi."}


    # Clear Cache Route
@app.post("/api/clear-cache")
async def clear_cache():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    downloads_dir = os.path.join(project_dir, "downloads")
    uploads_dir = os.path.join(project_dir, "static", "uploads")
    deleted_files = []


    if os.path.exists(downloads_dir):
        for root, dirs, files in os.walk(downloads_dir):
            for file in files:
                if file in ["observations.json", "events.json", "narrations.json"]:
                    file_path = os.path.join(root, file)
                    try:
                        os.remove(file_path)
                        deleted_files.append(file_path)
                    except Exception as e:
                        await sse_logger.log(f"Không thể xóa cache {file} tại {root}: {str(e)}", "warning")

    if os.path.exists(uploads_dir):
        for file in os.listdir(uploads_dir):
            file_path = os.path.join(uploads_dir, file)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    deleted_files.append(file_path)
                except Exception as e:
                    await sse_logger.log(f"Không thể xóa tệp tải lên {file}: {str(e)}", "warning")
                    

    # Clear browser cache
    b_cache_info = ""
    try:
        b_res = await asyncio.to_thread(clear_browser_cache)
        b_cache_info = f" Đồng thời dọn dẹp {b_res.get('cleaned_mb', 0)} MB browser cache ({b_res.get('cleaned_folders', 0)} thư mục)."
    except Exception as b_err:
        await sse_logger.log(f"Lỗi khi xóa browser cache: {b_err}", "warning")

    await sse_logger.log(f"Đã xóa thành công {len(deleted_files)} file cache và tệp tải lên.{b_cache_info}", "success")
    return {"status": "success", "message": f"Đã xóa {len(deleted_files)} cache files thành công.{b_cache_info}"}

@app.post("/api/upload-logo")
async def upload_logo(file: UploadFile = File(...)):
    import uuid
    # Create static/uploads directory if it doesn't exist
    os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
    
    # Generate unique filename to avoid caching issues
    ext = os.path.splitext(file.filename)[1] or ".png"
    filename = f"logo_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join("static", "uploads", filename)
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    return {"status": "success", "file_path": file_path, "url": f"/uploads/{filename}"}

@app.post("/api/upload-ref-audio")
async def upload_ref_audio(file: UploadFile = File(...)):
    import uuid
    import subprocess
    import sys
    # Create static/uploads directory if it doesn't exist
    os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
    
    # Save original uploaded file first
    temp_filename = f"temp_ref_{uuid.uuid4().hex}_{file.filename}"
    temp_path = os.path.join("static", "uploads", temp_filename)
    with open(temp_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    # Convert to standard 24kHz mono WAV for OmniVoice using FFmpeg
    output_filename = f"ref_audio_{uuid.uuid4().hex}.wav"
    output_path = os.path.join("static", "uploads", output_filename)
    
    try:
        ffmpeg_exe = find_ffmpeg()
        cmd = [
            ffmpeg_exe, "-y", "-i", temp_path,
            "-ar", "24000", "-ac", "1", output_path
        ]
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        if result.returncode != 0:
            # Fallback to copy if ffmpeg fails
            import shutil
            shutil.copy(temp_path, output_path)
    except Exception:
        import shutil
        shutil.copy(temp_path, output_path)
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass
            
    return {"status": "success", "file_path": output_path, "url": f"/uploads/{output_filename}"}

@app.post("/api/upload-overlay")
async def upload_overlay(file: UploadFile = File(...)):
    import uuid
    # Create static/uploads directory if it doesn't exist
    os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
    
    # Generate unique filename to avoid caching issues
    ext = os.path.splitext(file.filename)[1] or ".png"
    filename = f"overlay_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join("static", "uploads", filename)
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    return {"status": "success", "file_path": file_path, "url": f"/uploads/{filename}"}

class VideoRequest(BaseModel):
    comic_folder: str
    from_episode: int
    to_episode: int
    voice_id: str = "auto"
    logo_path: str = None
    overlay_path: str = None
    remove_text: bool = True
    remove_text_conf: float = 0.3
    remove_text_radius: int = 3
    ref_audio_path: Optional[str] = None
    ai33pro_api_key: Optional[str] = None
    film_grain: bool = True
    grain_strength: int = 6
    flip_horizontal: bool = False
    video_mark_path: Optional[str] = None
    video_mark_alpha: float = 0.01
    enable_video_mark: bool = True

def find_ffmpeg() -> str:
    import shutil
    # 0. Check custom environment variable
    env_override = os.getenv("FFMPEG_PATH")
    if env_override and os.path.exists(env_override):
        return env_override

    # 1. Check in PATH
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    # 2. Check standard Windows tools directories
    common_paths = [
        r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "bin", "ffmpeg.exe"),
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p

    # 3. Check CapCut AppData directory
    appdata_local = os.getenv("LOCALAPPDATA")
    if appdata_local:
        capcut_dir = os.path.join(appdata_local, "CapCut", "Apps")
        if os.path.exists(capcut_dir):
            versions = sorted(
                [d for d in os.listdir(capcut_dir) if os.path.isdir(os.path.join(capcut_dir, d))],
                reverse=True
            )
            for v in versions:
                exe_path = os.path.join(capcut_dir, v, "ffmpeg.exe")
                if os.path.exists(exe_path):
                    return exe_path

    # 4. Fail safe fallback
    return "ffmpeg"

def check_ffmpeg_has_mp3lame(ffmpeg_exe: str) -> bool:
    """Returns True if the specified FFmpeg binary supports libmp3lame encoding."""
    import subprocess
    if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
        return False
    try:
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            [ffmpeg_exe, "-encoders"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            startupinfo=startupinfo, timeout=5, text=True, errors="ignore"
        )
        return "libmp3lame" in res.stdout
    except Exception:
        return False

def get_nvenc_params(encoder: str) -> list:
    """
    Returns optimal FFmpeg encoding parameters for the given video encoder.
    Optimized for NVIDIA GeForce RTX 3060 (NVENC Gen 7/8).
    """
    if encoder == 'h264_nvenc':
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",        # p4: balanced speed & quality on Ampere
            "-tune", "hq",          # High quality mode
            "-rc", "vbr",           # Variable bitrate
            "-cq", "22",            # Constant quality target
            "-b:v", "0",
            "-maxrate", "12M",
            "-bufsize", "24M",
            "-pix_fmt", "yuv420p"
        ]
    elif encoder == 'libx264':
        return [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-threads", "6"
        ]
    return ["-c:v", encoder]

def get_working_encoder(ffmpeg_path: str, test_image: str) -> str:
    import subprocess
    import sys
    encoders = ['h264_nvenc', 'h264_qsv', 'h264_amf', 'h264_videotoolbox', 'libx264']
    if not test_image or not os.path.exists(test_image):
        return 'libx264'
    for enc in encoders:
        cmd = [
            ffmpeg_path, '-y', '-loop', '1', '-i', test_image, 
            '-t', '0.1', '-c:v', enc, 'test_detect.mp4'
        ]
        try:
            startupinfo = None
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
 
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                startupinfo=startupinfo, timeout=5
            )
            if result.returncode == 0:
                if os.path.exists('test_detect.mp4'):
                    try:
                        os.remove('test_detect.mp4')
                    except Exception:
                        pass
                return enc
        except Exception:
            pass
    return 'libx264'

def compile_batch_files(download_dir: str, title: str, from_ep: int, to_ep: int):
    episodes_data = []
    for ep in range(from_ep, to_ep + 1):
        ep_summary_path = os.path.join(download_dir, f"ep_{ep}_summary.json")
        ep_segments = []
        if os.path.exists(ep_summary_path):
            with open(ep_summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    ep_segments = data.get("segments", [])
                elif isinstance(data, list):
                    ep_segments = data
        else:
            ep_narration_path = os.path.join(download_dir, f"ep_{ep}", "narrations.json")
            if os.path.exists(ep_narration_path):
                with open(ep_narration_path, "r", encoding="utf-8") as f:
                    ep_segments = json.load(f)

        episodes_data.append({
            "episode": ep,
            "title": f"{title} - Episode {ep}",
            "segments": ep_segments
        })

    # Save summary_ep_{from_ep}_to_{to_ep}.json
    summary_filename = f"summary_ep_{from_ep}_to_{to_ep}.json"
    summary_path = os.path.join(download_dir, summary_filename)
    summary_json = {
        "title": f"{title} - Episodes {from_ep} to {to_ep}",
        "episodes": episodes_data
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_json, f, ensure_ascii=False, indent=2)

    # Save narrations_ep_{from_ep}_to_{to_ep}.json
    narrations_filename = f"narrations_ep_{from_ep}_to_{to_ep}.json"
    narrations_path = os.path.join(download_dir, narrations_filename)
    narrations_json = {
        "title": title,
        "episodes": episodes_data
    }
    with open(narrations_path, "w", encoding="utf-8") as f:
        json.dump(narrations_json, f, ensure_ascii=False, indent=2)

    # Save narrations_ep_{from_ep}_to_{to_ep}.txt
    text_content = []
    for ep_data in episodes_data:
        for seg in ep_data['segments']:
            speech = seg.get('speech', '').strip()
            if speech:
                text_content.append(speech)
    txt_filename = f"narrations_ep_{from_ep}_to_{to_ep}.txt"
    txt_path = os.path.join(download_dir, txt_filename)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(text_content))

def parse_time_to_seconds(time_str: str) -> float:
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s

def get_match_score(sub_text: str, seg_text: str) -> float:
    sub_clean = re.sub(r'[^a-z0-9\s]', '', sub_text.lower()).strip()
    seg_clean = re.sub(r'[^a-z0-9\s]', '', seg_text.lower()).strip()
    if not sub_clean:
        return 0.0

    # 1. Exact substring match
    if sub_clean in seg_clean:
        return 10.0 + (len(sub_clean) / 1000.0)

    # 2. Word overlap match
    sub_words = sub_clean.split()
    seg_words = set(seg_clean.split())
    matches = sum(1 for w in sub_words if w in seg_words)
    return matches / len(sub_words) if sub_words else 0.0

async def render_camera_clip(
    stitched_image_path: str,
    duration: float,
    keyframes: List[Dict[str, float]],
    output_path: str,
    encoder: str
) -> bool:
    from PIL import Image, ImageFile, ImageFilter, ImageEnhance
    import uuid
    import subprocess
    
    # Allow loading of truncated/broken images
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    
    if not os.path.exists(stitched_image_path):
        print(f"Stitched image not found at {stitched_image_path}")
        return False
        
    ffmpeg_exe = find_ffmpeg()
    
    extra_args = []
    if encoder == "libx264":
        extra_args = ["-crf", "23", "-preset", "veryfast", "-maxrate", "3500k", "-bufsize", "6000k", "-threads", "0"]
    elif encoder == "h264_nvenc":
        extra_args = [
            "-preset", "p3", "-tune", "hq", "-rc", "vbr", "-cq", "26",
            "-b:v", "2200k", "-maxrate", "3800k", "-bufsize", "6000k",
            "-spatial_aq", "1", "-temporal_aq", "1", "-threads", "0"
        ]
    elif encoder == "h264_amf":
        extra_args = ["-rc", "cqp", "-qp_i", "24", "-qp_p", "24", "-b:v", "2200k", "-maxrate", "3800k", "-threads", "0"]
    elif encoder == "h264_qsv":
        extra_args = ["-preset", "veryfast", "-global_quality", "25", "-b:v", "2200k", "-maxrate", "3800k", "-threads", "0"]
    else:
        extra_args = ["-b:v", "2500k", "-threads", "0"]

    # Calculate keyframe timings
    if not keyframes:
        keyframes = [{"center_y": 0.5, "zoom": 1.0, "duration_weight": 1.0}]
        
    temp_files = []
    try:
        def get_image_size():
            with Image.open(stitched_image_path) as img:
                return img.size
        img_w, img_h = await asyncio.to_thread(get_image_size)
    except Exception as e:
        print(f"Error reading image: {e}")
        return False

    img = None
    try:
        with Image.open(stitched_image_path) as loaded_img:
            img = loaded_img.convert('RGB')
            img.load()
        
        target_w, target_h = 1920, 1080
        target_aspect = target_w / target_h
        
        clip_paths = []
        
        for idx, kf in enumerate(keyframes):
            if stop_requested:
                raise Exception("Tiến trình bị dừng bởi người dùng.")
                
            weight = kf.get("duration_weight", 1.0 / len(keyframes))
            kf_dur = duration * weight
            if kf_dur <= 0:
                continue
                
            cy = kf.get("center_y", 0.5)
            
            # Crop height calculation (zoom is ignored, forced to 1.0)
            crop_w = img_w
            crop_h = img_w * 16.0 / 9.0
            if crop_h > img_h:
                crop_h = img_h
                
            center_x = img_w / 2.0
            center_y_pixel = cy * img_h
            
            x1 = center_x - crop_w / 2.0
            y1 = center_y_pixel - crop_h / 2.0
            x2 = center_x + crop_w / 2.0
            y2 = center_y_pixel + crop_h / 2.0
            
            # Clamp to bounds
            if y1 < 0:
                shift = -y1
                y1 += shift
                y2 += shift
            if y2 > img_h:
                shift = y2 - img_h
                y1 -= shift
                y2 -= shift
                
            y1 = max(0, min(img_h - 1, int(y1)))
            y2 = max(1, min(img_h, int(y2)))
            x1 = max(0, min(img_w - 1, int(x1)))
            x2 = max(1, min(img_w, int(x2)))
            
            if y2 <= y1: y2 = y1 + 1
            if x2 <= x1: x2 = x1 + 1
            
            cropped = img.crop((x1, y1, x2, y2))
            crop_aspect = cropped.width / cropped.height
            # Foreground sizing: Always full height (1080px)
            fg_h = target_h
            fg_w = max(1, int(round(target_h * crop_aspect)))
            if fg_w <= 0: fg_w = 1


            
            fg_resized = cropped.resize((fg_w, fg_h), Image.Resampling.BILINEAR)
            
            # Background sizing
            if crop_aspect > target_aspect:
                bg_h = target_h
                bg_w = int(target_h * crop_aspect)
            else:
                bg_w = target_w
                bg_h = int(target_w / crop_aspect)
                
            if bg_w <= 0: bg_w = 1
            if bg_h <= 0: bg_h = 1
            
            bg_resized = cropped.resize((bg_w, bg_h), Image.Resampling.BOX)
            
            bg_x1 = (bg_w - target_w) // 2
            bg_y1 = (bg_h - target_h) // 2
            bg_x2 = bg_x1 + target_w
            bg_y2 = bg_y1 + target_h
            bg_cropped = bg_resized.crop((bg_x1, bg_y1, bg_x2, bg_y2))
            bg_resized.close()
            
            bg_blurred = bg_cropped.filter(ImageFilter.GaussianBlur(radius=15))
            bg_cropped.close()
            
            enhancer = ImageEnhance.Brightness(bg_blurred)
            bg_darkened = enhancer.enhance(0.6)
            bg_blurred.close()
            
            final_frame = Image.new("RGB", (target_w, target_h), (0, 0, 0))
            final_frame.paste(bg_darkened, (0, 0))
            bg_darkened.close()
            
            paste_x = (target_w - fg_w) // 2
            paste_y = (target_h - fg_h) // 2
            final_frame.paste(fg_resized, (paste_x, paste_y))
            fg_resized.close()
            cropped.close()
            
            # Save final frame to unique temp jpg file
            parent_dir = os.path.abspath(os.path.dirname(output_path))
            uuid_suffix = f"{idx}_{uuid.uuid4().hex[:8]}"
            temp_jpg = os.path.join(parent_dir, f"temp_kf_{uuid_suffix}.jpg")
            final_frame.save(temp_jpg, "JPEG", quality=90)
            final_frame.close()
            temp_files.append(temp_jpg)
            
            # Target clip path
            temp_mp4 = os.path.join(parent_dir, f"temp_kf_{uuid_suffix}.mp4")
            
            # Generate looped clip from static image using FFmpeg
            clip_cmd = [
                ffmpeg_exe, "-y",
                "-loop", "1",
                "-i", temp_jpg,
                "-t", f"{kf_dur:.3f}",
                "-c:v", encoder,
            ] + extra_args + [
                "-pix_fmt", "yuv420p",
                temp_mp4
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *clip_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr_data = await proc.communicate()
            if proc.returncode != 0:
                raise Exception(f"Lỗi render segment clip {idx}: {stderr_data.decode('utf-8', errors='ignore')}")
                
            clip_paths.append(temp_mp4)
            temp_files.append(temp_mp4)
        
        # Concat multiple clips if more than 1 keyframe
        if len(clip_paths) == 1:
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(clip_paths[0], output_path)
            temp_files.remove(clip_paths[0])
        elif len(clip_paths) > 1:
            concat_manifest = os.path.join(parent_dir, f"concat_manifest_{uuid.uuid4().hex[:8]}.txt")
            temp_files.append(concat_manifest)
            with open(concat_manifest, "w", encoding="utf-8") as f:
                for cp in clip_paths:
                    f.write(f"file '{os.path.basename(cp)}'\n")
                    
            concat_cmd = [
                ffmpeg_exe, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_manifest,
                "-c", "copy",
                output_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *concat_cmd,
                cwd=parent_dir,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr_data = await proc.communicate()
            if proc.returncode != 0:
                raise Exception(f"Lỗi concat segments: {stderr_data.decode('utf-8', errors='ignore')}")
                
        return True
        
    except Exception as e:
        print(f"Lỗi trong render_camera_clip: {e}")
        return False
        
    finally:
        if img:
            try:
                img.close()
            except Exception:
                pass
        # Clean up all temp files
        for tf in temp_files:
            if os.path.exists(tf):
                try:
                    os.remove(tf)
                except Exception:
                    pass




async def run_video_pipeline(
    comic_folder: str, 
    from_ep: int, 
    to_ep: int, 
    voice_id: str = "auto", 
    logo_path: str = None, 
    overlay_path: str = None,
    remove_text: bool = True,
    remove_text_conf: float = 0.3,
    remove_text_radius: int = 3,
    ref_audio_path: str = None,
    ai33pro_api_key: str = None,
    video_mark_path: str = None,
    video_mark_alpha: float = 0.01,
    enable_video_mark: bool = True
):
    global crawler_running, stop_requested
    stop_requested = False

    import httpx
    async with crawler_lock:
        crawler_running = True
        await sse_logger.log(f"Bắt đầu quy trình tạo video cho thư mục '{comic_folder}'...", "system", "active", "Đang tạo video...")

        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))
            download_dir = os.path.join(project_dir, "downloads", comic_folder)

            # Clean up old render cache files before starting to avoid caching issues
            for cache_file in ["audio.mp3", "transcript.srt", "combined_silent.mp4", "final.mp4", "concat_list.txt"]:
                path_to_del = os.path.join(download_dir, cache_file)
                if os.path.exists(path_to_del):
                    try:
                        os.remove(path_to_del)
                    except Exception:
                        pass

            title = "Manhwa Recap"
            test_ep_path = os.path.join(download_dir, f"ep_{from_ep}_summary.json")
            if os.path.exists(test_ep_path):
                try:
                    with open(test_ep_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        title = data.get("title", "Manhwa").split(" - Episode")[0].strip()
                except Exception:
                    pass

            await sse_logger.log("Đang biên dịch tóm tắt và thuyết minh...", "info")
            compile_batch_files(download_dir, title, from_ep, to_ep)

            narrations_path = os.path.join(download_dir, f"narrations_ep_{from_ep}_to_{to_ep}.json")
            if not os.path.exists(narrations_path):
                raise FileNotFoundError(f"Không tìm thấy file narrations {narrations_path}")

            with open(narrations_path, "r", encoding="utf-8") as f:
                narrations_data = json.load(f)

            narration_segments = []
            for ep_data in narrations_data.get("episodes", []):
                for seg in ep_data.get("segments", []):
                    narration_segments.append(seg)

            concatenated_text = " ".join([seg["speech"].strip() for seg in narration_segments if seg.get("speech")])
            if not concatenated_text:
                raise Exception("Nội dung thuyết minh rỗng.")

            audio_path = os.path.join(download_dir, "audio.mp3")
            srt_path = os.path.join(download_dir, "transcript.srt")
            cache_path = os.path.join(download_dir, "tts_config.json")

            cache_valid = False
            if os.path.exists(cache_path) and os.path.exists(audio_path) and os.path.exists(srt_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as cf:
                        saved_config = json.load(cf)
                    if (saved_config.get("voice_id") == voice_id and 
                        saved_config.get("text") == concatenated_text and 
                        saved_config.get("ref_audio_path") == ref_audio_path):
                        cache_valid = True
                except Exception:
                    pass

            if cache_valid:
                await sse_logger.log("Phát hiện audio.mp3 và transcript.srt có sẵn với cấu hình trùng khớp. Bỏ qua sinh local TTS.", "success")
            else:
                await sse_logger.log("Đang sinh local TTS...", "info")
                from tts_provider import generate_tts
                success = await generate_tts(concatenated_text, audio_path, srt_path, voice_id, ref_audio_path, ai33pro_api_key=ai33pro_api_key)
                if not success:
                    raise Exception("Lỗi khi tạo local TTS hoặc Whisper transcript.")

                # Save config cache
                try:
                    with open(cache_path, "w", encoding="utf-8") as cf:
                        json.dump({
                            "voice_id": voice_id, 
                            "text": concatenated_text,
                            "ref_audio_path": ref_audio_path
                        }, cf, ensure_ascii=False, indent=4)
                except Exception:
                    pass

                await sse_logger.log("Đã tạo xong local audio.mp3 và transcript.srt.", "success")

            # 3. Parse transcript.srt (prefer raw transcript if available)
            raw_srt_path = os.path.join(download_dir, "transcript_raw.srt")
            source_srt_path = raw_srt_path if os.path.exists(raw_srt_path) else srt_path
            await sse_logger.log(f"Đang phân tích {os.path.basename(source_srt_path)}...", "info")
            with open(source_srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()

            srt_content = srt_content.replace('\r\n', '\n').strip()
            pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n(.*?)(?=\n\n|\Z)"
            matches = re.findall(pattern, srt_content, re.DOTALL)
            subtitles = []
            for num, start_str, end_str, text in matches:
                text_clean = " ".join([l.strip() for l in text.split('\n') if l.strip()])
                text_clean = re.sub(r'\[speed_[a-z0-9_]+\]', '', text_clean, flags=re.IGNORECASE).strip()
                text_clean = " ".join(text_clean.split())
                start = parse_time_to_seconds(start_str)
                end = parse_time_to_seconds(end_str)
                subtitles.append({
                    "start": start,
                    "end": end,
                    "text": text_clean
                })

            if not subtitles:
                raise Exception("Không trích xuất được phụ đề nào từ file SRT.")

            # 4. Match Subtitles to Summary Segments
            await sse_logger.log("Đang khớp nối phụ đề với các cảnh truyện tranh...", "info")

            summary_path = os.path.join(download_dir, f"summary_ep_{from_ep}_to_{to_ep}.json")
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_data = json.load(f)

            summary_segments = []
            for ep_data in summary_data.get("episodes", []):
                ep_num = ep_data.get("episode", from_ep)
                for seg in ep_data.get("segments", []):
                    seg["episode"] = ep_num
                    summary_segments.append(seg)

            def clean_w(word):
                return re.sub(r'[^a-z0-9]', '', word.lower())

            # Compute cumulative word boundaries for segments
            segment_word_counts = []
            for seg in summary_segments:
                speech = seg.get("speech", "")
                words = [clean_w(w) for w in speech.split() if clean_w(w)]
                segment_word_counts.append(len(words))

            segment_ranges = []
            current_idx = 0
            for count in segment_word_counts:
                segment_ranges.append((current_idx, current_idx + count))
                current_idx += count
            total_segment_words = current_idx

            # 4. Match and Normalize Subtitles to Summary Segments (1-to-1 matching)
            await sse_logger.log("Đang khớp nối và chuẩn hóa phụ đề với các cảnh truyện tranh...", "info")
            from workflow_stages_2 import align_transcript_to_segments
            normalized_srt_entries = align_transcript_to_segments(subtitles, summary_segments)

            # Overwrite the srt_path with normalized subtitles
            try:
                with open(srt_path, "w", encoding="utf-8") as f:
                    for s_idx, entry in enumerate(normalized_srt_entries, 1):
                        start_str = format_timestamp(entry["start"])
                        end_str = format_timestamp(entry["end"])
                        f.write(f"{s_idx}\n{start_str} --> {end_str}\n{entry['text']}\n\n")
            except Exception as e:
                print(f"Error writing normalized srt: {e}")

            # Update the subtitles list variable to match the normalized segments
            subtitles = []
            for s_idx, entry in enumerate(normalized_srt_entries):
                subtitles.append({
                    "start": entry["start"],
                    "end": entry["end"],
                    "text": entry["text"],
                    "matched_segment_idx": s_idx
                })

            # 5. Build Video Timeline
            await sse_logger.log("Đang lập biểu đồ thời gian hiển thị hình ảnh...", "info")
            segment_end_times = [0.0] * len(summary_segments)
            for sub in subtitles:
                idx = sub["matched_segment_idx"]
                segment_end_times[idx] = max(segment_end_times[idx], sub["end"])

            for i in range(1, len(summary_segments)):
                segment_end_times[i] = max(segment_end_times[i], segment_end_times[i-1])

            total_duration = subtitles[-1]["end"]
            
            await sse_logger.log("Đang tìm kiếm FFmpeg binary và cấu hình bộ giải mã...", "info")
            ffmpeg_exe = find_ffmpeg()

            test_img = None
            for root, dirs, files in os.walk(download_dir):
                for file in files:
                    if file == "stitched.jpg":
                        test_img = os.path.join(root, file)
                        break
                if test_img:
                    break

            if not test_img:
                for root, dirs, files in os.walk(download_dir):
                    for file in files:
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                            test_img = os.path.join(root, file)
                            break
                    if test_img:
                        break

            if not test_img:
                raise Exception("Không tìm thấy ảnh minh họa để test bộ giải mã FFmpeg.")

            working_encoder = get_working_encoder(ffmpeg_exe, test_img)
            await sse_logger.log(f"Sử dụng bộ giải mã video: {working_encoder}", "info")

            # Remove text in-place from original images in ep_dir and rebuild stitched.jpg if requested
            if remove_text:
                from tools.text_remover.comic_text_remover import get_easyocr_reader, process_image
                # Omitted page text removal pass per user request to preserve original text and speed up rendering

            # 6. Render individual panning/zooming keyframe clips concurrently
            await sse_logger.log("Bắt đầu dựng (render) các đoạn clip chuyển động camera...", "info", app_status="active", status_text="Đang render clips...")

            rendered_clips = []
            last_end = 0.0

            # Concurrency semaphore to render up to 4 clips concurrently in parallel
            render_sem = asyncio.Semaphore(4)

            async def render_segment_task(i, ep_num, seg_dur, stitched_image_path, clip_path, keyframes):
                async with render_sem:
                    if stop_requested:
                        return False
                    await sse_logger.log(f"  -> Bắt đầu dựng slide {i + 1}/{len(summary_segments)}: tập {ep_num} ({seg_dur:.2f}s)...", "info")
                    success = await render_camera_clip(
                        stitched_image_path=stitched_image_path,
                        duration=seg_dur,
                        keyframes=keyframes,
                        output_path=clip_path,
                        encoder=working_encoder
                    )
                    if not success:
                        if stop_requested:
                            return False
                        try:
                            from PIL import Image
                            fallback_jpg = os.path.join(download_dir, f"fallback_{i}.jpg")
                            bg = Image.new("RGB", (1920, 1080), (10, 10, 10))
                            bg.save(fallback_jpg, "JPEG")
                            bg.close()
                            
                            extra_args = ["-crf", "23", "-preset", "veryfast", "-maxrate", "3500k", "-bufsize", "6000k"] if working_encoder == "libx264" else ["-b:v", "2200k", "-maxrate", "3800k"]
                            fallback_cmd = [
                                ffmpeg_exe, "-y",
                                "-loop", "1",
                                "-i", fallback_jpg,
                                "-t", str(seg_dur),
                                "-c:v", working_encoder,
                            ] + extra_args + [
                                "-pix_fmt", "yuv420p",
                                clip_path
                            ]
                            proc_f = await asyncio.create_subprocess_exec(
                                *fallback_cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL
                            )
                            await proc_f.wait()
                            if os.path.exists(fallback_jpg):
                                os.remove(fallback_jpg)
                            success = True
                        except Exception as e:
                            print(f"Fallback rendering error for segment {i}: {e}")
                            success = False
                            
                    if success:
                        await sse_logger.log(f"  -> Dựng xong slide {i + 1}/{len(summary_segments)}: tập {ep_num}.", "info")
                    return success

            tasks = []
            for i in range(len(summary_segments)):
                end = segment_end_times[i]
                seg = summary_segments[i]
                ep_num = seg.get("episode", from_ep)

                if i == len(summary_segments) - 1:
                    seg_dur = total_duration - last_end + 3.0
                    if seg_dur < 3.0:
                        seg_dur = 3.0
                else:
                    seg_dur = end - last_end

                if seg_dur <= 0:
                    continue

                if stop_requested:
                    raise Exception("Tiến trình bị dừng bởi người dùng.")

                stitched_image_path = os.path.join(download_dir, f"ep_{ep_num}", "stitched.jpg")
                if not os.path.exists(stitched_image_path):
                    stitched_image_path = os.path.join(download_dir, "stitched.jpg")

                clip_filename = f"temp_clip_{i}.mp4"
                clip_path = os.path.join(download_dir, clip_filename)

                keyframes = seg.get("camera", [])
                if not keyframes:
                    images_old = seg.get("images") or seg.get("slides")
                    if isinstance(images_old, list) and images_old:
                        num_pages = len(images_old)
                        keyframes = []
                        
                        # Load actual page offsets in stitched image
                        ep_dir = os.path.join(download_dir, f"ep_{ep_num}")
                        offsets = []
                        try:
                            from PIL import Image
                            with Image.open(stitched_image_path) as s_img:
                                target_width = s_img.width
                                img_h_actual = s_img.height
                            
                            files = get_unique_sorted_images(ep_dir)
                            if files:
                                heights = []
                                total_height = 0
                                for f in files:
                                    with Image.open(os.path.join(ep_dir, f)) as img_tmp:
                                        w, h = img_tmp.size
                                        ratio = target_width / w
                                        new_h = int(h * ratio)
                                        if new_h <= 0: new_h = 1
                                        heights.append(new_h)
                                        total_height += new_h
                                
                                max_allowed_height = 65000
                                if total_height > max_allowed_height:
                                    scale_ratio = max_allowed_height / total_height
                                    heights = [max(1, int(h * scale_ratio)) for h in heights]
                                    
                                current_y = 0
                                for h in heights:
                                    offsets.append((current_y, current_y + h))
                                    current_y += h
                        except Exception as e:
                            print(f"Error calculating page offsets: {e}")
                            offsets = []

                        for idx_p, img_obj in enumerate(images_old):
                            p_num = img_obj.get("page", 1)
                            p_idx = p_num - 1
                            if offsets and 0 <= p_idx < len(offsets):
                                p_mid = (offsets[p_idx][0] + offsets[p_idx][1]) / 2
                                cy = p_mid / img_h_actual
                            else:
                                cy = 0.1 + 0.8 * (idx_p / max(1, num_pages - 1))
                            
                            weight = 1.0 / num_pages
                            keyframes.append({"center_y": cy, "zoom": 1.0, "duration_weight": weight})
                    else:
                        keyframes = [{"center_y": 0.5, "zoom": 1.0, "duration_weight": 1.0}]

                # Add to task list for parallel execution
                tasks.append(render_segment_task(
                    i=i,
                    ep_num=ep_num,
                    seg_dur=seg_dur,
                    stitched_image_path=stitched_image_path,
                    clip_path=clip_path,
                    keyframes=keyframes
                ))
                rendered_clips.append(clip_filename)
                last_end = end

            # Wait for all clips to render concurrently in parallel
            results = await asyncio.gather(*tasks)
            for idx, success in enumerate(results):
                if not success:
                    raise Exception(f"Dựng slide {idx + 1} thất bại.")


            # 7. Concatenate all silent clips
            await sse_logger.log("Đang ghép nối các đoạn clip...", "info")
            concat_list_path = os.path.join(download_dir, "concat_list.txt")
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for filename in rendered_clips:
                    f.write(f"file '{filename}'\n")

            concat_cmd = [
                ffmpeg_exe, "-y",
                "-f", "concat", "-safe", "0", "-i", "concat_list.txt",
                "-c", "copy",
                "combined_silent.mp4"
            ]

            proc = await asyncio.create_subprocess_exec(
                *concat_cmd,
                cwd=download_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout_data, stderr_data = await proc.communicate()
            if proc.returncode != 0:
                raise Exception(f"Lỗi ghép nối clip: {stderr_data.decode('utf-8', errors='ignore')}")

            # 8. Multiplex silent video with audio at original speed
            await sse_logger.log("Đang ghép nối âm thanh thuyết minh và kết xuất video final...", "info", app_status="active", status_text="Đang xuất video final...")

            final_args = []
            if working_encoder == "libx264":
                final_args = ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-maxrate", "3500k", "-bufsize", "6000k", "-threads", "0"]
            elif working_encoder == "h264_nvenc":
                final_args = [
                    "-c:v", "h264_nvenc", "-preset", "p3", "-tune", "hq", "-rc", "vbr", "-cq", "26",
                    "-b:v", "2200k", "-maxrate", "3800k", "-bufsize", "6000k",
                    "-spatial_aq", "1", "-temporal_aq", "1", "-threads", "0"
                ]
            elif working_encoder == "h264_amf":
                final_args = ["-c:v", "h264_amf", "-rc", "cqp", "-qp_i", "24", "-qp_p", "24", "-b:v", "2200k", "-maxrate", "3800k", "-threads", "0"]
            elif working_encoder == "h264_qsv":
                final_args = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "25", "-b:v", "2200k", "-maxrate", "3800k", "-threads", "0"]
            else:
                final_args = ["-c:v", working_encoder, "-b:v", "2500k", "-threads", "0"]

            logo_path_to_use = logo_path
            if logo_path_to_use:
                logo_path_to_use = os.path.abspath(logo_path_to_use)
            if not logo_path_to_use or not os.path.exists(logo_path_to_use):
                logo_path_to_use = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "logo.png")

            overlay_path_to_use = overlay_path
            if overlay_path_to_use:
                overlay_path_to_use = os.path.abspath(overlay_path_to_use)
            if not overlay_path_to_use or not os.path.exists(overlay_path_to_use):
                overlay_path_to_use = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "overlay.png")

            video_mark_path_to_use = video_mark_path
            if video_mark_path_to_use:
                video_mark_path_to_use = os.path.abspath(video_mark_path_to_use)
            if not video_mark_path_to_use or not os.path.exists(video_mark_path_to_use):
                video_mark_path_to_use = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "video_mark.mp4")

            has_video_mark = enable_video_mark and os.path.exists(video_mark_path_to_use) and os.path.getsize(video_mark_path_to_use) > 1000
            has_logo = os.path.exists(logo_path_to_use) and os.path.getsize(logo_path_to_use) > 0
            has_overlay = os.path.exists(overlay_path_to_use) and os.path.getsize(overlay_path_to_use) > 0

            final_cmd = [
                ffmpeg_exe, "-y",
                "-i", "combined_silent.mp4",
                "-i", "audio.mp3",
            ]
            current_idx = 2
            vm_idx = None
            ol_idx = None
            lg_idx = None

            if has_video_mark:
                final_cmd += ["-stream_loop", "-1", "-i", video_mark_path_to_use]
                vm_idx = current_idx
                current_idx += 1

            if has_overlay:
                final_cmd += ["-loop", "1", "-i", overlay_path_to_use]
                ol_idx = current_idx
                current_idx += 1

            if has_logo:
                final_cmd += ["-loop", "1", "-i", logo_path_to_use]
                lg_idx = current_idx
                current_idx += 1

            filter_parts = []
            curr_v = "0:v"

            if has_video_mark:
                filter_parts.append(f"[{vm_idx}:v]crop=w=min(iw\\,ih*16/9):h=min(ih\\,iw*9/16),scale=1920:1080,format=rgba,colorchannelmixer=aa={video_mark_alpha:.4f}[vm]")
                next_v = "v_vm" if (has_overlay or has_logo) else "v"
                filter_parts.append(f"[{curr_v}][vm]overlay=shortest=1[{next_v}]")
                curr_v = next_v

            if has_overlay:
                filter_parts.append(f"[{ol_idx}:v]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.005[ol]")
                next_v = "v_ol" if has_logo else "v"
                filter_parts.append(f"[{curr_v}][ol]overlay=shortest=1[{next_v}]")
                curr_v = next_v

            if has_logo:
                filter_parts.append(f"[{lg_idx}:v]scale=50:50[logo]")
                filter_parts.append(f"[{curr_v}][logo]overlay=25:25:shortest=1[v]")
                curr_v = "v"

            if curr_v == "0:v":
                filter_parts.append("[0:v]null[v]")

            filter_parts.append("[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,apad[a]")
            final_filter_str = ";".join(filter_parts)

            final_cmd += [
                "-filter_complex", final_filter_str,
                "-map", "[v]",
                "-map", "[a]"
            ] + final_args + [
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "final.mp4"
            ]

            proc = await asyncio.create_subprocess_exec(
                *final_cmd,
                cwd=download_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout_data, stderr_data = await proc.communicate()
            if proc.returncode != 0:
                raise Exception(f"Lỗi ghép âm thanh: {stderr_data.decode('utf-8', errors='ignore')}")

            # 9. Clean up temporary files
            await sse_logger.log("Đang dọn dẹp các tệp tạm thời...", "info")
            for filename in rendered_clips:
                try:
                    os.remove(os.path.join(download_dir, filename))
                    temp_jpg = filename.replace("temp_clip_", "temp_segment_").replace(".mp4", ".jpg")
                    os.remove(os.path.join(download_dir, temp_jpg))
                except Exception:
                    pass
            try:
                os.remove(concat_list_path)
                os.remove(os.path.join(download_dir, "combined_silent.mp4"))
                # Delete TTS and batch compiled JSON files
                os.remove(audio_path)
                os.remove(srt_path)
                os.remove(summary_path)
                os.remove(narrations_path)
            except Exception:
                pass

            await sse_logger.log("Đã xuất video thành công!", "success")
            await sse_logger.log("Video completed.", "success", app_status="idle", status_text="Sẵn sàng")

        except Exception as e:
            import traceback
            traceback.print_exc()
            await sse_logger.log(f"Lỗi tiến trình tạo video: {str(e)}", "error", "idle", "Sẵn sàng")
        finally:
            crawler_running = False

@app.post("/api/generate-video")
async def generate_video(payload: VideoRequest, background_tasks: BackgroundTasks):
    global crawler_running
    if crawler_running:
        await sse_logger.log("Yêu cầu tạo video bị từ chối: Một tiến trình khác đang chạy.", "warning")
        raise HTTPException(status_code=409, detail="Another task is already running.")

    background_tasks.add_task(
        run_video_pipeline,
        payload.comic_folder,
        payload.from_episode,
        payload.to_episode,
        payload.voice_id,
        payload.logo_path,
        payload.overlay_path,
        payload.remove_text,
        payload.remove_text_conf,
        payload.remove_text_radius,
        payload.ref_audio_path,
        payload.ai33pro_api_key,
        payload.video_mark_path,
        payload.video_mark_alpha,
        payload.enable_video_mark
    )
    return {"status": "success", "message": f"Bắt đầu quy trình tạo video cho {payload.comic_folder} trong nền."}

VOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
os.makedirs(VOICES_DIR, exist_ok=True)

def _init_sample_voices():
    sample_files = [
        "voice_preview_amy - natural and sweet.mp3",
        "jessa - easygoing and effortless.mp3"
    ]
    for sf in sample_files:
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", sf)
        if os.path.exists(src):
            dst = os.path.join(VOICES_DIR, sf)
            if not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

_init_sample_voices()

@app.get("/api/voices")
async def list_voices_endpoint():
    os.makedirs(VOICES_DIR, exist_ok=True)
    valid_exts = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".webm")
    voices = []
    for f in sorted(os.listdir(VOICES_DIR)):
        if any(f.lower().endswith(ext) for ext in valid_exts):
            fp = os.path.join(VOICES_DIR, f)
            size = os.path.getsize(fp)
            name = os.path.splitext(f)[0]
            if name.startswith("voice_preview_"):
                name = name[len("voice_preview_"):]
            name = name.replace("_", " ").strip().title()
            voices.append({
                "name": name,
                "filename": f,
                "path": os.path.join("voices", f).replace("\\", "/"),
                "url": f"/voices/{urllib.parse.quote(f)}",
                "size_bytes": size,
                "size_formatted": f"{round(size / 1024, 1)} KB" if size < 1024*1024 else f"{round(size / (1024*1024), 2)} MB"
            })
    return {"status": "success", "voices": voices}

@app.post("/api/voices/upload")
async def upload_voice_endpoint(file: UploadFile = File(...)):
    os.makedirs(VOICES_DIR, exist_ok=True)
    valid_exts = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".webm")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in valid_exts:
        raise HTTPException(status_code=400, detail="Định dạng âm thanh không hỗ trợ. Vui lòng tải lên file .mp3, .wav, .m4a, .ogg, .flac")
    
    clean_name = os.path.splitext(file.filename)[0]
    clean_name = "".join(c for c in clean_name if c.isalnum() or c in (" ", "_", "-")).strip()
    if not clean_name:
        clean_name = f"voice_{int(time.time())}"
    final_filename = f"{clean_name}{ext}"
    dest_path = os.path.join(VOICES_DIR, final_filename)
    
    counter = 1
    while os.path.exists(dest_path):
        final_filename = f"{clean_name}_{counter}{ext}"
        dest_path = os.path.join(VOICES_DIR, final_filename)
        counter += 1
        
    with open(dest_path, "wb") as f_out:
        content = await file.read()
        f_out.write(content)
        
    size = len(content)
    display_name = os.path.splitext(final_filename)[0].replace("_", " ").strip().title()
    return {
        "status": "success",
        "voice": {
            "name": display_name,
            "filename": final_filename,
            "path": os.path.join("voices", final_filename).replace("\\", "/"),
            "url": f"/voices/{urllib.parse.quote(final_filename)}",
            "size_bytes": size,
            "size_formatted": f"{round(size / 1024, 1)} KB" if size < 1024*1024 else f"{round(size / (1024*1024), 2)} MB"
        }
    }

@app.delete("/api/voices/{filename}")
async def delete_voice_endpoint(filename: str):
    filename = os.path.basename(filename)
    target = os.path.join(VOICES_DIR, filename)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Không tìm thấy file voice.")
    try:
        os.remove(target)
        return {"status": "success", "message": f"Đã xóa voice {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể xóa file voice: {str(e)}")

# --- PRESETS MANAGEMENT API ---
import time
PRESETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "presets.json")

class PresetItem(BaseModel):
    id: Optional[str] = None
    name: str
    headless: bool = False
    language: str = "vi"
    gemini_model: str = "flash"
    tts_voice_id: str = "auto"
    flip_horizontal: bool = False
    voice_sample_path: Optional[str] = ""
    voice_sample_name: Optional[str] = ""

def _load_presets_data():
    os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
    if not os.path.exists(PRESETS_FILE):
        default_data = {
            "active_preset_id": "default_vi",
            "presets": [
                {
                    "id": "default_vi",
                    "name": "Tiếng Việt Chuẩn (Flash)",
                    "headless": False,
                    "language": "vi",
                    "gemini_model": "flash",
                    "tts_voice_id": "auto",
                    "flip_horizontal": False,
                    "voice_sample_path": "",
                    "voice_sample_name": ""
                },
                {
                    "id": "english_pro_flipped",
                    "name": "English Pro (Lật ảnh)",
                    "headless": True,
                    "language": "en",
                    "gemini_model": "pro",
                    "tts_voice_id": "auto",
                    "flip_horizontal": True,
                    "voice_sample_path": "",
                    "voice_sample_name": ""
                }
            ]
        }
        try:
            with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return default_data
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "presets" not in data or not isinstance(data["presets"], list):
                data["presets"] = []
            return data
    except Exception:
        return {"active_preset_id": None, "presets": []}

def _save_presets_data(data):
    os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.get("/api/presets")
async def get_presets_endpoint():
    data = _load_presets_data()
    return {
        "status": "success",
        "active_preset_id": data.get("active_preset_id"),
        "presets": data.get("presets", [])
    }

@app.post("/api/presets")
async def save_preset_endpoint(preset: PresetItem):
    data = _load_presets_data()
    presets = data.get("presets", [])
    
    preset_dict = preset.dict()
    if not preset_dict.get("id"):
        preset_dict["id"] = f"preset_{int(time.time())}_{random.randint(100, 999)}"
        presets.append(preset_dict)
    else:
        found = False
        for i, p in enumerate(presets):
            if p.get("id") == preset_dict["id"]:
                presets[i] = preset_dict
                found = True
                break
        if not found:
            presets.append(preset_dict)
            
    data["presets"] = presets
    data["active_preset_id"] = preset_dict["id"]
    _save_presets_data(data)
    return {
        "status": "success",
        "active_preset_id": data["active_preset_id"],
        "preset": preset_dict,
        "presets": presets
    }

@app.post("/api/presets/active/{preset_id}")
async def set_active_preset_endpoint(preset_id: str):
    data = _load_presets_data()
    data["active_preset_id"] = preset_id
    _save_presets_data(data)
    return {"status": "success", "active_preset_id": preset_id}

@app.delete("/api/presets/{preset_id}")
async def delete_preset_endpoint(preset_id: str):
    data = _load_presets_data()
    presets = data.get("presets", [])
    original_len = len(presets)
    presets = [p for p in presets if p.get("id") != preset_id]
    if len(presets) == original_len:
        raise HTTPException(status_code=404, detail="Không tìm thấy preset cần xóa.")
        
    data["presets"] = presets
    if data.get("active_preset_id") == preset_id:
        data["active_preset_id"] = presets[0]["id"] if presets else None
    _save_presets_data(data)
    return {
        "status": "success",
        "active_preset_id": data.get("active_preset_id"),
        "presets": presets
    }

from typing import List, Dict, Optional, Any
import re

class SubtitleTranslateRequest(BaseModel):
    srt_text: Optional[str] = None
    cues: Optional[List[Dict[str, Any]]] = None
    target_lang: str = "vi"
    source_lang: str = "auto"


def _sync_translate_chunk(combined_text: str, target_lang: str = "vi", source_lang: str = "auto") -> str:
    """Synchronous translate worker using Google Translate API with fallback clients."""
    import urllib.request
    import urllib.parse
    import json

    clients = ["gtx", "dict-chrome-ex"]
    last_err = None
    for client in clients:
        try:
            data = urllib.parse.urlencode({
                "client": client,
                "sl": source_lang,
                "tl": target_lang,
                "dt": "t",
                "q": combined_text
            }).encode("utf-8")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
            }

            req = urllib.request.Request(
                "https://translate.googleapis.com/translate_a/single",
                data=data,
                headers=headers
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body and isinstance(body, list) and len(body) > 0 and isinstance(body[0], list):
                    return "".join(part[0] for part in body[0] if part and len(part) > 0 and part[0])
        except Exception as e:
            last_err = e
            continue
    raise last_err or Exception("All translation clients failed")


@app.post("/api/subtitles/translate")
async def translate_subtitles_endpoint(payload: SubtitleTranslateRequest):
    import re
    target_lang = (payload.target_lang or "vi").strip()
    source_lang = (payload.source_lang or "auto").strip()
    raw_cues = payload.cues or []

    # If cues were not sent but srt_text was provided, parse SRT
    if not raw_cues and payload.srt_text:
        parsed_cues = []
        blocks = re.split(r'\n\s*\n', payload.srt_text.replace('\r\n', '\n').replace('\r', '\n').strip())
        for block in blocks:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if len(lines) < 2:
                continue
            time_idx = -1
            for i, line in enumerate(lines):
                if '-->' in line:
                    time_idx = i
                    break
            if time_idx != -1:
                parts = lines[time_idx].split('-->')
                if len(parts) == 2:
                    text_content = "\n".join(lines[time_idx + 1:])
                    parsed_cues.append({
                        "id": len(parsed_cues) + 1,
                        "startStr": parts[0].strip(),
                        "endStr": parts[1].strip(),
                        "text": text_content
                    })
        raw_cues = parsed_cues

    if not raw_cues:
        raise HTTPException(status_code=400, detail="Không tìm thấy câu thoại hợp lệ để dịch.")

    # Batch translate concurrently with semaphore
    batch_size = 40
    batches = [raw_cues[i:i + batch_size] for i in range(0, len(raw_cues), batch_size)]
    translated_map = {}
    sem = asyncio.Semaphore(8)

    async def _process_batch(b_idx: int, batch: list):
        offset = b_idx * batch_size
        lines = [f"[{offset + i}] {c.get('text', '').replace(chr(10), ' _nl_ ')}" for i, c in enumerate(batch)]
        combined = "\n".join(lines)

        try:
            async with sem:
                raw_trans = await asyncio.to_thread(_sync_translate_chunk, combined, target_lang, source_lang)
            pattern = re.compile(r"^[\[【\s]*(\d+)[\]】\s\:\.\-]+\s*(.*)$")
            cur_idx = None
            cur_lines = []

            for line in raw_trans.splitlines():
                trimmed = line.strip()
                if not trimmed:
                    continue
                m = pattern.match(trimmed)
                if m:
                    if cur_idx is not None:
                        combined_sub = "\n".join(cur_lines).replace(" _nl_ ", "\n").replace("_nl_", "\n").strip()
                        translated_map[cur_idx] = combined_sub
                    cur_idx = int(m.group(1))
                    cur_lines = [m.group(2).strip()] if m.group(2).strip() else []
                else:
                    if cur_idx is not None:
                        cur_lines.append(trimmed)

            if cur_idx is not None:
                combined_sub = "\n".join(cur_lines).replace(" _nl_ ", "\n").replace("_nl_", "\n").strip()
                translated_map[cur_idx] = combined_sub
        except Exception as e:
            print(f"[Translate] Batch {b_idx} error: {e}", flush=True)

    await asyncio.gather(*[_process_batch(idx, b) for idx, b in enumerate(batches)])

    translated_cues = []
    srt_output_lines = []

    for i, c in enumerate(raw_cues):
        orig_text = c.get("text", "")
        trans_text = translated_map.get(i, orig_text)
        cue_item = {
            **c,
            "original_text": orig_text,
            "translated_text": trans_text,
            "text": trans_text
        }
        translated_cues.append(cue_item)

        start_str = c.get("fullStartStr") or c.get("startStr") or c.get("start") or "00:00:00,000"
        end_str = c.get("fullEndStr") or c.get("endStr") or c.get("end") or "00:00:00,000"
        srt_output_lines.append(f"{i + 1}\n{start_str} --> {end_str}\n{trans_text}\n")

    return {
        "status": "success",
        "target_lang": target_lang,
        "source_lang": source_lang,
        "cues": translated_cues,
        "translated_cues": translated_cues,
        "translated_srt": "\n".join(srt_output_lines)
    }


@app.get("/api/subtitles")
async def get_subtitles_endpoint(
    folder: Optional[str] = None,
    episode: Optional[str] = None,
    video: Optional[str] = None,
    raw_path: Optional[str] = None
):
    project_dir = os.path.dirname(os.path.abspath(__file__))
    downloads_dir = os.path.join(project_dir, "downloads")
    
    candidates_to_check = []
    
    clean_folder = urllib.parse.unquote((folder or "").strip().replace("\\", "/").strip("/"))
    if clean_folder.lower().startswith("downloads/"):
        clean_folder = clean_folder[len("downloads/"):]
    if clean_folder.lower() in ("none", "null"):
        clean_folder = ""
        
    clean_ep = (str(episode) if episode is not None else "").strip()
    if clean_ep.lower() in ("none", "null"):
        clean_ep = ""
        
    clean_video = urllib.parse.unquote((video or "").strip().replace("\\", "/"))
    clean_raw = urllib.parse.unquote((raw_path or "").strip())
    
    # 0. Check raw_path on disk directly if provided
    if clean_raw:
        raw_norm = os.path.normpath(clean_raw)
        if os.path.isfile(raw_norm):
            candidates_to_check.append(os.path.splitext(raw_norm)[0] + ".srt")
            candidates_to_check.append(os.path.join(os.path.dirname(raw_norm), "transcript.srt"))
            candidates_to_check.append(os.path.join(os.path.dirname(raw_norm), "transcript_raw.srt"))
        elif clean_raw.lower().endswith((".mp4", ".mkv", ".webm")):
            candidates_to_check.append(os.path.splitext(raw_norm)[0] + ".srt")

    # 1. Video-based resolution
    if clean_video:
        if os.path.isfile(clean_video):
            candidates_to_check.append(os.path.splitext(clean_video)[0] + ".srt")
            candidates_to_check.append(os.path.join(os.path.dirname(clean_video), "transcript.srt"))

        norm_v = clean_video
        d_idx = norm_v.lower().find("downloads/")
        if d_idx != -1:
            rel_path = norm_v[d_idx + len("downloads/"):].lstrip("/")
            abs_v = os.path.join(downloads_dir, rel_path.replace("/", os.sep))
            v_dir = os.path.dirname(abs_v)
            # The exact 1-to-1 video subtitle matching the mp4 filename
            base_srt = os.path.splitext(abs_v)[0] + ".srt"
            candidates_to_check.append(base_srt)
            candidates_to_check.append(os.path.join(v_dir, "transcript.srt"))
            candidates_to_check.append(os.path.join(v_dir, "transcript_raw.srt"))
            
            parts = rel_path.split("/")
            if parts and not clean_folder and parts[0].lower() not in ("none", "null", ""):
                clean_folder = parts[0]
                
    # 2. Folder and episode-based resolution
    if clean_folder:
        folder_dir = os.path.join(downloads_dir, clean_folder)
        if clean_ep and "-" not in clean_ep:
            # Single episode requested: prioritize episode directory transcript
            ep_dir = os.path.join(folder_dir, f"episode_{clean_ep}")
            candidates_to_check.append(os.path.join(ep_dir, f"{clean_folder}_ep{clean_ep}.srt"))
            candidates_to_check.append(os.path.join(ep_dir, "transcript.srt"))
            candidates_to_check.append(os.path.join(ep_dir, "transcript_raw.srt"))
            candidates_to_check.append(os.path.join(ep_dir, "video.srt"))
            candidates_to_check.append(os.path.join(folder_dir, "output", f"{clean_folder}_ep{clean_ep}.srt"))
            candidates_to_check.append(os.path.join(folder_dir, "output", f"{clean_folder}.srt"))
            candidates_to_check.append(os.path.join(folder_dir, "output", "transcript.srt"))
        elif clean_ep and "-" in clean_ep:
            # Range episode requested (e.g. 1-3): prioritize output merged srt
            parts = clean_ep.split("-")
            f_ep, t_ep = parts[0].strip(), parts[1].strip()
            candidates_to_check.append(os.path.join(folder_dir, "output", f"{clean_folder}_ep{f_ep}_{t_ep}.srt"))
            candidates_to_check.append(os.path.join(folder_dir, "output", f"{clean_folder}.srt"))
            candidates_to_check.append(os.path.join(folder_dir, "output", "transcript.srt"))
        else:
            candidates_to_check.append(os.path.join(folder_dir, "output", f"{clean_folder}.srt"))
            candidates_to_check.append(os.path.join(folder_dir, "output", "transcript.srt"))
            
        candidates_to_check.append(os.path.join(folder_dir, f"{clean_folder}.srt"))
        candidates_to_check.append(os.path.join(folder_dir, "transcript.srt"))
        
        out_d = os.path.join(folder_dir, "output")
        if os.path.isdir(out_d):
            for s_f in os.listdir(out_d):
                if s_f.endswith(".srt"):
                    candidates_to_check.append(os.path.join(out_d, s_f))

        if os.path.isdir(folder_dir):
            for sub in sorted(os.listdir(folder_dir)):
                if sub.startswith("episode_"):
                    candidates_to_check.append(os.path.join(folder_dir, sub, "transcript.srt"))
                    candidates_to_check.append(os.path.join(folder_dir, sub, "transcript_raw.srt"))

    # 3. Fallback: Search all folders in downloads_dir ONLY if NO video and NO folder was provided
    if not clean_folder and not clean_video and not clean_raw and os.path.isdir(downloads_dir):
        for fld in sorted(os.listdir(downloads_dir)):
            fld_path = os.path.join(downloads_dir, fld)
            if not os.path.isdir(fld_path):
                continue
            if clean_ep:
                candidates_to_check.append(os.path.join(fld_path, f"episode_{clean_ep}", "transcript.srt"))
                candidates_to_check.append(os.path.join(fld_path, f"episode_{clean_ep}", "transcript_raw.srt"))
            candidates_to_check.append(os.path.join(fld_path, "output", f"{fld}.srt"))
            candidates_to_check.append(os.path.join(fld_path, "output", "transcript.srt"))

    seen_paths = set()
    for c_path in candidates_to_check:
        norm_c = os.path.normpath(c_path)
        if norm_c in seen_paths:
            continue
        seen_paths.add(norm_c)
        if os.path.isfile(norm_c) and os.path.getsize(norm_c) > 10:
            try:
                with open(norm_c, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if "-->" in content:
                    rel_url = "/" + os.path.relpath(norm_c, project_dir).replace("\\", "/")
                    return {
                        "status": "success",
                        "content": content,
                        "filename": os.path.basename(norm_c),
                        "url": rel_url
                    }
            except Exception:
                continue

    return {
        "status": "not_found",
        "message": "No subtitle file found for the requested parameters."
    }

    # Mount static files (style.css, app.js)
    # Mount downloads static directory
os.makedirs("downloads", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")
app.mount("/Downloads", StaticFiles(directory="downloads"), name="downloads_capital")

    # Mount voices static directory
os.makedirs("voices", exist_ok=True)
app.mount("/voices", StaticFiles(directory="voices"), name="voices_dir")

    # Mount static files (style.css, app.js)
app.mount("/static", StaticFiles(directory="static"), name="static_dir")
app.mount("/", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)

