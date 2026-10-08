#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
CapCut Draft Builder (Python Engine) - High Compatibility Edition
=============================================================================
Tự động hóa tạo Project Draft cho CapCut PC (Windows & macOS).
Xuất thẳng timeline video, ảnh, lồng tiếng (Voiceover), nhạc nền (BGM),
hiệu ứng phóng to Ken Burns tự động, và đăng ký trực tiếp vào trang chủ CapCut PC.

Author: GiangDA881 (Enhanced for CapCut 9.5+ Compatibility)
License: MIT
=============================================================================
"""

import os
import sys
import json
import uuid
import time
import shutil
import platform
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

# Đảm bảo UTF-8 an toàn trên Windows Console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Xác định đường dẫn thư mục lưu trữ Draft của CapCut PC
def get_default_capcut_root() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    elif system == "Darwin": # macOS
        return Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    else:
        return Path.home() / ".capcut" / "drafts"

# Khử triệt để lỗi đường dẫn Windows (prefix \\?\ hoặc //?/) làm CapCut crash/không nhận file
def sanitize_path(p: Union[str, Path]) -> str:
    path_str = os.path.abspath(str(p))
    path_str = path_str.replace("//?/", "").replace("\\\\?\\", "").replace("\\", "/")
    return path_str

def get_ffmpeg_binary() -> Optional[str]:
    """Tìm binary ffmpeg từ .venv, imageio_ffmpeg hoặc PATH hệ thống."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    venv_ffmpeg = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "ffmpeg.exe"
    if venv_ffmpeg.exists():
        return str(venv_ffmpeg)

    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return which_ffmpeg

    return None

def get_media_duration_us(file_path: Union[str, Path]) -> int:
    """Đo thời lượng video/audio chính xác bằng micro-giây (us) qua ffmpeg hoặc ffprobe."""
    fp = Path(file_path)
    if not fp.exists():
        return 0

    if shutil.which("ffprobe"):
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(fp)
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode == 0 and res.stdout.strip():
                return int(round(float(res.stdout.strip()) * 1_000_000))
        except Exception:
            pass

    ffmpeg_exe = get_ffmpeg_binary()
    if ffmpeg_exe:
        cmd = [ffmpeg_exe, "-i", str(fp)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr)
            if match:
                hours = float(match.group(1))
                minutes = float(match.group(2))
                seconds = float(match.group(3))
                total_sec = hours * 3600 + minutes * 60 + seconds
                return int(round(total_sec * 1_000_000))
        except Exception:
            pass

    return 0

