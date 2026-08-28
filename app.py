import sys
import os
# Optimize CUDA memory allocation to avoid fragmentation and OOM
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
# Enable CPU fallback for unsupported MPS operators on macOS
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import subprocess
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, message=".*The key `labels`.*")
import asyncio
import threading

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
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import List, Dict, Optional, Literal
load_dotenv()
from tts_settings import normalize_tts_voice_mode

# --- Configuration Management for Chrome Profiles ---
CONFIG_FILE = "config.json"

def load_config():
    default_profile = os.getenv("CHROME_PROFILE_PATH") or r"C:\Data\Profile 1"
    if not os.path.exists(CONFIG_FILE):
        config = {
            "chrome_profiles": [default_profile],
            "current_profile_index": 0
        }
        save_config(config)
        return config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "chrome_profiles": [default_profile],
            "current_profile_index": 0
        }

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)



if sys.platform == 'win32':
    # Prevent uvicorn from overriding loop policy to SelectorEventLoop on Windows
    asyncio.WindowsSelectorEventLoopPolicy = asyncio.WindowsProactorEventLoopPolicy
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi import FastAPI, HTTPException, status, File, UploadFile, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from playwright.async_api import async_playwright
from PIL import Image
from security_utils import (
    PathAccessError,
    SESSION_COOKIE_NAME,
    SESSION_TOKEN,
    redact_sensitive_text,
    request_host_allowed,
    resolve_download_path,
    resolve_upload_path,
    same_origin_allowed,
    session_token_matches,
    upload_reference,
)
from process_control import ProcessIdentity, identity_for_process, popen_command, process_matches
from worker_protocol import atomic_write_json

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


@app.middleware("http")
async def protect_local_api(request: Request, call_next):
    host = request.headers.get("host", "")
    if not request_host_allowed(host):
        return JSONResponse(status_code=403, content={"detail": "Host is not allowed."})

    if request.url.path.startswith("/api/"):
        if not session_token_matches(request.cookies.get(SESSION_COOKIE_NAME)):
            return JSONResponse(status_code=403, content={"detail": "Invalid local session."})
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not same_origin_allowed(
            request.headers.get("origin"), host
        ):
            return JSONResponse(status_code=403, content={"detail": "Cross-origin mutation is not allowed."})

    return await call_next(request)

from workflow import (
    JSONWorkflowRepository,
    EventBus,
    WorkflowManager,
    WorkflowTask,
    WorkflowState,
    StageState
)

textbox_selectors = [
    "rich-textarea p",
    "rich-textarea div[contenteditable='true']",
    "div[contenteditable='true']",
    "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[1]/div/div/div/rich-textarea/div[1]/p[2]",
    "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div[2]/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[1]/div/div/div/rich-textarea/div[1]/p",
    "#prompt-textarea",
    "textarea#prompt-textarea",
    "textarea"
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
repository = JSONWorkflowRepository(os.getenv("RECAP_TASK_DB", "tasks_db.json"))
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
        safe_message = redact_sensitive_text(str(message)) or ""
        print(f"[{level.upper()}] {safe_message}", flush=True)
        payload = {
            "message": safe_message,
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

    async def safe_goto(self, page, url: str, reason: str, caller: str):
        async with self.mutex:
            self.current_url = url
            self.track_navigation(url, caller)

            # Update cookies count
            if self.context:
                try:
                    cookies = await self.context.cookies()
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
                response = await page.goto(url, timeout=60000)
                final_url = page.url
                self.current_url = final_url

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
    chrome_profiles: List[str]
    current_profile_index: int

@app.get("/api/config")
async def get_app_config():
    return load_config()

@app.post("/api/config")
async def save_app_config(payload: SaveConfigRequest):
    config = {
        "chrome_profiles": [p.strip() for p in payload.chrome_profiles if p.strip()],
        "current_profile_index": payload.current_profile_index
    }
    save_config(config)
    if config["chrome_profiles"]:
        idx = config["current_profile_index"]
        if idx < len(config["chrome_profiles"]):
            os.environ["CHROME_PROFILE_PATH"] = config["chrome_profiles"][idx]
    return {"status": "success", "message": "Cập nhật cấu hình Chrome Profiles thành công.", "config": config}

# Serve HTML frontend
@app.get("/")
async def get_index():
    response = FileResponse("static/index.html")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        SESSION_TOKEN,
        httponly=True,
        samesite="strict",
        secure=False,
    )
    return response

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
                browser, context = await get_shared_browser_context(headless=False, start_maximized=True, custom_profile_path=target_profile)
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
    model_config = ConfigDict(extra="forbid")
    url: str
    from_episode: int = Field(ge=1)
    to_episode: int = Field(ge=1)
    safe_mode: bool = False
    nsfw_threshold: float = 0.3
    nsfw_mode: str = "mask"
    timeout: int = Field(default=160, ge=30, le=600)
    retry_count: int = Field(default=5, ge=1, le=10)
    concurrency: int = Field(default=5, ge=1, le=5)
    image_quality: int = Field(default=20, ge=10, le=100)
    pdf_quality: int = Field(default=20, ge=10, le=100)
    language: str = "vi"
    vlm_provider: Literal["gemini"] = "gemini"
    voice_id: str = "ai33pro"
    ref_audio_path: Optional[str] = None
    logo_path: Optional[str] = None
    overlay_path: Optional[str] = None
    burn_subtitles: bool = False
    remove_text: bool = True
    remove_text_conf: float = 0.3
    remove_text_radius: int = 3
    comix_group_id: Optional[str] = None


def _validated_asset_reference(value: str | None) -> str | None:
    try:
        return upload_reference(resolve_upload_path(value, must_exist=True))
    except PathAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Uploaded asset does not exist.") from exc



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

async def get_browser_context(p, headless=False, start_maximized=False, temp_suffix="", custom_profile_path=None):
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

    launch_args = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu-shader-disk-cache",
            "--disable-dev-shm-usage",
            "--disable-features=Translate,BackForwardCache,AcceptCHFrame,MediaRouter,OptimizationHints",
            "--no-first-run",
            "--no-default-browser-check",
            "--password-store=basic",
            "--use-mock-keychain",
        ],
        "ignore_default_args": ["--enable-automation", "--no-sandbox"]
    }
    if start_maximized:
        launch_args["args"].append("--start-maximized")

    if profile_path:
        profile_path = os.path.abspath(profile_path)

        basename = os.path.basename(profile_path)
        if basename.startswith("Profile ") or basename == "Default":
            profile_dir_arg = basename
            user_data_dir = os.path.dirname(profile_path)
            launch_args["args"].append(f"--profile-directory={profile_dir_arg}")
            print(f"Using persistent Chrome profile directory: {user_data_dir} with profile: {profile_dir_arg}")
        else:
            user_data_dir = profile_path
            print(f"Using persistent Chrome profile at: {user_data_dir}")

        # Clean browser lock files inside profile path
        for lock_name in ["SingletonLock", "lock", "SingletonCookie", "SingletonSocket"]:
            for root, dirs, files in os.walk(user_data_dir):
                if lock_name in files:
                    try:
                        os.remove(os.path.join(root, lock_name))
                        print(f"Cleared lock file: {os.path.join(root, lock_name)}")
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
                            channel="chrome",
                            no_viewport=True if start_maximized else None,
                            permissions=["clipboard-read", "clipboard-write"],
                            **launch_args
                        )
                    except Exception as inner_e:
                        # Fallback if channel="chrome" fails
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=user_data_dir,
                            no_viewport=True if start_maximized else None,
                            permissions=["clipboard-read", "clipboard-write"],
                            **launch_args
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
                print(f"Warning: Persistent profile is locked. Attempting to bypass by copying to a temp profile directory...")
                import time
                temp_profile_dir = os.path.join(os.getcwd(), f"chrome_profile_temp_{int(time.time())}")
                try:
                    sync_chrome_profile(user_data_dir, temp_profile_dir)
                    user_data_dir = temp_profile_dir
                    _temp_profiles_to_clean.append(temp_profile_dir)
                    
                    # Clean browser lock files inside temp profile path
                    for lock_name in ["SingletonLock", "lock", "SingletonCookie", "SingletonSocket"]:
                        for root, dirs, files in os.walk(user_data_dir):
                            if lock_name in files:
                                try:
                                    os.remove(os.path.join(root, lock_name))
                                except Exception:
                                    pass
                    
                    try:
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=user_data_dir,
                            channel="chrome",
                            no_viewport=True if start_maximized else None,
                            permissions=["clipboard-read", "clipboard-write"],
                            **launch_args
                        )
                    except Exception:
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=user_data_dir,
                            no_viewport=True if start_maximized else None,
                            permissions=["clipboard-read", "clipboard-write"],
                            **launch_args
                        )
                except Exception as copy_err:
                    print(f"Warning: Could not sync locked profile to temp directory: {copy_err}")
                
                # If we bypassed or if we are already using the temp directory but still locked
                if not context:
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

        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); delete navigator.__proto__.webdriver;")
        await context.route("**/*", lambda route, request: route.abort() if any(domain in request.url for domain in ["google-analytics.com", "googletagmanager.com", "analytics", "doubleclick.net", "facebook.net"]) else route.continue_())
        return None, context

    try:
        browser = await p.chromium.launch(channel="chrome", **launch_args)
    except Exception:
        browser = await p.chromium.launch(**launch_args)

    context_args = {
        "no_viewport": True if start_maximized else None,
        "permissions": ["clipboard-read", "clipboard-write"]
    }

    context = await browser.new_context(**context_args)
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); delete navigator.__proto__.webdriver;")
    await context.route("**/*", lambda route, request: route.abort() if any(domain in request.url for domain in ["google-analytics.com", "googletagmanager.com", "analytics", "doubleclick.net", "facebook.net"]) else route.continue_())
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

