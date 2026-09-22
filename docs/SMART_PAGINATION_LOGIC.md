# Kiến Trúc & Logic Phân Trang Thông Minh (Smart Pagination Architecture)

Tài liệu này mô tả chi tiết toàn bộ logic, thuật toán và kiến trúc hệ thống phân trang truyện tranh (**Smart Pagination Engine**) trong dự án `recap_comics`. Hệ thống được thiết kế theo kiến trúc **Hybrid 4 Tầng** kết hợp giữa **Pure Computer Vision** (siêu tốc, zero GPU) và **Deep Learning Object Detection** (chính xác cao, nhận diện ngữ nghĩa) nhằm giải quyết triệt để các thách thức đặc thù của Manhwa / Webtoon hiện đại.

---

## 1. Tổng Quan Kiến Trúc & Mục Tiêu Hệ Thống

### 1.1. Thách Thức của Truyện Tranh Manhwa Hiện Đại
- **Canvas siêu dài**: Một tập truyện/chapter manhwa thường được ghép thành một dải ảnh dọc dài từ **50,000px đến 250,000px**.
- **Hiệu ứng tràn viền (Bleeding Art) & Nhân vật nhảy khung**: Nhân vật, quái vật, vạt áo, tóc hoặc mũi kiếm thường xuyên vẽ vươn ra ngoài khung tranh (`frame`), đè lên khoảng trắng giữa 2 tranh. Thuật toán cắt rãnh trắng thông thường sẽ cắt đứt chân/vũ khí của nhân vật.
- **Bóng thoại lơ lửng (Floating Bubbles)**: Bóng thoại nằm đè lên gutter hoặc nằm giữa 2 ô tranh.
- **Vệt viền mồ côi (Orphan Border Slivers)**: Các đường cắt lệch 1-4px để lại vệt đen đơn độc cùng dải trắng lớn ở đầu hoặc đuôi trang.
- **Bảo toàn đại cảnh cuộn liền (Continuous Epic Scroll)**: Các phân cảnh chiến đấu kéo dài hoặc tranh phong cảnh hùng vĩ không được phép bị cắt vụn thành nhiều trang nhỏ.

### 1.2. Sơ Đồ Luồng Xử Lý Toàn Diện (End-to-End Pipeline)

```mermaid
graph TD
    Input[Ảnh Canvas Dọc / Tệp PDF Manhwa] --> Downsample[Downsample Chiều Rộng: W=128px]
    
    %% Tầng 1: Pure CV
    Downsample --> HPP[Tầng 1: Pure CV - HPP Gutter Scanner<br/>Tính Row Variance, Row Mean, Sobel Edge X+Y<br/>Thời gian: 2 - 5ms]
    HPP --> RawGutters[Danh Sách Rãnh Trắng/Đen HPP<br/>Interval: y_start -> y_end]
    
    %% Tầng 2: 1D Signal Scanner
    Input --> VBS[Tầng 2: Visual Boundary Scanner<br/>Phân Tích Tín Hiệu 1D Dọc Trục Y<br/>Luminance, Margin, Color Transition, Continuity C(y)]
    VBS --> VisualCands[Ứng Viên Chuyển Đổi Thị Giác<br/>Scene Transition, Composition Transition]
    
    %% Tầng 3: Deep Learning
    Input --> YOLO[Tầng 3: Deep Learning - YOLOv11 Manga109<br/>Chạy Batched Mini-Batch trên GPU RTX 4070 SUPER<br/>Detect: frame, body, face, text]
    YOLO --> SemanticMasks[Vùng Cấm Cắt: Forbidden Spans<br/>Bảo Vệ: Cơ Thể, Mặt Nhân Vật, Bóng Thoại]
    
    %% Tầng 4: Arbitration
    RawGutters --> Arbitrator[Tầng 4: Hybrid Arbitration Layer<br/>Đối Chiếu Rãnh HPP và Vùng Cấm Cắt YOLO]
    VisualCands --> Arbitrator
    SemanticMasks --> Arbitrator
    
    Arbitrator --> CandidatePool[Tập Hợp Điểm Cắt Ứng Viên Chuẩn Hóa<br/>Được Gán Điểm & Nhãn Ngữ Nghĩa]
    
    %% Tầng 5: Global DP Optimizer
    CandidatePool --> DPOptimizer[Tầng 5: Global Dynamic Programming Optimizer<br/>Tìm Tập Điểm Cắt Tối Ưu Toàn Cục<br/>Cân Bằng min_height, ideal_height, max_height]
    
    %% Tầng 6: Post Processing
    DPOptimizer --> Slices[Các Lát Cắt Trang Thô]
    Slices --> RunawayCheck{Lát Cắt > hard_max_height?}
    RunawayCheck -- Có --> SubSegment[Đệ Quy Phân Đoạn Lại<br/>Runaway Safety Barrier]
    RunawayCheck -- Không --> CropStage[Tầng 6: Hậu Xử Lý & Crop Tinh Gọn]
    SubSegment --> CropStage
    
    CropStage --> OrphanFilter[Bộ Lọc Viền Mồ Côi - Orphan Border Filter]
    OrphanFilter --> TightCrop[Tight Auto-Crop 4 Biên: T, B, L, R]
    TightCrop --> FinalPages[Bộ Trang Hoàn Chỉnh Xuất Ra<br/>Image Slices + PageMetadata]
```

