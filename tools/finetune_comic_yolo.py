# -*- coding: utf-8 -*-
"""
Comic & Manhwa YOLO Fine-Tuning Utility.
Fine-tunes YOLOv11 on comic panel, speech bubble, and character datasets
(such as Manga109, Roboflow Comic Panels, or custom user-annotated webtoons).

Optimized for NVIDIA GeForce RTX 4070 SUPER (12GB VRAM).

Usage:
  python tools/finetune_comic_yolo.py --dataset path/to/dataset.yaml --epochs 50
  python tools/finetune_comic_yolo.py --create-template
"""

import os
import sys
import argparse
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger("FineTuneComicYOLO")


def check_cuda_environment() -> Dict[str, Any]:
    """Inspects CUDA GPU availability and memory."""
    env = {
        "cuda_available": False,
        "device_name": "CPU",
        "vram_total_gb": 0.0,
        "recommended_device": "cpu",
        "recommended_batch": 4
    }
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            env["cuda_available"] = True
            env["device_name"] = device_name
            env["vram_total_gb"] = round(vram, 2)
            env["recommended_device"] = "cuda:0"
            # 12GB VRAM (e.g. RTX 4070 SUPER) comfortably handles batch 16 at 640px
            if vram >= 10.0:
                env["recommended_batch"] = 16
            elif vram >= 6.0:
                env["recommended_batch"] = 8
            else:
                env["recommended_batch"] = 4
    except Exception as e:
        logger.warning(f"CUDA check encountered warning: {e}")
    return env


def create_dataset_template(target_path: str = "dataset_comic_sample.yaml") -> str:
    """Generates a starter dataset.yaml file for comic panels and text bubbles."""
    template = """# Comic & Manhwa Object Detection Dataset Configuration
# Classes correspond to ComicVisionAI and Manga109 standards:
# 0: body       (Character body / figure)
# 1: face       (Character face)
# 2: frame      (Comic / Manhwa panel border)
# 3: text       (Speech bubble / Dialogue / Narration)

path: ./data/comic_dataset  # dataset root directory
train: images/train         # train images (relative to 'path')
val: images/val             # val images (relative to 'path')
test: images/test           # test images (optional)

names:
  0: body
  1: face
  2: frame
  3: text
"""
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(template)
    logger.info(f"Sample dataset configuration created at: {target_path}")
    return target_path


def train_comic_model(
    dataset_yaml: str,
    base_model: str = "weights/manga109_yolo11m.pt",
    epochs: int = 50,
    batch_size: Optional[int] = None,
    img_size: int = 640,
    device: Optional[str] = None,
    output_dir: str = "runs/train_comic",
    export_path: str = "weights/comic_yolo_custom.pt"
) -> Optional[str]:
    """
    Executes fine-tuning of YOLOv11 on comic panel / speech bubble dataset.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.error("ultralytics is not installed. Please run: pip install ultralytics")
        return None

    if not os.path.exists(dataset_yaml):
        logger.error(f"Dataset config file '{dataset_yaml}' not found.")
        return None

    env = check_cuda_environment()
    target_device = device or env["recommended_device"]
    target_batch = batch_size or env["recommended_batch"]

    logger.info("=" * 60)
    logger.info("Starting Comic/Manhwa YOLO Fine-Tuning")
    logger.info(f"Device: {target_device} ({env['device_name']} | {env['vram_total_gb']} GB VRAM)")
    logger.info(f"Base Model: {base_model}")
    logger.info(f"Dataset Config: {dataset_yaml}")
    logger.info(f"Epochs: {epochs} | Batch: {target_batch} | Image Size: {img_size}")
    logger.info("=" * 60)

    # Resolve base model path: fallback to yolo11m.pt if specified path doesn't exist
    if not os.path.exists(base_model):
        alt_model = "yolo11m.pt"
        logger.warning(f"Base model '{base_model}' not found, falling back to '{alt_model}'")
        base_model = alt_model

    model = YOLO(base_model)

    # Train model
    results = model.train(
        data=dataset_yaml,
        epochs=epochs,
        batch=target_batch,
        imgsz=img_size,
        device=target_device,
        project=output_dir,
        name="finetune",
        save=True,
        exist_ok=True,
        patience=15,
        workers=4,
        verbose=True
    )

    # Locate best weights
    best_pt = os.path.join(output_dir, "finetune", "weights", "best.pt")
    if not os.path.exists(best_pt):
        best_pt = os.path.join(output_dir, "finetune", "weights", "last.pt")

    if os.path.exists(best_pt):
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        shutil.copy2(best_pt, export_path)
        logger.info(f"Successfully trained and saved model to: {export_path}")

        # Quick validation
        val_model = YOLO(export_path)
        logger.info(f"Validated exported model classes: {val_model.names}")
        return export_path
    else:
        logger.error(f"Training completed but weights file not found at {best_pt}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune YOLOv11 for Comic Panel & Speech Bubble Detection"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="",
        help="Path to dataset YAML file (e.g. dataset.yaml)"
    )
    parser.add_argument(
        "--base-model",
        type=str,
        default="weights/manga109_yolo11m.pt",
        help="Base model checkpoint to fine-tune from"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
        help="Number of training epochs (default: 50)"
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=None,
        help="Batch size (default: auto-detected based on GPU VRAM, 16 for RTX 4070 SUPER)"
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Input image resolution (default: 640)"
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Device to train on ('cuda:0' or 'cpu')"
    )
    parser.add_argument(
        "--export",
        type=str,
        default="weights/comic_yolo_custom.pt",
        help="Target path for exporting the best trained weights"
    )
    parser.add_argument(
        "--create-template",
        action="store_true",
        help="Create a sample dataset.yaml template and exit"
    )

    args = parser.parse_args()

    if args.create_template:
        create_dataset_template()
        return

    if not args.dataset:
        logger.info("No dataset specified. Displaying system capabilities:")
        env = check_cuda_environment()
        print(f"CUDA Available: {env['cuda_available']}")
        print(f"GPU: {env['device_name']}")
        print(f"VRAM: {env['vram_total_gb']} GB")
        print(f"Recommended Batch: {env['recommended_batch']}")
        print("\nTo generate a template dataset.yaml, run:")
        print("  python tools/finetune_comic_yolo.py --create-template")
        print("\nTo start training with an existing dataset:")
        print("  python tools/finetune_comic_yolo.py --dataset data/comic_data.yaml --epochs 50")
        return

    train_comic_model(
        dataset_yaml=args.dataset,
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch,
        img_size=args.imgsz,
        device=args.device,
        export_path=args.export
    )


if __name__ == "__main__":
    main()
