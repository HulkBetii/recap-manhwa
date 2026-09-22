# Đặc Tả Kiến Trúc Quy Trình Tinh Gọn 5 Giai Đoạn (Modular 5-Phase Workflow Specification)

Tài liệu này đặc tả toàn diện kiến trúc, luồng điều phối (pipelined orchestration), thiết kế module hóa và chi tiết kỹ thuật của hệ thống **Recap Comics Video Generator** sau khi đã tinh gọn từ 14 stage vụn vặt thành **5 Giai Đoạn Cốt Lõi (5 Modular Phases)**.

---

## 1. Bản Đồ Chuyển Đổi & Quy Ước Đặt Tên 5 Giai Đoạn (Phase Definition)

| Phase | Tên Giai Đoạn Cốt Lõi | Trọng Số (`weight`) | Phân Vùng Chức Năng |
|---|---|:---:|---|
| **Phase 1** | **Phase 1 - Thu thập & Xử lý Hình ảnh**<br>*(Visual Ingestion & PDF Preparation)* | 30% | Phân tích URL comic, Crawl ảnh tuần tự, Cắt chia layout thông minh (YOLOv11), Lọc kiểm duyệt NSFW (DINO+SAM) và xuất file PDF chất lượng cao. |
| **Phase 2** | **Phase 2 - Tạo Kịch bản AI VLM**<br>*(AI Vision Script Generation)* | 25% | Đẩy file PDF lên Gemini Web Automation bằng 1 browser window / 1 profile, tự động xoay vòng profile khi limit model Flash, cơ chế 9 cấp retry (3 web x 3 tool). |
| **Phase 3** | **Phase 3 - Xử lý Cấu trúc Kịch bản**<br>*(Script Structuring & Narration)* | 10% | Trích xuất JSON siêu bền vững, chuẩn hóa câu thoại phân cảnh, tạo SSML và làm sạch thẻ trích dẫn / thinking. |
| **Phase 4** | **Phase 4 - Giọng đọc TTS & Phụ đề**<br>*(Voice Synthesis & Subtitles)* | 15% | Tạo âm thanh lồng tiếng bằng EdgeTTS/Kokoro chất lượng cao, căn chỉnh thời lượng từng phân cảnh và xuất file phụ đề chuẩn SRT. |
| **Phase 5** | **Phase 5 - Ghép Nối & Xuất Bản**<br>*(Video Rendering & Final Export)* | 20% | Render video từng tập song song (tối đa 3 luồng), ghép nối thành video tổng hợp (Final Assembly), tạo metadata báo cáo và dọn dẹp file rác. |

---

## 2. Sơ Đồ Luồng Điều Phối Gối Đầu (Pipelined Workflow Execution)

```
                            [Khởi Tạo Nhiệm Vụ: Tập 1 -> N]
                                          │
                                          ▼
   ════════════════════════════════════════════════════════════════════════════════════
   PHASE 1: THU THẬP & XỬ LÝ HÌNH ẢNH (BARRIER PHASE)
   ────────────────────────────────────────────────────────────────────────────────────
   Crawl ảnh:   Tập 1 ─────────► Tập 2 ─────────► Tập 3 ─────────► ... ─────────► Tập N (Tuần tự)
                  │                │                │                               │
                  ▼                ▼                ▼                               ▼
   Visual/PDF:  PDF 1 (bg)       PDF 2 (bg)       PDF 3 (bg)                      PDF N (bg)
                (Chạy song song ngay khi crawl xong mỗi tập, tối đa 3 luồng)
   ════════════════════════════════════════════════════════════════════════════════════
                                          │
                        [Barrier Check: Tất cả tập đều có PDF]
                                          │
                                          ▼
   ════════════════════════════════════════════════════════════════════════════════════
   PHASE 2 -> PHASE 5: TẠO KỊCH BẢN TUẦN TỰ & HẬU KỲ GỐI ĐẦU SONG SONG
   ────────────────────────────────────────────────────────────────────────────────────
   Gemini Scripting (1 luồng Playwright, 1 Profile/Browser):
   Tập 1 Scripting ──────────► Tập 2 Scripting ──────────► Tập 3 Scripting ──────────► ...
          │                           │                           │
          ▼ (Bắn ngay sang bg)        ▼ (Bắn ngay sang bg)        ▼ (Bắn ngay sang bg)
   ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
   │ Hậu kỳ & TTS  │           │ Hậu kỳ & TTS  │           │ Hậu kỳ & TTS  │
   │   (Phase 3-4) │           │   (Phase 3-4) │           │   (Phase 3-4) │
   └──────┬────────┘           └──────┬────────┘           └──────┬────────┘
          │                           │                           │
          ▼                           ▼                           ▼
   ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
   │ Render Video  │           │ Render Video  │           │ Render Video  │
   │  (3 luồng max)│           │  (3 luồng max)│           │  (3 luồng max)│
   └───────────────┘           └───────────────┘           └───────────────┘
   ════════════════════════════════════════════════════════════════════════════════════
                                          │
                        [Barrier Check: Tất cả tập đều có Video]
                                          │
                                          ▼
   ════════════════════════════════════════════════════════════════════════════════════
   PHASE 5: FINAL ASSEMBLY & METADATA EXPORT
   ────────────────────────────────────────────────────────────────────────────────────
   Ghép nối Video Final ──► Tạo Phụ Đề Final ──► Xuất Metadata & Report ──► Cleanup
   ════════════════════════════════════════════════════════════════════════════════════
```

---

## 3. Kiến Trúc Cấu Trúc Module (`pipeline/`)

Toàn bộ logic được chia tách thành các module chuyên biệt theo đúng nguyên lý SOLID:

