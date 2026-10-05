"""
YouTube upload-kit builder shared by Stage 12 and the regeneration scripts.

Why: regenerate_youtube_kit.py and generate_all_seo_packages.py called generate_youtube_metadata
without LLM drafts, registry or premise pitch, hard-coded one comic and wrote fake intro data and a
"VALIDATED_100_PERCENT_GROUNDED" label — their kits always failed the pre-publish gate. Everything
that turns a finished download folder into a kit now lives here, so the pipeline and the scripts
produce the same result.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LogFn = Callable[[str, str], Awaitable[None]]
TextLlmCall = Callable[[str], Awaitable[Optional[str]]]

DEFAULT_NINEROUTER_URL = "http://localhost:20128/v1"


async def _print_log(message: str, level: str = "info") -> None:
    print(f"[{level.upper()}] {message}", flush=True)


def make_text_llm_call(ninerouter_api_key: Optional[str] = None) -> TextLlmCall:
    """Text-only Gemini call through the same 9Router configuration as Stage 5."""
    async def call(prompt: str) -> Optional[str]:
        from app import load_config
        from gemini_api_engine import get_gemini_api_engine
        cfg = load_config()
        engine = get_gemini_api_engine(
            base_url=(cfg.get("ninerouter_url") or "").strip() or DEFAULT_NINEROUTER_URL,
            api_key=ninerouter_api_key or None,
        )
        text, _model = await engine.generate_content(prompt=prompt, temperature=0.9, max_output_tokens=2048, timeout=90)
        return text
    return call


def load_story_memory(download_dir: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(download_dir, "story_memory.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        logger.warning("Unreadable story_memory.json in %s: %s", download_dir, err)
        return None


# =============================================================================
# Kit generation (Stage 12 core)
# =============================================================================

# LLM drafts recorded in output/metadata.json. A re-run offers them to the validators first, so an
# approved video and kit do not change on every run (Veteran 1-33 got a new pitch, outro and chapter
# names on each Stage 11/12 re-run). Payload regenerate_drafts=True drafts everything anew.
DRAFT_KEYS = ("premise_pitch", "llm_title_hooks", "outro", "llm_chapter_options", "llm_overlay_options")


def load_previous_drafts(download_dir: str) -> Dict[str, Any]:
    path = os.path.join(download_dir or "", "output", "metadata.json")
    if not download_dir or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        logger.warning("Unreadable %s, drafting anew: %s", path, err)
        return {}
    return {k: data[k] for k in DRAFT_KEYS if isinstance(data, dict) and data.get(k)}


def overlay_options_from_json(raw: Any) -> Dict[str, List[Tuple[str, str]]]:
    """metadata.json stores (main, sub) pairs as lists."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): [(str(p[0]), str(p[1])) for p in v if isinstance(p, (list, tuple)) and len(p) == 2]
        for k, v in raw.items() if isinstance(v, list)
    }


def resolve_story_status(download_dir: str, to_ep: int, artifacts: Dict[str, Any]) -> str:
    """'finished' only when the comic is completed and the video reaches its last episode (FINALE)."""
    from outro_engine import OutroType, classify_outro
    from series_status import load_release_status

    status = load_release_status(download_dir, artifacts)
    if status.state == "unknown":
        return "unknown"
    return "finished" if classify_outro(status, to_ep) == OutroType.FINALE else "not_finished"


def _count_passed(checks: List[Dict[str, Any]], source: str) -> Tuple[int, int]:
    mine = [c for c in checks if c.get("source") == source]
    return sum(1 for c in mine if c.get("passed")), len(mine)


