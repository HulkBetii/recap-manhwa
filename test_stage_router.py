# -*- coding: utf-8 -*-
"""
Test Stage Router: Dedicated API endpoints for independent testing of
individual pipeline stages (Stage 2b, Stage 5, Stage 8, Stage 10) on local episode folders.
"""

import os
import re
import json
import time
import urllib.parse
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/test_stage", tags=["test_stage"])


class TestStageRunRequest(BaseModel):
    stage: str  # "smart_paging", "gemini_automation", "tts", "video_render", "stage_2b", "stage_5", "stage_8", "stage_10"
    folder_path: Optional[str] = None  # e.g. "C:\...\downloads\the_forgotten_field_1_2_vi\episode_2" or "the_forgotten_field_1_2_vi"
    comic_url: Optional[str] = None
    local_folder: Optional[str] = None
    episode_num: Optional[int] = None
    force_recrawl: bool = False
    gemini_model: str = "flash"
    language: str = "vi"
    pdf_quality: int = 20
    headless: Optional[bool] = None


class ValidateFolderRequest(BaseModel):
    folder_path: str


def parse_folder_and_episode(input_path: str):
    """
    Parses an absolute or relative directory path into (comic_dir, comic_folder_name, episode_num).
    Supports paths like:
    - 'C:/.../downloads/the_forgotten_field_1_2_vi/episode_2' -> (comic_dir, 'the_forgotten_field_1_2_vi', 2)
    - 'the_forgotten_field_1_2_vi/episode_2' -> (comic_dir, 'the_forgotten_field_1_2_vi', 2)
    - 'the_forgotten_field_1_2_vi' -> (comic_dir, 'the_forgotten_field_1_2_vi', 1)
    """
    if not input_path:
        return None, None, 1

    clean_path = os.path.normpath(input_path.strip().strip('"').strip("'"))
    project_dir = os.path.dirname(os.path.abspath(__file__))
    downloads_dir = os.path.join(project_dir, "downloads")

    # If relative path, resolve against downloads or project
    if not os.path.isabs(clean_path):
        candidate1 = os.path.join(downloads_dir, clean_path)
        candidate2 = os.path.join(project_dir, clean_path)
        if os.path.exists(candidate1):
            clean_path = candidate1
        elif os.path.exists(candidate2):
            clean_path = candidate2
        else:
            clean_path = candidate1

    # Check if target is an episode subfolder
    base_name = os.path.basename(clean_path)
    if base_name.startswith("episode_"):
        try:
            ep_num = int(base_name.split("_")[1])
        except Exception:
            ep_num = 1
        comic_dir = os.path.dirname(clean_path)
        comic_folder_name = os.path.basename(comic_dir)
        return comic_dir, comic_folder_name, ep_num

    # Otherwise treat as comic root folder
    comic_dir = clean_path
    comic_folder_name = os.path.basename(comic_dir)
    return comic_dir, comic_folder_name, 1


