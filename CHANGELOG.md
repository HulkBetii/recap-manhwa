# Changelog & Version History

Tài liệu ghi lại toàn bộ lịch sử phát hành, các mốc kiến trúc và tính năng đã được kiểm chứng của hệ thống **Recap Comics Automation**.

---

## [v1.5.0] - 2026-09-14
### 🚀 Milestone: Marathon Recaps & Universal Narrative Arc Engine
Phiên bản chốt chặn độ ổn định cao (Stable Production Baseline), đánh dấu khả năng tự động hóa 100% quy trình sản xuất video recap marathon siêu dài (đã kiểm chứng thực tế lên tới 120 tập, 7 giờ 15 phút, 1080p).

### 1. Kiến Trúc Pipeline 14 Giai Đoạn (14-Stage Workflow)
- **Stage 0 - Project Init**: Khởi tạo thư mục task, kiểm tra tài nguyên hệ thống, dọn dẹp tiến trình treo.
- **Stage 1 - Comic Parsing**: Trích xuất metadata bộ truyện, danh sách tập hợp lệ thông qua `chapter_resolver.py`.
- **Stage 2 - Async Image Crawling**: Cào ảnh song song tốc độ cao với cơ chế fallback headless browser và anti-blocking.
- **Stage 2b - Intelligent Repagination**: Cắt ghép các webtoon strip dài thành các trang tiêu chuẩn đọc tối ưu.
- **Stage 3 - NSFW Moderation (Selective Pipeline)**: Nhận diện và che mờ vùng nhạy cảm bằng Grounding DINO + SAM-ViT, bảo vệ kênh khỏi vi phạm nguyên tắc cộng đồng YouTube.
- **Stage 4 - PDF Generation**: Đóng gói các trang truyện thành tệp PDF phân giải cao phục vụ OCR / VLM.
- **Stage 5 - Gemini Automation**: Tự động phân tích hình ảnh và tạo kịch bản dẫn chuyện (Narration Script) bằng Gemini 1.5/2.0 Flash với cơ chế luân chuyển profile Chrome và New Chat tự phục hồi.
- **Stage 6 - JSON Extraction & Healing**: Phân tích cú pháp phản hồi, trích xuất cấu trúc kịch bản theo từng khung tranh.
- **Stage 7 - Narration Aggregation & Anti-Loop**: Tổng hợp lời thoại, áp dụng chốt chặn phát hiện và loại bỏ vòng lặp kịch bản (Anti-Loop Guardrail).
- **Stage 8 - Local TTS Engine**: Sinh giọng đọc lồng tiếng ngoại tuyến chất lượng cao với OmniVoice Voice Cloning hoặc Kokoro TTS.
- **Stage 9 - Subtitle Normalization**: Chuẩn hóa phụ đề SRT theo thời lượng thực tế của file âm thanh lồng tiếng, canh chỉnh millisecond.
- **Stage 10 - Episode Video Rendering**: Dựng video từng tập với chuyển động camera kép (Dual Sub-shot Motion: Pan & Zoom, Ken Burns), xử lý pacing ngắt nghỉ tự nhiên.
- **Stage 11 - Final Video Assembly**: Ghép nối các tập thành Master Video (MP4 Faststart) bằng Concat Demuxer không re-encode, gộp phụ đề tổng thể.
- **Stage 12 - Metadata Reports & YouTube Upload Kit**: Tự động sinh trọn bộ tài liệu YouTube (Tiêu đề SEO, Mô tả, Chapters diễn biến, Pinned Comment, Tags Studio, Master Prompt tạo Thumbnail bằng GPT-4o).
- **Stage 13 - Cleanup**: Tùy chọn dọn dẹp các tệp trung gian nhằm tiết kiệm dung lượng ổ đĩa.