async def generate_youtube_kit(
    *,
    download_dir: str,
    comic_title: str,
    from_ep: int,
    to_ep: int,
    chapters: Optional[List[Dict[str, Any]]],
    payload: Dict[str, Any],
    artifacts: Dict[str, Any],
    llm_call: Optional[TextLlmCall],
    log: LogFn = _print_log,
) -> Dict[str, Any]:
    """
    Drafts titles / chapter names / overlay text with the LLM (when `llm_call` is given), builds the
    kit through generate_youtube_metadata, records the shipped title in the registry and logs the
    gate verdict. Returns the youtube_metadata dict. `artifacts` may carry Stage 11's
    llm_title_hooks and premise_pitch; it is updated with llm_title_hooks when drafted here.
    """
    from chapter_engine import build_arc_inputs, generate_llm_chapter_options
    from series_bible import load_bible
    from thumbnail_text import OVERLAY_CONCEPTS, fits_scene, generate_llm_overlay_options
    from title_engine import (
        DEFAULT_REGISTRY_PATH, TitleRegistry, build_hook_sheet, generate_llm_hooks, load_narration_by_episode,
    )
    from youtube_metadata import (
        generate_youtube_metadata, plan_chapter_arcs, preview_primary_title, preview_thumbnail_concepts,
    )

    story_memory = load_story_memory(download_dir)
    language = payload.get("language", "en")
    registry = TitleRegistry.load(payload.get("title_registry_path") or DEFAULT_REGISTRY_PATH)
    story_status = resolve_story_status(download_dir, to_ep, artifacts)
    hook_sheet = build_hook_sheet(
        comic_title, download_dir, from_ep, to_ep,
        story_memory=story_memory, bible=load_bible(download_dir), language=language,
    )

    # Reuse Stage 11's drafts: the premise pitch was written for the title they produce.
    llm_hooks = artifacts.get("llm_title_hooks")
    if llm_hooks is None:
        llm_hooks = await generate_llm_hooks(hook_sheet, llm_call) if llm_call else []
        artifacts["llm_title_hooks"] = llm_hooks
    if hook_sheet.has_story and not llm_hooks:
        await log("Title Engine: không có title từ LLM, dùng template dự phòng (vẫn qua bộ kiểm tra).", "warning")

    # Earlier drafts (artifacts, from metadata.json) go through the same validators as fresh ones;
    # they are only reused while they still cover every current arc / thumbnail concept.
    arcs = build_arc_inputs(
        plan_chapter_arcs(chapters, comic_title, story_memory, download_dir, from_ep, to_ep),
        load_narration_by_episode(download_dir, from_ep, to_ep),
        story_memory,
    )
    llm_chapter_options: Dict[str, List[str]] = artifacts.get("llm_chapter_options") or {}
    if arcs and not {a.key for a in arcs} <= set(llm_chapter_options):
        llm_chapter_options = {}
    if llm_chapter_options:
        await log("Chapter Engine: dùng lại tên chapter của lần chạy trước (vẫn qua bộ kiểm tra).", "info")
    elif llm_call:
        llm_chapter_options = await generate_llm_chapter_options(arcs, hook_sheet.character_names, llm_call)
        if arcs and not llm_chapter_options:
            await log("Chapter Engine: LLM không trả về tên chapter, dùng tên Stage 11 / 'Part N' (vẫn qua bộ kiểm tra).", "warning")
    artifacts["llm_chapter_options"] = llm_chapter_options

    top_concepts = preview_thumbnail_concepts(comic_title, from_ep, to_ep, story_memory, download_dir)
    llm_overlay_options = overlay_options_from_json(artifacts.get("llm_overlay_options"))
    if not all(
        any(fits_scene(main, sub, c) for main, sub in llm_overlay_options.get(str(c.get("id")), []))
        for c in top_concepts[:OVERLAY_CONCEPTS]
    ):
        llm_overlay_options = {}
    if llm_overlay_options:
        await log("Thumbnail: dùng lại chữ overlay của lần chạy trước (vẫn qua bộ kiểm tra).", "info")
    elif llm_call:
        # Overlay text must complement the shipped title: reuse the pitch's title or preview it.
        overlay_title = (artifacts.get("premise_pitch") or {}).get("title")
        if not overlay_title:
            overlay_title = preview_primary_title(
                comic_title, from_ep, to_ep, story_memory, download_dir,
                llm_title_candidates=llm_hooks,
                registry_titles=registry.titles_for_dedup(comic_title),
                language=language,
            )["primary_title"]
        llm_overlay_options = await generate_llm_overlay_options(hook_sheet, overlay_title, top_concepts, llm_call)
    artifacts["llm_overlay_options"] = llm_overlay_options

    yt_meta = generate_youtube_metadata(
        comic_title,
        from_ep,
        to_ep,
        chapters=chapters,
        story_memory=story_memory,
        download_dir=download_dir,
        llm_title_candidates=llm_hooks,
        registry_titles=registry.titles_for_dedup(comic_title),
        language=language,
        llm_chapter_options=llm_chapter_options,
        registry_chapter_names=registry.chapter_names_for_dedup(comic_title),
        premise_pitch=artifacts.get("premise_pitch"),
        llm_overlay_options=llm_overlay_options,
        # Navigation links only when the user supplies real URLs (never synthesized).
        playlist_url=payload.get("playlist_url"),
        previous_part_url=payload.get("previous_part_url"),
        next_part_url=payload.get("next_part_url"),
        outro=artifacts.get("outro"),
        story_status=story_status,
    )

    title_engine_audit = yt_meta["prepublish_audit"]["claim_audit"].get("title_engine", {})
    checks = title_engine_audit.get("checks", [])
    llm_ok, llm_total = _count_passed(checks, "llm")
    tpl_ok, tpl_total = _count_passed(checks, "template")
    await log(
        f"Title Engine: {title_engine_audit.get('status')} — title LLM đạt {llm_ok}/{llm_total}, "
        f"template đạt {tpl_ok}/{tpl_total}.",
        "info" if title_engine_audit.get("status") == "validated" else "warning",
    )
    # Only grounded titles enter the registry; no narration means nothing was verified.
    if hook_sheet.has_story and title_engine_audit.get("status") == "validated":
        shipped_chapters = [
            ch["theme"] for ch in yt_meta.get("narrative_chapters", []) if ch.get("naming_source") != "fallback"
        ]
        registry.record_kit_title(yt_meta["title"], comic_title, from_ep, to_ep, chapters=shipped_chapters)
        registry.save()

    gate = yt_meta["prepublish_audit"].get("gate", {})
    blocking = [c["id"] for c in gate.get("checks", []) if not c["passed"] and c["severity"] == "fail"]
    review = [c["id"] for c in gate.get("checks", []) if not c["passed"] and c["severity"] == "warn"]
    await log(
        f"Pre-publish gate: {gate.get('status')} — chặn: {', '.join(blocking) or 'không'}; "
        f"cần xem lại: {', '.join(review) or 'không'}.",
        {"PASS": "success", "WARN": "warning"}.get(gate.get("status"), "error"),
    )
    return yt_meta


