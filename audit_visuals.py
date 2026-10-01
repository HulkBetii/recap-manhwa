import os
import sys
import json
import cv2
import numpy as np
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.chdir(Path(__file__).resolve().parent)

def list_image_files(directory):
    if not os.path.exists(directory):
        return []
    valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    files = [f for f in os.listdir(directory) if os.path.splitext(f.lower())[1] in valid_exts]
    return sorted(files)

from visual_scorer import VisualSemanticScorer
download_dir = r"downloads\veteran_of_the_apocalypse_1_5_vi_e826e8f9"

print("=" * 80)
print("  AUDIT CHUYÊN SÂU: KIỂM TRA ẢNH VÔ NGHĨA & CHẤT LƯỢNG HÌNH ẢNH (TẬP 1-5)")
print("=" * 80)

# Check all images in images_blur for each episode
all_meaningless_images = []
all_high_bubble_images = []
all_low_detail_images = []

for ep in range(1, 6):
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    images_dir = os.path.join(ep_dir, "images_blur")
    if not os.path.exists(images_dir):
        images_dir = os.path.join(ep_dir, "images_pdf")
    
    img_files = list_image_files(images_dir)
    print(f"\n--- TẬP {ep} ({len(img_files)} ảnh) ---")
    
    ep_meaningless = []
    ep_high_bubble = []
    ep_low_score = []
    
    for idx, fname in enumerate(img_files):
        p_num = idx + 1
        img_p = os.path.join(images_dir, fname)
        mat = cv2.imread(img_p)
        if mat is None:
            continue
            
        sc, bd = VisualSemanticScorer.calculate_score(mat)
        is_mean = bd.get("is_meaningless", False)
        bubble_cov = bd.get("bubble_coverage_ratio", 0.0)
        char_p = bd.get("character_presence", 0.0)
        is_est = bd.get("is_establishing_shot", False)
        
        if is_mean:
            ep_meaningless.append((p_num, fname, sc, char_p, bubble_cov, bd.get("reason", "")))
        elif bubble_cov >= 0.35:
            ep_high_bubble.append((p_num, fname, sc, char_p, bubble_cov))
        elif sc < 45 and not is_est and char_p < 20:
            ep_low_score.append((p_num, fname, sc, char_p, bubble_cov))
            
    print(f"  • Ảnh vô nghĩa / khung rác / chỉ bóng thoại: {len(ep_meaningless)}")
    for item in ep_meaningless:
        print(f"    - Trang {item[0]} ({item[1]}): score={item[2]}, char={item[3]:.1f}%, bubble={item[4]*100:.1f}%, lý do={item[5]}")
    
    print(f"  • Ảnh có tỷ lệ bóng thoại cao (>35%): {len(ep_high_bubble)}")
    for item in ep_high_bubble:
        print(f"    - Trang {item[0]} ({item[1]}): score={item[2]}, char={item[3]:.1f}%, bubble={item[4]*100:.1f}%")
        
    print(f"  • Ảnh điểm chi tiết thấp (<45, ít nhân vật): {len(ep_low_score)}")
    for item in ep_low_score:
        print(f"    - Trang {item[0]} ({item[1]}): score={item[2]}, char={item[3]:.1f}%, bubble={item[4]*100:.1f}%")

print("\n" + "=" * 80)
print("  KIỂM TRA CÁC ẢNH THỰC SỰ HIỂN THỊ TRONG VIDEO (STAGE 10 DISPLAYED SHOTS)")
print("=" * 80)

