"""
Re-generate youtube_upload_kit.txt and metadata.json for one finished download folder with the same
engine as Stage 12 (LLM drafts, title registry, premise pitch, pre-publish gate).

Usage:
    python regenerate_youtube_kit.py <download_dir> [--no-llm] [--fresh] [--registry PATH] [--playlist-url URL]
"""
import argparse
import asyncio
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("download_dir", help="Folder with episode_*/video.mp4 (e.g. downloads/<comic>_1_3_en_<id>)")
    parser.add_argument("--no-llm", action="store_true", help="Template titles/chapters/overlays only (no 9Router calls)")
    parser.add_argument("--fresh", action="store_true", help="Draft chapter names/overlays anew instead of reusing metadata.json's")
    parser.add_argument("--registry", help="Title registry JSON (default: channel_registry.json)")
    parser.add_argument("--playlist-url", help="Real playlist URL to link in the description")
    args = parser.parse_args()

    download_dir = os.path.abspath(args.download_dir)
    if not os.path.isdir(download_dir):
        print(f"[ERROR] Not a folder: {download_dir}", file=sys.stderr)
        return 2

    os.chdir(PROJECT_ROOT)  # config/registry paths are relative to the project
    sys.path.insert(0, PROJECT_ROOT)
    from metadata_kit import regenerate_kit

    metadata = asyncio.run(regenerate_kit(
        download_dir, use_llm=not args.no_llm, registry_path=args.registry, playlist_url=args.playlist_url,
        fresh_drafts=args.fresh,
    ))
    return 0 if metadata["youtube_metadata"]["prepublish_audit"].get("gate_status") != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