def write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


KIT_FILENAME = "youtube_upload_kit.txt"
UPLOAD_DIRNAME = "upload"
UPLOAD_MANAGED_SUFFIXES = (".mp4", ".srt", ".txt")


def write_kit_text(output_dir: str, yt_meta: Dict[str, Any]) -> str:
    kit_path = os.path.join(output_dir, KIT_FILENAME)
    with open(kit_path, "w", encoding="utf-8") as f:
        f.write(yt_meta.get("formatted_kit", ""))
    return kit_path


def prepare_upload_folder(output_dir: str, folder_name: str, yt_meta: Dict[str, Any]) -> Dict[str, str]:
    """
    output/upload/: the final video and subtitles under the kit's SEO file names, plus the kit, ready
    to drag into YouTube Studio. Video/subtitles are hard links (no extra disk for a 1 GB video), copies
    when the filesystem refuses links. The internal names stay: UI links and re-runs rely on them.
    Returns {upload name: path}; {} when the final video is missing.
    """
    names = yt_meta.get("seo_filenames") or {}
    video_src = os.path.join(output_dir, f"{folder_name}.mp4")
    if not names.get("video_filename") or not os.path.isfile(video_src):
        return {}
    sources = {
        names["video_filename"]: video_src,
        names.get("srt_filename"): os.path.join(output_dir, f"{folder_name}.srt"),
        names.get("kit_filename"): os.path.join(output_dir, KIT_FILENAME),
    }
    sources = {name: path for name, path in sources.items() if name and os.path.isfile(path)}

    upload_dir = os.path.join(output_dir, UPLOAD_DIRNAME)
    os.makedirs(upload_dir, exist_ok=True)
    # Tool-managed folder: files of an earlier title or range would be uploaded by mistake.
    for name in os.listdir(upload_dir):
        if name.endswith(UPLOAD_MANAGED_SUFFIXES) and name not in sources:
            os.remove(os.path.join(upload_dir, name))

    placed: Dict[str, str] = {}
    for name, src in sources.items():
        dst = os.path.join(upload_dir, name)
        if os.path.exists(dst):
            os.remove(dst)  # always relink: a re-render replaces the source file
        if src.endswith(".txt"):
            shutil.copy2(src, dst)  # the kit is small and rewritten in place by later runs
        else:
            try:
                os.link(src, dst)
            except OSError as err:
                logger.warning("Hard link %s -> %s failed (%s); copying instead", src, dst, err)
                shutil.copy2(src, dst)
        placed[name] = dst
    return placed


