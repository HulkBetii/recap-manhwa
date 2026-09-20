import os
import json
import pytest
from workflow_stages_2 import (
    Stage12_MetadataReports,
    WorkflowContext,
)
from workflow_base import WorkflowTask


@pytest.mark.asyncio
async def test_stage12_metadata_and_youtube_kit(tmp_path):
    download_dir = tmp_path / "comic_task"
    download_dir.mkdir()
    output_dir = download_dir / "output"
    output_dir.mkdir()

    chapters = [
        {"episode": 1, "timestamp": "00:00", "title": "Episode 1", "duration_seconds": 1800.0},
        {"episode": 2, "timestamp": "30:00", "title": "Episode 2", "duration_seconds": 2100.0},
    ]

    task = WorkflowTask(
        comic_title="The Apocalypse Needs A Pro",
        comic_url="https://vortexscans.org/series/the-apocalypse-needs-a-pro",
        from_episode=1,
        to_episode=2,
        payload={
            "market_id": "us_apocalypse",
        }
    )
    task.artifacts["download_dir"] = str(download_dir)
    task.artifacts["download_folder_name"] = "comic_task"
    task.artifacts["chapters"] = chapters

    class MockContext:
        def __init__(self, t):
            self.task = t
        async def log(self, msg, level="info"):
            pass
        async def update_stage_progress(self, name, pct):
            pass

    context = MockContext(task)
    stage = Stage12_MetadataReports()
    success = await stage.execute(context)
    assert success is True

    # Verify metadata.json
    meta_path = output_dir / "metadata.json"
    assert meta_path.exists()
    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["comic_title"] == "The Apocalypse Needs A Pro"
    assert "youtube_metadata" in data
    # Dynamic titles use pronouns instead of comic title (research: pronouns > IP names)
    assert data["youtube_metadata"]["title"].endswith("| Manhwa Recap")

    # Verify youtube_upload_kit.txt
    kit_path = output_dir / "youtube_upload_kit.txt"
    assert kit_path.exists()
    kit_text = kit_path.read_text(encoding="utf-8")
    assert "YOUTUBE UPLOAD KIT: The Apocalypse Needs A Pro" in kit_text
    assert "Market: us_apocalypse" in kit_text
    assert "[1. TITLE CANDIDATES" in kit_text
    assert "[2. DESCRIPTION & TIMESTAMPS" in kit_text
    assert "00:00" in kit_text
    # Creation statement replaces Section 107 disclaimer (research-driven)
    assert "original scripted narration" in kit_text
    assert "[3. PINNED COMMENT" in kit_text
    assert "📌 MANHWA INFO" in kit_text
    assert "STATUS" in kit_text
    assert "[4. TAGS" in kit_text

    # Verify task artifacts
    assert task.artifacts.get("youtube_upload_kit_url") == "/downloads/comic_task/output/youtube_upload_kit.txt"
