# Kiến Trúc Quy Trình Render Video Recap Truyện Tranh (Manhwa Video Recap Pipeline)

Tài liệu này mô tả chi tiết toàn bộ kiến trúc, luồng xử lý và thuật toán của hệ thống **Render Video Recap Truyện Tranh Manhwa** từ tập ảnh thô (raw webtoon canvas) cho đến video thành phẩm chất lượng cao (MP4 1080p / 9:16 / 16:9).

---

## 1. Sơ Đồ Tổng Quan Quy Trình (End-to-End Architecture)

```
[Raw Webtoon Images (20+ files)]
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Giai Đoạn 1: Phân Trang Thông Minh (Smart Pagination V3)     │
│  ├─ Ghép nối Canvas dài (100k - 300k px)                   │
│  ├─ YOLOv11 Vision AI: Bounding Box (Body, Face, Frame, Text)│
│  ├─ Semantic Safety: Vùng cấm cắt (Forbidden Spans)         │
│  ├─ Speech Bubble Analyzer: Triệt tiêu Orphan Bubbles       │
│  ├─ Boundary Scorer: Chấm điểm rãnh cắt đa tiêu chí         │
│  ├─ Global Page Optimizer: Quy hoạch động (DP Shortest Path)│
│  └─ Taxonomy & Camera Metadata (Focal Points, Camera Hints) │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
[44 Pages Chuẩn + manifest.json + Vocal/TTS Audio + Subtitles]
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Giai Đoạn 2: Lập Kế Hoạch Chuyển Động & Bố Cục Khung Hình   │
│  ├─ TimelineManager: Đồng bộ Audio TTS & Phân đoạn thời gian│
│  ├─ AdaptiveMotionPlanner: Lập quỹ đạo camera (Pan / Zoom)  │
│  │   ├─ Face-Guided Tracking: Tâm mặt nhân vật làm tiêu điểm│
│  │   ├─ Multi-Tier Duration & Easing Curves (Sine / Cubic)  │
│  │   └─ Directional Motion Blur (Mờ chuyển động vật lý)     │
│  └─ ImageComposer: Xử lý nền mờ động (Animated Background)  │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Giai Đoạn 3: Động Cơ Render Trực Tiếp (Streaming Renderer)  │
│  ├─ AdaptiveManhwaRendererV2: Render frame NumPy in-memory  │
│  ├─ Pipe Streaming: Đẩy rawvideo bgr24 qua stdin của FFmpeg │
│  ├─ Mã hóa phần cứng GPU: NVIDIA NVENC (h264_nvenc)        │
│  └─ Audio / Watermark / Subtitle Mixing                     │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
[Video Recap Hoàn Chỉnh (MP4, Chuẩn Full HD, Khung hình mượt)]
```

---

## 2. Giai Đoạn 1: Phân Trang Thông Minh Thế Hệ Mới (Smart Pagination V3)

Mục tiêu: Chuyển đổi dải cuộn vô tận của webtoon thành **35 – 45 trang chất lượng cao**, giàu ngữ cảnh kể chuyện, chuẩn bị hoàn hảo cho chuyển động camera video.

### 2.1. Quét Thị Giác Máy Tính AI (ComicVisionAI)
* **Model**: YOLOv11m huấn luyện chuyên sâu cho manga/manhwa (`weights/manga109_yolo11m.pt`) chạy tăng tốc trên GPU CUDA.
* **4 Lớp đối tượng nhận diện**:
  1. `face`: Khuôn mặt nhân vật (độ ưu tiên bảo vệ tối đa).
  2. `body`: Toàn thân nhân vật (ngăn chặn chém đứt cơ thể, tay chân, vũ khí).
  3. `frame`: Khung tranh (panel borders) để ưu tiên vết cắt rơi đúng mép khung.
  4. `text`: Khung thoại, chữ SFX hiệu ứng.
* **Vùng cấm cắt tuyệt đối (`forbidden_spans`)**:
  - Mọi vùng thân nhân vật được bao bọc vùng an toàn $\pm 25\text{px}$.
  - Mọi vùng mặt được bảo vệ tuyệt đối $100\%$.
  - Mọi bóng thoại được bảo vệ lõi chữ $\pm 15\text{px}$.
  - **Kết quả**: $0$ vi phạm cắt trúng nhân vật (`hit_faces = 0, hit_chars = 0`).

### 2.2. Xử Lý Bóng Thoại & Triệt Tiêu Trang Thoại Cô Lập (SpeechBubbleAnalyzer)
* **Phân loại vai trò bóng thoại**:
  - `EDGE_TOP`: Bóng thoại nằm ở cạnh trên phân cảnh $\to$ Đặt vết cắt ở đỉnh trên của bóng thoại để kéo thoại gộp vào tranh bên dưới.
  - `EDGE_BOTTOM`: Bóng thoại nằm ở đáy phân cảnh $\to$ Đặt vết cắt ở đáy dưới của bóng thoại để gộp thoại vào tranh bên trên.
  - `INTERNAL`: Bóng thoại nằm lọt thỏm trong nội hàm bức tranh.
  - `ORPHAN`: Bóng thoại trôi nổi giữa rãnh trắng mênh mông.
