import asyncio
import os
import sys
import json
import time
from typing import Optional

from workflow_base import WorkflowContext, WorkflowTask
from artifact_cache import EpisodeStageCache, stage_fingerprint

class StreamingPipelineConsumer:
    """
    Background worker that consumes completed episodes from Stage 5
    and streams them through Stage 7 -> Stage 8 -> Stage 9 -> Stage 10 on the GPU.
    """
    def __init__(self, context: WorkflowContext):
        self.context = context
        self.task = context.task
        self.queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._is_running = False

    def start(self):
        if not self._is_running:
            self._is_running = True
            self._worker_task = asyncio.create_task(self._consumer_loop())

    async def enqueue_episode(self, ep: int):
        await self.queue.put(ep)

    async def _consumer_loop(self):
        while self._is_running or not self.queue.empty():
            if self.context.cancel_token.is_cancelled():
                while not self.queue.empty():
                    try:
                        self.queue.get_nowait()
                        self.queue.task_done()
                    except (asyncio.QueueEmpty, ValueError):
                        break
                break
            try:
                ep = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                if not self.context.cancel_token.is_cancelled():
                    await self.process_episode(ep)
            except Exception as e:
                await self.context.log(f"[Streaming Pipeline] Lỗi khi xử lý gối đầu tập {ep}: {e}", "warning", episode=ep)
                await self.context.fail_episode(ep, str(e))
            finally:
                self.queue.task_done()

    async def process_episode(self, ep: int):
        """Processes Stage 7 -> Stage 8 -> Stage 9 -> Stage 10 for a single episode."""
        task = self.task
        download_dir = task.artifacts.get("download_dir")
        if not download_dir:
            await self.context.fail_episode(ep, "[Streaming Pipeline] download_dir không tồn tại.")
            return

        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        recap_json_path = os.path.join(ep_dir, "recap.json")
        if not os.path.exists(recap_json_path):
            await self.context.fail_episode(ep, f"[Streaming Pipeline] recap.json của tập {ep} không tồn tại.")
            return

        cache = EpisodeStageCache(ep_dir)

        # 1. Stage 7 - Narration Aggregation
        from workflow_stages_2 import load_recap_dicts
        narration_txt_path = os.path.join(ep_dir, "narration.txt")
        narr_fingerprint = stage_fingerprint(task, "narration", ep, input_paths=[recap_json_path])
        if not cache.is_current(
            stage="narration",
            fingerprint=narr_fingerprint,
            outputs=[narration_txt_path],
            validate=lambda: os.path.isfile(narration_txt_path) and os.path.getsize(narration_txt_path) > 0,
        ):
            segments = load_recap_dicts(recap_json_path)
            speech_list = [seg.get("speech", "").strip() for seg in segments if seg.get("speech", "").strip()]
            aggregated_narration = " ".join(speech_list)
            tmp_path = narration_txt_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(aggregated_narration)
            os.replace(tmp_path, narration_txt_path)
            cache.commit(stage="narration", fingerprint=narr_fingerprint, outputs=[narration_txt_path])
            await self.context.log(f"[Streaming Ep {ep}] Tổng hợp xong narration.txt.", "info", episode=ep)

        # 2. Stage 8 - Local TTS
        audio_path = os.path.join(ep_dir, "audio.mp3")
        srt_path = os.path.join(ep_dir, "transcript.srt")
        tts_cache_path = os.path.join(ep_dir, "tts_cache.json") if os.path.exists(os.path.join(ep_dir, "tts_cache.json")) else os.path.join(ep_dir, "tts_config.json")

        market_id = task.payload.get("market_id")
        raw_voice_id = task.payload.get("voice_id")
        from markets import get_market
        market = get_market(market_id)
        voice_id = market.default_voice_id if market and (not raw_voice_id or raw_voice_id in ("ai33pro", "auto", "default")) else (raw_voice_id or "auto")
        rate = market.voice_rate if market and market.voice_rate else "+0%"
        pitch = market.voice_pitch if market and market.voice_pitch else "+0Hz"
        ref_audio_path = getattr(market, "reference_audio", None) if market else None
        if not ref_audio_path:
            ref_audio_path = task.payload.get("ref_audio_path")
        if not ref_audio_path and voice_id in ("auto", "clone", "omnivoice", "default"):
            import config
            language = task.payload.get("language", "en")
            if language in ("vi", "vietnamese"):
                ref_audio_path = getattr(config, "DEFAULT_VI_REF_AUDIO", getattr(config, "DEFAULT_REF_AUDIO_PATH", None))
            else:
                ref_audio_path = getattr(config, "DEFAULT_REF_AUDIO_PATH", None)

        tts_fingerprint = stage_fingerprint(task, "tts", ep, input_paths=[narration_txt_path, ref_audio_path])

        from workflow_stages_2 import validate_nonempty_file, validate_srt_file
        tts_valid = (
            cache.is_current(
                stage="tts",
                fingerprint=tts_fingerprint,
                outputs=[audio_path, srt_path, tts_cache_path],
                validate=lambda: (
                    validate_nonempty_file(audio_path)
                    and validate_srt_file(srt_path)
                    and validate_nonempty_file(tts_cache_path)
                )
            )
        )
        if not tts_valid:
            from tts_provider import generate_tts
            audio_tmp = audio_path + ".tmp.mp3"
            srt_tmp = srt_path + ".tmp"
            await self.context.log(f"[Streaming Ep {ep}] Đang sinh local TTS ({voice_id})...", "info", episode=ep)
            with open(narration_txt_path, "r", encoding="utf-8") as f:
                narr_text = f.read()
            success = await generate_tts(
                narr_text, audio_tmp, srt_tmp, voice_id, ref_audio_path,
                rate=rate, pitch=pitch, language=task.payload.get("language", "en")
            )
            if success:
                os.replace(audio_tmp, audio_path)
                os.replace(srt_tmp, srt_path)
                with open(tts_cache_path + ".tmp", "w", encoding="utf-8") as cf:
                    json.dump({
                        "voice_id": voice_id,
                        "narration_hash": stage_fingerprint(task, "tts", ep, input_paths=[narration_txt_path]),
                        "ref_audio_path": ref_audio_path,
                    }, cf, ensure_ascii=False, indent=4)
                os.replace(tts_cache_path + ".tmp", tts_cache_path)
                cache.commit(stage="tts", fingerprint=tts_fingerprint, outputs=[audio_path, srt_path, tts_cache_path])
                await self.context.log(f"[Streaming Ep {ep}] Sinh xong audio.mp3 & srt.", "success", episode=ep)
            else:
                await self.context.fail_episode(ep, f"[Streaming Pipeline] Lỗi khi tạo local TTS cho tập {ep}.")
                return

        # 3. Stage 9 - Subtitle Normalization
        sub_fingerprint = stage_fingerprint(task, "subtitles", ep, input_paths=[recap_json_path, audio_path])
        if not (cache.is_current(stage="subtitles", fingerprint=sub_fingerprint, outputs=[srt_path], validate=lambda: validate_srt_file(srt_path))):
            from workflow_stages_2 import Stage9_SubtitleNormalization
            stage9 = Stage9_SubtitleNormalization()
            ep_task = WorkflowTask(
                comic_title=task.comic_title,
                comic_url=task.comic_url,
                from_episode=ep,
                to_episode=ep,
                payload=task.payload,
                id=f"{task.id}_stream_sub_{ep}",
            )
            ep_task.artifacts = dict(task.artifacts)
            ep_task.status = task.status
            config = getattr(self.context, "config", {})
            manager = getattr(self.context, "manager", None)
            if manager and hasattr(manager, "cancel_tokens") and hasattr(self.context, "cancel_token"):
                manager.cancel_tokens[ep_task.id] = self.context.cancel_token
            ep_context = WorkflowContext(ep_task, config, manager)
            stage9_ok = await stage9.execute(ep_context)
            if not stage9_ok:
                await self.context.fail_episode(ep, f"[Streaming Pipeline] Chuẩn hóa phụ đề tập {ep} thất bại.")
                return

        # 4. Stage 10 - Video Rendering
        from workflow_stages_2 import Stage10_EpisodeVideoRendering, validate_mp4_file
        video_filename = task.payload.get("video_filename", "video.mp4")
        output_video_path = os.path.join(ep_dir, video_filename)
        images_blur_dir = os.path.join(ep_dir, "images_blur")
        project_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = task.payload.get("logo_path")
        if logo_path:
            logo_path = os.path.abspath(logo_path)
        if not logo_path or not os.path.exists(logo_path):
            logo_path = os.path.join(project_dir, "images", "logo.png")

        overlay_path = task.payload.get("overlay_path")
        if overlay_path:
            overlay_path = os.path.abspath(overlay_path)
        if not overlay_path or not os.path.exists(overlay_path):
            overlay_path = os.path.join(project_dir, "images", "overlay.png")

        video_fingerprint = stage_fingerprint(
            task,
            "video",
            ep,
            input_paths=[images_blur_dir, recap_json_path, srt_path, audio_path, logo_path, overlay_path],
        )

        if not (cache.is_current(stage="video", fingerprint=video_fingerprint, outputs=[output_video_path], validate=lambda: validate_mp4_file(output_video_path))):
            await self.context.log(f"[Streaming Ep {ep}] Đang render video 1080p NVENC...", "info", episode=ep)
            stage10 = Stage10_EpisodeVideoRendering()
            ep_task = WorkflowTask(
                comic_title=task.comic_title,
                comic_url=task.comic_url,
                from_episode=ep,
                to_episode=ep,
                payload=task.payload,
                id=f"{task.id}_stream_ep_{ep}",
            )
            ep_task.artifacts = dict(task.artifacts)
            ep_task.status = task.status
            config = getattr(self.context, "config", {})
            manager = getattr(self.context, "manager", None)
            if manager and hasattr(manager, "cancel_tokens") and hasattr(self.context, "cancel_token"):
                manager.cancel_tokens[ep_task.id] = self.context.cancel_token
            ep_context = WorkflowContext(ep_task, config, manager)
            stage10_ok = await stage10.execute(ep_context)
            if not stage10_ok:
                await self.context.fail_episode(ep, f"[Streaming Pipeline] Render video tập {ep} thất bại.")
                return
            if "final_videos" in ep_task.artifacts:
                task.artifacts.setdefault("final_videos", {}).update(ep_task.artifacts["final_videos"])

    async def wait_all(self):
        """Waits for all enqueued episodes to finish processing and stops consumer."""
        if self.context.cancel_token.is_cancelled():
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except (asyncio.QueueEmpty, ValueError):
                    break
        await self.queue.join()
        self._is_running = False
        if self._worker_task:
            await self._worker_task
            self._worker_task = None
