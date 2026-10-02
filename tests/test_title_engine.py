import asyncio
import itertools
import json

from series_bible import CharacterEntry, new_bible, save_bible
from title_engine import (
    DUPLICATE_JACCARD,
    HookSheet,
    TitleRegistry,
    TitleValidator,
    build_hook_sheet,
    build_title_prompt,
    generate_llm_hooks,
    jaccard,
    parse_title_candidates,
    select_titles,
)
from youtube_metadata import generate_youtube_metadata

ZOMBIE_NARRATION = [
    "Martial law hits Seoul as the zombie outbreak spreads from a drifting trawler.",
    "Tae, a former national taekwondo athlete, refuses to panic while the city collapses.",
    "He drags 300 cans of food into the abandoned church basement before the horde arrives.",
    "The infected overrun the barricade in 3 days, and the soldiers retreat to the stadium.",
    "Mingu's mobsters try to steal the supplies, but Tae breaks the boss's jaw in one strike.",
    "By winter only 40 survivors remain inside the church, rationing every can of food.",
]


def _write_story(tmp_path, segments, comic="Zombie Revelation 82-08", mc="Tae"):
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir(parents=True, exist_ok=True)
    data = [{"speech": s, "images": [{"page": i + 1, "priority": 1.0}]} for i, s in enumerate(segments)]
    (ep_dir / "recap.json").write_text(json.dumps(data), encoding="utf-8")
    bible = new_bible(comic)
    bible.protagonist = CharacterEntry(name=mc, gender="male")
    bible.characters.append(CharacterEntry(name="Mingu", role="mob boss"))
    save_bible(bible, str(tmp_path))
    return str(tmp_path)


def _validator(tmp_path, registry=(), language="en"):
    download_dir = _write_story(tmp_path, ZOMBIE_NARRATION)
    from series_bible import load_bible
    sheet = build_hook_sheet("Zombie Revelation 82-08", download_dir, 1, 1, bible=load_bible(download_dir), language=language)
    return TitleValidator(sheet, registry_titles=registry)


# --- Hook sheet & prompt -----------------------------------------------------

def test_hook_sheet_collects_numbers_niche_and_names(tmp_path):
    download_dir = _write_story(tmp_path, ZOMBIE_NARRATION)
    from series_bible import load_bible
    sheet = build_hook_sheet("Zombie Revelation 82-08", download_dir, 1, 1, bible=load_bible(download_dir))
    phrases = [f.phrase for f in sheet.numeric_facts]
    assert "300 cans" in phrases and "40 survivors" in phrases
    assert sheet.sub_niches[0] == "zombie outbreak"
    assert sheet.character_names == ["Tae", "Mingu"]
    prompt = build_title_prompt(sheet)
    assert "300 cans" in prompt and "Max 60 characters" in prompt


def test_parse_title_candidates_handles_fences_numbering_and_suffix():
    raw = '```json\n["He Hoards 300 Cans While The Zombie Horde Waits | Manhwa Recap", "Second"]\n```'
    assert parse_title_candidates(raw) == ["He Hoards 300 Cans While The Zombie Horde Waits", "Second"]
    assert parse_title_candidates("1. First hook\n2) Second hook") == ["First hook", "Second hook"]


def test_no_llm_call_without_narration():
    async def must_not_be_called(_prompt):
        raise AssertionError("LLM must not run when there is nothing to ground on")

    assert asyncio.run(generate_llm_hooks(HookSheet(comic_title="X"), must_not_be_called)) == []


# --- Validator ---------------------------------------------------------------

def test_grounded_story_title_passes(tmp_path):
    check = _validator(tmp_path).check("Zombie Outbreak Hits, He Hoards 300 Cans Of Food!", "llm")
    assert check.passed, check.reasons
    assert check.title.endswith(" | Manhwa Recap")