async def get_shared_browser_context(headless=False, start_maximized=False, temp_suffix="", custom_profile_path=None):
    global _shared_playwright, _shared_context, _shared_browser, _shared_headless, _shared_context_lock, _shared_profile_path
    from playwright.async_api import async_playwright
    
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
            print("Shared browser context mismatch (headless, profile) or validation failed. Resetting...")
            await reset_shared_browser_context()
                
        if _shared_playwright is None:
            _shared_playwright = await async_playwright().start()
            
        browser_res, context_res = await get_browser_context(_shared_playwright, headless=headless, start_maximized=start_maximized, temp_suffix=temp_suffix, custom_profile_path=target_profile_path)
        _shared_browser = browser_res
        _shared_context = context_res
        _shared_headless = headless
        _shared_profile_path = target_profile_path
        return _shared_browser, _shared_context

async def check_and_rotate_profiles_until_ready(context_logger=None, force_check=False):
    """
    Checks if the active Chrome Profile's Gemini model 3.6 Flash is limited.
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
        
    # Optimization: if not force_check and we already have a validated context, reuse it directly
    if not force_check and _shared_context:
        active_profile = profiles[start_idx]
        if _shared_profile_path == active_profile:
            try:
                await _shared_context.cookies()
                return _shared_browser, _shared_context
            except Exception:
                pass
                
    num_profiles = len(profiles)
    
    for i in range(num_profiles):
        idx = (start_idx + i) % num_profiles
        profile_path = profiles[idx]
        
        msg = f"Đang kiểm tra giới hạn tài khoản (Profile {idx+1}/{num_profiles}): {profile_path}..."
        if context_logger:
            await context_logger.log(msg, "info")
        else:
            print(msg)
            
        # Update config index so get_shared_browser_context launches this profile
        config["current_profile_index"] = idx
        save_config(config)
        
        # Reset current context to force launch with the new profile
        await reset_shared_browser_context()
        
        # Launch headed browser to verify
        br, ctx = await get_shared_browser_context(headless=False, start_maximized=True, custom_profile_path=profile_path)
        
        page = await ctx.new_page()
        try:
            await page.goto("https://gemini.google.com/app", timeout=60000)
            
            # Check login and rate-limit status
            status = await check_gemini_login_and_limit_status(page, context_logger)
            
            if status == "needs_login":
                if context_logger:
                    await context_logger.log("Chưa đăng nhập trên Gemini. Đang chờ bạn đăng nhập thủ công trên cửa sổ trình duyệt (Tối đa 180s)...", "warning")
                else:
                    print("Needs login. Waiting for manual login...")
                    
                login_success = False
                for _ in range(90):  # 90 * 2s = 180s
                    await asyncio.sleep(2)
                    new_status = await check_gemini_login_and_limit_status(page, None)
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
                    continue
            
            if status == "limited":
                if context_logger:
                    await context_logger.log(f"Tài khoản {profile_path} bị giới hạn (Rate limit) model 3.6 Flash. Đang xoay vòng...", "warning")
                else:
                    print(f"Profile {profile_path} is limited. Rotating...")
                await page.close()
                continue
                
            # If status == "ok"
            if context_logger:
                await context_logger.log(f"Tài khoản {profile_path} KHÔNG bị giới hạn. Tiếp tục thực thi với tài khoản này.", "success")
            else:
                print(f"Profile {profile_path} is ready.")
            
            # Keep this profile context and close verification page
            await page.close()
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
            continue
            
    # If we exited the loop, all profiles are limited
    err_msg = "Tất cả các tài khoản/Chrome Profiles đều đang bị giới hạn (Rate limited) hoặc chưa đăng nhập. Vui lòng thêm tài khoản mới trên giao diện Web UI hoặc đợi hết giới hạn."
    if context_logger:
        await context_logger.log(err_msg, "error")
    raise Exception(err_msg)

async def check_gemini_login_and_limit_status(page, context_logger=None):
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
        
    dropdown_btn = await page.query_selector("button.input-area-switch")
    if not dropdown_btn:
        return "ok"
        
    try:
        await dropdown_btn.click()
        await page.wait_for_timeout(1000)
    except Exception:
        return "ok"
        
    check_js = """
    (() => {
        const flashItem = document.querySelector('gem-menu-item[data-mode-id="56fdd199312815e2"]') 
                       || Array.from(document.querySelectorAll('gem-menu-item')).find(el => el.textContent.includes('3.6 Flash'));
                       
        if (!flashItem) {
            return { error: "3.6 Flash model option not found in menu" };
        }
        
        const ariaDisabled = flashItem.getAttribute('aria-disabled') === 'true';
        const hasDisabledClass = flashItem.classList.contains('disabled') 
                              || flashItem.classList.contains('gmat-disabled')
                              || flashItem.querySelector('.disabled') !== null;
        
        const sublabelEl = flashItem.querySelector('.sublabel');
        const sublabel = sublabelEl ? sublabelEl.textContent.trim() : "";
        
        const isLimitText = /limit|giới hạn|reached|try again|quá tải|chờ|resets/i.test(sublabel);
        const isLimited = ariaDisabled || hasDisabledClass || isLimitText;
        
        if (!isLimited) {
            flashItem.click();
        }
        
        return {
            isLimited: isLimited,
            sublabel: sublabel,
            clicked: !isLimited
        };
    })()
    """
    try:
        result = await page.evaluate(check_js)
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

async def ensure_model_selected(page, context_logger=None):
    dropdown_btn = await page.query_selector("button.input-area-switch")
    if not dropdown_btn:
        return
        
    try:
        btn_text = await page.eval_on_selector("button.input-area-switch", "el => el.textContent")
        if "3.6 Flash" in btn_text or ("Flash" in btn_text and "lite" not in btn_text.lower()):
            # Already selected, no need to click
            return
            
        await dropdown_btn.click()
        await page.wait_for_timeout(1000)
        
        check_js = """
        (() => {
            const flashItem = document.querySelector('gem-menu-item[data-mode-id="56fdd199312815e2"]') 
                           || Array.from(document.querySelectorAll('gem-menu-item')).find(el => el.textContent.includes('3.6 Flash'));
                           
            if (flashItem) {
                const ariaDisabled = flashItem.getAttribute('aria-disabled') === 'true';
                const hasDisabledClass = flashItem.classList.contains('disabled') 
                                      || flashItem.classList.contains('gmat-disabled');
                const sublabelEl = flashItem.querySelector('.sublabel');
                const sublabel = sublabelEl ? sublabelEl.textContent.trim() : "";
                const isLimitText = /limit|giới hạn|reached|try again|quá tải|chờ|resets/i.test(sublabel);
                
                if (!ariaDisabled && !hasDisabledClass && !isLimitText) {
                    flashItem.click();
                    return { success: true };
                }
            }
            return { success: false };
        })()
        """
        result = await page.evaluate(check_js)
        
        if not result or not isinstance(result, dict) or not result.get("success"):
            await dropdown_btn.click()
            if context_logger:
                await context_logger.log("Không thể tự động chọn model 3.6 Flash (có thể bị giới hạn hoặc lỗi giao diện).", "warning")
        else:
            if context_logger:
                await context_logger.log("Đã tự động chuyển đổi sang model 3.6 Flash trên trang hiện tại.", "success")
                
    except Exception as e:
        if context_logger:
            await context_logger.log(f"Lỗi khi đảm bảo chọn model 3.6 Flash: {e}", "warning")

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

        await delete_btn.click()
        await page.wait_for_timeout(1500)

        # Step 2: Click "Delete all time" (Xóa từ trước đến nay)
        all_time_btn = None
        all_time_selectors = [
            "span:has-text('All time')",
            "span:has-text('Từ trước đến nay')",
            "[role='menuitem']:has-text('All time')",
            "[role='menuitem']:has-text('Từ trước đến nay')",
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

        if not all_time_btn:
            raise Exception("Không tìm thấy tùy chọn 'Xóa từ trước đến nay' (Delete all time) trong menu.")

        await all_time_btn.click()
        await page.wait_for_timeout(2000)

        # Step 3: Handle confirmation dialogs (could be 1 or 2 confirmation modals)
        for confirm_step in range(3):
            confirm_btn = None
            confirm_selectors = [
                "button:has-text('Delete')",
                "button:has-text('Xóa')",
                "button:has-text('Next')",
                "button:has-text('Tiếp theo')",
                "span:has-text('Delete')",
                "span:has-text('Xóa')",
                "span:has-text('Next')",
                "span:has-text('Tiếp theo')"
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
                btn_txt = await confirm_btn.text_content()
                if context_logger:
                    await context_logger.log(f"Đang xác nhận bước {confirm_step + 1}: click '{btn_txt.strip()}'...", "info")
                await confirm_btn.click()
                await page.wait_for_timeout(2500)
            else:
                break

        # Step 4: Got it button to close dialog
        got_it_btn = None
        got_it_selectors = [
            "button:has-text('Got it')",
            "button:has-text('Đã hiểu')",
            "button:has-text('OK')",
            "span:has-text('Got it')",
            "span:has-text('Đã hiểu')",
            "span:has-text('OK')"
        ]
        for sel in got_it_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    got_it_btn = loc
                    break
            except Exception:
                pass

        if got_it_btn:
            await got_it_btn.click()
            await page.wait_for_timeout(1000)

        msg = "Đã dọn dẹp toàn bộ lịch sử hoạt động Gemini thành công!"
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
        else:
            referer = "https://www.webtoons.com/"
            
    req = urllib.request.Request(
        url,
        headers={
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req) as response, open(save_path, "wb") as out_file:
        out_file.write(response.read())

async def download_image(url: str, save_path: str, referer: str = None):
    await asyncio.to_thread(download_image_sync, url, save_path, referer)

def sanitize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"\s+", "_", title)
    title = re.sub(r"[^\w]", "", title)
    title = re.sub(r"_+", "_", title)
    return title.strip("_")

def clean_gemini_response(text: str) -> str:
    if not text:
        return text
    
    # Strip trailing XML-like tags and markdown backticks recursively
    text = text.strip()
    while True:
        new_text = re.sub(r"<\s*/\s*[a-zA-Z_0-9\-]+\s*>\s*$", "", text)
        new_text = re.sub(r"```\s*$", "", new_text)
        new_text = new_text.strip()
        if new_text == text:
            break
        text = new_text
        
    # 1. Split text into lines
    lines = text.split("\n")
    
    page_prefix_pat = re.compile(r"^\s*\[?[0-9\s,:%]+\]?\s*[\-:\.]")
    
    # Filter out conversational intro/outro lines
    filtered_lines = []
    in_thinking = False
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        if "<thinking>" in line_str:
            in_thinking = True
        if in_thinking or page_prefix_pat.match(line_str):
            filtered_lines.append(line_str)
        if "</thinking>" in line_str:
            in_thinking = False
            
    lines = filtered_lines
    
    # 2. Remove garbage lines from the end
    garbage_words_pat = re.compile(r"PDF|\.pdf|\+\s*\d+|chapter", re.IGNORECASE)
    
    while lines:
        last_line = lines[-1].strip()
        if not last_line:
            lines.pop()
            continue
        
        # Check if it looks like a valid page entry line
        if page_prefix_pat.match(last_line):
            break
        
        # If it doesn't look like a page entry, check if it's garbage
        if garbage_words_pat.search(last_line) or last_line == "#":
            lines.pop()
        else:
            break
            
    # 3. Clean the new last line if it has trailing garbage
    if lines:
        last_line = lines[-1]
        hash_idx = last_line.rfind("#")
        
        strict_garbage_pat = re.compile(r"(PDF\s*\+\s*\d+|\+\s*\d+|PDF\s*\+?\s*\d+)$", re.IGNORECASE)
        
        if hash_idx != -1:
            trailing = last_line[hash_idx+1:].strip()
            # If there's any alphanumeric text after #, it's trailing garbage
            if trailing and re.search(r"[a-zA-Z0-9]", trailing):
                lines[-1] = last_line[:hash_idx+1]
            else:
                # If trailing is empty, check if the content before the hash ends with strict garbage
                last_line_content = last_line[:hash_idx].strip()
                garbage_end_match = strict_garbage_pat.search(last_line_content)
                if garbage_end_match:
                    lines[-1] = last_line_content[:garbage_end_match.start()].strip() + "#"
        else:
            # No hash at all, but does it end with strict garbage?
            last_line_stripped = last_line.strip()
            match = strict_garbage_pat.search(last_line_stripped)
            if match:
                start_idx = match.start()
                cleaned_line = last_line_stripped[:start_idx].strip()
                if cleaned_line:
                    lines[-1] = cleaned_line + "#"
                    
    # 4. Auto-correct missing '#' for each line
    for i in range(len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if line.startswith("<thinking>") or line.endswith("</thinking>"):
            continue
        if page_prefix_pat.match(line):
            if not line.endswith("#"):
                lines[i] = line + "#"
                
    return "\n".join(lines)

def verify_gemini_response_format(text: str) -> tuple[bool, str]:
    if not text:
        return False, "Response is empty"
    
    text = clean_gemini_response(text)
    
    # 1. Check if this is a JSON response
    # If it is valid JSON with speech/images, we bypass the text-format checks.
    extracted = extract_json_from_text(text)
    if extracted and ("\"speech\"" in extracted or "'speech'" in extracted):
        try:
            parsed = json.loads(extracted)
            if isinstance(parsed, list) and len(parsed) > 0:
                valid_json = True
                for item in parsed:
                    if not isinstance(item, dict) or "speech" not in item or "images" not in item:
                        valid_json = False
                        break
                if valid_json:
                    return True, "Valid JSON"
        except Exception:
            pass

    # 2. Clean thinking tags
    clean_text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()
    
    # 3. Check for trailing garbage after the last '#'
    last_hash_idx = clean_text.rfind("#")
    if last_hash_idx == -1:
        return False, "No hash symbol (#) found in the response."
        
    trailing = clean_text[last_hash_idx+1:].strip()
    if trailing:
        # Check if the trailing text contains typical garbage
        if re.search(r"PDF|\.pdf|\+\d+|chapter", trailing, re.IGNORECASE):
            return False, f"Trailing garbage detected after the last hash: '{trailing}'"
        if re.search(r"[a-zA-Z0-9]", trailing):
            return False, f"Extra text found after the last hash: '{trailing}'"

    # 4. Check format line by line
    lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
    if not lines:
        return False, "No non-empty lines found in the response."

    # Check if the last line ends with garbage before the '#'
    last_line = lines[-1]
    last_line_content = last_line[:-1].strip() if last_line.endswith("#") else last_line.strip()
    if re.search(r"(PDF\s*\+\s*\d+|\+\s*\d+|PDF\s*\+?\s*\d+)$", last_line_content, re.IGNORECASE):
        return False, f"Trailing garbage detected at the end of the last line: '{last_line_content}'"

    for idx, line in enumerate(lines):
        if not line.endswith("#"):
            return False, f"Line {idx+1} does not end with the hash symbol (#): '{line}'"
        
        # Verify the line matches the format [Page(s)] - [Text]#
        line_content = line[:-1].strip()
        match = re.match(r"^\[?([0-9\s,:%]+)\]?\s*[\-:\.]?\s*(.+)$", line_content, re.DOTALL)
        if not match:
            return False, f"Line {idx+1} does not match the expected '[Page] - [Text]' format: '{line}'"
            
    return True, "Valid"


def _parse_gemini_image_specs(spec_str: str) -> list[dict]:
    """
    Parses image specs from string formats like:
    - "14" -> [{"page": 14, "priority": 1.0}]
    - "[14, 15]" -> [{"page": 14, "priority": 0.5}, {"page": 15, "priority": 0.5}]
    - "[14:40%, 15:60%]" -> [{"page": 14, "priority": 0.4}, {"page": 15, "priority": 0.6}]
    - "[14:0.3, 15:0.7]" -> [{"page": 14, "priority": 0.3}, {"page": 15, "priority": 0.7}]
    """
    cleaned = spec_str.strip().strip("[]").strip()
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not parts:
        return []

    parsed_images = []
    has_custom_weights = False

    for part in parts:
        if ":" in part:
            p_num_str, weight_str = part.split(":", 1)
            digits = re.sub(r"\D", "", p_num_str)
            if not digits:
                continue
            p_num = int(digits)
            weight_clean = weight_str.replace("%", "").strip()
            try:
                weight_val = float(weight_clean)
                if "%" in weight_str or weight_val > 1.0:
                    weight_val = weight_val / 100.0
            except ValueError:
                weight_val = 1.0
            parsed_images.append({"page": p_num, "priority": max(0.01, weight_val)})
            has_custom_weights = True
        else:
            digits = re.sub(r"\D", "", part)
            if not digits:
                continue
            p_num = int(digits)
            parsed_images.append({"page": p_num, "priority": 1.0})

    if not parsed_images:
        return []

    if not has_custom_weights:
        count = len(parsed_images)
        for img in parsed_images:
            img["priority"] = round(1.0 / count, 4)
    else:
        total = sum(img["priority"] for img in parsed_images)
        if total > 0:
            for img in parsed_images:
                img["priority"] = round(img["priority"] / total, 4)

    # Adjust rounding discrepancy to ensure exact 1.0 sum
    diff = round(1.0 - sum(img["priority"] for img in parsed_images), 4)
    if diff != 0 and parsed_images:
        parsed_images[-1]["priority"] = max(0.01, round(parsed_images[-1]["priority"] + diff, 4))

    return parsed_images


def parse_gemini_recap_text(text: str) -> list:
    if not text:
        return []
    
    text = clean_gemini_response(text)
    
    # Verify response format and check for garbage at the end
    is_valid, err_msg = verify_gemini_response_format(text)
    if not is_valid:
        raise ValueError(f"Kiểm tra định dạng phản hồi Gemini thất bại: {err_msg}")
    # 1. Strip everything between <thinking> and </thinking>
    text_clean = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()
    
    # 2. Clean the text, split by '#'
    segments = text_clean.split("#")
    parsed_list = []
    
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
            
        m = re.match(r"^\[?([0-9\s,:%]+)\]?\s*[\-:\.]?\s*(.*)$", seg, re.DOTALL)
        if m:
            page_spec = m.group(1).strip()
            content = m.group(2).strip()
            if content:
                content = re.sub(r"[\*\_`]", "", content).strip()
                imgs = _parse_gemini_image_specs(page_spec)
                if imgs and content:
                    parsed_list.append({
                        "speech": content,
                        "images": imgs
                    })
                    
    # Fallback to JSON if plain text parsing did not yield any results
    if not parsed_list:
        extracted_json = extract_json_from_text(text)
        if extracted_json:
            try:
                temp_data = json.loads(extracted_json)
                if isinstance(temp_data, list) and len(temp_data) > 0:
                    parsed_list = temp_data
            except Exception:
                pass
                
    # Normalize priorities for downstream components
    for item in parsed_list:
        if isinstance(item, dict) and "speech" in item and "images" in item:
            images_list = item.get("images", [])
            if isinstance(images_list, list) and len(images_list) > 0:
                total_p = sum(float(img.get("priority", 0)) for img in images_list)
                if abs(total_p - 1.0) > 0.02:
                    for img in images_list:
                        img["priority"] = round(1.0 / len(images_list), 4)
                        
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

        title_text = ""
        if "vortexscans.org" in url:
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
        if not title_text:
            title_text = await page.title()
            title_text = title_text.split("|")[0].strip()
            title_text = title_text.split("Chapter")[0].strip()

        max_ep = 0
        if "comix.to" in url:
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
            # Click "Show more" buttons if present on Vortex Scans to fall back
            if "vortexscans.org" in url:
                click_count = 0
                while True:
                    show_more_button = page.locator("button:has-text('Show more')")
                    visible_count = await show_more_button.count()
                    found_clickable = False
                    for idx in range(visible_count):
                        btn = show_more_button.nth(idx)
                        if await btn.is_visible() and await btn.is_enabled():
                            await btn.click()
                            await asyncio.sleep(1.0)
                            click_count += 1
                            found_clickable = True
                            break
                    if not found_clickable or click_count >= 10:
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
                    elif ("vortexscans.org" in url or "toongod.org" in url) and "/chapter-" in href:
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

            if ("vortexscans.org" in url or "toongod.org" in url) and vortex_chapters:
                vortex_chapters = list(set(vortex_chapters))
                def extract_chap_number(slug):
                    m = re.search(r"chapter-(\d+\.?\d*)", slug)
                    if m:
                        try:
                            return float(m.group(1))
                        except ValueError:
                            pass
                    return 0.0
                vortex_chapters.sort(key=extract_chap_number)
                max_ep = len(vortex_chapters)
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
                max_ep = len(vortex_chapters)

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
                threshold=0.15,
                text_threshold=0.15,
                target_sizes=[image.size[::-1]]
            )[0]

            boxes = results_dino["boxes"].cpu().numpy()
            scores = results_dino["scores"].cpu().numpy()
            labels = results_dino.get("text_labels", results_dino.get("labels", []))

            sensitive_keywords = [
                "breast", "butt", "genitalia", "nude", "naked", "underwear", "anus", "sex",
                "exposed chest", "bare chest", "exposed torso", "bare torso"
            ]
            text_keywords = ["speech", "bubble", "text", "words", "written", "write", "dialogue", "letter", "font", "word", "talk"]

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
                    censor_boxes.append(box.tolist())

            censor_mask = np.zeros((h_img, w_img), dtype=bool)
            keep_mask = np.zeros((h_img, w_img), dtype=bool)

            if len(censor_boxes) > 0:
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

            if combined_mask.any():
                if pdf_img_path:
                    # Do not blur or modify the main image (path)
                    # Only black out (mask) in the PDF image (pdf_img_path)
                    img_mask = img_cv.copy()
                    img_mask[combined_mask] = (0, 0, 0)
                    cv2.imwrite(pdf_img_path, img_mask)

                    log_res = f"{file_name}: censored (mask in PDF only) ({len(censor_boxes)} regions)"
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

async def sanitize_episode_images(
    ep_dir: str,
    nsfw_threshold: float,
    nsfw_mode: str,
    from_page: int = None,
    to_page: int = None,
    sse_logger = None,
    concurrency: int = 5,
    pdf_dir: str = None,
    selected_files=None,
    strict: bool = False,
) -> list:
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

    if selected_files is not None:
        selected_set = set(selected_files)
        missing = sorted(selected_set - set(image_files))
        if missing:
            raise ValueError(f"Không tìm thấy ảnh cần kiểm duyệt: {missing}")
        image_files = [file_name for file_name in image_files if file_name in selected_set]
        if not image_files:
            raise ValueError("Danh sách ảnh cần kiểm duyệt đang rỗng.")

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

        from moderation_utils import MODERATION_PROMPT
        prompt = MODERATION_PROMPT
        effective_threshold = max(0.1, nsfw_threshold)

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
        if strict and any(": error" in result.casefold() for result in sanitized_log):
            raise RuntimeError("Một hoặc nhiều ảnh kiểm duyệt bị lỗi.")

    except Exception as e:
        print(f"Lỗi chạy DINO+SAM filter: {str(e)}")
        if strict:
            raise
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
    timeout: int = 160,
    retry_count: int = 5,
    concurrency: int = 5,
    image_quality: int = 80,
    pdf_quality: int = 80,
    language: str = "vi",
    voice_id: str = "ai33pro",
):
    global crawler_running, stop_requested
    stop_requested = False

    success = False
    download_folder_name = None

    async with crawler_lock:
        crawler_running = True
        voice_id = normalize_tts_voice_mode(voice_id)

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
                            image_files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f not in ("chapter.pdf", "gemini_prompt.txt", "stitched.jpg", "stitched_mask.jpg")])
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
                timeout=timeout,
                retry_count=retry_count,
                concurrency=concurrency,
                image_quality=image_quality,
                pdf_quality=pdf_quality,
                language=language,
            )
            success = True
                

        except Exception as e:
            import traceback
            traceback.print_exc()
            await sse_logger.log(f"Lỗi tiến trình crawl/tóm tắt: {str(e)}", "error", "idle", "Sẵn sàng")
        finally:
            crawler_running = False

    if success:
        await run_video_pipeline(download_folder_name, from_ep, to_ep, voice_id=voice_id)


async def run_auto_summarization_flow(
    download_dir: str, title_text: str, from_ep: int, to_ep: int,
    safe_mode: bool = False,
    nsfw_threshold: float = 0.4,
    nsfw_mode: str = "mask",
    timeout: int = 160,
    retry_count: int = 5,
    concurrency: int = 5,
    image_quality: int = 80,
    pdf_quality: int = 80,
    language: str = "vi",
):
    global stop_requested
    vlm_url = "https://gemini.google.com/app"
    vlm_name = "Gemini"
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
                await page.evaluate(js_paste_img, {
                    "xpath": textbox_xpath,
                    "base64Data": img_base64,
                    "fileName": os.path.basename(stitched_path),
                    "mimeType": "image/jpeg"
                })
                await sse_logger.log(f"{step_desc}: Đã đính kèm tệp ảnh thành công bằng Clipboard. Đang chờ 3 giây...", "success")
                await asyncio.sleep(3)


        await sse_logger.log(f"{step_desc}: Đang điền nội dung prompt...", "info")
        await textbox.click(force=True)
        await textbox.fill(prompt_content)
        await sse_logger.log(f"{step_desc}: Đã điền prompt thành công. Đang chờ 5 giây trước khi gửi...", "success")
        await asyncio.sleep(5)
    

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
            await send_button.click(force=True)
            await sse_logger.log(f"{step_desc}: Đã click nút Gửi.", "success")
        else:
            await textbox.press("Enter")
            await sse_logger.log(f"{step_desc}: Đã gửi bằng Enter.", "success")
        

        await sse_logger.log(f"{step_desc}: Đang theo dõi kết quả trả về...", "info")
        raw_json_text = None
        parsed_json = None
        last_logged_len = 0
        last_thinking_text = ""
        unchanged_seconds = 0
        last_checked_text = ""
    

        for _ in range(timeout):
            if stop_requested:
                raise Exception("Tiến trình bị dừng bởi người dùng.")
            await asyncio.sleep(1)
            text_content = ""
            for sel in response_selectors:
                try:
                    loc = page.locator(sel).last
                    if await loc.count() > 0:
                        txt = await loc.inner_text()
                        if txt.strip():
                            if "you are an elite" in txt.lower():
                                continue
                            text_content = txt
                            break
                except Exception:
                    pass
            

            if "can't help with that image" in text_content.lower() or "safety" in text_content.lower() or "không thể giúp" in text_content.lower():
                raise VisionSafetyException("Gemini Vision Safety filter triggered.")
            if text_content:
                if text_content == last_checked_text:
                    unchanged_seconds += 1
                else:
                    unchanged_seconds = 0
                    last_checked_text = text_content

                if len(text_content) > last_logged_len:
                    last_logged_len = len(text_content)
                    # Write debug response
                    try:
                        with open(os.path.join(os.path.dirname(stitched_path), "raw_gemini_response.txt"), "w", encoding="utf-8") as rdf:
                            rdf.write(text_content)
                    except Exception:
                        pass
                

            if not text_content:
                try:
                    thinking_indicator = page.locator("[data-testid='thinking-indicator'], .thinking-container button, .thinking-container").first
                    if await thinking_indicator.count() > 0 and await thinking_indicator.is_visible():
                        thinking_txt = await thinking_indicator.inner_text()
                        thinking_txt = thinking_txt.strip().replace("\n", " ")
                        if thinking_txt and thinking_txt != last_thinking_text:
                            last_thinking_text = thinking_txt
                            await sse_logger.log(f"{step_desc}: Gemini đang suy nghĩ ({thinking_txt})...", "info")
                except Exception:
                    pass

            if text_content:
                # Check thinking container state
                has_thinking = False
                is_still_thinking = False
                has_finished_thinking = False
                
                thinking_container = page.locator(".thinking-container, [data-testid='thinking-indicator']").first
                if await thinking_container.count() > 0 and await thinking_container.is_visible():
                    has_thinking = True
                    chevron_down = page.locator(".thinking-container svg.lucide-chevron-down, [data-testid='thinking-indicator'] svg.lucide-chevron-down").first
                    if await chevron_down.count() > 0 and await chevron_down.is_visible():
                        is_still_thinking = True
                    
                    panel_left_open = page.locator(".thinking-container svg.lucide-panel-left-open, [data-testid='thinking-indicator'] svg.lucide-panel-left-open").first
                    if await panel_left_open.count() > 0 and await panel_left_open.is_visible():
                        has_finished_thinking = True

                # Check if still generating by looking for stop button/icon
                is_generating = False
                stop_button_selectors = [
                    "button[aria-label='Stop generating']",
                    "button[aria-label*='Stop']",
                    "button[aria-label*='stop']",
                    "button[aria-label*='Dừng']",
                    "button[aria-label*='dừng']",
                    "button[data-testid='stop-button']",
                    "[data-testid='stop-button']",
                    "[aria-label='Stop generating']",
                    "[aria-label='Stop']",
                    "[aria-label='stop']",
                    "mat-icon:has-text('stop')",
                    "mat-icon[fonticon='stop']",
                    "gem-icon-button[aria-label*='Stop']",
                    "gem-icon-button[aria-label*='stop']",
                    "gem-icon-button[aria-label*='Dừng']",
                    "gem-icon-button[aria-label*='dừng']"
                ]
                for stop_sel in stop_button_selectors:
                    try:
                        loc = page.locator(stop_sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            is_generating = True
                            break
                    except Exception:
                        pass

                cleaned_content = clean_gemini_response(text_content).strip() if text_content else ""
                can_check_completion = True
                if is_generating:
                    can_check_completion = False

                if has_thinking:
                    if is_still_thinking or not has_finished_thinking:
                        if not cleaned_content.endswith("#"):
                            can_check_completion = False

                # Safety backup check: if response has not changed for at least 8 seconds, we can treat it as done.
                if not can_check_completion and unchanged_seconds >= 8:
                    can_check_completion = True

                if can_check_completion:
                    if cleaned_content.endswith("#"):
                        try:
                            parsed_text = parse_gemini_recap_text(text_content)
                            if parsed_text:
                                parsed_json = parsed_text
                                break
                        except Exception:
                            pass
                        
                extracted = extract_json_from_text(text_content)
                if extracted:
                    try:
                        parsed_json = json.loads(extracted)
                        raw_json_text = extracted
                        break
                    except Exception:
                        pass
        

        if not parsed_json and text_content:
            try:
                parsed_json = parse_gemini_recap_text(text_content)
            except Exception:
                pass

        if not parsed_json:
            raise Exception("Không nhận được kịch bản recap hợp lệ từ Gemini.")

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
    if payload.to_episode < payload.from_episode:
        raise HTTPException(status_code=422, detail="to_episode must be greater than or equal to from_episode")
    url = payload.url.strip()
    parsed_url = urllib.parse.urlparse(url)
    if "asura" in parsed_url.netloc.lower() and parsed_url.netloc.lower() != "asurascans.com":
        url = urllib.parse.urlunparse(parsed_url._replace(netloc="asurascans.com"))
        payload.url = url
        await sse_logger.log(f"Chuẩn hóa tên miền Asura Scans thành: {url}", "info")
    
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

    v_id = normalize_tts_voice_mode(payload.voice_id)
        
    config = {
        "safe_mode": payload.safe_mode,
        "nsfw_threshold": payload.nsfw_threshold,
        "nsfw_mode": payload.nsfw_mode,
        "timeout": payload.timeout,
        "retry_count": payload.retry_count,
        "concurrency": payload.concurrency,
        "image_quality": payload.image_quality,
        "pdf_quality": payload.pdf_quality,
        "language": payload.language,
        "vlm_provider": payload.vlm_provider,
        "voice_id": v_id,
        "ref_audio_path": _validated_asset_reference(payload.ref_audio_path),
        "logo_path": _validated_asset_reference(payload.logo_path),
        "overlay_path": _validated_asset_reference(payload.overlay_path),
        "burn_subtitles": payload.burn_subtitles,
        "remove_text": payload.remove_text,
        "remove_text_conf": payload.remove_text_conf,
        "remove_text_radius": payload.remove_text_radius,
        "comix_group_id": payload.comix_group_id
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
    return [t.to_public_dict(include_logs=False) for t in tasks]


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




def get_unique_sorted_images(ep_dir: str) -> list:
    files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
    files = [f for f in files if f not in ("chapter.pdf", "gemini_prompt.txt", "stitched.jpg")]
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

import json
import os


def generate_gemini_prompt(
    comic_title: str,
    ep: int,
    total_pages: int,
    target_language: str = "vi",
    glossary: str = None,
) -> str:
    language_map = {
        "vi": "Vietnamese",
        "vietnamese": "Vietnamese",
        "en": "English",
        "english": "English",
        "ja": "Japanese",
        "japanese": "Japanese",
        "ko": "Korean",
        "korean": "Korean",
        "zh": "Chinese",
        "chinese": "Chinese",
        "th": "Thai",
        "thai": "Thai",
        "id": "Indonesian",
        "indonesian": "Indonesian",
        "es": "Spanish",
        "spanish": "Spanish",
    }

    lang_key = target_language.strip().lower()
    lang_name = language_map.get(lang_key, target_language.title())

    # ---------------------------------------------------------
    # Glossary
    # ---------------------------------------------------------
    if not glossary:
        try:
            glossary_path = os.path.join(os.getcwd(), "glossary.json")

            with open(
                glossary_path,
                "r",
                encoding="utf-8",
            ) as f:
                data = json.load(f)

            if isinstance(data, dict):
                glossary = ", ".join(
                    f'"{k}" -> "{v}"'
                    for k, v in data.items()
                )
            else:
                glossary = str(data)

        except Exception:
            glossary = "No glossary provided."

    # ---------------------------------------------------------
    # Episode 1 hook
    # ---------------------------------------------------------
    if ep == 1:
        intro_rule = f"""
