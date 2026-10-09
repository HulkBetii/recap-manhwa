# Kế Hoạch Nghiên Cứu & Triển Khai Thị Trường Manhwa Recap Tây Ban Nha (TBN)

**Nhánh Git:** `manhwa-TBN`  
**Mốc chuẩn (Baseline Tag):** `v1.7.0-stable`  
**Ngày lập:** 2026-10-08  
**Trạng thái:** Sẵn sàng cho giai đoạn nghiên cứu & chuẩn bị cấu hình  

---

## 1. Bối Cảnh & Mục Tiêu Cốt Lõi

Hệ thống `Recap Comics Automation Engine` hiện đã ổn định ở phiên bản v1.7.0 với khả năng render video 1080p tăng tốc phần cứng NVENC và cắt khung thoại thông minh. Mục tiêu của giai đoạn này là **bản địa hóa (localization) toàn diện pipeline sang thị trường Tây Ban Nha (Tây Ban Nha & Mỹ Latinh - LATAM)** để khai thác tối đa tiềm năng tăng trưởng lượt xem và doanh thu.

### 🎯 NGÁCH ĐƯỢC CHỐT CHÍNH THỨC CHO KÊNH MỚI:
**"TRAICIÓN & APOCALIPSIS CON REFUGIO OCULTO" (Bị Phản Bội & Tận Thế Sinh Tồn / Căn Cứ Ẩn)**
- **Lý do chọn**: Kết hợp giữa **CTR cực đại** của yếu tố "Bị phản bội" (Rage Hook) và **Thời lượng giữ chân (Retention) khủng** của thể loại sinh tồn tích trữ tài nguyên / xây căn cứ (Marathon 2h - 4h+).
- **Lợi thế thực thi**: Tận dụng 100% dữ liệu đã xử lý sẵn trong repo (*Veteran of the Apocalypse* và *The Tyrant of the Apocalypse Returns*).


---

## 2. Bằng Chứng Thực Nghiệm Từ Nghiên Cứu Thị Trường (YouTube API Audit)

Dữ liệu crawl thực tế ngày 2026-10-08 từ các kênh recap hàng đầu:

| Kênh đối thủ | Quốc gia / Ngôn ngữ | Định dạng & Thời lượng | Hiệu suất lượt xem | Nhận định kỹ thuật |
| :--- | :--- | :--- | :--- | :--- |
| **ArkinG 2.0** | `es-419` (LATAM) | Mega-Movie (6h 26m) | 175.090 views / 6 ngày (6.8k likes) | Video cực dài giữ chân người xem cực tốt, thuật toán đẩy đề xuất liên tục. |
| **MANHWA 8584** | `es-US` (Hispanic) | Marathon (1h 29m) | 32.654 views / 24 giờ (1.9k likes) | Tốc độ cắn đề xuất trong 24h đầu rất cao (Like/View > 6%). |
| **SIXSS TALES** | `es` (Tây Ban Nha) | Arc Recap (2h 19m) | 68.117 views / 5 ngày (2.6k likes) | Nhịp kể chuyện nhanh, tập trung tóm tắt trọn 1 arc. |

### Đúc kết quan trọng:
1. **Format bắt buộc**: Phải sản xuất định dạng **Mega-Movie / Marathon (1.5h - 4h+)**, không làm video ngắn 10–15 phút.
2. **Khẩu vị khán giả**: Chuộng thể loại hồi quy (Regresión), thức tỉnh (Despertar), thợ săn (Cazadores), hầm ngục (Mazmorras) và ngày tận thế (Apocalipsis).
3. **Dung sai AI**: Người xem LATAM chấp nhận tốt giọng đọc AI tự nhiên, không đòi hỏi lồng tiếng diễn cảm phức tạp như thị trường Pháp hay Nhật.

---

## 3. Danh Mục Các Hạng Mục Cần Nghiên Cứu & Quyết Định (Research Backlog)

Trước khi can thiệp vào code, cần chốt 4 bài toán kỹ thuật sau:

### [ ] Nghiên cứu 1: Lựa chọn Mô hình Giọng Đọc (TTS Profile Evaluation)
- **Mục tiêu**: Chọn giọng nam kể chuyện tiếng TBN trầm ấm, tự nhiên, nhịp đọc nhanh (~1.1x).
- **Ứng viên**:
  - `Edge-TTS` (Miễn phí, tốc độ cao): `es-MX-JorgeNeural` (Mexico), `es-ES-AlvaroNeural` (Spain), `es-CO-GonzaloNeural` (Colombia).
  - `Azure Neural TTS` (Chi phí trung bình, chất lượng cao).
  - `ElevenLabs` (Chi phí cao, cảm xúc sâu).
