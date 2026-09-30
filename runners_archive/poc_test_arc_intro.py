import os
import sys
import asyncio
import time
from arc_intro_engine import (
    ArcClimaxMiner,
    InMediasResHookGenerator,
    MicroIntroRenderer,
    FastIntroPrepender
)

async def run_poc():
    print("=======================================================")
    print("  STARTING GLOBAL ARC FLASH-FORWARD INTRO ENGINE PoC")
    print("=======================================================")
    
    download_dir = os.path.abspath("downloads/hiding_out_in_an_apocalypse_1_101_en_3724ae4c")
    if not os.path.exists(download_dir):
        print(f"Error: dataset directory not found: {download_dir}")
        return

    # STEP 1: Scan for climax episode
    t0 = time.time()
    print("\n>>> Step 1: Scanning 101 episodes for future climax moments...")
    climax_info = ArcClimaxMiner.scan_climax_episode(download_dir, from_ep=1, to_ep=101, min_future_offset=10)
    t_scan = time.time() - t0
    climax_ep = climax_info["climax_episode"]
    print(f"[SUCCESS] Best Climax Episode: Episode {climax_ep} (Score: {climax_info['climax_score']}) in {t_scan:.2f}s")
    print(f"Sample narration: {climax_info['climax_narration_sample'][:150]}...")

    # STEP 2: Select top visual action panels
    t0 = time.time()
    print(f"\n>>> Step 2: Selecting top visual action panels from Episode {climax_ep}...")
    images = ArcClimaxMiner.select_top_climax_images(download_dir, climax_episode=climax_ep, num_images=3, min_point_threshold=80)
    t_img = time.time() - t0
    print(f"[SUCCESS] Selected {len(images)} top panels in {t_img:.2f}s:")
    for idx, im in enumerate(images, 1):
        print(f"  {idx}. {im['filename']} | Score: {im['score']} | Composite: {im.get('composite', 0):.1f}")
    image_paths = [im["path"] for im in images]

    # STEP 3: Generate In Medias Res Hook Script
    print("\n>>> Step 3: Generating In Medias Res Hook Script...")
    hook_script = InMediasResHookGenerator.generate_hook_script(
        comic_title="Hiding Out In An Apocalypse",
        protagonist_name="Hunter Park",
        climax_episode=climax_ep,
        language="en"
    )
    print("[SUCCESS] Hook Script Generated:")
    print(f"\"{hook_script}\"")
    print(f"Word count: {len(hook_script.split())} words (~15-18s reading time)")

    # STEP 4: Render Micro-Intro Clip
    t0 = time.time()
    intro_output_dir = os.path.join(download_dir, "test_poc_intro")
    print(f"\n>>> Step 4: Rendering 15-20s Micro-Intro Clip to {intro_output_dir}...")
    intro_result = await MicroIntroRenderer.render_intro_clip(
        intro_dir=intro_output_dir,
        hook_script=hook_script,
        image_paths=image_paths,
        language="en",
        voice_id="ai33pro",
        target_resolution=(1920, 1080),
        fps=30
    )
    t_render = time.time() - t0
    print(f"[SUCCESS] Micro-Intro rendered in {t_render:.2f}s!")
    print(f"  Video: {intro_result['video_path']} ({os.path.getsize(intro_result['video_path']) / (1024*1024):.2f} MB)")
    print(f"  Duration: {intro_result['duration']:.2f} seconds")
    print(f"  SRT: {intro_result['srt_path']}")

    # STEP 5: Fast Prepend to Episode 1
    t0 = time.time()
    ep1_video = os.path.join(download_dir, "episode_1", "video.mp4")
    ep1_srt = os.path.join(download_dir, "episode_1", "transcript.srt")
    out_video = os.path.join(intro_output_dir, "episode_1_with_flash_forward_intro.mp4")
    out_srt = os.path.join(intro_output_dir, "episode_1_with_flash_forward_intro.srt")

    print(f"\n>>> Step 5: Prepending Flash-Forward Intro to Episode 1...")
    prepend_ok = FastIntroPrepender.prepend_intro(
        intro_video_path=intro_result["video_path"],
        intro_srt_path=intro_result["srt_path"],
        intro_duration=intro_result["duration"],
        target_video_path=ep1_video,
        target_srt_path=ep1_srt,
        output_video_path=out_video,
        output_srt_path=out_srt
    )
    t_prepend = time.time() - t0
    if prepend_ok:
        print(f"[SUCCESS] Prepending completed in {t_prepend:.2f}s without re-encoding!")
        print(f"  Combined Video: {out_video} ({os.path.getsize(out_video) / (1024*1024):.2f} MB)")
        print(f"  Combined SRT: {out_srt}")
    else:
        print("[FAIL] Prepend operation failed.")

    print("\n=======================================================")
    print(f"  PoC FINISHED SUCCESSFULLY! Total time: {t_scan + t_img + t_render + t_prepend:.2f}s")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(run_poc())