---

## 2. Chi Tiết Các Tầng Xử Lý (Implementation Layers)

### Tầng 1: Pure Computer Vision — Horizontal Projection Profile (HPP)
*Tệp nguồn: [`renderer/hpp_gutter_scanner.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/hpp_gutter_scanner.py)*

- **Thu nhỏ chiều rộng (Width Downscaling)**:
  Ảnh được resize về $W=128\text{px}$ bằng `cv2.INTER_AREA`. Việc này giúp giảm kích thước dữ liệu hàng trăm lần nhưng vẫn giữ nguyên vẹn giá trị trung bình hàng, cho phép xử lý vector hóa hoàn toàn bằng NumPy trong **2-5 mili-giây** cho cả canvas 100,000px.
- **Tính toán 1D Row Variance, Mean & Sobel Gradient**:
  $$\text{Row Mean: } \mu_y = \frac{1}{W} \sum_{x=0}^{W-1} I(x, y)$$
  $$\text{Row Variance: } \sigma_y^2 = \frac{1}{W} \sum_{x=0}^{W-1} (I(x, y) - \mu_y)^2$$
  $$\text{Row Edge Density: } E(y) = \frac{1}{W} \sum_{x=0}^{W-1} \left( |\text{Sobel}_x(x, y)| + |\text{Sobel}_y(x, y)| \right)$$
  - *Lưu ý quan trọng*: Bắt buộc phải tính cả $\text{Sobel}_y$. Nếu chỉ tính $\text{Sobel}_x$, các dải sọc ngang hoặc nét vẽ họa tiết ngang sẽ có variance = 0 và bị nhận nhầm thành rãnh trắng.
- **Điều Kiện Nhận Diện Rãnh Cắt (Gutter Criteria)**:
  Một hàng $y$ là rãnh trắng/đen khi và chỉ khi thỏa mãn đồng thời 3 điều kiện:
  1. Phương sai ngang cực thấp: $\sigma_y^2 < \text{threshold}$ (mặc định $6.0$).
  2. Mật độ biên cạnh cực thấp: $E(y) < 8.0$.
  3. Màu sắc đồng nhất với nền canvas:
     - Nền sáng: $\mu_y \ge 225$.
     - Nền tối: $\mu_y \le 30$.
     - Nền màu: $|\mu_y - \text{bg\_val}| \le 12.0$.
- **Khử Nhiễu Dọc (Vertical Uniformity Check)**:
  Các dải rãnh liên tục có chiều cao $H \ge \text{min\_gutter\_height}$ được kiểm tra độ lệch chuẩn dọc:
  $$\text{Std}_y(\mu_y) \le 3.5$$
  Điều này loại bỏ triệt để các vùng màu chuyển sắc (gradients) hoặc sọc ngang có variance thấp nhưng đổi màu theo chiều dọc.
- **Căn Chỉnh Mép Viền Ngoài (`snap_to_panel_edge`)**:
  Tìm kiếm trong bán kính $\pm 12\text{px}$ của điểm cắt tâm rãnh để tìm vị trí có đạo hàm cạnh lớn nhất (đường viền đen ngoài cùng của ô tranh), giúp vết cắt áp sát vào mép viền, loại bỏ hoàn toàn viền mồ côi 1-2px.

---

### Tầng 2: Phân Tích Tín Hiệu Thị Giác 1D (Visual Boundary Scanner)
*Tệp nguồn: [`renderer/visual_boundary_scanner.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/visual_boundary_scanner.py)*

