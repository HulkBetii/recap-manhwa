import os
import sys
import argparse
import asyncio
from typing import Optional

# Fix Unicode output for Windows Console
sys.stdout.reconfigure(encoding='utf-8')

# Ensure we can import app and gemini_api_engine from the parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import load_config
from gemini_api_engine import get_gemini_api_engine

async def generate_qa_report(srt_path: str, output_path: str):
    if not os.path.exists(srt_path):
        print(f"❌ Error: Không tìm thấy file SRT tại: {srt_path}")
        return

    print(f"📖 Đang đọc nội dung file SRT: {srt_path}...")
    with open(srt_path, 'r', encoding='utf-8-sig') as f:
        srt_content = f.read()

    print("🤖 Đang khởi tạo kết nối Gemini qua 9Router...")
    cfg = load_config()
    engine = get_gemini_api_engine(
        base_url=(cfg.get("ninerouter_url") or "").strip(),
        default_model="ag/gemini-3.8-flash-high" # Force a high quality model for reading big texts
    )

    prompt = f"""Bạn là một chuyên gia Chiến lược gia YouTube (YouTube Strategist) & Đạo diễn Nội dung chuyên chấm điểm kịch bản Recap Manhwa (ngôn ngữ Tây Ban Nha).
Người dùng của bạn là chủ kênh YouTube người Việt Nam không biết tiếng Tây Ban Nha.

Nhiệm vụ: Đọc toàn bộ file phụ đề (SRT) Tây Ban Nha bên dưới của một video dài khoảng 1 tiếng, sau đó BÁO CÁO siêu chi tiết bằng TIẾNG VIỆT theo cấu trúc Markdown sau:

# 📋 Báo Cáo Kiểm Định Chất Lượng Nội Dung (QA Report V2)

## 1. Tóm tắt Cốt truyện chính (Plot Summary)
- Video này đang kể về sự kiện gì? (Kể tóm tắt lại diễn biến chính trong 3-4 đoạn).

## 2. Đánh giá Mở bài & Kết bài (Hook & Outro)
- **Đoạn Mở (Hook 15s đầu):** Có giật gân, cuốn hút không? Nó dùng thủ thuật gì?
- **Đoạn Kết (Outro):** Câu chốt có đúng kêu gọi hành động (Subscribe) không? (Dịch ra tiếng Việt).

## 3. Nhịp điệu & Khả năng Giữ chân (Pacing & Retention) 🚨
- **Lỗi Lê thê (Dead Air):** Có phân đoạn nào nhân vật độc thoại/thuyết minh giải thích luật lệ, bối cảnh quá 4 câu liên tục mà không có hành động nào xảy ra không? (Nếu có, BÁO ĐỘNG ĐỎ và chỉ rõ phút thứ mấy).
- Nhịp độ của video có dồn dập, căng thẳng không?

## 4. Tính Khả thi Hình ảnh (Visual Cues) 🖼️
- Kịch bản có sử dụng những từ ngữ mang tính hành động cao (chém, giết, nổ, chạy) để Editor dễ dàng tìm khung hình truyện tranh (panel) ghép vào không? Hay nó quá trừu tượng (ví dụ: suy ngẫm về nhân sinh) khiến video bị tĩnh?

## 5. Phân tích Văn phong (Tone & Style)
- Giọng điệu có chuẩn "Sarcasmo Latino" (ngầu, mỉa mai, tàn nhẫn) của ngách Sinh tồn không? Nêu ví dụ 1-2 câu thoại hay nhất (kèm dịch tiếng Việt).

## 6. Cảnh báo Vi phạm Chính sách (Red Flags) ⚠️
- Kịch bản có chứa từ ngữ bạo lực cực đoan (Masacre, Carnicería), khiêu dâm, hoặc từ ngữ bị cấm trên YouTube không? 

## 7. Chấm điểm & Khuyến nghị (Rating & Actionable Advice)
- Chấm điểm /10. Đưa ra 2 gạch đầu dòng khuyên người dựng video nên làm gì ở khâu edit.

---
NỘI DUNG FILE SRT CẦN PHÂN TÍCH:
{srt_content}
"""

    print("⏳ Đang phân tích kịch bản và lập Báo cáo QA (Quá trình này có thể mất 15-30 giây)...")
    
    try:
        response_text, _ = await engine.generate_content(
            prompt=prompt,
            temperature=0.7,
            max_output_tokens=4096,
            timeout=180
        )
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(response_text)
            
        print(f"\n✅ Hoàn tất! Báo cáo QA Tiếng Việt đã được lưu tại:\n👉 {output_path}")
        
    except Exception as e:
        print(f"\n❌ Lỗi khi gọi LLM: {e}")

def main():
    parser = argparse.ArgumentParser(description="Tạo báo cáo QA Tiếng Việt từ file SRT Tây Ban Nha.")
    parser.add_argument("--srt", required=True, help="Đường dẫn đến file .srt tiếng Tây Ban Nha cần phân tích")
    parser.add_argument("--output", required=False, help="Đường dẫn lưu file báo cáo (Mặc định: lưu cùng thư mục với srt)")
    
    args = parser.parse_args()
    
    output_path = args.output
    if not output_path:
        base_dir = os.path.dirname(args.srt)
        output_path = os.path.join(base_dir, "QA_Report_VI.md")
        
    asyncio.run(generate_qa_report(args.srt, output_path))

if __name__ == "__main__":
    main()
