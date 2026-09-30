# -*- coding: utf-8 -*-
"""
V5.3 Validation Rebuild & Retention Benchmark for Episodes 1-5
Comic: Zombie Revelation: 82-08 (English US Apocalypse Market)
"""
import os
import sys
import asyncio
import json
import time
import shutil
import re

# Ensure UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import Stage5_GeminiAutomation, Stage6_JSONExtraction
from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
    Stage10_EpisodeVideoRendering,
)
from story_memory import StoryMemory

class SimpleCancelToken:
    def is_cancelled(self): return False

class ConsoleContext:
    def __init__(self, task):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload

    async def log(self, message, level="info", *a, **kw):
        ep_part = f" [Ep {kw.get('episode')}]" if kw.get('episode') else ""
        print(f"[{level.upper()}]{ep_part} {message}", flush=True)
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": kw.get("episode") or self.task.current_episode
        })

    async def start_episode(self, ep: int):
        self.task.current_episode = ep
        await self.log(f"Bắt đầu xử lý tập {ep}...", "info", episode=ep)

    async def complete_episode(self, ep: int):
        await self.log(f"Hoàn thành tập {ep}.", "success", episode=ep)

    async def fail_episode(self, ep: int, error: str):
        await self.log(f"Lỗi tập {ep}: {error}", "error", episode=ep)

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)


async def run_stage(stage, task, ctx):
    task.current_stage = stage.name
    print(f"\n{'='*75}")
    print(f"  >>> BẮT ĐẦU: {stage.name}")
    print(f"{'='*75}")
    for s in task.stages:
        if s["name"] == stage.name:
            s["status"] = StageState.RUNNING
            s["progress"] = 0.0

    start_t = time.time()
    ok = await stage.execute(ctx)
    elapsed = time.time() - start_t

    if not ok:
        print(f"\n[FATAL] Giai đoạn {stage.name} thất bại sau {elapsed:.1f}s.")
        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.FAILED
        task.status = WorkflowState.FAILED
        return False

    for s in task.stages:
        if s["name"] == stage.name:
            s["status"] = StageState.SUCCESS
            s["progress"] = 100.0
    print(f"[DONE] Giai đoạn {stage.name} hoàn thành trong {elapsed:.1f}s.")
    return True


