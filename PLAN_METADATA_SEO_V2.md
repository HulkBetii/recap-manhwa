# Kế hoạch nâng cấp Metadata & Retention (v2)

Ngày lập: 2026-10-02 · Trạng thái: **đã chốt phương án, chưa code**

## 1. Bối cảnh & bằng chứng

Kênh: Jaehwan Manhwa (EN-US, niche apocalypse/survival recap). Dữ liệu 12/9–1/10/2026 (CSV Studio):

| Phát hiện | Số liệu | Nguyên nhân gốc trong code |
|---|---|---|
| View ảo từ Search | 93% view từ search, CTR 0,4%, ~6s/view; engaged chỉ 296/4.718; search terms phần lớn không liên quan | Không do tool (cơ chế đếm view từ khung hình đầu từ 24/8/2026) |
| Title lệch nội dung | "WEAKEST Trainee… SSS-Rank" cho truyện zombie 1982; narration không có trainee/SSS | Title chọn từ pool theo archetype, không theo truyện |
| 3 truyện khác nhau cùng 1 title | "He Refused To Regress…" ×3 | `generate_dynamic_titles` luôn lấy template hợp lệ đầu tiên của pool archetype (pool tower chỉ có 3 mẫu) |
| Retention sụp 0:30→7:50 | 98% → 7,5% (AVD 1:33, 0,2%) | Prompt tập 1 cấm premise pitch (`app.py:3774`) → kể nguyên văn đoạn đời thường chậm |
| Tên nhân vật trôi | Intro gọi "Paran", phần còn lại "Tae" | Stage 5 chạy song song (`workflow_stages_1.py:2477`), tập 1 không có tên chuẩn; tên chỉ được chuẩn hóa trong story_memory, không trong recap.json |
| Chapter lỗi + không hiển thị | Tên cắt giữa câu, trùng tên; thanh tiến trình không chia đoạn | Fallback cắt câu đầu 5–7 từ; registry chapter hardcode cho Zombie Revelation |

Overfit nguy hiểm cần gỡ (sẽ đặt sai tên cho truyện mới):
- `youtube_metadata.py:1489` `get_character_names`: mọi truyện zombie → "Tae"; hardcode World After the Fall, Solo Leveling…
- `youtube_metadata.py:1556` `THEME_COMPONENT_REGISTRY`: 10 chapter riêng của Zombie Revelation.
- `youtube_metadata.py:1975` `_extract_story_beats`: hardcode Dingo, Hyeongjun, Migyeong, Elena.

Đối thủ (Dystopia Manhwa, Manhwa Outpost): 25–48 giây đầu là **premise pitch** giao ngay lời hứa của title bằng con số cụ thể; title = [hoàn cảnh yếu thế] + "Apocalypse" + [con số/tài nguyên] + [kết quả]; không có tên truyện trong title.

## 2. Quyết định đã chốt

| Câu hỏi | Quyết định |
|---|---|
| Dùng LLM cho Bible/title/chapter | **Có** — dùng `GeminiApiEngine.generate_content` (9Router, có xoay key). Không dùng httpx thô như `arc_intro_engine.generate_hook_script_llm` |
| Duyệt Series Bible | **Hoàn toàn tự động** (không dừng pipeline), kết quả hiển thị trong báo cáo cuối |
| Nhiều phần cho 1 truyện | **Không** — mỗi truyện 1 video; chỉ cần chặn trùng title giữa các truyện |
| Tên truyện trong title | Không. Đặt trong mô tả, tags, pinned comment |
| Chapter không hiển thị | Cần xử lý (xem mục C3) |

## 3. Workstreams (thứ tự thực hiện: A → B → E → C → D)

### A. Series Bible — đồng bộ ngữ cảnh nhân vật
**Trạng thái: ĐÃ CODE (2026-10-02)** — `series_bible.py`, `tests/test_series_bible.py` (23 test). Nối vào Stage 5 (bootstrap trước khi chạy song song, inject prompt, chuẩn hóa + quan sát ở cả 3 điểm ghi recap.json), Stage 11 intro, metadata (`_merge_series_bible`, bỏ đoán tên theo title).
Giới hạn còn lại:
- recap.json đã có từ lần chạy trước KHÔNG được chuẩn hóa lại (tránh làm mất cache TTS/render).
- Bootstrap bằng LLM cần API key (9Router hoặc GEMINI_API_KEY); chế độ chỉ-Chrome rơi về tên do user nhập / StoryMemory.
- Các tên hardcode kích hoạt theo nội dung narration (Dingo, Hyeongjun, Migyeong, Elena trong `_extract_story_beats` và concept thumbnail) vẫn còn — không gây sai tên cho truyện khác, sẽ dọn khi làm B.
- Thêm xử lý biến thể phiên âm ("Min-gu" → "Mingu") và tách "RECURRING PROPER NOUNS" (tên tự phát hiện, có thể là địa danh).

