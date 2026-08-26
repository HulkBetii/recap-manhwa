import abc
import asyncio
import json
import os
import threading
import time
import uuid
from typing import Dict, List, Any, Optional

from security_utils import public_artifacts, redact_sensitive_text, strip_sensitive_fields
from recap_schema import validate_recap_file
from tts_settings import normalize_tts_voice_mode

# --- CORE EVENTS & lifecycle states ---
class WorkflowState:
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

class StageState:
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

# --- TASK DATA MODEL ---
class WorkflowTask:
    def __init__(
        self,
        comic_title: str,
        comic_url: str,
        from_episode: int,
        to_episode: int,
        payload: Dict[str, Any],
        id: Optional[str] = None
    ):
        self.id = id or str(uuid.uuid4())
        self.comic_title = comic_title
        self.comic_url = comic_url
        self.from_episode = from_episode
        self.to_episode = to_episode
        self.payload = payload
        if "voice_id" in self.payload:
            self.payload["voice_id"] = normalize_tts_voice_mode(self.payload.get("voice_id"))
        
        self.creation_time = payload.get("creation_time") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.started_time: Optional[str] = payload.get("started_time")
        self.finished_time: Optional[str] = payload.get("finished_time")
        self.status = payload.get("status") or WorkflowState.WAITING
        self.current_stage = payload.get("current_stage") or "Stage 0 - Project Init"
        self.current_episode: Optional[int] = payload.get("current_episode")
        
        # Define 14 stages list
        self.stages = payload.get("stages") or [
            {"name": "Stage 0 - Project Init", "status": StageState.WAITING, "progress": 0.0, "weight": 0.02},
            {"name": "Stage 1 - Comic Parsing", "status": StageState.WAITING, "progress": 0.0, "weight": 0.03},
            {"name": "Stage 2 - Image Crawling", "status": StageState.WAITING, "progress": 0.0, "weight": 0.12},
            {"name": "Stage 2b - Intelligent Re-pagination", "status": StageState.WAITING, "progress": 0.0, "weight": 0.05},
            {"name": "Stage 3 - NSFW Moderation", "status": StageState.WAITING, "progress": 0.0, "weight": 0.08},
            {"name": "Stage 4 - PDF Generation", "status": StageState.WAITING, "progress": 0.0, "weight": 0.05},
            {"name": "Stage 5 - Gemini Automation", "status": StageState.WAITING, "progress": 0.0, "weight": 0.15},
            {"name": "Stage 6 - JSON Extraction", "status": StageState.WAITING, "progress": 0.0, "weight": 0.05},
            {"name": "Stage 7 - Narration Aggregation", "status": StageState.WAITING, "progress": 0.0, "weight": 0.02},
            {"name": "Stage 8 - Local TTS", "status": StageState.WAITING, "progress": 0.0, "weight": 0.15},
            {"name": "Stage 9 - Subtitle Normalization", "status": StageState.WAITING, "progress": 0.0, "weight": 0.03},
            {"name": "Stage 10 - Episode Video Rendering", "status": StageState.WAITING, "progress": 0.0, "weight": 0.15},
            {"name": "Stage 11 - Final Video Assembly", "status": StageState.WAITING, "progress": 0.0, "weight": 0.05},
            {"name": "Stage 12 - Metadata & Reports", "status": StageState.WAITING, "progress": 0.0, "weight": 0.03},
            {"name": "Stage 13 - Cleanup", "status": StageState.WAITING, "progress": 0.0, "weight": 0.02},
            {"name": "Completed", "status": StageState.WAITING, "progress": 0.0, "weight": 0.0}
        ]
        
        self.overall_progress = payload.get("overall_progress") or 0.0
        self.episode_progress: Dict[str, Dict[str, str]] = payload.get("episode_progress") or {}
        self.completed_count = payload.get("completed_count") or 0
        self.failed_count = payload.get("failed_count") or 0
        self.elapsed_time = payload.get("elapsed_time") or 0.0
        self.estimated_remaining_time: Optional[float] = payload.get("estimated_remaining_time")
        self.logs: List[Dict[str, Any]] = payload.get("logs") or []
        self.error_message: Optional[str] = payload.get("error_message")
        self.artifacts: Dict[str, Any] = payload.get("artifacts") or {}
        self.runtime: Dict[str, Any] = payload.get("runtime") or {}

    def to_storage_dict(self, include_logs: bool = True) -> Dict[str, Any]:
        result = strip_sensitive_fields(self.payload.copy())
        result.update({
            "id": self.id,
            "comic_title": self.comic_title,
            "comic_url": self.comic_url,
            "from_episode": self.from_episode,
            "to_episode": self.to_episode,
            "creation_time": self.creation_time,
            "started_time": self.started_time,
            "finished_time": self.finished_time,
            "status": self.status,
            "current_stage": self.current_stage,
            "current_episode": self.current_episode,
            "stages": self.stages,
            "overall_progress": self.overall_progress,
            "episode_progress": self.episode_progress,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "elapsed_time": self.elapsed_time,
            "estimated_remaining_time": self.estimated_remaining_time,
            "logs": strip_sensitive_fields(self.logs) if include_logs else [],
            "error_message": redact_sensitive_text(self.error_message),
            "artifacts": self.artifacts,
            "runtime": self.runtime,
            "language": self.payload.get("language", "vi")
        })
        return strip_sensitive_fields(result)

    def to_public_dict(self, include_logs: bool = True) -> Dict[str, Any]:
        return {
            "id": self.id,
            "comic_title": self.comic_title,
            "comic_url": self.comic_url,
            "from_episode": self.from_episode,
            "to_episode": self.to_episode,
            "creation_time": self.creation_time,
            "started_time": self.started_time,
            "finished_time": self.finished_time,
            "status": self.status,
            "current_stage": self.current_stage,
            "current_episode": self.current_episode,
            "stages": strip_sensitive_fields(self.stages),
            "overall_progress": self.overall_progress,
            "episode_progress": strip_sensitive_fields(self.episode_progress),
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "elapsed_time": self.elapsed_time,
            "estimated_remaining_time": self.estimated_remaining_time,
            "logs": strip_sensitive_fields(self.logs) if include_logs else [],
            "error_message": redact_sensitive_text(self.error_message),
            "artifacts": public_artifacts(self.artifacts),
            "language": self.payload.get("language", "vi"),
        }

    def to_dict(self, include_logs: bool = True) -> Dict[str, Any]:
        return self.to_storage_dict(include_logs=include_logs)

