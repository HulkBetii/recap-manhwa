import os
import sys
import json
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.chdir(Path(__file__).resolve().parent)

download_dir = r"downloads\veteran_of_the_apocalypse_1_5_vi_e826e8f9"

print("=" * 80)
print("  DANH SÁCH PHÂN ĐOẠN MỞ ĐẦU (SEGMENT 1) TỪNG TẬP")
print("=" * 80)

for ep in range(1, 6):
    recap_p = os.path.join(download_dir, f"episode_{ep}", "recap.json")
    with open(recap_p, "r", encoding="utf-8") as f:
        recap = json.load(f)
    seg0 = recap[0]
    pages = [img["page"] for img in seg0.get("images", [])]
    sp = seg0.get("speech", "")
    print(f"Tập {ep} Seg 1 (Trang {pages}): \"{sp}\"")