**File mới:** `series_bible.py`, output `downloads/<task>/series_bible.json`.

Schema (Pydantic v2):
```
SeriesBible
  series_title, setting {era, location, premise}
  protagonist {name, aliases[], gender, locked}
  characters[] {name, aliases[], role, gender, first_episode, locked}
  factions[], locations[], terms[]   # power system, organisations
  placeholder_blocklist[]            # "Paran", "[MC name]", "Protagonist"...
  version, source ("user" | "llm_bootstrap" | "inferred")
```

Luồng:
1. **Bootstrap tuần tự trước Stage 5 song song**: ưu tiên `task.payload.ip_context` (user) → 1 lệnh LLM đọc PDF tập 1–3 chỉ trả JSON danh sách nhân vật → fallback `StoryMemory.infer_protagonist_name`.
2. **Inject** khối "CAST BIBLE" vào mọi prompt `generate_gemini_prompt` (`app.py:3695`), mọi tập, bất kể song song.
3. **Validator sau Stage 6** (`EntityNormalizer`): thay placeholder & alias → tên chuẩn; tên viết hoa lạ xuất hiện ≥N lần → thêm vào Bible (asyncio.Lock); tập có 0 lần nhắc MC nhưng tên lạ áp đảo → cờ `MC_DRIFT`.
4. Áp `EntityNormalizer` cho: recap.json, intro hook, chapter, title, mô tả, pinned comment, prompt thumbnail.
5. Gỡ hardcode tên ở `youtube_metadata.py` (get_character_names, _extract_story_beats) → đọc từ Bible.

Tiêu chí kiểm chứng:
- Test: recap có "Paran" + Bible MC="Tae" → output không còn "Paran".
- Test: 2 tập chạy song song đều nhận cùng tên MC trong prompt.
- Test: truyện zombie mới (không phải 82-08) không bị gán "Tae".

### B. Title gắn nội dung thật & không trùng
**Trạng thái: ĐÃ CODE (2026-10-02)** — `title_engine.py`, `tests/test_title_engine.py` (17 test). Stage 12 gọi LLM (`_title_llm_call`, cùng cấu hình 9Router với Stage 5) → `generate_youtube_metadata(llm_title_candidates=..., registry_titles=...)` → `select_titles`. Bỏ `_enforce_title_pre_pipe` (nguồn gốc "One Lone!").
Bổ sung so với thiết kế: luật `claim_not_in_story` — từ hứa hẹn thể loại (SSS, trainee, regress, academy, weakest…) phải xuất hiện nguyên văn ≥3 lần trong narration (tiền tố 5 ký tự quá dễ dãi trên narration 13h).
Giới hạn:
- Không có LLM → chỉ còn template; trên dữ liệu thật mọi template zombie đều >60 ký tự → `status = no_valid_candidates`, kit giữ title cũ chưa kiểm định (mục E phải gắn FAIL).
- Narration không phải tiếng Anh (chạy `vi`) → bỏ qua kiểm tra bám từ vựng, chỉ còn kiểm tra số/format/trùng.
- Registry: `channel_registry.json` (gitignored). Nhập video đã đăng: `python title_engine.py import-studio-csv "<thư mục export Content>"`.
1. `HookSheet` (từ StoryFactGraph + tóm tắt tập + Bible): premise, lợi thế riêng của MC, con số cụ thể có trong narration, sub-niche (zombie/frozen/bunker/regression…).
2. LLM sinh ~10 title theo công thức niche.
3. Validator (deterministic, tái dùng `validate_text_surface`):
   - Mọi claim/con số/danh từ chính có bằng chứng trong narration.
   - Giữ blacklist chéo thể loại hiện có (`youtube_metadata.py:1364`).
   - Từ khóa niche (apocalypse/zombie/survival/end of the world…) trong 50 ký tự đầu.
   - **Quá dài → loại, không cắt** (bỏ hành vi `_enforce_title_pre_pipe` tự thêm "!" sau khi cắt).
   - Không trùng/gần trùng registry (exact + token-Jaccard ≥ 0,6).
   - ALL-CAPS ≤ 3 từ; không có tên truyện.
