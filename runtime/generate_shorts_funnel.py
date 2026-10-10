"""Tri-Shorts Funnel Engine for YouTube Manhwa Recap Channels.
Generates 3 weekly mobile-optimized vertical YouTube Shorts (1080x1920)
aligned with the Rey Manhwa publication schedule:
- Short #1: Sábado (12:00 PM CDMX) - Gancho / Cold Open (0s - ~48s)
- Short #2: Martes (05:30 PM CDMX) - Acción & Combate (20m - 35m)
- Short #3: Jueves (05:30 PM CDMX) - Clímax & Supervivencia (40m - 55m)
Includes smart sentence boundary detection, burned subtitles, vertical crop,
CTA audio & video screen, plus automated YouTube Shorts Upload Kit packaging.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

def get_ffmpeg_exe() -> str:
    try:
        from app import find_ffmpeg
        exe = find_ffmpeg()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    env_ffmpeg = os.path.join(PROJECT_DIR, ".venv", "Scripts", "ffmpeg.exe")
    if os.path.exists(env_ffmpeg):
        return env_ffmpeg
    return "ffmpeg"

FFMPEG_PATH = get_ffmpeg_exe()

def parse_time(time_str: str) -> float:
    parts = time_str.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

def parse_srt(srt_path: str) -> List[Dict[str, Any]]:
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read().strip()
    pattern = re.compile(
        r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)",
        re.DOTALL,
    )
    matches = pattern.findall(content)
    cues = []
    for m in matches:
        start_s = parse_time(m[1])
        end_s = parse_time(m[2])
        text = m[3].replace("\n", " ").strip()
        cues.append({"id": int(m[0]), "start": start_s, "end": end_s, "text": text})
    return cues

def get_video_duration(video_path: str) -> float:
    cmd = [FFMPEG_PATH, "-i", video_path]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="ignore")
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
    if dur_match:
        h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), float(dur_match.group(3))
        return h * 3600 + m * 60 + s
    return 3600.0

ACTION_WORDS = [
    "lobby", "disparo", "arma", "muerte", "monstruo", "zombi", "hacha", "sangre",
    "destroza", "cabeza", "derrapar", "emboscada", "trampa", "acaba", "coloso",
    "decapita", "peligro", "ataque", "golpe", "cuchillo", "camioneta", "horda",
    "matadero", "fusil", "pelea", "furia", "grito", "escapar", "mordida"
]

def find_tri_shorts_windows(cues: List[Dict[str, Any]], total_duration: float) -> List[Dict[str, Any]]:
    windows = []

    # 1. Window 1: Cold Open (Thứ Bảy - 0s đến ~48s)
    end1 = 48.0
    for b in cues:
        if 40.0 <= b["end"] <= 52.0:
            if re.search(r'[.!?¡¿"]$', b["text"].strip()):
                end1 = b["end"]
                break
    text1 = " ".join(c["text"] for c in cues if c["end"] <= end1)
    windows.append({
        "id": 1,
        "name": "SHORTS_1_Intro",
        "day_label": "SÁBADO (Thứ Bảy) - 12:00 PM CDMX",
        "category": "Mồi Nhử / Cold Open",
        "start": 0.0,
        "end": end1,
        "duration": end1,
        "text": text1,
    })

    # 2. Window 2: Combat / Action (Thứ Ba - khoảng 20% đến 55% thời lượng)
    range2 = (total_duration * 0.20, total_duration * 0.55)
    best_w2 = None
    max_score2 = -1
    for i in range(len(cues)):
        if range2[0] <= cues[i]["start"] <= range2[1]:
            start_t = cues[i]["start"]
            for j in range(i + 1, min(i + 30, len(cues))):
                dur = cues[j]["end"] - start_t
                if 38.0 <= dur <= 50.0:
                    if re.search(r'[.!?¡¿"]$', cues[j]["text"].strip()):
                        w_text = " ".join(c["text"] for c in cues[i:j + 1])
                        score = sum(w_text.lower().count(w) for w in ACTION_WORDS)
                        if score > max_score2:
                            max_score2 = score
                            best_w2 = (start_t, cues[j]["end"], dur, w_text)

    if not best_w2:
        # Fallback mid-video
        mid_s = total_duration * 0.35
        best_w2 = (mid_s, mid_s + 45.0, 45.0, "")
    
    windows.append({
        "id": 2,
        "name": "SHORTS_2_Combat",
        "day_label": "MARTES (Thứ Ba) - 05:30 PM CDMX",
        "category": "Bơm View / Combat & Rượt Đuổi",
        "start": best_w2[0],
        "end": best_w2[1],
        "duration": best_w2[2],
        "text": best_w2[3],
    })

    # 3. Window 3: Climax / Boss Fight (Thứ Năm - khoảng 60% đến 88% thời lượng)
    range3 = (total_duration * 0.60, total_duration * 0.88)
    best_w3 = None
    max_score3 = -1
    for i in range(len(cues)):
        if range3[0] <= cues[i]["start"] <= range3[1]:
            start_t = cues[i]["start"]
            for j in range(i + 1, min(i + 30, len(cues))):
                dur = cues[j]["end"] - start_t
                if 38.0 <= dur <= 50.0:
                    if re.search(r'[.!?¡¿"]$', cues[j]["text"].strip()):
                        w_text = " ".join(c["text"] for c in cues[i:j + 1])
                        score = sum(w_text.lower().count(w) for w in ACTION_WORDS)
                        if score > max_score3:
                            max_score3 = score
                            best_w3 = (start_t, cues[j]["end"], dur, w_text)

    if not best_w3:
        # Fallback late-video
        late_s = total_duration * 0.70
        best_w3 = (late_s, late_s + 45.0, 45.0, "")

    windows.append({
        "id": 3,
        "name": "SHORTS_3_Climax",
        "day_label": "JUEVES (Thứ Năm) - 05:30 PM CDMX",
        "category": "Giữ Nhiệt / Boss Climax & Sinh Tồn",
        "start": best_w3[0],
        "end": best_w3[1],
        "duration": best_w3[2],
        "text": best_w3[3],
    })

    return windows

def slice_and_offset_srt(cues: List[Dict[str, Any]], start_t: float, end_t: float, out_srt_path: str):
    sliced = []
    idx = 1
    for c in cues:
        if c["end"] > start_t and c["start"] < end_t:
            c_start = max(0.0, c["start"] - start_t)
            c_end = min(end_t - start_t, c["end"] - start_t)
            if c_end > c_start:
                sliced.append({
                    "id": idx,
                    "start": format_time(c_start),
                    "end": format_time(c_end),
                    "text": c["text"],
                })
                idx += 1
    with open(out_srt_path, "w", encoding="utf-8-sig") as f:
        for s in sliced:
            f.write(f"{s['id']}\n{s['start']} --> {s['end']}\n{s['text']}\n\n")

def generate_cta_audio(text: str, output_path: str):
    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return
    print(f"[CTA] Generating TTS for: '{text}'")
    cmd = [
        sys.executable,
        "-m",
        "edge_tts",
        "--voice", "es-MX-JorgeNeural",
        "--rate", "+10%",
        "--text", text,
        "--write-media", output_path,
    ]
    subprocess.run(cmd, check=True)

def render_cta_video(cta_audio_path: str, output_cta_video: str):
    if os.path.exists(output_cta_video) and os.path.getsize(output_cta_video) > 5000:
        return
    print(f"[CTA] Rendering CTA video segment...")
    cmd_cta = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=4.0",
        "-i", cta_audio_path,
        "-vf", "drawtext=text='VÍDEO COMPLETO ABAJO \\n    ↓ ↓ ↓':fontcolor=white:fontsize=70:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-shortest",
        output_cta_video,
    ]
    subprocess.run(cmd_cta, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def render_single_short(
    video_abs: str,
    cues: List[Dict[str, Any]],
    window: Dict[str, Any],
    output_mp4: str,
    temp_dir: str,
    cta_video_path: str,
):
    print(f"\n🎬 [RENDER] Bắt đầu render {window['name']} ({window['day_label']})...")
    print(f"   Mốc thời gian: {window['start']:.2f}s ({window['start']/60:.2f}m) -> {window['end']:.2f}s ({window['end']/60:.2f}m) | Thời lượng: {window['duration']:.2f}s")

    w_id = window["id"]
    temp_srt = os.path.join(temp_dir, f"temp_subs_{w_id}.srt")
    temp_main_mp4 = os.path.join(temp_dir, f"temp_main_{w_id}.mp4")
    temp_list = os.path.join(temp_dir, f"temp_list_{w_id}.txt")

    # 1. Slice & Offset SRT
    slice_and_offset_srt(cues, window["start"], window["end"], temp_srt)

    # 2. Extract, Crop 9:16 and Burn Subtitles
    # On Windows, drive letter colon (D:) in subtitles filter must be escaped as D\:
    safe_sub_path = os.path.abspath(temp_srt).replace("\\", "/").replace(":", r"\:")
    vf_string = (
        f"crop=608:1080,scale=1080:1920,"
        f"subtitles='{safe_sub_path}':force_style='FontSize=22,Alignment=2,MarginV=60,Outline=2,Shadow=0,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000'"
    )

    cmd_main = [
        FFMPEG_PATH, "-y",
        "-ss", str(window["start"]),
        "-i", video_abs,
        "-t", str(window["duration"]),
        "-vf", vf_string,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        temp_main_mp4,
    ]
    try:
        subprocess.run(cmd_main, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as err:
        print(f"❌ [FFMPEG LỖI RENDER]: {err.stderr.decode('utf-8', errors='replace')}")
        raise err

    # 3. Concatenate with 4s CTA
    with open(temp_list, "w", encoding="utf-8") as f:
        p_main = os.path.abspath(temp_main_mp4).replace("\\", "/")
        p_cta = os.path.abspath(cta_video_path).replace("\\", "/")
        f.write(f"file '{p_main}'\n")
        f.write(f"file '{p_cta}'\n")

    cmd_concat = [
        FFMPEG_PATH, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", temp_list,
        "-c", "copy",
        output_mp4,
    ]
    try:
        subprocess.run(cmd_concat, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as err:
        print(f"❌ [FFMPEG LỖI CONCAT]: {err.stderr.decode('utf-8', errors='replace')}")
        raise err
    print(f"✔ [XUẤT BẢN] Hoàn thành {os.path.basename(output_mp4)}")

def call_9router_llm(prompt: str) -> Optional[str]:
    url = "http://localhost:20128/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "ag/gemini-3.8-flash-high",
        "messages": [
            {"role": "system", "content": "Eres un estratega experto de YouTube Shorts para el canal Rey Manhwa (Latinoamérica). Responde únicamente en texto plano."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.85,
        "max_tokens": 1500,
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠ [LLM] Không gọi được 9Router ({e}), dùng bộ mẫu template dự phòng.")
        return None

def generate_tri_shorts_metadata_kit(
    comic_title: str,
    master_title: str,
    windows: List[Dict[str, Any]],
    output_kit_path: str,
    video_filenames: List[str],
):
    print(f"\n📝 [METADATA] Đang tạo bộ công cụ YouTube Shorts Upload Kit (3 bài đăng)...")
    prompt = f"""Escribe los títulos, descripciones y etiquetas para 3 YouTube Shorts del manhwa "{comic_title}".
