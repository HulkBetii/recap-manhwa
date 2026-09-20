import pytest
from recap_schema import auto_split_long_segments, enforce_monotonic_page_order
from workflow_stages_2 import CameraPlanner

def test_auto_split_long_segments_on_conjunction():
    segments = [{
        'speech': 'When the toxic spores contaminated the atmosphere and turned humanity into flesh-eating beasts, Paran sealed his impenetrable bunker and watched the entire city tear itself apart.',
        'images': [{'page': 5, 'priority': 0.75}, {'page': 6, 'priority': 0.25}]
    }]
    split_segs = auto_split_long_segments(segments, max_words=20)
    assert len(split_segs) == 2
    assert len(split_segs[0]['speech'].split()) <= 20
    assert len(split_segs[1]['speech'].split()) <= 20
    assert split_segs[0]['images'][0]['page'] == 5
    assert split_segs[1]['images'][0]['page'] == 6

def test_auto_split_long_segments_on_em_dash():
    segments = [{
        'speech': 'He stared straight into the abyssal darkness without flinching ‐ daring whatever lurked inside the shadows to make the first move against his fortified gates.',
        'images': [{'page': 10, 'priority': 1.0}]
    }]
    split_segs = auto_split_long_segments(segments, max_words=20)
    assert len(split_segs) == 2
    assert len(split_segs[0]['speech'].split()) <= 20
    assert len(split_segs[1]['speech'].split()) <= 20

def test_enforce_monotonic_page_order():
    segments = [
        {'speech': 'First scene.', 'images': [{'page': 5, 'priority': 1.0}]},
        {'speech': 'Second scene.', 'images': [{'page': 12, 'priority': 1.0}]},
        {'speech': 'Accidental backward jump.', 'images': [{'page': 7, 'priority': 1.0}]},
        {'speech': 'Fourth scene.', 'images': [{'page': 18, 'priority': 1.0}]}
    ]
    monotonic = enforce_monotonic_page_order(segments)
    pages = [s['images'][0]['page'] for s in monotonic]
    assert pages == [5, 12, 12, 18]

def test_camera_planner_face_aware_headroom_protection():
    # Tall panel (800x1600) with face right at the top (y=20 on height=1600, face_y_ratio = 0.0125)
    bounds = (0, 0, 800, 1600)
    plan = CameraPlanner.generate_camera_plan(
        page_num=10,
        duration=4.0,
        bounds=bounds,
        focal_point=(400.0, 20.0),
        shot_index=0
    )
    assert plan['animation_type'] == 'vertical_pan_glide'
    h_cam_ref = 800.0 / 0.68
    kfs = plan['keyframes']
    upper_y = min(kfs[0]['y'], kfs[1]['y'])
    assert abs(upper_y - (h_cam_ref * 0.5)) < 1.0

def test_camera_planner_auto_upgrade_ultra_tall_panels():
    bounds = (0, 0, 800, 1895)
    plan = CameraPlanner.generate_camera_plan(
        page_num=35,
        duration=4.5,
        bounds=bounds,
        focal_point=None,
        shot_index=0
    )
    assert plan['animation_type'] == 'vertical_pan_glide'


def test_create_numbered_pdf_forbidden_cover_page_detection(tmp_path):
    import cv2
    import numpy as np
    from PIL import Image
    from moderation_utils import create_numbered_pdf
    from visual_scorer import VisualSemanticScorer

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    pdf_out = tmp_path / "test_ep1.pdf"

    # Page 1: Empty title banner (mostly white with chapter title text)
    cover_page = np.ones((800, 720, 3), dtype=np.uint8) * 245
    cv2.putText(cover_page, "CHAPTER 1: SURVIVAL", (50, 400), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2)
    cv2.imwrite(str(images_dir / "001.jpg"), cover_page)

    # Page 2: Rich story panel with character face and dynamic scene
    story_page = np.zeros((800, 720, 3), dtype=np.uint8)
    for y in range(800):
        story_page[y, :] = [(y * 80 // 800) + 30, (y * 120 // 800) + 40, (y * 160 // 800) + 50]
    for i in range(80):
        cv2.circle(story_page, (int((i * 43) % 720), int((i * 61) % 800)), int(15 + (i % 20)), (int(i*5 % 255), int(i*7 % 255), int(i*9 % 255)), -1)
    for i in range(25):
        cv2.line(story_page, (0, i * 32), (720, 800 - i * 32), (200, 200, 200), 2)
    cv2.circle(story_page, (180, 250), 50, (220, 180, 100), -1)  # Character face
    cv2.putText(story_page, "Hero Counter Attack", (50, 450), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    cv2.imwrite(str(images_dir / "002.jpg"), story_page)

    # Verify VisualSemanticScorer detects cover_page as meaningless / low score
    score1, breakdown1 = VisualSemanticScorer.calculate_score(cover_page)
    score2, breakdown2 = VisualSemanticScorer.calculate_score(story_page)
    assert breakdown1['is_meaningless'] is True
    assert score1 <= 25
    assert breakdown2['is_meaningless'] is False
    assert score2 >= 50

    # Run create_numbered_pdf
    create_numbered_pdf(images_dir, pdf_out, quality=80)
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 0

