"""
Re-generate the SEO package of every finished folder in downloads/ with the same engine as Stage 12.

Per folder:
- youtube_upload_kit.txt + metadata.json (metadata_kit.regenerate_kit)
- seo_dashboard.json (structured copy of the kit, with the real pre-publish gate status)

Folders without rendered episode videos are skipped and reported.

Usage:
    python generate_all_seo_packages.py [--no-llm] [--registry PATH] [--downloads DIR]
"""
import argparse
import asyncio
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def write_seo_dashboard(output_dir: str, metadata: dict) -> str:
    yt_meta = metadata["youtube_metadata"]
    seo_dashboard = {
        "comic_title": metadata["comic_title"],
        "episodes_range": f"Ep {metadata['from_episode']}–{metadata['to_episode']}",
        "gate_status": yt_meta["prepublish_audit"].get("gate_status"),
        "primary_title": yt_meta.get("title"),
        "title_options": yt_meta.get("title_options", []),
        "tags_list": yt_meta.get("tags", []),
        "pinned_comment": yt_meta.get("pinned_comment"),
        "community_posts": yt_meta.get("community_posts", {}),
        "card_anchors_timestamps": yt_meta.get("card_anchors", {}),
        "seo_filenames": yt_meta.get("seo_filenames", {}),
        "thumbnail_concepts": yt_meta.get("thumbnail_concepts", []),
        "compliance_flags": yt_meta.get("compliance_flags", {}),
    }
    path = os.path.join(output_dir, "seo_dashboard.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seo_dashboard, f, ensure_ascii=False, indent=2)
    return path


async def run(downloads_root: str, use_llm: bool, registry_path: str | None) -> int:
    from metadata_kit import regenerate_kit

    results = {}
    for folder_name in sorted(os.listdir(downloads_root)):
        folder_path = os.path.join(downloads_root, folder_name)
        if not os.path.isdir(folder_path):
            continue
        print(f"\n>>> {folder_name}")
        try:
            metadata = await regenerate_kit(folder_path, use_llm=use_llm, registry_path=registry_path)
        except (ValueError, FileNotFoundError) as err:
            print(f"  [SKIPPED] {err}")
            results[folder_name] = "SKIPPED"
            continue
        print(f"  [SAVED] {write_seo_dashboard(os.path.join(folder_path, 'output'), metadata)}")
        results[folder_name] = metadata["youtube_metadata"]["prepublish_audit"].get("gate_status")

    print("\n" + "=" * 80)
    for folder_name, status in results.items():
        print(f"  {status:<8} {folder_name}")
    print("=" * 80)
    return 1 if "FAIL" in results.values() else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-llm", action="store_true", help="Template titles/chapters/overlays only (no 9Router calls)")
    parser.add_argument("--registry", help="Title registry JSON (default: channel_registry.json)")
    parser.add_argument("--downloads", default=os.path.join(PROJECT_ROOT, "downloads"), help="Downloads root folder")
    args = parser.parse_args()

    downloads_root = os.path.abspath(args.downloads)
    os.chdir(PROJECT_ROOT)
    sys.path.insert(0, PROJECT_ROOT)
    return asyncio.run(run(downloads_root, not args.no_llm, args.registry))


if __name__ == "__main__":
    sys.exit(main())