* **Cơ chế Post-DP Bubble Snapping**:
  - Tự động dò tìm các lát cắt ngắn ($< 450\text{px}$) chỉ chứa chữ/thoại.
  - Tự động snap và gộp trọn vẹn vào trang tranh kế cận có kích thước phù hợp nhất.
  - **Cam kết**: Triệt tiêu hoàn toàn các trang thoại mồ côi (Zero Orphan Pages).

### 2.3. Cắt Bỏ Lề Canvas Rác (Canvas Margin Cleanup)
* **Đầu Canvas**: Nhận diện và gọt sạch các banner credit nhóm dịch (như AsuraScans banner 800px) và khoảng trắng đệm thừa ở đỉnh canvas, đảm bảo Trang 1 luôn bắt đầu trực tiếp từ tác phẩm nghệ thuật.
* **Đuôi Canvas**: Tự động nhận diện banner tuyển dụng, donate, credit cuối tập bằng regex và loại bỏ khỏi video candidates.

### 2.4. Thuật Toán Tối Ưu Hóa Toàn Cục (GlobalPageOptimizer - Dynamic Programming)
* Mô hình hóa bài toán phân đoạn thành đồ thị có hướng không chu trình (DAG Shortest Path).
* Hàm mục tiêu (Cost Function):
  $$\text{Cost}(i, j) = \text{base\_page\_cost} + \text{height\_penalty}(h_{i,j}) - \text{boundary\_score}(j) + \text{bubble\_risk}$$
  Trong đó:
  - $\text{height\_penalty}$: Phạt bình phương khoảng lệch so với chiều cao lý tưởng $\text{ideal\_page\_height} \approx 5.200\text{px}$.
  - $\text{boundary\_score}$: Điểm thưởng chất lượng rãnh cắt (khoảng cách an toàn tới panel, rãnh trắng đồng nhất, chuyển đổi phân cảnh).
* **Rào cản Runaway Barrier**: Đảm bảo $100\%$ các trang không vượt quá ngưỡng trần kỹ thuật, tránh các trang dài lê thê làm đơ camera.

### 2.5. Phân Loại Trực Quan 5 Nhóm (5-Tag Visual Taxonomy) & Tiêu Điểm Khuôn Mặt
* **5 Nhãn nội dung**:
  1. `ACTION_ART`: Combat, chiêu thức, đường kiếm, va chạm năng lượng cao.
  2. `CHARACTER_ART`: Đặc tả chân dung, biểu cảm nhân vật rõ nét.
  3. `CHARACTER_SCENE`: Nhân vật tương tác trong phối cảnh bối cảnh.
  4. `BACKGROUND_SCENE`: Phong cảnh, thành quách, thiên nhiên không có nhân vật.
  5. `NON_VISUAL`: Trang thông tin phụ trợ (bị loại khỏi video).
* **Trích xuất tiêu điểm (Focal Point Tracking)**:
  - Tính toán tọa độ chuẩn hóa $(f_x, f_y) \in [0.0, 1.0]$.
  - Ưu tiên trọng số cao nhất cho khuôn mặt nhân vật chính (`weight = 2.5`).
  - Gán sẵn gợi ý chuyển động: `camera_hint = "zoom_in_face"` khi có nhân vật, hoặc `camera_hint = "pan_top_to_bottom"` cho cảnh hành động rộng.

---

## 3. Giai Đoạn 2: Lập Kế Hoạch Chuyển Động & Bố Cục Khung Hình (Adaptive Motion & Composition)

Mục tiêu: Biến các trang tranh tĩnh thành những thước phim chuyển động mượt mà, định hướng ánh nhìn của khán giả theo đúng diễn biến câu chuyện.

### 3.1. Quản Lý Dòng Thời Gian Kể Chuyện (TimelineManager)
* **Đồng bộ âm thanh - hình ảnh**:
  - Tiếp nhận các mốc thời gian giọng đọc từ kịch bản recap (`timings` theo từng câu/đoạn).
  - Phân bổ thời lượng (`duration`) cho từng ảnh dựa trên trọng số ưu tiên (`priority`).
  - Tự động bổ sung bộ đệm an toàn (Outro buffer $3.0\text{s}$) ở phân đoạn kết thúc.