Coi trục $Y$ của canvas như một tín hiệu 1D liên tục đa chiều để phát hiện các bước chuyển nghệ thuật mà không phụ thuộc vào việc có hay không có rãnh trắng:

1. **Chuyển dịch màu sắc (Color Transition)**: Khoảng cách màu sắc trong không gian Lab giữa dải ảnh phía trên và phía dưới hàng $y$.
2. **Biến động bề rộng nội dung (Width Transition)**: Độ co hẹp hay mở rộng bất thường của lề trái/phải tranh.
3. **Mật độ đường hành động (Action Line Density)**: Phát hiện các tia tốc độ, đường kiếm chém có góc nghiêng mạnh qua phép nhân gradient chéo $|\text{Sobel}_x \cdot \text{Sobel}_y|$.
4. **Tín hiệu liên tục thị giác $C(y) \in [0.0, 1.0]$ (Visual Continuity)**:
   $$C(y) = (1 - \text{Disruption}(y)) \cdot \text{ContentPresence}(y) + \text{ActionBoost}(y)$$
   - $C(y) > 0.40$: Báo hiệu đây là một bức tranh liên tục (ví dụ: đại cảnh ngọn núi, thân rồng, phân cảnh giao đấu). **Cấm cắt qua** ngay cả khi có khoảng trống nhỏ bên trong!
   - $C(y) < 0.30$: Báo hiệu có sự đứt gãy tự nhiên về thị giác (chuyển cảnh từ ngày sang đêm, chuyển đổi nhân vật).
5. **Spatial Bucketing (Chống Bỏ Sót Ứng Viên Trên Canvas Lớn)**:
   Trên các canvas siêu dài ($> 100,000\text{px}$), canvas được chia thành các phân đoạn 1000px. Mỗi phân đoạn đảm bảo giữ lại ít nhất $K$ ứng viên chất lượng cao nhất, loại bỏ hiện tượng các trang ở cuối canvas bị "đói" ứng viên cắt.

---

### Tầng 3: Deep Learning Semantic Detection & Vùng Cấm Cắt
*Tệp nguồn: [`renderer/comic_vision_ai.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/comic_vision_ai.py) & [`renderer/semantic_safety.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/semantic_safety.py)*

