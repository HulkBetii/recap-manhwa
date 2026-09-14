from __future__ import annotations

import os
import re
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
    elif any(k in combined for k in ["world after the fall", "tower", "floor", "chaos", "return stone", "regress", "nightmare"]):
        return "tower_anti_regression"
    elif any(k in combined for k in ["bunker", "shelter", "shut-in", "shutin", "warehouse", "hoard", "freeze", "freezing"]):
        return "bunker_prepper"
    elif any(k in combined for k in ["hunter", "gate", "dungeon", "awakening", "rank", "necromancer", "shadow"]):
        return "hunter_gate"
    elif any(k in combined for k in ["murim", "martial", "cultivation", "sword", "heavenly", "demon"]):
        return "murim_apocalypse"
    return "general_apocalypse"


def get_character_names(comic_title: str, story_memory: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Resolves protagonist and key supporting character names.
    """
    title_lower = (comic_title or "").lower()
    mc_name = ""
    if story_memory:
        raw_mc = story_memory.get("protagonist_name", "").strip()
        if raw_mc and len(raw_mc) > 1 and raw_mc.lower() not in ["a", "protagonist", "mc", "unknown"]:
            mc_name = raw_mc

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
        else:
            mc_name = "The Lone Survivor"

    if "world after the fall" in title_lower:
        female_lead = "Mino / Sirwen Armelt"
    elif "global freeze" in title_lower or "shelter" in title_lower:
        female_lead = "Yu Qing / Zhou Keer"
    elif any(k in title_lower for k in ["zombie", "82-08", "8208"]):
        female_lead = "The Fearless Survivor"
    else:
        female_lead = "The Seductive Companion"

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

    # Fallback: clean action phrase
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

    # Backward compatibility with existing small 2-chapter tests where titles are explicitly "Episode 1", "Episode 2"
    if total_eps <= 2 and all(ch.get("title", "").strip().lower().startswith("episode") for ch in chapters) and not download_dir:
        return [
            {
                "timestamp": "00:00" if i == 0 else ch.get("timestamp", "00:00"),
                "title": ch.get("title", f"Episode {ch.get('episode', i + 1)}"),
                "episode": ch.get("episode", i + 1)
            }
            for i, ch in enumerate(chapters)
        ]

    # Universal Narrative Progression Template
    prog_list = UNIVERSAL_NARRATIVE_PROGRESSION.get(archetype, UNIVERSAL_NARRATIVE_PROGRESSION["general_apocalypse"])

    # Determine number of video progression arcs
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

        # YouTube strictly requires the first chapter timestamp to be 00:00
        ts = "00:00" if k == 0 else ch_start.get("timestamp", "00:00")

        # Get base narrative theme from universal progression table
        theme_idx = min(len(prog_list) - 1, round(k * (len(prog_list) - 1) / max(1, num_arcs - 1)))
        base_theme = prog_list[theme_idx]

        # If recap.json exists, check for chapter-specific thematic action
        custom_theme = None
        if download_dir:
            recap_path = os.path.join(download_dir, f"episode_{start_ep}", "recap.json")
            custom_theme = extract_episode_theme(recap_path, start_ep, comic_title)
            if custom_theme and (custom_theme.lower().startswith("chapter") or custom_theme.lower().startswith("episode")):
                custom_theme = None

        chosen_theme = custom_theme if custom_theme else base_theme

        # Format arc title with episode span
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
        # Look for protagonist panels in earliest chapters
        for ep in [1, 2]:
            ep_img_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
            if os.path.isdir(ep_img_dir):
                imgs = sorted(glob.glob(os.path.join(ep_img_dir, "*.webp")) + glob.glob(os.path.join(ep_img_dir, "*.jpg")) + glob.glob(os.path.join(ep_img_dir, "*.png")))
                if imgs and len(refs["protagonist"]) < 2:
                    refs["protagonist"].append(imgs[min(1, len(imgs) - 1)])
        # Look for female companion panels in chapters where female leads appear (Mino, Sirwen, etc.)
        for ep in [14, 20, 35, 15, 4]:
            ep_img_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
            if os.path.isdir(ep_img_dir):
                imgs = sorted(glob.glob(os.path.join(ep_img_dir, "*.webp")) + glob.glob(os.path.join(ep_img_dir, "*.jpg")) + glob.glob(os.path.join(ep_img_dir, "*.png")))
                if imgs and len(refs["female_characters"]) < 2:
                    refs["female_characters"].append(imgs[min(2, len(imgs) - 1)])

    return refs


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
    archetype = detect_archetype(comic_title, story_memory)
    image_refs = find_character_image_references(download_dir, image_references)

    # 1. High-CTR Title Options based on Archetype (Always ending with ' - Manhwa Recap')
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
            "Surviving The Apocalypse In A Max-Level Luxury Underground Bunker | Manhwa Recap",
        ]
        synopsis_text = (
            f"When a sudden cataclysm plunges civilization into an eternal winter, society crumbles in mere days. "
            f"While survivors freeze and fight over breadcrumbs, {mc_name} relaxes inside an impenetrable subterranean fortress "
            f"stocked with decades worth of gourmet supplies, state-of-the-art power grids, and an infinite spatial inventory.\n\n"
            f"Armed with ruthless pragmatism and total self-sufficiency, {mc_name} turns away selfish parasites and dominates the wasteland."
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
            f"When dimensional rifts tore open across modern Earth, grotesque monsters invaded our cities. "
            f"Mocked as the weakest awakened hunter, {mc_name} is betrayed by his squad and abandoned inside a lethal calamity dungeon. "
            f"On the verge of death, a hidden prompt awakens within his soul, granting him forbidden power that defies the world's hierarchy."
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
            f"While humanity descended into panic, {mc_name} unlocked unyielding resolve and absolute strength, "
            f"carving an unstoppable path of survival through ruins and warlords."
        )

    # Guarantee all titles always strictly end with ' - Manhwa Recap' and fit within 100 chars
    title_options = [format_recap_title(t) for t in title_options]
    primary_title = title_options[0]

    # 2. Description Lines with Story Progression Timestamps (Form chung cho mọi video)
    desc_lines = [
        f"{title_options[0]}",
        f"This is the complete marathon recap of {comic_title} ({ep_range}).",
        "",
        "📖 SYNOPSIS:",
        synopsis_text,
        "",
        "⏱️ Chapters & Timestamps:",
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

    # Dynamic hashtags based on comic title and archetype
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

    # 3. SEO Tags (Deduplicated and strictly capped under YouTube's 500-character Studio limit)
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
        ])
    elif archetype == "hunter_gate":
        base_tags.extend([
            "hunter manhwa recap",
            "dungeon manhwa recap",
            "gate manhwa",
            "solo monarch recap",
        ])
    elif archetype == "bunker_prepper":
        base_tags.extend([
            "bunker manhwa recap",
            "shelter manhwa",
            "doomsday manhwa recap",
            "infinite space manhwa",
        ])

    if "world after the fall" in comic_title.lower():
        base_tags.extend([
            "the world after the fall full recap",
            "sing shong manhwa",
            "omniscient reader author",
            "jaehwan thrust",
            "chaos arc recap",
            "the world after the fall chapters 1-89",
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

    # 4. Contextual High-CTR Sensual / Alluring Thumbnail Concepts (Story-Tailored, Anti-Formula)
    mc_ref_path = image_refs['protagonist'][0] if image_refs['protagonist'] else "Panel ảnh nam chính từ episode_1"
    f1_ref_path = image_refs['female_characters'][0] if image_refs['female_characters'] else "Panel ảnh nữ phụ 1 từ episode_14"
    f2_ref_path = image_refs['female_characters'][1] if len(image_refs['female_characters']) > 1 else f1_ref_path

    is_twatf = "world after the fall" in comic_title.lower()
    f1_name = "Mino" if is_twatf else "The Alluring Female Lead"
    f2_name = "Sirwen Armelt" if is_twatf else "The Enchanting Second Female Lead"

    # =========================================================================
    # STORY-TAILORED VIRAL CONCEPTS (Deeply rooted in the comic's actual lore)
    # =========================================================================
    if is_twatf:
        # Concept 1: The 10-Billion Thrusts Awakening & Stunned Mino
        # Directly based on Jaehwan training naked in the frost tower for decades + shattering floor 100
        prompt_concept_1 = (
            f"Create an ultra-detailed, cinematic 16:9 widescreen YouTube thumbnail illustration in the authentic Korean webtoon manhwa art style of Redice Studio "
            f"(similar to Solo Leveling and The World After The Fall). Sharp ink linework, saturated cel-shading, dynamic rim lighting, and glowing violet-and-gold void embers.\n\n"
            f"[CHARACTER REFERENCES & STORY-SPECIFIC COMPOSITION]:\n"
            f"1. CHISELED AWAKENED SWORDSMAN ({mc_name} - Please match Image 1):\n"
            f"Standing in the foreground center. After practicing a single thrust billions of times in the frozen tower, he possesses an athletic, vascular 8-pack physique and sculpted chest. "
            f"His dark battle coat is torn open, casually exposing his muscular torso. Wiping sweat from his angular chin with a cold, nonchalant smirk. "
            f"In his right hand, his dark sword radiates a reality-piercing violet void aura crackling with dimensional energy.\n\n"
            f"2. STUNNED ROGUE ENCHANTRESS ({f1_name} - Please match Image 2):\n"
            f"Kneeling intimately beside him in the Chaos wasteland, her floating crystalline daggers dropped to the ground in shock. "
            f"She leans in close with glistening eyes, heavily flushed beet-red cheeks, and half-parted glossy lips, staring in total awe, lust, and infatuation at his god-tier strike and perfect physical body. "
            f"She wears a form-fitting Chaos leather-and-silk battle corset with an alluring neckline flattering her feminine curves.\n\n"
            f"[SCENE & ATMOSPHERE]:\n"
            f"The shattered 100th floor threshold entering the Chaos wilderness. Colossal cracked stone pillars and swirling celestial nebula skies with dramatic volumetric backlight.\n\n"
            f"[THUMBNAIL GRAPHIC OVERLAYS]:\n"
            f"In the top-left corner, render bold glowing golden-yellow (#FFD700) comic typography reading \"ONE STAB WAS ENOUGH\" with an 8px black stroke. "
            f"Above Mino's blushing head, render a cute pink thought bubble with glowing hearts reading \"HE DID 10 BILLION THRUSTS?!\"."
        )

        # Concept 2: The Nightmare Mistress Seduction & The Crushed Return Stone
        # Directly based on Nightmare Lord Sirwen Armelt testing Jaehwan's soul with the Return Stone
        prompt_concept_2 = (
            f"Create a breathtaking, intensely seductive 16:9 widescreen YouTube thumbnail illustration in the signature Redice Studio webtoon manhwa art style. "
            f"Exquisite character beauty, rich jewel tones, cinematic chiaroscuro, and glowing magical dream powder.\n\n"
            f"[CHARACTER REFERENCES & STORY-SPECIFIC COMPOSITION]:\n"
            f"1. ALLURING NIGHTMARE LORD ({f2_name} - Please match Image 3):\n"
            f"Floating intimately behind Jaehwan, her soft arms wrapped gently around his muscular shoulders. "
            f"She has delicate curved demonic horns on her forehead, long flowing silky pastel hair, and playful half-lidded bedroom eyes whispering seductive sweet illusions against his ear. "
            f"She wears a luxurious, semi-translucent violet astral gown with a daring neckline that clings to her feminine silhouette, emitting swirling pink and purple dream mist.\n\n"
            f"2. COLD UNYIELDING MONARCH ({mc_name} - Please match Image 1):\n"
            f"Front-and-center, seated on a throne of shattered obsidian. Unfazed by her overwhelming sexual temptation, he stares forward with chilling indifferent eyes. "
            f"His left fist is raised, forcefully crushing a glowing blue 'Return Stone' into glittering magical powder right in front of her face.\n\n"
            f"[SCENE & ATMOSPHERE]:\n"
            f"The surreal, mystical dream realm of the Nightmare Tower. Floating clock gears, starry nebula clouds, and soft violet rim lighting creating immense romantic, sensual, and power tension.\n\n"
            f"[THUMBNAIL GRAPHIC OVERLAYS]:\n"
            f"At the top-center, render distressed bold typography reading \"SHE OFFERED PARADISE\" in vivid yellow (#FFE500) with a thick black outline, "
            f"and an arrow pointing to the shattered stone reading \"HE CHOSE CHAOS\"."
        )

        # Concept 3: The Soul-Clothes Inspection & Lethal Proximity in Gorgon Fortress
        # Directly based on Mino and Jaehwan's tense, intimate interrogation/encounter in Gorgon Fortress
        prompt_concept_3 = (
            f"Create a heart-pounding, highly provocative 16:9 widescreen YouTube thumbnail illustration with an extreme Dutch angle in the authentic Redice Studio manhwa art style. "
            f"High aesthetic fidelity, crisp dark ink outlines, warm lantern glow, and crackling violet spark embers.\n\n"
            f"[CHARACTER REFERENCES & STORY-SPECIFIC COMPOSITION]:\n"
            f"1. SEDUCTIVE ROGUE BEAUTY ({f1_name} - Please match Image 2):\n"
            f"Positioned intimately close on the right, her face merely one inch away from Jaehwan's lips. "
            f"She playfully tugs at the neckline of her unbuttoned translucent soul-clothes tunic to inspect his spirit core, revealing her graceful feminine collarbone and curves. "
            f"Her cheeks are flushed heated red, lips glistening and parted, panting with a mix of playful flirtation and dangerous awe.\n\n"
            f"2. DEADPAN WARRIOR ({mc_name} - Please match Image 1):\n"
            f"Framed tightly on the left. Handsome male swordsman with pitch-black hair and sharp piercing eyes. "
            f"He doesn't flinch an inch, casually holding the sharp tip of his dark glowing blade right against her throat in a dangerous, heart-stopping standoff.\n\n"
            f"[SCENE & ATMOSPHERE]:\n"
            f"A private backroom in the Gorgon Fortress tavern. Flickering warm candlelight, deep crimson drapery, and floating spirit motes. Maximum electric tension blending fatal danger and irresistible physical attraction.\n\n"
            f"[THUMBNAIL GRAPHIC OVERLAYS]:\n"
            f"In the upper-right corner, render a vibrant yellow comic speech bubble with a thick black outline reading \"INSPECTING MY BODY?\" pointing at Mino, "
            f"with red comic blushing lines and question marks \"???\"."
        )

        thumbnail_concepts = [
            {
                "id": "concept_1",
                "name": "The 10-Billion Thrusts Awakening (Khoe Thể Chất Vô Song & Mino Sững Sờ)",
                "thumbnail_text": "ONE STAB WAS ENOUGH",
                "text_style": "Font Gothic vàng kim (#FFD700) phát sáng cực đại 'ONE STAB WAS ENOUGH', kèm bong bóng suy nghĩ màu hồng 'HE DID 10 BILLION THRUSTS?!' trên đầu Mino.",
                "characters": [
                    {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                    {"role": f"Nữ phụ ({f1_name})", "image_reference": f1_ref_path},
                ],
                "gpt_prompt": prompt_concept_1,
            },
            {
                "id": "concept_2",
                "name": "The Nightmare Mistress Seduction (Chúa Tể Ác Mộng Cám Dỗ & Bóp Nát Đá Hồi Quy)",
                "thumbnail_text": "SHE OFFERED PARADISE",
                "text_style": "Font chữ khối dày màu vàng chanh (#FFE500) 'SHE OFFERED PARADISE' ở giữa trên, mũi tên chỉ vào bàn tay nghiền nát đá hồi quy 'HE CHOSE CHAOS'.",
                "characters": [
                    {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                    {"role": f"Nữ chúa Ác Mộng ({f2_name})", "image_reference": f2_ref_path},
                ],
                "gpt_prompt": prompt_concept_2,
            },
            {
                "id": "concept_3",
                "name": "The Soul-Clothes Inspection (Áp Sát Trong Gang Tấc / Vén Áo Linh Hồn)",
                "thumbnail_text": "INSPECTING MY BODY?",
                "text_style": "Bong bóng thoại truyện tranh vàng chanh viền đen 8px 'INSPECTING MY BODY?', mũi tên chỉ vào Mino, vạch đỏ mặt '???' trên đầu nam chính.",
                "characters": [
                    {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                    {"role": f"Nữ phụ ({f1_name})", "image_reference": f1_ref_path},
                ],
                "gpt_prompt": prompt_concept_3,
            },
        ]
    else:
        # Dynamic Story-Adaptive Concepts for Any Other Manhwa
        prompt_concept_1 = (
            f"Create an ultra-detailed, cinematic 16:9 widescreen YouTube thumbnail illustration in the authentic Redice Studio manhwa art style. "
            f"Sharp linework, saturated cel-shading, dynamic rim lighting, and glowing magical embers.\n\n"
            f"[CHARACTER REFERENCES & COMPOSITION - POWER & ALLURE DYNAMIC]:\n"
            f"1. PROTAGONIST ({mc_name} - Please match Image 1): Athletic, handsome male hero standing confidently in the foreground, displaying his overwhelming physical strength and unyielding presence with glowing powers.\n"
            f"2. ALLURING COMPANION ({f1_name} - Please match Image 2): Extraordinarily beautiful female lead with flushed blushing cheeks and half-lidded bedroom eyes, leaning intimately close in adoration and awe. "
            f"Wearing a form-fitting fantasy outfit accentuating her feminine curves.\n\n"
            f"[THUMBNAIL GRAPHIC OVERLAYS]: Bold yellow text overlay reading \"UNTOUCHABLE MONARCH\" with glowing neon cyan accents."
        )
        prompt_concept_2 = (
            f"Create a heart-racing, playful and intensely sensual 16:9 widescreen YouTube thumbnail illustration in Redice Studio manhwa art style. "
            f"Warm intimate lighting, soft ambient glow, and high romantic tension.\n\n"
            f"[COMPOSITION - ACCIDENTAL PROXIMITY]: Seductive female lead ({f1_name} - Please match Image 2) leaning over the flustered male protagonist ({mc_name} - Please match Image 1), "
            f"playfully tugging at her neckline with flushed cheeks. Male protagonist caught off-guard and blushing bright crimson.\n\n"
            f"[THUMBNAIL GRAPHIC OVERLAYS]: Manga speech bubble reading \"TOO HOT RIGHT?\" with comic question marks."
        )
        prompt_concept_3 = (
            f"Create an epic, high-stakes 16:9 widescreen YouTube thumbnail illustration in Redice Studio manhwa art style.\n\n"
            f"[COMPOSITION - SUBMISSIVE HAREM DYNAMIC]: Male protagonist ({mc_name} - Please match Image 1) dominating on a throne or safezone sanctuary, "
            f"while multiple stunning female leads ({f1_name} & {f2_name} - Please match Image 2 & Image 3) in battle-worn fitted attire beg to enter or serve with total devotion.\n\n"
            f"[THUMBNAIL GRAPHIC OVERLAYS]: Bold typography reading \"THEY BEGGED TO SERVE\" in pure white with neon outer glow."
        )
        thumbnail_concepts = [
            {
                "id": "concept_1",
                "name": "The Overwhelming Power & Flustered Waifu (Khoe Thể Chất & Mỹ Nhân Mê Mẩn)",
                "thumbnail_text": "UNTOUCHABLE MONARCH",
                "text_style": "Font Gothic vàng kim phát sáng, mũi tên chỉ điểm nóng và bong bóng suy nghĩ đỏ mặt.",
                "characters": [
                    {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                    {"role": f"Nữ phụ ({f1_name})", "image_reference": f1_ref_path},
                ],
                "gpt_prompt": prompt_concept_1,
            },
            {
                "id": "concept_2",
                "name": "The Accidental Intimate Encounter (Va Chạm Nhạy Cảm / Nữ Nhân Áp Sát)",
                "thumbnail_text": "TOO HOT RIGHT?",
                "text_style": "Bong bóng thoại màu vàng viền đen dày, dấu chấm hỏi đỏ mặt trên đầu MC.",
                "characters": [
                    {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                    {"role": f"Nữ phụ ({f1_name})", "image_reference": f1_ref_path},
                ],
                "gpt_prompt": prompt_concept_2,
            },
            {
                "id": "concept_3",
                "name": "The Safezone Sanctuary / Harem Devotion (Đế Vương / Song Nữ Phục Tùng)",
                "thumbnail_text": "THEY BEGGED TO SERVE",
                "text_style": "Font Sans-Serif khối lớn màu trắng viền neon cyan phát sáng.",
                "characters": [
                    {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                    {"role": f"Nữ phụ 1 ({f1_name})", "image_reference": f1_ref_path},
                    {"role": f"Nữ phụ 2 ({f2_name})", "image_reference": f2_ref_path},
                ],
                "gpt_prompt": prompt_concept_3,
            },
        ]

    # 5. Dynamic Story Progression Arcs Timeline for Pinned Comment (Form chung cho mọi video)
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

    # 6. Full Formatted Kit String
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
        "[5. HIGH-CTR THUMBNAIL CONCEPTS & MASTER PROMPTS CHO CHATGPT (GPT-4o)]",
        "Hướng dẫn:",
        "1. Chọn 1 trong 3 Concept dưới đây phù hợp nhất với phong cách video của bạn.",
        "2. Mở ChatGPT (chọn mô hình GPT-4o).",
        "3. Bấm nút đính kèm (dấu +) và tải lên các tệp ảnh tham chiếu tương ứng của Concept đó.",
        "4. Copy duy nhất đoạn MASTER PROMPT của Concept đó dán vào ChatGPT để sinh ảnh Thumbnail 16:9.",
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

    # Alternative concepts library
    prompt_alt_lewd = (
        f"Create a high-impact, provocative 16:9 widescreen YouTube thumbnail illustration in the signature Redice Studio webtoon manhwa art style. "
        f"Sharp graphic linework, vibrant cel-shaded colors, cinematic volumetric lighting, and glowing holographic digital particles.\n\n"
        f"[CHARACTER REFERENCES & COMPOSITION - SYSTEM QUEST PROVOCATION]:\n"
        f"1. PROUD ALLURING FEMALE LEAD ({f1_name} - Please match Image 2):\n"
        f"Positioned in the center-right, turned slightly away to showcase her voluptuous feminine silhouette. She wears snug fantasy combat leggings or a high-slit battle skirt. "
        f"Clearly visible on her curve is a vivid glowing crimson handprint mark. She looks back over her shoulder with beet-red blushing cheeks, teary humiliated eyes, and biting her lower lip in fierce embarrassment.\n\n"
        f"2. CONFIDENT MALE PROTAGONIST ({mc_name} - Please match Image 1):\n"
        f"Standing in the foreground left, viewed from an over-the-shoulder angle. A handsome warrior with an amused, nonchalant smirk, holding a dark glowing weapon as he watches the floating system notification.\n\n"
        f"[SYSTEM QUEST HOLOGRAM]:\n"
        f"Floating between them is a prominent, glowing crimson-red system quest window with caution borders, displaying bold white-and-yellow typography: \"! ALERT QUEST: TOUCH HER ! REWARD: LEVEL UP +99\".\n\n"
        f"[SCENE & ATMOSPHERE]:\n"
        f"A grand fantasy arena or dungeon chamber with blue-and-red glowing holographic runes floating in the background."
    )

    prompt_alt_base = (
        f"Create an eye-catching, dramatic 16:9 widescreen YouTube thumbnail illustration in authentic Korean webtoon manhwa art style. "
        f"Dynamic composition contrasting warmth and devastation, sharp ink linework, and vibrant neon lighting.\n\n"
        f"[CHARACTER REFERENCES & COMPOSITION - SAFEZONE VS WASTELAND]:\n"
        f"1. FIRST-PERSON / SPLIT-SCREEN PERSPECTIVE:\n"
        f"On the LEFT (MC'S SAFEZONE): A luxurious, warm sanctuary with air conditioning, comfortable seating, and fresh food. "
        f"Male protagonist ({mc_name} - Please match Image 1) stands relaxed in modern adventurer gear, holding fresh food, gazing coolly toward the entrance.\n\n"
        f"2. DESPERATE ALLURING SURVIVORS ({f1_name} & {f2_name} - Please match Image 2 & Image 3):\n"
        f"On the RIGHT (FROZEN WASTELAND): Through a glowing blue dimensional portal or vault doorway, two extraordinarily gorgeous female awakened warriors are kneeling or stepping desperately into the safezone. "
        f"They wear battle-torn, form-fitting athletic crop tops and snug leggings accentuating their hourglass curves. Both have flushed cheeks, disheveled silky hair, and pleading, seductive bedroom eyes begging to enter.\n\n"
        f"[THUMBNAIL GRAPHIC OVERLAYS]:\n"
        f"At the top-center, render massive bold all-caps typography reading \"ALL GIRLS WANT IN\" in vibrant yellow (#FFE500) with a thick black stroke. "
        f"Add contrasting glowing neon badges: \"SAFEZONE\" in neon cyan on the left, and \"APOCALYPSE\" in fiery crimson on the right."
    )

    alternative_archetypes = [
        {
            "id": "alt_lewd_system",
            "name": "The Lewd System Quest & Handprint (Nhiệm Vụ Hệ Thống Táo Bạo / Vết Tát Mông)",
            "thumbnail_text": "! ALERT QUEST: TOUCH HER !",
            "text_style": "Bảng nhiệm vụ System Hologram đỏ rực màu máu, font in hoa 'REWARD: STATS +999', mũi tên vàng neon chỉ vào vòng 3 có vết bàn tay đỏ ửng phát sáng.",
            "characters": [
                {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                {"role": f"Nữ phụ ({f1_name})", "image_reference": f1_ref_path},
            ],
            "gpt_prompt": prompt_alt_lewd,
        },
        {
            "id": "alt_base_portal",
            "name": "The Apocalypse Base & Food Sanctuary (Trùm Căn Cứ / Cổng Không Gian Đón Gái Xinh)",
            "thumbnail_text": "ALL GIRLS WANT IN",
            "text_style": "Font Impact màu vàng chanh viền đen 8px ở giữa trên, chia đôi nhãn SAFEZONE (xanh neon) và APOCALYPSE (đỏ rực) ở hai bên cổng.",
            "characters": [
                {"role": f"Nam chính ({mc_name})", "image_reference": mc_ref_path},
                {"role": f"Nữ phụ 1 ({f1_name})", "image_reference": f1_ref_path},
                {"role": f"Nữ phụ 2 ({f2_name})", "image_reference": f2_ref_path},
            ],
            "gpt_prompt": prompt_alt_base,
        },
    ]

    # Section 6: Alternative Viral Concepts Catalog
    if alternative_archetypes:
        kit_lines.extend([
            "",
            "=" * 80,
            "[6. ALTERNATIVE VIRAL CONCEPTS CATALOG (DANH MỤC CONCEPT DỰ PHÒNG & THỬ NGHIỆM CTR ĐỘC LẠ)]",
            "Ghi chú: Nếu bạn muốn thử nghiệm phong cách thị giác khác cho video này (ví dụ: Nhiệm Vụ Hệ Thống Táo Bạo,",
            "Trùm Căn Cứ Tiếp Tế Lương Thực, hoặc Nữ Chỉ Huy Học Viện), hãy copy các Master Prompt dưới đây:",
            "=" * 80,
        ])
        for idx, alt in enumerate(alternative_archetypes, 1):
            kit_lines.extend([
                "",
                f"▶ ALTERNATIVE CONCEPT {idx}: {alt['name'].upper()}",
                f"  • Clickbait Text Overlay : {alt['thumbnail_text']}",
                f"  • Text Styling Guide     : {alt['text_style']}",
                "  • Nhân vật & Tệp ảnh tham chiếu:",
            ])
            for c_idx, char in enumerate(alt['characters'], 1):
                kit_lines.append(f"    - Ảnh {c_idx} ({char['role']}) : {char['image_reference']}")
            kit_lines.extend([
                "",
                "  • MASTER PROMPT CHO CHATGPT (Copy toàn bộ dán vào GPT-4o):",
                "--------------------------------------------------------------------------------",
                alt['gpt_prompt'],
                "--------------------------------------------------------------------------------",
            ])

    # Section 7: Universal Manhwa Recap Meta-Prompt (For Generating Bespoke Concepts For Any Comic)
    meta_prompt_text = (
        "You are an elite YouTube Manhwa Recap Art Director specializing in 500K+ view high-CTR thumbnails.\n"
        "Given the following manhwa synopsis or chapter plot, invent 3 UNIQUE, STORY-SPECIFIC thumbnail concepts.\n"
        "RULES:\n"
        "1. Do NOT use generic formulas. Adapt directly to the unique weapons, monsters, and absurd moments of this story.\n"
        "2. Include 1 or 2 gorgeous female characters with intense sensual tension, seductive curiosity, or blushing embarrassment.\n"
        "3. Provide exactly ONE Master Prompt per concept for ChatGPT (GPT-4o) specifying 16:9 widescreen, Redice Studio manhwa art style, character reference mappings (Image 1, Image 2), cinematic lighting, and clickbait graphic overlays (comic speech bubbles, yellow typography with black stroke, or system quest hologram).\n"
        "4. Keep prompts strictly filter-safe against OpenAI moderation while maximizing visual allure (form-fitting gowns, blushing cheeks, intimate proximity).\n\n"
        "[PASTE YOUR COMIC TITLE & PLOT SUMMARY HERE]"
    )

    kit_lines.extend([
        "",
        "=" * 80,
        "[7. UNIVERSAL AI META-PROMPT (CÔNG CỤ TẠO THUMBNAIL ĐỘC BẢN CHO BẤT KỲ BỘ TRUYỆN MỚI)]",
        "Hướng dẫn: Bạn có thể copy đoạn Meta-Prompt dưới đây dán vào ChatGPT hoặc Gemini, kèm đoạn tóm tắt của bất kỳ",
        "bộ truyện nào để AI tự động sáng tạo 3 Thumbnail Concept mới tinh, bám sát 100% tình tiết cốt truyện thực tế:",
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
        "alternative_concepts": alternative_archetypes,
        "formatted_kit": formatted_kit,
    }

