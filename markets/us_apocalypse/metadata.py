from __future__ import annotations

import os
import re
import json
import glob
from typing import Dict, Any, List, Optional


def detect_archetype(comic_title: str, story_memory: Optional[Dict[str, Any]] = None) -> str:
    """
    Detects the specific manhwa archetype/subgenre to generate tailored, high-CTR titles and synopses.
    """
    title_lower = (comic_title or "").lower()
    mem_text = ""
    if story_memory:
        mem_text = str(story_memory).lower()

    combined = f"{title_lower} {mem_text}"

    if any(k in combined for k in ["zombie", "infected", "undead", "ghoul", "plague", "virus", "outbreak", "82-08", "8208", "walking dead"]):
        return "zombie_apocalypse"
    elif any(k in combined for k in ["world after the fall", "tower", "floor", "chaos", "return stone", "regress", "nightmare", "thrust"]):
        return "tower_anti_regression"
    elif any(k in combined for k in ["bunker", "shelter", "shut-in", "shutin", "warehouse", "hoard", "freeze", "freezing", "ice age", "supplies", "vault", "doomsday prepper"]):
        return "bunker_prepper"
    elif any(k in combined for k in ["hunter", "gate", "dungeon", "awakening", "rank", "necromancer", "shadow", "monarch", "s-rank", "calamity"]):
        return "hunter_gate"
    elif any(k in combined for k in ["murim", "martial", "cultivation", "sword", "heavenly", "demon", "sect", "dantian", "qi"]):
        return "murim_apocalypse"
    elif any(k in combined for k in ["revenge", "betray", "betrayed", "executed", "reborn", "regressor", "returnee", "vengeance"]):
        return "reincarnation_revenge"
    elif any(k in combined for k in ["space", "inventory", "infinite storage", "supermarket", "grocery"]):
        return "infinite_space_hoard"
    return "general_apocalypse"


