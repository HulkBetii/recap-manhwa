# Changelog & Version History

Tài liệu ghi lại toàn bộ lịch sử phát hành, các mốc kiến trúc và tính năng đã được kiểm chứng của hệ thống **Recap Comics Automation**.

---

## [v1.8.0] - 2026-09-16
### 🎯 Milestone: Face-First Neural Saliency (YuNet ONNX), Anti-Decapitation Slicer & Dynamic Safe-Zone Framing
Phiên bản đột phá về chất lượng chọn ảnh và chuyển động camera sau khi kiểm toán toàn diện 85 tập phim (*Master Movie 5h09m*): Tích hợp mạng nơ-ron YuNet ONNX phát hiện khuôn mặt tốc độ cao, thiết lập rào cản chống chém đầu nhân vật ở khâu cắt lát, loại bỏ triệt để dương tính giả nhận diện màu da, và nâng cấp camera khóa tiêu điểm mắt nhân vật.

### 1. Định Vị Nhân Vật Chuẩn Xác Với Mạng Nơ-ron YuNet (Face-First Neural Saliency)
- **YuNet ONNX Integration**: Tích hợp mô hình nhận diện khuôn mặt YuNet (`models/face_detection_yunet_2023mar.onnx`, 232KB, thời gian suy luận $<5\text{ms}$ trên CPU thông qua OpenCV `cv2.FaceDetectorYN`).
- **Triệt tiêu Dương Tính Giả Màu Da**: Giới hạn điểm màu da (`skin_ratio`) tối đa 25 điểm nếu không phát hiện khuôn mặt người thật. Loại bỏ triệt để tình trạng các panel bắp chân trần (Ep 3 `034.webp`), cánh tay, hoặc tường màu cam (Ep 72 `p39`) nhận diện nhầm thành nhân vật với điểm số cao (75–90 điểm). Điểm của các panel này giảm xuống còn $\le 15$ điểm và bị gắn cờ `is_meaningless = True`.
- **Thanh lọc bóng thoại rác**: Tự động đánh dấu `is_meaningless = True` đối với các ô tranh có tỷ lệ bóng thoại hoặc nền trắng chiếm đa số mà không có nhân vật, bảo đảm loại bỏ 100% khỏi video recap.

### 2. Rào Cản Chống Chém Đầu & Giữ Trọn Khung Tranh (Anti-Decapitation Face Guard & Panel-Preserving Lookahead)
- **Local Gutter Recognition**: Bổ sung kiểm tra độ lệch chuẩn hàng tranh `row_std < 4.0` trong `get_clean_rows` để nhận diện rãnh tranh cục bộ bất kể sự thay đổi màu sắc của trang nền (cảnh đêm, hồi tưởng flashback).
- **Anti-Decapitation Face Guard**: Tự động trích xuất tọa độ khuôn mặt toàn dải (`global_faces`) và dựng rào cản phạt $+100.0$ penalty trên mọi hàng cắt đi qua vùng đầu/mặt/cổ nhân vật, triệt tiêu vĩnh viễn lỗi cắt đôi người (từng gặp ở Ep 29 `015.jpg` tạo ra ảnh không đầu `010.webp`).
- **Panel-Preserving Lookahead**: Mở rộng biên độ tìm kiếm hàng cắt tới $1.45 \times \text{max\_h}$ khi phát hiện rãnh tranh sắp tới, ưu tiên giữ trọn vẹn toàn bộ khung tranh thay vì cắt ngang khung hình một cách cơ học.

### 3. Khóa Tiêu Điểm Mắt Nhân Vật & Khung Nhìn An Toàn Động (Face-Locked Camera & Dynamic Safe-Zone Framing)
- **Eye-Line Focal Point with Headroom Protection**: Camera Planner ưu tiên khóa tiêu điểm trực tiếp vào vùng mắt/trán của khuôn mặt nhân vật nổi bật nhất, duy trì 15% khoảng trống phía trên trán (Headroom), ngăn chặn triệt để hiện tượng chữ SFX to ("SPLATTER", "BOOM") cướp tiêu điểm thị giác.
- **Dynamic Safe-Zone Framing**: Khi khoảng trượt dọc hữu dụng $usable\_v < 160\text{px}$, tự động điều chỉnh khung nhìn card linh hoạt theo đúng tỷ lệ thật của khung tranh, xóa bỏ hoàn toàn hiện tượng camera bị kẹt ở tâm và lỗi méo tỷ lệ.
- **Dual-Phase Continuous Ken Burns Motion (`dual_shot_cinematic`)**: Đối với các câu thoại dài ($> 7.0\text{s}$) trên khung tranh tĩnh, tự động áp dụng chuyển động Ken Burns 2 pha (zoom in từ $1.00 \to 1.10$ ở điểm giữa, sau đó zoom out nhẹ về $1.00$ ở cuối câu), tạo sự sống động liên tục mà không gây giật góc máy (jump cuts).

---