- **Tiêu chí đánh giá**: Tốc độ render batch, độ chuẩn phát âm tên nhân vật Hàn Quốc (ví dụ: Sung Jin-woo, Kang Tae-sik), chi phí vận hành.

### [ ] Nghiên cứu 2: Chuẩn Hóa Bộ Từ Vựng Webtoon & System Prompt LLM
- **Mục tiêu**: Đảm bảo Gemini API sinh kịch bản tiếng TBN trung tính (Español Neutro), tránh tiếng lóng địa phương.
- **Bảng thuật ngữ chuẩn (Glossary)**:
  - Hunter $\to$ *Cazador*
  - Dungeon / Gate $\to$ *Mazmorra / Portal*
  - Awakening $\to$ *Despertar*
  - Level Up / System $\to$ *Subir de nivel / Sistema*
  - Regression $\to$ *Regresión*
  - Status Window $\to$ *Ventana de estado*
- **Cấu trúc kịch bản**: Premise Hook (30s đầu) $\to$ Kể chuyện dồn dập $\to$ Giữ câu hỏi lửng cuối mỗi tập để nối tập mượt mà.

### [ ] Nghiên cứu 3: Quy Chuẩn Tiêu Đề, SEO & Thumbnail Hooks (Metadata Kit)
- **Mục tiêu**: Tối ưu hóa CTR cho người dùng LATAM.
- **Công thức Tiêu đề đã kiểm chứng**:
  - `[#1-XX] <Sự kiện kịch tính / Tình huống nghịch lý> | MANHWA RESUMEN`
  - `⚫ <Tóm tắt số phận nhân vật chính> | Manhwa Narrado`
  - *Ví dụ mẫu*: `⚫ Fue el PEOR Cazador del Mundo… pero DESPERTÓ un Poder Prohibido | Manhwa Resumen`
- **Thumbnail Text**: Ngắn gọn (3-5 từ), font chữ to, tương phản cao (Vàng/Đỏ trên nền tối). Ví dụ: `¡PODER OCULTO!`, `DESPERTAR EX`, `TRAICIONADO`.

### [ ] Nghiên cứu 4: Tối Ưu Hóa Ghép Nối Phim Dài (Mega-Movie Assembly Pipeline)
- **Mục tiêu**: Đảm bảo `Stage11_FinalVideoAssembly` ghép nối 20-50 tập thành file 3-5 tiếng không bị nghẽn RAM hoặc lỗi lệch âm thanh/phụ đề.
- **Xác minh**:
  - Kiểm tra độ ổn định của FFmpeg Concat Demuxer trên các tệp MP4 độ dài lớn (>10GB).
  - Tịnh tiến timestamp của file `master.srt` chính xác tuyệt đối.

---

## 4. Ma Trận Đánh Đổi Kỹ Thuật (Architecture Trade-offs)

| Thành phần | Phương án A (Khuyến nghị) | Phương án B | Căn cứ kỹ thuật |
| :--- | :--- | :--- | :--- |
| **Quy trình sinh kịch bản** | **Prompt Gemini sinh trực tiếp tiếng TBN** | Sinh tiếng Anh rồi dịch qua DeepL/Gemini | Sinh trực tiếp giảm 50% chi phí token, giữ mạch cảm xúc liền lạc hơn, không bị lỗi dịch máy cứng nhắc. |
| **Động cơ TTS** | **Edge-TTS / Neural chuẩn (es-MX-Jorge)** | ElevenLabs API | Edge-TTS hoàn toàn miễn phí, tốc độ tổng hợp audio nhanh gấp 10 lần, đáp ứng hoàn hảo khối lượng nội dung 3–5 tiếng. |
| **Chiến lược phát hành** | **Mega-Movie hoàn chỉnh (Tập 1 - N)** | Đăng từng tập lẻ 10 phút | Dữ liệu YouTube thực chứng: Mega-Movie có tỷ lệ giữ chân và tốc độ cắn thuật toán cao gấp 8 lần tập lẻ. |

---

## 5. Lộ Trình Triển Khai Sau Khi Nghiên Cứu Hoàn Tất

1. **Bước 1**: Cập nhật `config.json` & `tts_settings.py` cho profile tiếng TBN.
2. **Bước 2**: Nâng cấp prompt tạo kịch bản trong `workflow_stages_1.py` / `gemini_api_engine.py`.
3. **Bước 3**: Thử nghiệm sinh kịch bản và audio thử cho 3 chapters đầu, kiểm tra chất lượng phát âm.
4. **Bước 4**: Thử nghiệm render full video 1 arc và kiểm tra tính toàn vẹn của video/audio/metadata.
