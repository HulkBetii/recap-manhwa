import abc
import asyncio
import json
import os
import time
import uuid
import threading
from typing import Dict, List, Any, Optional

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
        
        self.creation_time = payload.get("creation_time") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.started_time: Optional[str] = payload.get("started_time")
        self.finished_time: Optional[str] = payload.get("finished_time")
        self.status = payload.get("status") or WorkflowState.WAITING
        self.current_stage = payload.get("current_stage") or "Stage 0 - Project Init"
        self.current_episode: Optional[int] = payload.get("current_episode")
        
        # Define 5 Core Modular Phases list with exact weights summing to 1.00
        self.stages = payload.get("stages") or [
            {"name": "Phase 1 - Thu thập & Xử lý Hình ảnh", "status": StageState.WAITING, "progress": 0.0, "weight": 0.30},
            {"name": "Phase 2 - Tạo Kịch bản AI VLM", "status": StageState.WAITING, "progress": 0.0, "weight": 0.25},
            {"name": "Phase 3 - Xử lý Cấu trúc Kịch bản", "status": StageState.WAITING, "progress": 0.0, "weight": 0.10},
            {"name": "Phase 4 - Giọng đọc TTS & Phụ đề", "status": StageState.WAITING, "progress": 0.0, "weight": 0.15},
            {"name": "Phase 5 - Ghép Nối & Xuất Bản", "status": StageState.WAITING, "progress": 0.0, "weight": 0.20},
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

    def to_dict(self, include_logs: bool = True) -> Dict[str, Any]:
        result = self.payload.copy()
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
            "logs": self.logs if include_logs else [],
            "error_message": self.error_message,
            "artifacts": self.artifacts,
            "language": self.payload.get("language", "vi")
        })
        return result

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
        self._lock = threading.Lock()
        self._tasks = {}
        self._load_from_disk()

    def _load_from_disk(self):
        with self._lock:
            target_path = self.file_path
            if (not os.path.exists(target_path) or os.path.getsize(target_path) <= 2) and os.path.exists("tasks.json") and os.path.getsize("tasks.json") > 2:
                target_path = "tasks.json"

            if os.path.exists(target_path):
                try:
                    with open(target_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for tid, tdata in data.items():
                            try:
                                payload = tdata.copy()
                                if payload.get("status") in [WorkflowState.RUNNING, WorkflowState.WAITING]:
                                    payload["status"] = WorkflowState.FAILED
                                    payload["error_message"] = "Task was interrupted by server shutdown."
                                    for stage in payload.get("stages", []):
                                        if stage.get("status") in [StageState.RUNNING, StageState.WAITING]:
                                            stage["status"] = StageState.FAILED
                                
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
                                self._tasks[tid] = task
                            except Exception as item_err:
                                print(f"Error loading individual task {tid}: {item_err}", flush=True)
                except Exception as e:
                    print(f"Error loading tasks: {e}", flush=True)

    def _save_to_disk(self):
        with self._lock:
            for attempt in range(5):
                try:
                    data = {tid: task.to_dict() for tid, task in self._tasks.items()}
                    temp_filepath = f"{self.file_path}.tmp_{os.getpid()}_{int(time.time()*1000)}"
                    with open(temp_filepath, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    os.replace(temp_filepath, self.file_path)
                    break
                except Exception as e:
                    if attempt == 4:
                        print(f"Error saving tasks after 5 attempts: {e}", flush=True)
                    else:
                        time.sleep(0.05 * (attempt + 1))

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
        log_entry = {
            "timestamp": timestamp,
            "message": message,
            "level": level,
            "stage": stage_name or self.task.current_stage,
            "episode": episode or self.task.current_episode
        }
        self.task.logs.append(log_entry)
        print(f"[{self.task.comic_title}] [{level.upper()}] {message}", flush=True)
        await self.manager.save_and_broadcast("WorkflowProgressUpdated", self.task)

    async def update_stage_progress(self, stage_name: str, progress: float):
        for s in self.task.stages:
            if s["name"] == stage_name:
                s["progress"] = progress
                if progress >= 100.0:
                    s["status"] = StageState.SUCCESS
                elif progress > 0 and s.get("status") != StageState.SUCCESS:
                    s["status"] = StageState.RUNNING
                break
        await self.manager.calculate_overall_progress(self.task)
        await self.manager.save_and_broadcast("WorkflowProgressUpdated", self.task)

    async def update_episode_stage(self, episode: int, stage_name: str, status: str = StageState.RUNNING):
        self.task.current_episode = episode
        ep_key = str(episode)
        if ep_key not in self.task.episode_progress:
            self.task.episode_progress[ep_key] = {}
        # Mark previous running stages as SUCCESS when advancing to a new stage
        if status == StageState.RUNNING:
            for s_name, s_st in list(self.task.episode_progress[ep_key].items()):
                if s_st == StageState.RUNNING and s_name != stage_name:
                    self.task.episode_progress[ep_key][s_name] = StageState.SUCCESS
        self.task.episode_progress[ep_key][stage_name] = status
        await self.manager.calculate_overall_progress(self.task)
        await self.manager.save_and_broadcast("EpisodeProgressUpdated", self.task)

    async def start_episode(self, episode: int, initial_stage: str = "Stage 2 - Async Image Crawling"):
        self.task.current_episode = episode
        ep_key = str(episode)
        if ep_key not in self.task.episode_progress:
            self.task.episode_progress[ep_key] = {}
        self.task.episode_progress[ep_key][initial_stage] = StageState.RUNNING
        await self.manager.calculate_overall_progress(self.task)
        await self.manager.save_and_broadcast("EpisodeStarted", self.task)

    async def complete_episode(self, episode: int):
        ep_key = str(episode)
        if ep_key not in self.task.episode_progress:
            self.task.episode_progress[ep_key] = {}
        for s_name in list(self.task.episode_progress[ep_key].keys()):
            if self.task.episode_progress[ep_key][s_name] == StageState.RUNNING:
                self.task.episode_progress[ep_key][s_name] = StageState.SUCCESS
        self.task.episode_progress[ep_key]["Stage 10 - Episode Video Rendering"] = StageState.SUCCESS
        self.task.completed_count = sum(
            1 for ep_num, stages in self.task.episode_progress.items()
            if any(status == StageState.SUCCESS for s_k, status in stages.items() if "10" in s_k or "Completed" in s_k)
        )
        await self.manager.calculate_overall_progress(self.task)
        await self.manager.save_and_broadcast("EpisodeCompleted", self.task)

    async def fail_episode(self, episode: int, error_msg: str, stage_name: Optional[str] = None):
        ep_key = str(episode)
        if ep_key not in self.task.episode_progress:
            self.task.episode_progress[ep_key] = {}
        target_stage = stage_name or self.task.current_stage
        self.task.episode_progress[ep_key][target_stage] = StageState.FAILED
        self.task.failed_count = sum(
            1 for ep_num, stages in self.task.episode_progress.items()
            if any(status == StageState.FAILED for status in stages.values())
        )
        await self.log(f"Tập {episode} thất bại ở {target_stage}: {error_msg}", "error", episode=episode, stage_name=target_stage)
        await self.manager.calculate_overall_progress(self.task)
        await self.manager.save_and_broadcast("EpisodeFailed", self.task)

# --- BASE STAGE INTERFACE ---
class BaseStage(abc.ABC):
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
        
    # 3. Check JSON validity and schema of recap.json
    segments_count = 0
    try:
        with open(recap_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list) or len(data) == 0:
                return False
            for item in data:
                if not isinstance(item, dict) or "speech" not in item or "images" not in item:
                    return False
            segments_count = len(data)
    except Exception:
        return False

    # 4. Check that transcript.srt cue count matches recap.json segment count 1-to-1
    try:
        with open(srt_path, "r", encoding="utf-8") as sf:
            srt_text = sf.read()
        import re
        cues_count = len(re.findall(r"\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}", srt_text))
        if cues_count != segments_count:
            return False
    except Exception:
        return False
        
    return True


def find_and_copy_completed_episode(downloads_parent: str, sanitized_title: str, language: str, dest_download_dir: str, ep: int) -> bool:
    # 1. First check if it is already completed in dest_download_dir
    dest_ep_dir = os.path.join(dest_download_dir, f"episode_{ep}")
    if check_episode_completed(dest_download_dir, ep):
        return True
        
    # 2. Iterate through all items in downloads_parent
    if not os.path.exists(downloads_parent):
        return False
        
    prefix = f"{sanitized_title}_"
    suffix = f"_{language}"
    
    for item in os.listdir(downloads_parent):
        item_path = os.path.join(downloads_parent, item)
        if not os.path.isdir(item_path):
            continue
        # Check matching pattern: starts with title_ and ends with _lang
        if item.startswith(prefix) and item.endswith(suffix):
            # Do not copy from the destination itself
            if os.path.abspath(item_path) == os.path.abspath(dest_download_dir):
                continue
            src_ep_dir = os.path.join(item_path, f"episode_{ep}")
            if os.path.exists(src_ep_dir) and check_episode_completed(item_path, ep):
                # We found a completed episode in a previous folder! Copy it!
                import shutil
                if os.path.exists(dest_ep_dir):
                    try:
                        shutil.rmtree(dest_ep_dir)
                    except Exception:
                        pass
                try:
                    shutil.copytree(src_ep_dir, dest_ep_dir)
                    return True
                except Exception:
                    pass
                    
    return False