## [v1.7.0] - 2026-09-16
### 🚀 Milestone: Adaptive Velocity Clamping, Dominant Bubble Repulsion, Stateful Donor Deduplication & Autonomous VLM Safety Bypass
Phiên bản chốt chặn độ hoàn thiện cao sau thực nghiệm toàn diện 85 tập truyện dài (*Ultimate Shut-in*): Khắc phục dứt điểm lỗi bẻ khóa keyframe ở Stage 10, khống chế trần vận tốc trượt camera ($v \le 120\text{px/s}$), tránh triệt tiêu vector bóng thoại đa vị trí, khử trùng lặp trang donor lân cận, và trang bị bộ tự động vượt lỗi kiểm duyệt VLM.

### 1. Đồng Bộ Hóa Keyframe & Khống Chế Vận Tốc Camera (Adaptive Velocity Clamping)
- **Keyframe-Driven Renderer Sync**: Ràng buộc trực tiếp tọa độ trọng tâm `(cx, cy)` trong `render_page_frame` theo đúng các điểm mốc `(x_focal, y_focal)` của keyframe được nội suy bởi `CameraPlanner`. Loại bỏ hoàn toàn lỗi tính đè `cy_min + (cy_max - cy_min) * prog` vốn từng ép camera trượt hết 100% chiều cao và đè qua các vùng bóng thoại đã được né.
- **Adaptive Velocity Clamping**: Thiết lập trần vận tốc trượt tối đa $120\text{px/s}$. Khoảng trượt được điều chỉnh tự thích ứng theo thời lượng: $\text{span} = \min(H_c \times 0.35, \text{duration} \times 120.0)$. Nếu thời lượng câu thoại quá ngắn khiến khoảng trượt $< 50\text{px}$, camera tự động chuyển sang chế độ Ken Burns Focus Zoom mượt mà thay vì trượt gấp gây chóng mặt và kích hoạt motion blur nặng.
- **Dọn dẹp mã nguồn (Abolish Magic Numbers)**: Xóa bỏ danh sách số trang hardcode `if page_num in [2, 8, 20, 23, 35]`, bảo đảm hướng trượt được quyết định 100% khách quan dựa vào vị trí bóng thoại và số thứ tự shot.
- **Chuẩn hóa ngưỡng góc nhìn ngang (Landscape Aspect Threshold)**: Nâng ngưỡng kích hoạt chuyển động trượt ngang `cinematic_pan_horizontal` từ $\ge 1.30$ lên $\ge 2.20$, giúp các khung tranh 4:3 và 16:9 tiêu chuẩn được hiển thị trọn vẹn ở chế độ Focus Zoom mà không bị trượt ngang không cần thiết.

### 2. Né Bóng Thoại Theo Cụm Ưu Thế (Dominant Bubble Repulsion)
- **Connected Components Dominance**: Thay thế việc lấy trung bình cộng tọa độ toàn bộ bóng thoại bằng hàm `cv2.connectedComponentsWithStats` để xác định chính xác tâm hình học của **bóng thoại có diện tích lớn nhất (Dominant Bubble)**.
- **Triệt tiêu Vector Cancellation**: Ngăn chặn hoàn toàn hiện tượng 2 bóng thoại đối xứng ở hai góc triệt tiêu lẫn nhau khiến camera hướng vào khoảng trống vô nghĩa giữa các nhân vật.

### 3. Khử Trùng Lặp Trang Thay Thế (Stateful Donor Deduplication)
- **Recent Donor History Registry**: Thiết lập bộ nhớ lưu vết `recent_used_donors` theo từng tập phim.
- **Deduplication Penalty**: Khi một phân đoạn gặp panel rác/gutter, các trang donor đã được sử dụng trong 2 phân đoạn kề trước bị phạt 25.0 điểm chất lượng, buộc thuật toán ưu tiên chọn các trang nhân vật đặc sắc khác trong bán kính $\pm 5$ trang, chấm dứt triệt để hiện tượng lặp lại cùng một hình ảnh cho 2–3 câu thoại liên tiếp.

### 4. Tự Động Phục Hồi Lỗi Kiểm Duyệt VLM (Autonomous VLM Safety Bypass)
- **Universal Safety Markers**: Mở rộng bộ nhận diện từ chối an toàn của Google Gemini (`can't help with that image`, `against my safety guidelines`, `graphic violence`, `violent content`, `không thể hỗ trợ`...).
- **Autonomous Safe PDF Fallback**: Cho phép Stage 5 tự động kích hoạt tạo tệp PDF an toàn riêng và thử lại ở Attempt 2 ngay khi gặp lỗi kiểm duyệt, ngay cả khi tham số khởi tạo `safe_mode=False`.
- **Expanded NSFW & Violence Masking**: Bổ sung các nhãn bạo lực/chấn thương (`blood. wound. injured person. corpse.`) vào `MODERATION_PROMPT`, giúp bộ lọc DINO + SAM tự động che phủ các cảnh máu me/vết thương (như trang 60 tập 32), bảo đảm pipeline marathon chạy xuyên suốt 100% không bị treo giữa chừng.