def get_character_names(comic_title: str, story_memory: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Resolves protagonist and key supporting character names dynamically from story memory or smart archetype fallbacks.
    """
    title_lower = (comic_title or "").lower()
    mc_name = ""
    female_lead = ""

    if story_memory:
        raw_mc = story_memory.get("protagonist_name", "").strip()
        if raw_mc and len(raw_mc) > 1 and raw_mc.lower() not in ["a", "protagonist", "mc", "unknown", "hero", "the hero"]:
            mc_name = raw_mc
        raw_fl = story_memory.get("female_lead", "") or story_memory.get("companion_name", "")
        if raw_fl and len(raw_fl) > 1 and raw_fl.lower() not in ["a", "companion", "female", "unknown"]:
            female_lead = raw_fl

    if not mc_name:
        if "world after the fall" in title_lower:
            mc_name = "Jaehwan"
        elif "omniscient reader" in title_lower:
            mc_name = "Kim Dokja"
        elif "solo leveling" in title_lower:
            mc_name = "Sung Jinwoo"
        elif "doom breaker" in title_lower or "reincarnation of the suicidal" in title_lower:
            mc_name = "Zephyr"
        elif "veteran" in title_lower:
            mc_name = "The Veteran Survivor"
        elif any(k in title_lower for k in ["zombie", "82-08", "8208"]):
            mc_name = "South"
        elif any(k in title_lower for k in ["shut-in", "shutin", "bunker", "shelter"]):
            mc_name = "The Ultimate Bunker Sovereign"
        else:
            mc_name = "The Lone Sovereign"

    if not female_lead:
        if "world after the fall" in title_lower:
            female_lead = "Mino / Sirwen Armelt"
        elif "global freeze" in title_lower or "shelter" in title_lower or "shut-in" in title_lower:
            female_lead = "Yu Qing / Zhou Keer"
        elif any(k in title_lower for k in ["zombie", "82-08", "8208"]):
            female_lead = "The Fearless Survivor"
        else:
            female_lead = "The Alluring Female Lead"

    return {
        "mc": mc_name,
        "female_lead": female_lead
    }


def extract_episode_theme(recap_path: str, ep: int, comic_title: str = "") -> str:
    """
    Extracts a punchy, dramatic narrative theme for an episode from its recap.json.
    """
    if not os.path.isfile(recap_path):
        return f"Chapter {ep}"
    try:
        with open(recap_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return f"Chapter {ep}"

    if not data or not isinstance(data, list):
        return f"Chapter {ep}"

    full_speech = " ".join([item.get("speech", "") for item in data[:3]])
    if not full_speech:
        return f"Chapter {ep}"

    kw_rules = [
        (["prologue", "boat", "ship", "ocean", "sea"], "The Outbreak & Boat 82-08 Incident"),
        (["martial law", "broadcast", "chopper", "helicopter"], "Martial Law & First Encounters"),
        (["syndicate", "enforcer", "gang", "thug"], "Syndicate Enforcers & Urban Collapse"),
        (["subway", "station", "platform", "tracks"], "Subway Descent & Platform Bloodbath"),
        (["garrison", "military", "conscript", "magazine"], "Garrison Deployment & Midnight Horde"),
        (["church", "stairwell", "door", "locked", "coward"], "The Church Stairwell Betrayal"),
        (["starvation", "water", "supply", "supplies", "food"], "Starvation Threat & Scavenge Run"),
        (["atomic", "nuclear", "research", "perimeter"], "Atomic Research Station in the Deluge"),
        (["turret", "heavy caliber", "abandon"], "Heavy Turret Stand & High Ground Retreat"),
        (["monstrosity", "awakened", "quarantine", "lab", "biolab"], "Quarantine Breach & Mutant Lab Collapse"),
        (["wire", "bridge", "mesh", "vault", "flapping"], "High-Altitude Wire Bridge Horror"),
        (["airport", "tarmac", "crate", "transport"], "Airport Tarmac & Black Market Escape"),
        (["marine", "coastline", "scorched", "mop-up"], "Coastline Mop-Up & Deceptive Silence"),
        (["trap", "disappearing", "quiet", "trace"], "The Disappearing Horde & Springing the Trap"),
        (["mutiny", "major", "brass", "kick"], "Fractured Command & Mutiny Against the Brass"),
        (["season 2", "reset", "haze", "headlights"], "Season 2 Begins: Dark Horizon & New Strains"),
        (["winter", "freeze", "cold", "rain", "tempest"], "Winter Onslaught & Freezing Ambush"),
        (["doctor", "surgery", "morphine", "medic"], "Field Surgery & Cost of Infection"),
        (["wiped out", "twenty minutes", "ultimatum"], "Shattered Evac Point: The 20-Minute Ultimatum"),
        (["barricade", "sealed", "artery", "arteries"], "Barricaded Arteries & Labyrinth of Ruin"),
        (["containment", "order", "secret"], "The Secret Containment Order Exposed"),
        (["chassis", "canister", "axle", "convoy"], "Convoy Ambush & The Canister Race"),
        (["vanguard", "blade", "slice"], "Iron Vanguard: Clashing with Fast Strains"),
        (["tunnel", "rescue", "cowering"], "Subway Slaughter & Rescuing Survivors"),
        (["orchestrated", "truth", "extermination"], "The Orchestrated Plague & True Origin"),
        (["fortress", "resistance", "level head"], "Fortress Road & Armed Resistance"),
        (["citadel", "inner ring", "breach"], "Citadel Breach: Inner Ring Infiltration"),
        (["final stand", "tempest", "fence", "storm"], "Midnight Tempest: Final Perimeter Defense"),
        (["dawn", "ruins", "reckoning"], "Grand Finale: Dawn Over the Ruins"),
        (["tower", "floor", "nightmare", "climb"], "The Tower Trials & Endless Ascent"),
        (["bunker", "shelter", "subterranean"], "Bunker Fortification & Survival Prep"),
        (["dungeon", "gate", "awakening"], "Calamity Gate & Solo Awakening"),
    ]

    lower_speech = full_speech.lower()
    for keywords, theme in kw_rules:
        if any(kw in lower_speech for kw in keywords):
            return theme

    first_sent = re.split(r"[.!?]", full_speech)[0].strip()
    first_sent = re.sub(r"^(while|as|spotting|even with|with|after)\s+[^,]+,\s*", "", first_sent, flags=re.IGNORECASE)
    first_sent = re.sub(r"^(south|he|they|she|the hero|the survivor)\s+(watches|scrambles|lunges|braces|realizes|slices|slams|freezes|frantically|doesn\'t waste|doesn\'t hesitate)\s+[^,\.]*?(?:as|when|that|to)?\s*", "", first_sent, flags=re.IGNORECASE)
    words = first_sent.split()
    if 2 <= len(words) <= 7:
        clean_theme = " ".join(words).title()
    elif len(words) > 7:
        clean_theme = " ".join(words[:6]).title()
    else:
        clean_theme = f"Chapter {ep}"
    clean_theme = re.sub(r"[^a-zA-Z0-9\s\-–—\':]", "", clean_theme).strip()
    return clean_theme if len(clean_theme) > 3 else f"Chapter {ep}"


UNIVERSAL_NARRATIVE_PROGRESSION = {
    "zombie_apocalypse": [
        "Outbreak & Patient Zero",
        "The Barricades & Apartment Siege",
        "Road Ambush & Gas Station Escape",
        "Mutated Predators & First Swarm",
        "Highway Quarantine Zone Collapse",
        "Gathering Survivors & Rising Despair",
        "Underground Infiltration & Secret Lab",
        "Military Checkpoint Fall & Tyrant Evolution",
        "The Swarm Overruns The City Center",
        "Final Extraction & Dawn of Ruin",
    ],
    "tower_anti_regression": [
        "Nightmare Tower & The Rejected Regression",
        "The Solitary Floor 100 Awakening",
        "Descent into Chaos & Gorgon Fortress",
        "The Rogue Enchantress & First Blood",
        "Shattering The System & False Adapters",
        "Nightmare Lords & Dream Seduction",
        "The Ruined Citadel & Infiltration",
        "Monarchs of Chaos & Abyss Awakening",
        "Tree of Imagery & The Reality Thrust",
        "Breaking The World & Dawn of Chaos",
    ],
    "hunter_gate": [
        "The Calamity Gate & Betrayal in the Abyss",
        "The Glitched Awakening & First Blood",
        "Returning to Modern Earth & Solo Hunter",
        "High-Rank Dungeon Raid & S-Rank Ambush",
        "Breaking The Global Hunter System",
        "The Void Monarch's Shadows",
        "Guild War & Underground Arena",
        "The Red Gate Cataclysm",
        "Sovereign Showdown & Sovereign Domain",
        "Monarch's Reign & The Next Calamity",
    ],
    "bunker_prepper": [
        "Cataclysm Warning & Fortifying the Vault",
        "The Eternal Frost & Parasites Arrive",
        "Repelling The Warlords & Infinite Supplies",
        "Wasteland Scouting & Sub-Zero Predators",
        "The Energy Core Upgrade",
        "Raiding The Corrupt Shelter",
        "Mutant Swarm & Vault Perimeter Defense",
        "Infiltrating The Underground City",
        "The Wasteland Siege & Ruthless Retribution",
        "Sovereign of the Frozen Earth",
    ],
    "reincarnation_revenge": [
        "The Fatal Betrayal & Death in the Abyss",
        "Rebirth with 10 Years of Future Knowledge",
        "Hoarding Forbidden Artifacts in Secret",
        "First Blood Against Former Traitors",
        "Dominating The Underground Black Market",
        "Crushing The Corrupt Noble Clan",
        "Unleashing The Forbidden Bloodline",
        "The High Citadel Confrontation",
        "Absolute Vengeance & Royal Fall",
        "Sovereign of Rebirth: The New Era",
    ],
    "murim_apocalypse": [
        "The Demonic Sect Incursion & Ruined Sect",
        "Awakening The Heavenly Demon Dantian",
        "Slicing Through The Zombie Outbreak in Jianghu",
        "The Poison Clan's Deadly Ambush",
        "Breaking The Nine Heavens Barrier",
        "Solo Slaughter of Corrupt Elders",
        "The Demonic Blood Sword Master",
        "Alliance Siege on Heavenly Demon Mount",
        "The Grand Climax: Slicing the Nether Gate",
        "The Undisputed Martial Sovereign",
    ],
    "general_apocalypse": [
        "The Sudden Cataclysm & The Awakening",
        "Brutal Survival & Adapting to the New World",
        "Securing The Safe Zone & Gathering Allies",
        "The First Siege: Repelling The Swarm",
        "Power Breakthrough & Unlocking Hidden Potential",
        "Into The Wasteland & Uncovering Dark Truths",
        "The Swarm Evolves & Desperate Stand Under Siege",
        "Infiltrating The Enemy Stronghold",
        "The Climax: Total War for Survival",
        "Dawn of a New Era & The Path Ahead",
    ],
}


def build_narrative_story_chapters(
    chapters: Optional[List[Dict[str, Any]]],
    download_dir: Optional[str] = None,
    comic_title: str = "Comic",
    archetype: str = "general_apocalypse",
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[Dict[str, Any]]:
    """
    Builds narrative story chapters grouped by video story progression / arcs (form chung cho mọi video).
    Ensures the first chapter is strictly 00:00 and chapters represent key narrative progression acts.
    """
    if not chapters:
        prog_list = UNIVERSAL_NARRATIVE_PROGRESSION.get(archetype, UNIVERSAL_NARRATIVE_PROGRESSION["general_apocalypse"])
        return [
            {"timestamp": "00:00", "title": f"Arc 1: {prog_list[0]}", "episode": from_ep},
            {"timestamp": "05:00", "title": f"Arc 2: {prog_list[1]}", "episode": from_ep + 1},
            {"timestamp": "15:00", "title": f"Arc 3: {prog_list[len(prog_list)//2]}", "episode": from_ep + 2},
            {"timestamp": "30:00", "title": f"Arc 4: {prog_list[-1]}", "episode": to_ep},
        ]

    total_eps = len(chapters)

    if total_eps <= 2 and all(ch.get("title", "").strip().lower().startswith("episode") for ch in chapters):
        return [
            {
                "timestamp": "00:00" if i == 0 else ch.get("timestamp", "00:00"),
                "title": ch.get("title", f"Episode {ch.get('episode', i + 1)}"),
                "episode": ch.get("episode", i + 1)
            }
            for i, ch in enumerate(chapters)
        ]

    prog_list = UNIVERSAL_NARRATIVE_PROGRESSION.get(archetype, UNIVERSAL_NARRATIVE_PROGRESSION["general_apocalypse"])

    if total_eps >= 35:
        num_arcs = 10
    elif total_eps >= 16:
        num_arcs = 8
    elif total_eps >= 7:
        num_arcs = 6
    elif total_eps >= 3:
        num_arcs = min(total_eps, 4)
    else:
        num_arcs = 1

    result = []
    for k in range(num_arcs):
        start_idx = round(k * total_eps / num_arcs)
        end_idx = min(total_eps - 1, round((k + 1) * total_eps / num_arcs) - 1)
        if end_idx < start_idx:
            end_idx = start_idx

        ch_start = chapters[start_idx]
        ch_end = chapters[end_idx]
        start_ep = ch_start.get("episode", start_idx + from_ep)
        end_ep = ch_end.get("episode", end_idx + from_ep)

        ts = "00:00" if k == 0 else ch_start.get("timestamp", "00:00")
        theme_idx = min(len(prog_list) - 1, round(k * (len(prog_list) - 1) / max(1, num_arcs - 1)))
        base_theme = prog_list[theme_idx]

        custom_theme = None
        if download_dir:
            recap_path = os.path.join(download_dir, f"episode_{start_ep}", "recap.json")
            custom_theme = extract_episode_theme(recap_path, start_ep, comic_title)
            if custom_theme and (custom_theme.lower().startswith("chapter") or custom_theme.lower().startswith("episode")):
                custom_theme = None

        chosen_theme = custom_theme if custom_theme else base_theme
        ep_label = f"Ep {start_ep}" if start_ep == end_ep else f"Ep {start_ep}–{end_ep}"
        title = f"Arc {k + 1}: {chosen_theme} ({ep_label})"

        result.append({
            "timestamp": ts,
            "title": title,
            "episode": start_ep,
            "end_episode": end_ep,
            "theme": chosen_theme,
        })

    return result


def format_recap_title(base_title: str, suffix: str = " | Manhwa Recap") -> str:
    """
    Ensures the title always ends with ' | Manhwa Recap' (standard YouTube US Manhwa Recap convention),
    while keeping the total length strictly within YouTube's 100-character limit.
    """
    cleaned = base_title.strip()
    if cleaned.lower().endswith("manhwa recap"):
        cleaned = re.sub(r"[\s\-\|]+manhwa recap$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(" -|")
    target = f"{cleaned}{suffix}"
    if len(target) > 100:
        max_base_len = 100 - len(suffix)
        cleaned = cleaned[:max_base_len].rstrip(" .,-|")
        return f"{cleaned}{suffix}"
    return target


def find_character_image_references(
    download_dir: Optional[str] = None,
    image_references: Optional[Dict[str, Any]] = None
) -> Dict[str, List[str]]:
    """
    Finds real character panel images from downloaded episodes for AI image prompt reference.
    """
    refs = {"protagonist": [], "female_characters": []}
    if image_references:
        for k, v in image_references.items():
            if k in refs and isinstance(v, list):
                refs[k].extend(v)

    if download_dir and os.path.isdir(download_dir):
        for ep in [1, 2, 3]:
            ep_img_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
            if os.path.isdir(ep_img_dir):
                imgs = sorted(glob.glob(os.path.join(ep_img_dir, "*.webp")) + glob.glob(os.path.join(ep_img_dir, "*.jpg")) + glob.glob(os.path.join(ep_img_dir, "*.png")))
                if imgs and len(refs["protagonist"]) < 2:
                    refs["protagonist"].append(imgs[min(1, len(imgs) - 1)])
        for ep in [4, 14, 15, 20, 27, 35, 40, 74]:
            ep_img_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
            if os.path.isdir(ep_img_dir):
                imgs = sorted(glob.glob(os.path.join(ep_img_dir, "*.webp")) + glob.glob(os.path.join(ep_img_dir, "*.jpg")) + glob.glob(os.path.join(ep_img_dir, "*.png")))
                if imgs and len(refs["female_characters"]) < 2:
                    refs["female_characters"].append(imgs[min(2, len(imgs) - 1)])

    return refs


def extract_story_narrative_climax_highlights(
    comic_title: str,
    from_ep: int,
    to_ep: int,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Dynamically scans actual episode recaps, story memory, and dialogue to extract dramatic narrative peaks,
    key weapons, high-stakes conflicts, intimate moments, enemy interactions, and resource milestones.
    """
    highlights = []

    if story_memory and isinstance(story_memory, dict):
        for k in ["climax_moment", "signature_weapon", "turning_point", "core_conflict", "recent_events", "current_threat"]:
            val = story_memory.get(k)
            if val and isinstance(val, str) and len(val.strip()) > 8:
                highlights.append({"source": k, "summary": val.strip()})

    if download_dir and os.path.isdir(download_dir):
        ep_list = []
        if from_ep == to_ep:
            ep_list = [from_ep]
        else:
            ep_list = sorted(list(set([
                from_ep,
                from_ep + 1,
                (from_ep + to_ep) // 2,
                max(from_ep, to_ep - 2),
                max(from_ep, to_ep - 1),
                to_ep
            ])))

        for ep in ep_list:
            rpath = os.path.join(download_dir, f"episode_{ep}", "recap.json")
            if os.path.isfile(rpath):
                try:
                    with open(rpath, "r", encoding="utf-8") as rf:
                        rdata = json.load(rf)
                    if isinstance(rdata, list) and rdata:
                        speeches = [item.get("speech", "").strip() for item in rdata if isinstance(item, dict) and item.get("speech")]
                        if speeches:
                            # Pick top longest action/dialogue sentence
                            longest = max(speeches, key=len)
                            if len(longest) > 20:
                                highlights.append({"source": f"Episode {ep}", "summary": longest[:220]})
                except Exception:
                    pass

    return highlights


# =============================================================================
# 6-LAYER STANDARDIZED GPT IMAGE PROMPT BUILDER (DALL-E 3 & GPT-4o COMPLIANT)
# =============================================================================

def build_standard_gpt_image_prompt(
    art_medium_and_style: str,
    characters_and_references: List[Dict[str, str]],
    spatial_composition: str,
    scene_environment_and_lighting: str,
    clickbait_graphic_overlays: str,
    technical_guardrails: str = "Ensure anatomical precision with crisp hand-drawn ink outlines, natural hand proportions, sharp facial features, and zero visual distortion or watermarks.",
) -> str:
    """
    Constructs an anatomically rigorous 6-layer prompt specifically engineered for OpenAI GPT-4o / DALL-E 3
    multi-image reference processing, 2.5D webtoon aesthetics, and YouTube clickbait typography.
    """
    char_lines = []
    for c in characters_and_references:
        char_lines.append(f"• {c['label']} (Reference: {c['ref_image']}): {c['description']}")
    char_block = "\n".join(char_lines)

    prompt = (
        f"[IMAGE MEDIUM, ART STYLE & ASPECT RATIO]\n"
        f"{art_medium_and_style}\n\n"
        f"[CHARACTER REFERENCES & SUBJECT ANCHORS]\n"
        f"{char_block}\n\n"
        f"[SPATIAL COMPOSITION & CAMERA FRAMING]\n"
        f"{spatial_composition}\n\n"
        f"[SCENE ENVIRONMENT, 2.5D LIGHTING & COLOR PALETTE]\n"
        f"{scene_environment_and_lighting}\n\n"
        f"[YOUTUBE CLICKBAIT GRAPHIC DESIGN & TYPOGRAPHY OVERLAYS]\n"
        f"{clickbait_graphic_overlays}\n\n"
        f"[TECHNICAL QUALITY & ANATOMY GUARDRAILS]\n"
        f"{technical_guardrails}"
    )
    return prompt


def generate_story_flex_thumbnail_concepts(
    comic_title: str,
    from_ep: int,
    to_ep: int,
    archetype: str,
    mc_name: str,
    female_lead_name: str,
    image_refs: Dict[str, List[str]],
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Pure AI Story-Flex Thumbnail Synthesizer generating 5 distinct, high-CTR viral concepts
    engineered strictly under the Standard 6-Layer GPT-4o / DALL-E 3 Image Generation Framework:
      1. The Sovereign Feat & Reality Piercing Climax (Peak Power / Decisive Strike)
      2. Lethal Seductive Proximity & Whispered Tension (Intimate Stand-off / Flirtation)
      3. Disbelief Shock & Total Enemy Humiliation (Enemy Defeat / Begging for Mercy)
      4. Extreme Resource & Safezone Monopoly Contrast (Luxury Haven vs Wasteland Hell)
      5. Glitched System / Forbidden Choice Defiance (RPG Quest Warning / Rule Breaking)
    """
    mc_ref_path = image_refs['protagonist'][0] if image_refs['protagonist'] else "Panel ảnh nam chính từ episode_1"
    f1_ref_path = image_refs['female_characters'][0] if image_refs['female_characters'] else "Panel ảnh nữ phụ 1 từ episode_14"
    f2_ref_path = image_refs['female_characters'][1] if len(image_refs['female_characters']) > 1 else f1_ref_path
    enemy_ref_path = image_refs.get('enemies', [f2_ref_path])[0] if image_refs.get('enemies') else f2_ref_path

    raw_highlights = extract_story_narrative_climax_highlights(comic_title, from_ep, to_ep, story_memory, download_dir)
    highlight_text = " ".join([h["summary"] for h in raw_highlights]).lower()
    t_lower = (comic_title or "").lower()

    art_style_header = (
        "An ultra-detailed, cinematic 16:9 widescreen YouTube thumbnail illustration in authentic Modern Korean Webtoon (Manhwa 2.5D) art style "
        "(signature visual aesthetic of Redice Studio, Solo Leveling, and The World After The Fall). "
        "Crisp dark ink linework, saturated cel-shading, dynamic 2.5D volumetric rim lighting, high micro-contrast, and glowing particle effects."
    )

    concepts = []

    # =========================================================================
    # CONCEPT 1: THE SOVEREIGN FEAT & REALITY PIERCING CLIMAX (PEAK POWER)
    # =========================================================================
    if "world after the fall" in t_lower or "thrust" in highlight_text:
        c1_name = "The 10-Billion Thrusts & Reality Piercing Awakening"
        c1_text = "ONE STAB WAS ENOUGH"
        c1_style = "Font Gothic vàng kim (#FFD700) phát sáng cực đại viền đen 8px, kèm vệt chém hư không tím xé toạc không gian."
        c1_mc = f"Possesses an athletic, vascular 8-pack build and sharp chiseled jawline. Masculine sovereign ({mc_name}) holding a dark blade crackling with reality-piercing violet void lightning."
        c1_fl = f"Female lead ({female_lead_name}) standing intimately behind him in awe, glistening eyes, flushed beet-red cheeks, and parted glossy lips."
        c1_spatial = "Dynamic Dutch low-angle framing with Protagonist commanding the center-left foreground. Dramatic depth of field with shattered stone shards in extreme foreground."
        c1_env = "Shattered 100th floor threshold entering cosmic Chaos wilderness. Swirling violet nebula sky, floating stone ruins, volumetric backlighting, and floating magical embers."
        c1_overlay = 'In the upper-left corner, render bold glowing golden-yellow (#FFD700) comic typography reading "ONE STAB WAS ENOUGH" with an 8px solid black stroke and drop shadow.'
    elif any(k in t_lower or k in highlight_text for k in ["bunker", "shut-in", "shutin", "freeze", "hoard", "shelter"]):
        c1_name = "The Ultimate Shelter Sovereign & Impenetrable Defense Blast"
        c1_text = "HE OBLITERATED THEM ALL"
        c1_style = "Font Gothic vàng kim (#FFD700) viền đen 8px, chùm tia laser phòng thủ tự động quét sạch kẻ đột kích."
        c1_mc = f"Handsome bunker sovereign ({mc_name}) casually pressing a glowing red defense console button with a mocking smirk, dressed in tactical dark adventurer attire."
        c1_fl = f"Beautiful female companion ({female_lead_name}) in a cozy indoor outfit watching automated laser turrets annihilate attacking raiders through reinforced glass with utter devotion."
        c1_spatial = "Wide 16:9 interior angle showing MC centered at command console with cinematic split-screen view of defense lasers vaporizing enemies outside."
        c1_env = "High-tech subterranean command bridge with warm amber display lights contrasting with brilliant cyan-and-red defense laser beams."
        c1_overlay = 'At the top-left, render massive bold typography reading "HE OBLITERATED THEM ALL" in vivid golden yellow (#FFD700) with an 8px black stroke.'
    elif any(k in t_lower or k in highlight_text for k in ["zombie", "infected", "82-08", "8208", "outbreak"]):
        c1_name = "The Day 1 vs Day 100 Undead Slayer Transformation"
        c1_text = "DAY 1 VS DAY 100"
        c1_style = "Font Impact chia đôi: 'DAY 1: VICTIM' (màu đỏ rách nát) vs 'DAY 100: MONSTER' (màu vàng kim phát sáng)."
        c1_mc = f"Battle-hardened lone survivor ({mc_name}) standing atop a mountain of defeated mutated infected. Dual customized combat blades in hand, glowing piercing eyes, battle-worn combat vest over sculpted muscular arms."
        c1_fl = f"Fearless female companion ({female_lead_name}) in tactical combat gear reloading her weapon while gazing at him in profound admiration."
        c1_spatial = "Extreme low-angle hero shot with protagonist dominating composition. Blurred silhouettes of reaching zombie claws in extreme foreground."
        c1_env = "Barricaded skyscraper rooftop under a burning crimson sunset sky. Volumetric smoke, glowing red eye reflections, and vibrant golden rim light on hero silhouette."
        c1_overlay = 'At the top-center, render contrasting split-title banner: "DAY 1: VICTIM" in distressed dark red on left, and "DAY 100: MONSTER" in gleaming golden yellow (#FFD700) with heavy black outline on right.'
    elif any(k in t_lower or k in highlight_text for k in ["solo", "hunter", "shadow", "monarch", "gate"]):
        c1_name = "The Glitched Level 999 Awakening & Sovereign Shadow Domain"
        c1_text = "LEVEL 999 MONARCH"
        c1_style = "Font Gothic vàng kim viền đen 'LEVEL 999 MONARCH', bảng nhiệm vụ System Quest Hologram phát sáng neon."
        c1_mc = f"Handsome black-haired solo hunter ({mc_name}) with glowing electric cyan-and-violet eyes. Dark trench coat billowing with shadow aura, surrounded by crackling dimensional lightning."
        c1_fl = f"High-ranking S-Class female hunter ({female_lead_name}) kneeling in shock and awe as she witnesses his glitched sovereign power."
        c1_spatial = "Grand wide-angle perspective with MC elevated on a dungeon dais. Scores of summoned shadow phantom warriors rising from ground behind him."
        c1_env = "Calamity Red Gate dungeon boss chamber with cracked crystalline pillars, glowing purple rift portals, and vibrant neon rim lighting."
        c1_overlay = 'In the upper-left, render bold Gothic typography reading "LEVEL 999 MONARCH" in vivid yellow with black stroke. In center, render floating translucent crimson RPG hologram displaying "! QUEST COMPLETED: DEIFIED !".'
    else:
        c1_name = "The Unstoppable Climax & Awakened Sovereign Strike"
        c1_text = "ONE STRIKE WAS ENOUGH"
        c1_style = "Font Gothic vàng kim (#FFD700) viền đen 8px, vệt kiếm khí rực sáng xé toạc không gian."
        c1_mc = f"Athletic awakened sovereign ({mc_name}) radiating supreme confidence, sharp jawline, glowing eyes, holding his signature weapon crackling with vibrant power embers."
        c1_fl = f"Gorgeous female lead ({female_lead_name}) intimately beside him, gazing with glistening eyes and flushed cheeks in awe of his overwhelming dominance."
        c1_spatial = "Dynamic 16:9 hero framing with MC front-and-center and female lead leaning in on right. Foreground bokeh blur on shattered dimensional particles."
        c1_env = "Ruined citadel surrounded by swirling atmospheric energy, dramatic volumetric backlighting, and vibrant neon rim light."
        c1_overlay = 'At the top-left, render bold comic typography reading "ONE STRIKE WAS ENOUGH" in vibrant yellow (#FFD700) with an 8px solid black stroke and drop shadow.'

    p1 = build_standard_gpt_image_prompt(
        art_medium_and_style=art_style_header,
        characters_and_references=[
            {"label": f"MALE PROTAGONIST ({mc_name})", "ref_image": "Please match Image 1 (Face, hairstyle, eyes, physique)", "description": c1_mc},
            {"label": f"FEMALE LEAD ({female_lead_name})", "ref_image": "Please match Image 2 (Hair, facial features, curves)", "description": c1_fl},
        ],
        spatial_composition=c1_spatial,
        scene_environment_and_lighting=c1_env,
        clickbait_graphic_overlays=c1_overlay,
    )

    concepts.append({
        "id": "concept_sovereign_climax",
        "name": c1_name,
        "thumbnail_text": c1_text,
        "text_overlay": c1_text,
        "text_style": c1_style,
        "characters": [
            {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
            {"role": f"Nữ chính ({female_lead_name})", "image_reference": f1_ref_path},
        ],
        "prompt": p1,
        "gpt_prompt": p1,
    })

    # =========================================================================
    # CONCEPT 2: LETHAL SEDUCTIVE PROXIMITY & WHISPERED TENSION
    # =========================================================================
    if "world after the fall" in t_lower:
        c2_name = "The Soul-Clothes Inspection & Lethal Proximity in Gorgon Fortress"
        c2_text = "INSPECTING MY BODY?"
        c2_style = "Bong bóng thoại truyện tranh vàng chanh viền đen 8px 'INSPECTING MY BODY?', mũi tên chỉ vào Mino, vạch đỏ mặt '???'."
        c2_mc = f"Handsome swordsman ({mc_name}) with cold indifferent eyes, calmly resting glowing sharp tip of his dark blade against her throat in an electric standoff."
        c2_fl = f"Mino ({female_lead_name}) leaning in merely one inch away from his lips, playfully tugging her unbuttoned collar to inspect his spirit core. Flushed beet-red cheeks, glossy parted lips, and playful bedroom eyes."
        c2_spatial = "Extreme close-up Dutch angle framing. The distance between their faces is less than an inch, creating intense romantic and fatal tension."
        c2_env = "Private backroom in Gorgon Fortress tavern. Flickering warm candlelight, deep shadows, and subtle violet void rim lighting."
        c2_overlay = 'In upper-right corner, render vibrant yellow comic speech bubble with an 8px solid black stroke reading "INSPECTING MY BODY?" pointing at female lead, with red comic blushing lines and question marks "???".'
    elif any(k in t_lower or k in highlight_text for k in ["bunker", "shut-in", "shutin", "freeze", "shelter"]):
        c2_name = "The Luxury Lounge Seduction & Heated Bunker Flirtation"
        c2_text = "TOO WARM IN HERE?"
        c2_style = "Bong bóng thoại màu hồng viền đen 'TOO WARM IN HERE?', nữ nhân vật cởi bớt áo khoác lộ đường cong quyến rũ."
        c2_mc = f"Handsome male sovereign ({mc_name}) sitting relaxed on a plush sofa, composed and amused, watching her playful flirtation."
        c2_fl = f"Alluring female survivor ({female_lead_name}) leaning over him intimately in heated bunker, playfully slipping off her winter jacket to reveal a form-fitting athletic crop top. Flushed cheeks, glistening eyes, and teasing smile."
        c2_spatial = "Intimate over-the-shoulder Dutch angle with female companion leaning directly toward camera and protagonist in foreground."
        c2_env = "Cozy luxury bunker living quarters with glowing electric fireplace, amber ambient lighting, and rich warm shadows."
        c2_overlay = 'In top corner, render expressive pink-and-yellow comic speech bubble reading "TOO WARM IN HERE?" with heart icons and cute comic blushing lines.'
    elif any(k in t_lower or k in highlight_text for k in ["zombie", "82-08", "8208", "outbreak"]):
        c2_name = "The Silent Barricade Embrace During The Midnight Horde"
        c2_text = "DON'T MAKE A SOUND!"
        c2_style = "Bong bóng thì thầm căng thẳng 'DON'T MAKE A SOUND!', MC che miệng nữ chính ép sát vào ngực khi bầy zombie lướt qua."
        c2_mc = f"Protagonist ({mc_name}) holding one hand gently over her parted lips while pulling her tightly against his chest behind a splintered barricade."
        c2_fl = f"Female lead ({female_lead_name}) pressed against him, breathless with heart-pounding tension, glistening eyes staring into his, blushing in close proximity."
        c2_spatial = "Tight vertical framing focusing on their faces and chest proximity behind a splintered wooden barricade."
        c2_env = "Moonlit ruined corridor with cool blue light filtering through broken glass and ominous yellow zombie eyes glowing in background darkness."
        c2_overlay = (
            'In upper-left, render high-tension comic whisper bubble reading "DON\'T MAKE A SOUND!" '
            'in yellow with heavy black outline and exclamation marks.'
        )
    else:
        c2_name = "The Lethal Intimate Proximity & Whispered Stand-off"
        c2_text = "TOO CLOSE RIGHT?"
        c2_style = "Bong bóng thoại màu vàng viền đen dày, dấu chấm hỏi đỏ mặt '???' trên đầu nam chính."
        c2_mc = f"Cold, unyielding male protagonist ({mc_name}) with sharp indifferent eyes, casually holding his weapon between them to maintain lethal distance."
        c2_fl = f"Seductive female lead ({female_lead_name}) whispering playfully inches from his face, flushed cheeks, parted glossy lips, and form-fitting combat attire."
        c2_spatial = "Tightly cropped intimate Dutch angle framing their faces in sharp focus with warm ambient bokeh blur in background."
        c2_env = "Private refuge sanctuary with warm lantern glow, chiaroscuro lighting, and violet rim light on their silhouettes."
        c2_overlay = 'In upper corner, render vibrant yellow comic speech bubble with thick black outline reading "TOO CLOSE RIGHT?" with red blushing lines.'

    p2 = build_standard_gpt_image_prompt(
        art_medium_and_style=art_style_header,
        characters_and_references=[
            {"label": f"MALE PROTAGONIST ({mc_name})", "ref_image": "Please match Image 1 (Face, hairstyle, eyes, physique)", "description": c2_mc},
            {"label": f"FEMALE LEAD ({female_lead_name})", "ref_image": "Please match Image 2 (Hair, facial features, curves)", "description": c2_fl},
        ],
        spatial_composition=c2_spatial,
        scene_environment_and_lighting=c2_env,
        clickbait_graphic_overlays=c2_overlay,
    )

    concepts.append({
        "id": "concept_intimate_proximity",
        "name": c2_name,
        "thumbnail_text": c2_text,
        "text_overlay": c2_text,
        "text_style": c2_style,
        "characters": [
            {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
            {"role": f"Nữ chính ({female_lead_name})", "image_reference": f1_ref_path},
        ],
        "prompt": p2,
        "gpt_prompt": p2,
    })

    # =========================================================================
    # CONCEPT 3: DISBELIEF SHOCK & TOTAL ENEMY HUMILIATION (REACTION SHOCK)
    # =========================================================================
    c3_name = "The Total Domination & Defeated Rivals Begging For Mercy"
    c3_text = "THEY BEGGED FOR MERCY"
    c3_style = "Font khối trắng viền cyan phát sáng 'THEY BEGGED FOR MERCY', các thủ lĩnh đối thủ quỳ gối xin tha trước hào quang MC."
    c3_mc = f"Supreme Sovereign ({mc_name}) standing tall in center foreground, looking down with cold amusement, dark coat billowing with radiant sovereign aura."
    c3_enemy = f"Defeated rival warlords and arrogant guild leaders ({female_lead_name} & rivals) kneeling in trembling submission, bruised and sweating in sheer disbelief."
    c3_spatial = "Heroic low-angle perspective with MC elevated in sharp foreground focus and kneeling rivals foreshortened in dramatic perspective below."
    c3_env = "Conquered apocalyptic battlefield with fiery sunset sky, burning debris, volumetric smoke plumes, and brilliant neon cyan rim lighting."
    c3_overlay = 'At top-center, render bold all-caps typography reading "THEY BEGGED FOR MERCY" in pure white with a neon cyan outer glow and an 8px solid black stroke.'

    p3 = build_standard_gpt_image_prompt(
        art_medium_and_style=art_style_header,
        characters_and_references=[
            {"label": f"SOVEREIGN PROTAGONIST ({mc_name})", "ref_image": "Please match Image 1 (Face, hairstyle, eyes, physique)", "description": c3_mc},
            {"label": f"DEFEATED RIVALS & WITNESSES ({female_lead_name})", "ref_image": "Please match Image 2 & Image 3", "description": c3_enemy},
        ],
        spatial_composition=c3_spatial,
        scene_environment_and_lighting=c3_env,
        clickbait_graphic_overlays=c3_overlay,
    )

    concepts.append({
        "id": "concept_enemy_humiliation",
        "name": c3_name,
        "thumbnail_text": c3_text,
        "text_overlay": c3_text,
        "text_style": c3_style,
        "characters": [
            {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
            {"role": f"Nữ phụ / Kẻ thù ({female_lead_name})", "image_reference": f1_ref_path},
            {"role": "Đối thủ quỳ gối", "image_reference": enemy_ref_path},
        ],
        "prompt": p3,
        "gpt_prompt": p3,
    })

    # =========================================================================
    # CONCEPT 4: EXTREME RESOURCE & SAFEZONE MONOPOLY CONTRAST
    # =========================================================================
    if any(k in t_lower or k in highlight_text for k in ["bunker", "shut-in", "shutin", "freeze", "hoard", "shelter"]):
        c4_name = "The 50,000 Tons Supply Warehouse & Safezone Paradise Contrast"
        c4_text = "50,000 TONS OF FOOD"
        c4_style = "Font Impact vàng chanh (#FFE500) viền đen 8px '50,000 TONS OF FOOD', mũi tên neon chỉ vào kho lương thực vô tận và MC ung dung."
        c4_mc = f"Protagonist ({mc_name}) sitting relaxed on an executive armchair with an amused smirk, savoring fresh gourmet steak and wine inside heated vault."
        c4_fl = f"Two gorgeous female survivors ({female_lead_name} & companion) looking through reinforced glass from the freezing blizzard with yearning, tearful eyes and flushed cold cheeks."
        c4_spatial = "Split-depth perspective: 60% left showing heated luxury vault interior in foreground, 40% right showing freezing blizzard wasteland through reinforced glass."
        c4_env = "Warm amber indoor lighting and glowing holographic inventory counters showing 'SUPPLIES: 999,999+' contrasting with howling blue snowstorm outside."
        c4_overlay = 'At top-left, render bold high-impact typography reading "50,000 TONS OF FOOD" in vibrant yellow (#FFE500) with 8px black stroke. Render glowing badges: "SAFEZONE" in neon cyan and "APOCALYPSE" in fiery red.'
    else:
        c4_name = "The Supreme Monopoly & Paradise vs Wasteland Contrast"
        c4_text = "ALL GIRLS WANT IN"
        c4_style = "Chia đôi nhãn: SAFEZONE (xanh neon cyan) bên trong ấm áp vs APOCALYPSE (đỏ rực) bên ngoài thảm họa."
        c4_mc = f"Protagonist ({mc_name}) relaxing inside his private luxury sanctuary with unlimited fresh supplies, completely unbothered by the world end."
        c4_fl = f"Two beautiful survivors ({female_lead_name} & companion) outside at the barrier gates, wearing battle-torn attire, pleading with clasped hands to enter."
        c4_spatial = "Wide split-screen perspective contrasting luxury interior in foreground left with brutal apocalyptic wasteland in background right."
        c4_env = "Warm golden indoor illumination and clean neon status lights contrasting with dark stormy exterior skies."
        c4_overlay = 'At top-center, render massive bold all-caps typography reading "ALL GIRLS WANT IN" in yellow (#FFE500) with heavy black outline and glowing badges: "SAFEZONE" (cyan) vs "APOCALYPSE" (red).'

    p4 = build_standard_gpt_image_prompt(
        art_medium_and_style=art_style_header,
        characters_and_references=[
            {"label": f"SOVEREIGN PROTAGONIST ({mc_name})", "ref_image": "Please match Image 1 (Face, hairstyle, eyes, physique)", "description": c4_mc},
            {"label": f"OUTSIDE SURVIVORS ({female_lead_name})", "ref_image": "Please match Image 2 & Image 3", "description": c4_fl},
        ],
        spatial_composition=c4_spatial,
        scene_environment_and_lighting=c4_env,
        clickbait_graphic_overlays=c4_overlay,
    )

    concepts.append({
        "id": "concept_resource_contrast",
        "name": c4_name,
        "thumbnail_text": c4_text,
        "text_overlay": c4_text,
        "text_style": c4_style,
        "characters": [
            {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
            {"role": f"Nữ phụ 1 ({female_lead_name})", "image_reference": f1_ref_path},
            {"role": "Nữ phụ 2", "image_reference": f2_ref_path},
        ],
        "prompt": p4,
        "gpt_prompt": p4,
    })

    # =========================================================================
    # CONCEPT 5: GLITCHED SYSTEM / FORBIDDEN CHOICE DEFIANCE
    # =========================================================================
    if "world after the fall" in t_lower or "tower" in t_lower:
        c5_name = "The Nightmare Mistress Seduction & Crushed Return Stone"
        c5_text = "SHE OFFERED PARADISE"
        c5_style = "Font khối dày màu vàng chanh (#FFE500) 'SHE OFFERED PARADISE', mũi tên chỉ bàn tay bóp nát đá hồi quy 'HE CHOSE CHAOS'."
        c5_mc = f"Jaehwan ({mc_name}) seated on an obsidian throne, indifferent and cold, left fist crushing a glowing blue Return Stone into glittering magical dust."
        c5_fl = f"Nightmare Lord Sirwen Armelt ({female_lead_name}) floating behind him with delicate demonic horns, whispering sweet illusions into his ear, wearing a semi-translucent astral gown."
        c5_spatial = "Centered regal framing with Jaehwan commanding the throne and the Nightmare Lord wrapped around his shoulders."
        c5_env = "Surreal mystical dream realm with floating clock gears, purple nebula mist, and glittering blue crystal shards falling from his fist."
        c5_overlay = 'At top-center, render bold typography reading "SHE OFFERED PARADISE" in yellow (#FFE500) with black stroke, and an arrow pointing to the crushed crystal reading "HE CHOSE CHAOS".'
    elif any(k in t_lower or k in highlight_text for k in ["hunter", "gate", "system", "dungeon", "solo"]):
        c5_name = "The Glitched Alert System Quest & S-Rank Defiance"
        c5_text = "! ALERT: SSS-RANK DETECTED !"
        c5_style = "Bảng nhiệm vụ System Hologram đỏ rực màu máu, font in hoa '! ALERT: SSS-RANK DETECTED !', mũi tên vàng neon chỉ vào hào quang MC."
        c5_mc = f"Solo Hunter ({mc_name}) walking forward with an amused smirk as an enormous crimson-and-gold system quest window hovers before him."
        c5_fl = f"S-Rank female guild master ({female_lead_name}) gasping in disbelief in background as dungeon ranking system shatters."
        c5_spatial = "Dynamic Dutch perspective with floating holographic system window angled across center screen."
        c5_env = "Dungeon portal threshold with crackling dimensional lightning, crimson warning light, and glowing holographic runes."
        c5_overlay = 'Floating across center, render prominent glowing crimson RPG system window with warning borders reading "! ALERT: SSS-RANK MONARCH DETECTED !".'
    else:
        c5_name = "The Glitched Awakening & System Breaking Defiance"
        c5_text = "HE BROKE THE SYSTEM!"
        c5_style = "Bảng thông số System Hologram vỡ vụn với tia sét neon cyan, font in hoa 'HE BROKE THE SYSTEM!'."
        c5_mc = f"Protagonist ({mc_name}) shattering a floating red warning holographic window with one fist, surrounded by crackling violet lightning."
        c5_fl = f"Witness companion ({female_lead_name}) gasping in sheer awe as the world rules collapse around him."
        c5_spatial = "Dynamic 16:9 diagonal angle with shattered glass HUD elements flying towards camera."
        c5_env = "Crackling dimensional rift with glowing runic circles, volumetric electric discharge, and dark violet atmosphere."
        c5_overlay = 'In center, render shattered holographic system window reading "! ERROR: LIMIT EXCEEDED !" and top banner reading "HE BROKE THE SYSTEM!" in yellow (#FFD700) with 8px black stroke.'

    p5 = build_standard_gpt_image_prompt(
        art_medium_and_style=art_style_header,
        characters_and_references=[
            {"label": f"PROTAGONIST ({mc_name})", "ref_image": "Please match Image 1 (Face, hairstyle, eyes, physique)", "description": c5_mc},
            {"label": f"WITNESS / COMPANION ({female_lead_name})", "ref_image": "Please match Image 2", "description": c5_fl},
        ],
        spatial_composition=c5_spatial,
        scene_environment_and_lighting=c5_env,
        clickbait_graphic_overlays=c5_overlay,
    )

    concepts.append({
        "id": "concept_system_defiance",
        "name": c5_name,
        "thumbnail_text": c5_text,
        "text_overlay": c5_text,
        "text_style": c5_style,
        "characters": [
            {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
            {"role": f"Nữ phụ / Đồng đội ({female_lead_name})", "image_reference": f1_ref_path},
        ],
        "prompt": p5,
        "gpt_prompt": p5,
    })

    return concepts


def generate_us_apocalypse_metadata(
    comic_title: str,
    from_ep: int,
    to_ep: int,
    chapters: List[Dict[str, Any]] | None = None,
    story_memory: Optional[Dict[str, Any]] = None,
    image_references: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
    char_names = get_character_names(comic_title, story_memory)
    mc_name = char_names["mc"]
    female_lead_name = char_names["female_lead"]
    archetype = detect_archetype(comic_title, story_memory)
    image_refs = find_character_image_references(download_dir, image_references)

    # =========================================================================
    # 1. HIGH-CTR SEO TITLE CANDIDATES (5 CATEGORIES ACCORDING TO US YOUTUBE STANDARDS)
    # =========================================================================
    if archetype == "tower_anti_regression":
        title_options = [
            "He Refused To Regress When Everyone Else Gave Up, Climbing The Tower Alone... | Manhwa Recap",
            "He Rejected All Skills And Practiced One Thrust For Decades Until He Broke Reality | Manhwa Recap",
            f"From The Creator Of Omniscient Reader: The Man Who Refused To Regress [{ep_range}] | Manhwa Recap",
            "While Everyone Regressed, He Alone Conquered The Tower And Entered Chaos | Manhwa Recap",
            f"The Monster Who Refused The Regression Stone [{ep_range} Full Arc] | Manhwa Recap",
        ]
        synopsis_text = (
            f"When mysterious 'Towers of Nightmares' erupted across the globe, humanity was thrown into a brutal apocalypse. "
            f"Walkers were offered an escape: use the 'Return Stone' to regress back to the past and start over. "
            f"One by one, every single human abandoned the tower and regressed—except {mc_name}.\n\n"
            f"Realizing that regression was nothing more than a fabricated illusion designed to cultivate despair, {mc_name} stayed behind. "
            f"For decades, isolated in the frozen silence of the tower, he discarded all skills, system levels, and false adaptations. "
            f"He practiced a single thrust billions of times until his blade could pierce reality itself.\n\n"
            f"When he finally clears the 100th floor alone, he discovers the horrifying truth: the Tower was merely an incubator. "
            f"Beyond its peak lies [Chaos]—the ruthless afterlife where dead souls, deceptive Nightmares, and god-like Monarchs feast on human despair. "
            f"Armed only with his sword and an unyielding will to break the cycle, {mc_name} plunges into Chaos to destroy the creators of the world."
        )
    elif archetype == "bunker_prepper":
        title_options = [
            "He Prepared An Impenetrable Bunker Before The Apocalypse Struck, Then... | Manhwa Recap",
            "Everyone Laughed When He Hoarded 50,000 Tons Of Supplies, Until The Frost... | Manhwa Recap",
            f"The World Ended Overnight, But He Had An Infinite Space Warehouse [{ep_range}] | Manhwa Recap",
            "He Regressed Before The Doomsday Freeze And Prepared Everything Alone | Manhwa Recap",
            f"Surviving The Apocalypse In A Max-Level Luxury Underground Bunker [{ep_range}] | Manhwa Recap",
        ]
        synopsis_text = (
            f"When a sudden cataclysm plunges civilization into an eternal sub-zero winter, society crumbles in mere days. "
            f"While survivors freeze and turn on each other over breadcrumbs, {mc_name} relaxes inside an impenetrable subterranean fortress "
            f"stocked with decades worth of gourmet supplies, automated defenses, state-of-the-art power grids, and an infinite spatial inventory.\n\n"
            f"Armed with ruthless pragmatism and total self-sufficiency, {mc_name} turns away selfish parasites, defends his territory against mutant hordes and wasteland warlords, "
            f"and dominates the frozen apocalypse on his own terms."
        )
    elif archetype == "hunter_gate":
        title_options = [
            "He Was Left For Dead In An S-Rank Dungeon, Until He Awakened... | Manhwa Recap",
            f"The Weakest Hunter Awakened A Glitched God-Tier Ability [{ep_range}] | Manhwa Recap",
            "He Returned From The Dark Abyss As The Ultimate Undefeated Monarch | Manhwa Recap",
            "While Top Guilds Struggled, A Solo Hunter Cleared The Calamity Gate | Manhwa Recap",
            f"The Hunter Who Broke The Global Ranking System [{ep_range} Full Arc] | Manhwa Recap",
        ]
        synopsis_text = (
            f"When dimensional rifts tore open across modern Earth, grotesque monsters invaded civilization. "
            f"Mocked as the weakest awakened hunter, {mc_name} is betrayed by his squad and left for dead inside a lethal calamity dungeon. "
            f"On the verge of death, a hidden glitched system prompt awakens within his soul, granting him forbidden power that defies the world's hierarchy.\n\n"
            f"Rising from the abyss as an unstoppable solo monarch, {mc_name} conquers impossible gates, crushes corrupt top guilds, and uncovers the dark truth behind the apocalypse."
        )
    elif archetype == "zombie_apocalypse":
        title_options = [
            f"He Survived The Zombie Outbreak Day By Day While The World Collapsed [{ep_range}] | Manhwa Recap",
            "When The Infected Mutated Beyond Control, A Ruthless Survivor Emerged Alone | Manhwa Recap",
            f"From Day 1 To Day {to_ep}: Surviving The Ultimate Zombie Cataclysm [{ep_range}] | Manhwa Recap",
            "He Turned His Apartment Into An Impenetrable Fortress During The Undead Apocalypse | Manhwa Recap",
            f"The Lone Survivor Who Refused To Die In A World Of Mutated Monsters [{ep_range}] | Manhwa Recap",
        ]
        synopsis_text = (
            f"Civilization collapsed without warning when an unknown pathogen swept across the globe, "
            f"transforming billions into ferocious, flesh-craving infected. As society shattered into chaos, "
            f"supplies dwindled, and human morals dissolved in the bloody streets, {mc_name} relies on sheer survival instinct, "
            f"tactical ingenuity, and ruthless determination to stay alive.\n\n"
            f"From fortifying high-rise barricades to braving lethal supply runs through infected swarms and mutated monstrosities, "
            f"every single day is an agonizing battle for humanity's final breath. In a ruined world where both the undead and desperate survivors "
            f"pose mortal danger, {mc_name} carves an unyielding path of survival across the wasteland."
        )
    elif archetype == "reincarnation_revenge":
        title_options = [
            "He Was Betrayed And Executed By His Clan, Then Reborn 10 Years In The Past | Manhwa Recap",
            f"The Betrayed Sovereign Returned To Take Everything From His Traitors [{ep_range}] | Manhwa Recap",
            "They Stole His Throne And Power, So He Reincarnated With Forbidden Knowledge | Manhwa Recap",
            "He Died A Miserable Death, But Woke Up Before The Calamity Began | Manhwa Recap",
            f"The Ruthless Rebirth Of The Betrayed Monarch [{ep_range} Full Story] | Manhwa Recap",
        ]
        synopsis_text = (
            f"After sacrificing everything for his clan and allies, {mc_name} was betrayed, stripped of his powers, and left to die in agony. "
            f"Instead of the afterlife, he awakens ten years in the past—before the calamity struck and before the betrayal occurred.\n\n"
            f"Armed with memories of future catastrophes, hidden artifact locations, and the true faces of his enemies, {mc_name} discards naivety. "
            f"He embarks on a calculating, relentless journey of revenge, hoarding forbidden strength to crush every traitor before they even see him coming."
        )
    elif archetype == "murim_apocalypse":
        title_options = [
            f"When The Demonic Outbreak Ruined Jianghu, A Solo Martial God Awakened [{comic_title}] | Manhwa Recap",
            "He Mastered The Forbidden Heavenly Demon Blade To Slay The Undead Horde | Manhwa Recap",
            f"The Fallen Sect's Weakest Disciple Awakened The Sovereign Bloodline [{ep_range}] | Manhwa Recap",
            "While Great Sects Fell To The Nether Plague, He Cleared Jianghu Alone | Manhwa Recap",
            f"The Ultimate Murim Sovereign [{ep_range} Full Marathon] | Manhwa Recap",
        ]
        synopsis_text = (
            f"The peaceful martial world of Jianghu is torn asunder when a demonic Nether plague transforms martial artists into bloodthirsty fiends. "
            f"With great sects crumbling and orthodox masters falling one after another, {mc_name} unlocks the forgotten Heavenly Demon scripture.\n\n"
            f"Wielding lethal blade arts and unmatched internal qi, he cuts an unstoppable swath of destruction through undead hordes and corrupt factions, "
            f"restoring order to Jianghu with absolute martial might."
        )
    else:
        title_options = [
            f"A Lone Survivor Stood Against The Cataclysm [{comic_title}] | Manhwa Recap",
            f"He Refused The False System And Conquered The Apocalypse Alone [{ep_range}] | Manhwa Recap",
            f"From Zero To Sovereign: The Ultimate Apocalypse Survivor [{comic_title}] | Manhwa Recap",
            "The Lone Survivor Who Terrified The End Of The World | Manhwa Recap",
            f"Conquering The Doomsday Cataclysm [{ep_range} Full Recap] | Manhwa Recap",
        ]
        synopsis_text = (
            f"Society collapsed in a single night as an otherworldly apocalypse consumed the Earth. "
            f"While humanity descended into panic and despair, {mc_name} unlocked unyielding resolve and absolute strength, "
            f"carving an unstoppable path of survival through ruins, mutated monsters, and ruthless warlords."
        )

    title_options = [format_recap_title(t) for t in title_options]
    primary_title = title_options[0]

    # =========================================================================
    # 2. DESCRIPTION LINES WITH STORY PROGRESSION TIMESTAMPS (6-ZONE US STANDARD)
    # =========================================================================
    desc_lines = [
        f"{title_options[0]}",
        f"This is the complete marathon recap of {comic_title} ({ep_range}).",
        "",
        "📖 SYNOPSIS:",
        synopsis_text,
        "",
        "⏱️ Chapters & Timestamps (Story Progression Arcs):",
    ]

    narrative_chapters = build_narrative_story_chapters(
        chapters,
        download_dir=download_dir,
        comic_title=comic_title,
        archetype=archetype,
        from_ep=from_ep,
        to_ep=to_ep,
    )
    for ch in narrative_chapters:
        desc_lines.append(f"{ch['timestamp']} - {ch['title']}")

    clean_tag = re.sub(r"[^a-zA-Z0-9]", "", comic_title.lower())
    dynamic_hashtags = [
        f"#{clean_tag}" if clean_tag else "#manhwarecap",
        "#manhwarecap",
        "#apocalypsemanhwa",
        "#survivalmanhwa",
        "#mangarecap",
        "#webtoonrecap",
        "#opmc",
    ]
    if archetype == "zombie_apocalypse":
        dynamic_hashtags.insert(3, "#zombiemanhwa")
    elif archetype == "tower_anti_regression":
        dynamic_hashtags.insert(3, "#towermanhwa")
    elif archetype == "hunter_gate":
        dynamic_hashtags.insert(3, "#dungeonmanhwa")
    elif archetype == "bunker_prepper":
        dynamic_hashtags.insert(3, "#bunkermanhwa")
    elif archetype == "reincarnation_revenge":
        dynamic_hashtags.insert(3, "#revengemanhwa")
    elif archetype == "murim_apocalypse":
        dynamic_hashtags.insert(3, "#murimmanhwa")

    desc_lines.extend([
        "",
        "🔔 Don't forget to LIKE and SUBSCRIBE for more epic Apocalypse & Survival Manhwa recaps!",
        "💬 What was your favorite moment from this arc? Share your thoughts in the comments below!",
        "",
        "⚠️ Copyright Disclaimer:",
        "Under Section 107 of the Copyright Act 1976, allowance is made for 'fair use' for purposes such as criticism, comment, news reporting, teaching, scholarship, and research. Fair use is a use permitted by copyright statute that might otherwise be infringing. All rights belong to their respective creators and publishers.",
        "",
        " ".join(dynamic_hashtags),
    ])

    # =========================================================================
    # 3. SEO TAGS (DEDUPLICATED & CAPPED UNDER YOUTUBE'S 500-CHARACTER STUDIO LIMIT)
    # =========================================================================
    base_tags = [
        "manhwa recap",
        "apocalypse manhwa",
        "survival manhwa",
        "action manhwa recap",
        "op mc manhwa",
        "manga recap",
        "comic recap",
        "full story recap",
        "binge watch manhwa recap",
        comic_title.lower(),
        f"{comic_title.lower()} recap",
    ]
    if archetype == "zombie_apocalypse":
        base_tags.extend([
            "zombie manhwa recap",
            "zombie apocalypse manhwa",
            "undead manhwa recap",
            "outbreak manhwa",
            "survival zombie manhwa",
            "apocalypse survival recap",
        ])
    elif archetype == "tower_anti_regression":
        base_tags.extend([
            "tower manhwa recap",
            "he refused to regress",
            "refused to regress manhwa",
            "chaos arc recap",
            "tower climbing manhwa",
        ])
    elif archetype == "hunter_gate":
        base_tags.extend([
            "hunter manhwa recap",
            "dungeon manhwa recap",
            "gate manhwa",
            "solo monarch recap",
            "awakened hunter recap",
        ])
    elif archetype == "bunker_prepper":
        base_tags.extend([
            "bunker manhwa recap",
            "shelter manhwa",
            "doomsday manhwa recap",
            "infinite space manhwa",
            "ice age manhwa recap",
        ])
    elif archetype == "reincarnation_revenge":
        base_tags.extend([
            "revenge manhwa recap",
            "reincarnation manhwa",
            "regressor manhwa recap",
            "betrayed mc recap",
        ])
    elif archetype == "murim_apocalypse":
        base_tags.extend([
            "murim manhwa recap",
            "martial arts manhwa",
            "heavenly demon recap",
            "cultivation manhwa recap",
        ])

    seen_tags = set()
    cleaned_tags = []
    current_char_count = 0
    for tag in base_tags:
        t_clean = tag.strip().lower()
        if t_clean and t_clean not in seen_tags:
            tag_len = len(t_clean) + (2 if cleaned_tags else 0)
            if current_char_count + tag_len <= 485:
                seen_tags.add(t_clean)
                cleaned_tags.append(t_clean)
                current_char_count += tag_len
            else:
                break
    base_tags = cleaned_tags

    # =========================================================================
    # 4. TRUE DYNAMIC STORY-FLEX THUMBNAIL CONCEPTS (6-LAYER GPT PROMPT ENGINE)
    # =========================================================================
    thumbnail_concepts = generate_story_flex_thumbnail_concepts(
        comic_title=comic_title,
        from_ep=from_ep,
        to_ep=to_ep,
        archetype=archetype,
        mc_name=mc_name,
        female_lead_name=female_lead_name,
        image_refs=image_refs,
        story_memory=story_memory,
        download_dir=download_dir,
    )

    # Standard 6-Layer Meta-Director Prompt for Universal Generation
    meta_prompt_text = (
        f"You are an elite YouTube Manhwa Recap Art Director specializing in 1M+ view viral thumbnails.\n"
        f"Generate 3 brand-new, ultra-detailed thumbnail prompts adhering strictly to the Standard 6-Layer GPT-4o / DALL-E 3 Image Generation Framework.\n\n"
        f"[COMIC CONTEXT]\n"
        f"• Title: {comic_title} (Chapters {from_ep} to {to_ep})\n"
        f"• Subgenre: {archetype.upper()}\n"
        f"• Protagonist: {mc_name} (Reference Image 1)\n"
        f"• Female Lead: {female_lead_name} (Reference Image 2)\n"
        f"• Story Highlights: {synopsis_text[:250]}...\n\n"
        f"[MANDATORY 6-LAYER PROMPT STRUCTURE PER CONCEPT]\n"
        f"1. [IMAGE MEDIUM, ART STYLE & ASPECT RATIO]: 16:9 widescreen, Modern Korean Webtoon (Manhwa 2.5D), Redice Studio aesthetic.\n"
        f"2. [CHARACTER REFERENCES & SUBJECT ANCHORS]: Clear reference mappings (Image 1, Image 2), physical traits, costumes, poses.\n"
        f"3. [SPATIAL COMPOSITION & CAMERA FRAMING]: Dutch angle, Rule of Thirds, foreground bokeh / depth of field.\n"
        f"4. [SCENE ENVIRONMENT, 2.5D LIGHTING & COLOR PALETTE]: Volumetric backlighting, multi-colored rim lights, particle embers.\n"
        f"5. [YOUTUBE CLICKBAIT GRAPHIC DESIGN & TYPOGRAPHY OVERLAYS]: Bold yellow (#FFD700) / cyan text in quotes with 8px solid black stroke, comic speech bubbles with blushing lines, or glowing system quest holograms.\n"
        f"6. [TECHNICAL QUALITY & ANATOMY GUARDRAILS]: Anatomical precision, crisp linework, zero distortion, no watermarks."
    )

    # =========================================================================
    # 5. DYNAMIC STORY PROGRESSION ARCS TIMELINE FOR PINNED COMMENT
    # =========================================================================
    arc_lines = []
    for ch in narrative_chapters:
        arc_lines.append(f"• {ch['timestamp']} — {ch['title']}")
    arc_timeline = "\n".join(arc_lines)

    pinned_comment_text = (
        "📌 MANHWA INFO & TIMESTAMPS:\n"
        f"📖 Manhwa: {comic_title}\n"
        f"📚 Chapters: {from_ep} – {to_ep}\n\n"
        "⏱️ ARCS TIMELINE (STORY PROGRESSION):\n"
        f"{arc_timeline}\n\n"
        "👉 Like & Subscribe for more full-arc manhwa recaps!"
    )

    # =========================================================================
    # 6. FULL FORMATTED KIT STRING
    # =========================================================================
    kit_lines = [
        "=" * 80,
        f"YOUTUBE UPLOAD KIT: {comic_title}",
        f"Episodes: {from_ep} - {to_ep} | Market: us_apocalypse | Archetype: {archetype.upper()}",
        "=" * 80,
        "",
        "[1. TITLE CANDIDATES (Pick one for YouTube Title)]",
        f"★ Option 1 (Recommended - Peak Manhwa Meta):\n{title_options[0]}",
        f"\nOption 2 (Raw Power & Anti-System Trope):\n{title_options[1]}",
        f"\nOption 3 (Author / Fanbase Magnet):\n{title_options[2]}",
        f"\nOption 4 (Story-Driven Binge Marathon):\n{title_options[3]}",
        f"\nOption 5 (Mobile-First High Impact):\n{title_options[4]}",
        "",
        "[2. DESCRIPTION & TIMESTAMPS (Copy & paste into YouTube Description)]",
        "\n".join(desc_lines),
        "",
        "[3. PINNED COMMENT (BÌNH LUẬN GHIM NGẮN GỌN - Copy & paste to Pin)]",
        pinned_comment_text,
        "",
        "[4. TAGS (Copy & paste directly into YouTube Studio Tag Box)]",
        ", ".join(base_tags),
        "",
        "=" * 80,
        "[5. DYNAMIC STORY-FLEX THUMBNAIL MASTER PROMPTS (STANDARD 6-LAYER GPT-4o / DALL-E 3)]",
        "Hướng dẫn:",
        "1. Mở ChatGPT (mô hình GPT-4o), Midjourney v6, hoặc Flux.",
        "2. Bấm nút đính kèm (+) và tải lên các ảnh panel tham chiếu (Ảnh 1: Nam chính, Ảnh 2: Nữ phụ/Boss).",
        "3. Copy toàn bộ đoạn MASTER PROMPT của Concept bạn chọn dán vào khung chat để sinh ảnh Thumbnail 16:9 chuẩn Manhwa 2.5D.",
        "=" * 80,
    ]

    for i, c in enumerate(thumbnail_concepts, 1):
        kit_lines.extend([
            "",
            f"▶ CONCEPT {i}: {c['name'].upper()}",
            f"  • Clickbait Text Overlay : {c['thumbnail_text']}",
            f"  • Text Styling Guide     : {c['text_style']}",
            "  • Nhân vật & Tệp ảnh tham chiếu:",
        ])
        for idx, char in enumerate(c['characters'], 1):
            kit_lines.append(f"    - Ảnh {idx} ({char['role']}) : {char['image_reference']}")
        kit_lines.extend([
            "",
            "  • MASTER PROMPT CHO CHATGPT (Copy toàn bộ dán vào GPT-4o):",
            "--------------------------------------------------------------------------------",
            c['gpt_prompt'],
            "--------------------------------------------------------------------------------",
        ])

    kit_lines.extend([
        "",
        "=" * 80,
        "[6. UNIVERSAL 6-LAYER AI META-DIRECTOR PROMPT (CÔNG CỤ TẠO THUMBNAIL SÁNG TẠO TỰ DO)]",
        "Hướng dẫn: Copy đoạn Meta-Prompt dưới đây dán vào ChatGPT hoặc Gemini để AI tự do 'flex' thêm vô số",
        "concept độc bản tuân thủ chuẩn 6 Layer chuyên nghiệp:",
        "=" * 80,
        meta_prompt_text,
        "=" * 80,
    ])

    formatted_kit = "\n".join(kit_lines)

    return {
        "title": primary_title,
        "title_options": title_options,
        "description": "\n".join(desc_lines),
        "pinned_comment": pinned_comment_text,
        "tags": base_tags,
        "narrative_chapters": narrative_chapters,
        "thumbnail_concepts": thumbnail_concepts,
        "formatted_kit": formatted_kit,
    }
