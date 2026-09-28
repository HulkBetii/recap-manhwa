# -*- coding: utf-8 -*-
"""
Production Validation Runner for Episodes 6-10 using frozen pipeline.
Validates:
1. Stage 5 V5.3 Protagonist Continuity
2. StoryMemory Consistency
3. Stage 11 Timeline Generation
4. Stage 12 Chapter Grounding V1
5. Prepublish Audit

Exports: production_validation_ep6_ep10.json
"""
import os
import sys
import json
import time
import re
from typing import Dict, Any, List

# Ensure UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from story_memory import StoryMemory
from markets.us_apocalypse.metadata import (
    generate_us_apocalypse_metadata,
    build_narrative_story_chapters,
    validate_packaging_consistency,
    _build_resource_contrast_concepts,
    EvidenceIndex,
)
from markets.us_apocalypse.story_fact_graph import StoryFactGraph


def parse_srt(srt_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(srt_path):
        return []
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    blocks = re.split(r"\n\s*\n", content)
    cues = []
    for b in blocks:
        lines = b.strip().splitlines()
        if len(lines) >= 3:
            timing = lines[1]
            txt = " ".join(lines[2:]).strip()
            m = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", timing)
            if m:
                s_h, s_m, s_s, s_ms = map(int, m.groups()[:4])
                e_h, e_m, e_s, e_ms = map(int, m.groups()[4:8])
                start_sec = s_h * 3600 + s_m * 60 + s_s + s_ms / 1000.0
                end_sec = e_h * 3600 + e_m * 60 + e_s + e_ms / 1000.0
            else:
                start_sec = 0.0
                end_sec = 0.0
            cues.append({
                "index": int(lines[0]) if lines[0].isdigit() else len(cues) + 1,
                "timing": timing,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration_sec": round(end_sec - start_sec, 3),
                "text": txt,
            })
    return cues


def format_timestamp(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def run_production_validation():
    base_dir = os.path.join(PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_143_en_946016ec")
    episodes = list(range(6, 11))
    
    print("=" * 80)
    print("  PRODUCTION VALIDATION: EPISODES 6–10 (FROZEN PIPELINE)")
    print("=" * 80)

    validation_report: Dict[str, Any] = {
        "comic_title": "Zombie Revelation: 82-08",
        "market": "us_apocalypse",
        "archetype": "zombie_apocalypse",
        "episodes_validated": episodes,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall_validation_status": "PASS",
        "grounding_score": 1.0,
        "protagonist_consistency_score": 1.0,
        "errors": [],
        "stages": {}
    }

    errors: List[str] = []

    # =========================================================================
    # 1. STAGE 5 V5.3 PROTAGONIST CONTINUITY VALIDATION
    # =========================================================================
    print("\n[STAGE 5 V5.3] Validating Protagonist Continuity & Retention Hooks...")
    stage5_results = {}
    protagonist_mentions_total = 0
    total_segments_all = 0
    episodes_with_early_mc = 0

    for ep in episodes:
        ep_dir = os.path.join(base_dir, f"episode_{ep}")
        recap_path = os.path.join(ep_dir, "recap.json")
        narration_path = os.path.join(ep_dir, "narration.txt")
        srt_path = os.path.join(ep_dir, "transcript.srt")
        video_path = os.path.join(ep_dir, "video.mp4")

        files_ok = {
            "recap_json": os.path.exists(recap_path),
            "narration_txt": os.path.exists(narration_path),
            "transcript_srt": os.path.exists(srt_path),
            "video_mp4": os.path.exists(video_path),
        }

        if not all(files_ok.values()):
            err = f"Episode {ep}: Missing output files: {[k for k, v in files_ok.items() if not v]}"
            errors.append(err)
            stage5_results[f"episode_{ep}"] = {"status": "FAIL", "error": err, "files": files_ok}
            continue

        with open(recap_path, "r", encoding="utf-8") as f:
            recap_data = json.load(f)

        cues = parse_srt(srt_path)
        total_segments = len(recap_data)
        total_segments_all += total_segments

        all_text = " ".join(seg.get("speech", "") for seg in recap_data)
        tae_count = len(re.findall(r"\bTae\b", all_text))
        protagonist_mentions_total += tae_count

        # Check placeholder contamination
        placeholder_matches = re.findall(r"\b(Paran|\[MC\]|\[Protagonist\]|\(MC\))\b", all_text, re.IGNORECASE)
        if placeholder_matches:
            err = f"Episode {ep}: Found hallucinated placeholders {placeholder_matches}"
            errors.append(err)

        # First appearance calculation
        first_mc_sec = None
        first_mc_seg = None
        for idx, seg in enumerate(recap_data):
            speech = seg.get("speech", "")
            if "Tae" in speech or (idx == 0 and any(w in speech.lower() for w in ["tae", "his ", "he "])):
                first_mc_seg = idx + 1
                first_mc_sec = cues[idx]["start_sec"] if idx < len(cues) else 0.0
                break

        if first_mc_sec is not None and first_mc_sec <= 15.0:
            episodes_with_early_mc += 1

        opening_line = recap_data[0].get("speech", "") if recap_data else ""
        closing_line = recap_data[-1].get("speech", "") if recap_data else ""

        ep_status = "PASS" if (tae_count > 0 and len(placeholder_matches) == 0) else "FAIL"
        if ep_status == "FAIL":
            errors.append(f"Episode {ep}: Protagonist check failed (Tae mentions={tae_count})")

        stage5_results[f"episode_{ep}"] = {
            "episode": ep,
            "status": ep_status,
            "total_segments": total_segments,
            "protagonist_detected": tae_count > 0,
            "protagonist_name": "Tae",
            "protagonist_mentions_count": tae_count,
            "first_appearance_sec": first_mc_sec,
            "first_appearance_segment": first_mc_seg,
            "opening_line": opening_line[:120] + "...",
            "closing_cliffhanger": closing_line[:120] + "...",
            "placeholder_violations": len(placeholder_matches),
            "video_size_mb": round(os.path.getsize(video_path) / (1024 * 1024), 2),
        }
        print(f"  • Episode {ep}: Status={ep_status} | Segments={total_segments} | MC First Appearance={first_mc_sec}s | Tae Mentions={tae_count}")

    stage5_score = round(episodes_with_early_mc / len(episodes), 3) if episodes else 0.0
    stage5_status = "PASS" if all(r.get("status") == "PASS" for r in stage5_results.values()) else "FAIL"

    validation_report["stages"]["stage_5_protagonist_continuity"] = {
        "status": stage5_status,
        "protagonist_consistency_score": stage5_score,
        "total_segments_analyzed": total_segments_all,
        "total_protagonist_mentions": protagonist_mentions_total,
        "episodes": stage5_results,
    }

    # =========================================================================
    # 2. STORYMEMORY CONSISTENCY VALIDATION
    # =========================================================================
    print("\n[STORYMEMORY] Validating Cross-Episode Memory Consistency...")
    memory_manager = StoryMemory.load(base_dir, comic_title="Zombie Revelation: 82-08", language="en")
    
    # Check Protagonist Name & Archetype in memory or fact graph
    fact_graph = StoryFactGraph(
        comic_title="Zombie Revelation: 82-08",
        archetype="zombie_apocalypse",
        download_dir=base_dir,
        from_ep=6,
        to_ep=10,
        story_memory={"protagonist_name": "Tae"},
    ).build()

    total_facts = len(fact_graph._facts)
    character_facts = [f for f in fact_graph._facts if "Tae" in f.canonical_text or f.type == "character_action"]
    
    memory_status = "PASS" if (total_facts > 0 and len(character_facts) > 0) else "FAIL"
    memory_score = 1.0 if memory_status == "PASS" else 0.0

    validation_report["stages"]["story_memory_consistency"] = {
        "status": memory_status,
        "memory_consistency_score": memory_score,
        "protagonist_locked_name": "Tae",
        "archetype": "zombie_apocalypse",
        "total_grounded_facts_ep6_10": total_facts,
        "protagonist_grounded_facts": len(character_facts),
        "fact_graph_quality_summary": fact_graph.provenance_summary(),
    }
    print(f"  • Memory Consistency: Status={memory_status} | Grounded Facts={total_facts} | Protagonist Actions={len(character_facts)}")

    # =========================================================================
    # 3. STAGE 11 TIMELINE GENERATION (Episodes 6-10)
    # =========================================================================
    print("\n[STAGE 11 TIMELINE] Generating Multi-Episode Timeline Segments...")
    stage11_timeline_segments = []
    cumulative_time = 0.0
    episodes_timeline = {}

    for ep in episodes:
        ep_dir = os.path.join(base_dir, f"episode_{ep}")
        srt_path = os.path.join(ep_dir, "transcript.srt")
        video_path = os.path.join(ep_dir, "video.mp4")
        recap_path = os.path.join(ep_dir, "recap.json")

        cues = parse_srt(srt_path)
        with open(recap_path, "r", encoding="utf-8") as f:
            recap_data = json.load(f)

        ep_duration = cues[-1]["end_sec"] if cues else 0.0
        start_ts = format_timestamp(cumulative_time)

        ep_timeline_entry = {
            "episode": ep,
            "start_timestamp": start_ts,
            "start_seconds": round(cumulative_time, 2),
            "duration_seconds": round(ep_duration, 2),
            "total_scenes": len(cues),
            "video_path": video_path,
            "scenes": cues,
        }
        episodes_timeline[f"episode_{ep}"] = ep_timeline_entry

        stage11_timeline_segments.append({
            "episode": ep,
            "start_episode": ep,
            "end_episode": ep,
            "episode_range": f"{ep}",
            "timestamp": start_ts,
            "title": f"Episode {ep}",
            "start_seconds": round(cumulative_time, 2),
            "duration_seconds": round(ep_duration, 2),
        })

        cumulative_time += ep_duration

    stage11_status = "PASS" if len(stage11_timeline_segments) == 5 else "FAIL"
    validation_report["stages"]["stage_11_timeline_generation"] = {
        "status": stage11_status,
        "total_episodes": len(episodes),
        "total_duration_seconds": round(cumulative_time, 2),
        "formatted_total_duration": format_timestamp(cumulative_time),
        "timeline_milestones": stage11_timeline_segments,
    }
    print(f"  • Stage 11 Timeline: Status={stage11_status} | Total Duration={format_timestamp(cumulative_time)} ({cumulative_time:.1f}s)")

    # =========================================================================
    # 4. STAGE 12 CHAPTER GROUNDING V1 VALIDATION
    # =========================================================================
    print("\n[STAGE 12 CHAPTER GROUNDING V1] Validating Strict Chapter Grounding...")
    grounded_chapters = build_narrative_story_chapters(
        chapters=stage11_timeline_segments,
        download_dir=base_dir,
        comic_title="Zombie Revelation: 82-08",
        archetype="zombie_apocalypse",
        from_ep=6,
        to_ep=10,
    )

    evidence_index = EvidenceIndex(
        comic_title="Zombie Revelation: 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae"},
        download_dir=base_dir,
        from_ep=6,
        to_ep=10,
    )

    concepts = _build_resource_contrast_concepts(
        "Zombie Revelation: 82-08", "zombie_apocalypse", "Tae", {"disaster": "Zombie Outbreak"}, evidence_index
    )

    packaging_audit = validate_packaging_consistency(
        title="When The Outbreak Breaches Sector 6, Tae Holds The Defensive Line | Manhwa Recap",
        thumbnail_concepts=concepts,
        description="When the outbreak breaches sector 6, Tae holds the defensive line.\nOriginal scripted narration.",
        narrative_chapters=grounded_chapters,
        tags=["zombie apocalypse", "manhwa recap", "survival action", "apocalypse manhwa"],
        archetype="zombie_apocalypse",
        evidence_index=evidence_index,
    )

    chapter_audit = packaging_audit.get("chapter_audit", [])
    all_chapters_grounded = len(chapter_audit) > 0 and all(c.get("grounded", False) for c in chapter_audit)
    chapter_grounding_score = 1.0 if all_chapters_grounded else 0.0
    stage12_chapter_status = "PASS" if (all_chapters_grounded and packaging_audit["checks"].get("chapters_grounded", False)) else "FAIL"

    validation_report["stages"]["stage_12_chapter_grounding_v1"] = {
        "status": stage12_chapter_status,
        "grounding_score": chapter_grounding_score,
        "total_chapters": len(grounded_chapters),
        "chapter_audit": chapter_audit,
        "checks": packaging_audit["checks"],
        "warnings": packaging_audit["warnings"],
    }
    print(f"  • Stage 12 Chapter Grounding: Status={stage12_chapter_status} | Grounding Score={chapter_grounding_score} | Chapters={len(chapter_audit)}")

    # =========================================================================
    # 5. PREPUBLISH AUDIT
    # =========================================================================
    print("\n[STAGE 12 PREPUBLISH AUDIT] Executing Full YouTube Metadata & Compliance Audit...")
    full_meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation: 82-08",
        from_ep=6,
        to_ep=10,
        chapters=stage11_timeline_segments,
        story_memory={"protagonist_name": "Tae"},
        download_dir=base_dir,
    )

    prepublish_audit = full_meta["prepublish_audit"]
    prepublish_status = "PASS" if prepublish_audit.get("passed", False) else "FAIL"

    validation_report["stages"]["stage_12_prepublish_audit"] = {
        "status": prepublish_status,
        "primary_title": full_meta["title"],
        "title_length_chars": prepublish_audit.get("title_length_chars"),
        "description_bytes": prepublish_audit.get("description_utf8_bytes"),
        "tag_count": prepublish_audit.get("tag_count"),
        "first_chapter_is_zero": prepublish_audit.get("first_chapter_is_zero"),
        "chapters_grounded": prepublish_audit.get("chapters_grounded"),
        "packaging_consistent": full_meta["packaging_audit"].get("is_consistent"),
        "ypp_originality_passed": prepublish_audit.get("ypp_originality_statement_present"),
        "unsupported_claims": prepublish_audit.get("unsupported_claims"),
        "candidate_rejections": prepublish_audit.get("candidate_rejections"),
        "prepublish_passed": prepublish_audit.get("passed"),
    }
    print(f"  • Prepublish Audit: Status={prepublish_status} | Overall Passed={prepublish_audit.get('passed')}")

    # =========================================================================
    # OVERALL AGGREGATION & EXPORT
    # =========================================================================
    all_stages_pass = all(s.get("status") == "PASS" for s in validation_report["stages"].values())
    validation_report["overall_validation_status"] = "PASS" if (all_stages_pass and len(errors) == 0) else "FAIL"
    validation_report["errors"] = errors
    validation_report["grounding_score"] = chapter_grounding_score
    validation_report["protagonist_consistency_score"] = stage5_score

    # Export to root and downloads output
    export_root = os.path.join(PROJECT_ROOT, "production_validation_ep6_ep10.json")
    export_dl = os.path.join(base_dir, "output", "production_validation_ep6_ep10.json")

    with open(export_root, "w", encoding="utf-8") as f:
        json.dump(validation_report, f, indent=2, ensure_ascii=False)
    
    os.makedirs(os.path.dirname(export_dl), exist_ok=True)
    with open(export_dl, "w", encoding="utf-8") as f:
        json.dump(validation_report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"  FINAL RESULT: {validation_report['overall_validation_status']}")
    print(f"  Exported: {export_root}")
    print(f"  Exported: {export_dl}")
    print("=" * 80)

    return validation_report


if __name__ == "__main__":
    run_production_validation()