def test_cross_genre_hype_is_rejected(tmp_path):
    hook = "WEAKEST Trainee Reveals SSS-Rank Power In Apocalypse"  # fits length: only grounding can reject it
    check = _validator(tmp_path).check(hook, "llm")
    assert not check.passed
    assert not any(r.startswith("hook_too_long") for r in check.reasons)
    assert any(r.startswith("low_grounding") for r in check.reasons)


def test_genre_promise_needs_verbatim_evidence_even_in_huge_corpus():
    """Prefixes from 'training'/'revealing' must not excuse 'Trainee'/'SSS' in a 13h narration."""
    corpus = ["Their training was brutal, revealing raw power in every recruit of high rank."] * 50
    sheet = HookSheet(comic_title="X", corpus=corpus)
    check = TitleValidator(sheet).check("Apocalypse: WEAKEST Trainee Reveals SSS Power", "llm")
    assert "claim_not_in_story:sss,trainee,weakest" in check.reasons


def test_long_hook_is_rejected_not_truncated(tmp_path):
    hook = "When The Zombie Outbreak Overruns The City, One Lone Survivor Fights Back"
    check = _validator(tmp_path).check(hook, "template")
    assert not check.passed
    assert any(r.startswith("hook_too_long") for r in check.reasons)
    assert check.hook == hook  # never cut to "One Lone!"


def test_ungrounded_number_is_rejected(tmp_path):
    check = _validator(tmp_path).check("Zombie Outbreak Hits, He Hoards 60,000 Tons Of Food!", "llm")
    assert any(r.startswith("ungrounded_numbers") for r in check.reasons)


def test_character_name_and_comic_title_are_rejected(tmp_path):
    validator = _validator(tmp_path)
    assert "contains_character_name" in validator.check("Zombie Outbreak: Tae Hoards 300 Cans Of Food", "llm").reasons
    assert "contains_comic_title" in validator.check("Zombie Revelation 82-08: He Hoards Food", "llm").reasons


def test_format_rules(tmp_path):
    validator = _validator(tmp_path)
    caps = validator.check("ZOMBIE OUTBREAK HITS AND HE HOARDS 300 Cans", "llm")
    assert any(r.startswith("too_many_caps_words") for r in caps.reasons)
    no_niche = validator.check("He Hoards 300 Cans Of Food Inside The Church Basement", "llm")
    assert "no_niche_keyword_early" in no_niche.reasons


def test_vietnamese_narration_skips_lexical_grounding(tmp_path):
    check = _validator(tmp_path, language="vi").check("Zombie Outbreak Hits, He Hoards 300 Cans Of Food!", "llm")
    assert check.grounded_ratio is None


# --- Duplicates & selection --------------------------------------------------

def test_published_title_blocks_near_duplicate(tmp_path):
    published = ["He Refused To Regress When Everyone Else Gave Up, Climbing The Tower Alone... | Manhwa Recap"]
    validator = _validator(tmp_path, registry=published)
    check = validator.check("He Refused To Regress When Everyone Else Gave Up", "template")
    assert any(r.startswith("duplicate_of_published") for r in check.reasons)


def test_three_comics_sharing_templates_get_distinct_titles():
    """Regression: three different tower stories once shipped the same title."""
    shared_templates = [
        "Tower Apocalypse: He Climbs Alone While Everyone Regresses",
        "Tower Apocalypse: Everyone Regresses, But He Keeps Climbing",
    ]
    story_hooks = {
        "Comic A": "Tower Apocalypse: He Clears 100 Floors Without Regressing",
        "Comic B": "Monsters Pour From The Tower, He Guards 12 Survivors",
        "Comic C": "Dungeon Apocalypse: He Trades 7 Lives For One Key",
    }
    registry = TitleRegistry(path="unused.json")
    chosen = []
    for comic, hook in story_hooks.items():
        corpus = [hook.lower(), " ".join(shared_templates).lower(), "floors survivors lives key"]
        sheet = HookSheet(comic_title=comic, corpus=corpus)
        validator = TitleValidator(sheet, registry_titles=registry.titles_for_dedup(comic))
        selection = select_titles([hook], shared_templates, validator)
        assert selection.status == "validated"
        chosen.append(selection.titles[0])
        registry.record_kit_title(selection.titles[0], comic, 1, 10)
    assert len(set(chosen)) == 3
    for a, b in itertools.combinations(chosen, 2):
        assert jaccard(a, b) < DUPLICATE_JACCARD