- **Mô hình**: YOLOv11m huấn luyện chuyên biệt trên tập dữ liệu truyện tranh Manga109 ([`weights/manga109_yolo11m.pt`](file:///c:/Users/USA/Documents/Workspace/recap_comics/weights/manga109_yolo11m.pt)).
- **Khả năng tăng tốc**: Tự động chạy với mini-batch $16$ trên card đồ họa **NVIDIA GeForce RTX 4070 SUPER (12GB VRAM)**.
- **Phân loại đối tượng cốt lõi**:
  - `0: 'body'`: Thân nhân vật, quái vật, tay chân, tà áo.
  - `1: 'face'`: Khuôn mặt nhân vật.
  - `2: 'frame'`: Đường viền khung tranh (panel boundary).
  - `3: 'text'`: Bóng thoại, lời thoại, bong bóng la hét, chữ dẫn truyện.
- **Thiết Lập Vùng Cấm Cắt (Forbidden Spans)**:
  Mỗi bounding box của `body`, `face`, và `text` được mở rộng lề bảo vệ (safety padding) $5\text{px} - 10\text{px}$:
  $$\text{Forbidden Span} = [y_{\text{top}} - 5, y_{\text{bottom}} + 5]$$
  Các vùng cấm cắt liên tiếp hoặc gần nhau được gộp lại (merge intervals) thành danh sách các khoảng cấm cắt tuyệt đối.

---

### Tầng 4: Tầng Phân Xử Lai (Hybrid Arbitration Layer)
*Tệp nguồn: Tích hợp trong [`renderer/smart_pagination.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/smart_pagination.py#L2565-L2655)*

Tầng phân xử nhận đầu vào từ **Tầng 1 (HPP)**, **Tầng 2 (1D Scanner)** và **Tầng 3 (Deep Learning)** để đưa ra quyết định cắt:

| Tình Huống Thị Giác | Tín Hiệu HPP | Tín Hiệu YOLO | Hành Động Của Trọng Tài Lai (Arbitration) |
|---|---|---|---|
| **1. Rãnh Sạch (Clean Gutter)** | Tìm thấy dải trắng/đen liên tục | Không có nhân vật hay bóng thoại giao cắt | Cắt trực tiếp tại rãnh, snap mép viền ngoài. Gán điểm uy tín cao (`natural_visual_endpoint`). |
| **2. Tràn Viền (Bleeding Art)** | HPP thấy rãnh trắng giả định | Bounding box `body` hoặc `text` đè lên rãnh | **Vô hiệu hóa điểm cắt phạm vào cơ thể!** Đẩy điểm cắt lên trên đỉnh hoặc xuống dưới chân/vũ khí nơi nhân vật kết thúc hoàn toàn. |
| **3. Tranh Không Rãnh (Zero Gutter)** | Không có dải trắng ($var > 0$) | Nhận diện 2 `frame` liền kề hoặc chuyển cảnh | Sử dụng ranh giới giữa 2 `frame` kết hợp với dò cạnh Sobel để cắt ngay đường viền tiếp giáp. |
| **4. Đại Cảnh Liên Tục (Continuous Art)** | Có thể có vệt trắng nhỏ | $C(y) > 0.35$ (độ liên tục thị giác cao) | Hủy ứng viên HPP để bảo toàn bức tranh cuộn liền nguyên vẹn. |

---

### Tầng 5: Chấm Điểm & Tối Ưu Hóa Toàn Cục (DP Optimizer)
*Tệp nguồn: [`renderer/boundary_scorer.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/boundary_scorer.py) & [`renderer/global_page_optimizer.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/global_page_optimizer.py)*

1. **Chấm Điểm Đa Tiêu Chí (Boundary Scoring)**:
   Tổng hợp điểm số từ các trọng số cấu hình:
   $$\text{Score}(y) = \frac{w_{\text{scene}} S_{\text{scene}} + w_{\text{comp}} S_{\text{comp}} + w_{\text{panel}} S_{\text{panel}} + w_{\text{endpoint}} S_{\text{endpoint}}}{\sum w} - \text{Penalties}$$
   - **Phạt cực nặng (Penalty = 15.0)**: Nếu điểm cắt đi xuyên qua giữa thân nhân vật hoặc bóng thoại.
   - **10 Phân Loại Ngữ Nghĩa**: `SAFE_CUT`, `CONTINUOUS_CHARACTER`, `EDGE_BUBBLE`, `INTERNAL_BUBBLE`, `SCENE_TRANSITION`, `CONTINUOUS_ACTION`, v.v.
2. **Quy Hoạch Động (Global Dynamic Programming Optimization)**:
   Tìm tập hợp các điểm cắt $\{y_1, y_2, \dots, y_k\}$ sao cho tối thiểu hóa hàm chi phí toàn cục:
   $$\text{Cost} = \sum_{i} \left( \alpha \cdot \left| (y_{i} - y_{i-1}) - H_{\text{ideal}} \right| - \beta \cdot \text{Score}(y_i) \right)$$
   Ràng buộc cứng: $H_{\text{min}} \le y_i - y_{i-1} \le H_{\text{max}}$.
   - Nếu khoảng cách nằm ngoài giới hạn, chi phí sẽ tăng theo cấp số nhân.
   - Các điểm cắt có nhãn `hard` hoặc điểm tin cậy cao sẽ được thuật toán ưu tiên lựa chọn.

---

### Tầng 6: Hậu Xử Lý & Crop Tinh Gọn (Post-Processing)
*Tệp nguồn: [`renderer/smart_pagination.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/renderer/smart_pagination.py#L2165-L2200)*

1. **Bộ Lọc Viền Mồ Côi (Orphan Border Filter)**:
   Khi tìm phạm vi nội dung tranh (`find_content_range`), nếu phát hiện ở đầu hoặc đuôi lát cắt có một vệt màu lạ 1-4px, liền kề sau đó là một khoảng trống lớn $> 15\text{px}$, thuật toán sẽ bỏ qua vệt viền này và bắt đầu trang từ nội dung tranh thực sự.
2. **Tight Auto-Crop 4 Biên (Top, Bottom, Left, Right)**:
   Tự động phát hiện màu nền `bg_val` và cắt gọt sát 4 cạnh với lề đệm an toàn `crop_padding` (mặc định 2-4px), xóa bỏ hoàn toàn các dải trắng/đen thừa.
3. **Runaway Safety Barrier**:
   Nếu bất kỳ phân đoạn nào sau khi tối ưu vẫn có chiều cao vượt quá `hard_max_height` (ví dụ 1400px với Webtoon hoặc 4500px với Manga), hệ thống sẽ đệ quy gọi `segment_canvas_v2` để chia nhỏ phân đoạn đó, đảm bảo không bao giờ xuất hiện trang siêu dài ngoài ý muốn.

---

## 3. Cấu Hình & Các Presets Sẵn Có

Các tham số được quản lý tập trung trong `PaginationConfig`:

```python
@dataclass
class PaginationConfig:
    ideal_page_height: int = 1200       # Chiều cao lý tưởng cho 1 trang
    max_page_height: int = 3500         # Giới hạn chiều cao cho phép
    hard_max_height: int = 4500         # Rào chắn đệ quy chống trang siêu dài
    min_page_height: int = 20           # Chiều cao tối thiểu (cho phản ứng/bóng thoại nhỏ)
    
    # Cấu hình Hybrid HPP & Deep Learning
    enable_hpp_fast_path: bool = True   # Bật bộ quét Pure CV HPP
    hpp_variance_threshold: float = 6.0 # Ngưỡng phương sai nhận diện rãnh trắng
    hpp_downsample_width: int = 128     # Chiều rộng downscale để tính toán cực nhanh
    comic_panel_model_path: str = None  # Đường dẫn trọng số YOLO tùy chỉnh
    
    # Cấu hình Cắt gọt
    tight_auto_crop: bool = True        # Tự động gọt 4 cạnh trắng/đen thừa
    crop_padding: int = 4               # Lề đệm an toàn sau khi gọt
    isolate_visual_frames: bool = True  # Tách biệt từng khung tranh
```

### Các Presets Được Cung Cấp Sẵn:
1. **`PaginationConfig.webtoon_clean()`**:
   - Tối ưu cho Webtoon/Manhwa (Line Webtoon Canvas).
   - Giới hạn: `ideal_page_height = 900`, `max_page_height = 1280`, `hard_max_height = 1400`.
   - Bật gọt biên chặt chẽ (`tight_auto_crop=True`, `crop_padding=2`).
2. **`PaginationConfig.tapas_clean()`**:
   - Tối ưu cho chuẩn xuất bản Tapas (chiều rộng tối đa 940px, chiều cao tối đa 1280px).
3. **`PaginationConfig.video_recap()` / `from_preset("video")`**:
   - Chuyên dụng cho pipeline dựng video recap Manhwa (khung hình dọc 9:16, chuẩn HD 1080p).
   - Tham số kỹ thuật:
     - `min_page_height = 400`: Loại bỏ hoàn toàn các trang thoại nhỏ lẻ cô lập.
     - `ideal_page_height = 1080`: Mục tiêu tối ưu độ cao chuẩn Full HD.
     - `max_page_height = 1920`: Tỷ lệ vàng 9:16 cho video dọc TikTok/Reels/Shorts.
     - `hard_max_height = 2160`: Rào chắn cứng ngăn chặn các trang quá dài bị runaway.
     - `crop_padding = 4`: Padding tối ưu khi auto-crop biên ngoài.
     - `speech_edge_hard_cut = False`: Không cắt đứt mép bóng thoại, tự động snap bóng thoại vào ô tranh kế cận.
     - `separate_speech_bubbles = False`: Bật cơ chế Bubble Snapping & Merging.
     - `tight_auto_crop = True`: Tự động xén 4 mép nền thừa.

---

## 4. Tối Ưu Hóa Chuyên Sâu Cho Video Recap Pipeline

### 4.1. Cơ Chế Bubble Snapping & Merging (Triệt Tiêu Trang Thoại Cô Lập)
- **Vấn đề thực tế**: Trong bản phân trang thông thường, các bóng thoại nằm ngoài ô tranh hoặc nằm trong rãnh trắng thường bị cắt thành trang độc lập chỉ chứa chữ trắng viền đen (`DIALOGUE`), khiến video recap bị gián đoạn thị giác.
- **Giải pháp**:
  1. Khi `keep_with_visual=True` (trong `SpeechBubbleAnalyzer`), các bóng thoại loại `EDGE_TOP` sẽ đặt vết cắt **phía trên** bóng thoại (`by1 - pad`), giúp bóng thoại gắn liền vào tranh bên dưới. Bóng thoại loại `EDGE_BOTTOM` đặt vết cắt **phía dưới** bóng thoại (`by2 + pad`), giúp gắn vào tranh bên trên.
  2. **Vòng lặp hậu DP (Post-DP Snapping Loop)**: Bất kỳ lát cắt nào có chiều cao $< 450\text{px}$ và không chứa nhân vật/khung tranh nhưng chứa bóng thoại sẽ tự động snap và gộp vào trang tranh liền trước hoặc liền sau có độ cao gần `ideal_page_height` (1080px) nhất.

### 4.2. Rào Chắn Chống Phình Trang (Runaway Barrier $\le 2160\text{px}$)
- Bất kỳ phân đoạn nào vượt quá `hard_max_height` (2160px) sẽ tự động kích hoạt hàm đệ quy `_split_runaway_slice()`.
- Thuật toán dò tìm vết cắt tối ưu trong cửa sổ lân cận 1080px dựa trên:
  1. Rãnh trống giữa 2 panel YOLO liền kề (`panels`).
  2. Điểm cực tiểu phương sai hàng ngang (Sobel variance minimum) nằm ngoài vùng cấm (`forbidden_spans`).
  3. Đảm bảo 100% trang xuất ra đều $\le 2160\text{px}$.

### 4.3. Dọn Dẹp Margin Đầu & Đuôi Canvas (Canvas Margin Cleanup)
1. **Gọt viền rác đầu canvas**: Tự động nhận diện và loại bỏ các dải sliver $< 150\text{px}$ ở đỉnh canvas trước khi nội dung truyện tranh đầu tiên bắt đầu.
2. **Lọc watermark & credit ở đuôi canvas**: Tự động phát hiện và loại bỏ các banner giới thiệu scanlation, watermark nhóm dịch (`ASURASCANS`, `REDICE`, `CHAPTER END`, `RECRUITMENT`, `PATREON`, `DISCORD`) ở trang cuối. Các trang này được gán nhãn `content_type = CREDIT_ADS`, `page_tag = NON_VISUAL`, `video_candidate = False` và bị loại bỏ khỏi danh sách render video recap.

### 4.4. Phân Loại 5 Nhãn Thị Giác (5-Tag Visual Taxonomy)
Hệ thống phân loại chính xác từng trang vào 5 nhóm trực quan:
1. `CHARACTER_ART`: Trang cận cảnh hoặc chân dung nhân vật chủ đạo (dựa trên YOLO `face` và `body`, độ bao phủ khuôn mặt/nhân vật cao).
2. `CHARACTER_SCENE`: Nhân vật kết hợp với bối cảnh / hậu cảnh hoàn chỉnh.
3. `BACKGROUND_SCENE`: Đại cảnh phong cảnh, kiến trúc, chiến trường không có nhân vật chính chiếm ưu thế (`skin_ratio < 0.02`, `detected_characters = []`).
4. `ACTION_ART`: Cảnh chiến đấu gay cấn, chiêu thức võ thuật, đường chém kiếm với mật độ đường hành động Sobel chéo cao (`diag_energy >= 70.0`, `text_score < 45`).
5. `NON_VISUAL`: Trang bóng thoại, chữ thuần, dải phân cách rác hoặc credit nhóm dịch.

### 4.5. Metadata Điều Khiển Camera (Face-Guided Camera Motion)
Xuất ra metadata chi tiết cho từng trang hỗ trợ tự động hóa FFmpeg / MoviePy:
- `primary_focal_point`: Tọa độ chuẩn hóa `(norm_x, norm_y)` được tính toán theo trọng số ưu tiên: Khuôn mặt nhân vật (`weight: 2.5`) $\to$ Thân nhân vật (`weight: 1.5`) $\to$ Trọng tâm thị giác.
- `focal_points`: Danh sách toàn bộ các điểm neo thị giác (khuôn mặt, nhân vật, bóng thoại).
- `camera_hint`: Gợi ý chuyển động camera thông minh:
  - `"zoom_in_face"`: Tự động zoom từ từ vào khuôn mặt nhân vật biểu cảm/thoại.
  - `"pan_top_to_bottom"`: Quét từ trên xuống dưới cho các trang cảnh dọc hoặc đại cảnh cuộn.
  - `"pan_left_to_right"`: Quét ngang cho các trang cảnh rộng có 2 nhân vật đối thoại hai bên.
  - `"zoom_in"` / `"zoom_out"` / `"static"`.

---

## 5. Hướng Dẫn Huấn Luyện & Fine-Tuning (Custom Weights)

Dự án cung cấp sẵn công cụ huấn luyện dòng lệnh tại [`tools/finetune_comic_yolo.py`](file:///c:/Users/USA/Documents/Workspace/recap_comics/tools/finetune_comic_yolo.py).

### 5.1. Tạo File Cấu Hình Dữ Liệu Mẫu
```powershell
python tools/finetune_comic_yolo.py --create-template
```
Lệnh này sẽ tạo ra file `dataset_comic_sample.yaml` với cấu trúc chuẩn:
```yaml
path: ./data/comic_dataset
train: images/train
val: images/val

names:
  0: body
  1: face
  2: frame
  3: text
```

### 5.2. Khởi Chạy Quá Trình Huấn Luyện Trên GPU
```powershell
python tools/finetune_comic_yolo.py --dataset data/comic_data.yaml --epochs 50 --batch 16
```
- Công cụ sẽ tự động kiểm tra dung lượng VRAM của GPU (RTX 4070 SUPER 12GB).
- Tự động fine-tune từ model nền `weights/manga109_yolo11m.pt`.
- Khi huấn luyện xong, trọng số tốt nhất sẽ được lưu vào `weights/comic_yolo_custom.pt`.

### 5.3. Sử Dụng Trọng Số Đã Fine-Tune
Người dùng chỉ cần truyền đường dẫn trọng số vào `PaginationConfig`:
```python
cfg = PaginationConfig.webtoon_clean()
cfg.comic_panel_model_path = "weights/comic_yolo_custom.pt"

paginator = SmartPaginator(config=cfg)
pages = paginator.paginate_canvas(canvas_bgr)
```
Hệ thống sẽ tự động nạp model mới và thực hiện phân trang theo trọng số tùy chỉnh của bạn.
