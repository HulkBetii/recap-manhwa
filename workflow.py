import asyncio
import time
import os
from typing import Dict, List, Any, Optional

# Import core workflow elements
from workflow_base import (
    WorkflowState,
    StageState,
    WorkflowTask,
    CancellationToken,
    EventBus,
    JSONWorkflowRepository,
    WorkflowContext,
    BaseStage
)

from workflow_stages_1 import (
    Stage0_ProjectInit,
    Stage1_ComicParsing,
    Stage2_AsyncImageCrawling,
    Stage2b_IntelligentRepagination,
    Stage3_NSFWModeration,
    Stage4_PDFGeneration,
    Stage5_GeminiAutomation,
    Stage6_JSONExtraction,
    execute_episode_full_pipeline,
    execute_multi_episode_pipelined_workflow
)

from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
    Stage10_EpisodeVideoRendering,
    Stage11_FinalVideoAssembly,
    Stage12_MetadataReports,
    Stage13_Cleanup
)

# --- WORKFLOW MANAGER ---
class WorkflowManager:
    def __init__(self, repository: JSONWorkflowRepository, event_bus: EventBus, max_workers: int = 1):
        self.repository = repository
        self.event_bus = event_bus
        self.max_workers = max_workers
        self.queue = asyncio.Queue()
        self.cancel_tokens = {}
        self.running_tasks = {}
        self.workers = []
        self._started = False

    def start(self):
        if self._started: return
        self._started = True
        for i in range(self.max_workers):
            self.workers.append(asyncio.create_task(self._worker_loop(i)))

    async def stop(self):
        for w in self.workers:
            w.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self._started = False
        self.workers = []

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
                task.completed_count = 0
                task.failed_count = 0
                
                # Reset only the non-success stages
                for stage in task.stages:
                    if stage["status"] != StageState.SUCCESS:
                        stage["status"] = StageState.WAITING
                        stage["progress"] = 0.0
                
                # Reset only non-success stages in episode_progress
                if hasattr(task, "episode_progress") and isinstance(task.episode_progress, dict):
                    for ep_key, ep_stages in task.episode_progress.items():
                        if isinstance(ep_stages, dict):
                            for s_name, s_state in ep_stages.items():
                                if s_state != StageState.SUCCESS:
                                    ep_stages[s_name] = StageState.WAITING

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
            
            # Reset only the non-success stages
            for stage in task.stages:
                if stage["status"] != StageState.SUCCESS:
                    stage["status"] = StageState.WAITING
                    stage["progress"] = 0.0
            
            # Reset only non-success stages in episode_progress
            if hasattr(task, "episode_progress") and isinstance(task.episode_progress, dict):
                for ep_key, ep_stages in task.episode_progress.items():
                    if isinstance(ep_stages, dict):
                        for s_name, s_state in ep_stages.items():
                            if s_state != StageState.SUCCESS:
                                ep_stages[s_name] = StageState.WAITING

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
            if task_id in self.running_tasks:
                self.running_tasks[task_id].cancel()
            
            task.status = WorkflowState.CANCELLED
            task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for stage in task.stages:
                if stage["status"] in [StageState.RUNNING, StageState.WAITING]:
                    stage["status"] = StageState.CANCELLED
            
            task.logs.append({
                "timestamp": time.strftime("%H:%M:%S"),
                "message": "Nhiệm vụ đã bị hủy bởi người dùng.",
                "level": "warning",
                "stage": task.current_stage,
                "episode": task.current_episode
            })
            await self.save_and_broadcast("WorkflowCancelled", task)
            return True
        return False

    async def remove_task(self, task_id: str) -> bool:
        task = self.repository.load(task_id)
        if not task: return False
        
        if task.status in [WorkflowState.RUNNING, WorkflowState.WAITING]:
            await self.cancel_task(task_id)
        
        self.repository.delete(task_id)
        if task_id in self.cancel_tokens: del self.cancel_tokens[task_id]
        if task_id in self.running_tasks: del self.running_tasks[task_id]
        
        await self.event_bus.publish("WorkflowRemoved", task_id, {"task_id": task_id})
        return True

    async def save_and_broadcast(self, event_name: str, task: WorkflowTask):
        self.repository.update(task)
        await self.event_bus.publish(event_name, task.id, task.to_dict(include_logs=False))

    async def calculate_overall_progress(self, task: WorkflowTask):
        test_pipeline_targets = task.payload.get("test_stage_pipeline")
        if test_pipeline_targets and isinstance(test_pipeline_targets, list):
            relevant_stages = [
                s for s in task.stages
                if s["name"] in test_pipeline_targets or any(t.lower() in s["name"].lower() for t in test_pipeline_targets)
            ]
        else:
            relevant_stages = [s for s in task.stages if s["name"] != "Completed"]

        # If task has per-episode progress, update streaming stages (Stage 2..10)
        total_episodes = max(1, task.to_episode - task.from_episode + 1)
        ep_prog = task.episode_progress or {}
        if ep_prog:
            for s in relevant_stages:
                s_name = s.get("name", "")
                # Check if this stage belongs to the streaming episode pipeline (Stages 2..10)
                if any(f"Stage {i}" in s_name for i in ["2", "2b", "3", "4", "5", "6", "7", "8", "9", "10"]):
                    comp = 0
                    run = 0
                    for ep_k, st_dict in ep_prog.items():
                        if not isinstance(st_dict, dict):
                            continue
                        # Look for matching stage name in episode progress
                        matched_state = None
                        for ep_st_name, st_state in st_dict.items():
                            if ep_st_name == s_name or (s_name.split(" - ")[0] in ep_st_name):
                                matched_state = st_state
                                break
                        if matched_state == StageState.SUCCESS:
                            comp += 1
                        elif matched_state == StageState.RUNNING:
                            run += 1
                    if comp + run > 0:
                        s_prog = min(100.0, round(((comp + run * 0.5) / total_episodes) * 100.0, 1))
                        s["progress"] = s_prog
                        if s_prog >= 100.0:
                            s["status"] = StageState.SUCCESS
                        elif s_prog > 0 and s.get("status") != StageState.SUCCESS:
                            s["status"] = StageState.RUNNING

        total_weight = sum(float(s.get("weight", 0.0)) for s in relevant_stages) or 1.0
        overall = 0.0
        for s in relevant_stages:
            weight = float(s.get("weight", 0.0))
            status = s.get("status")
            progress = float(s.get("progress", 0.0))
            if status == StageState.SUCCESS:
                overall += weight
            elif status == StageState.RUNNING:
                overall += (progress / 100.0) * weight
        task.overall_progress = min(100.0, max(0.0, round((overall / total_weight) * 100.0, 1)))

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

                executor_coro = self._execute_workflow(task)
                run_task = asyncio.create_task(executor_coro)
                self.running_tasks[task_id] = run_task
                
                try:
                    await run_task
                except asyncio.CancelledError:
                    pass
                finally:
                    if task_id in self.running_tasks:
                        del self.running_tasks[task_id]
                    self.queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _run_stage_with_retries(self, stage: BaseStage, context: WorkflowContext, task: WorkflowTask) -> bool:
        stage_record = next((s for s in task.stages if s["name"] == stage.name), None)
        if stage_record and stage_record.get("status") == StageState.SUCCESS:
            await context.log(f"Giai đoạn '{stage.name}' đã hoàn thành trước đó. Bỏ qua.", "success")
            return True

        task.current_stage = stage.name
        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        await self.save_and_broadcast("StageStarted", task)
        await context.log(f"Giai đoạn '{stage.name}' bắt đầu.", "info")

        stage_success = False
        max_retries = task.payload.get("retry_count", 5)

        for attempt in range(1, max_retries + 1):
            if context.cancel_token.is_cancelled():
                raise asyncio.CancelledError()
            try:
                stage_success = await stage.execute(context)
                if stage_success:
                    break
            except Exception as e:
                await context.log(f"Lỗi giai đoạn '{stage.name}' (thử lại {attempt}/{max_retries}): {e}", "error")
                if attempt == max_retries:
                    raise e
            if attempt < max_retries:
                await asyncio.sleep(5)

        if not stage_success:
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.FAILED
            return False

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.SUCCESS
                s["progress"] = 100.0
        await context.log(f"Giai đoạn '{stage.name}' hoàn thành.", "success")
        await self.save_and_broadcast("StageCompleted", task)
        return True

    async def _execute_workflow(self, task: WorkflowTask):
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

        start_time_seconds = time.time()
        success = True
        error_msg = None
        
        async def timer_loop():
            try:
                while task.status == WorkflowState.RUNNING:
                    await asyncio.sleep(1)
                    task.elapsed_time = round(time.time() - start_time_seconds, 1)
                    
                    if task.overall_progress > 2.0 and task.elapsed_time > 5.0:
                        total_estimated = task.elapsed_time / (task.overall_progress / 100.0)
                        remaining = max(0.0, total_estimated - task.elapsed_time)
                        task.estimated_remaining_time = round(remaining, 1)
                    else:
                        task.estimated_remaining_time = None
                    await self.save_and_broadcast("WorkflowProgressUpdated", task)
            except asyncio.CancelledError:
                pass
                
        timer_task = asyncio.create_task(timer_loop())
        
        try:
            # Targeted single/subset stage execution for Dev & Test Studio
            test_pipeline_targets = task.payload.get("test_stage_pipeline")
            if test_pipeline_targets and isinstance(test_pipeline_targets, list):
                filtered_pipeline = []
                for s in stages_pipeline:
                    if s.name in test_pipeline_targets or any(t.lower() in s.name.lower() for t in test_pipeline_targets):
                        filtered_pipeline.append(s)
                if filtered_pipeline:
                    stages_pipeline = filtered_pipeline
                    await context.log(f"[TEST_STAGE] Chạy quy trình test độc lập cho: {[s.name for s in stages_pipeline]}", "info")
                
                for stage in stages_pipeline:
                    if context.cancel_token.is_cancelled():
                        raise asyncio.CancelledError()
                    stage_ok = await self._run_stage_with_retries(stage, context, task)
                    if not stage_ok:
                        success = False
                        error_msg = f"Giai đoạn '{stage.name}' gặp lỗi không thể hoàn tất."
                        break
                    stop_after_stage = task.payload.get("stop_after_stage")
                    if stop_after_stage and stage.name == stop_after_stage:
                        await context.log(f"[TEST_STAGE] Đã đạt stage đích '{stage.name}'. Dừng workflow theo chế độ Test Stage.", "info")
                        break
            else:
                # Full end-to-end streaming multi-episode workflow
                # 1. Stage 0 - Project Init
                ok0 = await self._run_stage_with_retries(Stage0_ProjectInit(), context, task)
                if not ok0:
                    success = False
                    error_msg = "Stage 0 - Project Init thất bại."
                
                # 2. Stage 1 - Comic Parsing
                if success:
                    ok1 = await self._run_stage_with_retries(Stage1_ComicParsing(), context, task)
                    if not ok1:
                        success = False
                        error_msg = "Stage 1 - Comic Parsing thất bại."

                # 3. Stages 2 -> 10: Multi-episode streaming pipeline (2 Phase + Barrier + Auto Retry)
                if success:
                    task.current_stage = "Stage 2 -> 10 (Streaming Pipeline)"
                    await self.save_and_broadcast("StageStarted", task)
                    pw_ctx = None
                    try:
                        from app import get_shared_browser_context, load_config
                        cfg = load_config()
                        headless_val = task.payload.get("headless", cfg.get("headless", False))
                        _, pw_ctx = await get_shared_browser_context(headless=headless_val)
                    except Exception:
                        pw_ctx = None

                    try:
                        ok_pipeline = await execute_multi_episode_pipelined_workflow(
                            context=context,
                            browser_context=pw_ctx,
                            profile_pool=None,
                            max_phase_retries=task.payload.get("retry_count", 3)
                        )
                    except Exception as pipe_err:
                        ok_pipeline = False
                        await context.log(f"Lỗi pipeline: {pipe_err}", "error")

                    if not ok_pipeline:
                        success = False
                        error_msg = "Một hoặc nhiều tập truyện thất bại trong quy trình xử lý pipeline."
                    else:
                        streaming_stage_names = [
                            "Stage 2 - Async Image Crawling",
                            "Stage 2 - Image Crawling",
                            "Stage 2b - Intelligent Re-pagination",
                            "Stage 3 - NSFW Moderation",
                            "Stage 4 - PDF Generation",
                            "Stage 5 - Gemini Automation",
                            "Stage 6 - JSON Extraction",
                            "Stage 7 - Narration Aggregation",
                            "Stage 8 - Local TTS",
                            "Stage 9 - Subtitle Normalization",
                            "Stage 10 - Episode Video Rendering"
                        ]
                        for s in task.stages:
                            if any(sn in s["name"] or s["name"] in sn for sn in streaming_stage_names):
                                s["status"] = StageState.SUCCESS
                                s["progress"] = 100.0

                # 4. Stage 11 - Final Video Assembly
                if success:
                    ok11 = await self._run_stage_with_retries(Stage11_FinalVideoAssembly(), context, task)
                    if not ok11:
                        success = False
                        error_msg = "Stage 11 - Final Video Assembly thất bại."

                # 5. Stage 12 - Metadata Reports
                if success:
                    ok12 = await self._run_stage_with_retries(Stage12_MetadataReports(), context, task)
                    if not ok12:
                        success = False
                        error_msg = "Stage 12 - Metadata Reports thất bại."

                # 6. Stage 13 - Cleanup
                if success:
                    ok13 = await self._run_stage_with_retries(Stage13_Cleanup(), context, task)
                    if not ok13:
                        success = False
                        error_msg = "Stage 13 - Cleanup thất bại."

            if success:
                # Clear all Gemini My Activity logs on all configured profiles concurrently without retries (skip for fast test stage)
                if not task.payload.get("is_test_stage", False):
                    try:
                        from playwright.async_api import async_playwright
                        from app import get_browser_context, clear_gemini_activity, load_config, reset_shared_browser_context
                        
                        await reset_shared_browser_context()
                        config = load_config()
                        profiles = config.get("chrome_profiles", [])
                        headless_val = task.payload.get("headless", config.get("headless", False))
                        
                        if profiles:
                            await context.log(f"Đang tiến hành dọn dẹp lịch sử hoạt động Gemini song song trên {len(profiles)} tài khoản (không retry)...", "info")
                            
                            clear_sem = asyncio.Semaphore(min(4, len(profiles)))
                            async with async_playwright() as p:
                                async def clear_account_task(profile_path, idx):
                                    async with clear_sem:
                                        p_name = os.path.basename(profile_path) or f"Profile_{idx+1}"
                                        await context.log(f"Tài khoản {idx+1}/{len(profiles)} ({p_name}): Bắt đầu dọn dẹp hoạt động...", "info")
                                        br = None
                                        ctx = None
                                        try:
                                            br, ctx = await get_browser_context(p, headless=headless_val, start_maximized=False, custom_profile_path=profile_path)
                                            page = await ctx.new_page()
                                            try:
                                                await clear_gemini_activity(page, context)
                                            finally:
                                                try:
                                                    await page.close()
                                                except Exception:
                                                    pass
                                        except Exception as p_err:
                                            await context.log(f"Tài khoản {idx+1}/{len(profiles)} ({p_name}): Không thể dọn dẹp lịch sử ({p_err}). Bỏ qua mà không retry.", "warning")
                                        finally:
                                            if ctx:
                                                try:
                                                    await ctx.close()
                                                except Exception:
                                                    pass
                                            if br:
                                                try:
                                                    await br.close()
                                                except Exception:
                                                    pass

                                await asyncio.gather(*[clear_account_task(prof, i) for i, prof in enumerate(profiles)], return_exceptions=True)

                            # Reset shared browser context cleanly
                            await reset_shared_browser_context()
                            await context.log("Đã hoàn tất dọn dẹp lịch sử hoạt động cho tất cả các tài khoản.", "success")
                    except Exception as clear_err:
                        await context.log(f"Cảnh báo: Lỗi trong quá trình dọn dẹp lịch sử hoạt động Gemini: {clear_err}", "warning")

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
                task.status = WorkflowState.FAILED
                task.error_message = error_msg
                task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await context.log(f"Quy trình thất bại: {error_msg}", "error")
                await self.save_and_broadcast("WorkflowFailed", task)

        except asyncio.CancelledError:
            task.status = WorkflowState.CANCELLED
            for s in task.stages:
                if s["status"] in [StageState.RUNNING, StageState.WAITING]:
                    s["status"] = StageState.CANCELLED
            task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await context.log("Tiến trình đã bị hủy.", "warning")
            await self.save_and_broadcast("WorkflowCancelled", task)
            
        except Exception as e:
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
