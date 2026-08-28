import asyncio
import json
import time
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

# Import core workflow elements
from workflow_base import (
    BaseWorkflowRepository,
    WorkflowState,
    StageState,
    WorkflowTask,
    CancellationToken,
    EventBus,
    JSONWorkflowRepository,
    WorkflowContext,
    BaseStage
)

from process_control import ProcessIdentity, identity_for_process, popen_command, process_matches, terminate_process_tree
from worker_protocol import atomic_write_json

# --- WORKFLOW MANAGER ---
class WorkflowManager:
    def __init__(
        self,
        repository: BaseWorkflowRepository,
        event_bus: EventBus,
        max_workers: int = 1,
        *,
        run_in_subprocess: bool = True,
        runtime_root: str | Path = "runtime/jobs",
        cancel_grace_seconds: float = 15.0,
    ):
        self.repository = repository
        self.event_bus = event_bus
        self.max_workers = max_workers
        self.run_in_subprocess = run_in_subprocess
        self.runtime_root = Path(runtime_root).resolve()
        self.cancel_grace_seconds = max(0.0, cancel_grace_seconds)
        self.queue = asyncio.Queue()
        self.cancel_tokens = {}
        self.running_tasks = {}
        self.cancellation_tasks = {}
        self.workers = []
        self._started = False

    def start(self):
        if self._started: return
        self._started = True
        if self.run_in_subprocess:
            self.runtime_root.mkdir(parents=True, exist_ok=True)
            for task in self.repository.load_all():
                if task.status == WorkflowState.WAITING:
                    self.queue.put_nowait(task.id)
                elif task.status == WorkflowState.RUNNING:
                    identity = self._task_identity(task)
                    if identity is not None and process_matches(identity):
                        self.running_tasks[task.id] = asyncio.create_task(self._monitor_reattached_worker(task, identity))
                        if task.runtime.get("cancel_requested"):
                            self.cancellation_tasks[task.id] = asyncio.create_task(
                                self._force_cancel_after_grace(task.id)
                            )
                    else:
                        self._mark_process_lost(task)
        for i in range(self.max_workers):
            self.workers.append(asyncio.create_task(self._worker_loop(i)))

    async def stop(self):
        for w in self.workers:
            w.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        monitors = list(self.running_tasks.values())
        for monitor in monitors:
            monitor.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)
        cancellation_tasks = list(self.cancellation_tasks.values())
        for cancellation_task in cancellation_tasks:
            cancellation_task.cancel()
        await asyncio.gather(*cancellation_tasks, return_exceptions=True)
        self._started = False
        self.workers = []
        self.running_tasks = {}
        self.cancellation_tasks = {}

    async def queue_task(self, comic_title: str, comic_url: str, from_episode: int, to_episode: int, config: Dict[str, Any]) -> str:
        payload = {
            "status": WorkflowState.WAITING,
            "current_stage": "Stage 0 - Project Init",
            "logs": [{"timestamp": time.strftime("%H:%M:%S"), "message": "Nhiệm vụ được tạo và đưa vào hàng chờ.", "level": "info", "stage": "Stage 0 - Project Init", "episode": None}]
        }
        task = WorkflowTask(comic_title, comic_url, from_episode, to_episode, payload)
        task.payload.update(config)
        self.repository.save(task)
        self.cancel_tokens[task.id] = CancellationToken()
        await self.queue.put(task.id)
        await self.save_and_broadcast("WorkflowCreated", task)
        return task.id

    def _job_dir(self, task_id: str) -> Path:
        return self.runtime_root / task_id

    def _worker_command(self, task_id: str) -> list[str]:
        return [sys.executable, "-m", "workflow_worker", "--job-dir", str(self._job_dir(task_id))]

    def _task_identity(self, task: WorkflowTask) -> ProcessIdentity | None:
        try:
            return ProcessIdentity.from_dict(task.runtime)
        except (KeyError, TypeError, ValueError):
            return None

    def _mark_process_lost(self, task: WorkflowTask) -> None:
        cancel_requested = bool(task.runtime.get("cancel_requested"))
        task.status = WorkflowState.CANCELLED if cancel_requested else WorkflowState.FAILED
        task.error_message = (
            None
            if cancel_requested
            else "Worker process was lost after server restart. Retry will validate cached artifacts."
        )
        task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        task.runtime = {}
        for stage in task.stages:
            if stage["status"] == StageState.RUNNING:
                stage["status"] = StageState.CANCELLED if cancel_requested else StageState.FAILED
        self.repository.update(task)

    def _read_worker_snapshot(self, task: WorkflowTask) -> tuple[int, dict[str, Any]] | None:
        status_path = self._job_dir(task.id) / "status.json"
        if not status_path.is_file():
            return None
        try:
            value = json.loads(status_path.read_text(encoding="utf-8"))
            return int(value["revision"]), value["task"]
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    async def _apply_worker_snapshot(self, task: WorkflowTask) -> bool:
        snapshot = self._read_worker_snapshot(task)
        if snapshot is None:
            return False
        revision, value = snapshot
        if revision <= int(task.runtime.get("revision", 0)):
            return False
        worker_task = WorkflowTask(
            comic_title=value.get("comic_title", task.comic_title),
            comic_url=value.get("comic_url", task.comic_url),
            from_episode=int(value.get("from_episode", task.from_episode)),
            to_episode=int(value.get("to_episode", task.to_episode)),
            payload=value,
            id=task.id,
        )
        runtime = task.runtime
        task.__dict__.update(worker_task.__dict__)
        task.runtime = runtime
        task.runtime["revision"] = revision
        await self.save_and_broadcast("WorkflowProgressUpdated", task)
        return True

    async def _monitor_reattached_worker(self, task: WorkflowTask, identity: ProcessIdentity) -> None:
        try:
            while process_matches(identity):
                await self._apply_worker_snapshot(task)
                await asyncio.sleep(0.5)
            await self._apply_worker_snapshot(task)
            if task.status not in {WorkflowState.SUCCESS, WorkflowState.FAILED, WorkflowState.CANCELLED}:
                self._mark_process_lost(task)
        except asyncio.CancelledError:
            raise
        finally:
            self.running_tasks.pop(task.id, None)
            self.cancellation_tasks.pop(task.id, None)

    async def _execute_workflow_subprocess(self, task: WorkflowTask) -> None:
        job_dir = self._job_dir(task.id)
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        task.runtime = {}
        atomic_write_json(job_dir / "input.json", task.to_storage_dict())
        command = self._worker_command(task.id)
        env = os.environ.copy()
        env["RECAP_WORKER_PROCESS"] = "1"
        env["RECAP_TASK_DB"] = str(job_dir / "worker_app_state.json")
        process = await asyncio.to_thread(popen_command, command, cwd=Path(__file__).resolve().parent, env=env)
        identity = identity_for_process(process, command)
        task.runtime = {**identity.to_dict(), "revision": 0, "cancel_requested": False}
        task.status = WorkflowState.RUNNING
        task.started_time = task.started_time or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self.save_and_broadcast("WorkflowStarted", task)
        try:
            while process.poll() is None:
                await self._apply_worker_snapshot(task)
                await asyncio.sleep(0.5)
            await self._apply_worker_snapshot(task)
            if task.status not in {WorkflowState.SUCCESS, WorkflowState.FAILED, WorkflowState.CANCELLED}:
                cancel_requested = bool(task.runtime.get("cancel_requested"))
                task.status = WorkflowState.CANCELLED if cancel_requested else WorkflowState.FAILED
                task.error_message = (
                    None
                    if cancel_requested
                    else f"Worker exited with code {process.returncode} before writing a final status."
                )
                task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await self.save_and_broadcast(
                    "WorkflowCancelled" if cancel_requested else "WorkflowFailed",
                    task,
                )
            revision = int(task.runtime.get("revision", 0))
            task.runtime = {"revision": revision, "exit_code": process.returncode}
            self.repository.update(task)
        except asyncio.CancelledError:
            raise

    async def retry_all_failed_or_cancelled(self) -> int:
        tasks = self.repository.load_all()
        retried_count = 0
        for task in tasks:
            if task.status in [WorkflowState.FAILED, WorkflowState.CANCELLED]:
                # Reset task state
                task.status = WorkflowState.WAITING
                task.error_message = None
                task.finished_time = None
                task.elapsed_time = 0.0
                task.current_stage = "Stage 0 - Project Init"
                task.overall_progress = 0.0
                task.episode_progress = {}
                task.completed_count = 0
                task.failed_count = 0
                task.runtime = {}
                
                # Reset all stages to WAITING to run from the beginning
                for stage in task.stages:
                    stage["status"] = StageState.WAITING
                    stage["progress"] = 0.0
                
                # Re-queue the task
                self.cancel_tokens[task.id] = CancellationToken()
                await self.queue.put(task.id)
                await self.save_and_broadcast("WorkflowUpdated", task)
                retried_count += 1
        return retried_count

    async def retry_task(self, task_id: str) -> bool:
        task = self.repository.load(task_id)
        if not task:
            return False
        if task.status in [WorkflowState.FAILED, WorkflowState.CANCELLED]:
            # Reset task state
            task.status = WorkflowState.WAITING
            task.error_message = None
            task.finished_time = None
            task.elapsed_time = 0.0
            task.completed_count = 0
            task.failed_count = 0
            task.runtime = {}
            
            # Reset only the non-success stages
            for stage in task.stages:
                if stage["status"] != StageState.SUCCESS:
                    stage["status"] = StageState.WAITING
                    stage["progress"] = 0.0
            
            # Re-queue the task
            self.cancel_tokens[task.id] = CancellationToken()
            await self.queue.put(task.id)
            await self.save_and_broadcast("WorkflowUpdated", task)
            return True
        return False

    def get_cancel_token(self, task_id: str) -> CancellationToken:
        if task_id not in self.cancel_tokens:
            self.cancel_tokens[task_id] = CancellationToken()
        return self.cancel_tokens[task_id]

    async def cancel_task(self, task_id: str) -> bool:
        task = self.repository.load(task_id)
        if not task: return False
        
        if task.status in [WorkflowState.RUNNING, WorkflowState.WAITING]:
            self.get_cancel_token(task_id).cancel()
            if task.status == WorkflowState.WAITING:
                task.status = WorkflowState.CANCELLED
                task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                for stage in task.stages:
                    if stage["status"] in [StageState.RUNNING, StageState.WAITING]:
                        stage["status"] = StageState.CANCELLED
            elif self.run_in_subprocess:
                cancel_path = self._job_dir(task_id) / "cancel.flag"
                cancel_path.parent.mkdir(parents=True, exist_ok=True)
                cancel_path.touch(exist_ok=True)
                task.runtime["cancel_requested"] = True
                if task_id not in self.cancellation_tasks:
                    cancellation_task = asyncio.create_task(self._force_cancel_after_grace(task_id))
                    self.cancellation_tasks[task_id] = cancellation_task
            else:
                running_task = self.running_tasks.get(task_id)
                if running_task is not None:
                    running_task.cancel()

            task.logs.append({
                "timestamp": time.strftime("%H:%M:%S"),
                "message": "Đã gửi yêu cầu hủy nhiệm vụ; worker có tối đa 15 giây để dừng an toàn.",
                "level": "warning",
                "stage": task.current_stage,
                "episode": task.current_episode
            })
            await self.save_and_broadcast(
                "WorkflowCancelled" if task.status == WorkflowState.CANCELLED else "WorkflowCancellationRequested",
                task,
            )
            return True
        return False

    async def _force_cancel_after_grace(self, task_id: str) -> None:
        try:
            await asyncio.sleep(self.cancel_grace_seconds)
            task = self.repository.load(task_id)
            if task is None or task.status != WorkflowState.RUNNING:
                return
            identity = self._task_identity(task)
            if identity is not None and process_matches(identity):
                await asyncio.to_thread(terminate_process_tree, identity, grace_seconds=0)
        finally:
            self.cancellation_tasks.pop(task_id, None)

    async def _wait_for_task_exit(self, task_id: str) -> None:
        monitor = self.running_tasks.get(task_id)
        if monitor is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(monitor),
                timeout=self.cancel_grace_seconds + 7,
            )
        except asyncio.TimeoutError:
            task = self.repository.load(task_id)
            identity = self._task_identity(task) if task is not None else None
            if identity is not None:
                await asyncio.to_thread(terminate_process_tree, identity, grace_seconds=0)
            try:
                await asyncio.wait_for(asyncio.shield(monitor), timeout=5)
            except asyncio.TimeoutError:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)

    async def remove_task(self, task_id: str) -> bool:
        task = self.repository.load(task_id)
        if not task: return False
        
        if task.status in [WorkflowState.RUNNING, WorkflowState.WAITING]:
            await self.cancel_task(task_id)
            await self._wait_for_task_exit(task_id)
        
        self.repository.delete(task_id)
        if task_id in self.cancel_tokens: del self.cancel_tokens[task_id]
        cancellation_task = self.cancellation_tasks.pop(task_id, None)
        if cancellation_task is not None:
            cancellation_task.cancel()
            await asyncio.gather(cancellation_task, return_exceptions=True)
        job_dir = self._job_dir(task_id)
        if job_dir.exists():
            await asyncio.to_thread(shutil.rmtree, job_dir)
        
        await self.event_bus.publish("WorkflowRemoved", task_id, {"task_id": task_id})
        return True

    async def save_and_broadcast(self, event_name: str, task: WorkflowTask):
        self.repository.update(task)
        await self.event_bus.publish(event_name, task.id, task.to_public_dict(include_logs=False))

    async def calculate_overall_progress(self, task: WorkflowTask):
        overall = 0.0
        current_reached = False
        for s in task.stages:
            if s["name"] == "Completed": continue
            if s["name"] == task.current_stage:
                overall += (s["progress"] / 100.0) * s["weight"]
                current_reached = True
            elif not current_reached:
                overall += s["weight"]
        task.overall_progress = min(100.0, round(overall * 100.0, 1))

    async def _worker_loop(self, worker_id: int):
        try:
            while True:
                task_id = await self.queue.get()
                task = self.repository.load(task_id)
                if not task or task.status == WorkflowState.CANCELLED:
                    self.queue.task_done()
                    continue
                
                if self.get_cancel_token(task_id).is_cancelled():
                    self.queue.task_done()
                    continue

                executor_coro = (
                    self._execute_workflow_subprocess(task)
                    if self.run_in_subprocess
                    else self._execute_workflow(task)
                )
                run_task = asyncio.create_task(executor_coro)
                self.running_tasks[task_id] = run_task
                
                try:
                    await asyncio.shield(run_task)
                except asyncio.CancelledError:
                    current_worker = asyncio.current_task()
                    if current_worker is not None and current_worker.cancelling():
                        raise
                except Exception as exc:
                    task = self.repository.load(task_id)
                    if task is not None and task.status not in {
                        WorkflowState.SUCCESS,
                        WorkflowState.FAILED,
                        WorkflowState.CANCELLED,
                    }:
                        task.status = WorkflowState.FAILED
                        task.error_message = f"Workflow supervisor error: {exc}"
                        task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        await self.save_and_broadcast("WorkflowFailed", task)
                finally:
                    if run_task.done() and self.running_tasks.get(task_id) is run_task:
                        del self.running_tasks[task_id]
                    self.queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _execute_workflow(self, task: WorkflowTask):
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
        )

        task.status = WorkflowState.RUNNING
        task.started_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self.save_and_broadcast("WorkflowStarted", task)
        
        context = WorkflowContext(task, task.payload, self)
        stages_pipeline = [
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
            Stage13_Cleanup()
        ]
        
        start_time_seconds = time.monotonic()
        success = True
        error_msg = None
        
        async def timer_loop():
            try:
                while task.status == WorkflowState.RUNNING:
                    await asyncio.sleep(1)
                    task.elapsed_time = round(time.monotonic() - start_time_seconds, 1)
                    
                    total_eps = task.to_episode - task.from_episode + 1
                    completed_eps = sum(1 for ep_num, stages in task.episode_progress.items() if all(status == StageState.SUCCESS for status in stages.values()))
                    
                    if completed_eps > 0:
                        avg_time_per_ep = task.elapsed_time / completed_eps
                        remaining_eps = total_eps - completed_eps
                        task.estimated_remaining_time = round(avg_time_per_ep * remaining_eps, 1)
                    else:
                        task.estimated_remaining_time = None
                    await self.save_and_broadcast("WorkflowProgressUpdated", task)
            except asyncio.CancelledError:
                pass
                
        timer_task = asyncio.create_task(timer_loop())
        
        try:
            for stage in stages_pipeline:
                if context.cancel_token.is_cancelled():
                    raise asyncio.CancelledError()

                stage_record = next((item for item in task.stages if item["name"] == stage.name), None)
                if (
                    stage.name != "Stage 0 - Project Init"
                    and stage_record is not None
                    and stage_record["status"] == StageState.SUCCESS
                ):
                    await context.log(
                        f"Giai đoạn '{stage.name}' đã hoàn thành ở lần chạy trước. Tiếp tục từ checkpoint kế tiếp.",
                        "success",
                    )
                    continue
                
                task.current_stage = stage.name
                for s in task.stages:
                    if s["name"] == stage.name:
                        s["status"] = StageState.RUNNING
                        s["progress"] = 0.0
                await self.save_and_broadcast("StageStarted", task)
                await context.log(f"Giai đoạn '{stage.name}' bắt đầu.", "info")
                
                stage_success = False
                max_retries = 1 if stage.handles_retries else task.payload.get("retry_count", 5)
                
                for attempt in range(1, max_retries + 1):
                    if context.cancel_token.is_cancelled():
                        raise asyncio.CancelledError()
                    try:
                        stage_success = await stage.execute(context)
                        if stage_success: break
                    except Exception as e:
                        await context.log(f"Lỗi giai đoạn '{stage.name}' (thử lại {attempt}/{max_retries}): {e}", "error")
                        if attempt == max_retries: raise e
                    if attempt < max_retries:
                        await asyncio.sleep(5)
                
                if not stage_success:
                    success = False
                    error_msg = f"Giai đoạn '{stage.name}' gặp lỗi không thể hoàn tất."
                    for s in task.stages:
                        if s["name"] == stage.name:
                            s["status"] = StageState.FAILED
                    break
                else:
                    for s in task.stages:
                        if s["name"] == stage.name:
                            s["status"] = StageState.SUCCESS
                            s["progress"] = 100.0
                    await context.log(f"Giai đoạn '{stage.name}' hoàn thành.", "success")
                    await self.save_and_broadcast("StageCompleted", task)

            if success:
                task.elapsed_time = round(time.monotonic() - start_time_seconds, 1)
                task.status = WorkflowState.SUCCESS
                for s in task.stages:
                    if s["name"] == "Completed":
                        s["status"] = StageState.SUCCESS
                        s["progress"] = 100.0
                task.overall_progress = 100.0
                task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await context.log("Quy trình workflow hoàn thành thành công!", "success")
                await self.save_and_broadcast("WorkflowCompleted", task)
            else:
                task.elapsed_time = round(time.monotonic() - start_time_seconds, 1)
                task.status = WorkflowState.FAILED
                task.error_message = error_msg
                task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await context.log(f"Quy trình thất bại: {error_msg}", "error")
                await self.save_and_broadcast("WorkflowFailed", task)

        except asyncio.CancelledError:
            task.elapsed_time = round(time.monotonic() - start_time_seconds, 1)
            task.status = WorkflowState.CANCELLED
            for s in task.stages:
                if s["status"] in [StageState.RUNNING, StageState.WAITING]:
                    s["status"] = StageState.CANCELLED
            task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await context.log("Tiến trình đã bị hủy.", "warning")
            await self.save_and_broadcast("WorkflowCancelled", task)
            
        except Exception as e:
            task.elapsed_time = round(time.monotonic() - start_time_seconds, 1)
            task.status = WorkflowState.FAILED
            task.error_message = str(e)
            for s in task.stages:
                if s["status"] in [StageState.RUNNING, StageState.WAITING]:
                    s["status"] = StageState.FAILED
            task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await context.log(f"Quy trình lỗi nghiêm trọng: {e}", "error")
            await self.save_and_broadcast("WorkflowFailed", task)
        finally:
            timer_task.cancel()
            if task.status == WorkflowState.SUCCESS and self.queue.empty():
                try:
                    from app import reset_shared_browser_context
                    await reset_shared_browser_context()
                except Exception as reset_err:
                    print(f"Error resetting shared browser context: {reset_err}", flush=True)
            else:
                if task.status in [WorkflowState.FAILED, WorkflowState.CANCELLED]:
                    print(f"[WorkflowManager] Tác vụ kết thúc với trạng thái {task.status}. Giữ trình duyệt mở để kiểm tra/gỡ lỗi.", flush=True)
                else:
                    print("[WorkflowManager] Hàng đợi vẫn còn tác vụ chờ, giữ trình duyệt mở cho tác vụ tiếp theo.", flush=True)