```text
pipeline/
├── interfaces.py                  # Định nghĩa Abstract BaseStage, IStage, IEpisodeProcessor
├── orchestrator.py                # Nhạc trưởng điều phối luồng đa tập (Pipelining Orchestrator)
└── stages/
    ├── __init__.py                # Export thống nhất các Phase 1 -> 5
    ├── stage1_visual.py           # Phase 1: Ingestion, Crawling, Smart Paging, NSFW, PDF Export
    ├── stage2_script.py           # Phase 2: Gemini Playwright Automation, Profile Rotator, Safe Mode
    ├── stage3_audio.py            # Phase 3 & 4: JSON Parsing, SSML Dialogue, TTS Synthesis, Subtitles
    ├── stage4_render.py           # Phase 4 & 5: Video Engine Render từng tập (3 luồng)
    └── stage5_export.py           # Phase 5: Final Concat Demuxer, Metadata Reports, Cleanup
```

---

## 4. Chi Tiết Kỹ Thuật 5 Giai Đoạn

### Giai Đoạn 1: Thu Thập & Chuẩn Hóa Hình Ảnh (Phase 1)
* **Đầu vào**: Comic URL, danh sách tập cần crawl (`from_episode` $\to$ `to_episode`).
* **Logic điều phối**:
  1. Crawl tuần tự từng tập từ $1 \to N$ để chống Cloudflare/WAF block.
  2. Ngay khi một tập crawl ảnh xong, bắn ngay tác vụ `_run_visual_and_pdf` chạy nền song song (tối đa 3 luồng).
  3. Áp dụng AI YOLOv11 nhận diện frame/panel tranh, thuật toán Quy hoạch động (DP) phân trang cắt dọc, bóc tách bong bóng thoại tiếng nước ngoài.
  4. Lọc nội dung nhạy cảm / NSFW và kết xuất file PDF chất lượng cao `episode_{ep}/pdf/`.
* **Đầu ra**: File PDF hoàn chỉnh và thư mục ảnh đã tiền xử lý cho mỗi tập.

### Giai Đoạn 2: Tạo Kịch Bản AI VLM (Phase 2)
* **Nguyên tắc Browser/Profile**: Chỉ mở **duy nhất 1 cửa sổ trình duyệt + 1 profile** tại một thời điểm, chạy đơn luồng.
* **Cơ chế Xoay Vòng Profile (Profile Rotation)**:
  * Khi mở trang `gemini.google.com`, kiểm tra limit model Flash. Nếu model bị Rate Limit, đóng hoàn toàn browser cũ và mở profile tiếp theo ($1 \to 2 \to 3 \to 1 \dots$).
* **Cơ chế 9 Cấp Retry Ladder**:
  * **Level Web (Nút Redo)**: Khi Gemini trả về response lỗi hoặc thiếu dấu phân tách `#`, tự động bấm Redo / Try Again trên giao diện web tối đa 3 lần.
  * **Level Tool**: Nếu sau 3 lần Redo web vẫn thất bại, reload tab và làm lại tool (tối đa 3 lần).
  * **Safe Mode Escalation**: Ở lần tool thứ 3, tự động kích hoạt chế độ DINO+SAM làm mờ/che các vùng tranh nhạy cảm trước khi tái xuất PDF và gửi lại.
  * **Tổng cộng**: $3 \text{ Tool Attempts} \times 3 \text{ Web Redos} = 9 \text{ lần retry}$.

### Giai Đoạn 3 & 4: Xử Lý Kịch Bản, Lồng Tiếng TTS & Phụ Đề (Phase 3 & Phase 4)
* **Trích xuất kịch bản**: Chuyển đổi văn bản phản hồi từ Gemini thành danh sách phân cảnh chuẩn hóa `recap.json`.
* **Tổng hợp lời dẫn (SSML Aggregation)**: Làm sạch câu từ, chèn thẻ ngừng nghỉ tự nhiên.
* **Tạo Audio & Subtitle**:
  * Sử dụng EdgeTTS hoặc Kokoro tạo giọng đọc `audio.mp3` cho từng phân cảnh.
  * Ghép nối và tính toán chính xác timestamp xuất file phụ đề `transcript.srt`.

### Giai Đoạn 5: Render Video & Xuất Bản Hoàn Chỉnh (Phase 5)
* **Pipelining Render**: Ngay khi một tập tạo xong kịch bản ở Phase 2, tập đó được đẩy sang chạy nền Phase 3 $\to$ Phase 4 $\to$ Phase 5 (Render Video), trong khi Gemini lập tức chuyển sang tạo kịch bản cho tập tiếp theo.
* **Render Video Đa Luồng**: Giới hạn tối đa 3 tiến trình render video chạy đồng thời (`asyncio.Semaphore(3)`).
* **Final Assembly**:
  * Ghép nối tất cả các file video tập thành `final_video.mp4` bằng FFmpeg không nén lại (Stream Copy Concat).
  * Gộp phụ đề toàn bộ các tập thành `final_transcript.srt`.
  * Xuất file metadata, thống kê thời lượng và dọn dẹp cache.

---

## 5. Tự Động Khắc Phục Sự Cố (Self-Healing & Auto-Recovery)
1. **Kiểm tra toàn diện trước khi hoàn tất (Phase 3 Barrier)**:
   * Sau khi vòng lặp hoàn tất, hệ thống quét toàn bộ danh sách tập.
   * Nếu có bất kỳ tập nào render lỗi hoặc chưa có video hoàn chỉnh, hệ thống tự động đưa vào danh sách retry để chạy lại riêng các tập đó cho đến khi đủ $100\%$ video các tập.
2. **Khả năng tiếp tục (Idempotency)**:
   * Mọi stage đều nhận diện các file đã tạo (`recap.json`, `audio.mp3`, `video.mp4`), tự động bỏ qua các bước đã hoàn tất khi chạy lại task.
