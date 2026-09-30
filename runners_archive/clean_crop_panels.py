import os
import sys
import shutil
from PIL import Image, ImageFilter

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

def clean_crop_key_panels(img_dir: str):
    """
    Clean crop speech bubbles and text boxes from key panels to make them 100% pure artwork.
    Backs up originals with _orig.webp extension in backup_orig.
    """
    crops = {
        2: (0, 0, 800, 1580),     # P02 Tower: cut bottom text 'IT WAS THE END OF THE WORLD.'
        3: (0, 570, 800, 1341),   # P03 City screen: cut top black box 'SOME PEOPLE SAID...'
        8: (0, 0, 800, 1400),     # P08 Warriors march: cut bottom black pants, focus on weapons & hero
        16: (0, 170, 800, 1190),  # P16 Fellow holding stone: cut top bubble & bottom bubble
        20: (0, 0, 800, 1345),    # P20 Epic light & shadows: cut bottom 2 round bubbles
        21: (0, 210, 800, 1000),  # P21 Panic battle: cut top & bottom speech bubbles
        23: (0, 0, 800, 1300),    # P23 Sword graveyard: cut bottom white circular bubble
        26: (0, 160, 800, 764),   # P26 Jaehwan face: cut top 'LET'S GO, YUNHWAN!'
        27: (0, 130, 800, 1378),  # P27 Friend collapsed: cut top 'YUNHWAN...?'
        30: (0, 180, 800, 1170),  # P30 Dying friend smile: cut top 'I'M SORRY' and bottom 'JAEHWAN...'
        34: (0, 0, 800, 470),     # P34 Jaehwan face fl99: cut bottom-right white speech arc
        35: (0, 340, 800, 1942),  # P35 Ice dragon: cut top 340px massive black bubble
        36: (0, 90, 800, 829),    # P36 Sword hilt grip: cut top 'TO THE PAST.'
        38: (0, 160, 800, 1234),  # P38 Shadow entity watching screens: cut top 'HMM...'
        40: (0, 0, 800, 1320),    # P40 Demon smiling teeth: cut bottom speech bubble
    }

    print(f"[CLEAN-CROP] Bắt đầu cắt lọc bóng thoại trên {len(crops)} panel trọng điểm tại {img_dir}...")
    ep_dir = os.path.dirname(img_dir)
    backup_dir = os.path.join(ep_dir, "backup_orig")
    blur_dir = os.path.join(ep_dir, "images_blur")
    os.makedirs(backup_dir, exist_ok=True)

    for p, box in crops.items():
        fname = f"{p:03d}.webp"
        im_path = os.path.join(img_dir, fname)
        backup_path = os.path.join(backup_dir, f"{p:03d}_orig.webp")
        
        if not os.path.exists(im_path) and not os.path.exists(backup_path):
            print(f"[WARN] Không tìm thấy {im_path}")
            continue

        # Backup if not already backed up
        if not os.path.exists(backup_path):
            shutil.copy2(im_path, backup_path)
            source_path = backup_path
        else:
            source_path = backup_path

        with Image.open(source_path) as im:
            w, h = im.size
            x1, y1, x2, y2 = box
            # Ensure box bounds within original image
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

            print(f"[CLEAN-CROP] Panel P{p:02d}: {w}x{h} -> {cropped.size} (Đã làm sạch 100% bóng thoại)")

    print(f"[CLEAN-CROP] Hoàn tất cắt lọc bóng thoại {len(crops)} panel thành công!")

if __name__ == "__main__":
    img_dir = r"downloads\the_world_after_the_fall_1_1_vi_be5d3841\episode_1\images_pdf"
    clean_crop_key_panels(img_dir)