def audit_episodes(download_dir, from_ep=1, to_ep=5):
    """Audits retention, protagonist bootstrap, and binge transitions for Episodes 1-5."""
    print("\n" + "=" * 80)
    print("  RUNNING COMPREHENSIVE RETENTION & BINGE CONTINUITY AUDIT (EPISODES 1–5)")
    print("=" * 80)

    report = {
        "comic_title": "Zombie Revelation 82-08",
        "episodes_audited": list(range(from_ep, to_ep + 1)),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pipeline_version": "Stage 5 V5.3 (Retention Hook & Protagonist Bootstrap Patch)",
        "results": {},
        "overall_status": "PENDING"
    }

    all_passed = True

    for ep in range(from_ep, to_ep + 1):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        recap_path = os.path.join(ep_dir, "recap.json")
        narration_path = os.path.join(ep_dir, "narration.txt")
        srt_path = os.path.join(ep_dir, "transcript.srt")
        video_path = os.path.join(ep_dir, "video.mp4")

        ep_result = {
            "episode": ep,
            "files_present": {
                "recap_json": os.path.exists(recap_path),
                "narration_txt": os.path.exists(narration_path),
                "transcript_srt": os.path.exists(srt_path),
                "video_mp4": os.path.exists(video_path),
            },
            "video_size_mb": round(os.path.getsize(video_path) / (1024 * 1024), 2) if os.path.exists(video_path) else 0.0,
            "total_segments": 0,
            "opening_line": "",
            "closing_cliffhanger": "",
            "protagonist_detected": False,
            "protagonist_name_used": "",
            "first_appearance_sec": None,
            "placeholder_paran_count": 0,
            "binge_transition_valid": True,
            "audit_flags": [],
            "status": "PASS"
        }

        # Check files
        if not all(ep_result["files_present"].values()):
            ep_result["audit_flags"].append("Missing generated files")
            ep_result["status"] = "FAIL"
            all_passed = False
            report["results"][f"episode_{ep}"] = ep_result
            continue

        with open(recap_path, "r", encoding="utf-8") as f:
            recap_data = json.load(f)
        ep_result["total_segments"] = len(recap_data)

        # Parse SRT timestamps
        srt_cues = []
        if os.path.exists(srt_path):
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read().strip()
            blocks = re.split(r"\n\s*\n", srt_content)
            for b in blocks:
                lines = b.strip().splitlines()
                if len(lines) >= 3:
                    timing = lines[1]
                    txt = " ".join(lines[2:]).strip()
                    m = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", timing)
                    if m:
                        s_h, s_m, s_s, s_ms = map(int, m.groups()[:4])
                        start_sec = s_h * 3600 + s_m * 60 + s_s + s_ms / 1000.0
                    else:
                        start_sec = 0.0
                    srt_cues.append({"timing": timing, "start_sec": start_sec, "text": txt})

        if recap_data:
            ep_result["opening_line"] = recap_data[0].get("speech", "")
            ep_result["closing_cliffhanger"] = recap_data[-1].get("speech", "")

        # Full episode text
        all_speech = " ".join(seg.get("speech", "") for seg in recap_data)
        ep_result["placeholder_paran_count"] = len(re.findall(r"\bParan\b", all_speech, re.IGNORECASE))
        if ep_result["placeholder_paran_count"] > 0:
            ep_result["audit_flags"].append(f"Hallucinated 'Paran' placeholder found ({ep_result['placeholder_paran_count']} times)")
            ep_result["status"] = "FAIL"
            all_passed = False

        # Protagonist check
        if "Tae" in all_speech:
            ep_result["protagonist_detected"] = True
            ep_result["protagonist_name_used"] = "Tae"
        elif any(p in all_speech.lower() for p in ["our boy", "he ", "his "]):
            ep_result["protagonist_detected"] = True
            ep_result["protagonist_name_used"] = "Tae (via context pronouns)"

        # Timing of first MC mention
        for idx, seg in enumerate(recap_data):
            speech = seg.get("speech", "")
            if "Tae" in speech or (idx == 0 and any(w in speech.lower() for w in ["tae", "our boy", "our protagonist"])):
                if idx < len(srt_cues):
                    ep_result["first_appearance_sec"] = srt_cues[idx]["start_sec"]
                else:
                    ep_result["first_appearance_sec"] = 0.0
                break

        # Episode 1 Specific: Golden 0-15s Hook check
        if ep == 1:
            if ep_result["first_appearance_sec"] is None or ep_result["first_appearance_sec"] > 15.0:
                ep_result["audit_flags"].append(f"Protagonist appearance delayed ({ep_result['first_appearance_sec']}s > 15.0s)")
                ep_result["status"] = "FAIL"
                all_passed = False
            if "Tae" not in ep_result["opening_line"]:
                # Check segment 2
                seg2_speech = recap_data[1].get("speech", "") if len(recap_data) > 1 else ""
                if "Tae" not in seg2_speech:
                    ep_result["audit_flags"].append("Tae not introduced in Segment 1 or 2")
                    ep_result["status"] = "FAIL"
                    all_passed = False

        # Episodes 2-5: Binge transition check
        if ep > 1:
            prev_ep_dir = os.path.join(download_dir, f"episode_{ep - 1}")
            prev_recap_path = os.path.join(prev_ep_dir, "recap.json")
            if os.path.exists(prev_recap_path):
                with open(prev_recap_path, "r", encoding="utf-8") as pf:
                    prev_recap = json.load(pf)
                prev_cliffhanger = prev_recap[-1].get("speech", "") if prev_recap else ""
                # Verify zero throat clearing
                if any(w in ep_result["opening_line"].lower() for w in ["welcome back", "in the previous", "previously", "last chapter"]):
                    ep_result["audit_flags"].append("Throat clearing detected in Episode opening")
                    ep_result["status"] = "FAIL"
                    all_passed = False

        print(f"\n--- EPISODE {ep} BENCHMARK AUDIT ---")
        print(f"  Status: {ep_result['status']}")
        print(f"  Segments: {ep_result['total_segments']}")
        print(f"  Video Size: {ep_result['video_size_mb']} MB")
        print(f"  Opening Line (0-5s): \"{ep_result['opening_line'][:90]}...\"")
        print(f"  Protagonist First Appearance: {ep_result['first_appearance_sec']}s (MC: {ep_result['protagonist_name_used']})")
        print(f"  Placeholder 'Paran' Count: {ep_result['placeholder_paran_count']}")
        if ep_result["audit_flags"]:
            print(f"  Flags: {ep_result['audit_flags']}")

        report["results"][f"episode_{ep}"] = ep_result

    report["overall_status"] = "PASS" if all_passed else "FAIL"

    # Save artifact
    os.makedirs(os.path.join(download_dir, "output"), exist_ok=True)
    report_path = os.path.join(download_dir, "output", "v5_3_retention_benchmark_ep1_5.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"  OVERALL AUDIT BENCHMARK: {report['overall_status']}")
    print(f"  Saved benchmark report to: {report_path}")
    print("=" * 80)
    return report


async def main():
    target_url = "https://www.webtoons.com/en/action/zombie-revelation-82-08/list?title_no=6065"
    download_dir = os.path.join(PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_143_en_946016ec")
    from_ep = 1
    to_ep = 5

    print("=" * 80)
    print("  START V5.3 VALIDATION REBUILD FOR EPISODES 1–5")
    print(f"  Comic: Zombie Revelation: 82-08 | URL: {target_url}")
    print(f"  Episodes: {from_ep} -> {to_ep}")
    print(f"  Directory: {download_dir}")
    print("=" * 80)

    # 1. Clean previous generation artifacts for Episodes 2-5 to force fresh V5.3 generation
    for ep in range(from_ep, to_ep + 1):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        if ep > 1: # For ep 2-5, clear old recap/narration/audio to force fresh generation
            for fname in ["recap.json", "raw_gemini_response.txt", "narration.txt", "audio.mp3", "transcript.srt", "video.mp4", "artifact_manifest.json"]:
                p = os.path.join(ep_dir, fname)
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass

    # 2. Setup Task
    task_id = f"zombie-revelation-v5-3-rebuild-1-5-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Zombie Revelation: 82-08",
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload={
            "vlm_model": "ag/gemini-3.8-flash-medium",
            "language": "en",
            "market_id": "us_apocalypse",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "enable_flash_forward_intro": False,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
        },
        id=task_id
    )
    task.artifacts["download_dir"] = download_dir
    task.artifacts["comic_title"] = "Zombie Revelation: 82-08"

    ctx = ConsoleContext(task)

    # 3. Pipeline Stages
    pipeline = [
        Stage5_GeminiAutomation(),
        Stage6_JSONExtraction(),
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
        Stage10_EpisodeVideoRendering(),
    ]

    for stage in pipeline:
        ok = await run_stage(stage, task, ctx)
        if not ok:
            print(f"[FATAL ERROR] Rebuild failed at stage {stage.name}!")
            return 1

    # 4. Retention Benchmark Audit
    audit_report = audit_episodes(download_dir, from_ep, to_ep)
    if audit_report["overall_status"] != "PASS":
        print("[WARNING] Audit flagged some items.")
        return 2

    print("\n[SUCCESS] Rebuild and Retention Benchmark Completed Successfully!")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