EPISODE 1 HOOK:

The first output line must function as a strong short-form video hook
that introduces the core premise of "{comic_title}".

Requirements:
- Write the hook entirely in {lang_name}.
- Keep it dramatic, clear, and easy to understand.
- Introduce the protagonist and their initial situation.
- Highlight the main inciting event shown or clearly established by the
  provided material.
- Give viewers a brief teaser of the larger premise without inventing
  events that are not supported by reliable information.
- Do not reveal unnecessary future plot details.
- Do not use humor in the hook.
- End naturally with a short transition that encourages the viewer to
  continue watching.
- Keep the hook concise: approximately 1–2 short sentences.
- Assign the hook to the strongest relevant page showing the protagonist
  or the central story premise.
- The hook must still follow the normal output format.
"""

    else:
        intro_rule = """
EPISODE CONTINUATION:

This is not Episode 1.

Start directly with the story. Do not add introductions, greetings,
episode announcements, or generic welcoming statements.
"""

    # ---------------------------------------------------------
    # Language-specific rules
    # ---------------------------------------------------------
    if lang_key in {"vi", "vietnamese"}:
        language_rules = """
LANGUAGE RULES:
- Write the entire output in natural Vietnamese.
- Use standard Vietnamese Latin script.
- Do not mix Chinese characters, Japanese characters, Korean characters,
  or untranslated foreign phrases into Vietnamese sentences.