4. Xếp hạng → 3 title khác biệt rõ cho Test & Compare. Pool template chỉ là fallback.

**Registry title đã đăng:** `channel_registry.json`, import từ CSV "Content" export của Studio (cột Video title) + tự ghi khi sinh kit.

Tiêu chí kiểm chứng:
- Test với narration Zombie Revelation: không title nào chứa SSS/Trainee; mọi title qua validator grounding.
- Test: 3 truyện tower khác nhau → 3 title khác nhau, không cặp nào Jaccard ≥ 0,6.
- Test: title trùng registry bị loại.

### E. Báo cáo pre-publish
**Trạng thái: ĐÃ CODE (2026-10-02)** — `prepublish_gate.py`, `tests/test_prepublish_gate.py` (12 test), `series_bible.audit_names`. Banner PASS/WARN/FAIL ở đầu kit; `prepublish_audit.passed = gate_status != "FAIL"`; Stage 12 log trạng thái gate và báo lỗi metadata lên UI.
Checks: FAIL — `title_validated`, `title_not_duplicate`, `names_consistent` (tên giữ chỗ / lệch MC), `chapters_valid` (<3, không bắt đầu 00:00, trùng, cắt cụt, em dash), `youtube_limits`. WARN — `names_consistent` khi chưa có Bible, `title_promise_in_opening` (sẽ nâng lên FAIL sau mục D), `description_placeholders` (link "Coming Soon", link playlist tự bịa `...-full-recap`).
Chạy thử trên dữ liệu thật (Veteran of the Apocalypse 1–33): FAIL vì title chưa kiểm định + chapter cắt cụt "The News Anchor Sounds Calm But Those".

- Bỏ `calculate_prime_time_publishing_schedule` khỏi kit (tài liệu SEO: YouTube chưa thấy bằng chứng giờ đăng ảnh hưởng dài hạn).
- Thêm check: title–nội dung, trùng registry, nhất quán tên (Bible), chất lượng chapter, intro có nêu lời hứa title.
- Lỗi nghiêm trọng → `FAIL` rõ ràng trong `youtube_upload_kit.txt` thay vì `passed: True`.
- Sửa bug `market_id` chưa định nghĩa ở nhánh fallback Stage 12 (`workflow_stages_2.py:2872`).

### C. Chapter
**Trạng thái: ĐÃ CODE (2026-10-02)** — `chapter_engine.py`, `tests/test_chapter_engine.py` (10 test). Đã xóa `THEME_COMPONENT_REGISTRY`, `extract_episode_theme*`, danh sách theme theo archetype (`prog_list`) — 180+ dòng. Stage 12: `plan_chapter_arcs` → `build_arc_inputs` → 1 lệnh LLM cho mọi arc (2 phương án/arc) → `apply_chapter_names` trong metadata. Thứ tự: tên LLM hợp lệ → tên Stage 11 hợp lệ → "Part N" (gate WARN `chapters_descriptive`). Registry lưu chapter đã ship để chặn trùng giữa các truyện.
Khác thiết kế: cho phép 2–6 từ (thay vì 3–6) để giữ tên ngắn như "Convoy Ambush"; danh sách từ sự kiện chung (siege, showdown, brawl…) được miễn kiểm tra bám narration.
Giới hạn: validator không bắt được lỗi ngữ pháp (vd câu mất chủ ngữ) — chỉ bắt định dạng/bám nội dung; hai script `regenerate_youtube_kit.py`, `generate_all_seo_packages.py` chưa gọi LLM nên chỉ ra "Part N".

1. Bỏ `THEME_COMPONENT_REGISTRY` hardcode và fallback cắt câu đầu.
2. LLM đặt tên chapter cho mỗi arc từ tóm tắt các tập trong arc.
3. Validator: 3–6 từ; không kết thúc bằng mạo từ/giới từ/liên từ; không trùng/gần trùng; tên riêng phải có trong Bible; từ khóa chính có trong narration của arc.
4. Định dạng: `00:00 - Title` (gạch ngang thường), **cấm em dash " — "**; ≥3 mốc tăng dần, mỗi chapter ≥10s (YouTube Help "Video Chapters").
5. Chặn tên chapter giống nhau giữa các video khác truyện (2 video tower khác truyện đang dùng chung "Arc 1: Nightmare Tower & The Rejected Regression").

