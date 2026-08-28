from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from tts_settings import get_ai33pro_voice_id, uses_ai33pro


CACHE_VERSION = 3
MANIFEST_NAME = "artifact_manifest.json"
STAGE_ORDER = (
    "image_crawl",
    "repagination",
    "pdf",
    "gemini_safe_pdf",
    "gemini",
    "json_extract",
    "narration",
    "tts",
    "subtitles",
    "selected_moderation",
    "video",
)
STAGE_CONFIG_KEYS = {
    "image_crawl": ("image_quality", "concurrency", "comix_group_id"),
    "repagination": ("image_quality",),
    "pdf": ("pdf_quality", "language"),
    "gemini_safe_pdf": ("safe_mode", "nsfw_threshold", "nsfw_mode", "pdf_quality"),
    "gemini": ("vlm_provider", "language"),
    "json_extract": ("language",),
    "narration": ("language",),
    "tts": ("voice_id", "ref_audio_path", "language"),
    "subtitles": ("language",),
    "selected_moderation": ("safe_mode", "nsfw_threshold", "nsfw_mode"),
    "video": ("logo_path", "overlay_path", "remove_text", "remove_text_conf", "remove_text_radius", "burn_subtitles", "fps"),
}
STAGE_OUTPUT_PATHS = {
    "image_crawl": ("images",),
    "repagination": ("images_pdf", "debug_repaging"),
    "pdf": ("pdf",),
    "gemini_safe_pdf": ("gemini_safe",),
    "gemini": ("raw_gemini_response.txt", "recap.json"),
    "json_extract": (),
    "narration": ("narration.txt",),
    "tts": ("audio.mp3", "transcript.srt", "tts_config.json"),
    "subtitles": (),
    "selected_moderation": ("images_blur",),
    "video": ("video.mp4", "content_bounds_cache.json", "ffmpeg_render_stderr.log"),
}


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StageFingerprint(str):
    def __new__(cls, value: str, metadata: dict[str, Any]):
        instance = super().__new__(cls, value)
        instance.metadata = metadata
        return instance


def source_hash(url: str, length: int = 8) -> str:
    return stable_hash(url.strip())[0:length]


def path_signature(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return None
    if resolved.is_file():
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        stat = resolved.stat()
        return {"type": "file", "size": stat.st_size, "sha256": digest.hexdigest()}

    entries: list[tuple[str, int, str]] = []
    for item in sorted((entry for entry in resolved.rglob("*") if entry.is_file()), key=lambda entry: str(entry).casefold()):
        signature = path_signature(item)
        if signature is None:
            continue
        entries.append((item.relative_to(resolved).as_posix(), signature["size"], signature["sha256"]))
    return {"type": "directory", "sha256": stable_hash(entries), "file_count": len(entries)}


def validate_nonempty_file(path: str | Path) -> bool:
    value = Path(path)
    return value.is_file() and value.stat().st_size > 0


def validate_pdf_file(path: str | Path) -> bool:
    if not validate_nonempty_file(path):
        return False
    try:
        with Path(path).open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def validate_mp4_file(path: str | Path) -> bool:
    if not validate_nonempty_file(path):
        return False
    value = Path(path)
    try:
        size = value.stat().st_size
        with value.open("rb") as handle:
            head = handle.read(min(size, 1024 * 1024))
            if b"ftyp" not in head:
                return False
            if b"moov" in head:
                return True
            if size > 1024 * 1024:
                handle.seek(max(0, size - 1024 * 1024))
                return b"moov" in handle.read(1024 * 1024)
    except OSError:
        return False
    return False


def validate_srt_file(path: str | Path) -> bool:
    if not validate_nonempty_file(path):
        return False
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return bool(re.search(
        r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}",
        content,
    ))


