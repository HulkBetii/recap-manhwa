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
            finally:
                self.queue.task_done()

    async def process_episode(self, ep: int):
        """Processes Stage 7 -> Stage 8 -> Stage 9 -> Stage 10 for a single episode."""
        task = self.task
        download_dir = task.artifacts.get("download_dir")
        if not download_dir:
            return

        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        recap_json_path = os.path.join(ep_dir, "recap.json")
        if not os.path.exists(recap_json_path):
            return

        cache = EpisodeStageCache(ep_dir)

        # 1. Stage 7 - Narration Aggregation
        from workflow_stages_2 import load_recap_dicts
        narration_txt_path = os.path.join(ep_dir, "narration.txt")
        narr_fingerprint = stage_fingerprint(task, "narration", ep, input_paths=[recap_json_path])
        if not (cache.is_current(stage="narration", fingerprint=narr_fingerprint, outputs=[narration_txt_path]) and os.path.isfile(narration_txt_path)):
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
            await stage9.execute(ep_context)

        # 4. Stage 10 - Video Rendering
        from workflow_stages_2 import Stage10_EpisodeVideoRendering, validate_mp4_file
        video_filename = f"video_{ep}.mp4"
        output_video_path = os.path.join(ep_dir, video_filename)
        images_dir = os.path.join(ep_dir, "images_pdf") if os.path.isdir(os.path.join(ep_dir, "images_pdf")) else os.path.join(ep_dir, "images")
        video_fingerprint = stage_fingerprint(task, "video", ep, input_paths=[recap_json_path, audio_path, srt_path, images_dir])

        if not (cache.is_current(stage="video", fingerprint=video_fingerprint, outputs=[output_video_path], validate=lambda: validate_mp4_file(output_video_path))):
            await self.context.log(f"[Streaming Ep {ep}] Đang render video 1080p NVENC...", "info", episode=ep)
            stage10 = Stage10_EpisodeVideoRendering()
            # Run Stage 10 for this episode
            # Creating an episode-targeted sub-task
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
            await stage10.execute(ep_context)

    async def wait_all(self):
        """Waits for all enqueued episodes to finish processing and stops consumer."""
        await self.queue.join()
        self._is_running = False
        if self._worker_task:
            await self._worker_task
            self._worker_task = None
