import asyncio
import json

import pytest

import metadata_kit
import title_engine
from series_bible import CharacterEntry, new_bible, save_bible

CORPUS = [
    "Martial law hits Seoul as the zombie outbreak spreads from a drifting trawler.",
    "Tae, a former taekwondo athlete, refuses to panic while the city collapses.",
    "He drags 300 cans of food into the abandoned church basement before the horde arrives.",
    "By winter only 40 survivors remain inside the church in Jamsil, rationing every can of food.",
]
HOOK = "Zombie Outbreak Hits, He Hoards 300 Cans Of Food!"
PITCH = {"title": HOOK + " | Manhwa Recap", "text": "The zombie outbreak hits Seoul.", "prepended": True}


def _folder(tmp_path, name="zombie_revelation_1_1_en_abc123"):
    root = tmp_path / name
    ep = root / "episode_1"
    ep.mkdir(parents=True)
    (ep / "recap.json").write_text(
        json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in CORPUS]), encoding="utf-8"
    )
    bible = new_bible("Zombie Revelation 82-08")
    bible.protagonist = CharacterEntry(name="Tae", gender="male")
    save_bible(bible, str(root))
    return root


_LOGS = []


async def _quiet_log(message, level="info"):
    _LOGS.append((level, message))


@pytest.fixture(autouse=True)
def _no_ffprobe(monkeypatch):
    _LOGS.clear()
    monkeypatch.setattr(
        metadata_kit, "chapters_from_episode_videos",
        lambda download_dir, from_ep, to_ep: [{"episode": 1, "timestamp": "00:00", "title": "Episode 1", "duration_seconds": 600.0}],
    )


def test_regenerate_writes_kit_and_keeps_recorded_pitch(tmp_path):
    root = _folder(tmp_path)
    (root / "output").mkdir()
    (root / "output" / "metadata.json").write_text(
        json.dumps({"comic_url": "https://example.com/c", "premise_pitch": PITCH}), encoding="utf-8"
    )
    metadata = asyncio.run(metadata_kit.regenerate_kit(
        str(root), use_llm=False, registry_path=str(tmp_path / "registry.json"), log=_quiet_log,
    ))

    assert metadata["comic_title"] == "Zombie Revelation 82-08"  # from the bible, not the folder name
    assert metadata["premise_pitch"] == PITCH and metadata["comic_url"] == "https://example.com/c"
    assert (root / "output" / "youtube_upload_kit.txt").read_text(encoding="utf-8")
    saved = json.loads((root / "output" / "metadata.json").read_text(encoding="utf-8"))
    assert saved["premise_pitch"] == PITCH
    # Without recorded drafts the kit keeps the title the rendered pitch promises.
    assert saved["llm_title_hooks"] == [HOOK]
    assert saved["youtube_metadata"]["title"] == PITCH["title"]
    assert saved["youtube_metadata"]["prepublish_audit"]["premise_pitch_in_video"] is True
    assert saved["youtube_metadata"]["prepublish_audit"]["gate_status"] in {"PASS", "WARN", "FAIL"}
    assert "VALIDATED_100_PERCENT_GROUNDED" not in json.dumps(saved)


def test_stage11_title_hooks_are_reused_and_log_splits_sources(tmp_path, monkeypatch):
    root = _folder(tmp_path)

    async def must_not_draft(*_args, **_kwargs):
        raise AssertionError("title hooks should come from Stage 11")

    monkeypatch.setattr(title_engine, "generate_llm_hooks", must_not_draft)
    prompts = []

    async def fake_llm(prompt):
        prompts.append(prompt)
        return ""

    artifacts = {"llm_title_hooks": [HOOK]}
    meta = asyncio.run(metadata_kit.generate_youtube_kit(
        download_dir=str(root), comic_title="Zombie Revelation 82-08", from_ep=1, to_ep=1,
        chapters=None, payload={"title_registry_path": str(tmp_path / "registry.json")},
        artifacts=artifacts, llm_call=fake_llm, log=_quiet_log,
    ))
    assert meta["title"].startswith(HOOK)
    assert prompts  # chapter / overlay drafts still go to the LLM
    engine_log = next(m for _lvl, m in _LOGS if m.startswith("Title Engine"))
    assert "title LLM đạt 1/1" in engine_log and "template đạt" in engine_log
    assert (tmp_path / "registry.json").exists()  # validated title recorded


def test_episode_range_and_title_fallbacks(tmp_path):
    root = tmp_path / "veteran_of_the_apocalypse_1_3_en_e826e8f9"
    for ep in (1, 2, 3):
        (root / f"episode_{ep}").mkdir(parents=True)
    assert metadata_kit.episode_range(str(root)) == (1, 3)
    assert metadata_kit.resolve_comic_title(str(root), None) == "Veteran Of The Apocalypse"
    assert metadata_kit.resolve_comic_title(str(root), {"comic_title": "Veteran of the Apocalypse"}) == "Veteran of the Apocalypse"
    assert metadata_kit.resolve_language(str(root), None) == "en"

    with pytest.raises(ValueError):
        metadata_kit.episode_range(str(tmp_path))