def test_variants_are_diverse(tmp_path):
    validator = _validator(tmp_path)
    selection = select_titles(
        [
            "Zombie Outbreak Hits, He Hoards 300 Cans Of Food!",
            "Zombie Outbreak Hits, He Hoards 300 Cans Of Food Fast",
            "Only 40 Survivors Remain As Zombie Horde Overruns Seoul",
            "Martial Law Falls, Zombie Horde Overruns The Barricade",
        ],
        [],
        validator,
    )
    variants = list(selection.variants.values())
    assert len(variants) == 3
    for a, b in itertools.combinations(variants, 2):
        assert jaccard(a, b) < DUPLICATE_JACCARD


# --- Registry ----------------------------------------------------------------

def test_registry_imports_studio_content_csv(tmp_path):
    csv_dir = tmp_path / "Content 2026-09-12_2026-10-01 Jaehwan Manhwa"
    csv_dir.mkdir()
    (csv_dir / "Table data.csv").write_text(
        "Content,Video title,Video publish time,Duration,Views\n"
        "Total,,,,5052\n"
        'R26qwMQVoos,When The WEAKEST Trainee Reveals His SSS-Rank Power And HUMILIATES Everyone | Manhwa Recap,"Sep 26, 2026",47032,3529\n'
        '1o9DxIZKzbc,"He Refused To Regress When Everyone Else Gave Up, Climbing The Tower Alone... | Manhwa Recap","Sep 19, 2026",15593,854\n',
        encoding="utf-8",
    )
    registry = TitleRegistry(path=str(tmp_path / "registry.json"))
    assert registry.import_studio_csv(str(csv_dir)) == 2
    assert registry.import_studio_csv(str(csv_dir)) == 0  # idempotent
    registry.save()
    reloaded = TitleRegistry.load(str(tmp_path / "registry.json"))
    assert len(reloaded.titles_for_dedup("Any Comic")) == 2


def test_own_kit_drafts_do_not_block_regeneration():
    registry = TitleRegistry(path="unused.json")
    registry.record_kit_title("Zombie Outbreak Hits, He Hoards 300 Cans | Manhwa Recap", "Zombie Revelation 82-08", 1, 143)
    assert registry.titles_for_dedup("Zombie Revelation 82-08") == []
    assert len(registry.titles_for_dedup("Another Comic")) == 1


# --- End-to-end through generate_youtube_metadata ----------------------------

def test_metadata_picks_grounded_llm_title_and_never_sss_for_zombie(tmp_path):
    download_dir = _write_story(tmp_path, ZOMBIE_NARRATION)
    meta = generate_youtube_metadata(
        "Zombie Revelation 82-08", 1, 1,
        download_dir=download_dir,
        llm_title_candidates=[
            "When The WEAKEST Trainee Reveals His SSS-Rank Power",
            "Zombie Outbreak Hits, He Hoards 300 Cans Of Food!",
            "Only 40 Survivors Remain As Zombie Horde Overruns Seoul",
        ],
    )
    all_titles = [meta["title"], *meta["title_options"], *meta["title_variants"].values()]
    assert meta["title"] == "Zombie Outbreak Hits, He Hoards 300 Cans Of Food! | Manhwa Recap"
    assert not any("SSS" in t or "Trainee" in t for t in all_titles)
    engine = meta["prepublish_audit"]["claim_audit"]["title_engine"]
    assert engine["status"] == "validated"
    assert engine["llm_candidates"] == 3