@router.get("/local_comics")
async def get_local_comics():
    """Returns all available local comic folders and their episodes in downloads/."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    downloads_dir = os.path.join(project_dir, "downloads")
    if not os.path.exists(downloads_dir):
        return {"comics": []}

    results = []
    for item in sorted(os.listdir(downloads_dir)):
        item_path = os.path.join(downloads_dir, item)
        if not os.path.isdir(item_path):
            continue

        episodes = []
        for sub in sorted(os.listdir(item_path)):
            if sub.startswith("episode_") and os.path.isdir(os.path.join(item_path, sub)):
                try:
                    ep_num = int(sub.split("_")[1])
                except Exception:
                    continue

                ep_dir = os.path.join(item_path, sub)
                raw_images_dir = os.path.join(ep_dir, "images_source_raw")
                images_dir = os.path.join(ep_dir, "images")
                images_pdf_dir = os.path.join(ep_dir, "images_pdf")
                pdf_dir = os.path.join(ep_dir, "pdf")
                recap_path = os.path.join(ep_dir, "recap.json")
                audio_path = os.path.join(ep_dir, "audio.mp3")
                video_path = os.path.join(ep_dir, "video.mp4")

                raw_count = 0
                if os.path.exists(raw_images_dir):
                    raw_count = len([f for f in os.listdir(raw_images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])

                img_count = 0
                if os.path.exists(images_dir):
                    img_count = len([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
                elif os.path.exists(images_pdf_dir):
                    img_count = len([f for f in os.listdir(images_pdf_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])

                pdf_files = []
                if os.path.exists(pdf_dir):
                    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf') and os.path.getsize(os.path.join(pdf_dir, f)) > 0]

                has_recap = os.path.exists(recap_path) and os.path.getsize(recap_path) > 0
                has_audio = os.path.exists(audio_path) and os.path.getsize(audio_path) > 0
                has_video = os.path.exists(video_path) and os.path.getsize(video_path) > 0

                episodes.append({
                    "episode_num": ep_num,
                    "folder_path": ep_dir,
                    "has_raw_images": raw_count > 0,
                    "raw_images_count": raw_count,
                    "has_images": img_count > 0,
                    "images_count": img_count,
                    "has_pdf": len(pdf_files) > 0,
                    "pdf_name": pdf_files[0] if pdf_files else None,
                    "has_recap": has_recap,
                    "has_audio": has_audio,
                    "has_video": has_video
                })

        if episodes:
            clean_name = item.replace("_", " ").title()
            results.append({
                "folder_name": item,
                "display_name": clean_name,
                "path": item_path,
                "episodes": episodes
            })

    return {"comics": results}


@router.post("/validate_folder")
async def validate_folder(payload: ValidateFolderRequest):
    """Inspects a provided folder path and returns validation status and available resources."""
    comic_dir, folder_name, ep_num = parse_folder_and_episode(payload.folder_path)
    if not comic_dir or not os.path.exists(comic_dir):
        return {
            "valid": False,
            "error": f"Đường dẫn không tồn tại: {payload.folder_path}"
        }

    ep_dir = os.path.join(comic_dir, f"episode_{ep_num}")
    if not os.path.exists(ep_dir):
        available_eps = [f for f in os.listdir(comic_dir) if f.startswith("episode_")]
        return {
            "valid": False,
            "error": f"Không tìm thấy thư mục episode_{ep_num} trong '{comic_dir}'. Các tập có sẵn: {available_eps}"
        }

    raw_images_dir = os.path.join(ep_dir, "images_source_raw")
    images_dir = os.path.join(ep_dir, "images")
    pdf_dir = os.path.join(ep_dir, "pdf")
    recap_path = os.path.join(ep_dir, "recap.json")
    audio_path = os.path.join(ep_dir, "audio.mp3")
    video_path = os.path.join(ep_dir, "video.mp4")

    raw_count = len([f for f in os.listdir(raw_images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]) if os.path.exists(raw_images_dir) else 0
    img_count = len([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]) if os.path.exists(images_dir) else 0
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')] if os.path.exists(pdf_dir) else []

    return {
        "valid": True,
        "comic_title": folder_name.replace("_", " ").title(),
        "folder_name": folder_name,
        "episode_num": ep_num,
        "ep_dir": ep_dir,
        "has_raw_images": raw_count > 0,
        "raw_images_count": raw_count,
        "has_images": img_count > 0,
        "images_count": img_count,
        "has_pdf": len(pdf_files) > 0,
        "pdf_name": pdf_files[0] if pdf_files else None,
        "has_recap": os.path.exists(recap_path) and os.path.getsize(recap_path) > 0,
        "has_audio": os.path.exists(audio_path),
        "has_video": os.path.exists(video_path)
    }


@router.post("/run")
async def run_test_stage(payload: TestStageRunRequest):
    """
    Launches a targeted single-stage or multi-stage test workflow for a specific episode.
    """
    from app import workflow_manager, load_config

    raw_stage = payload.stage.strip().lower()
    
    stage_map = {
        "phase_1": "stage_2b",
        "phase1": "stage_2b",
        "visual_prep": "stage_2b",
        "smart_paging": "stage_2b",
        "stage_2b": "stage_2b",
        "stage2b": "stage_2b",
        "repagination": "stage_2b",
        "phase_2": "stage_5",
        "phase2": "stage_5",
        "script": "stage_5",
        "gemini_automation": "stage_5",
        "stage_5": "stage_5",
        "stage5": "stage_5",
        "gemini": "stage_5",
        "phase_3": "stage_8",
        "phase3": "stage_8",
        "audio": "stage_8",
        "tts": "stage_8",
        "stage_8": "stage_8",
        "stage8": "stage_8",
        "phase_4": "stage_10",
        "phase4": "stage_10",
        "render": "stage_10",
        "video_render": "stage_10",
        "stage_10": "stage_10",
        "stage10": "stage_10"
    }

    stage_type = stage_map.get(raw_stage, "stage_2b")
    folder_input = payload.folder_path or payload.local_folder

    comic_dir = None
    comic_folder_name = None
    ep_num = payload.episode_num or 1
    comic_title = "Comic Test"
    comic_url = (payload.comic_url or "").strip()

    if folder_input:
        c_dir, f_name, e_num = parse_folder_and_episode(folder_input)
        if c_dir and os.path.exists(c_dir):
            comic_dir = c_dir
            comic_folder_name = f_name
            ep_num = payload.episode_num if payload.episode_num else e_num
            comic_title = f_name.replace("_", " ").title()
            if not comic_url:
                comic_url = f"https://local-test/{f_name}"
        else:
            raise HTTPException(status_code=404, detail=f"Thư mục '{folder_input}' không tồn tại.")
    elif comic_url:
        parsed = urllib.parse.urlparse(comic_url)
        if "asura" in parsed.netloc.lower() and parsed.netloc.lower() != "asurascans.com":
            comic_url = urllib.parse.urlunparse(parsed._replace(netloc="asurascans.com"))
        elif "manhuaplus.com" in parsed.netloc.lower() and "/chapter-" in comic_url:
            comic_url = re.sub(r"/chapter-[^/]+/?$", "/", comic_url)

        parsed = urllib.parse.urlparse(comic_url)
        if parsed.path:
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if parts:
                slug = parts[-1]
                if slug in ('viewer', 'list') and len(parts) >= 2:
                    slug = parts[-2]
                comic_title = slug.replace("-", " ").title()
    else:
        raise HTTPException(status_code=400, detail="Cần truyền Đường dẫn thư mục tập có sẵn hoặc Link truyện.")

    test_pipeline = []
    stop_after = None

    if stage_type == "stage_2b":
        if comic_dir:
            test_pipeline = [
                "Stage 2b - Intelligent Re-pagination",
                "Stage 4 - PDF Generation"
            ]
        else:
            test_pipeline = [
                "Stage 0 - Project Init",
                "Stage 1 - Comic Parsing",
                "Stage 2 - Image Crawling",
                "Stage 2b - Intelligent Re-pagination",
                "Stage 3 - NSFW Moderation",
                "Stage 4 - PDF Generation"
            ]
        stop_after = "Stage 4 - PDF Generation"

    elif stage_type == "stage_5":
        if comic_dir:
            test_pipeline = [
                "Stage 5 - Gemini Automation",
                "Stage 6 - JSON Extraction"
            ]
        else:
            test_pipeline = [
                "Stage 0 - Project Init",
                "Stage 1 - Comic Parsing",
                "Stage 2 - Image Crawling",
                "Stage 2b - Intelligent Re-pagination",
                "Stage 3 - NSFW Moderation",
                "Stage 4 - PDF Generation",
                "Stage 5 - Gemini Automation",
                "Stage 6 - JSON Extraction"
            ]
        stop_after = "Stage 6 - JSON Extraction"

    elif stage_type == "stage_8":
        test_pipeline = [
            "Stage 7 - Narration Aggregation",
            "Stage 8 - Local TTS",
            "Stage 9 - Subtitle Normalization"
        ]
        stop_after = "Stage 9 - Subtitle Normalization"

    elif stage_type == "stage_10":
        test_pipeline = [
            "Stage 10 - Episode Video Rendering"
        ]
        stop_after = "Stage 10 - Episode Video Rendering"

    task_config = {
        "is_test_stage": True,
        "test_stage_type": stage_type,
        "test_stage_pipeline": test_pipeline,
        "stop_after_stage": stop_after,
        "gemini_model": payload.gemini_model or "flash",
        "language": payload.language or "vi",
        "pdf_quality": payload.pdf_quality or 20,
        "safe_mode": False,
        "nsfw_threshold": 0.45,
        "nsfw_mode": "dino_sam",
        "concurrency": 2,
        "paging_mode": "ai_direct",
        "separate_speech_bubbles": True,
        "isolate_visual_frames": True,
        "tight_auto_crop": True,
        "video_only_frame_filter": True,
        "use_ai_sr": True,
        "force_recrawl": payload.force_recrawl,
        "headless": payload.headless if payload.headless is not None else load_config().get("headless", False)
    }

    task_id = await workflow_manager.queue_task(
        comic_title=comic_title,
        comic_url=comic_url,
        from_episode=ep_num,
        to_episode=ep_num,
        config=task_config
    )

    if comic_dir:
        created_task = workflow_manager.repository.load(task_id)
        if created_task:
            created_task.artifacts["download_dir"] = comic_dir
            created_task.artifacts["download_folder_name"] = comic_folder_name
            workflow_manager.repository.save(created_task)

    return {
        "status": "success",
        "task_id": task_id,
        "stage": stage_type,
        "episode": ep_num,
        "target_pipeline": test_pipeline,
        "stop_after_stage": stop_after,
        "comic_title": comic_title
    }


@router.get("/status/{task_id}")
async def get_test_stage_status(task_id: str):
    """Returns live status and comprehensive extracted visual results for the test task."""
    from app import workflow_manager

    task = workflow_manager.repository.load(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy task với ID yêu cầu.")

    stage_type = task.payload.get("test_stage_type", "stage_2b")
    download_dir = task.artifacts.get("download_dir")
    folder_name = task.artifacts.get("download_folder_name")
    if not folder_name and download_dir:
        folder_name = os.path.basename(download_dir)

    ep_num = task.from_episode or 1
    result_data = None

    if download_dir and os.path.exists(download_dir):
        ep_dir = os.path.join(download_dir, f"episode_{ep_num}")
        if os.path.exists(ep_dir):
            if stage_type in ("stage_2b", "smart_paging"):
                result_data = extract_smart_paging_results(ep_dir, folder_name, ep_num)
            elif stage_type in ("stage_5", "gemini_automation"):
                result_data = extract_gemini_automation_results(ep_dir, folder_name, ep_num)
            elif stage_type in ("stage_8", "tts"):
                result_data = extract_tts_results(ep_dir, folder_name, ep_num)
            elif stage_type in ("stage_10", "video_render"):
                result_data = extract_video_results(ep_dir, folder_name, ep_num)

    norm_status = str(task.status).upper() if task.status else ""
    return {
        "task_id": task.id,
        "status": norm_status,
        "raw_status": task.status,
        "stage_type": stage_type,
        "episode": ep_num,
        "current_stage": task.current_stage,
        "overall_progress": task.overall_progress,
        "elapsed_time": task.elapsed_time,
        "error_message": task.error_message,
        "logs": task.logs[-80:] if task.logs else [],
        "result": result_data
    }


@router.post("/cancel/{task_id}")
async def cancel_test_stage(task_id: str):
    """Cancels the active test task."""
    from app import workflow_manager
    success = await workflow_manager.cancel_task(task_id)
    return {"status": "success" if success else "failed", "cancelled": success}


def extract_smart_paging_results(ep_dir: str, folder_name: str, ep_num: int = 1) -> Optional[Dict[str, Any]]:
    """Extracts PDF, visual frames, metadata, and dropped junk audit for Smart Paging / Stage 2b."""
    pdf_dir = os.path.join(ep_dir, "pdf")
    pdf_file = None
    pdf_size_mb = 0.0
    if os.path.exists(pdf_dir):
        for f in os.listdir(pdf_dir):
            if f.lower().endswith(".pdf"):
                fp = os.path.join(pdf_dir, f)
                if os.path.getsize(fp) > 0:
                    pdf_file = f
                    pdf_size_mb = round(os.path.getsize(fp) / (1024 * 1024), 2)
                    break

    images_source_dir = os.path.join(ep_dir, "images")
    subfolder = "images"
    if not os.path.exists(images_source_dir) or not os.listdir(images_source_dir):
        images_source_dir = os.path.join(ep_dir, "images_pdf")
        subfolder = "images_pdf"

    page_files = []
    if os.path.exists(images_source_dir):
        page_files = sorted([f for f in os.listdir(images_source_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])

    meta_path = os.path.join(ep_dir, "debug_repaging", "pure_visual_regions_metadata.json")
    if not os.path.exists(meta_path):
        meta_path = os.path.join(ep_dir, "debug", "pure_visual_regions_metadata.json")

    meta_data = {}
    dropped_junk = []
    total_candidates = len(page_files)
    total_exported = len(page_files)

    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as mf:
                meta_data = json.load(mf)
                total_candidates = meta_data.get("total_candidate_regions", len(page_files))
                total_exported = meta_data.get("total_pure_visual_regions", len(page_files))
                dropped_junk = meta_data.get("filtered_junk_regions", [])
        except Exception:
            pass

    regions_map = {}
    for r in meta_data.get("regions", []):
        rid = r.get("region_id")
        if rid:
            regions_map[str(rid)] = r

    pages = []
    for idx, f in enumerate(page_files, start=1):
        reg = regions_map.get(str(idx), {})
        det = reg.get("details", {})
        comp = det.get("visual_complexity", {})
        
        pages.append({
            "page_index": idx,
            "region_id": f"R{idx}",
            "filename": f,
            "image_url": f"/downloads/{folder_name}/episode_{ep_num}/{subfolder}/{f}",
            "width": det.get("width", 1080),
            "height": det.get("height", 0),
            "visual_score": round(reg.get("visual_ratio", 0.85) * 100, 1),
            "face_count": reg.get("face_count", 0),
            "body_count": reg.get("body_count", 0),
            "edge_density": comp.get("edge_density", 0.0),
            "laplacian": comp.get("laplacian_variance", 0.0)
        })

    if not pdf_file and not pages:
        return None

    return {
        "type": "smart_paging",
        "episode": ep_num,
        "has_pdf": pdf_file is not None,
        "pdf_filename": pdf_file,
        "pdf_url": f"/downloads/{folder_name}/episode_{ep_num}/pdf/{pdf_file}" if pdf_file else None,
        "pdf_size_mb": pdf_size_mb,
        "total_pages": len(pages),
        "total_candidates": total_candidates,
        "total_exported": total_exported,
        "total_junk_dropped": len(dropped_junk),
        "pages": pages,
        "dropped_junk": dropped_junk
    }


def extract_gemini_automation_results(ep_dir: str, folder_name: str, ep_num: int = 1) -> Optional[Dict[str, Any]]:
    """Extracts recap.json and pairs each speech segment with its visual frame for Gemini Automation / Stage 5."""
    recap_path = os.path.join(ep_dir, "recap.json")
    if not os.path.exists(recap_path) or os.path.getsize(recap_path) == 0:
        return None

    try:
        with open(recap_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
    except Exception:
        return None

    images_source_dir = os.path.join(ep_dir, "images")
    subfolder = "images"
    if not os.path.exists(images_source_dir) or not os.listdir(images_source_dir):
        images_source_dir = os.path.join(ep_dir, "images_pdf")
        subfolder = "images_pdf"

    image_files = []
    if os.path.exists(images_source_dir):
        image_files = sorted([f for f in os.listdir(images_source_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])

    raw_response_text = ""
    raw_resp_path = os.path.join(ep_dir, "raw_gemini_response.txt")
    if os.path.exists(raw_resp_path):
        try:
            with open(raw_resp_path, "r", encoding="utf-8") as rf:
                raw_response_text = rf.read()
        except Exception:
            pass

    segments = []
    total_words = 0

    for s_idx, item in enumerate(data, start=1):
        speech_text = item.get("speech", "").strip()
        words = len(speech_text.split())
        total_words += words
        img_list = item.get("images", [])

        page_num = 1
        priority = 1.0
        if isinstance(img_list, list) and len(img_list) > 0:
            first_img = img_list[0]
            if isinstance(first_img, dict):
                try:
                    page_num = int(first_img.get("page", 1))
                except Exception:
                    page_num = 1
                try:
                    priority = float(first_img.get("priority", 1.0))
                except Exception:
                    priority = 1.0
            elif isinstance(first_img, (int, str)):
                try:
                    page_num = int(first_img)
                except Exception:
                    page_num = 1

        img_file = None
        page_idx = page_num - 1
        if 0 <= page_idx < len(image_files):
            img_file = image_files[page_idx]
        elif image_files:
            img_file = image_files[min(len(image_files) - 1, max(0, page_idx))]

        img_url = f"/downloads/{folder_name}/episode_{ep_num}/{subfolder}/{img_file}" if img_file else None

        segments.append({
            "segment_index": s_idx,
            "page_num": page_num,
            "frame_label": f"R{page_num}",
            "image_filename": img_file,
            "image_url": img_url,
            "speech": speech_text,
            "word_count": words,
            "priority": priority
        })

    return {
        "type": "gemini_automation",
        "episode": ep_num,
        "total_segments": len(segments),
        "total_words": total_words,
        "recap_json_url": f"/downloads/{folder_name}/episode_{ep_num}/recap.json",
        "segments": segments,
        "raw_json": data,
        "raw_text": raw_response_text
    }


def extract_tts_results(ep_dir: str, folder_name: str, ep_num: int = 1) -> Optional[Dict[str, Any]]:
    """Extracts audio and transcript for TTS / Stage 8."""
    audio_path = os.path.join(ep_dir, "audio.mp3")
    srt_path = os.path.join(ep_dir, "transcript.srt")
    if not os.path.exists(audio_path):
        return None

    audio_size_mb = round(os.path.getsize(audio_path) / (1024 * 1024), 2)
    srt_content = ""
    if os.path.exists(srt_path):
        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()
        except Exception:
            pass

    return {
        "type": "tts",
        "episode": ep_num,
        "audio_url": f"/downloads/{folder_name}/episode_{ep_num}/audio.mp3",
        "audio_size_mb": audio_size_mb,
        "srt_url": f"/downloads/{folder_name}/episode_{ep_num}/transcript.srt" if os.path.exists(srt_path) else None,
        "srt_content": srt_content
    }


def extract_video_results(ep_dir: str, folder_name: str, ep_num: int = 1) -> Optional[Dict[str, Any]]:
    """Extracts rendered video and properties for Video Rendering / Stage 10."""
    video_path = os.path.join(ep_dir, "video.mp4")
    if not os.path.exists(video_path):
        return None

    video_size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2)
    srt_path = os.path.join(ep_dir, "video.srt")
    if not os.path.exists(srt_path):
        srt_path = os.path.join(ep_dir, "transcript.srt")

    # Ensure video.srt is created if only transcript.srt existed
    if os.path.exists(os.path.join(ep_dir, "transcript.srt")) and not os.path.exists(os.path.join(ep_dir, "video.srt")):
        try:
            import shutil
            shutil.copy2(os.path.join(ep_dir, "transcript.srt"), os.path.join(ep_dir, "video.srt"))
            srt_path = os.path.join(ep_dir, "video.srt")
        except Exception:
            pass

    srt_content = ""
    if os.path.exists(srt_path):
        try:
            with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
                srt_content = f.read()
        except Exception:
            pass

    return {
        "type": "video_render",
        "episode": ep_num,
        "video_url": f"/downloads/{folder_name}/episode_{ep_num}/video.mp4",
        "video_size_mb": video_size_mb,
        "srt_url": f"/downloads/{folder_name}/episode_{ep_num}/video.srt" if os.path.exists(os.path.join(ep_dir, "video.srt")) else (f"/downloads/{folder_name}/episode_{ep_num}/transcript.srt" if os.path.exists(srt_path) else None),
        "srt_content": srt_content
    }