- Character names and established proper nouns may remain unchanged when
  translating them would make the name unnatural, unless the glossary
  explicitly provides a Vietnamese equivalent.
- Vietnamese Sino-Vietnamese terminology should be written normally in
  Vietnamese Latin script.
"""
    else:
        language_rules = f"""
LANGUAGE RULES:
- Write the entire output naturally in {lang_name}.
- Do not unnecessarily mix unrelated languages or scripts into the output.
- Follow the glossary consistently.
- Preserve proper names when translating them would be unnatural unless
  an explicit glossary translation is provided.
"""

    # ---------------------------------------------------------
    # Main prompt
    # ---------------------------------------------------------
    return f"""
ROLE:

You are a professional short-form comic recap scriptwriter.

Your job is to analyze the provided comic pages and create a concise,
transformative story recap in {lang_name} for a TikTok/Shorts-style video.

The goal is to help the viewer understand the story while using original
wording, natural narration, and entertaining commentary.

SOURCE:
Title: "{comic_title}"
Episode: {ep}
Total provided pages: {total_pages}

IMPORTANT:
The provided pages are the primary source of truth.

Do not invent events, characters, motivations, dialogue, outcomes, or
future plot developments that are not supported by the provided material.

If a page is unclear, unreadable, or ambiguous, do not guess.
Use only information that can reasonably be established from the visual
content and readable text.

