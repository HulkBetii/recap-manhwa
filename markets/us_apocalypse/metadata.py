from __future__ import annotations

import json
import os
import re
import glob
import math
from typing import Dict, Any, List, Optional, Tuple


# =============================================================================
# RESEARCH-VALIDATED CONSTANTS
# Based on: deep-research-report.md & Manhwa Recap Channel Analysis.md
# =============================================================================

# Title formula templates — data-driven, story-adaptive
# Structure: [Disadvantage/Threat] + [OP Resolution/Resource] | Manhwa Recap
# Target length: 80-95 chars (research validated: mean ~91, median ~93)
TITLE_FORMULA_TEMPLATES = {
    "resource_monopoly": [
        "Everyone Is {suffering}, But He Has {advantage} After the {disaster} | Manhwa Recap",
        "{disaster} Hit and EVERYONE Lost {scarce_thing}, But He Had {advantage} | Manhwa Recap",
        "The World Ran Out of {scarce_thing}, But He Controls the ONLY {advantage} | Manhwa Recap",
    ],
    "preparation_advantage": [
        "He KNEW the {disaster} Was Coming and Built {fortress} | Manhwa Recap",
        "They Called Him INSANE for {prep_action}, Until the {disaster} Hit | Manhwa Recap",
        "He Spent {time_span} Preparing for {disaster} That ACTUALLY Happened | Manhwa Recap",
    ],
    "climate_disaster": [
        "The World Reaches {extreme_temp}, But His {shelter} Has {resource} | Manhwa Recap",
        "{extreme_condition} Wiped Out EVERYONE, But He Had {secret_advantage} | Manhwa Recap",
    ],
    "class_reversal": [
        "Everyone Picked {obvious_class}, But His '{trash_class}' Controls All {resource} | Manhwa Recap",
        "His '{trash_class}' Was WORTHLESS Until the {disaster} Made It STRONGEST | Manhwa Recap",
    ],
    "regression_return": [
        "He DIES in the {disaster} and Returns {time_before} Before Everyone Else | Manhwa Recap",
        "BETRAYED at Level {level}, He REGRESSED {time_span} to DESTROY Them All | Manhwa Recap",
    ],
    "betrayal_revenge": [
        "He Was BETRAYED by {betrayer}, But Awakened {power} | Manhwa Recap",
        "They Left Him for DEAD in {danger_zone}, But He Came Back as {title} | Manhwa Recap",
    ],
    "system_awakening": [
        "He Awakened a BROKEN {system_name} That Turns {weak_thing} Into {strong_thing} | Manhwa Recap",
        "Everyone Got {common_power}, But His GLITCHED System Gives {op_ability} | Manhwa Recap",
    ],
    "lone_survivor": [
        "He Is the ONLY Survivor of {disaster} and Now Controls {advantage} | Manhwa Recap",
        "{disaster} Wiped Out 99% of Humanity, But He Thrives With {advantage} | Manhwa Recap",
    ],
}

# Engagement questions for pinned comments — per archetype
# (Research: top channels use pinned debate questions to inflate comment velocity)
ENGAGEMENT_QUESTIONS = {
    "zombie_apocalypse": [
        "What's more dangerous — the zombies or the other survivors? Drop your take below! 👇",
        "Would YOU open the door for strangers during the apocalypse? Be honest 👀",
        "What's the FIRST weapon you'd grab in a zombie outbreak? 🧟",
    ],
    "bunker_prepper": [
        "What's the #1 supply you'd stockpile FIRST — food, water, weapons, or medicine? 🤔",
        "His prep level is INSANE — but what would YOU add to the bunker? 👇",
        "Would you let strangers into your shelter if they had useful skills? Be honest 👀",
    ],
    "tower_anti_regression": [
        "Would YOU refuse to regress if everyone else already went back? 🤔",
        "What's more terrifying — the Tower or the Chaos beyond it? Drop your answer! 👇",
    ],
    "hunter_gate": [
        "If you could awaken ONE ability from this story, which would you pick? 💪",
        "Solo hunting or guild raids — which strategy would YOU choose? 🤔",
    ],
    "game_system_reality": [
        "If your favorite game suddenly became REAL, would you survive? Be honest 👀",
        "What game skill would be most broken in real life? Drop your pick below! 🎮",
    ],
    "regression_prep": [
        "If you could go back 30 days before a disaster, what's your FIRST move? ⏪",
        "Is future knowledge or an OP system the bigger advantage? Debate below! 👇",
    ],
    "farming_kingdom": [
        "Food or military power — which is more important after the apocalypse? 🌾⚔️",
        "Would you rather build a kingdom or stay a lone wolf? Drop your answer! 👇",
    ],
    "murim_apocalypse": [
        "Which martial art style would be most effective in a real apocalypse? 🥋",
        "Inner peace or raw power — what matters more in survival? 🤔",
    ],
    "general_apocalypse": [
        "What's the ONE thing you'd want in an apocalypse? Drop your answer below! 👇",
        "Could YOU survive the first 7 days of this apocalypse? Be honest 👀",
    ],
}

# Survival Dashboard template — original editorial overlay concept
# (Research: strengthens YPP compliance as "original editorial content" evidence)
SURVIVAL_DASHBOARD_FIELDS = [
    "day_number",
    "food_reserve_pct",
    "water_reserve_pct",
    "power_status",
    "outside_condition",
    "base_security_level",
    "threat_description",
    "mc_level",
    "party_size",
]


# =============================================================================
# ARCHETYPE DETECTION — Expanded with 3 new content lanes
# =============================================================================