# --- CANCELLATION TOKEN ---
class CancellationToken:
    def __init__(self):
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def is_cancelled(self) -> bool:
        return self._is_cancelled

# --- EVENT BUS ---
class EventBus:
    def __init__(self):
        self.subscribers = []

    def subscribe(self, callback):
        self.subscribers.append(callback)

    def unsubscribe(self, callback):
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    async def publish(self, event_name: str, task_id: str, data: Dict[str, Any]):
        for sub in list(self.subscribers):
            try:
                if asyncio.iscoroutinefunction(sub):
                    await sub(event_name, task_id, data)
                else:
                    sub(event_name, task_id, data)
            except Exception as e:
                print(f"Error publishing event {event_name}: {e}", flush=True)

# --- REPOSITORY ---
class BaseWorkflowRepository(abc.ABC):
    @abc.abstractmethod
    def save(self, task: WorkflowTask): pass
    @abc.abstractmethod
    def load(self, task_id: str) -> Optional[WorkflowTask]: pass
    @abc.abstractmethod
    def load_all(self) -> List[WorkflowTask]: pass
    @abc.abstractmethod
    def update(self, task: WorkflowTask): pass
    @abc.abstractmethod
    def delete(self, task_id: str): pass

class JSONWorkflowRepository(BaseWorkflowRepository):
    def __init__(self, file_path: str = "tasks_db.json"):
        self.file_path = file_path
        self._tasks = {}
        self._lock = threading.RLock()
        self._load_from_disk()

    def _load_from_disk(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    scrubbed = False
                    for tid, tdata in data.items():
                        try:
                            payload = strip_sensitive_fields(tdata.copy())
                            scrubbed = scrubbed or payload != tdata
                            # Safely extract title from logs if missing
                            comic_title = tdata.get("comic_title")
                            if not comic_title:
                                for log in tdata.get("logs", []):
                                    if "Comic official title:" in log.get("message", ""):
                                        comic_title = log["message"].split("Comic official title:")[-1].strip()
                                        break
                            if not comic_title:
                                comic_title = "Unknown Comic"

                            task = WorkflowTask(
                                comic_title=comic_title,
                                comic_url=tdata.get("comic_url", ""),
                                from_episode=tdata.get("from_episode", 1),
                                to_episode=tdata.get("to_episode", 1),
                                payload=payload,
                                id=tid
                            )
                            scrubbed = scrubbed or task.payload != tdata
                            self._tasks[tid] = task
                        except Exception as item_err:
                            print(f"Error loading individual task {tid}: {item_err}", flush=True)
            except Exception as e:
                print(f"Error loading tasks: {e}", flush=True)
            else:
                if scrubbed:
                    self._save_to_disk()

    def _save_to_disk(self):
        with self._lock:
            try:
                data = {tid: task.to_storage_dict() for tid, task in self._tasks.items()}
                temp_filepath = self.file_path + ".tmp"
                with open(temp_filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(temp_filepath, self.file_path)
            except Exception as e:
                print(f"Error saving tasks: {e}", flush=True)

    def save(self, task: WorkflowTask):
        self._tasks[task.id] = task
        self._save_to_disk()

    def load(self, task_id: str) -> Optional[WorkflowTask]:
        return self._tasks.get(task_id)

    def load_all(self) -> List[WorkflowTask]:
        return sorted(self._tasks.values(), key=lambda t: t.creation_time, reverse=True)

    def update(self, task: WorkflowTask):
        self._tasks[task.id] = task
        self._save_to_disk()

    def delete(self, task_id: str):
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._save_to_disk()

# --- WORKFLOW CONTEXT ---
class WorkflowContext:
    def __init__(self, task: WorkflowTask, config: Dict[str, Any], manager: "WorkflowManager"):
        self.task = task
        self.config = config
        self.manager = manager
        self.cancel_token = manager.get_cancel_token(task.id)

    async def log(self, message: str, level: str = "info", stage_name: Optional[str] = None, episode: Optional[int] = None):
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        safe_message = redact_sensitive_text(str(message)) or ""
        log_entry = {
            "timestamp": timestamp,
            "message": safe_message,
            "level": level,
            "stage": stage_name or self.task.current_stage,
            "episode": episode or self.task.current_episode
        }
        self.task.logs.append(log_entry)
        print(f"[{self.task.comic_title}] [{level.upper()}] {safe_message}", flush=True)
        await self.manager.save_and_broadcast("WorkflowProgressUpdated", self.task)

    async def update_stage_progress(self, stage_name: str, progress: float):
        for s in self.task.stages:
            if s["name"] == stage_name:
                s["progress"] = progress
                break
        await self.manager.calculate_overall_progress(self.task)
        await self.manager.save_and_broadcast("WorkflowProgressUpdated", self.task)

    async def start_episode(self, episode: int):
        self.task.current_episode = episode
        ep_key = str(episode)
        if ep_key not in self.task.episode_progress:
            self.task.episode_progress[ep_key] = {}
        self.task.episode_progress[ep_key][self.task.current_stage] = StageState.RUNNING
        await self.manager.save_and_broadcast("EpisodeStarted", self.task)

    async def complete_episode(self, episode: int):
        ep_key = str(episode)
        if ep_key not in self.task.episode_progress:
            self.task.episode_progress[ep_key] = {}
        self.task.episode_progress[ep_key][self.task.current_stage] = StageState.SUCCESS
        self.task.completed_count = sum(
            1 for ep_num, stages in self.task.episode_progress.items()
            if all(status == StageState.SUCCESS for status in stages.values())
        )
        await self.manager.save_and_broadcast("EpisodeCompleted", self.task)

    async def fail_episode(self, episode: int, error_msg: str):
        ep_key = str(episode)
        if ep_key not in self.task.episode_progress:
            self.task.episode_progress[ep_key] = {}
        self.task.episode_progress[ep_key][self.task.current_stage] = StageState.FAILED
        self.task.failed_count = sum(
            1 for ep_num, stages in self.task.episode_progress.items()
            if any(status == StageState.FAILED for status in stages.values())
        )
        await self.log(f"Episode {episode} failed: {error_msg}", "error", episode=episode)
        await self.manager.save_and_broadcast("EpisodeFailed", self.task)

# --- BASE STAGE INTERFACE ---
class BaseStage(abc.ABC):
    handles_retries = False

    @property
    @abc.abstractmethod
    def name(self) -> str: pass

    @property
    @abc.abstractmethod
    def weight(self) -> float: pass

    @abc.abstractmethod
    async def execute(self, context: WorkflowContext) -> bool: pass


# --- HELPER FUNCTIONS FOR RESUME / INCREMENTAL PROCESSING ---

def check_episode_completed(download_dir: Optional[str], ep: int) -> bool:
    if not download_dir:
        return False
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    if not os.path.exists(ep_dir):
        return False
    
    recap_path = os.path.join(ep_dir, "recap.json")
    audio_path = os.path.join(ep_dir, "audio.mp3")
    srt_path = os.path.join(ep_dir, "transcript.srt")
    video_path = os.path.join(ep_dir, "video.mp4")
    
    # 1. Check existence of key files
    if not (os.path.exists(recap_path) and os.path.exists(audio_path) and os.path.exists(srt_path) and os.path.exists(video_path)):
        return False
        
    # 2. Check sizes are non-zero
    if os.path.getsize(audio_path) == 0 or os.path.getsize(srt_path) == 0 or os.path.getsize(video_path) == 0:
        return False
        
    # 2b. Verify MP4 integrity by scanning for the mandatory 'moov' atom in the first/last MB of the file
    try:
        video_size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            if video_size < 1024 * 1024:
                if b"moov" not in f.read():
                    return False
            else:
                f.seek(0)
                if b"moov" not in f.read(1024 * 1024):
                    f.seek(video_size - 1024 * 1024)
                    if b"moov" not in f.read(1024 * 1024):
                        return False
    except Exception:
        return False
        
    image_dir = os.path.join(ep_dir, "images_blur")
    if not os.path.isdir(image_dir):
        image_dir = os.path.join(ep_dir, "images_pdf")
    max_page = None
    if os.path.isdir(image_dir):
        max_page = sum(
            1
            for name in os.listdir(image_dir)
            if os.path.isfile(os.path.join(image_dir, name))
            and name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ) or None
    if not validate_recap_file(recap_path, max_page=max_page):
        return False
        
    return True