# =============================================================================
# Regeneration from a finished download folder (scripts)
# =============================================================================

def episode_range(download_dir: str) -> Tuple[int, int]:
    eps = [
        int(d.split("_", 1)[1]) for d in os.listdir(download_dir)
        if d.startswith("episode_") and d.split("_", 1)[1].isdigit() and os.path.isdir(os.path.join(download_dir, d))
    ]
    if not eps:
        raise ValueError(f"No episode_* folders in {download_dir}")
    return min(eps), max(eps)


def resolve_comic_title(download_dir: str, story_memory: Optional[Dict[str, Any]]) -> str:
    from series_bible import load_bible
    bible = load_bible(download_dir)
    if bible and bible.series_title:
        return bible.series_title
    if story_memory and story_memory.get("comic_title"):
        return str(story_memory["comic_title"])
    folder = os.path.basename(os.path.normpath(download_dir))
    return re.sub(r"_\d+_\d+_[a-z]{2}_[0-9a-f]+$", "", folder).replace("_", " ").title()


def resolve_language(download_dir: str, story_memory: Optional[Dict[str, Any]]) -> str:
    if story_memory and story_memory.get("language"):
        return str(story_memory["language"])
    m = re.search(r"_([a-z]{2})_[0-9a-f]+$", os.path.basename(os.path.normpath(download_dir)))
    return m.group(1) if m else "en"


