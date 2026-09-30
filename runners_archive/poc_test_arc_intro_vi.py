import os
import sys
import asyncio
import time
import config
from arc_intro_engine import (
    ArcClimaxMiner,
    DynamicHookDirector,
    MicroIntroRenderer,
    FastIntroPrepender
)

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

async def run_vietnamese_intros():
    print("==================================================================")
    print("  GENERATING VIETNAMESE FLASH-FORWARD INTROS (JESSA DEFAULT VOICE)")
    print(f"  Voice: {config.DEFAULT_VI_VOICE} ({config.DEFAULT_VI_VOICE_ID})")
    print(f"  Reference Audio: {config.DEFAULT_VI_REF_AUDIO}")
    print("==================================================================")

    # -------------------------------------------------------------
    # CASE 1: Veteran of the Apocalypse (Cửu Binh Tận Thế - 100% Tiếng Việt)
    # -------------------------------------------------------------
    veteran_vi_dir = os.path.abspath("downloads/veteran_of_the_apocalypse_1_2_vi_e826e8f9")
    veteran_30_dir = os.path.abspath("downloads/veteran_of_the_apocalypse_1_30_en_e826e8f9")

    if os.path.exists(veteran_vi_dir):
        print("\n>>> [CASE 1] Processing: Cửu Binh Tận Thế (Kang Seongho) - Giọng Jessa...")
        source_dir = veteran_30_dir if os.path.exists(veteran_30_dir) else veteran_vi_dir
        to_ep = 30 if os.path.exists(veteran_30_dir) else 2
        
        climax_scan = ArcClimaxMiner.scan_climax_episode(source_dir, from_ep=1, to_ep=to_ep, min_future_offset=1 if to_ep <= 2 else 10)
        c_ep = climax_scan["climax_episode"]
        print(f"  -> Tập cao trào: Tập {c_ep} (Score: {climax_scan['climax_score']})")

        images_v = ArcClimaxMiner.select_top_climax_images(
            source_dir, climax_episode=c_ep, num_images=3, min_point_threshold=70
        )
        image_paths_v = [im["path"] for im in images_v]
        for idx, im in enumerate(images_v, 1):
            print(f"     Panel {idx}: {im['filename']} | Điểm hành động: {im['score']} | Tỷ lệ trắng: {im.get('white_ratio', 0):.1%}")

        hook_res = await DynamicHookDirector.generate_dynamic_retention_hook(
            comic_title="Cửu Binh Tận Thế",
            protagonist_name="Kang Seongho",
            climax_episode=c_ep,
            climax_text=climax_scan.get("climax_narration_sample", ""),
            origin_text=climax_scan.get("origin_narration_sample", ""),
            language="vi"
        )
        hook_script_kang = hook_res["hook_script"]
        print(f"  -> Archetype: [{hook_res['archetype']}]")
        print(f"  -> Kịch bản Hook (Jessa): \"{hook_script_kang}\"")

        intro_dir_veteran = os.path.join(veteran_vi_dir, "test_poc_dynamic_intro")
        os.makedirs(intro_dir_veteran, exist_ok=True)
        t0 = time.time()
        res_v = await MicroIntroRenderer.render_intro_clip(
            intro_dir=intro_dir_veteran,
            hook_script=hook_script_kang,
            image_paths=image_paths_v,
            language="vi",
            voice_id=config.DEFAULT_VI_VOICE_ID,
            ref_audio_path=config.DEFAULT_VI_REF_AUDIO,
            enable_sfx=True,
            target_resolution=(1920, 1080),
            fps=30
        )
        print(f"  -> [SUCCESS] Đã render intro trong {time.time() - t0:.2f}s! Thời lượng: {res_v['duration']:.2f}s")
        print(f"     Intro Video: {res_v['video_path']}")
        print(f"     Intro Audio: {res_v['audio_path']}")

        ep1_v_video = os.path.join(veteran_vi_dir, "episode_1", "video.mp4")
        ep1_v_srt = os.path.join(veteran_vi_dir, "episode_1", "transcript.srt")
        out_v_video = os.path.join(intro_dir_veteran, "episode_1_with_dynamic_intro_vi.mp4")
        out_v_srt = os.path.join(intro_dir_veteran, "episode_1_with_dynamic_intro_vi.srt")

        prep_ok = FastIntroPrepender.prepend_intro(
            intro_video_path=res_v["video_path"],
            intro_srt_path=res_v["srt_path"],
            intro_duration=res_v["duration"],
            target_video_path=ep1_v_video,
            target_srt_path=ep1_v_srt,
            output_video_path=out_v_video,
            output_srt_path=out_v_srt
        )
        print(f"  -> [SUCCESS] Ghép nối vào Tập 1 hoàn tất (Success={prep_ok})")
        print(f"     Video hoàn chỉnh: {out_v_video} (Dung lượng: {os.path.getsize(out_v_video):,} bytes)")

    # -------------------------------------------------------------
    # CASE 2: Hiding Out In An Apocalypse (101 Episodes Dataset)
    # -------------------------------------------------------------
    apoc_dir = os.path.abspath("downloads/hiding_out_in_an_apocalypse_1_101_en_3724ae4c")
    if os.path.exists(apoc_dir):
        print("\n>>> [CASE 2] Processing: Hiding Out In An Apocalypse (Hunter Park - Giọng Jessa)...")
        climax_ep = 100
        images = ArcClimaxMiner.select_top_climax_images(
            apoc_dir, climax_episode=climax_ep, num_images=3, min_point_threshold=80
        )
        image_paths = [im["path"] for im in images]

        hook_res_apoc = await DynamicHookDirector.generate_dynamic_retention_hook(
            comic_title="Trốn Thoát Trong Tận Thế",
            protagonist_name="Hunter Park",
            climax_episode=climax_ep,
            language="vi"
        )
        hook_script_vi = hook_res_apoc["hook_script"]
        print(f"  -> Archetype: [{hook_res_apoc['archetype']}]")
        print(f"  -> Kịch bản Hook (Jessa): \"{hook_script_vi}\"")

        intro_output_dir_vi = os.path.join(apoc_dir, "test_poc_intro_vi")
        os.makedirs(intro_output_dir_vi, exist_ok=True)
        t0 = time.time()
        res = await MicroIntroRenderer.render_intro_clip(
            intro_dir=intro_output_dir_vi,
            hook_script=hook_script_vi,
            image_paths=image_paths,
            language="vi",
            voice_id=config.DEFAULT_VI_VOICE_ID,
            ref_audio_path=config.DEFAULT_VI_REF_AUDIO,
            enable_sfx=True,
            target_resolution=(1920, 1080),
            fps=30
        )
        print(f"  -> [SUCCESS] Đã render intro trong {time.time() - t0:.2f}s! Thời lượng: {res['duration']:.2f}s")
        print(f"     Intro Video: {res['video_path']}")

        ep1_video = os.path.join(apoc_dir, "episode_1", "video.mp4")
        ep1_srt = os.path.join(apoc_dir, "episode_1", "transcript.srt")
        out_video = os.path.join(intro_output_dir_vi, "episode_1_with_flash_forward_intro_vi.mp4")
        out_srt = os.path.join(intro_output_dir_vi, "episode_1_with_flash_forward_intro_vi.srt")

        prep_ok = FastIntroPrepender.prepend_intro(
            intro_video_path=res["video_path"],
            intro_srt_path=res["srt_path"],
            intro_duration=res["duration"],
            target_video_path=ep1_video,
            target_srt_path=ep1_srt,
            output_video_path=out_video,
            output_srt_path=out_srt
        )
        print(f"  -> [SUCCESS] Ghép nối vào Tập 1 hoàn tất (Success={prep_ok})")
        print(f"     Video hoàn chỉnh: {out_video}")

    print("\n==================================================================")
    print("  ĐÃ HOÀN TẤT RENDER TẤT CẢ FLASH-FORWARD INTROS VỚI GIỌNG JESSA!")
    print("==================================================================")

if __name__ == "__main__":
    asyncio.run(run_vietnamese_intros())