def stage_fingerprint(
    task: Any,
    stage: str,
    episode: int,
    input_paths: Iterable[str | Path | None] = (),
    extra: Any = None,
) -> str:
    config = {key: task.payload.get(key) for key in STAGE_CONFIG_KEYS[stage]}
    if stage == "tts" and uses_ai33pro(config.get("voice_id")):
        config["voice_id"] = "ai33pro"
        config["ai33pro_voice_id_hash"] = stable_hash(get_ai33pro_voice_id())
    input_signatures = [path_signature(path) for path in input_paths]
    descriptor = {
        "cache_version": CACHE_VERSION,
        "stage": stage,
        "source_url": task.comic_url.strip(),
        "episode": episode,
        "language": task.payload.get("language", "vi"),
        "config": config,
        "inputs": input_signatures,
        "extra": extra,
    }
    manifest_config = {
        key: path_signature(value) if key.endswith("_path") and value else value
        for key, value in config.items()
    }
    metadata = {
        "source_identity": {
            "source_hash": source_hash(task.comic_url, length=16),
            "episode": episode,
        },
        "config": manifest_config,
        "input_fingerprint": stable_hash({"inputs": input_signatures, "extra": extra}),
    }
    return StageFingerprint(stable_hash(descriptor), metadata)


def clear_stage_and_downstream(episode_dir: str | Path, stage: str) -> None:
    root = Path(episode_dir).resolve()
    start = STAGE_ORDER.index(stage)
    seen: set[Path] = set()
    for stage_name in STAGE_ORDER[start:]:
        for relative in STAGE_OUTPUT_PATHS[stage_name]:
            target = (root / relative).resolve()
            if target in seen:
                continue
            seen.add(target)
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError("cache output escapes episode directory") from exc
            try:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists():
                    target.unlink()
            except OSError:
                pass


class EpisodeStageCache:
    def __init__(self, episode_dir: str | Path):
        self.episode_dir = Path(episode_dir)
        self.manifest_path = self.episode_dir / MANIFEST_NAME
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            return {"cache_version": CACHE_VERSION, "stages": {}}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {"cache_version": CACHE_VERSION, "stages": {}}
        if data.get("cache_version") != CACHE_VERSION or not isinstance(data.get("stages"), dict):
            return {"cache_version": CACHE_VERSION, "stages": {}}
        return data

    def _save(self) -> None:
        self.episode_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.manifest_path.with_name(f"{self.manifest_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            for attempt in range(10):
                try:
                    os.replace(temp_path, self.manifest_path)
                    return
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _output_signatures(self, outputs: Iterable[str | Path]) -> dict[str, Any]:
        root = self.episode_dir.resolve()
        signatures: dict[str, Any] = {}
        for path in outputs:
            resolved = Path(path).resolve()
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError("cache output escapes episode directory") from exc
            signatures[relative] = path_signature(resolved)
        return signatures

    def invalidate_from(self, stage: str) -> None:
        start = STAGE_ORDER.index(stage)
        changed = False
        for key in STAGE_ORDER[start:]:
            changed = self.data["stages"].pop(key, None) is not None or changed
        if changed:
            self._save()

    def is_current(
        self,
        *,
        stage: str,
        fingerprint: str,
        outputs: Iterable[str | Path],
        validate: Callable[[], bool] | None = None,
    ) -> bool:
        entry = self.data["stages"].get(stage)
        if not entry or entry.get("fingerprint") != str(fingerprint):
            self.invalidate_from(stage)
            clear_stage_and_downstream(self.episode_dir, stage)
            return False
        current = self._output_signatures(outputs)
        if current != entry.get("outputs") or any(signature is None for signature in current.values()):
            self.invalidate_from(stage)
            clear_stage_and_downstream(self.episode_dir, stage)
            return False
        if validate is not None and not validate():
            self.invalidate_from(stage)
            clear_stage_and_downstream(self.episode_dir, stage)
            return False
        return True

    def commit(self, *, stage: str, fingerprint: str, outputs: Iterable[str | Path]) -> None:
        signatures = self._output_signatures(outputs)
        if any(signature is None for signature in signatures.values()):
            raise FileNotFoundError(f"cannot cache missing output for stage {stage}")
        self.invalidate_from(stage)
        entry = {"fingerprint": str(fingerprint), "outputs": signatures}
        metadata = getattr(fingerprint, "metadata", None)
        if metadata:
            entry.update(metadata)
        self.data["stages"][stage] = entry
        self._save()