### 3.2. Lập Kế Hoạch Chuyển Động Camera Thông Minh (AdaptiveMotionPlanner)
* **Phân bậc thời lượng (Motion Tiers)**:
  - `MICRO` ($< 0.7\text{s}$): Nhát cắt nhanh, giữ nguyên tĩnh hoặc chuyển động cực nhẹ.
  - `SUBTLE` ($0.7\text{s} - 2.0\text{s}$): Zoom nhẹ $1.0 \to 1.05$.
  - `STANDARD` ($2.0\text{s} - 5.0\text{s}$): Chuyển động chuẩn (Pan dọc theo tranh kết hợp Zoom).
  - `MULTI_PHASE` ($5.0\text{s} - 10.0\text{s}$): Chuyển động đa pha (Focus mặt $\to$ Pan khám phá bối cảnh xung quanh).
  - `EXTENDED` ($> 10.0\text{s}$): Kết hợp chuyển động camera phức hợp.

* **Các Chế Độ Chuyển Động Cốt Lõi**:
  1. **Zoom vào khuôn mặt (`zoom_in_face`)**:
     - Tâm camera tịnh tiến mượt mà từ trung tâm trang hướng về toạ độ khuôn mặt $(f_x, f_y)$.
     - Tỷ lệ zoom mượt mà tăng dần $1.0 \to 1.20$.
  2. **Trượt dọc kết hợp Zoom (`slide_down_zoom_in` / `pan_top_to_bottom`)**:
     - Áp dụng cho các trang dọc dài (chiều cao $> 115\%$ khung hình video).
     - Camera trượt theo chiều dọc từ trên xuống dưới với tốc độ sinh học tự nhiên ($\approx 120\text{px/s}$).
     - Kết hợp zoom nhẹ từ độ rộng $960\text{px} \to 1150\text{px}$ để tạo chiều sâu không gian (depth illusion).

* **Đường Cong Làm Mượt (Easing Curves)**:
  - Sử dụng hàm `easeInOutSine` và `easeInOutCubic`:
    $$E(t) = \frac{1 - \cos(\pi \cdot t)}{2}$$
  - Giúp camera bắt đầu chuyển động êm dịu, tăng tốc ở giữa và hãm phanh mượt mà khi dừng lại, loại bỏ hoàn toàn cảm giác giật cục cơ học.

* **Hiệu Ứng Mờ Chuyển Động Vật Lý (Directional Motion Blur)**:
  - Khi vận tốc camera $(dx, dy)$ vượt ngưỡng an toàn ($> 0.6\text{px/frame}$), thuật toán tự động áp dụng ma trận tích chập (Convolution Kernel) lọc mờ có hướng dọc hoặc ngang.
  - Tạo cảm giác hành động điện ảnh chân thực như quay qua ống kính máy quay thật.

### 3.3. Xử Lý Nền Mờ Động (Animated Ambient Blur - ImageComposer)
* **Vấn đề**: Tỷ lệ khung hình của tranh manhwa rất đa dạng, khi đưa vào khung hình video cố định (16:9 ngang hoặc 9:16 dọc) sẽ dễ bị các vệt đen chết ở hai bên mép.
* **Giải pháp**:
  1. Tự động nhận diện đường viền nội dung thực (`detect_content_bounds`).
  2. Tạo nền mờ động học đa tầng (`render_animated_background_np`): Phóng đại ảnh gốc, áp dụng bộ lọc mờ Gaussian kết hợp điều chỉnh độ sáng/tương phản.
  3. **Đồng pha chuyển động**: Nền mờ phía sau di chuyển và zoom đồng bộ cùng chiều với camera của tranh tiền cảnh, tạo nên hiệu ứng thị giác sang trọng và chuyên nghiệp.

---

## 4. Giai Đoạn 3: Động Cơ Render Trực Tiếp & Mã Hóa Video (AdaptiveManhwaRendererV2 & FFmpeg Streaming)

Mục tiêu: Đạt tốc độ render cực đại, tiết kiệm tối đa tài nguyên RAM/ổ cứng và xuất video đạt chất lượng hình ảnh cao nhất.

### 4.1. Kiến Trúc Streaming Trực Tiếp Qua Bộ Nhớ Đệm (Rawvideo Pipe Streaming)
* **Cơ chế cũ (truyền thống)**: Tạo hàng nghìn frame ảnh PNG/JPEG ghi ra ổ cứng tạm thời $\to$ gọi FFmpeg đọc lại các file này. Gây nghẽn cổ chai ổ đĩa (I/O Bottleneck), tốn hàng chục GB dung lượng tạm.
* **Cơ chế mới (V2 Pipeline)**:
  - Khởi tạo tiến trình con FFmpeg một lần duy nhất với tham số nhận dữ liệu thô:
    ```bash
    ffmpeg -y -f rawvideo -vcodec rawvideo -s 1920x1080 -pix_fmt bgr24 -r 30 -i - ...
    ```
  - Khung hình sau khi tổng hợp xong trong bộ nhớ RAM (mảng contiguous NumPy) được đẩy thẳng trực tiếp vào `process.stdin.write(out_buffer.tobytes())`.
  - **Tối ưu**: Hoàn toàn không ghi đĩa trung gian, tốc độ render tăng gấp 3–5 lần, giải phóng RAM liên tục bằng bộ thu gom rác.

