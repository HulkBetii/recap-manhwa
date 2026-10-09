import os
import sys
import re
import asyncio

PROJECT_DIR = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
FOLDER_NAME = "return_survival_new_1_30_es_9b1e12cd"

sys.stdout.reconfigure(encoding="utf-8")
os.chdir(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

from workflow_stages_2 import merge_srt_files

def get_srt_duration(srt_path):
    if not os.path.exists(srt_path):
        return 0.0
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    time_matches = re.findall(r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})", content)
    if not time_matches:
        return 0.0
    last_end = time_matches[-1][4:] # (hh, mm, ss, mss)
    hrs, mins, secs, msecs = map(int, last_end)
    return hrs * 3600 + mins * 60 + secs + msecs / 1000.0 + 0.5 # 0.5s padding

async def main():
    download_dir = os.path.join(PROJECT_DIR, "downloads", FOLDER_NAME)
    
    print("📦 Đang gộp toàn bộ phụ đề (SRT) của 30 tập thành 1 file thống nhất...")
    srt_paths = []
    durations = []
    
    for ep in range(1, 31):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        srt_p = os.path.join(ep_dir, "transcript.srt")
        srt_paths.append(srt_p)
        dur = get_srt_duration(srt_p)
        durations.append(dur)

    out_srt = os.path.join(download_dir, "output", "upload", "he_returned_in_time_to_prepare_for_the_zombie_outbreak_es_V3.srt")
    merge_srt_files(srt_paths, durations, out_srt)
    print(f"✅ Đã tạo file phụ đề V3 mới nhất tại: {out_srt}")

    print("\n🕵️‍♂️ ĐANG KÍCH HOẠT CONTENT QA AUDITOR ĐỂ CHẤM ĐIỂM KỊCH BẢN V3...")
    from runtime.content_qa_auditor import generate_qa_report
    qa_report_path = os.path.join(download_dir, "output", "upload", "QA_Report_VI_V3.md")
    await generate_qa_report(out_srt, qa_report_path)
    print(f"\n🎉 HOÀN TẤT TẤT CẢ! Báo cáo nghiệm thu V3 đã sẵn sàng tại: {qa_report_path}")

if __name__ == "__main__":
    asyncio.run(main())