--------------------------------------------------
1. TRANSFORMATIVE RECAP
--------------------------------------------------

Create a concise recap of the major story developments contained in the
provided pages.

This is a recap, not a page-by-page transcription.

Use your own wording and narration.

Do NOT reproduce dialogue, narration, captions, or other source text
verbatim.

Do NOT translate the source text line-by-line.

Instead:
- identify the important events;
- explain what happens in your own words;
- connect events naturally;
- focus on character actions, motivations, conflicts, discoveries,
  consequences, and important reveals;
- remove repetitive or trivial information.

The result should feel like a creator is naturally telling the audience
what happened in the chapter rather than reading or translating the comic.

--------------------------------------------------
2. STORY COVERAGE & DENSE PACING
--------------------------------------------------

Create a rich, fast-paced recap of the {total_pages} provided pages with
approximately 30–45 high-value recap micro-segments (scaled to cover the
entire chapter thoroughly with minimal story gaps).

Cover the important story progression continuously from the beginning
toward the end of the provided material.

Prioritize:
1. important character introductions;
2. major actions and battle sequences;
3. important discoveries and clues;
4. conflicts and character dynamics;
5. turning points and strategy shifts;
6. emotional reactions and expressions;
7. meaningful reveals;
8. the ending or cliffhanger.