# Check how Stage 10 constructed page_displays
for ep in range(1, 6):
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    images_pdf_dir = os.path.join(ep_dir, "images_pdf")
    images_blur_dir = os.path.join(ep_dir, "images_blur")
    if not os.path.exists(images_blur_dir):
        images_blur_dir = images_pdf_dir
    
    img_files = list_image_files(images_blur_dir)
    recap_p = os.path.join(ep_dir, "recap.json")
    srt_p = os.path.join(ep_dir, "transcript.srt")
    
    with open(recap_p, "r", encoding="utf-8") as f:
        recap_data = json.load(f)
    segments = recap_data if isinstance(recap_data, list) else recap_data.get("segments", [])
    
    with open(srt_p, "r", encoding="utf-8") as f:
        srt_content = f.read().replace('\r\n', '\n').strip()
    import re
    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})"
    matches = re.findall(pattern, srt_content)
    
    def p2s(ts):
        ts = ts.replace(',', '.')
        p = ts.split(':')
        return float(p[0])*3600 + float(p[1])*60 + float(p[2])
        
    timings = [{"start": p2s(m[1]), "end": p2s(m[2])} for m in matches]
    
    # Simulate Stage 10 page displays builder
    current_time = 0.0
    recent_displayed_pages = []
    global_used_donors = set()
    page_displays = []
    
    for s_idx, seg in enumerate(segments):
        end_time = timings[s_idx]["end"] if s_idx < len(timings) else current_time + 3.0
        segment_duration = end_time - current_time
        if s_idx == len(segments) - 1:
            segment_duration = max(3.0, segment_duration + 3.0)
        if segment_duration <= 0:
            segment_duration = 1.0
            
        seg_images = seg.get("images", [])
        if seg_images:
            scored_candidates = []
            for img_obj in seg_images:
                p_idx = int(img_obj["page"]) - 1
                if 0 <= p_idx < len(img_files):
                    im_path = os.path.join(images_blur_dir, img_files[p_idx])
                    try:
                        im_bgr = cv2.imread(im_path)
                        sc, bd = VisualSemanticScorer.calculate_score(im_bgr)
                        char_p = bd.get("character_presence", 0.0)
                        bubble_cov = bd.get("bubble_coverage_ratio", 0.0)
                        is_bad = (
                            bd.get("is_meaningless", False)
                            or bubble_cov >= 0.35
                            or (char_p < 25.0 and not bd.get("is_establishing_shot", False))
                        )
                    except Exception:
                        sc, char_p, is_bad = 70, 50.0, False
                        bd = {}
                    scored_candidates.append((img_obj, sc, char_p, is_bad, bd.get("is_meaningless", False)))
            
            valid_art = [item for item in scored_candidates if not item[3]]
            if valid_art:
                seg_images = [it[0] for it in valid_art]
            else:
                best_item = max(scored_candidates, key=lambda x: x[1]) if scored_candidates else None
                if best_item:
                    bad_page_idx = int(best_item[0]["page"]) - 1
                    best_comp = -1
                    best_idx = bad_page_idx
                    for delta in [1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8]:
                        cand = bad_page_idx + delta
                        if 0 <= cand < len(img_files):
                            cand_page = cand + 1
                            if cand_page in recent_displayed_pages[-4:] or cand_page in global_used_donors:
                                continue
                            im_p = os.path.join(images_blur_dir, img_files[cand])
                            try:
                                im_bgr = cv2.imread(im_p)
                                sc, bd = VisualSemanticScorer.calculate_score(im_bgr)
                                char_p = bd.get("character_presence", 0.0)
                                bubble_cov = bd.get("bubble_coverage_ratio", 0.0)
                                is_est = bd.get("is_establishing_shot", False)
                                comp = sc * 0.6 + char_p * 0.4
                                if not bd.get("is_meaningless", False) and bubble_cov < 0.30 and (char_p >= 35.0 or (is_est and sc >= 60)) and comp > best_comp:
                                    best_comp = comp
                                    best_idx = cand
                            except Exception:
                                pass
                    if best_comp >= 45:
                        ch_p = best_idx + 1
                        global_used_donors.add(ch_p)
                        seg_images = [{"page": ch_p, "priority": 1.0}]
                    else:
                        seg_images = [{"page": best_item[0]["page"], "priority": 1.0}]
                        
        for img_obj in seg_images:
            page = int(img_obj["page"])
            priority = float(img_obj.get("priority", 1.0))
            img_dur = segment_duration * priority
            page_idx = page - 1
            img_file = img_files[page_idx] if 0 <= page_idx < len(img_files) else "unknown"
            page_displays.append({
                "page": page,
                "image_file": img_file,
                "duration": img_dur,
                "start_time": current_time,
                "end_time": current_time + img_dur,
                "segment_index": s_idx,
                "speech": seg.get("speech", "")
            })
            recent_displayed_pages.append(page)
            current_time += img_dur

    # Merge consecutive identical
    merged = []
    for pd in page_displays:
        if merged and merged[-1]["image_file"] == pd["image_file"]:
            merged[-1]["duration"] += pd["duration"]
            merged[-1]["end_time"] = merged[-1]["start_time"] + merged[-1]["duration"]
        else:
            merged.append(pd)
            
    # Hard floor 1.5s
    cleaned = []
    for pd in merged:
        if cleaned and pd["duration"] < 1.5:
            cleaned[-1]["duration"] += pd["duration"]
            cleaned[-1]["end_time"] = cleaned[-1]["start_time"] + cleaned[-1]["duration"]
        else:
            cleaned.append(pd)
    if len(cleaned) > 1 and cleaned[0]["duration"] < 1.5:
        first = cleaned.pop(0)
        cleaned[0]["duration"] += first["duration"]
        cleaned[0]["start_time"] = first["start_time"]
        
    final_displays = []
    for pd in cleaned:
        if final_displays and final_displays[-1]["image_file"] == pd["image_file"]:
            final_displays[-1]["duration"] += pd["duration"]
            final_displays[-1]["end_time"] = final_displays[-1]["start_time"] + final_displays[-1]["duration"]
        else:
            final_displays.append(pd)
            
    # Now audit final_displays for Episode ep
    ep_displayed_bad = []
    ep_displayed_high_bubble = []
    ep_long_shots = []
    
    for shot in final_displays:
        p_idx = shot["page"] - 1
        im_p = os.path.join(images_blur_dir, img_files[p_idx])
        mat = cv2.imread(im_p)
        sc, bd = VisualSemanticScorer.calculate_score(mat)
        if bd.get("is_meaningless", False):
            ep_displayed_bad.append((shot, sc, bd))
        elif bd.get("bubble_coverage_ratio", 0.0) >= 0.35:
            ep_displayed_high_bubble.append((shot, sc, bd))
        if shot["duration"] >= 6.0:
            ep_long_shots.append(shot)
            
    print(f"\n--- TẬP {ep}: Tổng cộng {len(final_displays)} shot hiển thị trên video ---")
    print(f"  • Shot vô nghĩa lọt vào video: {len(ep_displayed_bad)}")
    for s, sc, bd in ep_displayed_bad:
        print(f"    [CẢNH BÁO] Trang {s['page']} ({s['image_file']}) tại {s['start_time']:.1f}s-{s['end_time']:.1f}s: {bd.get('reason')}")
    print(f"  • Shot bóng thoại cao (>35%) lọt vào video: {len(ep_displayed_high_bubble)}")
    for s, sc, bd in ep_displayed_high_bubble:
        print(f"    [CẢNH BÁO] Trang {s['page']} ({s['image_file']}) tại {s['start_time']:.1f}s-{s['end_time']:.1f}s: bubble={bd.get('bubble_coverage_ratio', 0.0)*100:.1f}%")
    print(f"  • Shot dài (>= 6.0s): {len(ep_long_shots)}")
    for s in ep_long_shots[:5]:
        print(f"    - Trang {s['page']} ({s['image_file']}): {s['duration']:.1f}s ({s['start_time']:.1f}s-{s['end_time']:.1f}s) | '{s['speech'][:45]}...'")