### 2. Form Chung Chapters Theo Diễn Biến Video (Universal Narrative Arcs)
- **Chuẩn hóa Chapters YouTube**: Tự động phân bổ timeline video thành 6 – 10 Hồi cốt truyện (Narrative Arcs), thay thế hoàn toàn việc liệt kê cơ học `Episode 1`, `Episode 2`.
- **Đảm bảo quy chuẩn YouTube**: Timestamp đầu tiên bắt buộc `00:00`, các mốc sau tăng dần đều theo thời lượng thực tế, hiển thị khoảng tập `(Ep X–Y)`.
- **Hỗ trợ 5 Archetypes cốt truyện**:
  - `zombie_apocalypse`: Bùng nổ đại dịch, cố thủ chung cư, trạm kiểm soát sụp đổ, chủng biến dị, giải cứu tàn cuộc.
  - `tower_anti_regression`: Tháp ác mộng, từ chối hồi quy, độc hành tầng 100, phá vỡ hệ thống, chiến vương hỗn mang.
  - `hunter_gate`: Cổng thảm họa, kẻ yếu thức tỉnh, thợ săn độc hành, đại chiến bang hội, quân vương hư vô.
  - `bunker_prepper`: Cảnh báo ngày tận thế, hầm trú ẩn vô hạn, chống chọi băng vĩnh cửu, thống trị vùng hoang tàn.
  - `general_apocalypse`: Thảm họa bất ngờ, bản năng sinh tồn, đột phá năng lực, xâm nhập sào huyệt, kỷ nguyên mới.
- **Pinned Comment đồng bộ**: Tự động trích xuất timeline các Arcs vào bình luận ghim sẵn sàng copy-paste.

### 3. Hệ Thống Giọng Đọc (OmniVoice Voice Cloning Registry)
- **Tiếng Anh (Mỹ - US)**: Preset `clone_andrew` ("Andrew - Smooth, Smart and Clear") tối ưu cho ngách US Manhwa Recap.
- **Tiếng Việt (VN)**: Preset `clone_jessa` ("Jessa - Easygoing and Effortless").
- Tích hợp chuẩn hóa âm lượng, tự động tải reference audio & text cache, tăng tốc suy luận diffusion 16 bước.

### 4. Cơ Chế Chốt Chặn Toàn Vẹn & Chất Lượng (Quality Guardrails)
- **Chapter Integrity Guard (`chapter_resolver.py`)**: Ánh xạ số tập dựa trên giá trị số học tuyệt đối (Value-based Numeric Matching), chấm dứt hoàn toàn lỗi lệch số tập (off-by-one / index offset).
- **Anti-Loop Narration Guardrail**: Quét độ tương đồng ngữ nghĩa (Jaccard / N-gram), tự động cắt bỏ câu lặp vô hạn do AI sinh ra.
- **Dual Sub-shot Motion**: Cắt đôi chuyển động khung hình cho các câu thoại dài (>4.2s), loại bỏ cảm giác tĩnh và giữ chân người xem.
- **Dynamic BGM Ducking**: Tự động hạ âm lượng nhạc nền khi có lời thoại thuyết minh và nâng dần khi ngắt câu.

### 5. Dữ Liệu Kiểm Chứng (Verification Benchmarks)
- **Zombie Revelation: 82-08**: 120 tập (Full Story), video 1080p dài **7 giờ 15 phút 22 giây** (4.09 GB), phụ đề SRT 525 KB, hoàn thành xuất sắc 100%.
- **The World After The Fall**: Chạy thành công các kịch bản kiểm thử tiếng Anh và tiếng Việt.
- **Bộ kiểm thử tự động**: 11/11 tests pass trong `pytest tests/test_us_apocalypse_market.py tests/test_andrew_english_voice.py`.

---

## [v1.0.0] - 2026-09-08
### Initial Release
- Kiến trúc xử lý cơ bản với FastAPI backend và giao diện web tĩnh.
- Tích hợp Kokoro TTS và mô hình kiểm duyệt Grounding DINO ban đầu.
- Hỗ trợ cào ảnh từ các trang webtoon cơ bản.