Do not artificially create one segment per page, but maintain strong
visual and narrative continuity across the chapter.

The final segment must represent the latest meaningful story development
shown in the provided material.

--------------------------------------------------
3. NATURAL SHORT-FORM STYLE
--------------------------------------------------

Write like a native {lang_name} short-form content creator telling a story.

Style:
- fast-paced and punchy;
- conversational;
- concise (each segment approximately 1–2 short sentences, 2.5s–3.5s spoken);
- dramatic when appropriate;
- easy to understand;
- optimized for TTS;
- short sentences with active verbs;
- natural pauses;
- minimal complicated sentence structures.

Avoid:
- literal translation style;
- academic language;
- excessive exposition;
- repetitive sentence structures;
- unnecessary descriptions of artwork.

The narration should sound natural when spoken aloud.

--------------------------------------------------
4. HUMOR
--------------------------------------------------

For normal recap segments, use light humor, irony, sarcasm, playful
commentary, or relatable observations when they naturally fit the scene.

Humor must support the story rather than replace it.

Do not force a joke into every line.

Do not change the meaning of the original events for the sake of humor.

Episode 1 hook is exempt from the humor requirement.

--------------------------------------------------
5. ACCURACY
--------------------------------------------------

ZERO HALLUCINATION.

Only use information supported by the provided comic pages or reliable
context explicitly available to you.

Never:
- invent future events;
- invent dialogue;
- invent character thoughts;
- invent relationships;
- invent powers or abilities;
- invent explanations;
- continue the story beyond the provided material;
- assume an unreadable panel contains information that cannot be verified.

If something is ambiguous, describe only what can be confidently established.

The recap must end where the provided story material ends.

--------------------------------------------------
6. PROPER NAMES AND GLOSSARY
--------------------------------------------------

Apply this glossary consistently:

{glossary}

If a glossary term conflicts with another interpretation, prefer the
explicit glossary mapping.

Do not randomly translate character names or established fictional terms
unless the glossary or the target language convention clearly supports it.

--------------------------------------------------
7. PAGE & PANEL SELECTION (DIRECT VISUAL MATCHING & MULTI-PANEL DENSITY)
--------------------------------------------------

Every output segment must be assigned to the exact page/panel number(s)
from the provided comic that visually depicts the event, character, or action
described in that segment.

Crucial Visual Grounding & Multi-Panel Rules:
- Direct Alignment: If the narration mentions a specific character, attack,
  discovery, or emotion, select the specific page/panel that clearly SHOWS it.
- Multi-Panel Density (Crucial): To create dynamic visual flow (switching
  images every 1.8s–2.8s), heavily utilize multi-panel ranges (e.g. [12, 13],
  [14, 15, 16], or [20:40%, 21:60%]) whenever a sentence describes a sequence
  of action, reaction, or continuous dialogue.
- High Chapter Coverage: Strive to utilize 50%–80%+ of valid story pages
  throughout the script. Avoid skipping large clusters of consecutive story
  pages (e.g., avoid jumping 10+ pages with no segments).
- Prefer pages containing:
  * characters;
  * meaningful character interactions;
  * important actions;
  * major reveals;
  * strong emotional expressions;
  * visually significant scenes.
- Zero non-story pages: Never assign any segment to a cover, chapter title,
  production info, credit, or pure text card.

--------------------------------------------------
8. ENDING ANCHOR
--------------------------------------------------

The final recap segment must describe the latest meaningful story event
visible in the provided material.

Use the latest suitable story page as its page reference.

Do not continue beyond the supplied pages.

Do not use a credits page, title card, or unrelated final image as the
ending anchor.

--------------------------------------------------
9. EPISODE 1
--------------------------------------------------

{intro_rule}

--------------------------------------------------
10. VIOLENCE AND SENSITIVE MATERIAL
--------------------------------------------------

If the story contains violence or disturbing material, describe it in a
non-graphic narrative style.

Focus on:
- what happened;
- who was affected;
- the consequence;
- how the event changes the story.

Avoid unnecessary graphic descriptions.

Do not exaggerate the severity of an event beyond what is shown.

--------------------------------------------------
11. OUTPUT FORMAT
--------------------------------------------------

The output is consumed by an automated parser.

Return ONLY the following format:

[Page number(s)] - [Recap text]#

Rules:
- One segment per line.
- Every line must end with "#".
- The line starts with page number(s) in brackets (e.g. [5] or [12, 13] or [14, 15, 16] or [14:40%, 15:60%]).
- No title.
- No introduction outside the format.
- No conclusion outside the format.
- No Markdown.
- No bullet points.
- No numbering other than the required page number.
- Do not include analysis or explanations.
- Do not include quotation marks around the recap.
- Keep each segment concise enough for spoken narration.

Examples:

5 - Cậu vừa tưởng mọi chuyện đã kết thúc, nhưng hóa ra rắc rối mới chỉ bắt đầu.#
[12, 13] - Trong lúc mọi người còn hoang mang, anh lập tức rút kiếm chém đứt cánh tay đối thủ.#
[14, 15, 16] - Đòn tấn công uy lực khiến quái vật gầm rú dữ dội rồi đổ gục hoàn toàn xuống đất.#
24 - Và đến cuối cùng, thứ chờ đợi họ lại là một biến cố còn nguy hiểm hơn nữa.#

FINAL VALIDATION BEFORE RESPONDING:

