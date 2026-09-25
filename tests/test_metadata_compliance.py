import json
import os
import pytest
from markets.us_apocalypse.metadata import generate_us_apocalypse_metadata
from markets.korea_apocalypse.metadata import generate_korea_apocalypse_metadata
from markets.japan_isekai_territory.metadata import generate_japan_isekai_metadata
from workflow_stages_2 import Stage12_MetadataReports, WorkflowContext
from workflow_base import WorkflowTask


def test_us_apocalypse_metadata_compliance(tmp_path):
    comic_title = "The Apocalypse Needs A Pro"
    from_ep = 1
    to_ep = 2
    chapters = [
        {"episode": 1, "timestamp": "00:00", "title": "Episode 1"},
        {"episode": 2, "timestamp": "25:00", "title": "Episode 2"},
    ]
    story_memory = {
        "comic_title": comic_title,
        "protagonist_name": "Kang Minwoo",
        "episodes": {
            "1": {"summary": "Outbreak in the city", "cliffhanger": "The horde arrived"},
        }
    }

    meta = generate_us_apocalypse_metadata(
        comic_title=comic_title,
        from_ep=from_ep,
        to_ep=to_ep,
        chapters=chapters,
        story_memory=story_memory,
        download_dir=str(tmp_path),
    )

    # 1. Titles & A/B Variants
    assert "title" in meta
    assert len(meta["title"]) <= 100
    assert "title_variants" in meta
    variants = meta["title_variants"]
    assert "variant_a_conflict" in variants
    assert "variant_b_paradox" in variants
    assert "variant_c_scale" in variants
    for v in variants.values():
        assert len(v) <= 100
        assert v.endswith("| Manhwa Recap")

    # 2. Description UTF-8 Byte Limit (< 5000 bytes)
    desc_bytes = len(meta["description"].encode("utf-8"))
    assert desc_bytes <= 5000
    assert "original scripted narration" in meta["description"].lower()

    # 3. Tags (< 15 tags and < 500 chars)
    tags = meta["tags"]
    assert 4 <= len(tags) <= 15
    tag_chars = sum(len(t) for t in tags) + (len(tags) - 1) * 2
    assert tag_chars <= 500

    # 4. Narrative Chapters starting at 00:00
    narrative_ch = meta["narrative_chapters"]
    assert len(narrative_ch) >= 2
    assert narrative_ch[0]["timestamp"] in ("00:00", "0:00")

    # 5. Compliance Flags
    flags = meta["compliance_flags"]
    assert flags["title_length_ok"] is True
    assert flags["description_bytes_ok"] is True
    assert flags["tag_chars_ok"] is True
    assert flags["first_chapter_is_zero"] is True
    assert flags["ypp_originality_statement_present"] is True

    # 6. Formatted Kit includes A/B hypotheses and Compliance Audit
    kit = meta["formatted_kit"]
    assert "NATIVE A/B TEST TITLE HYPOTHESES" in kit
    assert "Hypothesis A (Conflict / Retaliation Hook):" in kit
    assert "Hypothesis B (Paradox / Resource Monopoly Hook):" in kit
    assert "Hypothesis C (Scale / Kingdom Progression Hook):" in kit
    assert "2026 ALGORITHM COMPLIANCE AUDIT SUMMARY" in kit


def test_korea_apocalypse_metadata_compliance():
    comic_title = "좀비묵시록"
    meta = generate_korea_apocalypse_metadata(
        comic_title=comic_title,
        from_ep=1,
        to_ep=3,
        story_memory={"protagonist_name": "이민혁", "episodes": {}}
    )

    assert "[웹툰 몰아보기]" in meta["title"] or "[아포칼립스 웹툰]" in meta["title"]
    assert len(meta["title"]) <= 100
    assert len(meta["description"].encode("utf-8")) <= 5000
    assert "title_variants" in meta
    assert len(meta["title_variants"]) == 3
    assert meta["narrative_chapters"][0]["timestamp"] in ("00:00", "0:00")
    assert meta["compliance_flags"]["title_length_ok"] is True
    assert meta["compliance_flags"]["description_bytes_ok"] is True


def test_japan_isekai_territory_metadata_compliance():
    comic_title = "無能追放領主"
    meta = generate_japan_isekai_metadata(
        comic_title=comic_title,
        from_ep=1,
        to_ep=2,
        story_memory={"protagonist_name": "カイン", "episodes": {}}
    )

    assert "【異世界漫画】" in meta["title"] or "【漫画総集編】" in meta["title"]
    assert len(meta["title"]) <= 100
    assert len(meta["description"].encode("utf-8")) <= 5000
    assert "title_variants" in meta
    assert len(meta["title_variants"]) == 3
    assert meta["narrative_chapters"][0]["timestamp"] in ("00:00", "0:00")
    assert meta["compliance_flags"]["title_length_ok"] is True
    assert meta["compliance_flags"]["description_bytes_ok"] is True


@pytest.mark.asyncio
async def test_stage12_execution_with_compliance_audit(tmp_path):
    download_dir = tmp_path / "comic_task"
    download_dir.mkdir()
    output_dir = download_dir / "output"
    output_dir.mkdir()

    chapters = [
        {"episode": 1, "timestamp": "00:00", "title": "Episode 1", "duration_seconds": 1200.0},
        {"episode": 2, "timestamp": "20:00", "title": "Episode 2", "duration_seconds": 1500.0},
    ]

    task = WorkflowTask(
        comic_title="Survival in Apocalypse",
        comic_url="https://example.com/comic",
        from_episode=1,
        to_episode=2,
        payload={"market_id": "us_apocalypse"}
    )
    task.artifacts["download_dir"] = str(download_dir)
    task.artifacts["download_folder_name"] = "comic_task"
    task.artifacts["chapters"] = chapters

    class MockContext:
        def __init__(self, t):
            self.task = t
        async def log(self, msg, level="info"): pass
        async def update_stage_progress(self, name, pct): pass

    context = MockContext(task)
    stage = Stage12_MetadataReports()
    success = await stage.execute(context)
    assert success is True

    # Check metadata.json contains compliance_audit
    meta_path = output_dir / "metadata.json"
    assert meta_path.exists()
    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "compliance_audit" in data
    assert data["compliance_audit"]["description_bytes_ok"] is True
    assert data["compliance_audit"]["title_length_ok"] is True

    # Check processing_report.json contains compliance_audit
    report_path = output_dir / "processing_report.json"
    assert report_path.exists()
    with open(report_path, "r", encoding="utf-8") as rf:
        rep_data = json.load(rf)
    assert "compliance_audit" in rep_data

    # Check youtube_upload_kit.txt
    kit_path = output_dir / "youtube_upload_kit.txt"
    assert kit_path.exists()
    kit_text = kit_path.read_text(encoding="utf-8")
    assert "NATIVE A/B TEST TITLE HYPOTHESES" in kit_text
    assert "2026 ALGORITHM COMPLIANCE AUDIT SUMMARY" in kit_text