def create_capcut_draft(
    project_name: str,
    video_clips: List[Dict[str, Any]],
    voiceover_tracks: Optional[List[Dict[str, Any]]] = None,
    bgm_tracks: Optional[List[Dict[str, Any]]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    register_to_capcut: bool = True,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    custom_draft_id: Optional[str] = None,
    cover_image_path: Optional[Union[str, Path]] = None
) -> Path:
    """
    Tạo cấu trúc Project Draft hoàn chỉnh cho CapCut PC tương thích 100% với CapCut 9.5+.
    """
    capcut_root = get_default_capcut_root()
    if output_dir:
        draft_dir = Path(os.path.abspath(str(output_dir)))
    else:
        draft_dir = capcut_root / project_name

    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_id = custom_draft_id or str(uuid.uuid4()).upper()

    materials_videos = []
    materials_audios = []
    materials_speeds = []
    materials_canvases = []
    materials_sound_channel = []

    now_ts = int(time.time() * 1_000_000)
    now_sec = int(time.time())

    # Danh sách materials metadata cho draft_meta_info.json
    meta_materials_value = []

    # -------------------------------------------------------------------------
    # 1. Xử lý Track Video / Photo
    # -------------------------------------------------------------------------
    video_segments = []
    cur_v_time_us = 0

    for idx, v in enumerate(video_clips):
        v_path_raw = Path(v["path"])
        v_path = sanitize_path(v_path_raw)
        is_video = v_path_raw.suffix.lower() in [".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".ts"]

        if "duration_us" in v:
            v_dur_us = int(v["duration_us"])
        elif "duration_sec" in v:
            v_dur_us = int(round(float(v["duration_sec"]) * 1_000_000))
        elif is_video:
            v_dur_us = get_media_duration_us(v_path_raw)
            if v_dur_us <= 0:
                v_dur_us = 5_000_000
        else:
            v_dur_us = 5_000_000

        mat_id = str(uuid.uuid4()).upper()
        speed_id = str(uuid.uuid4()).upper()
        canvas_id = str(uuid.uuid4()).upper()
        seg_id = str(uuid.uuid4()).upper()

        mat_type = "video" if is_video else "photo"
        base_dur = v_dur_us if is_video else 10800000000

        materials_videos.append({
            "id": mat_id,
            "type": mat_type,
            "material_name": v_path_raw.name,
            "path": v_path,
            "duration": base_dur,
            "width": width,
            "height": height,
            "category_id": "",
            "category_name": "local"
        })
        materials_speeds.append({"id": speed_id, "speed": 1.0, "type": "speed"})
        materials_canvases.append({"id": canvas_id, "type": "canvas_color", "color": ""})

        meta_materials_value.append({
            "ai_group_type": "",
            "create_time": now_sec,
            "duration": v_dur_us,
            "enter_from": 0,
            "extra_info": v_path_raw.name,
            "file_Path": v_path,
            "height": height,
            "id": str(uuid.uuid4()),
            "import_time": now_sec,
            "import_time_ms": now_ts,
            "item_source": 1,
            "material_color_tag": "",
            "md5": "",
            "metetype": "video" if is_video else "photo",
            "roughcut_time_range": {"duration": v_dur_us, "start": 0},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0,
            "width": width
        })

        # Keyframe chuyển động Ken Burns
        use_ken_burns = v.get("ken_burns", False)
        common_keyframes = []

        if use_ken_burns:
            motion_mode = v.get("motion_mode", idx % 3)
            if motion_mode == 0:
                zoom_start, zoom_end = 1.0, float(v.get("zoom_end", 1.06))
            elif motion_mode == 1:
                zoom_start, zoom_end = float(v.get("zoom_end", 1.06)), 1.0
            else:
                zoom_start, zoom_end = 1.0, float(v.get("zoom_end", 1.04))

            kf_id_x = str(uuid.uuid4()).upper()
            kf_id_y = str(uuid.uuid4()).upper()
            common_keyframes = [
                {
                    "id": kf_id_x,
                    "keyframe_list": [
                        {
                            "curveType": "Line",
                            "graphID": "",
                            "id": str(uuid.uuid4()).upper(),
                            "left_control": {"x": 0.0, "y": 0.0},
                            "right_control": {"x": 0.0, "y": 0.0},
                            "time_offset": 0,
                            "values": [zoom_start]
                        },
                        {
                            "curveType": "Line",
                            "graphID": "",
                            "id": str(uuid.uuid4()).upper(),
                            "left_control": {"x": 0.0, "y": 0.0},
                            "right_control": {"x": 0.0, "y": 0.0},
                            "time_offset": v_dur_us,
                            "values": [zoom_end]
                        }
                    ],
                    "material_id": "",
                    "property_type": "KFTypeScaleX"
                },
                {
                    "id": kf_id_y,
                    "keyframe_list": [
                        {
                            "curveType": "Line",
                            "graphID": "",
                            "id": str(uuid.uuid4()).upper(),
                            "left_control": {"x": 0.0, "y": 0.0},
                            "right_control": {"x": 0.0, "y": 0.0},
                            "time_offset": 0,
                            "values": [zoom_start]
                        },
                        {
                            "curveType": "Line",
                            "graphID": "",
                            "id": str(uuid.uuid4()).upper(),
                            "left_control": {"x": 0.0, "y": 0.0},
                            "right_control": {"x": 0.0, "y": 0.0},
                            "time_offset": v_dur_us,
                            "values": [zoom_end]
                        }
                    ],
                    "material_id": "",
                    "property_type": "KFTypeScaleY"
                }
            ]

        default_vol = 1.0 if is_video else 0.0
        clip_vol = float(v.get("volume", default_vol))

        video_segments.append({
            "id": seg_id,
            "source_timerange": {"start": 0, "duration": v_dur_us},
            "target_timerange": {"start": cur_v_time_us, "duration": v_dur_us},
            "render_timerange": {"start": 0, "duration": 0},
            "desc": v.get("desc", f"Visual Shot {idx+1}"),
            "state": 0,
            "speed": 1.0,
            "is_loop": False,
            "is_tone_modify": False,
            "reverse": False,
            "intensifies_audio": False,
            "cartoon": False,
            "volume": clip_vol,
            "last_nonzero_volume": clip_vol,
            "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}, "rotation": 0.0},
            "uniform_scale": {"on": True, "value": 1.0},
            "material_id": mat_id,
            "extra_material_refs": [speed_id, canvas_id],
            "render_index": 0,
            "keyframe_refs": [],
            "enable_lut": False,
            "enable_adjust": False,
            "enable_hsl": False,
            "visible": True,
            "group_id": "",
            "enable_color_curves": True,
            "enable_hsl_curves": True,
            "track_render_index": 0,
            "hdr_settings": None,
            "hdr_vivid_settings": None,
            "enable_color_wheels": True,
            "track_attribute": 5,
            "is_placeholder": False,
            "template_id": "",
            "enable_smart_color_adjust": False,
            "template_scene": "default",
            "common_keyframes": common_keyframes,
            "caption_info": None,
            "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0, "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
            "enable_color_match_adjust": False,
            "enable_color_correct_adjust": False,
            "enable_adjust_mask": False,
            "raw_segment_id": "",
            "lyric_keyframes": None,
            "enable_video_mask": True,
            "digital_human_template_group_id": "",
            "color_correct_alg_result": "",
            "source": "segmentsourcenormal",
            "enable_mask_stroke": False,
            "enable_mask_shadow": False,
            "enable_color_adjust_pro": False,
            "segment_color_tag": ""
        })
        cur_v_time_us += v_dur_us

    # -------------------------------------------------------------------------
    # 2. Xử lý Track Voiceover
    # -------------------------------------------------------------------------
    voiceover_segments = []
    cur_vo_time_us = 0
    if voiceover_tracks:
        for idx, a in enumerate(voiceover_tracks):
            a_path_raw = Path(a["path"])
            a_path = sanitize_path(a_path_raw)
            if "duration_us" in a:
                a_dur_us = int(a["duration_us"])
            elif "duration_sec" in a:
                a_dur_us = int(round(float(a["duration_sec"]) * 1_000_000))
            else:
                a_dur_us = get_media_duration_us(a_path_raw)

            mat_id = str(uuid.uuid4()).upper()
            speed_id = str(uuid.uuid4()).upper()
            sound_id = str(uuid.uuid4()).upper()
            seg_id = str(uuid.uuid4()).upper()

            # CapCut 9.5 yêu cầu type: "extract_music" và check_flag: 1
            materials_audios.append({
                "id": mat_id,
                "unique_id": str(uuid.uuid4()).replace("-", ""),
                "type": "extract_music",
                "name": a_path_raw.name,
                "path": a_path,
                "duration": a_dur_us,
                "category_name": "local",
                "check_flag": 1,
                "wave_points": []
            })
            materials_speeds.append({"id": speed_id, "speed": 1.0, "type": "speed"})
            materials_sound_channel.append({
                "id": sound_id,
                "type": "none",
                "audio_channel_mapping": 0,
                "is_config_open": False
            })

            meta_materials_value.append({
                "ai_group_type": "",
                "create_time": now_sec,
                "duration": a_dur_us,
                "enter_from": 0,
                "extra_info": a_path_raw.name,
                "file_Path": a_path,
                "height": 0,
                "id": str(uuid.uuid4()),
                "import_time": now_sec,
                "import_time_ms": now_ts,
                "item_source": 1,
                "material_color_tag": "",
                "md5": "",
                "metetype": "music",
                "roughcut_time_range": {"duration": a_dur_us, "start": 0},
                "sub_time_range": {"duration": -1, "start": -1},
                "type": 0,
                "width": 0
            })

            vol = float(a.get("volume", 1.0))
            voiceover_segments.append({
                "id": seg_id,
                "source_timerange": {"start": 0, "duration": a_dur_us},
                "target_timerange": {"start": cur_vo_time_us, "duration": a_dur_us},
                "render_timerange": {"start": 0, "duration": 0},
                "desc": a.get("desc", f"Voiceover {idx+1}"),
                "state": 0,
                "speed": 1.0,
                "is_loop": False,
                "is_tone_modify": False,
                "reverse": False,
                "intensifies_audio": False,
                "cartoon": False,
                "volume": vol,
                "last_nonzero_volume": vol,
                "clip": None,
                "uniform_scale": None,
                "material_id": mat_id,
                "extra_material_refs": [speed_id, sound_id],
                "render_index": 0,
                "keyframe_refs": [],
                "enable_lut": False,
                "enable_adjust": False,
                "enable_hsl": False,
                "visible": True,
                "group_id": "",
                "enable_color_curves": True,
                "enable_hsl_curves": True,
                "track_render_index": 1,
                "hdr_settings": None,
                "hdr_vivid_settings": None,
                "enable_color_wheels": True,
                "track_attribute": 4,
                "is_placeholder": False,
                "template_id": "",
                "enable_smart_color_adjust": False,
                "template_scene": "default",
                "common_keyframes": [],
                "caption_info": None,
                "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0, "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
                "enable_color_match_adjust": False,
                "enable_color_correct_adjust": False,
                "enable_adjust_mask": False,
                "raw_segment_id": "",
                "lyric_keyframes": None,
                "enable_video_mask": True,
                "digital_human_template_group_id": "",
                "color_correct_alg_result": "",
                "source": "segmentsourcenormal",
                "enable_mask_stroke": False,
                "enable_mask_shadow": False,
                "enable_color_adjust_pro": False,
                "segment_color_tag": ""
            })
            cur_vo_time_us += a_dur_us

    # -------------------------------------------------------------------------
    # 3. Xử lý Track Background Music (BGM)
    # -------------------------------------------------------------------------
    bgm_segments = []
    cur_bgm_time_us = 0
    if bgm_tracks:
        for idx, b in enumerate(bgm_tracks):
            b_path_raw = Path(b["path"])
            b_path = sanitize_path(b_path_raw)
            if "duration_us" in b:
                b_dur_us = int(b["duration_us"])
            elif "duration_sec" in b:
                b_dur_us = int(round(float(b["duration_sec"]) * 1_000_000))
            else:
                b_dur_us = get_media_duration_us(b_path_raw)

            mat_id = str(uuid.uuid4()).upper()
            speed_id = str(uuid.uuid4()).upper()
            sound_id = str(uuid.uuid4()).upper()
            seg_id = str(uuid.uuid4()).upper()

            materials_audios.append({
                "id": mat_id,
                "unique_id": str(uuid.uuid4()).replace("-", ""),
                "type": "music",
                "name": b_path_raw.name,
                "path": b_path,
                "duration": b_dur_us,
                "category_name": "local",
                "check_flag": 1,
                "wave_points": []
            })
            materials_speeds.append({"id": speed_id, "speed": 1.0, "type": "speed"})
            materials_sound_channel.append({
                "id": sound_id,
                "type": "none",
                "audio_channel_mapping": 0,
                "is_config_open": False
            })

            meta_materials_value.append({
                "ai_group_type": "",
                "create_time": now_sec,
                "duration": b_dur_us,
                "enter_from": 0,
                "extra_info": b_path_raw.name,
                "file_Path": b_path,
                "height": 0,
                "id": str(uuid.uuid4()),
                "import_time": now_sec,
                "import_time_ms": now_ts,
                "item_source": 1,
                "material_color_tag": "",
                "md5": "",
                "metetype": "music",
                "roughcut_time_range": {"duration": b_dur_us, "start": 0},
                "sub_time_range": {"duration": -1, "start": -1},
                "type": 0,
                "width": 0
            })

            bgm_vol = float(b.get("volume", 0.15))
            bgm_segments.append({
                "id": seg_id,
                "source_timerange": {"start": 0, "duration": b_dur_us},
                "target_timerange": {"start": cur_bgm_time_us, "duration": b_dur_us},
                "render_timerange": {"start": 0, "duration": 0},
                "desc": b.get("desc", f"BGM Track {idx+1}"),
                "state": 0,
                "speed": 1.0,
                "is_loop": False,
                "is_tone_modify": False,
                "reverse": False,
                "intensifies_audio": False,
                "cartoon": False,
                "volume": bgm_vol,
                "last_nonzero_volume": bgm_vol,
                "clip": None,
                "uniform_scale": None,
                "material_id": mat_id,
                "extra_material_refs": [speed_id, sound_id],
                "render_index": 0,
                "keyframe_refs": [],
                "enable_lut": False,
                "enable_adjust": False,
                "enable_hsl": False,
                "visible": True,
                "group_id": "",
                "enable_color_curves": True,
                "enable_hsl_curves": True,
                "track_render_index": 2,
                "hdr_settings": None,
                "hdr_vivid_settings": None,
                "enable_color_wheels": True,
                "track_attribute": 0,
                "is_placeholder": False,
                "template_id": "",
                "enable_smart_color_adjust": False,
                "template_scene": "default",
                "common_keyframes": [],
                "caption_info": None,
                "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0, "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
                "enable_color_match_adjust": False,
                "enable_color_correct_adjust": False,
                "enable_adjust_mask": False,
                "raw_segment_id": "",
                "lyric_keyframes": None,
                "enable_video_mask": True,
                "digital_human_template_group_id": "",
                "color_correct_alg_result": "",
                "source": "segmentsourcenormal",
                "enable_mask_stroke": False,
                "enable_mask_shadow": False,
                "enable_color_adjust_pro": False,
                "segment_color_tag": ""
            })
            cur_bgm_time_us += b_dur_us

    total_duration_us = max(cur_v_time_us, cur_vo_time_us, cur_bgm_time_us)

    # -------------------------------------------------------------------------
    # 4. Lắp ráp Timeline Tracks
    # -------------------------------------------------------------------------
    tracks = [
        {"id": str(uuid.uuid4()).upper(), "type": "video", "attribute": 5, "flag": 0, "segments": video_segments}
    ]
    if voiceover_segments:
        tracks.append({
            "id": str(uuid.uuid4()).upper(),
            "type": "audio",
            "attribute": 4,
            "flag": 0,
            "name": "Voiceover",
            "is_default_name": True,
            "segments": voiceover_segments
        })
    if bgm_segments:
        tracks.append({
            "id": str(uuid.uuid4()).upper(),
            "type": "audio",
            "attribute": 0,
            "flag": 0,
            "name": "BGM",
            "is_default_name": True,
            "segments": bgm_segments
        })

    draft_content = {
        "id": draft_id,
        "name": project_name,
        "version": 360000,
        "new_version": "187.0.0",
        "duration": total_duration_us,
        "fps": fps,
        "canvas_config": {"width": width, "height": height, "ratio": "original"},
        "materials": {
            "videos": materials_videos,
            "audios": materials_audios,
            "speeds": materials_speeds,
            "canvases": materials_canvases,
            "sound_channel_mappings": materials_sound_channel,
            "flowers": [],
            "tail_leaders": [],
            "images": [],
            "texts": [],
            "effects": [],
            "stickers": [],
            "transitions": [],
            "audio_effects": [],
            "audio_fades": [],
            "beats": [],
            "material_animations": [],
            "placeholders": [],
            "placeholder_infos": [],
            "common_mask": [],
            "chromas": [],
            "text_templates": [],
            "realtime_denoises": [],
            "audio_pannings": [],
            "audio_pitch_shifts": [],
            "video_trackings": [],
            "hsl": [],
            "drafts": [],
            "color_curves": [],
            "hsl_curves": [],
            "primary_color_wheels": [],
            "log_color_wheels": [],
            "video_effects": [],
            "ai_text_effects": [],
            "audio_balances": [],
            "handwrites": [],
            "manual_deformations": [],
            "manual_beautys": [],
            "plugin_effects": [],
            "green_screens": [],
            "shapes": [],
            "material_colors": [],
            "digital_humans": [],
            "digital_human_model_dressing": [],
            "smart_crops": [],
            "ai_translates": [],
            "audio_track_indexes": [],
            "loudnesses": [],
            "vocal_beautifys": [],
            "vocal_separations": [],
            "smart_relights": [],
            "time_marks": [],
            "multi_language_refs": [],
            "video_shadows": [],
            "video_strokes": [],
            "video_radius": []
        },
        "keyframes": {
            "adjusts": [],
            "audios": [],
            "effects": [],
            "filters": [],
            "handwrites": [],
            "stickers": [],
            "texts": [],
            "videos": []
        },
        "keyframe_graph_list": [],
        "tracks": tracks
    }

    # -------------------------------------------------------------------------
    # 5. Ghi các file JSON tiêu chuẩn của CapCut PC
    # -------------------------------------------------------------------------
    content_json_str = json.dumps(draft_content, ensure_ascii=False, indent=2)
    (draft_dir / "draft_content.json").write_text(content_json_str, encoding="utf-8")
    (draft_dir / "draft_content.json.bak").write_text(content_json_str, encoding="utf-8")
    (draft_dir / "draft_info.json").write_text(content_json_str, encoding="utf-8")
    (draft_dir / "template-2.tmp").write_text(content_json_str, encoding="utf-8")

    (draft_dir / "draft.extra").write_bytes(b"i\x04\x02\x04i\x04\x02\x04ei\x04\x02\x04\x01\x02\x01{}\x01e\x00")
    (draft_dir / "draft_virtual_store.json").write_text('{"draft_materials":[],"draft_virtual_store":[]}', encoding="utf-8")

    timeline_layout = {
        "dockItems": [
            {
                "dockIndex": 0,
                "ratio": 1,
                "timelineIds": [str(uuid.uuid4()).upper()],
                "timelineNames": ["Timeline 01"]
            }
        ],
        "layoutOrientation": 1
    }
    (draft_dir / "timeline_layout.json").write_text(json.dumps(timeline_layout), encoding="utf-8")

    settings_content = (
        "[General]\n"
        f"draft_create_time={now_sec}\n"
        f"draft_last_edit_time={now_sec}\n"
        "real_edit_seconds=14500\n"
        "real_edit_keys=185\n"
        "cloud_last_modify_platform=windows\n"
    )
    (draft_dir / "draft_settings").write_text(settings_content, encoding="utf-8")

    # Tạo draft_cover.jpg từ cover chỉ định hoặc clip đầu tiên
    cover_file = draft_dir / "draft_cover.jpg"
    selected_cover = cover_image_path or (video_clips[0]["path"] if video_clips else None)
    if selected_cover and Path(selected_cover).exists():
        sc_path = Path(selected_cover)
        if sc_path.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
            try:
                from PIL import Image
                with Image.open(sc_path) as im:
                    im.convert("RGB").save(cover_file, "JPEG", quality=92)
            except Exception:
                try:
                    shutil.copy2(sc_path, cover_file)
                except Exception:
                    pass

    # Meta Info với đầy đủ draft_materials
    draft_materials = [
        {"type": 0, "value": meta_materials_value},
        {"type": 1, "value": []},
        {"type": 2, "value": []},
        {"type": 3, "value": []},
        {"type": 6, "value": []},
        {"type": 7, "value": []},
        {"type": 8, "value": []},
        {"type": 18, "value": []}
    ]

    meta_info = {
        "cloud_draft_cover": False,
        "cloud_draft_sync": False,
        "draft_cover": "draft_cover.jpg",
        "draft_fold_path": sanitize_path(draft_dir),
        "draft_id": draft_id,
        "draft_materials": draft_materials,
        "draft_name": project_name,
        "draft_root_path": sanitize_path(capcut_root),
        "streaming_edit_draft_ready": True,
        "tm_draft_create": now_ts,
        "tm_draft_modified": now_ts,
        "tm_duration": total_duration_us
    }
    (draft_dir / "draft_meta_info.json").write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")

    # -------------------------------------------------------------------------
    # 6. Đăng ký vào root_meta_info.json (Hiển thị ngay trên CapCut PC)
    # -------------------------------------------------------------------------
    root_meta_file = capcut_root / "root_meta_info.json"
    if register_to_capcut and root_meta_file.exists():
        try:
            root_data = json.loads(root_meta_file.read_text(encoding="utf-8"))
            root_data["all_draft_store"] = [
                d for d in root_data.get("all_draft_store", [])
                if d.get("draft_name") != project_name and d.get("draft_id") != draft_id
            ]
            root_data["all_draft_store"].insert(0, {
                "draft_id": draft_id,
                "draft_name": project_name,
                "draft_fold_path": sanitize_path(draft_dir),
                "draft_json_file": sanitize_path(draft_dir / "draft_content.json"),
                "draft_cover": sanitize_path(cover_file),
                "draft_root_path": sanitize_path(capcut_root),
                "tm_draft_create": now_ts,
                "tm_draft_modified": now_ts,
                "tm_duration": total_duration_us,
                "draft_new_version": "187.0.0",
                "streaming_edit_draft_ready": True
            })
            root_meta_file.write_text(json.dumps(root_data, ensure_ascii=False), encoding="utf-8")
            print(f"[CapCut] Đã đăng ký '{project_name}' thành công vào CapCut Projects!")
        except Exception as e:
            print(f"[Warning] Không thể ghi root_meta_info.json: {e}")

    print(f"\n[SUCCESS] CapCut Draft đã được tạo thành công tại:")
    print(f"   -> {draft_dir}")
    print(f"   * Tổng thời lượng: {total_duration_us/1_000_000:.2f}s ({total_duration_us/60_000_000:.1f} phút)")
    print(f"   * Số phân cảnh video/ảnh: {len(video_clips)}")
    print(f"   * Số đoạn thoại: {len(voiceover_tracks or [])}")
    print(f"   * Số đoạn BGM: {len(bgm_tracks or [])}")
    return draft_dir


if __name__ == "__main__":
    print("CapCut Draft Builder Engine v2.0.0 (CapCut 9.5+ Ready)")