def detect_archetype(comic_title: str, story_memory: Optional[Dict[str, Any]] = None) -> str:
    """
    Detects the manhwa archetype/subgenre for tailored metadata generation.
    Expanded with 3 new archetypes based on 2026 market research:
    - game_system_reality (20% content lane)
    - regression_prep (10% content lane)
    - farming_kingdom (10% content lane)
    """
    title_lower = (comic_title or "").lower()
    mem_text = ""
    if story_memory:
        mem_text = str(story_memory).lower()

    combined = f"{title_lower} {mem_text}"

    # Priority 1: Direct comic title & explicit theme matching
    if "world after the fall" in title_lower:
        return "tower_anti_regression"
    if "surviving the apocalypse" in title_lower or "bunker" in title_lower or "apocalypse from the start" in title_lower:
        return "bunker_prepper"

    # Priority 2: Specific token groups (ordered by specificity)
    if any(k in combined for k in ["zombie", "infected", "undead", "ghoul", "plague", "virus", "outbreak", "82-08", "8208", "walking dead"]):
        return "zombie_apocalypse"
    elif any(k in combined for k in ["bunker", "shelter", "prepper", "shut-in", "shutin", "warehouse", "hoard"]):
        return "bunker_prepper"
    elif any(k in combined for k in ["freeze", "freezing", "frozen", "frost", "ice age", "eternal winter", "blizzard"]):
        return "bunker_prepper"
    elif any(k in combined for k in ["return stone", "regression stone", "floor 100", "chaos wasteland", "anti-regression", "world after the fall"]):
        return "tower_anti_regression"
    # NEW: Game/System becomes reality (20% content lane — research validated)
    elif any(k in combined for k in ["game become", "vr game", "game reality", "virtual reality", "player", "npc", "game world", "logged in", "tutorial"]):
        return "game_system_reality"
    # NEW: Regression / Time preparation (10% content lane)
    elif any(k in combined for k in ["regression", "regress", "second chance", "time travel", "rewind", "went back", "returned to", "before the apocalypse"]):
        return "regression_prep"
    # NEW: Farming / Kingdom building (10% content lane)
    elif any(k in combined for k in ["farming", "kingdom", "territory", "village", "build", "agriculture", "lord", "baron", "domain", "settlement"]):
        return "farming_kingdom"
    elif any(k in combined for k in ["hunter", "gate", "dungeon", "awakening", "rank", "necromancer", "shadow"]):
        return "hunter_gate"
    elif any(k in combined for k in ["murim", "martial", "cultivation", "heavenly demon", "mount hua"]):
        return "murim_apocalypse"
    return "general_apocalypse"


# =============================================================================
# CHARACTER NAME RESOLUTION
# =============================================================================