Video largo de referencia: "{master_title}".

Calendario de publicación oficial de Rey Manhwa:
1. SHORT #1 (Sábado 12:00 PM CDMX - Gancho & Cold Open):
Contexto: {windows[0]['text'][:300]}...

2. SHORT #2 (Martes 05:30 PM CDMX - Acción & Combate):
Contexto: {windows[1]['text'][:300]}...

3. SHORT #3 (Jueves 05:30 PM CDMX - Clímax & Supervivencia):
Contexto: {windows[2]['text'][:300]}...

REGLAS ESTRICTAS:
- TITULO: Máximo 60 caracteres. Extremadamente clickbait y épico. Debe terminar con "#shorts #manhwa".
- DESCRIPCION: 2 líneas intrigantes + llamado a la acción exacto: "👉 ¡Mira el video completo en el enlace relacionado abajo!" + hashtags (#manhwanarrado #resumen #apocalipsis #zombis).
- TAGS: 10 etiquetas separadas por coma.

Devuelve en el siguiente formato exacto:
[SHORT 1]
TITULO: <titulo>
DESCRIPCION: <descripcion>
TAGS: <tags>

[SHORT 2]
TITULO: <titulo>
DESCRIPCION: <descripcion>
TAGS: <tags>

[SHORT 3]
TITULO: <titulo>
DESCRIPCION: <descripcion>
TAGS: <tags>
"""
    llm_resp = call_9router_llm(prompt)

    # Parse or Fallback
    shorts_data = {}
    if llm_resp:
        for i in [1, 2, 3]:
            m = re.search(rf"\[SHORT {i}\].*?TITULO:\s*(.*?)\nDESCRIPCION:\s*(.*?)\nTAGS:\s*(.*?)(?=\n\n\[SHORT|\Z)", llm_resp, re.DOTALL)
            if m:
                shorts_data[i] = {
                    "title": m.group(1).strip()[:60],
                    "desc": m.group(2).strip(),
                    "tags": m.group(3).strip(),
                }

    # Template fallbacks if any missing
    default_meta = {
        1: {
            "title": "¡Regresó Al Pasado y Se Preparó! #shorts #manhwa",
            "desc": "El apocalipsis zombi destruyó todo, pero él volvió en el tiempo con un refugio oculto.\n\n👉 ¡Mira el video completo en el enlace relacionado abajo!\n\n#shorts #manhwa #resumen #apocalipsis #zombis",
            "tags": "manhwa resumen, resumen de manhwa, manhwa zombis, manhwa apocalipsis, manhwa regresion, webtoon resumen, prota op, supervivencia, manhwa audio latino, shorts",
        },
        2: {
            "title": "¡Atrapados En La Horda Pero No Teme! #shorts #manhwa",
            "desc": "Rodeados de zombis y saqueadores, Seongho Kang demuestra quién es el verdadero depredador.\n\n👉 ¡Mira el video completo en el enlace relacionado abajo!\n\n#shorts #manhwa #manhwanarrado #combate #apocalipsis",
            "tags": "manhwa resumen, resumen de manhwa, manhwa accion, manhwa combate, prota frio, zombis manhwa, manhwa audio latino, manhwa traicion, manhwa espanol, shorts",
        },
        3: {
            "title": "¡La Bestia Mutante En Las Sombras! #shorts #manhwa",
            "desc": "Una criatura mutante acecha en los túneles subterráneos. La batalla decisiva por el refugio.\n\n👉 ¡Mira el video completo en el enlace relacionado abajo!\n\n#shorts #manhwa #resumen #monstruos #climax",
            "tags": "manhwa resumen, resumen de manhwa, manhwa mutantes, batalla final, manhwa sistema, webtoon espaniol, resumen manhwas completos, prota badass, apocalipsis, shorts",
        },
    }

    for i in [1, 2, 3]:
        if i not in shorts_data:
            shorts_data[i] = default_meta[i]

    # Assemble formatted upload kit
    kit_lines = [
        "=" * 80,
        "KIT DE PUBLICACIÓN PARA YOUTUBE SHORTS (3 VIDEOS POR SEMANA - REY MANHWA)",
        f"Serie: {comic_title} | Basado en el Mega-Video: {master_title}",
        "=" * 80,
        "",
        "Lógica del Embudo (Funnel Logic):",
        "• Cada Short debe tener configurado en YouTube Studio el campo 'Related Video' (Video relacionado) apuntando directamente al enlace del Video Largo del canal.",
        "",
        "────────────────────────────────────────────────────────────────────────────────",
        f"[1. SHORT #1: {windows[0]['day_label'].upper()}] - {windows[0]['category'].upper()}",
        f"Archivo de Video: {video_filenames[0]}",
        f"Mốc thời lượng gốc: {windows[0]['start']:.1f}s -> {windows[0]['end']:.1f}s ({windows[0]['duration']:.1f}s)",
        "────────────────────────────────────────────────────────────────────────────────",
        "TITULO (Copiar en YouTube Studio):",
        shorts_data[1]["title"],
        "",
        "DESCRIPCION:",
        shorts_data[1]["desc"],
        "",
        "TAGS (Copiar en la caja de etiquetas):",
        shorts_data[1]["tags"],
        "",
        "────────────────────────────────────────────────────────────────────────────────",
        f"[2. SHORT #2: {windows[1]['day_label'].upper()}] - {windows[1]['category'].upper()}",
        f"Archivo de Video: {video_filenames[1]}",
        f"Mốc thời lượng gốc: {windows[1]['start']:.1f}s -> {windows[1]['end']:.1f}s ({windows[1]['duration']:.1f}s)",
        "────────────────────────────────────────────────────────────────────────────────",
        "TITULO (Copiar en YouTube Studio):",
        shorts_data[2]["title"],
        "",
        "DESCRIPCION:",
        shorts_data[2]["desc"],
        "",
        "TAGS (Copiar en la caja de etiquetas):",
        shorts_data[2]["tags"],
        "",
        "────────────────────────────────────────────────────────────────────────────────",
        f"[3. SHORT #3: {windows[2]['day_label'].upper()}] - {windows[2]['category'].upper()}",
        f"Archivo de Video: {video_filenames[2]}",
        f"Mốc thời lượng gốc: {windows[2]['start']:.1f}s -> {windows[2]['end']:.1f}s ({windows[2]['duration']:.1f}s)",
        "────────────────────────────────────────────────────────────────────────────────",
        "TITULO (Copiar en YouTube Studio):",
        shorts_data[3]["title"],
        "",
        "DESCRIPCION:",
        shorts_data[3]["desc"],
        "",
        "TAGS (Copiar en la caja de etiquetas):",
        shorts_data[3]["tags"],
        "",
        "=" * 80,
    ]

    with open(output_kit_path, "w", encoding="utf-8") as f:
        f.write("\n".join(kit_lines))
    print(f"✔ [METADATA] Đã ghi thành công bộ siêu dữ liệu tại: {output_kit_path}")

def main():
    parser = argparse.ArgumentParser(description="Generate Tri-Shorts Funnel videos (3 Shorts / Week).")
    parser.add_argument("--video", required=True, help="Input 16:9 mp4 master video")
    parser.add_argument("--srt", required=True, help="Input master SRT subtitles")
    parser.add_argument("--output-dir", help="Output directory for Shorts & kit")
    parser.add_argument("--output", help="Optional single output pattern / base name")
    parser.add_argument("--comic-title", default="Return Survival", help="Comic title for SEO prompt")
    args = parser.parse_args()

    video_abs = os.path.abspath(args.video)
    srt_abs = os.path.abspath(args.srt)

    if not os.path.exists(video_abs):
        raise FileNotFoundError(f"Video file not found: {video_abs}")
    if not os.path.exists(srt_abs):
        raise FileNotFoundError(f"SRT file not found: {srt_abs}")

    output_dir = os.path.abspath(args.output_dir or os.path.dirname(video_abs))
    os.makedirs(output_dir, exist_ok=True)

    master_filename = os.path.basename(video_abs)
    base_name = re.sub(r"_1080p\.mp4|\.mp4", "", master_filename)

    total_duration = get_video_duration(video_abs)
    print("=" * 70)
    print(f"🚀 KHỞI ĐỘNG HỆ THỐNG TRI-SHORTS FUNNEL (3 SHORTS CHO 1 TUẦN)")
    print(f"Video nguồn: {master_filename} ({total_duration/60:.2f} phút / {total_duration:.1f}s)")
    print(f"Thư mục xuất bản: {output_dir}")
    print("=" * 70)

    # 1. Parse SRT and calculate golden windows
    cues = parse_srt(srt_abs)
    print(f"Đã phân tích {len(cues)} cues phụ đề từ file SRT.")
    windows = find_tri_shorts_windows(cues, total_duration)

    temp_dir = os.path.join(output_dir, "temp_shorts_build")
    os.makedirs(temp_dir, exist_ok=True)

    cta_audio_path = os.path.join(temp_dir, "cta_audio.mp3")
    cta_video_path = os.path.join(temp_dir, "cta_video.mp4")

    # Generate shared CTA segment
    generate_cta_audio("¡Mira el video completo en el enlace relacionado abajo!", cta_audio_path)
    render_cta_video(cta_audio_path, cta_video_path)

    short_outputs = [
        os.path.join(output_dir, f"{base_name}_SHORTS_1_Intro.mp4"),
        os.path.join(output_dir, f"{base_name}_SHORTS_2_Combat.mp4"),
        os.path.join(output_dir, f"{base_name}_SHORTS_3_Climax.mp4"),
    ]

    # Render each Short
    for idx, win in enumerate(windows):
        out_mp4 = short_outputs[idx]
        render_single_short(video_abs, cues, win, out_mp4, temp_dir, cta_video_path)

    # Generate Metadata Kit
    kit_path = os.path.join(output_dir, "youtube_shorts_kit.txt")
    video_filenames = [os.path.basename(p) for p in short_outputs]
    generate_tri_shorts_metadata_kit(args.comic_title, master_filename, windows, kit_path, video_filenames)

    # Cleanup temp directory
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass

    print("\n" + "=" * 70)
    print("🎉 HOÀN TẤT TRỌN GÓI 3 YOUTUBE SHORTS & BỘ SIÊU DỮ LIỆU ĐĂNG BÀI!")
    for out_p in short_outputs:
        print(f"  📱 {os.path.basename(out_p)} ({os.path.getsize(out_p)/(1024*1024):.2f} MB)")
    print(f"  📋 {os.path.basename(kit_path)}")
    print("=" * 70)

if __name__ == "__main__":
    main()