Tiêu chí kiểm chứng: test với bộ chapter Zombie Revelation → không tên nào cắt cụt/trùng; mô tả không chứa " — " ở dòng timestamp.

**Đã kiểm tra (2026-10-02, trang xem công khai):** 2 video Regress dùng `00:00 - …` → chapter **hiển thị**; Zombie Revelation dùng `00:00 — …` → **không hiển thị**. Cả 4 video `playability=OK`, `isFamilySafe=true`, không bị vàng $ → loại trừ strike kênh / giới hạn độ tuổi. **Đã sửa (2026-10-02):** `youtube_metadata.py` dòng chapter dùng " - "; test `tests/test_chapter_timestamp_format.py`.

**Đã xác nhận:** người dùng đổi " — " thành " - " trong mô tả Zombie Revelation → chapter hiển thị. Nguyên nhân gốc = em dash ở dòng timestamp.

### D. Hook 3 phút đầu
**Trạng thái: ĐÃ CODE (2026-10-02)** — `premise_pitch.py`, `tests/test_premise_pitch.py` (16 test).
Thay đổi thiết kế (người dùng chọn): pitch là **intro riêng render sau khi có title**, không viết trong prompt tập 1 — vì Hook Sheet/title chỉ có sau khi narration xong.
- `youtube_metadata._select_video_titles` dùng chung cho kit và `preview_primary_title`; Stage 11 lưu `llm_title_hooks` để Stage 12 dùng lại → title của kit luôn là title pitch đã hứa.
- Stage 11 `_prepend_premise_pitch`: LLM viết pitch (60–115 từ EN) → kiểm tra (số liệu, tên bịa kể cả đầu câu, từ hứa hẹn thể loại, chào hỏi, phải nhắc lại title) → thử lại 1 lần kèm lý do → TTS + render (`MicroIntroRenderer`, 8 ảnh) → ghép vào tập đầu. Bật mặc định (`ENABLE_PREMISE_PITCH`, payload `enable_premise_pitch`); khi bật thì flash-forward template không chạy.
- Sửa rủi ro chạy lại: `intro_state.json` ghi chữ ký video sau khi ghép → nếu Stage 10 render lại tập đầu thì làm mới bản sao lưu; lần chạy không có intro thì gỡ intro cũ.
- Stage 5 prompt tập 1–2: luật SETUP COMPRESSION (trang không xung đột ≤ 2 segment, giữ thứ tự).
- Gate: `title_promise_in_opening` nâng lên **FAIL**, dùng pitch (nếu đúng title đang ship) + đoạn đầu tập 1.
Giới hạn: chưa chạy với TTS/Gemini thật; kiểm tra tên ở pitch là heuristic; pitch tiếng Việt bỏ qua kiểm tra bám từ vựng và nhắc title.

1. Thay luật "NO premise recap" (`app.py:3774`) bằng **Premise Pitch 30–45s** sinh từ HookSheet: nêu lời hứa title + stakes + con số trong 30s đầu, rồi vào cảnh xung đột.
2. Tập 1–2: nén trang không có xung đột xuống ≤ 2 segment, giữ thứ tự kể.
3. Flash-forward: bỏ template chung (`DynamicHookDirector.get_archetype_template`); chỉ giữ khi LLM sinh từ cảnh thật có bằng chứng.
4. Check tự động: từ khóa cốt lõi của title xuất hiện trong N segment đầu.

Đo lường sau triển khai: retention ở mốc 1% độ dài (baseline 7,5%) và AVD (baseline 1:33) trên các video mới.

## 4. Rủi ro & ghi chú
- D đụng prompt Stage 5 → ảnh hưởng toàn bộ narration; làm sau cùng, so sánh A/B trên 1 truyện trước khi áp dụng rộng.
- Mất cliffhanger giữa các tập khi chạy song song chưa được giải quyết bởi Bible. `[Gợi ý mở rộng (Optional)]` pass tuần tự sau Stage 5 chỉ viết lại câu mở mỗi tập dựa trên câu cuối tập trước.
- Chi phí: thêm ~3–6 lệnh gọi text/PDF Gemini mỗi video.
- Mọi kết luận về title/hook dựa trên mẫu nhỏ (4 video + ~100 title đối thủ) → kiểm chứng bằng Test & Compare và retention của video mới.
