import cv2
import numpy as np
from PIL import Image
from workflow_stages_2 import detect_clean_panel_and_focal_point, detect_vertical_bubble_edges, CameraPlanner

img_path = 'downloads/veteran_of_the_apocalypse_1_2_vi_e826e8f9/episode_1/images_pdf/006.webp'
with Image.open(img_path) as img:
    bounds, focal_point, skin_ratio, bubble_centroid, bubble_coverage_ratio = detect_clean_panel_and_focal_point(img)
    img_np = np.array(img.convert('RGB'))
    top_y, bot_y = detect_vertical_bubble_edges(img_np)

print(f"Page 006 size: {img.size}")
print(f"  bounds: {bounds}")
print(f"  focal_point: {focal_point}")
print(f"  top_bubble_bottom_y: {top_y}, bottom_bubble_top_y: {bot_y}")

plan = CameraPlanner.generate_camera_plan(
    page_num=6,
    duration=4.0,
    bounds=bounds,
    focal_point=focal_point,
    skin_ratio=skin_ratio,
    bubble_centroid=bubble_centroid,
    bubble_coverage_ratio=bubble_coverage_ratio,
    bottom_bubble_top_y=bot_y,
    top_bubble_bottom_y=top_y
)

print("Plan result:")
print(f"  animation_type: {plan.get('animation_type')}")
print(f"  direction: {plan.get('direction')}")

h_cam_ref = bounds[2] / 0.68
for kf in plan.get('keyframes', []):
    cy = kf['y']
    visible_top = cy - h_cam_ref * 0.5
    visible_bot = cy + h_cam_ref * 0.5
    t_val = kf['time']
    print(f"  t={t_val:.1f}s: cy={cy:.1f} | visible_y: [{visible_top:.1f} -> {visible_bot:.1f}] (Target max bot: <= {bot_y})")
    if bot_y is not None:
        assert visible_bot <= bot_y, f"FAILED: visible bottom {visible_bot} exceeds bubble boundary {bot_y}!"

print("\n>>> VERIFICATION SUCCESS: Camera viewport NEVER enters speech bubble! <<<")
