import os
import sys
import shutil
from PIL import Image, ImageFilter

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

def clean_crop_ep2_key_panels(img_dir: str):
    """
    Clean crop speech bubbles and text boxes from key panels in Episode 2.
    Backs up originals with _orig.webp in backup_orig.
    """
    crops = {
        4: (20, 215, 780, 735),     # P04 Girl looking at Jaehwan: cut top thief bubbles & bottom warning
        30: (0, 230, 800, 1399),    # P30 Tower Impact panic screen: cut top English box
        31: (0, 0, 800, 740),       # P31 Tower construction & workers: cut bottom bubble
        34: (0, 175, 800, 675),     # P34 Horned demon on ledge: cut top & bottom bubbles
        62: (0, 200, 800, 1100),    # P62 Glowing regression stone on floor: cut top & bottom bubbles completely
        64: (0, 120, 800, 1200),    # P64 Inchan holding stone: cut top & bottom bubbles
        71: (0, 0, 800, 720),       # P71 Sakamoto side profile: cut bottom timeline bubble
        73: (0, 35, 800, 997),      # P73 Earth splitting: cut top 35px black box remnant
        78: (0, 300, 800, 1460),    # P78 Cloaked warrior under starlight: cut top & bottom text boxes
        81: (0, 120, 800, 840),     # P81 Fingers holding crystal shard: cut bubbles
        94: (0, 170, 800, 880),     # P94 Comrades clutching stones in fear: cut bubbles
        96: (316, 920, 800, 1797),   # P96 Lone warrior against pillar: cut top bubbles AND 316px left black void
        107: (0, 0, 800, 1700),     # P107 Jaehwan walking into light: cut bottom bubble
    }

    rotations = {
        114: 90,                    # P114 Rotate 90 deg counter-clockwise to upright landscape
    }

    print(f"[CLEAN-CROP EP2] Bắt đầu cắt lọc bóng thoại trên {len(crops)} panel và xoay {len(rotations)} panel tại {img_dir}...")
    ep_dir = os.path.dirname(img_dir)
    backup_dir = os.path.join(ep_dir, "backup_orig")
    blur_dir = os.path.join(ep_dir, "images_blur")
    os.makedirs(backup_dir, exist_ok=True)

    # 1. Process crops
    for p, box in crops.items():
        fname = f"{p:03d}.webp"
        im_path = os.path.join(img_dir, fname)
        backup_path = os.path.join(backup_dir, f"{p:03d}_orig.webp")

        if not os.path.exists(im_path) and not os.path.exists(backup_path):
            print(f"[WARN] Không tìm thấy {im_path}")
            continue

        if not os.path.exists(backup_path):
            shutil.copy2(im_path, backup_path)
            source_path = backup_path
        else:
            source_path = backup_path

        with Image.open(source_path) as im:
            w, h = im.size
            x1, y1, x2, y2 = box
            x1 = max(0, min(w, x1))
            x2 = max(x1 + 10, min(w, x2))
            y1 = max(0, min(h, y1))
            y2 = max(y1 + 10, min(h, y2))

            cropped = im.crop((x1, y1, x2, y2))
            cropped.save(im_path, "WEBP", quality=95)

            if os.path.exists(blur_dir):
                blur_path = os.path.join(blur_dir, fname)
                bg = cropped.filter(ImageFilter.GaussianBlur(radius=25))
                bg.save(blur_path, "WEBP", quality=85)

            print(f"[CLEAN-CROP EP2] Panel P{p:02d}: {w}x{h} -> {cropped.size} (Đã làm sạch 100% bóng thoại)")

    # 2. Process rotations
    for p, angle in rotations.items():
        fname = f"{p:03d}.webp"
        im_path = os.path.join(img_dir, fname)
        backup_path = os.path.join(backup_dir, f"{p:03d}_orig.webp")

        if not os.path.exists(im_path) and not os.path.exists(backup_path):
            print(f"[WARN] Không tìm thấy {im_path}")
            continue

        if not os.path.exists(backup_path):
            shutil.copy2(im_path, backup_path)
            source_path = backup_path
        else:
            source_path = backup_path

        with Image.open(source_path) as im:
            rotated = im.rotate(angle, expand=True)
            rotated.save(im_path, "WEBP", quality=95)

            if os.path.exists(blur_dir):
                blur_path = os.path.join(blur_dir, fname)
                bg = rotated.filter(ImageFilter.GaussianBlur(radius=25))
                bg.save(blur_path, "WEBP", quality=85)

            print(f"[CLEAN-CROP EP2] Panel P{p:02d}: xoay {angle}° -> {rotated.size} (Upright orientation)")

    print(f"[CLEAN-CROP EP2] Hoàn tất xử lý mỹ thuật Episode 2 thành công!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        target_dir = r"downloads\the_world_after_the_fall_1_2_vi_be5d3841\episode_2\images_pdf"
    clean_crop_ep2_key_panels(target_dir)