### 4.2. Tăng Tốc Mã Hóa Bằng Phần Cứng GPU (Hardware Accelerated Encoding)
* Tự động dò tìm encoder tối ưu trên hệ thống máy tính của người dùng:
  1. **NVIDIA GPU**: `h264_nvenc` (Render siêu nhanh với chip phần cứng chuyên dụng).
  2. **Fallback CPU**: `libx264` đa luồng kết hợp preset `fast` / `medium`.
* Tham số mã hóa chuẩn:
  - `-pix_fmt yuv420p` (Đảm bảo tương thích $100\%$ với mọi nền tảng web, YouTube, TikTok, Facebook).
  - Bitrate video mục tiêu: $6.000 - 8.000\text{ kbps}$ (Hình ảnh nét căng, không bị vỡ hạt/bệt màu trong các cảnh tối).

### 4.3. Hoàn Tất Xuất Xưởng: Ghép Âm Thanh & Đồ Họa Phủ (Post-Processing)
* **Đồng bộ giọng đọc (Voiceover TTS)**: Căn khớp tuyệt đối theo từng frame hình ảnh.
* **Nhạc nền thông minh (BGM Ducking)**: Tự động hạ âm lượng nhạc nền xuống $15-20\%$ khi có giọng đọc thuyết minh và tự động nâng âm lượng lên trong các đoạn combat hành động không lời.
* **Đồ họa thương hiệu & Phụ đề**:
  - Chèn logo kênh, watermark chống reup với độ trong suốt tùy biến.
  - Ghép phụ đề động (Subtitles) nổi bật ở góc dưới màn hình.

---

## 5. Cấu Trúc Dữ Liệu Trao Đổi Giữa Các Giai Đoạn (Manifest Schema)

Sau khi phân trang xong, dữ liệu được kết xuất thành file `manifest.json` làm hợp đồng giao tiếp giữa Giai đoạn Phân Trang và Giai đoạn Render Video:

```json
[
  {
    "page_index": 1,
    "filename": "page_001.png",
    "y_start": 1570,
    "y_end": 5341,
    "height": 3771,
    "width": 901,
    "page_tag": "ACTION_ART",
    "content_type": "MIXED",
    "camera_hint": "pan_top_to_bottom",
    "focal_point": [0.62, 0.40],
    "focal_points": [
      { "type": "face", "center": [0.62, 0.40], "weight": 2.5 }
    ]
  },
  {
    "page_index": 3,
    "filename": "page_003.png",
    "y_start": 11826,
    "y_end": 17579,
    "height": 5753,
    "width": 901,
    "page_tag": "CHARACTER_ART",
    "content_type": "MIXED",
    "camera_hint": "zoom_in_face",
    "focal_point": [0.39, 0.47],
    "focal_points": [
      { "type": "face", "center": [0.39, 0.47], "weight": 2.5 },
      { "type": "body", "center": [0.42, 0.55], "weight": 1.0 }
    ]
  }
]
```

---

## 6. Tổng Kết Giá Trị Kỹ Thuật

| Hạng mục | Cơ chế cũ | Hệ thống mới (Hiện tại) |
|---|---|---|
| **Chất lượng cắt trang** | Cắt cơ học theo chiều cao cố định, dễ chém đứt mặt và thoại | YOLO AI nhận diện bảo vệ $100\%$ khuôn mặt, thân thể; $0$ vi phạm an toàn |
| **Bóng thoại cô lập** | Xuất hiện nhiều trang trắng xóa chỉ có $1-2$ bóng thoại | Snap & merge tự động gộp $100\%$ bóng thoại vào tranh liên quan |
| **Số trang trên mỗi tập** | Phân mảnh vụn vặt ($80 - 100$ trang/tập) | Tối ưu chuẩn nhịp video ($35 - 45$ trang/tập) bằng Quy hoạch động |
| **Chuyển động hình ảnh** | Phóng to/thu nhỏ tĩnh tại tâm ảnh gây nhàm chán | Camera bám theo khuôn mặt nhân vật, lướt dọc theo nhịp đọc truyện |
| **Bố cục khung hình** | Viền đen chết ở hai bên mép video | Nền mờ chuyển động động học đồng pha với camera |
| **Tốc độ render** | Ghi hàng nghìn file PNG ra ổ cứng rồi mới nén video | Truyền trực tiếp qua RAM Pipe tới FFmpeg + GPU NVENC tăng tốc |
