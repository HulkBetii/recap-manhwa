# -*- coding: utf-8 -*-
"""
Video Merge Router: Dedicated API endpoints for splitting and merging
rendered video episodes independently of the main workflow task queue.
"""

import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from workflow_merger import (
    get_task_available_episodes,
    merge_episode_ranges_for_task,
    delete_merged_video_file
)
from workflow_base import WorkflowTask, WorkflowState

logger = logging.getLogger("VideoMergeRouter")
router = APIRouter(prefix="/api/video_merge", tags=["video_merge"])


class SplitMergeRange(BaseModel):
    from_ep: int
    to_ep: int
    custom_name: Optional[str] = ""


class VideoMergeRunRequest(BaseModel):
    identifier: str  # task_id or folder_name
    ranges: List[SplitMergeRange]


def _resolve_task_or_folder(identifier: str) -> Optional[WorkflowTask]:
    """Helper to find an existing WorkflowTask by ID or build a dummy task for a standalone folder."""
    from app import workflow_manager
    
    # Try finding in repository
    task = workflow_manager.repository.load(identifier)
    if task:
        return task

    # Search tasks by folder name or title
    all_tasks = workflow_manager.repository.load_all()
    for t in all_tasks:
        art = getattr(t, "artifacts", {}) or {}
        f_name = art.get("download_folder_name")
        if f_name and f_name.lower() == identifier.lower():
            return t

    # If not in repository, check if downloads/{identifier} directory exists
    candidate_dir = os.path.join("downloads", identifier)
    if os.path.isdir(candidate_dir):
        # Create virtual task for this directory
        virtual_task = WorkflowTask(
            comic_title=identifier.replace("_", " ").title(),
            comic_url="",
            from_episode=1,
            to_episode=1,
            payload={},
            id=f"standalone_{identifier}"
        )
        virtual_task.status = WorkflowState.SUCCESS
        virtual_task.artifacts = {
            "download_dir": candidate_dir,
            "download_folder_name": identifier
        }
        return virtual_task

    return None


@router.get("/comics")
async def get_mergeable_comics():
    """Returns all comics that have rendered episode videos available for merging."""
    from app import workflow_manager
    results = []
    seen_folders = set()

    # 1. From workflow tasks
    tasks = workflow_manager.repository.load_all()
    for t in tasks:
        art = getattr(t, "artifacts", {}) or {}
        dl_dir = art.get("download_dir")
        folder = art.get("download_folder_name") or (os.path.basename(dl_dir) if dl_dir else None)
        if folder and os.path.isdir(os.path.join("downloads", folder)):
            info = get_task_available_episodes(t)
            if info.get("total_rendered", 0) > 0:
                seen_folders.add(folder.lower())
                results.append(info)

    # 2. From downloads directory (in case standalone or legacy)
    downloads_dir = "downloads"
    if os.path.isdir(downloads_dir):
        for entry in sorted(os.listdir(downloads_dir)):
            if entry.lower() in seen_folders:
                continue
            entry_path = os.path.join(downloads_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            
            # Check if has any episode_*/video.mp4
            has_videos = False
            for sub in os.listdir(entry_path):
                if sub.startswith("episode_") and os.path.isfile(os.path.join(entry_path, sub, "video.mp4")):
                    has_videos = True
                    break

            if has_videos:
                v_task = _resolve_task_or_folder(entry)
                if v_task:
                    info = get_task_available_episodes(v_task)
                    if info.get("total_rendered", 0) > 0:
                        seen_folders.add(entry.lower())
                        results.append(info)

    return {"status": "success", "comics": results}


@router.get("/info/{identifier}")
async def get_comic_merge_info(identifier: str):
    """Returns detailed episode and merge info for a specific task or folder."""
    task = _resolve_task_or_folder(identifier)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện hoặc nhiệm vụ.")

    info = get_task_available_episodes(task)
    return info


@router.post("/merge")
async def run_video_merge(payload: VideoMergeRunRequest):
    """Executes splitting and merging of rendered episode videos."""
    from app import workflow_manager
    task = _resolve_task_or_folder(payload.identifier)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện hoặc nhiệm vụ.")

    if not payload.ranges:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp ít nhất một khoảng tập để gộp.")

    ranges_data = [r.model_dump() if hasattr(r, 'model_dump') else r.dict() for r in payload.ranges]
    res = await merge_episode_ranges_for_task(task, ranges_data)

    # If task exists in repository, persist changes
    if not task.id.startswith("standalone_"):
        await workflow_manager.save_and_broadcast("WorkflowUpdated", task)

    if res.get("status") == "error" and not res.get("merged_videos"):
        error_details = "; ".join(res.get("errors", []))
        raise HTTPException(status_code=400, detail=f"Không thể gộp video: {error_details}")

    return res


@router.delete("/merged-videos/{identifier}/{file_name}")
async def delete_merged_video_endpoint(identifier: str, file_name: str):
    """Deletes a merged video output file."""
    from app import workflow_manager
    task = _resolve_task_or_folder(identifier)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện hoặc nhiệm vụ.")

    success = delete_merged_video_file(task, file_name)
    if success:
        if not task.id.startswith("standalone_"):
            await workflow_manager.save_and_broadcast("WorkflowUpdated", task)
        return {"status": "success", "message": f"Đã xóa video gộp '{file_name}' thành công."}
    else:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy video gộp '{file_name}'.")