def get_character_names(comic_title: str, story_memory: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Resolves protagonist and key supporting character names."""
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
        female_lead = "The Female Lead"

    return {
        "mc": mc_name,
        "female_lead": female_lead
    }


# =============================================================================
# EPISODE THEME EXTRACTION
# =============================================================================

def extract_episode_theme(recap_path: str, ep: int, comic_title: str = "") -> str:
    """Extracts a punchy, dramatic narrative theme for an episode from its recap.json."""
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
    clean_theme = re.sub(r"[^a-zA-Z0-9\s\-–—\':,]", "", clean_theme).strip()
    return clean_theme if len(clean_theme) > 3 else f"Chapter {ep}"


# =============================================================================
# NARRATIVE PROGRESSION TEMPLATES — Expanded with 3 new archetypes
# =============================================================================

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
    "game_system_reality": [
        "The Game Becomes Real & First Login",
        "Tutorial Zone & The Glitched Ability",
        "First Boss Encounter & Level Breakthrough",
        "NPC Allies & Hidden Quest Chain",
        "The PvP Arena & Rival Players",
        "Dungeon Raid & Legendary Drop",
        "The Admin's Secret & World Event",
        "Guild War & Territory Conquest",
        "Final Boss & System Collapse",
        "New Game+ & The True Ending",
    ],
    "regression_prep": [
        "Death & The Rewind Trigger",
        "30 Days Before Doomsday & Stockpiling",
        "Building The Ultimate Base",
        "The Apocalypse Strikes & Everyone Panics",
        "Resource Wars & Desperate Survivors",
        "Revealing Future Knowledge & Allies",
        "The First Major Threat Returns",
        "Changing The Timeline & New Dangers",
        "Confronting The True Enemy",
        "Breaking The Loop & Dawn of Control",
    ],
    "farming_kingdom": [
        "Exiled To Worthless Land",
        "First Harvest & System Activation",
        "Recruiting Followers & Village Defense",
        "The Merchant Route & Economic Warfare",
        "Noble Rivals & Political Intrigue",
        "Monster Siege & Wall Fortification",
        "Alliance Formation & Trade Empire",
        "The Royal Summons & Kingdom Recognition",
        "War Declaration & Total Mobilization",
        "Emperor's Domain & Continental Influence",
    ],
    "murim_apocalypse": [
        "The Fall of the Sect & Lone Survivor",
        "Training in Isolation & Forbidden Technique",
        "Return to the Martial World & First Duel",
        "The Underground Tournament & Blood Pact",
        "Sect Infiltration & The Traitor Revealed",
        "The Demonic Faction Rising",
        "Alliance of Sects & The War Council",
        "The Decisive Battle & Heavenly Technique",
        "Confronting The Heavenly Demon",
        "New Era of Martial Arts & Legacy",
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


# =============================================================================
# STORY CHAPTER BUILDER
# =============================================================================

def build_narrative_story_chapters(
    chapters: Optional[List[Dict[str, Any]]],
    download_dir: Optional[str] = None,
    comic_title: str = "Comic",
    archetype: str = "general_apocalypse",
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[Dict[str, Any]]:
    """
    Builds narrative story chapters grouped by video story progression arcs.
    Ensures the first chapter is strictly 00:00 and chapters represent key narrative acts.
    """
    if not chapters:
        prog_list = UNIVERSAL_NARRATIVE_PROGRESSION.get(archetype, UNIVERSAL_NARRATIVE_PROGRESSION["general_apocalypse"])
        return [
            {"timestamp": "00:00", "title": prog_list[0], "episode": from_ep},
            {"timestamp": "05:00", "title": prog_list[1], "episode": from_ep + 1},
            {"timestamp": "15:00", "title": prog_list[len(prog_list)//2], "episode": from_ep + 2},
            {"timestamp": "30:00", "title": prog_list[-1], "episode": to_ep},
        ]

    total_eps = len(chapters)

    # Backward compatibility with small 2-chapter tests
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
        title = f"{chosen_theme} ({ep_label})"

        result.append({
            "timestamp": ts,
            "title": title,
            "episode": start_ep,
            "end_episode": end_ep,
            "theme": chosen_theme,
        })

    return result


# =============================================================================
# TITLE ENGINE — Dynamic generation from story data
# =============================================================================

# Research-validated target: 80-95 chars (mean ~91, median ~93)
TITLE_TARGET_MAX = 95
TITLE_HARD_MAX = 100
TITLE_SUFFIX = " | Manhwa Recap"


def format_recap_title(base_title: str, suffix: str = TITLE_SUFFIX) -> str:
    """
    Ensures the title ends with ' | Manhwa Recap' and fits within the
    research-validated 80-95 char target (hard max 100).
    """
    cleaned = base_title.strip()
    if cleaned.lower().endswith("manhwa recap"):
        cleaned = re.sub(r"[\s\-\|]+manhwa recap$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(" -|")
    target = f"{cleaned}{suffix}"
    if len(target) > TITLE_HARD_MAX:
        max_base_len = TITLE_HARD_MAX - len(suffix)
        cleaned = cleaned[:max_base_len].rstrip(" .,-|")
        return f"{cleaned}{suffix}"
    return target


def _extract_story_beats(
    comic_title: str,
    archetype: str,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> Dict[str, str]:
    """
    Extracts actual story beats from recap.json and story_memory for dynamic
    title template filling. Returns a dict of template variables.
    """
    beats: Dict[str, str] = {}
    title_lower = (comic_title or "").lower()
    mc_name = get_character_names(comic_title, story_memory)["mc"]
    beats["mc_name"] = mc_name

    # Extract from story_memory
    if story_memory:
        # Disaster type
        mem_text = str(story_memory).lower()
        if any(k in mem_text for k in ["zombie", "infected", "undead", "outbreak"]):
            beats["disaster"] = "Zombie Apocalypse"
            beats["scarce_thing"] = "Safe Shelter"
        elif any(k in mem_text for k in ["freeze", "frozen", "frost", "ice", "cold"]):
            beats["disaster"] = "Global Freeze"
            beats["scarce_thing"] = "Heat and Power"
            beats["extreme_temp"] = "-60°F"
            beats["extreme_condition"] = "The Eternal Frost"
        elif any(k in mem_text for k in ["heat", "solar", "burning", "melt"]):
            beats["disaster"] = "Solar Apocalypse"
            beats["scarce_thing"] = "Water"
            beats["extreme_temp"] = "120°F"
            beats["extreme_condition"] = "The Solar Inferno"
        elif any(k in mem_text for k in ["mutant", "monster", "creature", "beast"]):
            beats["disaster"] = "Mutant Apocalypse"
            beats["scarce_thing"] = "Safe Territory"

        # Protagonist advantages
        if any(k in mem_text for k in ["bunker", "shelter", "vault", "fortress"]):
            beats["advantage"] = "an IMPENETRABLE Bunker"
            beats["fortress"] = "an IMPENETRABLE Underground Fortress"
            beats["shelter"] = "Bunker"
        if any(k in mem_text for k in ["spatial", "inventory", "storage", "dimensional"]):
            beats["advantage"] = "an INFINITE Dimensional Warehouse"
        if any(k in mem_text for k in ["stockpile", "hoard", "supply", "supplies", "food"]):
            beats["advantage"] = "UNLIMITED Supplies"
            beats["resource"] = "Food"
        if any(k in mem_text for k in ["system", "window", "quest", "level"]):
            beats["system_name"] = "System"
        if any(k in mem_text for k in ["regress", "return", "rewind", "went back"]):
            beats["time_before"] = "30 Days"
            beats["time_span"] = "5 Years"

        # Betrayer
        if any(k in mem_text for k in ["betray", "betrayed", "abandon", "left for dead"]):
            beats["betrayer"] = "His Own Allies"

        # Protagonist preparation
        if any(k in mem_text for k in ["train", "trained", "years", "decades"]):
            beats["time_span"] = "16 Years"
            beats["prep_action"] = "Building a Doomsday Bunker"

    # Title-based fallback extraction
    if "disaster" not in beats:
        if "zombie" in title_lower or "82-08" in title_lower:
            beats["disaster"] = "Zombie Apocalypse"
        elif "freeze" in title_lower or "frozen" in title_lower or "frost" in title_lower:
            beats["disaster"] = "Global Freeze"
        elif "apocalypse" in title_lower:
            beats["disaster"] = "Apocalypse"
        elif "tower" in title_lower or "floor" in title_lower:
            beats["disaster"] = "Tower Collapse"
        elif "dungeon" in title_lower or "gate" in title_lower:
            beats["disaster"] = "Dungeon Break"
        else:
            beats["disaster"] = "Apocalypse"

    # Archetype-based defaults
    archetype_defaults = {
        "zombie_apocalypse": {
            "suffering": "STARVING and Infected", "scarce_thing": "Safe Shelter",
            "advantage": "a FORTIFIED Base", "fortress": "an Unbreakable Fortress",
        },
        "bunker_prepper": {
            "suffering": "FREEZING to Death", "scarce_thing": "Food and Heat",
            "advantage": "UNLIMITED Supplies", "fortress": "a MAX-Level Underground Bunker",
            "prep_action": "Hoarding 50,000 Tons of Supplies", "time_span": "16 Years",
        },
        "tower_anti_regression": {
            "suffering": "Trapped in the Tower", "scarce_thing": "Hope",
            "advantage": "a REALITY-PIERCING Thrust", "power": "the Power to Break Reality",
        },
        "hunter_gate": {
            "suffering": "Left for Dead", "scarce_thing": "Strength",
            "advantage": "a GLITCHED God-Tier Ability", "power": "an SSS-RANK Awakening",
        },
        "game_system_reality": {
            "suffering": "Defenseless", "scarce_thing": "Real Combat Skills",
            "advantage": "10,000 Hours of Game Experience", "system_name": "Game System",
            "weak_thing": "Game Knowledge", "strong_thing": "Real-World Power",
        },
        "regression_prep": {
            "suffering": "Dying in the Apocalypse", "scarce_thing": "Time",
            "advantage": "Complete Future Knowledge", "time_before": "30 Days",
            "time_span": "5 Years",
        },
        "farming_kingdom": {
            "suffering": "EXILED to Worthless Land", "scarce_thing": "Resources",
            "advantage": "a BROKEN Farming System", "trash_class": "Farming",
            "obvious_class": "Combat Classes", "resource": "Food",
        },
        "general_apocalypse": {
            "suffering": "DYING", "scarce_thing": "Safety",
            "advantage": "an OVERPOWERED Ability",
        },
    }
    defaults = archetype_defaults.get(archetype, archetype_defaults["general_apocalypse"])
    for key, val in defaults.items():
        if key not in beats:
            beats[key] = val

    return beats


def _select_title_families(archetype: str) -> List[str]:
    """Returns the ordered list of title formula families best suited for the archetype."""
    family_map = {
        "zombie_apocalypse": ["resource_monopoly", "preparation_advantage", "lone_survivor", "betrayal_revenge"],
        "bunker_prepper": ["preparation_advantage", "resource_monopoly", "climate_disaster", "lone_survivor"],
        "tower_anti_regression": ["betrayal_revenge", "lone_survivor", "system_awakening"],
        "hunter_gate": ["betrayal_revenge", "system_awakening", "lone_survivor"],
        "game_system_reality": ["system_awakening", "class_reversal", "lone_survivor"],
        "regression_prep": ["regression_return", "preparation_advantage", "resource_monopoly"],
        "farming_kingdom": ["class_reversal", "resource_monopoly", "lone_survivor"],
        "murim_apocalypse": ["betrayal_revenge", "lone_survivor", "system_awakening"],
        "general_apocalypse": ["resource_monopoly", "lone_survivor", "betrayal_revenge", "system_awakening"],
    }
    return family_map.get(archetype, family_map["general_apocalypse"])


def generate_dynamic_titles(
    comic_title: str,
    archetype: str,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[str]:
    """
    Generates data-driven title options by extracting actual story beats
    and filling validated title formula templates.

    Research basis:
    - Target 80-95 chars (deep-research-report.md: mean ~91, median ~93)
    - Selective CAPS for 2-6 power words only
    - Pronouns > IP names for Browse/Suggested discovery
    - Structure: [Disadvantage/Threat] + [OP Resolution] | Manhwa Recap
    """
    beats = _extract_story_beats(comic_title, archetype, story_memory, download_dir, from_ep, to_ep)
    families = _select_title_families(archetype)

    titles = []
    for family_key in families:
        templates = TITLE_FORMULA_TEMPLATES.get(family_key, [])
        for template in templates:
            try:
                # Fill template with beats, using .get() via format_map
                filled = template.format_map(SafeFormatDict(beats))
                # Skip if any unfilled placeholders remain
                if "{" in filled:
                    continue
                formatted = format_recap_title(filled)
                if formatted not in titles:
                    titles.append(formatted)
            except (KeyError, ValueError):
                continue

        if len(titles) >= 5:
            break

    # Ensure at least 5 options — pad with ep_range-specific generic titles
    ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
    fallback_titles = [
        f"He Survived {beats.get('disaster', 'the Apocalypse')} While EVERYONE Else Fell [{ep_range}] | Manhwa Recap",
        f"From Day 1 to Day {to_ep}: Conquering {beats.get('disaster', 'the Apocalypse')} [{ep_range}] | Manhwa Recap",
        f"The Ultimate Survivor of {beats.get('disaster', 'the Apocalypse')} [{ep_range}] | Manhwa Recap",
    ]
    for fb in fallback_titles:
        if len(titles) >= 5:
            break
        formatted = format_recap_title(fb)
        if formatted not in titles:
            titles.append(formatted)

    return titles[:5]


class SafeFormatDict(dict):
    """Dict subclass that returns '{key}' for missing keys instead of raising KeyError."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


# =============================================================================
# TAG ENGINE — Radical simplification (research: tags play minimal role)
# =============================================================================

def build_minimal_tags(comic_title: str, archetype: str) -> List[str]:
    """
    Builds a minimal, high-value tag stack (5-8 tags).

    Research basis (deep-research-report.md):
    - YouTube officially states tags play a minimal discovery role
    - Tags are mainly useful for handling misspellings
    - Title, thumbnail, and description matter far more
    """
    tags = [
        "manhwa recap",
        comic_title.lower(),
        f"{comic_title.lower()} recap",
    ]

    archetype_tags = {
        "zombie_apocalypse": ["zombie manhwa", "apocalypse manhwa"],
        "bunker_prepper": ["survival manhwa", "apocalypse manhwa"],
        "tower_anti_regression": ["tower manhwa", "regression manhwa"],
        "hunter_gate": ["hunter manhwa", "dungeon manhwa"],
        "game_system_reality": ["game manhwa", "system manhwa"],
        "regression_prep": ["regression manhwa", "apocalypse manhwa"],
        "farming_kingdom": ["farming manhwa", "kingdom manhwa"],
        "murim_apocalypse": ["murim manhwa", "martial arts manhwa"],
        "general_apocalypse": ["apocalypse manhwa", "survival manhwa"],
    }
    tags.extend(archetype_tags.get(archetype, ["apocalypse manhwa"]))

    # Deduplicate while preserving order
    seen = set()
    cleaned = []
    for t in tags:
        t_clean = t.strip().lower()
        if t_clean and t_clean not in seen:
            seen.add(t_clean)
            cleaned.append(t_clean)

    return cleaned[:8]


# =============================================================================
# THUMBNAIL CONCEPTS — Resource Contrast model (replaces sensual/allure)
# =============================================================================

def _build_resource_contrast_concepts(
    comic_title: str,
    archetype: str,
    mc_name: str,
    beats: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Generates resource-contrast thumbnail concepts.

    Research basis (deep-research-report.md):
    - "Let the title explain the full causal story while the thumbnail
       communicates ONE VISUAL INEQUALITY"
    - Resource contrast: EVERYONE: 120°F vs HIM: 65°F, 0 FOOD vs 10 YEARS
    - "A thumbnail should NOT reprint a 90-character title"
    - Thumbnail answers "What does he have that everyone else doesn't?"
    """
    disaster = beats.get("disaster", "Apocalypse")
    advantage = beats.get("advantage", "Unlimited Supplies")
    scarce_thing = beats.get("scarce_thing", "Resources")

    # Concept 1: Split-Screen Resource Inequality
    prompt_split = (
        f"Create a dramatic, cinematic 16:9 widescreen YouTube thumbnail illustration in authentic Korean webtoon manhwa art style. "
        f"Sharp ink linework, saturated cel-shading, dynamic rim lighting.\n\n"
        f"[COMPOSITION — SPLIT-SCREEN RESOURCE INEQUALITY]:\n"
        f"Divide the frame vertically with a dramatic diagonal crack or energy divide.\n\n"
        f"LEFT SIDE (DEVASTATION — 45% of frame):\n"
        f"A crumbling cityscape showing the {disaster}. Panicked civilians desperately reaching toward the right side. "
        f"Muted, desaturated colors. Dust, debris, and chaos. A large bold text overlay reads the scarcity stat "
        f"(e.g. '0 FOOD' or '120°F' or 'NO SHELTER').\n\n"
        f"RIGHT SIDE (MC'S SANCTUARY — 55% of frame):\n"
        f"{mc_name} standing confidently inside a well-stocked, warm, secure base. "
        f"Vibrant saturated colors contrasting the left side. Shelves of supplies, working lights, comfort. "
        f"A large bold text overlay reads the abundance stat (e.g. '10 YEARS' or '65°F' or 'INFINITE').\n\n"
        f"[THUMBNAIL GRAPHIC OVERLAYS]:\n"
        f"Two contrasting stat badges: LEFT in fiery red/orange, RIGHT in cool blue/green or gold. "
        f"Bold sans-serif font (Montserrat/Impact style), thick black stroke for readability on mobile."
    )

    # Concept 2: Before/After Survival Progression
    prompt_progression = (
        f"Create a high-impact, cinematic 16:9 widescreen YouTube thumbnail illustration in Korean webtoon manhwa art style. "
        f"Sharp linework, vibrant colors, dynamic composition.\n\n"
        f"[COMPOSITION — BEFORE/AFTER SURVIVAL PROGRESSION]:\n"
        f"Horizontal timeline comparison showing the protagonist's transformation.\n\n"
        f"LEFT (DAY 1 — 40% of frame):\n"
        f"A small, ordinary-looking version of {mc_name} standing amid the initial chaos of {disaster}. "
        f"Confused expression, basic clothing, no equipment. Muted warm tones.\n\n"
        f"CENTER (ARROW/TRANSITION — 20% of frame):\n"
        f"A dramatic glowing arrow or energy surge connecting the two states, with 'DAY 1 → DAY 100' text.\n\n"
        f"RIGHT (DAY 100 — 40% of frame):\n"
        f"{mc_name} transformed into a confident, battle-hardened survivor. "
        f"Standing atop a fortified base or resource stockpile. Glowing aura, upgraded gear, dominant posture. "
        f"Vibrant saturated colors.\n\n"
        f"[THUMBNAIL GRAPHIC OVERLAYS]:\n"
        f"Bold typography: 'DAY 1' in muted grey on the left, 'DAY 100' in glowing gold (#FFD700) on the right. "
        f"Thick black stroke. No more than 4 words total."
    )

    # Concept 3: Survival Dashboard HUD Overlay
    prompt_dashboard = (
        f"Create a cinematic, game-UI-inspired 16:9 widescreen YouTube thumbnail illustration in Korean webtoon manhwa art style. "
        f"Clean linework, vibrant neon accents, dark atmospheric background.\n\n"
        f"[COMPOSITION — SURVIVAL DASHBOARD OVERLAY]:\n\n"
        f"CENTER: {mc_name} standing in a dramatic power pose amid the ruins of {disaster}. "
        f"Confident expression, tactical gear, glowing weapon or tool in hand.\n\n"
        f"OVERLAY — SURVIVAL HUD (semi-transparent, game-UI style):\n"
        f"Floating around the character, render a stylized survival status dashboard:\n"
        f"  • Top-left: 'DAY 47' in bold white\n"
        f"  • Left bar: 'FOOD ████████░░ 83%' in green\n"
        f"  • Left bar: 'WATER ██████░░░░ 61%' in blue\n"
        f"  • Right badge: 'THREAT: HIGH' in pulsing red\n"
        f"  • Right badge: 'BASE: LV.5' in gold\n\n"
        f"[THUMBNAIL GRAPHIC OVERLAYS]:\n"
        f"Semi-transparent dark panel behind the HUD stats for readability. "
        f"All text in clean sans-serif font with subtle glow effects. "
        f"The overall look should resemble a survival game screenshot, reinforcing the 'resource management' fantasy."
    )

    return [
        {
            "id": "concept_resource_split",
            "name": "Split-Screen Resource Inequality (Bất Bình Đẳng Tài Nguyên)",
            "thumbnail_text": f"0 {scarce_thing.upper()} vs INFINITE",
            "text_style": "Two contrasting stat badges: LEFT fiery red, RIGHT gold/green. Bold Impact font, thick black stroke.",
            "composition": "Vertical split: devastation LEFT vs sanctuary RIGHT",
            "gpt_prompt": prompt_split,
        },
        {
            "id": "concept_before_after",
            "name": "Before/After Survival Progression (DAY 1 → DAY 100)",
            "thumbnail_text": "DAY 1 → DAY 100",
            "text_style": "DAY 1 in muted grey, DAY 100 in glowing gold (#FFD700). Horizontal timeline arrow.",
            "composition": "Horizontal timeline: weak LEFT → powerful RIGHT",
            "gpt_prompt": prompt_progression,
        },
        {
            "id": "concept_survival_dashboard",
            "name": "Survival Dashboard HUD (Bảng Tình Trạng Sinh Tồn)",
            "thumbnail_text": "FOOD: 83% | THREAT: HIGH",
            "text_style": "Game-UI style HUD with progress bars and stat badges. Semi-transparent dark panels.",
            "composition": "Character center + floating survival stats overlay",
            "gpt_prompt": prompt_dashboard,
        },
    ]


# =============================================================================
# SURVIVAL DASHBOARD DATA GENERATOR
# =============================================================================

def generate_survival_dashboard_data(
    archetype: str,
    from_ep: int,
    to_ep: int,
    story_memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generates survival dashboard overlay data for video production.
    This is metadata-only — rendering implementation is separate.

    Research basis (deep-research-report.md):
    - Original editorial overlay strengthens YPP compliance
    - "Survival dashboard" = evidence of transformative creative contribution
    """
    total_eps = to_ep - from_ep + 1
    progress_pct = min(100, round((total_eps / max(1, to_ep)) * 100))

    # Base dashboard keyed to archetype
    if archetype == "zombie_apocalypse":
        outside_condition = "Infected Zone — Swarms Active"
        threat = "EXTREME"
    elif archetype == "bunker_prepper":
        outside_condition = "Sub-Zero Wasteland — Radiation Active"
        threat = "HIGH"
    elif archetype in ("game_system_reality", "hunter_gate"):
        outside_condition = "Dungeon Zone — Boss Spawning"
        threat = "S-RANK"
    elif archetype == "regression_prep":
        outside_condition = f"T-{max(1, 30 - total_eps)} Days Until Apocalypse"
        threat = "INCOMING"
    elif archetype == "farming_kingdom":
        outside_condition = "Hostile Territory — Rival Factions"
        threat = "MODERATE"
    else:
        outside_condition = "Wasteland — Unknown Threats"
        threat = "HIGH"

    return {
        "day_number": total_eps * 3,
        "food_reserve_pct": max(20, 95 - total_eps),
        "water_reserve_pct": max(15, 88 - total_eps),
        "power_status": "Online" if total_eps > 10 else "Offline",
        "outside_condition": outside_condition,
        "base_security_level": min(10, 1 + total_eps // 6),
        "threat_description": threat,
        "mc_level": min(999, total_eps * 5 + 1),
        "party_size": min(12, 1 + total_eps // 4),
        "story_progress_pct": progress_pct,
    }


def format_mini_status_block(
    archetype: str,
    survival_dashboard: Dict[str, Any],
) -> str:
    """
    Formats an immersive, archetype-adaptive mini status block for the pinned comment.
    """
    day = survival_dashboard.get("day_number", 1)
    threat = survival_dashboard.get("threat_description", "HIGH")
    outside = survival_dashboard.get("outside_condition", "Wasteland")

    if archetype in ("hunter_gate", "tower_anti_regression", "game_system_reality"):
        mc_lvl = survival_dashboard.get("mc_level", 99)
        party = survival_dashboard.get("party_size", 1)
        return (
            "📊 STATUS WINDOW:\n"
            f"• ⚔️ Player Level: Lv.{mc_lvl}\n"
            f"• 👥 Party / Guild: {party} Members\n"
            f"• 📍 Zone: {outside}\n"
            f"• ⚠️ Threat Rank: {threat}"
        )
    elif archetype == "farming_kingdom":
        sec_lvl = survival_dashboard.get("base_security_level", 1)
        food = survival_dashboard.get("food_reserve_pct", 80)
        return (
            "📊 TERRITORY LOG:\n"
            f"• 🗓️ Settlement Day: Day {day}\n"
            f"• 🌾 Harvest Reserves: {food}%\n"
            f"• 🏰 Domain Fortification: Level {sec_lvl}\n"
            f"• ⚠️ Region Threat: {threat}"
        )
    elif archetype == "regression_prep":
        sec_lvl = survival_dashboard.get("base_security_level", 1)
        food = survival_dashboard.get("food_reserve_pct", 80)
        return (
            "📊 REGRESSION PREP LOG:\n"
            f"• ⏳ Timeline: Day {day}\n"
            f"• 📦 Stockpile Progress: {food}%\n"
            f"• 🛡️ Shelter Fortification: Level {sec_lvl}\n"
            f"• ⚠️ Calamity Alert: {threat}"
        )
    else:  # bunker_prepper, zombie_apocalypse, murim_apocalypse, general_apocalypse
        food = survival_dashboard.get("food_reserve_pct", 80)
        water = survival_dashboard.get("water_reserve_pct", 75)
        sec_lvl = survival_dashboard.get("base_security_level", 1)
        power = survival_dashboard.get("power_status", "Online")
        return (
            "📊 SURVIVAL STATUS:\n"
            f"• 🗓️ Timeline: Day {day}\n"
            f"• 🍖 Reserves: Food {food}% | Water {water}%\n"
            f"• 🛡️ Defense: Base Security Lv.{sec_lvl} (Power: {power})\n"
            f"• ⚠️ Threat Alert: {threat} ({outside})"
        )


# =============================================================================
# ENGAGEMENT QUESTION GENERATOR
# =============================================================================

def generate_engagement_question(archetype: str) -> str:
    """Selects a contextual engagement question for pinned comment."""
    import random
    questions = ENGAGEMENT_QUESTIONS.get(archetype, ENGAGEMENT_QUESTIONS["general_apocalypse"])
    return random.choice(questions) if questions else "What was your favorite moment? Drop your thoughts below! 👇"


# =============================================================================
# CHARACTER IMAGE REFERENCES (unchanged utility)
# =============================================================================

def find_character_image_references(
    download_dir: Optional[str] = None,
    image_references: Optional[Dict[str, Any]] = None
) -> Dict[str, List[str]]:
    """Finds real character panel images from downloaded episodes for AI image prompt reference."""
    refs = {"protagonist": [], "female_characters": []}
    if image_references:
        for k, v in image_references.items():
            if k in refs and isinstance(v, list):
                refs[k].extend(v)

    if download_dir and os.path.isdir(download_dir):
        for ep in [1, 2]:
            ep_img_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
            if os.path.isdir(ep_img_dir):
                imgs = sorted(glob.glob(os.path.join(ep_img_dir, "*.webp")) + glob.glob(os.path.join(ep_img_dir, "*.jpg")) + glob.glob(os.path.join(ep_img_dir, "*.png")))
                if imgs and len(refs["protagonist"]) < 2:
                    refs["protagonist"].append(imgs[min(1, len(imgs) - 1)])
        for ep in [14, 20, 35, 15, 4]:
            ep_img_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
            if os.path.isdir(ep_img_dir):
                imgs = sorted(glob.glob(os.path.join(ep_img_dir, "*.webp")) + glob.glob(os.path.join(ep_img_dir, "*.jpg")) + glob.glob(os.path.join(ep_img_dir, "*.png")))
                if imgs and len(refs["female_characters"]) < 2:
                    refs["female_characters"].append(imgs[min(2, len(imgs) - 1)])

    return refs


# =============================================================================
# MAIN METADATA GENERATOR
# =============================================================================

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
    """
    Generates complete YouTube metadata kit for US Apocalypse market.

    Research-driven updates (Sep 2026):
    - Dynamic title generation from story beats (no hardcoded titles)
    - Radical tag simplification (5-8 tags, YouTube says tags are minimal)
    - Resource-contrast thumbnail concepts (validated by Mamoru's 2M-view titles)
    - Creation statement replaces Section 107 disclaimer
    - Engagement questions & mini status block in pinned comments (replaces redundant timestamps)
    - Survival dashboard data for editorial overlays
    """
    ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
    char_names = get_character_names(comic_title, story_memory)
    mc_name = char_names["mc"]
    archetype = detect_archetype(comic_title, story_memory)
    image_refs = find_character_image_references(download_dir, image_references)
    beats = _extract_story_beats(comic_title, archetype, story_memory, download_dir, from_ep, to_ep)

    # ── 1. DYNAMIC TITLES ──────────────────────────────────────────────────
    title_options = generate_dynamic_titles(
        comic_title, archetype, story_memory, download_dir, from_ep, to_ep
    )
    primary_title = title_options[0] if title_options else format_recap_title(f"{comic_title} [{ep_range}]")

    # ── 2. NARRATIVE CHAPTERS (Timestamps) ─────────────────────────────────
    narrative_chapters = build_narrative_story_chapters(
        chapters,
        download_dir=download_dir,
        comic_title=comic_title,
        archetype=archetype,
        from_ep=from_ep,
        to_ep=to_ep,
    )

    # ── 3. DESCRIPTION — Research-validated tier structure ──────────────────
    # Tier 1: Hook (above "Show More" fold)
    disaster = beats.get("disaster", "the Apocalypse")
    advantage = beats.get("advantage", "an impossible advantage")
    desc_lines = [
        f"When {disaster.lower()} strikes, everyone scrambles to survive—but {mc_name} already has {advantage.lower()}.",
        f"This manhwa recap covers {comic_title} ({ep_range}).",
        "",
    ]

    # Tier 2: Series identification
    desc_lines.extend([
        f"📖 Series: {comic_title}",
        f"Genre: apocalypse, survival, {archetype.replace('_', ' ')}",
        "",
    ])

    # Tier 3: Chapter timestamps
    desc_lines.append("⏱️ Chapters:")
    for ch in narrative_chapters:
        desc_lines.append(f"{ch['timestamp']} — {ch['title']}")

    # Tier 4: Subscribe CTA (single line)
    desc_lines.extend([
        "",
        "Subscribe for long-form apocalypse and survival manhwa recaps.",
        "",
    ])

    # Tier 5: Creation statement (replaces Section 107 disclaimer)
    desc_lines.extend([
        "This video contains original scripted narration, editorial structure,",
        "commentary and original editing. Rights in source artwork remain with",
        "their respective owners.",
        "",
    ])

    # Tier 6: Hashtags (minimal, natural)
    clean_tag = re.sub(r"[^a-zA-Z0-9]", "", comic_title.lower())
    hashtags = [
        f"#{clean_tag}" if clean_tag else "#manhwarecap",
        "#manhwarecap",
        "#apocalypsemanhwa",
        "#survivalmanhwa",
    ]
    if archetype == "zombie_apocalypse":
        hashtags.append("#zombiemanhwa")
    elif archetype == "tower_anti_regression":
        hashtags.append("#towermanhwa")
    elif archetype == "hunter_gate":
        hashtags.append("#dungeonmanhwa")
    elif archetype == "bunker_prepper":
        hashtags.append("#bunkermanhwa")
    elif archetype == "game_system_reality":
        hashtags.append("#gamemanhwa")
    elif archetype == "farming_kingdom":
        hashtags.append("#farmingmanhwa")

    desc_lines.append(" ".join(hashtags))

    # ── 4. TAGS — Radical simplification ───────────────────────────────────
    tags = build_minimal_tags(comic_title, archetype)

    # ── 5. THUMBNAIL CONCEPTS — Resource Contrast model ────────────────────
    thumbnail_concepts = _build_resource_contrast_concepts(comic_title, archetype, mc_name, beats)

    # ── 6. SURVIVAL DASHBOARD DATA ─────────────────────────────────────────
    survival_dashboard = generate_survival_dashboard_data(archetype, from_ep, to_ep, story_memory)

    # ── 7. PINNED COMMENT with mini status block & engagement question ────
    status_block = format_mini_status_block(archetype, survival_dashboard)
    engagement_q = generate_engagement_question(archetype)

    pinned_comment_text = (
        "📌 MANHWA INFO & STATUS LOG:\n"
        f"📖 Series: {comic_title} (Chapters {from_ep} – {to_ep})\n\n"
        f"{status_block}\n\n"
        f"💬 {engagement_q}\n\n"
        "👉 Like & Subscribe for more full-arc manhwa recaps!"
    )

    # ── 7. SURVIVAL DASHBOARD DATA ─────────────────────────────────────────
    survival_dashboard = generate_survival_dashboard_data(archetype, from_ep, to_ep, story_memory)

    # ── 8. FORMATTED KIT STRING ────────────────────────────────────────────
    kit_lines = [
        "=" * 80,
        f"YOUTUBE UPLOAD KIT: {comic_title}",
        f"Episodes: {from_ep} - {to_ep} | Market: us_apocalypse | Archetype: {archetype.upper()}",
        "=" * 80,
        "",
        "[1. TITLE CANDIDATES (Pick one for YouTube Title)]",
    ]
    for i, t in enumerate(title_options, 1):
        prefix = "★ " if i == 1 else "  "
        kit_lines.append(f"{prefix}Option {i}: {t}")

    kit_lines.extend([
        "",
        "[2. DESCRIPTION & TIMESTAMPS (Copy & paste into YouTube Description)]",
        "\n".join(desc_lines),
        "",
        "[3. PINNED COMMENT (Copy & paste to Pin)]",
        pinned_comment_text,
        "",
        "[4. TAGS (Copy & paste directly into YouTube Studio Tag Box)]",
        ", ".join(tags),
        "",
        "=" * 80,
        "[5. RESOURCE-CONTRAST THUMBNAIL CONCEPTS & AI PROMPTS]",
        "Instructions:",
        "1. Pick 1 of the 3 Concepts below that best fits your video.",
        "2. Open ChatGPT (select GPT-4o model).",
        "3. Copy the MASTER PROMPT for that Concept and paste into ChatGPT to generate a 16:9 thumbnail.",
        "=" * 80,
    ])

    for i, c in enumerate(thumbnail_concepts, 1):
        kit_lines.extend([
            "",
            f"▶ CONCEPT {i}: {c['name'].upper()}",
            f"  • Text Overlay : {c['thumbnail_text']}",
            f"  • Text Style   : {c['text_style']}",
            f"  • Composition  : {c['composition']}",
            "",
            "  • MASTER PROMPT (Copy & paste into GPT-4o):",
            "-" * 80,
            c['gpt_prompt'],
            "-" * 80,
        ])

    # Section 6: Survival Dashboard Reference Data
    kit_lines.extend([
        "",
        "=" * 80,
        "[6. SURVIVAL DASHBOARD OVERLAY DATA (For video editing)]",
        "Use this data to create an original editorial overlay in your video editor.",
        "This overlay strengthens YPP compliance as original creative content.",
        "=" * 80,
        "",
        f"  DAY {survival_dashboard['day_number']}",
        f"  Food Reserve: {survival_dashboard['food_reserve_pct']}%",
        f"  Water Reserve: {survival_dashboard['water_reserve_pct']}%",
        f"  Power: {survival_dashboard['power_status']}",
        f"  Outside: {survival_dashboard['outside_condition']}",
        f"  Base Security: Level {survival_dashboard['base_security_level']}",
        f"  Threat: {survival_dashboard['threat_description']}",
        f"  MC Level: {survival_dashboard['mc_level']}",
        f"  Party Size: {survival_dashboard['party_size']}",
        "",
        "=" * 80,
    ])

    formatted_kit = "\n".join(kit_lines)

    return {
        "title": primary_title,
        "title_options": title_options,
        "description": "\n".join(desc_lines),
        "pinned_comment": pinned_comment_text,
        "tags": tags,
        "narrative_chapters": narrative_chapters,
        "thumbnail_concepts": thumbnail_concepts,
        "engagement_question": engagement_q,
        "survival_dashboard": survival_dashboard,
        "formatted_kit": formatted_kit,
    }
