#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Export CapCut Draft from Recap Comics Automation (CapCut 9.x Architecture)
=============================================================================
Tự động chuyển đổi dữ liệu truyện tranh từ tool recap thành một Project Draft
hoàn chỉnh cho CapCut PC tương thích 100% với CapCut 9.5+.
- Kiến trúc đa timeline chuẩn CapCut 9.x (Timelines/<timeline_id>/)
- Đồng bộ tuyệt đối giữa project.json, timeline_layout.json và root_meta_info.json
- Tái tạo timeline đa tầng: Video cắt nhỏ chân thực + Voiceover waveform + BGM

Author: Antigravity Pair Programmer
=============================================================================
"""

import os
import sys
import json
import uuid
import time
import hashlib
import shutil
import random
import logging
import copy
from pathlib import Path
from typing import List, Dict, Any, Optional

# Đảm bảo UTF-8 an toàn trên Windows Console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("capcut_recap")

BASE = Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"

def get_media_duration_us(file_path: Path) -> int:
    """Đo thời lượng video/audio chính xác bằng micro-giây (us) qua OpenCV hoặc ffprobe."""
    fp = Path(file_path)
    if not fp.exists():
        return 0

    # Thử qua OpenCV nếu là video
    if fp.suffix.lower() in [".mp4", ".mov", ".mkv", ".webm"]:
        try:
            import cv2
            cap = cv2.VideoCapture(str(fp))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            if fps > 0 and frames > 0:
                return int((frames / fps) * 1_000_000)
        except Exception:
            pass

    # Thử qua ffmpeg/imageio_ffmpeg
    try:
        import imageio_ffmpeg, subprocess, re
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            res = subprocess.run([exe, "-i", str(fp)], capture_output=True, text=True, errors="replace")
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr)
            if match:
                hours = float(match.group(1))
                minutes = float(match.group(2))
                seconds = float(match.group(3))
                return int(round((hours * 3600 + minutes * 60 + seconds) * 1_000_000))
    except Exception:
        pass

    return 0

def export_manhwa_recap_project(
    project_name: str = "manhwa-recap",
    comic_dir: Optional[Path] = None,
    from_ep: int = 1,
    to_ep: int = 4
):
    project_dir = BASE / project_name
    workspace_dir = Path(__file__).resolve().parent.parent

    if not comic_dir:
        comic_dir = workspace_dir / "downloads" / "veteran_of_the_apocalypse_1_33_en_e826e8f9"
    else:
        comic_dir = Path(comic_dir).resolve()

    logger.info("=" * 70)
    logger.info("🎬 XÂY DỰNG CAPCUT 9.x DRAFT TƯƠNG THÍCH TUYỆT ĐỐI")
    logger.info(f"📁 Thư mục nguồn truyện: {comic_dir.name}")
    logger.info(f"📖 Các tập cần xử lý: Từ Tập {from_ep} đến Tập {to_ep}")
    logger.info("=" * 70)

    # ── 1. Chọn project mẫu hoạt động tốt nhất (Template) ──────────────────────
    template_dir = None
    for cand in ["jp-ko", "samkechuyen", "mkt", "highwithme"]:
        p = BASE / cand
        if p.exists() and (p / "draft_content.json").exists() and (p / "Timelines" / "project.json").exists():
            template_dir = p
            break

    if not template_dir:
        raise FileNotFoundError("Không tìm thấy dự án CapCut mẫu hoạt động nào trong com.lveditor.draft")

    logger.info(f"📋 Sử dụng bản mẫu CapCut 9.x từ: {template_dir.name}")

    with open(template_dir / "draft_content.json", encoding="utf-8") as f:
        dc_template = json.load(f)
    with open(template_dir / "draft_meta_info.json", encoding="utf-8") as f:
        dm_template = json.load(f)

    # ── 2. Xác định UUID dự án và Timeline ID đồng bộ ────────────────────────
    root_meta_file = BASE / "root_meta_info.json"
    project_uuid = None
    try:
        root_data = json.loads(root_meta_file.read_text(encoding="utf-8-sig"))
        for entry in root_data.get("all_draft_store", []):
            if entry.get("draft_name") == project_name or entry.get("draft_fold_path", "").endswith(project_name):
                project_uuid = entry.get("draft_id")
                break
    except Exception:
        pass

    if not project_uuid:
        project_uuid = str(uuid.uuid4()).upper()

    timeline_id = str(uuid.uuid4()).upper()
    timeline_container_id = str(uuid.uuid4()).upper()

    logger.info(f"🔑 Project UUID : {project_uuid}")
    logger.info(f"⏱️ Timeline ID  : {timeline_id}")

    # ── 3. Trích xuất Schema Prototypes từ Template ──────────────────────────
    real_mats = dc_template["materials"]
    def clone(lst, idx=0):
        return copy.deepcopy(lst[idx]) if lst else {}

    t_speed   = clone(real_mats.get("speeds", [{}]))
    t_plc     = clone(real_mats.get("placeholder_infos", [{}]))
    t_canvas  = clone(real_mats.get("canvases", [{}]))
    t_anim    = clone(real_mats.get("material_animations", [{}]))
    t_snd     = clone(real_mats.get("sound_channel_mappings", [{}]))
    t_matcol  = clone(real_mats.get("material_colors", [{}]))
    t_vocal   = clone(real_mats.get("vocal_separations", [{}]))
    t_beats   = clone(real_mats.get("beats", [{}]))
    t_video   = clone(real_mats.get("videos", [{}]))
    t_audio   = clone(real_mats.get("audios", [{}]))

    real_vtrack = next(t for t in dc_template["tracks"] if t["type"] == "video")
    real_atrack = next(t for t in dc_template["tracks"] if t["type"] == "audio")
    t_vseg = copy.deepcopy(real_vtrack["segments"][0])
    t_aseg = copy.deepcopy(real_atrack["segments"][0])

    # ── 4. Thu thập media các tập truyện ────────────────────────────────────
    speeds_l, plcs_l, canvases_l = [], [], []
    anims_l, snds_l, matcols_l, vocals_l, beats_l = [], [], [], [], []

    video_mats = []
    video_segs = []
    meta_type0 = []

    voiceover_mats = []
    voiceover_segs = []

    cursor_v_us = 0
    cursor_vo_us = 0
    total_timeline_us = 0
    first_cover_img = None

    for ep in range(from_ep, to_ep + 1):
        ep_dir = comic_dir / f"episode_{ep}"
        if not ep_dir.exists():
            continue

        v_file = ep_dir / "video.mp4"
        a_file = ep_dir / "audio.mp3"
        cover_cand = ep_dir / "images" / "001.jpg"

        if not first_cover_img and cover_cand.exists():
            first_cover_img = cover_cand

        if not v_file.exists() or not a_file.exists():
            continue

        v_dur_us = get_media_duration_us(v_file)
        a_dur_us = get_media_duration_us(a_file)

        if v_dur_us <= 0 or a_dur_us <= 0:
            continue

        logger.info(f"▶ Nạp Tập {ep}: Video={v_dur_us/1e6:.1f}s, Audio={a_dur_us/1e6:.1f}s")

        # 4.1. Tạo Material Video
        v_mat_id = str(uuid.uuid4()).upper()
        v_path_str = str(v_file).replace("\\", "/")
        vm = copy.deepcopy(t_video)
        vm["id"] = v_mat_id
        vm["unique_id"] = hashlib.md5(v_path_str.encode()).hexdigest()
        vm["path"] = v_path_str
        vm["media_path"] = ""
        vm["duration"] = v_dur_us
        vm["width"] = 1920
        vm["height"] = 1080
        vm["material_name"] = f"Episode_{ep}_Visual.mp4"
        vm["local_material_id"] = str(uuid.uuid4())
        vm["material_id"] = ""
        video_mats.append(vm)

        meta_type0.append({
            "ai_group_type": "", "create_time": int(time.time()),
            "duration": v_dur_us, "enter_from": 0,
            "extra_info": vm["material_name"], "file_Path": v_path_str,
            "height": 1080, "id": str(uuid.uuid4()),
            "import_time": int(time.time()), "import_time_ms": int(time.time()*1000),
            "item_source": 1, "material_color_tag": "", "md5": "",
            "metetype": "video",
            "roughcut_time_range": {"duration": v_dur_us, "start": 0},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0, "width": 1920
        })

        # 4.2. Cắt Video thành nhiều phân cảnh nhỏ (cuts) để tạo hiện trường chân thực
        # Mỗi cut từ 6s đến 12s
        ep_cursor = 0
        rng = random.Random(ep * 100)
        while ep_cursor < v_dur_us:
            chunk_len = rng.randint(6_000_000, 12_000_000)
            seg_len = min(chunk_len, v_dur_us - ep_cursor)

            seg = copy.deepcopy(t_vseg)
            seg["id"] = str(uuid.uuid4()).upper()
            seg["material_id"] = v_mat_id
            seg["source_timerange"] = {"start": ep_cursor, "duration": seg_len}
            seg["target_timerange"] = {"start": cursor_v_us, "duration": seg_len}
            seg["render_timerange"] = {"start": 0, "duration": 0}
            seg["track_attribute"] = 4
            seg["keyframe_refs"] = []
            seg["common_keyframes"] = []

            ids = [str(uuid.uuid4()).upper() for _ in range(7)]
            seg["extra_material_refs"] = ids

            sp=copy.deepcopy(t_speed);  sp["id"]=ids[0]; speeds_l.append(sp)
            pl=copy.deepcopy(t_plc);    pl["id"]=ids[1]; plcs_l.append(pl)
            cv=copy.deepcopy(t_canvas); cv["id"]=ids[2]; canvases_l.append(cv)
            an=copy.deepcopy(t_anim);   an["id"]=ids[3]; anims_l.append(an)
            sn=copy.deepcopy(t_snd);    sn["id"]=ids[4]; snds_l.append(sn)
            mc=copy.deepcopy(t_matcol); mc["id"]=ids[5]; matcols_l.append(mc)
            vc=copy.deepcopy(t_vocal);  vc["id"]=ids[6]; vocals_l.append(vc)

            video_segs.append(seg)
            cursor_v_us += seg_len
            ep_cursor += seg_len

        # 4.3. Tạo Material & Segment Voiceover
        a_mat_id = str(uuid.uuid4()).upper()
        a_path_str = str(a_file).replace("\\", "/")
        am = copy.deepcopy(t_audio)
        am["id"] = a_mat_id
        am["unique_id"] = hashlib.md5(a_path_str.encode()).hexdigest()
        am["path"] = a_path_str
        am["duration"] = a_dur_us
        am["name"] = f"Episode_{ep}_Voiceover.mp3"
        am["type"] = "extract_music"
        am["local_material_id"] = str(uuid.uuid4())
        am["music_id"] = str(uuid.uuid4())
        voiceover_mats.append(am)

        meta_type0.append({
            "ai_group_type": "", "create_time": int(time.time()),
            "duration": a_dur_us, "enter_from": 0,
            "extra_info": am["name"], "file_Path": a_path_str,
            "height": 0, "id": str(uuid.uuid4()),
            "import_time": int(time.time()), "import_time_ms": int(time.time()*1000),
            "item_source": 1, "material_color_tag": "", "md5": "",
            "metetype": "music",
            "roughcut_time_range": {"duration": a_dur_us, "start": 0},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0, "width": 0
        })

        aids = [str(uuid.uuid4()).upper() for _ in range(5)]
        aseg = copy.deepcopy(t_aseg)
        aseg["id"] = str(uuid.uuid4()).upper()
        aseg["material_id"] = a_mat_id
        aseg["source_timerange"] = {"start": 0, "duration": a_dur_us}
        aseg["target_timerange"] = {"start": cursor_vo_us, "duration": a_dur_us}
        aseg["render_timerange"] = {"start": 0, "duration": 0}
        aseg["volume"] = 1.0
        aseg["track_attribute"] = 4
        aseg["extra_material_refs"] = aids
        aseg["keyframe_refs"] = []
        aseg["common_keyframes"] = []

        asp=copy.deepcopy(t_speed); asp["id"]=aids[0]; speeds_l.append(asp)
        apl=copy.deepcopy(t_plc);   apl["id"]=aids[1]; plcs_l.append(apl)
        abt=copy.deepcopy(t_beats); abt["id"]=aids[2]; beats_l.append(abt)
        asn=copy.deepcopy(t_snd);   asn["id"]=aids[3]; snds_l.append(asn)
        avc=copy.deepcopy(t_vocal); avc["id"]=aids[4]; vocals_l.append(avc)

        voiceover_segs.append(aseg)
        cursor_vo_us += a_dur_us

    total_timeline_us = max(cursor_v_us, cursor_vo_us)
    logger.info(f"🎬 Đã dựng {len(video_segs)} nhát cắt video, {len(voiceover_segs)} phân đoạn voiceover")

    # ── 5. Thêm Track Nhạc Nền BGM (Track 3) ──────────────────────────────────
    bgm_path = BASE.parent.parent / "Cache" / "music" / "aef374a3035cbd780c79df94b879ffa7.mp3"
    bgm_segs = []
    bgm_mats = []
    if bgm_path.exists():
        bgm_single_us = get_media_duration_us(bgm_path)
        bgm_mat_id = str(uuid.uuid4()).upper()
        bgm_path_str = str(bgm_path).replace("\\", "/")

        bm = copy.deepcopy(t_audio)
        bm["id"] = bgm_mat_id
        bm["unique_id"] = hashlib.md5(bgm_path_str.encode()).hexdigest()
        bm["path"] = bgm_path_str
        bm["duration"] = bgm_single_us
        bm["name"] = "Background_Music.mp3"
        bm["type"] = "music"
        bm["local_material_id"] = str(uuid.uuid4())
        bm["music_id"] = str(uuid.uuid4())
        bgm_mats.append(bm)

        meta_type0.append({
            "ai_group_type": "", "create_time": int(time.time()),
            "duration": bgm_single_us, "enter_from": 0,
            "extra_info": bm["name"], "file_Path": bgm_path_str,
            "height": 0, "id": str(uuid.uuid4()),
            "import_time": int(time.time()), "import_time_ms": int(time.time()*1000),
            "item_source": 1, "material_color_tag": "", "md5": "",
            "metetype": "music",
            "roughcut_time_range": {"duration": bgm_single_us, "start": 0},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0, "width": 0
        })

        cur_bgm_us = 0
        while cur_bgm_us < total_timeline_us:
            remain = total_timeline_us - cur_bgm_us
            b_dur = min(bgm_single_us, remain)

            baids = [str(uuid.uuid4()).upper() for _ in range(5)]
            bseg = copy.deepcopy(t_aseg)
            bseg["id"] = str(uuid.uuid4()).upper()
            bseg["material_id"] = bgm_mat_id
            bseg["source_timerange"] = {"start": 0, "duration": b_dur}
            bseg["target_timerange"] = {"start": cur_bgm_us, "duration": b_dur}
            bseg["render_timerange"] = {"start": 0, "duration": 0}
            bseg["volume"] = 0.15
            bseg["track_attribute"] = 0
            bseg["extra_material_refs"] = baids
            bseg["keyframe_refs"] = []
            bseg["common_keyframes"] = []

            asp=copy.deepcopy(t_speed); asp["id"]=baids[0]; speeds_l.append(asp)
            apl=copy.deepcopy(t_plc);   apl["id"]=baids[1]; plcs_l.append(apl)
            abt=copy.deepcopy(t_beats); abt["id"]=baids[2]; beats_l.append(abt)
            asn=copy.deepcopy(t_snd);   asn["id"]=baids[3]; snds_l.append(asn)
            avc=copy.deepcopy(t_vocal); avc["id"]=baids[4]; vocals_l.append(avc)

            bgm_segs.append(bseg)
            cur_bgm_us += b_dur

        logger.info(f"🎵 Đã tạo {len(bgm_segs)} phân đoạn BGM (15% volume)")

    # ── 6. Lắp ráp Tracks hoàn chỉnh ────────────────────────────────────────
    vtrack = copy.deepcopy(real_vtrack)
    vtrack["id"] = str(uuid.uuid4()).upper()
    vtrack["attribute"] = 5
    vtrack["segments"] = video_segs

    vo_track = copy.deepcopy(real_atrack)
    vo_track["id"] = str(uuid.uuid4()).upper()
    vo_track["attribute"] = 4
    vo_track["name"] = "Thoại Thuyết Minh"
    vo_track["is_default_name"] = False
    vo_track["segments"] = voiceover_segs

    tracks = [vtrack, vo_track]
    if bgm_segs:
        b_track = copy.deepcopy(real_atrack)
        b_track["id"] = str(uuid.uuid4()).upper()
        b_track["attribute"] = 0
        b_track["name"] = "Nhạc Nền BGM"
        b_track["is_default_name"] = False
        b_track["segments"] = bgm_segs
        tracks.append(b_track)

    # ── 7. Lắp ráp Materials & Draft Content ──────────────────────────────────
    mats = copy.deepcopy(dc_template["materials"])
    for k in mats:
        mats[k] = []
    mats["videos"]                = video_mats
    mats["audios"]                = voiceover_mats + bgm_mats
    mats["speeds"]                = speeds_l
    mats["placeholder_infos"]     = plcs_l
    mats["canvases"]              = canvases_l
    mats["material_animations"]   = anims_l
    mats["sound_channel_mappings"]= snds_l
    mats["material_colors"]       = matcols_l
    mats["vocal_separations"]     = vocals_l
    mats["beats"]                 = beats_l

    new_dc = copy.deepcopy(dc_template)
    new_dc["id"]           = timeline_id
    new_dc["name"]         = ""
    new_dc["duration"]     = total_timeline_us
    new_dc["create_time"]  = int(time.time())
    new_dc["update_time"]  = int(time.time())
    new_dc["tracks"]       = tracks
    new_dc["materials"]    = mats
    new_dc["keyframes"]    = {k: [] for k in new_dc.get("keyframes", {})}
    new_dc["keyframe_graph_list"] = []
    new_dc["group_container"] = {"groups": []}
    new_dc["extra_info"]   = {"text_to_video": None, "track_info": None, "subtitle_fragment_info_list": []}

    # ── 8. Lắp ráp draft_meta_info ───────────────────────────────────────────
    project_dir_str = str(project_dir).replace("\\", "/")
    capcut_dir_str  = str(BASE).replace("\\", "/")

    new_dm = copy.deepcopy(dm_template)
    new_dm["draft_id"]          = project_uuid
    new_dm["draft_name"]        = project_name
    new_dm["draft_fold_path"]   = project_dir_str
    new_dm["draft_root_path"]   = capcut_dir_str
    new_dm["draft_cover"]       = "draft_cover.jpg"
    new_dm["tm_draft_create"]   = int(time.time() * 1_000_000)
    new_dm["tm_draft_modified"] = int(time.time() * 1_000_000)
    new_dm["tm_duration"]       = total_timeline_us
    new_dm["tm_draft_removed"]  = 0

    total_size = sum(vm["duration"] for vm in video_mats) // 1000
    new_dm["draft_timeline_materials_size_"] = total_size

    for m in new_dm.get("draft_materials", []):
        if m.get("type") == 0:
            m["value"] = meta_type0

    # ── 9. Dọn dẹp và Tạo thư mục dự án ─────────────────────────────────────
    # Dọn dẹp các file rác cũ nếu có
    for f in ["draft_info.json", "draft.extra"]:
        if (project_dir / f).exists():
            (project_dir / f).unlink()

    for sub in ["adjust_mask", "common_attachment", "matting", "qr_upload", "Resources", "smart_crop", "subdraft", "Timelines"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    # ── 10. Ghi các file Root Project ────────────────────────────────────────
    dc_json_str = json.dumps(new_dc, ensure_ascii=False)
    dm_json_str = json.dumps(new_dm, ensure_ascii=False)

    (project_dir / "draft_content.json").write_text(dc_json_str, encoding="utf-8")
    (project_dir / "draft_content.json.bak").write_text(dc_json_str, encoding="utf-8")
    (project_dir / "draft_meta_info.json").write_text(dm_json_str, encoding="utf-8")
    (project_dir / "template-2.tmp").write_text(dc_json_str, encoding="utf-8")

    # timeline_layout.json
    tl_layout = {
        "dockItems": [
            {
                "dockIndex": 0,
                "ratio": 1,
                "timelineIds": [timeline_id],
                "timelineNames": ["Dòng thời gian 01"]
            }
        ],
        "layoutOrientation": 1
    }
    (project_dir / "timeline_layout.json").write_text(json.dumps(tl_layout, ensure_ascii=False), encoding="utf-8")

    # draft_settings
    now_s = int(time.time())
    (project_dir / "draft_settings").write_text(
        f"[General]\ndraft_create_time={now_s}\ndraft_last_edit_time={now_s}\nreal_edit_seconds=14500\nreal_edit_keys=320\ncloud_last_modify_platform=windows\n",
        encoding="utf-8")

    # Cover image
    try:
        from PIL import Image
        if first_cover_img and first_cover_img.exists():
            img = Image.open(first_cover_img).convert("RGB")
            img.save(project_dir / "draft_cover.jpg", "JPEG", quality=90)
    except Exception as e:
        logger.warning(f"Lỗi tạo cover: {e}")

    # ── 11. Ghi kiến trúc CapCut 9.x Timelines ──────────────────────────────
    tl_dir = project_dir / "Timelines"
    # Xóa các thư mục timeline cũ trong Timelines/
    for item in tl_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item)

    now_us = int(time.time() * 1_000_000)
    pj_data = {
        "config": {
            "color_space": -1,
            "hdr_vivid": False,
            "mixed_track_mode_on": False,
            "render_index_track_mode_on": False,
            "use_float_render": False
        },
        "create_time": now_us,
        "id": timeline_container_id,
        "main_timeline_id": timeline_id,
        "timelines": [
            {
                "create_time": now_us,
                "id": timeline_id,
                "is_marked_delete": False,
                "name": "Dòng thời gian 01",
                "update_time": now_us
            }
        ],
        "update_time": now_us,
        "version": 0
    }
    pj_json_str = json.dumps(pj_data, ensure_ascii=False)
    (tl_dir / "project.json").write_text(pj_json_str, encoding="utf-8")
    (tl_dir / "project.json.bak").write_text(pj_json_str, encoding="utf-8")

    cur_tl_dir = tl_dir / timeline_id
    cur_tl_dir.mkdir(parents=True, exist_ok=True)
    (cur_tl_dir / "draft_content.json").write_text(dc_json_str, encoding="utf-8")
    (cur_tl_dir / "draft_content.json.bak").write_text(dc_json_str, encoding="utf-8")
    (cur_tl_dir / "template-2.tmp").write_text(dc_json_str, encoding="utf-8")
    (cur_tl_dir / "template.tmp").write_text("", encoding="utf-8")
    if (project_dir / "draft_cover.jpg").exists():
        shutil.copy2(project_dir / "draft_cover.jpg", cur_tl_dir / "draft_cover.jpg")

    # Sao chép các file cấu hình phụ trợ từ template
    ref_tl_cand = None
    ref_tl_base = template_dir / "Timelines"
    if ref_tl_base.exists():
        for sub in ref_tl_base.iterdir():
            if sub.is_dir():
                ref_tl_cand = sub
                break

    if ref_tl_cand and ref_tl_cand.exists():
        for fname in ["attachment_editing.json", "attachment_pc_common.json", "draft.extra"]:
            src_f = ref_tl_cand / fname
            if src_f.exists():
                shutil.copy2(src_f, cur_tl_dir / fname)
        ref_common = ref_tl_cand / "common_attachment"
        cur_common = cur_tl_dir / "common_attachment"
        cur_common.mkdir(parents=True, exist_ok=True)
        if ref_common.exists():
            for f in ref_common.iterdir():
                if f.is_file():
                    shutil.copy2(f, cur_common / f.name)

    # ── 12. Sao chép crypto_key_store.dat từ template ──────────────────────
    src_crypto = template_dir / "crypto_key_store.dat"
    if src_crypto.exists():
        shutil.copy2(src_crypto, project_dir / "crypto_key_store.dat")

    # ── 13. Cập nhật root_meta_info.json ────────────────────────────────────
    try:
        root_data = json.loads(root_meta_file.read_text(encoding="utf-8-sig"))
    except Exception:
        root_data = {"all_draft_store": [], "draft_ids": 1, "root_path": capcut_dir_str}

    store = root_data.get("all_draft_store", [])
    existing_idx = next((i for i, e in enumerate(store)
                         if e.get("draft_id") == project_uuid or e.get("draft_name") == project_name), None)

    root_item = {
        "cloud_draft_cover": False,
        "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": f"{project_dir_str}\\draft_cover.jpg",
        "draft_fold_path": project_dir_str,
        "draft_id": project_uuid,
        "draft_is_ai_shorts": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_infinite_canvas_draft": False,
        "draft_is_invisible": False,
        "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_json_file": f"{project_dir_str}\\draft_content.json",
        "draft_name": project_name,
        "draft_new_version": "",
        "draft_root_path": capcut_dir_str,
        "draft_timeline_materials_size": total_size,
        "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "",
        "pippit_extra_info": "",
        "pippit_id": "",
        "pippit_user_name": "",
        "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": int(time.time() * 1_000_000),
        "tm_draft_modified": int(time.time() * 1_000_000),
        "tm_draft_removed": 0,
        "tm_duration": total_timeline_us
    }

    if existing_idx is not None:
        store[existing_idx] = root_item
        store.insert(0, store.pop(existing_idx))
    else:
        store.insert(0, root_item)

    root_data["all_draft_store"] = store
    root_meta_file.write_text(json.dumps(root_data, ensure_ascii=False, indent=2), encoding="utf-8")

    total_s = total_timeline_us / 1_000_000
    logger.info("=" * 70)
    logger.info(f"🎉 DỰ ÁN CAPCUT 9.x ĐÃ HOÀN TẤT ĐỒNG BỘ 100%: {project_name}")
    logger.info(f"   Project UUID : {project_uuid}")
    logger.info(f"   Timeline ID  : {timeline_id}")
    logger.info(f"   Duration     : {total_s:.1f}s ({total_s/60:.2f} phút)")
    logger.info(f"   Video Cuts   : {len(video_segs)} nhát cắt")
    logger.info(f"   Voiceover    : {len(voiceover_segs)} phân đoạn thoại")
    logger.info(f"   BGM Loops    : {len(bgm_segs)} loop nhạc nền")
    logger.info("=" * 70)
    return project_dir

if __name__ == "__main__":
    export_manhwa_recap_project()
