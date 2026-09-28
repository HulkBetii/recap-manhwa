# -*- coding: utf-8 -*-
"""
Package all V5.3 deliverables:
1. stage5_v53_benchmark_ep1_ep5.json
2. 5 new SRT files (Episodes 1-5)
3. Stage 12 metadata refresh (Titles, Thumbnail concepts, Chapter timestamps)
4. stage5_prompt_runtime_dump.txt (Episodes 1-5 prompts)
5. v5_3_validation_package_ep1_ep5.zip
"""
import os
import sys
import json
import shutil
import zipfile

PROJECT_ROOT = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import generate_gemini_prompt
from story_memory import StoryMemory
from markets.us_apocalypse.metadata import generate_us_apocalypse_metadata

def main():
    download_dir = os.path.join(PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_143_en_946016ec")
    pkg_dir = os.path.join(PROJECT_ROOT, "v5_3_package")
    os.makedirs(pkg_dir, exist_ok=True)
    os.makedirs(os.path.join(pkg_dir, "srt"), exist_ok=True)

    # 1. stage5_v53_benchmark_ep1_ep5.json
    bench_src = os.path.join(download_dir, "output", "v5_3_retention_benchmark_ep1_5.json")
    bench_dst = os.path.join(PROJECT_ROOT, "stage5_v53_benchmark_ep1_ep5.json")
    if os.path.exists(bench_src):
        shutil.copy2(bench_src, bench_dst)
        shutil.copy2(bench_src, os.path.join(pkg_dir, "stage5_v53_benchmark_ep1_ep5.json"))
        print("[1] Copied stage5_v53_benchmark_ep1_ep5.json")

    # 2. 5 New SRT Files
    print("[2] Packaging 5 SRT files:")
    for ep in range(1, 6):
        src_srt = os.path.join(download_dir, f"episode_{ep}", "transcript.srt")
        dst_srt = os.path.join(pkg_dir, "srt", f"episode_{ep}_transcript.srt")
        if os.path.exists(src_srt):
            shutil.copy2(src_srt, dst_srt)
            print(f"  - Episode {ep} SRT -> {dst_srt}")

    # 3. stage5_prompt_runtime_dump.txt
    print("[3] Generating stage5_prompt_runtime_dump.txt:")
    memory = StoryMemory.load(download_dir, comic_title="Zombie Revelation: 82-08", language="en")
    
    prompt_dumps = []
    header = "=" * 80 + "\nSTAGE 5 V5.3 PROMPT RUNTIME DUMP (EPISODES 1-5)\n" + "=" * 80 + "\n\n"
    prompt_dumps.append(header)

    for ep in range(1, 6):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        img_pdf_dir = os.path.join(ep_dir, "images_pdf")
        page_count = len([f for f in os.listdir(img_pdf_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]) if os.path.exists(img_pdf_dir) else 50
        
        prev_ctx = memory.get_previous_context(ep, download_dir=download_dir) if ep > 1 else {"protagonist_name": "Tae", "protagonist_gender": "male"}
        
        prompt = generate_gemini_prompt(
            comic_title="Zombie Revelation: 82-08",
            ep=ep,
            total_pages=page_count,
            target_language="en",
            market_id="us_apocalypse",
            previous_context=prev_ctx
        )
        
        ep_banner = f"\n{'#'*80}\n### EPISODE {ep} STAGE 5 PROMPT (V5.3)\n{'#'*80}\n\n"
        prompt_dumps.append(ep_banner + prompt + "\n\n")

    dump_path = os.path.join(PROJECT_ROOT, "stage5_prompt_runtime_dump.txt")
    with open(dump_path, "w", encoding="utf-8") as f:
        f.writelines(prompt_dumps)
    shutil.copy2(dump_path, os.path.join(pkg_dir, "stage5_prompt_runtime_dump.txt"))
    print(f"  Saved {dump_path}")

    # 4. Refresh Stage 12 Metadata with V5.3 recaps
    print("[4] Refreshing Stage 12 Metadata:")
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation: 82-08",
        comic_url="https://www.webtoons.com/en/action/zombie-revelation-82-08/list?title_no=6065",
        from_ep=1,
        to_ep=143,
        download_dir=download_dir
    )
    upload_kit_path = os.path.join(download_dir, "output", "youtube_upload_kit.txt")
    metadata_json_path = os.path.join(download_dir, "output", "metadata.json")
    with open(metadata_json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    shutil.copy2(upload_kit_path, os.path.join(pkg_dir, "youtube_upload_kit.txt"))
    shutil.copy2(metadata_json_path, os.path.join(pkg_dir, "metadata.json"))
    print(f"  Updated metadata.json & youtube_upload_kit.txt")

    # 5. Create zip archive
    zip_path = os.path.join(PROJECT_ROOT, "v5_3_validation_package_ep1_ep5.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(pkg_dir):
            for file in files:
                full_p = os.path.join(root, file)
                rel_p = os.path.relpath(full_p, pkg_dir)
                z.write(full_p, rel_p)
    print(f"[5] Created zip package: {zip_path}")
    print("\nAll deliverables packaged successfully!")

if __name__ == "__main__":
    main()