Silently verify that:
1. Every line follows "[Page(s)] - [Text]#".
2. The output uses only {lang_name}.
3. There are approximately 30–45 concise micro-segments with dense multi-panel coverage.
4. No source dialogue or narration has been reproduced verbatim.
5. No unsupported plot event has been invented.
6. The final segment represents the latest meaningful story event.
7. Page references correspond strictly to visually relevant pages/panels.
8. There are no greetings, titles, explanations, or Markdown.
9. The result sounds natural when read aloud.
"""


class OpenFolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comic_folder: str
    episode: int = Field(ge=1)


class ImportJsonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comic_folder: str
    episode: int = Field(ge=1)
    json_content: str


class SaveSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comic_folder: str
    episode: int = Field(ge=1)
    summary_data: list




@app.post("/api/open-pdf-folder")
async def open_pdf_folder(payload: OpenFolderRequest):
    try:
        folder_path = resolve_download_path(payload.comic_folder, f"ep_{payload.episode}", must_exist=True)
    except PathAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Thư mục không tồn tại.") from exc
    if folder_path.exists():
        try:
            os.startfile(str(folder_path))
            return {"status": "success"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Không thể mở thư mục: {str(e)}")
    raise HTTPException(status_code=404, detail="Thư mục không tồn tại.")


@app.get("/api/get-prompt")
async def get_prompt(comic_folder: str, episode: int = 1):
    if episode < 1:
        raise HTTPException(status_code=422, detail="episode must be at least 1")
    try:
        prompt_path = resolve_download_path(comic_folder, f"ep_{episode}", "gemini_prompt.txt")
    except PathAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if prompt_path.exists():
        try:
            with prompt_path.open("r", encoding="utf-8") as f:
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
    

    try:
        ep_dir = resolve_download_path(comic_folder, f"ep_{ep}")
    except PathAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ep_dir.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy thư mục tập {ep} để xác thực ảnh.")
    

    image_files = sorted([f.name for f in ep_dir.iterdir() if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')])
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
    

    narrations_file = ep_dir / "narrations.json"
    with narrations_file.open("w", encoding="utf-8") as f:
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
    

        try:
            save_dir = resolve_download_path(comic_folder)
        except PathAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_dir.mkdir(parents=True, exist_ok=True)
    

        file_name = f"ep_{ep}_summary.json"
        save_path = save_dir / file_name
    

        with save_path.open("w", encoding="utf-8") as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
        

        await sse_logger.log(f"Tập {ep}: Lưu summary thành công vào file '{file_name}'.", "success")
        return {"status": "success", "message": f"Đã lưu summary tập {ep} thành công."}
    except HTTPException:
        raise
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
                image_files = sorted([f for f in os.listdir(ep_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f not in ("chapter.pdf", "gemini_prompt.txt", "stitched.jpg")])
                prompt_content = generate_gemini_prompt(title_text, ep, len(image_files), "vi")
                with open(prompt_path, "w", encoding="utf-8") as pf:
                    pf.write(prompt_content)
                await sse_logger.log("[TEST] Đã tạo thành công stitched.jpg và gemini_prompt.txt.", "success")
        
            # 3. Perform headed Gemini browser test
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
                    try:
                        await textbox.click(force=True)
                        if stop_requested:
                            raise Exception("Tiến trình test bị dừng bởi người dùng.")
                        await textbox.fill(prompt_content)
                        await sse_logger.log("[TEST] Đã điền nội dung prompt thành công. Đang chờ 5 giây trước khi gửi...", "success")

                        await sse_logger.log(f"[TEST] Đang gửi yêu cầu (gửi tệp và prompt) tới {vlm_name}...", "info")
                        if stop_requested:
                            raise Exception("Tiến trình test bị dừng bởi người dùng.")

                        await asyncio.sleep(5)
                    

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
                            "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[5]/div[2]/div[2]/gem-icon-button/button",
                            "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[3]/div[2]/div[2]/gem-icon-button/button",
                            "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div[2]/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[3]/div[2]/div[2]/gem-icon-button/button",
                            "xpath=/html/body/chat-app-orchestrator/chat-app/main/side-navigation-v2/bard-sidenav-container/bard-sidenav-content/div/div/div/chat-window/div/input-container/fieldset/input-area-v2/div/div/div[5]/div[2]/div[2]/gem-icon-button",
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
                            # Read text from response selectors
                            text_content = ""
                            for sel in response_selectors:
                                try:
                                    loc = page.locator(sel).last
                                    if await loc.count() > 0:
                                        txt = await loc.inner_text()
                                        if txt.strip():
                                            if "you are an elite" in txt.lower():
                                                continue
                                            text_content = txt
                                            break
                                except Exception:
                                    pass
                        
                            if not text_content:
                                try:
                                    thinking_indicator = page.locator("[data-testid='thinking-indicator'], .thinking-container button, .thinking-container").first
                                    if await thinking_indicator.count() > 0 and await thinking_indicator.is_visible():
                                        thinking_txt = await thinking_indicator.inner_text()
                                        thinking_txt = thinking_txt.strip().replace("\n", " ")
                                        if thinking_txt and thinking_txt != last_thinking_text:
                                            last_thinking_text = thinking_txt
                                            await sse_logger.log(f"[TEST] Gemini đang suy nghĩ ({thinking_txt})...", "info")
                                except Exception:
                                    pass

                            # Check thinking container state
                            has_thinking = False
                            is_still_thinking = False
                            has_finished_thinking = False
                            
                            thinking_container = page.locator(".thinking-container, [data-testid='thinking-indicator']").first
                            if await thinking_container.count() > 0 and await thinking_container.is_visible():
                                has_thinking = True
                                chevron_down = page.locator(".thinking-container svg.lucide-chevron-down, [data-testid='thinking-indicator'] svg.lucide-chevron-down").first
                                if await chevron_down.count() > 0 and await chevron_down.is_visible():
                                    is_still_thinking = True
                                
                                panel_left_open = page.locator(".thinking-container svg.lucide-panel-left-open, [data-testid='thinking-indicator'] svg.lucide-panel-left-open").first
                                if await panel_left_open.count() > 0 and await panel_left_open.is_visible():
                                    has_finished_thinking = True

                            cleaned_content = clean_gemini_response(text_content).strip() if text_content else ""
                            can_check_completion = True
                            if has_thinking:
                                if is_still_thinking or not has_finished_thinking:
                                    if not cleaned_content.endswith("#"):
                                        can_check_completion = False

                            if text_content and can_check_completion:
                                # Save raw text for debugging
                                if len(text_content) > last_logged_len:
                                    raw_debug_path = os.path.join(ep_dir, "raw_gemini_response.txt")
                                    try:
                                        with open(raw_debug_path, "w", encoding="utf-8") as rdf:
                                            rdf.write(text_content)
                                    except Exception:
                                        pass
                                    last_logged_len = len(text_content)
                                

                                extracted = extract_json_from_text(text_content)
                                if extracted:
                                    # Try parsing JSON to verify completeness
                                    try:
                                        parsed = json.loads(extracted)
                                        raw_json_text = extracted
                                        mock_json = parsed
                                        gemini_web_success = True
                                        await sse_logger.log("[TEST] Đã trích xuất và biên dịch thành công JSON đầy đủ!", "success")
                                        break
                                    except Exception:
                                        # Not complete or malformed yet, continue waiting
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
async def run_test_endpoint(payload: TestRequest):
    if os.getenv("RECAP_ENABLE_LEGACY_TESTS", "").strip() != "1":
        raise HTTPException(status_code=404, detail="Legacy test endpoint is disabled.")
    global crawler_running
    if crawler_running:
        await sse_logger.log("Yêu cầu chạy test bị từ chối: Một tiến trình khác đang chạy.", "warning")
        raise HTTPException(status_code=409, detail="A task is already running.")
    

    logo_path = _validated_asset_reference(payload.logo_path)
    overlay_path = _validated_asset_reference(payload.overlay_path)
    asyncio.create_task(run_test_task(logo_path, overlay_path))
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
                    

    await sse_logger.log(f"Đã xóa thành công {len(deleted_files)} file cache và tệp tải lên.", "success")
    return {"status": "success", "message": f"Đã xóa {len(deleted_files)} cache files thành công."}

@app.post("/api/upload-logo")
async def upload_logo(file: UploadFile = File(...)):
    import uuid
    os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Logo must be a PNG, JPEG, or WebP image.")
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
    os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
    source_ext = os.path.splitext(file.filename or "")[1].lower()
    if source_ext not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
        raise HTTPException(status_code=400, detail="Reference audio has an unsupported file type.")
    temp_filename = f"temp_ref_{uuid.uuid4().hex}{source_ext}"
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
    os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Overlay must be a PNG, JPEG, or WebP image.")
    filename = f"overlay_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join("static", "uploads", filename)
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    return {"status": "success", "file_path": file_path, "url": f"/uploads/{filename}"}

class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comic_folder: str
    from_episode: int = Field(ge=1)
    to_episode: int = Field(ge=1)
    voice_id: str = "ai33pro"
    logo_path: str = None
    overlay_path: str = None
    remove_text: bool = True
    remove_text_conf: float = 0.3
    remove_text_radius: int = 3
    ref_audio_path: Optional[str] = None

def find_ffmpeg() -> str:
    import shutil
    # 1. Check in PATH
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    # 2. Check CapCut AppData directory
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

    # 3. Fail safe fallback
    return "ffmpeg"

def get_working_encoder(ffmpeg_path: str, test_image: str) -> str:
    import subprocess
    import sys
    encoders = ['h264_videotoolbox', 'h264_nvenc', 'h264_amf', 'h264_qsv', 'libx264']
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
        extra_args = ["-crf", "20", "-preset", "veryfast"]
    elif encoder == "h264_nvenc":
        extra_args = ["-cq", "20", "-preset", "p1"]
    elif encoder == "h264_amf":
        extra_args = ["-rc", "cqp", "-qp_i", "20", "-qp_p", "20"]
    elif encoder == "h264_qsv":
        extra_args = ["-global_quality", "20"]
    else:
        extra_args = ["-b:v", "6M"]

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
            # Foreground sizing
            if crop_aspect > target_aspect:
                fg_w = target_w
                fg_h = int(target_w / crop_aspect)
            else:
                fg_h = target_h
                fg_w = int(target_h * crop_aspect)
                
            # Ensure main image width is at least 1/3 of video width
            min_fg_w = target_w // 3
            if fg_w < min_fg_w:
                fg_w = min_fg_w
                fg_h = int(round(fg_w / crop_aspect))
                
            if fg_w <= 0: fg_w = 1
            if fg_h <= 0: fg_h = 1


            
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
    voice_id: str = "ai33pro", 
    logo_path: str = None, 
    overlay_path: str = None,
    remove_text: bool = True,
    remove_text_conf: float = 0.3,
    remove_text_radius: int = 3,
    ref_audio_path: str = None
):
    global crawler_running, stop_requested
    stop_requested = False

    if from_ep < 1 or to_ep < from_ep:
        raise ValueError("Invalid episode range")
    download_dir = str(resolve_download_path(comic_folder, must_exist=True))
    logo_path = str(resolve_upload_path(logo_path, must_exist=True)) if logo_path else None
    overlay_path = str(resolve_upload_path(overlay_path, must_exist=True)) if overlay_path else None
    ref_audio_path = str(resolve_upload_path(ref_audio_path, must_exist=True)) if ref_audio_path else None

    import httpx
    async with crawler_lock:
        crawler_running = True
        await sse_logger.log(f"Bắt đầu quy trình tạo video cho thư mục '{comic_folder}'...", "system", "active", "Đang tạo video...")

        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))

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
                success = await generate_tts(concatenated_text, audio_path, srt_path, voice_id, ref_audio_path)
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

            # 3. Parse transcript.srt
            await sse_logger.log("Đang phân tích transcript.srt...", "info")
            with open(srt_path, "r", encoding="utf-8") as f:
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

            # Map subtitles to segments
            if len(subtitles) == len(summary_segments):
                for idx_sub, sub in enumerate(subtitles):
                    sub["matched_segment_idx"] = idx_sub
            else:
                # Compute subtitle words and running totals
                sub_word_counts = []
                total_subtitle_words = 0
                for sub in subtitles:
                    words = [clean_w(w) for w in sub["text"].split() if clean_w(w)]
                    sub_word_counts.append(len(words))
                    total_subtitle_words += len(words)

                ratio = total_segment_words / total_subtitle_words if total_subtitle_words > 0 else 1

                prev_words = 0
                for idx, sub in enumerate(subtitles):
                    count = sub_word_counts[idx]
                    if count == 0:
                        mid_word_idx = prev_words
                    else:
                        mid_word_idx = prev_words + count // 2

                    # Scale word pointer to segment space to be invariant to deletions/inserts
                    scaled_word_idx = mid_word_idx * ratio
                    
                    # Find which segment contains this scaled word index
                    matched_seg = len(summary_segments) - 1
                    for seg_idx, (start, end) in enumerate(segment_ranges):
                        if start <= scaled_word_idx < end:
                            matched_seg = seg_idx
                            break
                    sub["matched_segment_idx"] = matched_seg
                    prev_words += count

            # 4b. Subtitle Normalization & Re-alignment (matching segments count and text)
            from tts_provider import format_timestamp
            normalized_srt_entries = []
            last_end_time = 0.0
            
            for seg_idx, seg in enumerate(summary_segments):
                matched_subs = [sub for sub in subtitles if sub.get("matched_segment_idx") == seg_idx]
                if matched_subs:
                    start_time = min(sub["start"] for sub in matched_subs)
                    end_time = max(sub["end"] for sub in matched_subs)
                else:
                    start_time = last_end_time
                    word_count = len(seg.get("speech", "").split())
                    estimated_dur = max(2.0, word_count * 0.4)
                    end_time = start_time + estimated_dur
                
                if start_time < last_end_time: start_time = last_end_time
                if end_time <= start_time: end_time = start_time + 1.0
                
                last_end_time = end_time
                normalized_srt_entries.append({
                    "start": start_time,
                    "end": end_time,
                    "text": seg.get("speech", "")
                })

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
                            
                            extra_args = ["-crf", "20", "-preset", "veryfast"] if working_encoder == "libx264" else ["-b:v", "6M"]
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
                final_args = ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]
            elif working_encoder == "h264_nvenc":
                final_args = ["-c:v", "h264_nvenc", "-cq", "20", "-preset", "p1"]
            elif working_encoder == "h264_amf":
                final_args = ["-c:v", "h264_amf", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"]
            elif working_encoder == "h264_qsv":
                final_args = ["-c:v", "h264_qsv", "-global_quality", "20"]
            else:
                final_args = ["-c:v", working_encoder, "-b:v", "6M"]

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

            final_cmd = [
                ffmpeg_exe, "-y",
                "-i", "combined_silent.mp4",
                "-i", "audio.mp3",
                "-i", logo_path_to_use,
                "-i", overlay_path_to_use,
                "-filter_complex", "[2:v]scale=50:50[logo];[3:v]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.005[ol];[0:v][ol]overlay[temp1];[temp1][logo]overlay=25:25[v]",
                "-map", "[v]",
                "-map", "1:a"
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
            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            await sse_logger.log(f"Lỗi tiến trình tạo video: {str(e)}", "error", "idle", "Sẵn sàng")
            return False
        finally:
            crawler_running = False

VIDEO_RUNTIME_ROOT = (Path(__file__).resolve().parent / "runtime" / "video-jobs").resolve()


def _video_job_dir(job_id: str) -> Path:
    try:
        normalized = str(__import__("uuid").UUID(job_id))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail="Video job not found.") from exc
    return VIDEO_RUNTIME_ROOT / normalized


@app.post("/api/generate-video")
async def generate_video(payload: VideoRequest):
    if payload.to_episode < payload.from_episode:
        raise HTTPException(status_code=422, detail="to_episode must be greater than or equal to from_episode")
    try:
        resolve_download_path(payload.comic_folder, must_exist=True)
    except PathAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Comic folder does not exist.") from exc

    import uuid
    job_id = str(uuid.uuid4())
    job_dir = VIDEO_RUNTIME_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    worker_input = {
        "job_id": job_id,
        "comic_folder": payload.comic_folder,
        "from_episode": payload.from_episode,
        "to_episode": payload.to_episode,
        "voice_id": normalize_tts_voice_mode(payload.voice_id),
        "logo_path": _validated_asset_reference(payload.logo_path),
        "overlay_path": _validated_asset_reference(payload.overlay_path),
        "remove_text": payload.remove_text,
        "remove_text_conf": payload.remove_text_conf,
        "remove_text_radius": payload.remove_text_radius,
        "ref_audio_path": _validated_asset_reference(payload.ref_audio_path),
    }
    atomic_write_json(job_dir / "input.json", worker_input)
    command = [sys.executable, "-m", "video_worker", "--job-dir", str(job_dir)]
    env = os.environ.copy()
    env["RECAP_WORKER_PROCESS"] = "1"
    env["RECAP_TASK_DB"] = str(job_dir / "worker_app_state.json")
    process = await asyncio.to_thread(
        popen_command,
        command,
        cwd=Path(__file__).resolve().parent,
        env=env,
    )
    identity = identity_for_process(process, command)
    atomic_write_json(job_dir / "launch.json", identity.to_dict())
    return {
        "status": "success",
        "message": f"Bắt đầu quy trình tạo video cho {payload.comic_folder} trong worker riêng.",
        "job_id": job_id,
        "status_url": f"/api/video-jobs/{job_id}",
    }


@app.get("/api/video-jobs/{job_id}")
async def get_video_job(job_id: str):
    job_dir = _video_job_dir(job_id)
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="Video job not found.")
    status_path = job_dir / "status.json"
    if status_path.is_file():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"status": "running", "message": "Worker status is being updated."}
    else:
        data = {"status": "running", "message": "Worker is starting."}
        launch_path = job_dir / "launch.json"
        if launch_path.is_file():
            try:
                identity = ProcessIdentity.from_dict(json.loads(launch_path.read_text(encoding="utf-8")))
                if not process_matches(identity):
                    data = {"status": "failed", "message": "Video worker exited before reporting status."}
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                data = {"status": "failed", "message": "Video worker identity is invalid."}
    return {
        "job_id": job_id,
        "status": data.get("status", "failed"),
        "message": redact_sensitive_text(str(data.get("message", ""))),
        "final_video_url": data.get("final_video_url"),
    }

    # Mount static files (style.css, app.js)
    # Mount downloads static directory
os.makedirs("downloads", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

    # Mount static files (style.css, app.js)
app.mount("/", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
