import unittest
import numpy as np
import cv2
from renderer.smart_pagination import SmartPaginator, PaginationConfig, PageType, PageTag, VisualSemanticScorer, TextScorer, PageMetadata, ComicVisionDetector

class TestSmartPagination(unittest.TestCase):
    def setUp(self):
        self.config = PaginationConfig(separate_speech_bubbles=True)
        self.paginator = SmartPaginator(self.config)

    def test_bubble_and_shield_separation_no_micro_pages(self):
        """
        Tests that a canvas with:
        - Speech bubble at top
        - Shield/wings illustration in middle
        - Speech bubble at bottom
        is cleanly split into 3 complete pages without cutting through the illustration or creating micro-slices.
        """
        canvas = np.full((1600, 800, 3), 255, dtype=np.uint8)

        # 1. Top text box (y=50..250)
        cv2.rectangle(canvas, (200, 50), (600, 250), (0, 0, 0), 2)
        cv2.putText(canvas, "ANCIENT POWERS", (250, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        # Faint wisps (y=250..380)
        cv2.line(canvas, (400, 250), (380, 300), (220, 220, 220), 1)
        cv2.line(canvas, (380, 300), (410, 380), (230, 230, 230), 1)

        # 2. Shield illustration with wings (y=380..1050)
        pts = np.array([[400, 380], [750, 550], [600, 750], [400, 1050], [200, 750], [50, 550]], np.int32)
        cv2.fillPoly(canvas, [pts], (180, 150, 120))
        cv2.polylines(canvas, [pts], True, (50, 40, 30), 4)
        cv2.circle(canvas, (400, 650), 120, (100, 80, 60), -1)

        # Faint wisps (y=1050..1200)
        cv2.line(canvas, (400, 1050), (420, 1120), (225, 225, 225), 1)
        cv2.line(canvas, (420, 1120), (350, 1200), (230, 230, 230), 1)

        # 3. Bottom text boxes (y=1200..1480)
        cv2.rectangle(canvas, (250, 1200), (550, 1320), (0, 0, 0), 2)
        cv2.putText(canvas, "AMONGST THOSE", (270, 1260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.rectangle(canvas, (350, 1350), (700, 1480), (0, 0, 0), 2)
        cv2.putText(canvas, "FORMLESS SHIELD", (370, 1420), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3)

        # Check heights: no micro-pages (< 120px)
        for idx, (crop, meta) in enumerate(results, 1):
            self.assertGreaterEqual(meta.height, 120)
            self.assertGreater(meta.visual_score, 0)

        # Page 2 must be the full shield (> 500px)
        self.assertGreaterEqual(results[1][1].height, 500)

    def test_spiky_speech_bubble_above_and_below_panel(self):
        """
        Tests that a webtoon strip with:
        - Spiky screaming dialogue bubble at top ("IT'S FULL OF STRANGE LETTERS")
        - Horizontal black panel border
        - Colored character panel with skin tones and rich artwork
        - Horizontal black panel border
        - Spiky dialogue bubble at bottom ("BUT THIS IS DEFINITELY THE REAL THING!")
        is cleanly separated into 3 individual pages:
        - Page 1: Top speech bubble (PageType.TEXT_BUBBLE)
        - Page 2: Character illustration panel (PageType.CONTENT)
        - Page 3: Bottom speech bubble (PageType.TEXT_BUBBLE)
        """
        canvas = np.full((1800, 800, 3), 255, dtype=np.uint8)

        # 1. Top spiky speech bubble (y=50..260)
        cv2.ellipse(canvas, (400, 150), (220, 80), 0, 0, 360, (0, 0, 0), 3)
        # Jagged spiky border around bubble
        for angle in range(0, 360, 15):
            rad = np.deg2rad(angle)
            p1 = (int(400 + 220 * np.cos(rad)), int(150 + 80 * np.sin(rad)))
            p2 = (int(400 + 250 * np.cos(rad)), int(150 + 100 * np.sin(rad)))
            cv2.line(canvas, p1, p2, (0, 0, 0), 4)
        cv2.putText(canvas, "STRANGE LETTERS", (280, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

        # 2. Horizontal panel top border (y=290)
        cv2.line(canvas, (20, 290), (780, 290), (0, 0, 0), 4)

        # Character artwork panel (y=294..1200)
        # Character skin, clothes, stone tablet
        cv2.rectangle(canvas, (20, 294), (780, 1200), (80, 60, 50), -1) # Dark cave bg
        # Character face / skin tone (BGR format with Cr/Cb skin spectrum)
        cv2.ellipse(canvas, (400, 600), (120, 160), 0, 0, 360, (140, 160, 210), -1)
        # Character hair
        cv2.circle(canvas, (400, 500), 100, (40, 50, 90), -1)
        # Tablet
        cv2.rectangle(canvas, (300, 750), (550, 1050), (120, 130, 140), -1)

        # Horizontal panel bottom border (y=1200)
        cv2.line(canvas, (20, 1200), (780, 1200), (0, 0, 0), 4)

        # 3. Bottom spiky speech bubble (y=1250..1480)
        cv2.ellipse(canvas, (400, 1360), (240, 70), 0, 0, 360, (0, 0, 0), 3)
        for angle in range(0, 360, 15):
            rad = np.deg2rad(angle)
            p1 = (int(400 + 240 * np.cos(rad)), int(1360 + 70 * np.sin(rad)))
            p2 = (int(400 + 270 * np.cos(rad)), int(1360 + 90 * np.sin(rad)))
            cv2.line(canvas, p1, p2, (0, 0, 0), 4)
        cv2.putText(canvas, "THE REAL THING", (290, 1370), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3)

        top_bubble_meta = results[0][1]
        char_panel_meta = results[1][1]
        bot_bubble_meta = results[2][1]

        self.assertEqual(top_bubble_meta.page_type, PageType.TEXT_BUBBLE)
        self.assertEqual(char_panel_meta.page_type, PageType.CONTENT)
        self.assertEqual(bot_bubble_meta.page_type, PageType.TEXT_BUBBLE)

        # Character panel should span the artwork height (> 700px)
        self.assertGreaterEqual(char_panel_meta.height, 700)
        # Character panel should have significantly higher visual score than the text bubbles
        self.assertGreater(char_panel_meta.visual_score, top_bubble_meta.visual_score)

    def test_continuous_character_drawing_never_split_in_half(self):
        """
        Tests that a continuous manhwa scene with a character standing (head, neck, white shirt, body, patting girl)
        and speech bubble is kept intact as 1 complete page without cutting through the character's neck/body.
        """
        canvas = np.full((1300, 800, 3), 255, dtype=np.uint8)

        # 1. Dialogue bubble at top (y=60..240)
        cv2.ellipse(canvas, (400, 150), (200, 70), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "YOU WOULD BE ABLE", (260, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # 2. Dark aura / hair connecting to character (y=200..450)
        cv2.ellipse(canvas, (500, 350), (100, 150), 30, 0, 360, (30, 20, 40), -1)

        # 3. Character face with skin tones (y=400..550)
        cv2.ellipse(canvas, (450, 480), (60, 80), 0, 0, 360, (140, 160, 210), -1)

        # 4. White shirt / body with slight shading (y=550..850)
        cv2.rectangle(canvas, (350, 550), (550, 850), (230, 230, 235), -1)
        cv2.rectangle(canvas, (350, 550), (550, 850), (0, 0, 0), 2)

        # 5. Seated girl (y=650..950)
        cv2.ellipse(canvas, (300, 720), (50, 70), 0, 0, 360, (140, 160, 210), -1)

        # 6. Dark pants and shoes (y=850..1150)
        cv2.rectangle(canvas, (400, 850), (520, 1150), (25, 20, 30), -1)

        results = self.paginator.paginate_canvas(canvas)
        # Speech bubble is separated at top; continuous character drawing is preserved intact!
        self.assertEqual(len(results), 2)
        # Page 1: Speech bubble (DIALOGUE)
        bubble_meta = results[0][1]
        self.assertEqual(bubble_meta.content_type, PageType.DIALOGUE)
        self.assertFalse(bubble_meta.video_candidate)
        # Page 2: Continuous character drawing (VISUAL, intact height >= 900)
        char_meta = results[1][1]
        self.assertEqual(char_meta.content_type, PageType.VISUAL)
        self.assertTrue(char_meta.video_candidate)
        self.assertGreaterEqual(char_meta.height, 880)
        self.assertGreater(char_meta.visual_score, 0)

    def test_speech_bubbles_above_and_below_framed_panel_separated(self):
        """
        Tests that:
        - Speech bubble on white background at top
        - Framed panel with dark background & character portrait in middle
        - Speech bubble on white background at bottom
        is cleanly separated into 3 distinct pages (PageType.TEXT_BUBBLE, CONTENT, TEXT_BUBBLE).
        """
        canvas = np.full((1500, 800, 3), 255, dtype=np.uint8)

        # 1. Top speech bubble (y=50..260)
        cv2.ellipse(canvas, (400, 150), (220, 75), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "WE'LL HAVE TO PLAN", (260, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # 2. Framed character panel (y=300..950) with black border box
        cv2.rectangle(canvas, (10, 300), (790, 950), (30, 25, 40), -1) # Dark panel bg
        cv2.rectangle(canvas, (10, 300), (790, 950), (0, 0, 0), 4)      # Black border lines
        # Character head & eyes
        cv2.ellipse(canvas, (400, 580), (120, 150), 0, 0, 360, (140, 160, 210), -1)
        cv2.circle(canvas, (400, 500), 110, (20, 15, 25), -1)          # Dark hair

        # 3. Bottom speech bubble (y=980..1220)
        cv2.ellipse(canvas, (400, 1100), (230, 70), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "SWITCH POSITIONS", (280, 1105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0][1].page_type, PageType.TEXT_BUBBLE)
        self.assertEqual(results[1][1].page_type, PageType.CONTENT)
        self.assertEqual(results[2][1].page_type, PageType.TEXT_BUBBLE)

    def test_continuous_epic_art_scroll_kept_as_single_page(self):
        """
        Tests that an epic continuous scroll (dragon, red dark skies, monsters, warrior, skulls)
        separates top/bottom narration boxes while keeping the middle continuous artwork intact (>= 1500px).
        """
        canvas = np.full((2200, 800, 3), (20, 15, 60), dtype=np.uint8) # Dark crimson red background

        # Continuous background smoke/clouds & red glow from y=0 to y=2200
        for y in range(0, 2200, 40):
            cv2.line(canvas, (0, y), (800, y), (25, 20, 80 + int(20 * np.sin(y / 100.0))), 2)

        # Top text parchment (y=60..220)
        cv2.rectangle(canvas, (150, 60), (650, 220), (150, 180, 210), -1)
        cv2.putText(canvas, "THE GREAT EVIL DUNGEONS", (180, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 30, 40), 2)

        # Giant dragon silhouette with glowing wings (y=250..1000)
        pts = np.array([[400, 250], [750, 450], [650, 700], [400, 1000], [150, 700], [50, 450]], np.int32)
        cv2.fillPoly(canvas, [pts], (10, 10, 15))
        cv2.polylines(canvas, [pts], True, (20, 20, 200), 4) # Red glowing edge

        # Armored warrior in middle (y=950..1650)
        cv2.rectangle(canvas, (200, 950), (600, 1650), (50, 45, 60), -1)
        cv2.circle(canvas, (400, 1200), 100, (80, 70, 90), -1)

        # Bottom skulls & parchment overlapping warrior feet (y=1600..2150)
        cv2.circle(canvas, (300, 1750), 80, (200, 210, 220), -1)
        cv2.circle(canvas, (500, 1800), 90, (190, 200, 215), -1)
        cv2.rectangle(canvas, (150, 1900), (650, 2120), (150, 180, 210), -1)
        cv2.putText(canvas, "SEVEN DUNGEONS", (250, 2010), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 30, 40), 2)

        results = self.paginator.paginate_canvas(canvas)
        # Top narration box and bottom narration box separated; continuous epic artwork intact!
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0][1].content_type, PageType.MIXED)
        # Middle continuous illustration page (dragon, warrior, skulls) must remain 1 intact single page >= 1500px!
        art_page = results[1][1]
        self.assertEqual(art_page.content_type, PageType.VISUAL)
        self.assertTrue(art_page.video_candidate)
        self.assertGreaterEqual(art_page.height, 1500)
        self.assertEqual(results[2][1].content_type, PageType.MIXED)

    def test_visual_semantic_scorer(self):
        img = np.full((300, 300, 3), 255, dtype=np.uint8)
        cv2.circle(img, (150, 150), 80, (50, 100, 200), -1)
        score, breakdown = VisualSemanticScorer.calculate_score(img)
        self.assertIsInstance(score, int)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        self.assertIn("final_score", breakdown)

    def test_generate_chapter_pdf_individual_physical_pages(self):
        import tempfile
        import os
        from PIL import Image
        from workflow_stages_1 import generate_chapter_pdf
        import pypdf
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = os.path.join(tmp_dir, "images_pdf")
            os.makedirs(images_dir, exist_ok=True)
            pdf_path = os.path.join(tmp_dir, "chapter.pdf")

            # Create 120 small smart page dummy images
            image_files = []
            page_scores = {}
            for i in range(1, 121):
                fname = f"{i:03d}.webp"
                fpath = os.path.join(images_dir, fname)
                im = Image.new("RGB", (700, 200), (200, 220, 240))
                im.save(fpath, "WEBP")
                image_files.append(fname)
                page_scores[i] = 75

            # Render PDF: every page is an independent physical page
            generate_chapter_pdf(
                image_files=image_files,
                images_pdf_dir=images_dir,
                pdf_path=pdf_path,
                page_scores=page_scores,
                max_pdf_pages=None,
                pdf_quality=30
            )

            self.assertTrue(os.path.exists(pdf_path))
            reader = pypdf.PdfReader(pdf_path)
            num_physical_pages = len(reader.pages)
            # Each page in image_files must be an independent physical page in the PDF (1-to-1)
            self.assertEqual(num_physical_pages, 120)

    def test_generate_chapter_pdf_unlimited_pages(self):
        import tempfile
        import os
        from PIL import Image
        from workflow_stages_1 import generate_chapter_pdf
        import pypdf

        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = os.path.join(tmp_dir, "images_pdf")
            os.makedirs(images_dir, exist_ok=True)
            pdf_path = os.path.join(tmp_dir, "chapter_unlimited.pdf")

            # Create 45 distinct smart page images
            image_files = []
            page_scores = {}
            for i in range(1, 46):
                fname = f"{i:03d}.webp"
                fpath = os.path.join(images_dir, fname)
                im = Image.new("RGB", (700, 200), (200, 220, 240))
                im.save(fpath, "WEBP")
                image_files.append(fname)
                page_scores[i] = 75

            # When max_pdf_pages is None, all 45 pages must be kept 1-to-1 without limitation
            generate_chapter_pdf(
                image_files=image_files,
                images_pdf_dir=images_dir,
                pdf_path=pdf_path,
                page_scores=page_scores,
                max_pdf_pages=None,
                pdf_quality=30
            )

            self.assertTrue(os.path.exists(pdf_path))
            reader = pypdf.PdfReader(pdf_path)
            self.assertEqual(len(reader.pages), 45)

    def test_intro_and_gemini_prompts(self):
        from app import generate_intro_prompt, generate_gemini_prompt, parse_gemini_recap_text

        # 1. Test generate_intro_prompt for Vietnamese & English
        intro_vi = generate_intro_prompt("Lookism", 80, "vi")
        self.assertIn("Vietnamese", intro_vi)
        self.assertIn("Lookism", intro_vi)
        self.assertIn("INTRO", intro_vi)

        intro_en = generate_intro_prompt("Solo Leveling", 50, "en")
        self.assertIn("English", intro_en)
        self.assertIn("Solo Leveling", intro_en)

        # 2. Test generate_gemini_prompt
        recap_vi = generate_gemini_prompt("Lookism", 1, 80, "vi")
        self.assertIn("Vietnamese", recap_vi)
        self.assertIn("Lookism", recap_vi)
        self.assertIn("recap", recap_vi.lower())

        # 3. Test parsing intro hook response + story recap response
        intro_response = "18 - Tưởng đâu cống hiến hết thanh xuân làm nô lệ thì được về hưu an nhàn, ai ngờ thanh niên số nhọ lại bị cấp trên thanh lý môn hộ!#"
        story_response = "2 - Anh chàng mở mắt tỉnh dậy trong căn phòng trọ cũ kỹ.#\n5 - Nhận ra mình đã quay về quá khứ mười năm trước.#"

        parsed_intro = parse_gemini_recap_text(intro_response)
        parsed_story = parse_gemini_recap_text(story_response)

        self.assertEqual(len(parsed_intro), 1)
        self.assertEqual(parsed_intro[0]["images"][0]["page"], "18")
        self.assertIn("Tưởng đâu", parsed_intro[0]["speech"])

        self.assertEqual(len(parsed_story), 2)
        combined = parsed_intro + parsed_story
        self.assertEqual(len(combined), 3)
        self.assertEqual(combined[0]["images"][0]["page"], "18")
        self.assertEqual(combined[1]["images"][0]["page"], "2")
        self.assertEqual(combined[2]["images"][0]["page"], "5")

        # 4. Test stripping stray watermark badge from intro hook
        intro_watermark_response = "97 - Type: TRANH (VALID) - Vừa cày cuốc đến kiệt sức để xuyên không thành thiếu gia Van Ecclesia ăn hại nhằm hưởng thụ cuộc sống an nhàn, anh chàng số nhọ chưa kịp ngả lưng thì đã bị hệ thống ép gánh vác nhiệm vụ giải cứu thế giới—khiến anh lập tức phá nát bảng nhiệm vụ để tự cứu lấy chuỗi ngày lười biếng của đời mình.#"
        parsed_watermark_intro = parse_gemini_recap_text(intro_watermark_response)
        self.assertEqual(len(parsed_watermark_intro), 1)
        self.assertEqual(parsed_watermark_intro[0]["images"][0]["page"], "97")
        self.assertFalse(parsed_watermark_intro[0]["speech"].startswith("Type:"))
        self.assertNotIn("Type: TRANH", parsed_watermark_intro[0]["speech"])
        self.assertTrue(parsed_watermark_intro[0]["speech"].startswith("Vừa cày cuốc"))

    def test_gemini_citation_tags_cleaning_and_parsing(self):
        from app import clean_gemini_response, verify_gemini_response_format, parse_gemini_recap_text

        # Raw response mimicking Gemini Web output with citation badges on every line (from screenshot)
        raw_response = """
2 - Giữa chiến trường đổ nát ngập tràn xác chết, tháp chủ Bạch Tháp quỳ gối tuyệt vọng khi nhận ra ma pháp hồi đáp không còn ai đáp lại.# PDF
8 - Dồn chút tàn lực cuối cùng xuống mặt đất nhuốm máu, anh thiết tha mong một tiếng động hay dấu hiệu sống sót từ đồng đội.# PDF
14 - Cay đắng nhận ra toàn bộ quân đoàn ma pháp sư tinh anh đã hi sinh sạch sẽ, anh chỉ biết tự hỏi bản thân có phải kẻ duy nhất còn thở.# PDF
19 - Trong ký ức hiện về hình ảnh Đại Tư Tế quỷ tộc, kẻ từng thống nhất binh đoàn bóng tối và đẩy nhân loại đến bờ vực diệt vong.# PDF
23 - Ngọn lửa chiến tranh đã thiêu rụi từng gia đình vô tội khi đoàn quân quỷ tràn qua thế giới loài người.# [PDF]
28 - Những sinh linh bé nhỏ bất lực trước nanh vuốt tàn bạo của lũ quỷ khát máu.# +1
32 - Ký ức về những đứa trẻ ngây thơ được bảo bọc trong vòng tay ma pháp càng khắc sâu nỗi đau của vị tháp chủ.# PDF
41 - Toàn thể pháp sư Bạch Tháp từng kiêu hãnh đứng sau lưng chủ nhân, sẵn sàng đánh cược cả sinh mạng vì tương lai loài người.# PDF
PDF
+1
"""
        # 1. Clean response
        cleaned = clean_gemini_response(raw_response)
        self.assertTrue(all(line.endswith("#") for line in cleaned.split("\n") if line.strip()))
        self.assertNotIn("PDF", cleaned)

        # 2. Verify response format
        is_valid, msg = verify_gemini_response_format(raw_response)
        self.assertTrue(is_valid, f"Verification failed: {msg}")

        # 3. Parse recap items
        parsed = parse_gemini_recap_text(raw_response)
        self.assertEqual(len(parsed), 8)
        self.assertEqual(parsed[0]["images"][0]["page"], "2")
        self.assertIn("tháp chủ Bạch Tháp", parsed[0]["speech"])
        self.assertEqual(parsed[1]["images"][0]["page"], "8")
        self.assertEqual(parsed[6]["images"][0]["page"], "32")
        self.assertEqual(parsed[7]["images"][0]["page"], "41")

    def test_gemini_glued_singleline_citations_cleaning_and_parsing(self):
        from app import clean_gemini_response, verify_gemini_response_format, parse_gemini_recap_text

        raw = """2 - Giữa chiến trường rực8 - Giữa chiến trường ngập tràn xác chết, tháp chủ Oscar gục xuống dốc cạn chút ma lực cuối cùng để tìm kiếm một người còn sống.#  PDF14 - Không một lời hồi đáp, xung quanh chỉ toàn tro tàn và xác tử sĩ, xác nhận anh chính là kẻ sống sót duy nhất của Bạch Tháp.#  PDF19 - Kẻ gây ra thảm cảnh này không ai khác ngoài Đại Tư Tế, kẻ đầu tiên thống nhất loài quỷ và đẩy nhân loại tới bờ diệt vong.#  PDF41 - Để cứu vãn thế giới, Oscar cùng toàn bộ pháp sư Bạch Tháp đã dốc sạch sinh mạng vào một đòn chí mạng duy nhất.#  PDF53 - Cái giá phải trả là đầu quỷ vương rơi xuống, nhưng cái tháp ma pháp danh giá cũng chính thức trắng tay sạch bóng người.#  PDF245 - Ra ban công ngắm nhìn phố xá nhộn nhịp xe cộ, anh mới cay đắng chấp nhận sự thật bản thân đã chết được đúng 20 năm.#  PDF255 - Chủ nhân cơ thể này tên là Oscar Crussian, hai mươi tuổi đầu nhưng ma pháp chỉ đạt cấp một thuộc dạng phế vật chính hiệu.#  PDF"""

        # 1. Clean response
        cleaned = clean_gemini_response(raw)
        lines = cleaned.split("\n")
        self.assertEqual(len(lines), 7)
        self.assertTrue(all(l.endswith("#") for l in lines))
        self.assertNotIn("PDF", cleaned)
        self.assertTrue(lines[0].startswith("8 - "))

        # 2. Verify response format
        is_valid, msg = verify_gemini_response_format(raw)
        self.assertTrue(is_valid, f"Verification failed: {msg}")

        # 3. Parse recap items
        parsed = parse_gemini_recap_text(raw)
        self.assertEqual(len(parsed), 7)
        self.assertEqual(parsed[0]["images"][0]["page"], "8")
        self.assertEqual(parsed[1]["images"][0]["page"], "14")
        self.assertEqual(parsed[4]["images"][0]["page"], "53")
        self.assertEqual(parsed[5]["images"][0]["page"], "245")
        self.assertIn("chết được đúng 20 năm", parsed[5]["speech"])
        self.assertEqual(parsed[6]["images"][0]["page"], "255")

    def test_intro_hook_with_decimal_numbers_and_citations(self):
        from app import clean_gemini_response, verify_gemini_response_format, parse_gemini_recap_text

        raw_intro = """45 - Dành trọn thanh xuân với 5.500 giờ cày cuốc trong tựa game sinh tồn thực tế ảo vắng như chùa Bà Đanh mang tên 'Survival Life', Kang Seongho đành ngậm ngùi cất kính VR để về hiện thực khởi nghiệp với một quán bánh gạo cay. Thế nhưng ranh giới ảo và thực bỗng chốc vỡ vụn khi kịch bản tận thế từ chính 'dead game' ấy chuẩn bị giáng xuống Trái Đất, mang theo một món quà mỉa mai nhưng vô giá dành riêng cho kẻ bám trụ cuối cùng: một hệ thống kỹ năng vô song cùng Cổng Không Gian cá nhân độc nhất. Liệu chàng game thủ "lão làng" kiêm ông chủ tiệm ăn nhỏ này sẽ tận dụng bộ kỹ năng sinh tồn out trình của mình để đối phó với thảm họa như thế nào? Chần chờ gì nữa, hãy cùng đồng hành với Seongho bước vào hành trình lật ngược thế cờ cực kỳ mãn nhãn và đầy thú vị này nhé.# PDF + 2"""

        cleaned = clean_gemini_response(raw_intro)
        self.assertTrue(cleaned.startswith("45 - "))
        self.assertTrue(cleaned.endswith("#"))
        self.assertNotIn("PDF", cleaned)

        is_valid, msg = verify_gemini_response_format(raw_intro)
        self.assertTrue(is_valid, f"Verification failed: {msg}")

        parsed = parse_gemini_recap_text(raw_intro)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["images"][0]["page"], "45")
        self.assertIn("5.500 giờ cày cuốc", parsed[0]["speech"])
        self.assertIn("Kang Seongho", parsed[0]["speech"])

    def test_intro_hook_missing_hash_and_r_tag(self):
        from app import clean_gemini_response, verify_gemini_response_format, parse_gemini_recap_text

        # Test case: Gemini intro output missing hash '#' and containing [R67] prefix
        raw_intro_missing_hash = "[R67] - Là Nhị công chúa bị đế quốc xem như mầm bệnh, Talia chê diễn vai nạn nhân mà trực tiếp hạ độc chị gái, hất ly rượu định mệnh xé nát bộ mặt hoàng gia, chính thức bước lên đường ác nữ đoạt quyền tàn bạo nhất."

        cleaned = clean_gemini_response(raw_intro_missing_hash)
        self.assertTrue(cleaned.startswith("67 - "))
        self.assertTrue(cleaned.endswith("#"))
        self.assertIn("Là Nhị công chúa bị đế quốc xem như mầm bệnh", cleaned)

        is_valid, msg = verify_gemini_response_format(raw_intro_missing_hash, is_intro=True)
        self.assertTrue(is_valid, f"Verification failed: {msg}")

        parsed = parse_gemini_recap_text(raw_intro_missing_hash)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["images"][0]["page"], "67")
        self.assertIn("Talia chê diễn vai nạn nhân", parsed[0]["speech"])
        self.assertEqual(parsed[0]["images"][0]["priority"], 1.0)

    def test_cover_intro_multi_sentence_format(self):
        from app import clean_gemini_response, verify_gemini_response_format, parse_gemini_recap_text

        sample_cover = "[R2] - Từng là con chó săn trung thành làm mọi chuyện nhơ bẩn cho gia tộc Baskerville, Vikir lại nhận lấy kết cục bị vu oan và hành quyết trên máy chém. Nhưng định mệnh không dừng lại ở đó khi hắn bất ngờ trọng sinh về quá khứ trong hình hài một đứa trẻ sơ sinh. Nuốt trọn dòng sông Styx huyền thoại để tôi luyện cơ thể thành mình đồng da sắt, con chó săn thiết huyết đã bắt đầu âm thầm mài sắc nanh vuốt. Liệu kẻ từng bị vứt bỏ có thể tự tay xé toạc kẻ cầm đầu và khiến cả gia tộc Baskerville chìm trong biển máu phục thù?#"

        cleaned = clean_gemini_response(sample_cover)
        self.assertTrue(cleaned.startswith("2 - "))
        self.assertTrue(cleaned.endswith("#"))

        is_valid, msg = verify_gemini_response_format(sample_cover, is_intro=True)
        self.assertTrue(is_valid, f"Verification failed: {msg}")

        parsed = parse_gemini_recap_text(sample_cover)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["images"][0]["page"], "2")
        self.assertEqual(parsed[0]["images"][0]["priority"], 1.0)
        self.assertIn("Từng là con chó săn trung thành", parsed[0]["speech"])
        self.assertIn("gia tộc Baskerville chìm trong biển máu phục thù?", parsed[0]["speech"])

    def test_glitch_restart_without_hash_mid_sentence(self):
        """
        Tests AI Gemini glitch where recap restarts mid-sentence without '#' (e.g. '...sống yên[R3] - Vào ngày...').
        Must drop all lines before the restart and keep only the restarted recap from [R3].
        """
        from app import clean_gemini_response, verify_gemini_response_format, parse_gemini_recap_text

        raw_glitch = (
            "[R3] - Khi trường học chìm trong biển lửa ngút trời, người thầy giáo trẻ Jio chỉ có một suy nghĩ duy nhất...#\n"
            "[R8] - Thế nhưng khi mở mắt ra lần nữa...#\n"
            "[R24] - Bên ngoài bây giờ không còn là xã hội bình yên cũ...#\n"
            "[R26] - Nhìn cảnh tượng đao to búa lớn nguy hiểm ấy, một cựu giáo viên chỉ muốn sống yên[R3] - Vào ngày ngôi trường chìm trong biển lửa, Jio không chạy thoát thân mà lại đâm đầu vào phòng mỹ thuật...#\n"
            "[R6] - Khói lửa bao trùm bức tranh cuối cùng...#\n"
            "[R8] - Nhưng không, khi mở mắt tỉnh dậy...#\n"
            "[R52] - Và đó là lúc quy tắc cuối cùng lộ diện, kéo Jio vào một vòng xoáy định mệnh mới...#"
        )

        cleaned = clean_gemini_response(raw_glitch)
        lines = cleaned.splitlines()
        self.assertEqual(lines[0].split(" - ")[0], "3")
        self.assertIn("Vào ngày ngôi trường chìm trong biển lửa", lines[0])
        self.assertEqual(lines[-1].split(" - ")[0], "52")
        self.assertEqual(len(lines), 4)

        is_valid, msg = verify_gemini_response_format(raw_glitch)
        self.assertTrue(is_valid, f"Verification failed: {msg}")

        parsed = parse_gemini_recap_text(raw_glitch)
        self.assertEqual(len(parsed), 4)
        self.assertEqual(parsed[0]["images"][0]["page"], "3")
        self.assertIn("Vào ngày ngôi trường chìm trong biển lửa", parsed[0]["speech"])

    def test_speech_bubble_never_sliced_at_top_or_bottom_boundary(self):
        """
        Tests that an upper bubble at the bottom of Panel 1 and a lower bubble at the top of Panel 2
        are NEVER sliced through horizontally at page boundaries.
        """
        canvas = np.full((2000, 800, 3), 255, dtype=np.uint8)

        # Panel 1: Top speech bubble + art (y=50..350)
        cv2.ellipse(canvas, (400, 200), (200, 75), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "PREVIOUS SPEECH BUBBLE", (230, 205), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # White Gutter 1 (y=350..450)

        # Panel 2: Character portrait with top speech bubble and bottom speech bubble (y=450..1400)
        # Top bubble (y=460..640)
        cv2.ellipse(canvas, (400, 550), (220, 80), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "WE'LL HAVE TO PLAN", (280, 545), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.putText(canvas, "ACCORDINGLY AS WELL", (260, 575), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # Character face/body (y=620..1150)
        cv2.rectangle(canvas, (50, 640), (750, 1150), (30, 25, 40), -1) # Dark panel
        cv2.ellipse(canvas, (400, 850), (120, 150), 0, 0, 360, (140, 160, 210), -1) # Skin tone

        # Bottom bubble overlapping character panel (y=1100..1320)
        cv2.ellipse(canvas, (450, 1210), (240, 90), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "YOU TWO LISTEN CAREFULLY", (270, 1200), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.putText(canvas, "WE'RE GOING TO SWITCH", (280, 1230), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # White Gutter 2 (y=1350..1450)

        # Panel 3: Bottom art panel (y=1450..1850)
        cv2.rectangle(canvas, (50, 1450), (750, 1850), (40, 50, 80), -1)

        results = self.paginator.paginate_canvas(canvas)
        
        # Verify that all pages have clean boundaries and none of the bubbles are sliced in half
        for idx, (slice_img, meta) in enumerate(results):
            # No page cut should fall between y=125 and y=275 (inside top bubble)
            self.assertFalse(125 < meta.y_start < 275, f"Page {idx+1} sliced through top bubble start!")
            self.assertFalse(125 < meta.y_end < 275, f"Page {idx+1} sliced through top bubble end!")
            
            # No page cut should fall between y=470 and y=630 (inside panel 2 top bubble)
            self.assertFalse(470 < meta.y_start < 630, f"Page {idx+1} sliced through panel 2 top bubble start!")
            self.assertFalse(470 < meta.y_end < 630, f"Page {idx+1} sliced through panel 2 top bubble end!")

            # No page cut should fall between y=1120 and y=1300 (inside panel 2 bottom bubble)
            self.assertFalse(1120 < meta.y_start < 1300, f"Page {idx+1} sliced through panel 2 bottom bubble start!")
            self.assertFalse(1120 < meta.y_end < 1300, f"Page {idx+1} sliced through panel 2 bottom bubble end!")

    def test_faint_diagonal_shadow_bubble_and_character_separation(self):
        """
        Tests that faint diagonal gradient shading / hazy background in the gutter behind
        a top speech bubble and a bottom speech bubble does NOT prevent clean 3-way separation:
        - Page 1: Top speech bubble
        - Page 2: Clean character portrait panel
        - Page 3: Bottom speech bubble
        """
        canvas = np.full((1200, 500, 3), 255, dtype=np.uint8)

        # Draw faint diagonal gradient shadows in the gutter behind top & bottom bubbles
        for y in range(0, 400):
            for x in range(0, 150):
                # Faint shadow gray 215-240
                canvas[y, x] = (225 + int(15 * (x / 150.0)), 225, 230)
        for y in range(800, 1200):
            for x in range(350, 500):
                canvas[y, x] = (220, 220 + int(15 * ((500 - x) / 150.0)), 225)

        # 1. Top speech bubble (y=100..340)
        cv2.ellipse(canvas, (250, 220), (180, 75), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (250, 220), (180, 75), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "WE'LL HAVE TO PLAN", (150, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        cv2.putText(canvas, "ACCORDINGLY AS WELL", (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

        # Top black panel border line at y=360
        cv2.line(canvas, (0, 360), (500, 360), (0, 0, 0), 3)

        # 2. Character portrait panel (y=360..800)
        cv2.rectangle(canvas, (0, 360), (500, 800), (40, 35, 50), -1) # Dark background
        cv2.ellipse(canvas, (250, 580), (110, 140), 0, 0, 360, (140, 160, 210), -1) # Face skin

        # Bottom black panel border line on left side at y=800
        cv2.line(canvas, (0, 800), (280, 800), (0, 0, 0), 3)

        # 3. Bottom speech bubble overlapping bottom panel (y=750..1050)
        cv2.ellipse(canvas, (350, 900), (140, 80), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (350, 900), (140, 80), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "YOU TWO LISTEN", (270, 895), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        cv2.putText(canvas, "CAREFULLY", (290, 920), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3, f"Expected 3 distinct pages, got {len(results)}")

        # Page 1: Top bubble
        self.assertLessEqual(results[0][1].y_end, 380)
        # Page 2: Character portrait (must be clean, height >= 300)
        self.assertGreaterEqual(results[1][1].height, 300)
        self.assertGreaterEqual(results[1][1].visual_score, 50)
        # Page 3: Bottom bubble
        self.assertGreaterEqual(results[2][1].y_start, 670)

    def test_visual_and_large_dialogue_region_separated(self):
        """
        Tests that an artwork panel followed by a large dialogue/lore block
        is cleanly separated into two distinct pages:
        - Page 1: Artwork panel (video_candidate=True, content_type=ARTWORK or PANEL)
        - Page 2: Large dialogue region (video_candidate=False, content_type=TEXT_ONLY or TEXT_DOMINANT)
        """
        canvas = np.full((1300, 800, 3), 255, dtype=np.uint8)

        # 1. Rich artwork panel (y=50..650)
        cv2.rectangle(canvas, (40, 50), (760, 650), (45, 40, 60), -1) # Dark background
        cv2.ellipse(canvas, (400, 350), (140, 180), 0, 0, 360, (140, 160, 210), -1) # Face skin
        cv2.circle(canvas, (400, 230), 120, (30, 40, 80), -1) # Hair
        cv2.circle(canvas, (350, 330), 15, (20, 20, 20), -1) # Eye
        cv2.circle(canvas, (450, 330), 15, (20, 20, 20), -1) # Eye
        cv2.rectangle(canvas, (40, 50), (760, 650), (0, 0, 0), 3) # Border

        # Horizontal panel divider / border at y=650
        cv2.line(canvas, (0, 650), (800, 650), (0, 0, 0), 3)

        # 2. Large dialogue / lore box (y=720..1180, height=460)
        cv2.rectangle(canvas, (100, 720), (700, 1180), (255, 255, 255), -1)
        cv2.rectangle(canvas, (100, 720), (700, 1180), (0, 0, 0), 2)
        cv2.putText(canvas, "ACCORDING TO THE ANCIENT LORE", (140, 800), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.putText(canvas, "THE GATE WILL OPEN ONCE EVERY", (130, 870), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.putText(canvas, "ONE THOUSAND YEARS WHEN STARS ALIGN", (120, 940), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.putText(canvas, "AND THE FINAL SEAL IS SHATTERED", (130, 1010), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.putText(canvas, "BY THE BLOOD OF THE DEVOURER", (140, 1080), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 pages, got {len(results)}")

        crop1, meta1 = results[0]
        crop2, meta2 = results[1]

        # Page 1 must be visual artwork candidate
        self.assertIn(meta1.content_type, (PageType.ARTWORK, PageType.PANEL, PageType.SCENE))
        self.assertTrue(meta1.video_candidate)
        self.assertGreaterEqual(meta1.visual_score, 40)
        self.assertGreaterEqual(meta1.importance_score, 40)

        # Page 2 must be text-dominant or text-only, not a video candidate
        self.assertIn(meta2.content_type, (PageType.TEXT_ONLY, PageType.TEXT_DOMINANT, PageType.TEXT_BUBBLE))
        self.assertFalse(meta2.video_candidate)
        self.assertGreaterEqual(meta2.text_score, 30)

    def test_visual_and_small_speech_bubble_separated(self):
        """
        Tests that small speech bubbles are separated into independent DIALOGUE pages
        to cleanly isolate the character/action artwork panel as a standalone VISUAL page.
        """
        canvas = np.full((1100, 800, 3), 255, dtype=np.uint8)

        # 1. Main visual character panel (y=50..700)
        cv2.rectangle(canvas, (50, 50), (750, 700), (60, 50, 70), -1)
        cv2.ellipse(canvas, (400, 380), (130, 170), 0, 0, 360, (140, 160, 210), -1) # Skin tone
        cv2.circle(canvas, (400, 260), 110, (20, 20, 60), -1) # Hair
        cv2.rectangle(canvas, (50, 50), (750, 700), (0, 0, 0), 3)

        # 2. Small speech bubble directly attached below/near the panel (y=720..810, height=90 < 140)
        cv2.ellipse(canvas, (400, 765), (140, 40), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (400, 765), (140, 40), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "What?!", (350, 775), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 pages, got {len(results)}")

        crop1, meta1 = results[0]
        crop2, meta2 = results[1]
        self.assertEqual(meta1.content_type, PageType.VISUAL)
        self.assertTrue(meta1.video_candidate)
        self.assertGreaterEqual(meta1.height, 600)

        self.assertEqual(meta2.content_type, PageType.DIALOGUE)
        self.assertFalse(meta2.video_candidate)

    def test_girl_speech_bubbles_skeleton_separation(self):
        """
        Tests user specification:
        Girl/character artwork
        Speech bubbles + white/background text area
        Skeleton/character artwork
        Must produce exactly 3 pages:
        - Page 1: Girl artwork (VISUAL, video_candidate=True)
        - Page 2: Speech bubbles + text area (DIALOGUE, video_candidate=False)
        - Page 3: Skeleton artwork (VISUAL, video_candidate=True)
        """
        canvas = np.full((1600, 800, 3), 255, dtype=np.uint8)

        # 1. Girl/character artwork at top (y=40..450)
        cv2.rectangle(canvas, (40, 40), (760, 450), (45, 40, 60), -1)
        cv2.ellipse(canvas, (400, 240), (120, 150), 0, 0, 360, (140, 160, 210), -1)
        cv2.circle(canvas, (400, 150), 100, (30, 40, 80), -1)
        cv2.rectangle(canvas, (40, 40), (760, 450), (0, 0, 0), 3)

        # 2. Speech bubbles + white/background text area in gutter (y=520..820)
        # Bubble 1:
        cv2.ellipse(canvas, (300, 600), (180, 65), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (300, 600), (180, 65), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "IS THIS THE ONE?", (180, 605), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        # Bubble 2:
        cv2.ellipse(canvas, (500, 740), (190, 65), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (500, 740), (190, 65), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "THE ANCIENT SKELETON", (360, 745), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # 3. Skeleton/character artwork at bottom (y=890..1520)
        cv2.rectangle(canvas, (40, 890), (760, 1520), (35, 30, 45), -1)
        cv2.circle(canvas, (400, 1080), 110, (210, 215, 220), -1)
        cv2.circle(canvas, (360, 1070), 25, (10, 10, 10), -1)
        cv2.circle(canvas, (440, 1070), 25, (10, 10, 10), -1)
        cv2.rectangle(canvas, (250, 1220), (550, 1500), (190, 195, 200), -1)
        cv2.rectangle(canvas, (40, 890), (760, 1520), (0, 0, 0), 3)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3, f"Expected exactly 3 pages, got {len(results)}")

        # Page 1: Girl artwork
        p1_crop, p1_meta = results[0]
        self.assertEqual(p1_meta.content_type, PageType.VISUAL)
        self.assertTrue(p1_meta.video_candidate)
        self.assertGreaterEqual(p1_meta.visual_score, 30)

        # Page 2: Speech bubbles + text area
        p2_crop, p2_meta = results[1]
        self.assertEqual(p2_meta.content_type, PageType.DIALOGUE)
        self.assertFalse(p2_meta.video_candidate)

        # Page 3: Skeleton artwork
        p3_crop, p3_meta = results[2]
        self.assertEqual(p3_meta.content_type, PageType.VISUAL)
        self.assertTrue(p3_meta.video_candidate)
        self.assertGreaterEqual(p3_meta.visual_score, 30)

    def test_multi_panel_pages(self):
        """
        Tests that sequential distinct comic panels separated by gutters
        are segmented as independent visual units with accurate metadata.
        """
        canvas = np.full((1800, 700, 3), 255, dtype=np.uint8)

        # Panel 1: (y=50..450)
        cv2.rectangle(canvas, (30, 50), (670, 450), (80, 70, 90), -1)
        cv2.circle(canvas, (350, 250), 100, (140, 160, 210), -1)
        cv2.rectangle(canvas, (30, 50), (670, 450), (0, 0, 0), 3)

        # Gutter (y=450..550, 100px)

        # Panel 2: (y=550..1000)
        cv2.rectangle(canvas, (30, 550), (670, 1000), (90, 80, 50), -1)
        cv2.circle(canvas, (350, 770), 110, (140, 160, 210), -1)
        cv2.rectangle(canvas, (30, 550), (670, 1000), (0, 0, 0), 3)

        # Gutter (y=1000..1100, 100px)

        # Panel 3: (y=1100..1650)
        cv2.rectangle(canvas, (30, 1100), (670, 1650), (50, 80, 100), -1)
        cv2.circle(canvas, (350, 1370), 120, (140, 160, 210), -1)
        cv2.rectangle(canvas, (30, 1100), (670, 1650), (0, 0, 0), 3)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3, f"Expected 3 distinct panels, got {len(results)}")

        for idx, (crop, meta) in enumerate(results, 1):
            self.assertTrue(meta.video_candidate)
            self.assertIn(meta.content_type, (PageType.PANEL, PageType.ARTWORK, PageType.SCENE))
            self.assertGreaterEqual(meta.visual_score, 40)
            self.assertGreaterEqual(meta.importance_score, 40)
            # Check to_dict() serialization contains all expected keys
            d = meta.to_dict()
            self.assertIn("video_candidate", d)
            self.assertIn("content_type", d)
            self.assertIn("importance_score", d)
            self.assertIn("split_reason", d)

    def test_text_only_regions_marked_not_video_candidate(self):
        """
        Tests that pure text-only narration cards are identified as TEXT_ONLY
        and strictly marked video_candidate=False.
        """
        canvas = np.full((1200, 700, 3), 255, dtype=np.uint8)

        # 1. Pure text card on white background (y=50..450, height=400)
        cv2.putText(canvas, "PROLOGUE: THE BEGINNING", (150, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        cv2.putText(canvas, "In an era long forgotten by mankind,", (80, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.putText(canvas, "monsters roamed freely across the land.", (70, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.putText(canvas, "Only one hunter dared to stand against them.", (60, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.putText(canvas, "His name was never recorded in history.", (75, 370), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # Panel border divider at y=480
        cv2.line(canvas, (0, 480), (700, 480), (0, 0, 0), 3)

        # 2. Rich visual illustration (y=520..1150)
        cv2.rectangle(canvas, (40, 520), (660, 1150), (40, 30, 50), -1)
        cv2.circle(canvas, (350, 800), 130, (140, 160, 210), -1) # Character face
        cv2.rectangle(canvas, (40, 520), (660, 1150), (0, 0, 0), 3)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 pages, got {len(results)}")

        text_page_crop, text_page_meta = results[0]
        art_page_crop, art_page_meta = results[1]

        # Requirement: TEXT_ONLY pages should be marked video_candidate=false
        self.assertIn(text_page_meta.content_type, (PageType.TEXT_ONLY, PageType.TEXT_DOMINANT, PageType.TEXT_BUBBLE))
        self.assertFalse(text_page_meta.video_candidate, "Text-only page must have video_candidate=False")

        # Artwork page must be video candidate
        self.assertTrue(art_page_meta.video_candidate)
        self.assertIn(art_page_meta.content_type, (PageType.ARTWORK, PageType.PANEL, PageType.SCENE))

    def test_large_whitespace_gutter_splitting(self):
        """
        Tests that an unusually large whitespace gutter between panels
        is cleanly split at the gutter and trimmed without generating empty pages.
        """
        canvas = np.full((1600, 800, 3), 255, dtype=np.uint8)

        # Panel 1: (y=50..400)
        cv2.rectangle(canvas, (50, 50), (750, 400), (70, 90, 80), -1)
        cv2.circle(canvas, (400, 220), 80, (140, 160, 210), -1)
        cv2.rectangle(canvas, (50, 50), (750, 400), (0, 0, 0), 3)

        # Large whitespace gutter of 500px (y=400..900)

        # Panel 2: (y=900..1400)
        cv2.rectangle(canvas, (50, 900), (750, 1400), (90, 70, 60), -1)
        cv2.circle(canvas, (400, 1150), 90, (140, 160, 210), -1)
        cv2.rectangle(canvas, (50, 900), (750, 1400), (0, 0, 0), 3)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 panels, got {len(results)}")

        for crop, meta in results:
            self.assertTrue(meta.video_candidate)
            self.assertIn(meta.split_reason, ("gutter", "scene_transition", "end_of_canvas"))
            # Trimming should have eliminated the 500px blank gutter (panel is 500px + padding)
            self.assertLessEqual(meta.height, 560)

    def test_complex_scene_boundaries(self):
        """
        Tests that a major scene transition (daytime bright sky -> dark nighttime cave)
        is recognized as a scene transition boundary and split cleanly.
        """
        canvas = np.full((1700, 800, 3), 255, dtype=np.uint8)

        # Scene 1: Bright daytime outdoor scene (y=50..700)
        # Background: Bright cyan sky (255, 220, 150) BGR
        cv2.rectangle(canvas, (30, 50), (770, 700), (255, 220, 150), -1)
        # Character in sunlight
        cv2.circle(canvas, (400, 400), 120, (140, 160, 210), -1)
        cv2.rectangle(canvas, (30, 50), (770, 700), (0, 0, 0), 3)

        # Gutter (y=700..850, 150px)

        # Scene 2: Dark nighttime cave scene (y=850..1550)
        # Background: Dark moody purple/black (30, 20, 40) BGR
        cv2.rectangle(canvas, (30, 850), (770, 1550), (30, 20, 40), -1)
        # Glowing torch + character
        cv2.circle(canvas, (300, 1100), 50, (50, 180, 255), -1) # Orange torch
        cv2.circle(canvas, (500, 1200), 110, (140, 160, 210), -1) # Character face
        cv2.rectangle(canvas, (30, 850), (770, 1550), (0, 0, 0), 3)

        # Verify is_scene_transition detects the color shift
        is_trans = SmartPaginator.is_scene_transition(canvas, 700, 850)
        self.assertTrue(is_trans, "Expected is_scene_transition to be True between day and night scenes")

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 separate scenes, got {len(results)}")

        crop1, meta1 = results[0]
        crop2, meta2 = results[1]

        self.assertTrue(meta1.video_candidate)
        self.assertTrue(meta2.video_candidate)
        self.assertEqual(meta1.split_reason, "scene_transition")

    def test_visual_dialogue_visual_layout(self):
        """
        Tests user specification:
        CHARACTER FRAME / DIALOGUE / WHITE SPACE / CHARACTER FRAME
        Must split into exactly 3 independent pages (never combined into 1):
        - Page 1: Top Character Frame (VISUAL, video_candidate=True)
        - Page 2: Dialogue Speech Bubble (DIALOGUE, video_candidate=False)
        - Page 3: Bottom Character Frame (VISUAL, video_candidate=True)
        """
        canvas = np.full((1600, 800, 3), 255, dtype=np.uint8)
        # Character frame 1 (y=50..550)
        cv2.rectangle(canvas, (50, 50), (750, 550), (30, 25, 40), -1)
        cv2.ellipse(canvas, (400, 300), (120, 150), 0, 0, 360, (140, 160, 210), -1)
        # Dialogue bubble in gutter (y=620..780)
        cv2.ellipse(canvas, (400, 700), (220, 70), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "I WILL NEVER SURRENDER!", (220, 705), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        # Whitespace gutter (y=780..950)
        # Character frame 2 (y=950..1450)
        cv2.rectangle(canvas, (50, 950), (750, 1450), (40, 35, 60), -1)
        cv2.ellipse(canvas, (400, 1200), (130, 160), 0, 0, 360, (130, 150, 200), -1)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3, f"Expected 3 independent pages, got {len(results)}")
        self.assertEqual(results[0][1].content_type, PageType.VISUAL)
        self.assertTrue(results[0][1].video_candidate)
        self.assertEqual(results[1][1].content_type, PageType.DIALOGUE)
        self.assertFalse(results[1][1].video_candidate)
        self.assertEqual(results[2][1].content_type, PageType.VISUAL)
        self.assertTrue(results[2][1].video_candidate)

    def test_multiple_panels_split_at_panel_boundaries(self):
        """
        Tests that multiple distinct framed panels are cleanly split at their panel boundaries.
        """
        canvas = np.full((1800, 800, 3), 255, dtype=np.uint8)
        # Panel 1: y=50..450
        cv2.rectangle(canvas, (50, 50), (750, 450), (40, 50, 80), -1)
        cv2.circle(canvas, (400, 250), 80, (130, 160, 210), -1)
        # Panel 2: y=550..950
        cv2.rectangle(canvas, (50, 550), (750, 950), (50, 40, 70), -1)
        cv2.circle(canvas, (400, 750), 90, (140, 150, 200), -1)
        # Panel 3: y=1050..1550
        cv2.rectangle(canvas, (50, 1050), (750, 1550), (60, 45, 40), -1)
        cv2.circle(canvas, (400, 1300), 100, (150, 170, 220), -1)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 3, f"Expected 3 separate panel pages, got {len(results)}")
        for idx, (_, meta) in enumerate(results):
            self.assertEqual(meta.content_type, PageType.VISUAL)
            self.assertTrue(meta.video_candidate)

    def test_speech_bubble_attached_to_character_composition(self):
        """
        Tests that a small speech bubble attached directly inside character frame artwork
        remains with the character visual to avoid damaging the composition.
        """
        canvas = np.full((900, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(canvas, (60, 100), (740, 750), (45, 35, 55), -1)
        cv2.ellipse(canvas, (400, 450), (140, 180), 0, 0, 360, (140, 160, 210), -1)
        cv2.ellipse(canvas, (580, 230), (130, 60), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (580, 230), (130, 60), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "HMPH...", (530, 235), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 1, f"Expected 1 intact page, got {len(results)}")
        self.assertIn(results[0][1].content_type, (PageType.VISUAL, PageType.VISUAL_WITH_TEXT, PageType.MIXED))
        self.assertTrue(results[0][1].video_candidate)

    def test_text_only_region(self):
        """
        Tests that a pure narration block (prologue / text card) is marked video_candidate = False.
        """
        canvas = np.full((1200, 800, 3), 255, dtype=np.uint8)
        cv2.putText(canvas, "CHAPTER 1: THE BEGINNING", (200, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.putText(canvas, "LONG AGO IN AN ANCIENT EMPIRE", (160, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.putText(canvas, "THERE LIVED A FEARED MONSTER", (170, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.rectangle(canvas, (50, 600), (750, 1100), (40, 50, 80), -1)
        cv2.circle(canvas, (400, 850), 100, (140, 160, 210), -1)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 pages, got {len(results)}")
        self.assertIn(results[0][1].content_type, (PageType.TEXT_ONLY, PageType.DIALOGUE))
        self.assertFalse(results[0][1].video_candidate)
        self.assertEqual(results[1][1].content_type, PageType.VISUAL)
        self.assertTrue(results[1][1].video_candidate)

    def test_large_whitespace_boundary(self):
        """
        Tests that a wide whitespace gutter (300px) cleanly separates panels without fragmenting artwork.
        """
        canvas = np.full((1700, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(canvas, (50, 50), (750, 600), (30, 25, 40), -1)
        cv2.circle(canvas, (400, 320), 100, (140, 160, 210), -1)
        # 300px white space gutter (y=600..900)
        cv2.rectangle(canvas, (50, 900), (750, 1550), (40, 35, 60), -1)
        cv2.circle(canvas, (400, 1200), 100, (140, 160, 210), -1)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 pages, got {len(results)}")
        for _, meta in results:
            self.assertEqual(meta.content_type, PageType.VISUAL)
            self.assertTrue(meta.video_candidate)

    def test_irregular_panel_boundaries(self):
        """
        Tests that irregular/slanted panel borders are cleanly separated without cutting characters.
        """
        canvas = np.full((1600, 800, 3), 255, dtype=np.uint8)
        pts_top = np.array([[50, 50], [750, 50], [750, 680], [50, 600]], np.int32)
        cv2.fillPoly(canvas, [pts_top], (40, 35, 55))
        cv2.circle(canvas, (400, 320), 100, (140, 160, 210), -1)

        pts_bot = np.array([[50, 720], [750, 800], [750, 1450], [50, 1450]], np.int32)
        cv2.fillPoly(canvas, [pts_bot], (55, 40, 35))
        cv2.circle(canvas, (400, 1100), 100, (140, 160, 210), -1)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 2, f"Expected 2 pages, got {len(results)}")
        for _, meta in results:
            self.assertEqual(meta.content_type, PageType.VISUAL)
            self.assertTrue(meta.video_candidate)

    def test_overlapping_complex_artwork(self):
        """
        Tests that complex overlapping artwork (giant monster + foreground hero) is preserved
        as a single intact visual page.
        """
        canvas = np.full((1600, 800, 3), (20, 15, 30), dtype=np.uint8)
        for y in range(0, 1600, 50):
            cv2.line(canvas, (0, y), (800, y), (30, 25, 45), 2)
        cv2.rectangle(canvas, (100, 100), (700, 1200), (45, 35, 60), -1)
        cv2.rectangle(canvas, (250, 700), (550, 1500), (70, 80, 120), -1)
        cv2.circle(canvas, (400, 950), 120, (140, 160, 210), -1)

        results = self.paginator.paginate_canvas(canvas)
        self.assertEqual(len(results), 1, f"Expected 1 intact page, got {len(results)}")
        self.assertEqual(results[0][1].content_type, PageType.VISUAL)
        self.assertTrue(results[0][1].video_candidate)
        self.assertGreaterEqual(results[0][1].height, 1300)

    def test_character_card_with_nameplate_and_speech_bubble_intact(self):
        """
        Tests that a tall character introduction card (~2200px) with top speech bubble,
        character portrait (blonde hair, skin tones, white blouse), bottom floral nameplate,
        and continuous background artwork is preserved without slicing the character in half across neck or body.
        """
        import os
        rene_path = "scratch/rene_combined.jpg"
        if os.path.exists(rene_path):
            img = cv2.imread(rene_path)
            if img is not None:
                real_results = self.paginator.paginate_canvas(img)
                self.assertEqual(len(real_results), 1, f"Expected 1 intact character card page, got {len(real_results)}")
                meta = real_results[0][1]
                self.assertGreaterEqual(meta.height, 2150)
                self.assertTrue(meta.video_candidate)
                self.assertGreaterEqual(meta.visual_score, 80)

        canvas = np.full((2200, 800, 3), (15, 25, 20), dtype=np.uint8) # Dark foliage background
        for y in range(0, 2200, 35):
            cv2.line(canvas, (0, y), (800, y), (30, 45, 35), 2)

        # 1. Top speech bubble (y=150..300) with dialogue
        cv2.ellipse(canvas, (350, 220), (220, 75), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (350, 220), (220, 75), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "HURRY AND FINISH YOUR MEAL", (170, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
        cv2.putText(canvas, "SO YOU CAN GET TO SCHOOL!", (180, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

        # 2. Character head, hair, face (y=350..800)
        cv2.circle(canvas, (400, 520), 180, (50, 180, 240), -1) # Golden blonde hair
        cv2.ellipse(canvas, (400, 580), (120, 150), 0, 0, 360, (140, 160, 210), -1) # Skin tone face
        cv2.ellipse(canvas, (400, 750), (45, 70), 0, 0, 360, (140, 160, 210), -1)  # Neck

        # 3. White blouse & torso (y=780..1500)
        cv2.rectangle(canvas, (200, 800), (600, 1500), (235, 235, 240), -1) # White blouse
        cv2.rectangle(canvas, (200, 800), (600, 1500), (180, 180, 190), 2)

        # 4. Bottom nameplate banner with floral garland (y=1700..2050)
        cv2.ellipse(canvas, (400, 1880), (240, 95), 0, 0, 360, (230, 240, 235), -1)
        cv2.ellipse(canvas, (400, 1880), (240, 95), 0, 0, 360, (80, 120, 90), 3)
        cv2.putText(canvas, "RENE HAIZELIN", (270, 1860), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 40, 30), 2)
        cv2.putText(canvas, "HEAD OF THE BARONY", (240, 1900), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 40, 30), 2)

        results = self.paginator.paginate_canvas(canvas)
        char_pages = [p for p in results if p[1].content_type in (PageType.VISUAL, PageType.CONTENT, PageType.VISUAL_WITH_TEXT) and p[1].height >= 1000]
        self.assertGreaterEqual(len(char_pages), 1, "Character portrait page must be preserved")
        char_meta = char_pages[0][1]
        self.assertGreaterEqual(char_meta.height, 1100, "Character portrait must remain intact without slicing neck or body")
        self.assertTrue(char_meta.video_candidate)

    def test_visual_content_region_separated_from_speech_bubbles_and_gutters(self):
        """
        Tests that in default mode (separate_speech_bubbles=True), speech bubbles
        hovering above and below an artwork panel are cleanly separated into DIALOGUE pages,
        leaving the Visual Content Region in the middle as a pure VISUAL page (candidate=True)
        without any speech bubbles or empty white gutters sticking to it.
        """
        canvas = np.full((1200, 800, 3), 255, dtype=np.uint8)

        # Top speech bubble (y=40..120)
        cv2.ellipse(canvas, (400, 80), (120, 35), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "LOOK AT THAT MONSTER!", (240, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # Panel 1 at y=200..800
        cv2.rectangle(canvas, (50, 200), (750, 800), (30, 40, 60), -1)
        cv2.circle(canvas, (400, 500), 120, (140, 160, 210), -1)

        # Bottom speech bubble (y=900..1000)
        cv2.ellipse(canvas, (400, 950), (120, 35), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "WE HAVE TO ESCAPE NOW!", (240, 955), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        paginator = SmartPaginator(PaginationConfig())
        results = paginator.paginate_canvas(canvas)

        self.assertEqual(len(results), 3, f"Expected 3 pages (top dialogue, visual panel, bottom dialogue), got {len(results)}")
        
        # Page 0: Top speech bubble (DIALOGUE)
        top_crop, top_meta = results[0]
        self.assertEqual(top_meta.content_type, PageType.DIALOGUE)
        self.assertFalse(top_meta.video_candidate)

        # Page 1: Pure Visual Content Region
        art_crop, art_meta = results[1]
        self.assertEqual(art_meta.content_type, PageType.VISUAL)
        self.assertTrue(art_meta.video_candidate)
        # Visual panel is 200..800; trimmed cleanly without top/bottom white gutters
        self.assertGreaterEqual(art_meta.height, 595)
        self.assertLessEqual(art_meta.height, 615)
        self.assertGreaterEqual(art_meta.visual_score, 40)

        # Page 2: Bottom speech bubble (DIALOGUE)
        bot_crop, bot_meta = results[2]
        self.assertEqual(bot_meta.content_type, PageType.DIALOGUE)
        self.assertFalse(bot_meta.video_candidate)

    def test_black_gutter_and_bubble_separation(self):
        """
        Tests that on dark/black canvases (e.g. night scenes, horror, dark mode manhwa),
        speech bubbles in black gutters are cleanly separated from the Visual Content Region,
        and empty black background margins are completely trimmed out.
        """
        canvas = np.full((1200, 800, 3), 0, dtype=np.uint8)

        # Top bubble on black canvas
        cv2.ellipse(canvas, (400, 80), (120, 35), 0, 0, 360, (255, 255, 255), 2)
        cv2.putText(canvas, "DARK NIGHTMARE!", (280, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Panel 1 at 200..800
        cv2.rectangle(canvas, (50, 200), (750, 800), (40, 50, 70), -1)
        cv2.circle(canvas, (400, 500), 120, (140, 160, 210), -1)
        cv2.rectangle(canvas, (50, 200), (750, 800), (255, 255, 255), 3)

        # Bottom bubble on black canvas
        cv2.ellipse(canvas, (400, 950), (120, 35), 0, 0, 360, (255, 255, 255), 2)
        cv2.putText(canvas, "SHADOW ESCAPE!", (280, 955), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        paginator = SmartPaginator(PaginationConfig())
        results = paginator.paginate_canvas(canvas)

        self.assertEqual(len(results), 3, f"Expected 3 pages on black canvas, got {len(results)}")
        
        art_crop, art_meta = results[1]
        self.assertEqual(art_meta.content_type, PageType.VISUAL)
        self.assertTrue(art_meta.video_candidate)
        self.assertGreaterEqual(art_meta.height, 595)
        self.assertLessEqual(art_meta.height, 615)

    def test_gutter_whitespace_ignored_between_panels(self):
        """
        Tests that large empty whitespace gutters (150px-200px) between two distinct panels
        only serve as clean split boundaries, without creating any blank or fragmented pages.
        Each panel is trimmed with aesthetic padding.
        """
        canvas = np.full((2000, 800, 3), 255, dtype=np.uint8)

        # Panel 1 at y=100..700
        cv2.rectangle(canvas, (50, 100), (750, 700), (45, 35, 60), -1)
        cv2.circle(canvas, (400, 400), 130, (140, 160, 210), -1)

        # Large 250px whitespace gutter (y=700..950)

        # Panel 2 at y=950..1650
        cv2.rectangle(canvas, (50, 950), (750, 1650), (60, 45, 35), -1)
        cv2.circle(canvas, (400, 1300), 130, (140, 160, 210), -1)

        paginator = SmartPaginator(PaginationConfig(min_page_height=350))
        results = paginator.paginate_canvas(canvas)

        self.assertEqual(len(results), 2, f"Expected 2 visual panel pages, got {len(results)}")
        for i, (_, meta) in enumerate(results):
            self.assertEqual(meta.content_type, PageType.VISUAL)
            self.assertTrue(meta.video_candidate)
            self.assertGreaterEqual(meta.height, 550)
            self.assertLessEqual(meta.height, 750) # Generously trimmed without excessive gutter

    def test_character_card_full_visual_integrity_default_mode(self):
        """
        Tests that a full-height character introduction card (~2200px) is preserved as
        a single complete, intact Visual Content Region in default pagination mode.
        """
        import os
        rene_path = "scratch/rene_combined.jpg"
        if os.path.exists(rene_path):
            img = cv2.imread(rene_path)
            if img is not None:
                paginator = SmartPaginator(PaginationConfig()) # Default configuration
                self.assertTrue(paginator.config.separate_speech_bubbles)
                results = paginator.paginate_canvas(img)
                self.assertEqual(len(results), 1, f"Expected 1 full character card page, got {len(results)}")
                meta = results[0][1]
                self.assertGreaterEqual(meta.height, 2100)
                self.assertIn(meta.content_type, (PageType.VISUAL, PageType.MIXED))
                self.assertTrue(meta.video_candidate)
    def test_tall_character_and_bubble_not_split_across_pages(self):
        """
        Tests that a canvas containing:
        - Speech bubble (~450px tall with multi-line text)
        - Tall character body (~3100px tall)
        is not split through the character's body or through the speech bubble.
        """
        canvas = np.full((3800, 800, 3), 255, dtype=np.uint8)
        # 1. Speech bubble at top (y=100..450)
        cv2.ellipse(canvas, (400, 275), (250, 150), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "I CANNOT HELP", (280, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        cv2.putText(canvas, "YOU. LEAVE.", (300, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        # 2. Gutter (y=450..550)

        # 3. Tall character body (y=550..3650)
        # Face and hair
        cv2.circle(canvas, (400, 750), 100, (40, 40, 50), -1)
        cv2.ellipse(canvas, (400, 800), (70, 90), 0, 0, 360, (140, 160, 210), -1)
        # Torso / Robes
        cv2.rectangle(canvas, (250, 900), (550, 2500), (50, 40, 60), -1)
        # Legs / Boots
        cv2.rectangle(canvas, (300, 2500), (500, 3650), (30, 25, 35), -1)

        paginator = SmartPaginator(PaginationConfig())
        results = paginator.paginate_canvas(canvas)
        self.assertGreaterEqual(len(results), 2)
        for _, meta in results:
            self.assertFalse(1000 < meta.y_start < 3400, f"Character torso was cut at {meta.y_start}!")


    def test_recap_sentence_counting_and_short_recap_validation(self):
        from app import count_recap_sentences, verify_gemini_response_format, parse_gemini_recap_text

        # 1. Test counting on short text (< 10 sentences)
        short_text = """1 - Câu thứ nhất kết thúc bằng dấu chấm.#
2 - Câu thứ hai rất kịch tính! Câu thứ ba tiếp nối ngay sau đó?#
3 - Đây là câu thứ tư.#"""
        parsed_short = parse_gemini_recap_text(short_text)
        count_short = count_recap_sentences(parsed_short)
        self.assertEqual(count_short, 4)

        # 2. Non-intro with < 10 sentences MUST fail validation
        is_v, err = verify_gemini_response_format(short_text, is_intro=False, min_sentences=10)
        self.assertFalse(is_v)
        self.assertIn("quá ngắn", err)

        # 3. Intro hook validation: 1 to 5 sentences on a single line MUST pass
        single_intro = "18 - Tưởng đâu cống hiến hết thanh xuân làm nô lệ thì được về hưu an nhàn, ai ngờ thanh niên số nhọ lại bị cấp trên thanh lý môn hộ!#"
        is_v_intro, err_intro = verify_gemini_response_format(single_intro, is_intro=True)
        self.assertTrue(is_v_intro, f"Single-sentence intro should pass: {err_intro}")

        # Intro hook with 2-4 sentences on 1 line must pass
        multi_intro = "18 - Tưởng đâu làm nô lệ sẽ được yên ổn nghỉ hưu. Ai ngờ thanh niên lại bị sếp thanh lý! Thân phận con chó săn kết thúc trong bi thảm? Liệu anh có thể trọng sinh rửa hận!#"
        is_v_multi_intro, err_multi_intro = verify_gemini_response_format(multi_intro, is_intro=True)
        self.assertTrue(is_v_multi_intro, f"Multi-sentence intro on 1 line should pass: {err_multi_intro}")

        # Intro hook with 4-5 multi-lines must pass
        multi_line_intro = """1 - Tưởng đâu cống hiến hết thanh xuân làm nô lệ thì được về hưu an nhàn.#
2 - Ai ngờ thanh niên số nhọ lại bị cấp trên thanh lý môn hộ!#
3 - Thân phận con chó săn kết thúc trong bi thảm trong ngục tối.#
4 - Liệu anh có thể trọng sinh rửa hận và leo lên đỉnh cao?#"""
        is_v_lines, err_lines = verify_gemini_response_format(multi_line_intro, is_intro=True)
        self.assertTrue(is_v_lines, f"Multi-line 4-scene intro should pass: {err_lines}")

        # 4. Non-intro with >= 10 sentences MUST pass validation
        ten_sentences_text = """1 - Câu một bắt đầu hành trình. Câu hai mở ra bí mật mới.#
2 - Câu ba xuất hiện kẻ thù. Câu bốn giao chiến kịch liệt!#
3 - Câu năm tung ra tuyệt chiêu? Câu sáu đối phương chống đỡ.#
4 - Câu bảy lật ngược thế cờ. Câu tám giành lấy thắng lợi.#
5 - Câu chín thu dọn chiến trường. Câu mười chuẩn bị cho thử thách tiếp theo.#"""
        parsed_ten = parse_gemini_recap_text(ten_sentences_text)
        count_ten = count_recap_sentences(parsed_ten)
        self.assertGreaterEqual(count_ten, 10)

        is_v_ten, err_ten = verify_gemini_response_format(ten_sentences_text, is_intro=False, min_sentences=10)
        self.assertTrue(is_v_ten, f"Should pass when >= 10 sentences: {err_ten}")

        # 5. Non-intro with < 12 sentences MUST fail when min_sentences=12
        eleven_lines_text = "\n".join([f"{i} - Câu kể thứ {i} về diễn biến câu chuyện.#" for i in range(1, 12)])
        is_v_11, err_11 = verify_gemini_response_format(eleven_lines_text, is_intro=False, min_sentences=12)
        self.assertFalse(is_v_11)
        self.assertIn("quá ngắn", err_11)

        # Non-intro with >= 12 lines MUST pass when min_sentences=12
        twelve_lines_text = "\n".join([f"{i} - Câu kể thứ {i} về diễn biến câu chuyện.#" for i in range(1, 13)])
        is_v_12, err_12 = verify_gemini_response_format(twelve_lines_text, is_intro=False, min_sentences=12)
        self.assertTrue(is_v_12, f"Should pass when >= 12 lines: {err_12}")

        # 6. Test generate_gemini_prompt for Ep 1 includes hook directive
        from app import generate_gemini_prompt
        ep1_prompt = generate_gemini_prompt("Omniscient Reader", 1, 50, "vi")
        self.assertIn("hook", ep1_prompt.lower())

        # 7. Number formatting like 5.500 or 3.14 shouldn't count as sentence splits
        intro_with_numbers = [{"speech": "Đã cày 5.500 giờ trong game. Seongho sở hữu 3.5 triệu điểm kinh nghiệm!"}]
        self.assertEqual(count_recap_sentences(intro_with_numbers), 2)

    def test_overlapping_character_and_bubble_kept_in_same_page(self):
        """
        Rule: Nếu character và speech bubble chồng lên nhau, không có boundary rõ -> giữ cùng Page.
        """
        canvas = np.full((1200, 600, 3), 255, dtype=np.uint8)
        # Panel containing character artwork
        cv2.rectangle(canvas, (50, 100), (550, 900), (45, 55, 75), -1)
        # Character skin region (y=250..650)
        cv2.ellipse(canvas, (300, 450), (120, 180), 0, 0, 360, (140, 160, 210), -1)
        # Speech bubble overlapping character skin & body (y=400..600)
        cv2.ellipse(canvas, (320, 500), (160, 80), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (320, 500), (160, 80), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "OVERLAPPING BUBBLE", (200, 505), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)
        # The character and bubble must be in the same page (not sliced in between)
        self.assertEqual(len(results), 1)
        _, meta = results[0]
        self.assertLessEqual(meta.y_start, 120)
        self.assertGreaterEqual(meta.y_end, 880)

    def test_clear_boundary_character_bubble_character_separated(self):
        """
        Rule: Nếu có boundary rõ giữa character -> bubble/background -> character/object -> tách thành các Page riêng.
        """
        canvas = np.full((2400, 600, 3), 255, dtype=np.uint8)
        # Character 1: y=100..700
        cv2.rectangle(canvas, (50, 100), (550, 700), (40, 50, 70), -1)
        cv2.ellipse(canvas, (300, 400), (100, 150), 0, 0, 360, (140, 160, 210), -1)

        # White Gutter: y=700..900

        # Standalone Speech bubble: y=950..1250
        cv2.ellipse(canvas, (300, 1100), (200, 80), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (300, 1100), (200, 80), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "INDEPENDENT DIALOGUE", (170, 1105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # White Gutter: y=1250..1450

        # Character 2: y=1500..2100
        cv2.rectangle(canvas, (50, 1500), (550, 2100), (70, 40, 50), -1)
        cv2.ellipse(canvas, (300, 1800), (100, 150), 0, 0, 360, (140, 160, 210), -1)

        results = self.paginator.paginate_canvas(canvas)
        # Must be separated into 3 distinct pages
        self.assertEqual(len(results), 3)
        p1, p2, p3 = results[0][1], results[1][1], results[2][1]
        self.assertEqual(p1.page_type, PageType.CONTENT)
        self.assertEqual(p2.page_type, PageType.TEXT_BUBBLE)
        self.assertEqual(p3.page_type, PageType.CONTENT)

    def test_small_useless_noise_and_border_merged(self):
        """
        Rule: Không tạo page quá nhỏ do noise, border hoặc khoảng trắng vô nghĩa; merge các vùng nhỏ không có giá trị.
        """
        canvas = np.full((1200, 600, 3), 255, dtype=np.uint8)
        # Tiny noise line (< 30px) in gutter at y=50..70
        cv2.line(canvas, (100, 60), (300, 60), (180, 180, 180), 2)
        # Main artwork panel at y=150..800
        cv2.rectangle(canvas, (50, 150), (550, 800), (40, 60, 90), -1)

        results = self.paginator.paginate_canvas(canvas)
        # Should not create a tiny noise page
        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(results[0][1].height, 500)

    def test_paginate_canvas_start_page_index(self):
        """
        Tests that start_page_index allows continuous monotonic page indexing and ID generation.
        """
        canvas = np.full((1800, 600, 3), 255, dtype=np.uint8)
        cv2.rectangle(canvas, (50, 100), (550, 700), (40, 50, 70), -1)
        cv2.rectangle(canvas, (50, 900), (550, 1500), (70, 40, 50), -1)

        results = self.paginator.paginate_canvas(canvas, start_page_index=10)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][1].page_index, 10)
        self.assertEqual(results[0][1].page_id, "page_010")
        self.assertEqual(results[1][1].page_index, 11)
        self.assertEqual(results[1][1].page_id, "page_011")

    def test_paginate_pdf_unconstrained_smart_pages(self):
        """
        TASK: Fix Smart Pagination PDF Page Limit
        Acceptance Criteria:
        - Bỏ hoàn toàn giới hạn số lượng Page dựa trên số trang vật lý của PDF.
        - PDF physical page chỉ là nguồn ảnh đầu vào, một trang PDF có thể tạo ra nhiều Smart Pages.
        - Tổng số Smart Pages không bị giới hạn bởi tổng số trang vật lý của PDF.
        - Không reset Page numbering khi chuyển sang PDF page tiếp theo.
        - Page ID tăng liên tục xuyên suốt toàn bộ tập:
            PDF physical page 1 -> Page 1, Page 2, Page 3...
            PDF physical page 2 -> Page 4, Page 5, Page 6...
            PDF physical page 3 -> Page 7, Page 8...
        """
        import os
        import tempfile
        from PIL import Image

        # Create 3 physical PDF pages (each containing multiple panels and bubbles)
        phys_pages = []

        # Physical Page 1: Panel A (100..600), Dialogue Bubble (800..1100), Panel B (1300..1800)
        p1 = np.full((2000, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(p1, (50, 100), (750, 600), (40, 50, 80), -1)
        cv2.ellipse(p1, (400, 950), (220, 80), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(p1, (400, 950), (220, 80), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(p1, "SPEECH ON PAGE 1", (250, 955), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.rectangle(p1, (50, 1300), (750, 1800), (60, 40, 40), -1)
        phys_pages.append(p1)

        # Physical Page 2: Panel C (100..600), Dialogue Bubble (800..1100), Panel D (1300..1800)
        p2 = np.full((2000, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(p2, (50, 100), (750, 600), (50, 80, 50), -1)
        cv2.ellipse(p2, (400, 950), (220, 80), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(p2, (400, 950), (220, 80), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(p2, "SPEECH ON PAGE 2", (250, 955), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        cv2.rectangle(p2, (50, 1300), (750, 1800), (70, 70, 40), -1)
        phys_pages.append(p2)

        # Physical Page 3: Panel E (100..700), Dialogue Bubble (900..1200)
        p3 = np.full((1400, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(p3, (50, 100), (750, 700), (40, 70, 90), -1)
        cv2.ellipse(p3, (400, 1050), (220, 80), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(p3, (400, 1050), (220, 80), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(p3, "SPEECH ON PAGE 3", (250, 1055), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        phys_pages.append(p3)

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = os.path.join(tmp_dir, "test_input.pdf")
            pil_pages = [Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for im in phys_pages]
            pil_pages[0].save(pdf_path, "PDF", save_all=True, append_images=pil_pages[1:])

            # Execute paginate_pdf
            results = self.paginator.paginate_pdf(pdf_path, target_width=800)

            # 1. Total Smart Pages MUST NOT be bounded by the 3 physical PDF pages
            self.assertGreater(len(results), 3, f"Expected >3 Smart Pages from 3 physical pages, got {len(results)}")
            self.assertGreaterEqual(len(results), 7, f"Expected at least 7-8 Smart Pages, got {len(results)}")

            # 2. Page numbering and Page IDs must be strictly continuous (1, 2, 3, 4, 5, 6, 7, 8...)
            for idx, (_, meta) in enumerate(results, start=1):
                self.assertEqual(meta.page_index, idx, f"Page index should be {idx}, got {meta.page_index}")
                self.assertEqual(meta.page_id, f"page_{idx:03d}", f"Page ID should be page_{idx:03d}, got {meta.page_id}")
                self.assertGreaterEqual(meta.visual_score, 0)
                self.assertLessEqual(meta.visual_score, 100)

            # 3. Check that Smart Pages originate across different physical pages
            phys_page_origins = [meta.pdf_page for _, meta in results if meta.pdf_page is not None]
            self.assertIn(1, phys_page_origins, "Should have Smart Pages originating from physical page 1")
            self.assertIn(2, phys_page_origins, "Should have Smart Pages originating from physical page 2")
            self.assertIn(3, phys_page_origins, "Should have Smart Pages originating from physical page 3")

            # Verify that physical page 1 produces multiple smart pages
            p1_count = sum(1 for p in phys_page_origins if p == 1)
            self.assertGreater(p1_count, 1, f"Physical page 1 must produce multiple Smart Pages, got {p1_count}")

            # Verify that physical page 2 produces multiple smart pages
            p2_count = sum(1 for p in phys_page_origins if p == 2)
            self.assertGreater(p2_count, 1, f"Physical page 2 must produce multiple Smart Pages, got {p2_count}")

            # Verify that physical page 3 produces multiple smart pages
            p3_count = sum(1 for p in phys_page_origins if p == 3)
            self.assertGreater(p3_count, 1, f"Physical page 3 must produce multiple Smart Pages, got {p3_count}")

            # 4. Also test list of images input directly to paginate_pdf
            results_list = self.paginator.paginate_pdf(phys_pages, target_width=800)
            self.assertEqual(len(results_list), len(results))
            self.assertEqual(results_list[0][1].page_index, 1)
            self.assertEqual(results_list[-1][1].page_index, len(results_list))

    def test_continuous_scene_with_internal_composition_kept_as_single_page(self):
        """
        Tests user specification:
        A continuous comic panel/scene MUST remain as ONE single Page even when:
        - The image composition changes vertically (mountain -> temple -> warrior -> action -> smoke)
        - Characters appear after background elements
        - Visual density or camera framing shifts
        - Embedded sound effects or dialogue bubbles exist without panel dividers or gutters
        
        Must NOT split into Page 2 (mountain), Page 3 (continuation), Page 4 (warrior), Page 5 (action).
        """
        canvas = np.full((2800, 800, 3), (35, 30, 45), dtype=np.uint8)

        # Continuous background artwork from y=0 to y=2800 without gutters
        for y in range(0, 2800, 40):
            cv2.line(canvas, (0, y), (800, y), (45 + int(10 * np.sin(y / 100.0)), 40, 60), 2)

        pts_mountain = np.array([[0, 800], [250, 400], [500, 700], [800, 350], [800, 1500], [0, 1500]], np.int32)
        cv2.fillPoly(canvas, [pts_mountain], (60, 50, 70))

        cv2.rectangle(canvas, (200, 1400), (600, 2200), (80, 70, 90), -1)
        cv2.rectangle(canvas, (250, 2150), (550, 2500), (90, 80, 110), -1)
        cv2.ellipse(canvas, (400, 2400), (100, 140), 0, 0, 360, (140, 160, 210), -1)
        cv2.circle(canvas, (400, 2300), 90, (20, 20, 30), -1)
        cv2.ellipse(canvas, (450, 2600), (250, 120), 45, 0, 180, (0, 220, 255), 8)

        for y in range(2500, 2800, 50):
            cv2.circle(canvas, (200 + (y % 400), y), 60, (70, 65, 85), -1)

        results = self.paginator.paginate_canvas(canvas)

        # MUST remain ONE single continuous Page!
        self.assertEqual(len(results), 1, f"Expected continuous scene to be 1 Page, but got {len(results)} pages!")
        meta = results[0][1]
        self.assertEqual(meta.content_type, PageType.VISUAL)
        self.assertTrue(meta.video_candidate)
        self.assertGreaterEqual(meta.height, 2400)
        self.assertGreaterEqual(meta.visual_score, 25)


    def test_2d_panel_box_segmentation(self):
        """
        Tests Proposal 1: 2D panel box segmentation detects multi-panel layouts
        and side-by-side (parallel) panels with clean coordinates.
        """
        canvas = np.full((1000, 800, 3), 255, dtype=np.uint8)
        # Side-by-side panels
        # Left panel: x=40..370, y=100..800
        cv2.rectangle(canvas, (40, 100), (370, 800), (30, 40, 60), -1)
        cv2.rectangle(canvas, (40, 100), (370, 800), (0, 0, 0), 4)
        # Right panel: x=430..760, y=100..800
        cv2.rectangle(canvas, (430, 100), (760, 800), (60, 40, 30), -1)
        cv2.rectangle(canvas, (430, 100), (760, 800), (0, 0, 0), 4)

        panels = SmartPaginator.detect_panels_2d(canvas, bg_val=255)
        self.assertGreaterEqual(len(panels), 2, "Expected at least 2 panels detected")
        side_by_side_count = sum(1 for p in panels if p.get("is_side_by_side", False))
        self.assertGreaterEqual(side_by_side_count, 2, "Expected side-by-side flag on both panels")

        # Verify paginate_canvas attaches sub_panels to PageMetadata
        results = self.paginator.paginate_canvas(canvas)
        self.assertGreaterEqual(len(results), 1)
        meta = results[0][1]
        self.assertGreaterEqual(len(meta.sub_panels), 2)
        meta_dict = meta.to_dict()
        self.assertIn("subPanels", meta_dict)
        self.assertIn("subPanelDetails", meta_dict)

    def test_smart_focal_point_calculation(self):
        """
        Tests Proposal 2: Smart focal point and camera path generation calculates normalized
        focal coordinates and integrates with MotionPlanner.
        """
        from renderer.motion import MotionPlanner

        canvas = np.full((1200, 800, 3), 255, dtype=np.uint8)
        # Draw a character face/head in upper-right quadrant
        cv2.circle(canvas, (600, 300), 80, (180, 200, 240), -1) # skin tone
        cv2.circle(canvas, (575, 290), 12, (20, 20, 20), -1) # eyes
        cv2.circle(canvas, (625, 290), 12, (20, 20, 20), -1)
        cv2.ellipse(canvas, (600, 330), (25, 10), 0, 0, 180, (50, 50, 200), 2) # smile

        # Speech bubble in upper-left quadrant
        cv2.ellipse(canvas, (200, 200), (140, 50), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (200, 200), (140, 50), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "LOOK OVER HERE!", (100, 205), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        primary_focal, focal_pts, camera_hint = SmartPaginator.calculate_focal_points(canvas, bg_val=255)
        fx, fy = primary_focal
        self.assertTrue(0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0, f"Focal point out of bounds: {primary_focal}")
        self.assertGreaterEqual(len(focal_pts), 1, "Expected detected focal points")
        self.assertIn(camera_hint, ["zoom_in", "zoom_out", "pan_left_to_right", "pan_top_to_bottom", "static"])

        # Test MotionPlanner integration with focal point
        plan = MotionPlanner.generate_plan(
            page_id=1,
            duration=3.0,
            bounds=(0, 0, 800, 1200),
            focal_point=primary_focal,
            camera_hint=camera_hint
        )
        self.assertIsNotNone(plan)
        self.assertGreater(len(plan.keyframes), 0)

    def test_comic_vision_detector_ensemble(self):
        """
        Tests Proposal 3: Lightweight comic vision detector ensemble identifies
        panels, characters, speech bubbles, and SFX text.
        """
        canvas = np.full((1200, 800, 3), 255, dtype=np.uint8)
        # 1. Panel border
        cv2.rectangle(canvas, (50, 50), (750, 1150), (0, 0, 0), 4)

        # 2. Speech bubble
        cv2.ellipse(canvas, (300, 250), (150, 50), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (300, 250), (150, 50), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "WHAT WAS THAT?", (200, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # 3. Character face
        cv2.circle(canvas, (400, 700), 100, (190, 205, 235), -1)
        cv2.circle(canvas, (360, 680), 15, (20, 20, 20), -1)
        cv2.circle(canvas, (440, 680), 15, (20, 20, 20), -1)

        # 4. SFX text (high contrast text)
        cv2.putText(canvas, "BOOOOOM!", (180, 500), cv2.FONT_HERSHEY_COMPLEX, 1.8, (0, 0, 220), 4)

        detections = ComicVisionDetector.detect_all(canvas, bg_val=255)
        self.assertIn("panels", detections)
        self.assertIn("characters", detections)
        self.assertIn("bubbles", detections)
        self.assertIn("sfx", detections)
        self.assertGreaterEqual(len(detections["bubbles"]), 1, "Expected speech bubble detected")
        self.assertGreaterEqual(len(detections["characters"]), 1, "Expected character detected")

    def test_narrative_beat_clustering(self):
        """
        Tests Proposal 4: Narrative beat clustering combines adjacent rapid dialogue
        bubbles (< 180px gap) into unified dialogue beat blocks.
        """
        from renderer.smart_pagination import VisualContentBlock

        blocks = [
            VisualContentBlock(start_y=100, end_y=300, height=200, block_type=PageType.DIALOGUE, avg_activity=0.3),
            VisualContentBlock(start_y=380, end_y=600, height=220, block_type=PageType.DIALOGUE, avg_activity=0.35),
            VisualContentBlock(start_y=1000, end_y=1200, height=200, block_type=PageType.DIALOGUE, avg_activity=0.3)
        ]

        clustered = SmartPaginator.cluster_narrative_beats(blocks, max_dialogue_gap=180, max_cluster_height=1400)
        self.assertEqual(len(clustered), 2, f"Expected 2 clustered blocks (first 2 merged, 3rd standalone), got {len(clustered)}")
        self.assertEqual(clustered[0].start_y, 100)
        self.assertEqual(clustered[0].end_y, 600)
        self.assertEqual(clustered[0].height, 500)
        self.assertEqual(clustered[0].block_type, PageType.DIALOGUE)

    def test_auto_layer_separation(self):
        """
        Tests Proposal 5: Auto layer separation generates clean background plate
        and transparent bubble overlay RGBA PNG for video animations.
        """
        canvas = np.full((800, 600, 3), (200, 150, 100), dtype=np.uint8)
        # Speech bubble
        cv2.ellipse(canvas, (300, 400), (160, 60), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(canvas, (300, 400), (160, 60), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "UNBELIEVABLE!", (200, 405), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        layers = SmartPaginator.separate_page_layers(canvas, bg_val=255)
        self.assertIn("clean_plate", layers)
        self.assertIn("bubble_overlay", layers)
        self.assertIn("bubble_count", layers)
        self.assertGreaterEqual(layers["bubble_count"], 1)

        clean_plate = layers["clean_plate"]
        bubble_overlay = layers["bubble_overlay"]
        self.assertEqual(clean_plate.shape, (800, 600, 3))
        self.assertEqual(bubble_overlay.shape, (800, 600, 4))
        self.assertGreater(np.sum(bubble_overlay[:, :, 3] > 0), 1000)

    def test_page_tag_classification_and_metadata(self):
        """
        Tests the 5-tag classification system:
          - CHARACTER_ART (Main character is primary visual)
          - CHARACTER_SCENE (Character + background/scene)
          - BACKGROUND_SCENE (Scenery/architecture/crowd)
          - ACTION_ART (Combat/action/skill visual)
          - NON_VISUAL (Speech bubble, narration, blank, credit/ads)
        """
        # 1. Verify PageTag constants and collections
        self.assertEqual(PageTag.CHARACTER_ART, "CHARACTER_ART")
        self.assertEqual(PageTag.CHARACTER_SCENE, "CHARACTER_SCENE")
        self.assertEqual(PageTag.BACKGROUND_SCENE, "BACKGROUND_SCENE")
        self.assertEqual(PageTag.ACTION_ART, "ACTION_ART")
        self.assertEqual(PageTag.NON_VISUAL, "NON_VISUAL")
        self.assertEqual(len(PageTag.ALL_TAGS), 5)
        self.assertEqual(set(PageTag.KEEP_TAGS), {"CHARACTER_ART", "CHARACTER_SCENE", "BACKGROUND_SCENE", "ACTION_ART"})
        self.assertEqual(PageTag.REJECT_TAGS, ["NON_VISUAL"])

        # 2. Verify PageMetadata serialization
        meta = PageMetadata(
            page_index=1,
            y_start=0,
            y_end=500,
            height=500,
            page_type=PageType.VISUAL,
            content_score=0.8,
            boundary_confidence=0.9,
            content_type=PageType.VISUAL,
            page_tag=PageTag.CHARACTER_ART
        )
        d = meta.to_dict()
        self.assertEqual(d["page_tag"], PageTag.CHARACTER_ART)
        self.assertEqual(d["pageTag"], PageTag.CHARACTER_ART)
        self.assertEqual(d["tag"], PageTag.CHARACTER_ART)

        # 3. Test classify_page_tag for NON_VISUAL
        blank_img = np.full((300, 400, 3), 255, dtype=np.uint8)
        tag_blank = SmartPaginator.classify_page_tag(blank_img, p_type=PageType.EMPTY_GUTTER, visual_score=5)
        self.assertEqual(tag_blank, PageTag.NON_VISUAL)

        dialogue_img = np.full((120, 500, 3), 255, dtype=np.uint8)
        cv2.putText(dialogue_img, "Speech bubble content", (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        tag_dialogue = SmartPaginator.classify_page_tag(dialogue_img, content_type=PageType.DIALOGUE, visual_score=15, text_score=60)
        self.assertEqual(tag_dialogue, PageTag.NON_VISUAL)

        # 4. Test classify_page_tag for ACTION_ART (intense diagonal speedlines and high action context)
        action_img = np.zeros((600, 600, 3), dtype=np.uint8)
        for i in range(0, 600, 15):
            cv2.line(action_img, (0, i), (i, 600), (255, 200, 50), 3)
            cv2.line(action_img, (i, 0), (600, 600 - i), (200, 50, 255), 2)
        tag_action = SmartPaginator.classify_page_tag(
            action_img,
            visual_score=85,
            score_breakdown={"character_presence": 20.0, "action_context": 92.0, "visual_detail": 85.0, "semantic_similarity": 70.0}
        )
        self.assertEqual(tag_action, PageTag.ACTION_ART)

        # 5. Test classify_page_tag for BACKGROUND_SCENE (architectural lines, low character presence)
        scene_img = np.zeros((600, 600, 3), dtype=np.uint8)
        # Draw brick pattern / buildings
        for y in range(50, 550, 40):
            cv2.line(scene_img, (50, y), (550, y), (180, 180, 180), 2)
        for x in range(50, 550, 50):
            cv2.line(scene_img, (x, 50), (x, 550), (160, 160, 160), 2)
        tag_scene = SmartPaginator.classify_page_tag(
            scene_img,
            visual_score=70,
            score_breakdown={"character_presence": 10.0, "action_context": 30.0, "visual_detail": 65.0, "semantic_similarity": 60.0}
        )
        self.assertEqual(tag_scene, PageTag.BACKGROUND_SCENE)

        # 6. Test classify_page_tag for CHARACTER_ART (strong skin tone and face focal contrast)
        char_img = np.full((600, 500, 3), (230, 230, 230), dtype=np.uint8)
        # Face / skin region: BGR around (140, 170, 220)
        cv2.ellipse(char_img, (250, 250), (120, 160), 0, 0, 360, (140, 170, 220), -1)
        tag_char = SmartPaginator.classify_page_tag(
            char_img,
            visual_score=75,
            score_breakdown={"character_presence": 75.0, "action_context": 35.0, "visual_detail": 50.0, "semantic_similarity": 65.0}
        )
        self.assertEqual(tag_char, PageTag.CHARACTER_ART)

        # 7. Test SmartPaginator.is_video_frame respects page_tag
        meta_non_vis = PageMetadata(
            page_index=1, y_start=0, y_end=100, height=100,
            page_type=PageType.VISUAL, content_score=0.5, boundary_confidence=0.9,
            visual_score=70, page_tag=PageTag.NON_VISUAL
        )
        self.assertFalse(SmartPaginator.is_video_frame(meta_non_vis))

        meta_keep = PageMetadata(
            page_index=2, y_start=100, y_end=700, height=600,
            page_type=PageType.VISUAL, content_score=0.8, boundary_confidence=0.9,
            visual_score=80, page_tag=PageTag.CHARACTER_ART
        )
        self.assertTrue(SmartPaginator.is_video_frame(meta_keep))

    def test_orphan_border_filter_top(self):
        """
        Tests that an orphan border sliver (e.g. 3px dark line from previous panel cut)
        at the top of a slice followed by a large white gutter (100px) is completely
        discarded, and y_top snaps cleanly to where the actual content begins.
        """
        slice_img = np.full((500, 400, 3), 255, dtype=np.uint8)
        # 1. Stray border from previous panel at row 0..2
        slice_img[0:3, :] = (20, 20, 20)
        # 2. White gutter at row 3..150
        # 3. True panel / content starts at row 150..450
        cv2.rectangle(slice_img, (30, 150), (370, 450), (60, 80, 120), -1)
        cv2.rectangle(slice_img, (30, 150), (370, 450), (0, 0, 0), 3)

        y_top, y_bottom = SmartPaginator.find_content_range(slice_img, pad=2, bg_val=255)
        # y_top must not start at 0! It must skip the stray border and start around row 148-150
        self.assertGreaterEqual(y_top, 140)
        self.assertLessEqual(y_top, 152)
        self.assertGreaterEqual(y_bottom, 448)

    def test_orphan_border_filter_bottom(self):
        """
        Tests that an orphan border sliver (3px dark line from next panel cut)
        at the bottom of a slice preceded by a large white gutter is completely
        discarded, and y_bottom snaps cleanly to the real content end.
        """
        slice_img = np.full((500, 400, 3), 255, dtype=np.uint8)
        # 1. Content at row 50..350
        cv2.rectangle(slice_img, (30, 50), (370, 350), (60, 80, 120), -1)
        cv2.rectangle(slice_img, (30, 50), (370, 350), (0, 0, 0), 3)
        # 2. White gutter at row 351..496
        # 3. Stray border at row 497..499
        slice_img[497:500, :] = (20, 20, 20)

        y_top, y_bottom = SmartPaginator.find_content_range(slice_img, pad=2, bg_val=255)
        self.assertLessEqual(y_top, 52)
        self.assertGreaterEqual(y_top, 45)
        # y_bottom must not be 500! It must skip the bottom stray border
        self.assertLessEqual(y_bottom, 360)
        self.assertGreaterEqual(y_bottom, 345)

    def test_webtoon_clean_preset_and_from_preset(self):
        """
        Tests PaginationConfig.webtoon_clean and from_preset factory methods.
        """
        cfg_wt = PaginationConfig.webtoon_clean()
        self.assertEqual(cfg_wt.ideal_page_height, 900)
        self.assertEqual(cfg_wt.max_page_height, 1280)
        self.assertTrue(cfg_wt.isolate_visual_frames)
        self.assertTrue(cfg_wt.tight_auto_crop)

        cfg_from_str = PaginationConfig.from_preset("webtoon")
        self.assertEqual(cfg_from_str.ideal_page_height, 900)
        self.assertEqual(cfg_from_str.max_page_height, 1280)

        cfg_tapas = PaginationConfig.from_preset("tapas")
        self.assertEqual(cfg_tapas.ideal_page_height, 950)
        self.assertEqual(cfg_tapas.max_page_height, 1280)

    def test_align_transcript_to_segments(self):
        from workflow_stages_2 import align_transcript_to_segments

        # 5 recap segments vs 8 raw whisper cues
        segments = [
            {"speech": "Khi trường học chìm trong biển lửa ngút trời, người thầy giáo trẻ Jio chỉ có một suy nghĩ duy nhất."},
            {"speech": "Thế nhưng khi mở mắt ra lần nữa, trước mặt anh là ánh nắng êm dịu."},
            {"speech": "Hóa ra anh đã rơi thẳng vào bức tranh phong cảnh do mình vẽ."},
            {"speech": "Nơi này đầy ắp những sinh vật kỳ lạ bước ra từ cổ tích."},
            {"speech": "Jio bắt đầu đúc kết quy tắc sinh tồn thú vị của thế giới này."}
        ]

        subtitles = [
            {"start": 0.0, "end": 2.5, "text": "Khi trường học chìm trong biển lửa"},
            {"start": 2.5, "end": 5.0, "text": "ngút trời người thầy giáo trẻ Jio chỉ có một suy nghĩ duy nhất"},
            {"start": 5.2, "end": 7.0, "text": "Thế nhưng khi mở mắt ra lần nữa"},
            {"start": 7.0, "end": 9.5, "text": "trước mặt anh là ánh nắng êm dịu"},
            {"start": 9.8, "end": 13.0, "text": "Hóa ra anh đã rơi thẳng vào bức tranh phong cảnh do mình vẽ"},
            {"start": 13.2, "end": 15.0, "text": "Nơi này đầy ắp những sinh vật kỳ lạ"},
            {"start": 15.0, "end": 17.5, "text": "bước ra từ cổ tích"},
            {"start": 17.8, "end": 22.0, "text": "Jio bắt đầu đúc kết quy tắc sinh tồn thú vị của thế giới này"}
        ]

        aligned = align_transcript_to_segments(subtitles, segments)
        self.assertEqual(len(aligned), len(segments))
        for i, item in enumerate(aligned):
            self.assertEqual(item["text"], segments[i]["speech"])
            self.assertLess(item["start"], item["end"])
            if i > 0:
                self.assertGreaterEqual(item["start"], aligned[i - 1]["end"])


if __name__ == "__main__":
    unittest.main()