def chapters_from_episode_videos(download_dir: str, from_ep: int, to_ep: int) -> List[Dict[str, Any]]:
    """Per-episode timestamps from the rendered episode videos (same format as Stage 11)."""
    from app import find_ffmpeg
    from workflow_stages_2 import get_video_duration

    ffmpeg_exe = find_ffmpeg()
    chapters: List[Dict[str, Any]] = []
    elapsed = 0.0
    for ep in range(from_ep, to_ep + 1):
        video = os.path.join(download_dir, f"episode_{ep}", "video.mp4")
        if not os.path.exists(video):
            raise FileNotFoundError(f"Missing rendered video for episode {ep}: {video}")
        duration = get_video_duration(video, ffmpeg_exe)
        hrs, mins, secs = int(elapsed // 3600), int((elapsed % 3600) // 60), int(elapsed % 60)
        timestamp = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
        chapters.append({"episode": ep, "timestamp": timestamp, "title": f"Episode {ep}", "duration_seconds": duration})
        elapsed += duration
    return chapters


async def regenerate_kit(
    download_dir: str,
    use_llm: bool = True,
    registry_path: Optional[str] = None,
    playlist_url: Optional[str] = None,
    log: LogFn = _print_log,
    fresh_drafts: bool = False,
) -> Dict[str, Any]:
    """Rebuilds youtube_upload_kit.txt + metadata.json for a finished folder. Returns metadata.json content.
    Recorded chapter/overlay drafts are reused (and re-validated) unless `fresh_drafts`."""
    download_dir = os.path.abspath(download_dir)
    output_dir = os.path.join(download_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    story_memory = load_story_memory(download_dir)
    from_ep, to_ep = episode_range(download_dir)
    comic_title = resolve_comic_title(download_dir, story_memory)

    previous: Dict[str, Any] = {}
    metadata_path = os.path.join(output_dir, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            previous = json.load(f)
    # The pitch in the rendered video is whatever Stage 11 recorded; never invented here.
    pitch = previous.get("premise_pitch")
    # Same for the outro: its end-screen timestamp belongs to the rendered video.
    artifacts: Dict[str, Any] = {"premise_pitch": pitch, "outro": previous.get("outro")}
    # Reuse the recorded drafts so the kit keeps the title the rendered pitch promises. Older folders
    # have no drafts: the pitch's own title is then the only candidate (it is still re-validated).
    if previous.get("llm_title_hooks"):
        artifacts["llm_title_hooks"] = previous["llm_title_hooks"]
    elif pitch and pitch.get("prepended") and pitch.get("title"):
        from title_engine import strip_suffix
        artifacts["llm_title_hooks"] = [strip_suffix(pitch["title"])]
    if not fresh_drafts:
        for key in ("llm_chapter_options", "llm_overlay_options"):
            if previous.get(key):
                artifacts[key] = previous[key]
    payload: Dict[str, Any] = {"language": resolve_language(download_dir, story_memory)}
    if registry_path:
        payload["title_registry_path"] = registry_path
    if playlist_url:
        payload["playlist_url"] = playlist_url

    await log(f"Regenerating kit: {comic_title} (episodes {from_ep}-{to_ep}) in {download_dir}", "info")
    yt_meta = await generate_youtube_kit(
        download_dir=download_dir,
        comic_title=comic_title,
        from_ep=from_ep,
        to_ep=to_ep,
        chapters=chapters_from_episode_videos(download_dir, from_ep, to_ep),
        payload=payload,
        artifacts=artifacts,
        llm_call=make_text_llm_call() if use_llm else None,
        log=log,
    )
    # Keep the pipeline's own fields (comic_url, flash_forward_intro, progress) from the previous run.
    metadata = {
        **previous,
        "comic_title": comic_title,
        "from_episode": from_ep,
        "to_episode": to_ep,
        "generation_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "premise_pitch": artifacts.get("premise_pitch"),
        "llm_title_hooks": artifacts.get("llm_title_hooks"),
        "outro": artifacts.get("outro"),
        "llm_chapter_options": artifacts.get("llm_chapter_options"),
        "llm_overlay_options": artifacts.get("llm_overlay_options"),
        "youtube_metadata": yt_meta,
        "compliance_audit": yt_meta.get("compliance_flags"),
    }
    kit_path = write_kit_text(output_dir, yt_meta)
    write_json_atomic(metadata_path, metadata)
    await log(f"Wrote {kit_path} and {metadata_path} (gate: {yt_meta['prepublish_audit'].get('gate_status')}).", "success")
    placed = prepare_upload_folder(output_dir, os.path.basename(download_dir), yt_meta)
    if placed:
        await log(f"Upload folder: {os.path.join(output_dir, UPLOAD_DIRNAME)} ({', '.join(placed)})", "success")
    return metadata
