import os
import json
import pytest
import subprocess
from app import find_ffmpeg
from workflow_stages_2 import (
    Stage12_MetadataReports,
    WorkflowContext,
)
from workflow_base import WorkflowTask


def test_ffmpeg_sidechain_ducking(tmp_path):
    ffmpeg_exe = find_ffmpeg()
    
    # 1. Create a 3-second dummy voice audio (440Hz sine wave, mono 24kHz)
    dummy_voice = tmp_path / "voice.mp3"
    cmd_voice = [
        ffmpeg_exe, "-y",
        "-f", "lavfi", "-i", "sine=f=440:d=3",
        "-c:a", "libmp3lame", "-ar", "24000", "-ac", "1",
        str(dummy_voice)
    ]
    res = subprocess.run(cmd_voice, capture_output=True)
    assert res.returncode == 0

    # 2. Path to real apocalypse BGM
    bgm_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "static", "bgm", "apocalypse", "01_dark_wasteland_ambient.mp3"
    )
    assert os.path.exists(bgm_path)

    # 3. Test exact sidechain ducking filter from Stage 8
    bgm_volume = 0.18
    out_audio = tmp_path / "ducked_mix.mp3"
    filter_complex_str = (
        f"[0:a]aformat=channel_layouts=stereo,aresample=44100,asplit=2[voice_main][voice_sidechain]; "
        f"[1:a]aformat=channel_layouts=stereo,aresample=44100,volume={bgm_volume}[bgm_raw]; "
        f"[bgm_raw][voice_sidechain]sidechaincompress=threshold=0.08:ratio=4:attack=100:release=600[ducked_bgm]; "
        f"[voice_main][ducked_bgm]amix=inputs=2:duration=first:dropout_transition=2,aformat=channel_layouts=stereo[aout]"
    )
    cmd_duck = [
        ffmpeg_exe, "-y",
        "-i", str(dummy_voice),
        "-stream_loop", "-1", "-i", bgm_path,
        "-filter_complex", filter_complex_str,
        "-map", "[aout]",
        "-c:a", "libmp3lame",
        "-ac", "2",
        "-ar", "44100",
        str(out_audio)
    ]
    duck_res = subprocess.run(cmd_duck, capture_output=True)
    assert duck_res.returncode == 0, f"FFmpeg failed: {duck_res.stderr.decode('utf-8', errors='ignore')}"
    assert out_audio.exists()
    assert out_audio.stat().st_size > 10000

    # 5. Verify audio stream with ffprobe
    cmd_probe = [
        ffmpeg_exe.replace("ffmpeg.exe", "ffprobe.exe") if "ffmpeg.exe" in ffmpeg_exe else "ffprobe",
        "-v", "error",
        "-show_entries", "stream=codec_type,channels,sample_rate",
        "-of", "json",
        str(out_audio)
    ]
    probe_res = subprocess.run(cmd_probe, capture_output=True, text=True)
    assert probe_res.returncode == 0
    probe_data = json.loads(probe_res.stdout)
    streams = probe_data.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    assert len(audio_streams) == 1
    assert audio_streams[0].get("channels") == 2
    assert audio_streams[0].get("sample_rate") == "44100"


@pytest.mark.asyncio
async def test_stage12_metadata_and_youtube_kit(tmp_path):
    download_dir = tmp_path / "comic_task"
    download_dir.mkdir()
    output_dir = download_dir / "output"
    output_dir.mkdir()

    chapters = [
        {"episode": 1, "timestamp": "00:00", "title": "Episode 1", "duration_seconds": 1800.0},
        {"episode": 2, "timestamp": "30:00", "title": "Episode 2", "duration_seconds": 2100.0},
    ]

    task = WorkflowTask(
        comic_title="The Apocalypse Needs A Pro",
        comic_url="https://vortexscans.org/series/the-apocalypse-needs-a-pro",
        from_episode=1,
        to_episode=2,
        payload={
            "market_id": "us_apocalypse",
            "enable_bgm": True,
        }
    )
    task.artifacts["download_dir"] = str(download_dir)
    task.artifacts["download_folder_name"] = "comic_task"
    task.artifacts["chapters"] = chapters

    class MockContext:
        def __init__(self, t):
            self.task = t
        async def log(self, msg, level="info"):
            pass
        async def update_stage_progress(self, name, pct):
            pass

    context = MockContext(task)
    stage = Stage12_MetadataReports()
    success = await stage.execute(context)
    assert success is True

    # Verify metadata.json
    meta_path = output_dir / "metadata.json"
    assert meta_path.exists()
    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["comic_title"] == "The Apocalypse Needs A Pro"
    assert "youtube_metadata" in data
    assert "The Apocalypse Needs A Pro" in data["youtube_metadata"]["title"]

    # Verify youtube_upload_kit.txt
    kit_path = output_dir / "youtube_upload_kit.txt"
    assert kit_path.exists()
    kit_text = kit_path.read_text(encoding="utf-8")
    assert "YOUTUBE UPLOAD KIT: The Apocalypse Needs A Pro" in kit_text
    assert "Market: us_apocalypse" in kit_text
    assert "[1. TITLE CANDIDATES" in kit_text
    assert "[2. DESCRIPTION & TIMESTAMPS" in kit_text
    assert "00:00 - Episode 1" in kit_text
    assert "30:00 - Episode 2" in kit_text
    assert "Copyright Disclaimer" in kit_text
    assert "[3. TAGS" in kit_text
    assert "apocalypse manhwa" in kit_text

    # Verify task artifacts
    assert task.artifacts.get("youtube_upload_kit_url") == "/downloads/comic_task/output/youtube_upload_kit.txt"