### 5. Tối Ưu Hóa Gói Câu Giọng Đọc (Sentence Packing Optimization)
- **Batch Sentence Packing**: Bổ sung bước gom cụm các câu ngắn liên tiếp thành các khối thoại tối ưu ~250 ký tự trong `split_text_into_segments`.
- **Cắt giảm 50% thời gian khởi tạo mô hình TTS**: Giảm số lần gọi `model.generate` của OmniVoice từ 40–50 lần xuống còn 12–15 lần mỗi tập, giúp giọng đọc tự nhiên, liền mạch và rút ngắn đáng kể thời gian sinh âm thanh trên GPU.

---

## [v1.6.0] - 2026-09-15
### 🎬 Milestone: Continuous Vertical Pan, Wide Scene Framing & Meaningless Gutter Purging
Phiên bản nâng cấp trải nghiệm thị giác chuyên sâu cho Webtoon/Manhwa Recaps: loại bỏ hoàn toàn hiện tượng camera bị khựng ("trượt rồi dừng"), mở rộng tầm nhìn toàn cảnh khung tranh, chủ động né bóng thoại 2 chiều và thanh lọc triệt để các panel rác/gutter xám.

### 1. Trượt Dọc Tuyến Tính Mượt Mà Liên Tục (Continuous Vertical Pan Glide)
- **Abolish Clamping Freeze**: Khắc phục dứt điểm lỗi tính toán khoảng pan vượt biên (`cy_min`, `cy_max`) khiến camera bị `np.clip` giữ yên 30-40% cuối shot. Camera giờ đây trượt đều đặn theo toàn bộ chiều cao hữu dụng `[cy_min, cy_max]`.
- **Soft Linear Glide Easing**: Thay thế `easeInOutSine` (vốn giảm gia tốc về 0 quá sớm) bằng hàm nội suy chuyển động chuyên dụng: 5% soft ease-in khởi động, 90% vận tốc tuyến tính không đổi (constant linear glide), 5% soft ease-out kết thúc.
- **Smart Alternating Direction**: Luân chuyển hướng trượt thông minh giữa các shot (`top_to_bottom` vs `bottom_to_top`), tự động phát hiện vị trí bóng thoại: nếu bóng thoại dồn ở 35% trên cùng, camera tự động trượt từ dưới lên (`bottom_to_top`) để ưu tiên hiển thị nhân vật/hành động trước.

### 2. Mở Rộng Khung Hình & Bảo Tồn Bối Cảnh (Wide Context Framing)
- **Full-Width Canvas Preservation**: Mở rộng bề rộng crop đạt 100% chiều rộng panel (`w_base = float(W_c)`), chấm dứt việc crop quá hẹp làm mất chi tiết cơ thể nhân vật và bối cảnh hai bên.
- **Nâng Floor Aspect Ratio**: Nâng sàn tỷ lệ khung hình card từ 0.50 lên 0.65 (tối đa 0.85), loại bỏ hoàn toàn các dải đen hẹp bất thường (narrow pillarbox slits) trên video 16:9.

### 3. Đẩy Trọng Tâm Né Bóng Thoại 2 Chiều (2D Speech Bubble Repulsion)
- **2D Bubble Repulsion Vector**: Tự động tính vector đẩy trọng tâm camera (`focal_x`, `focal_y`) lệch xa khỏi tâm bóng thoại trên cả trục X (ngang) và Y (dọc), bảo đảm khung nhìn tập trung vào biểu cảm khuôn mặt và động thái nhân vật thay vì bị bóng thoại chiếm trọn tầm mắt.

### 4. Thanh Lọc Panel Rác & Khoảng Đệm Trắng/Xám (Meaningless & Gutter Purging)
- **Pixel Std-Dev Gutter Detection**: Bổ sung kiểm tra độ lệch chuẩn pixel (`gray_std < 14.0 or visual_detail < 8.0`) nhằm phát hiện và loại bỏ các dải màu đồng nhất/gutter xám (như RGB mean 66.6, std 6.62 trong các webtoon strip Naver/Webtoons) mà các ngưỡng độ sáng đơn thuần trước đây bỏ sót.
- **Hard Score Floor & Bubble Dominance**: Thiết lập chặn sàn điểm tối đa 25 điểm cho ảnh vô nghĩa (`final_score_raw < 32.0` -> `is_meaningless = True`). Nhận diện triệt để các panel chỉ chứa bóng thoại (`bubble_coverage_ratio > 0.40 and skin_ratio < 0.03`).
- **Repagination Slice Filter**: Chặn tạo slice chứa toàn bóng thoại/khoảng trắng rác ngay tại Stage 2b Intelligent Repagination (`is_text_bubble_dominant`).
- **Stage 10 Intelligent Donor Search**: Cơ chế thay thế trang rác mở rộng bán kính tìm kiếm từ $\pm 1$ lên $\pm 5$ trang lân cận với ngưỡng điểm sàn chất lượng `composite >= 45`.

### 5. Chuẩn Hóa Hệ Thống & Bộ Giọng Đọc
- Đồng bộ toàn diện hệ thống lên phiên bản **v1.6.0** (`config.py`, `app.py`, `static/index.html`).
- Cấu hình chuẩn cho kịch bản tiếng Việt (`vi`) sử dụng mô hình OmniVoice Voice Cloning với giọng mẫu `static/jessa - easygoing and effortless.mp3`.

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
