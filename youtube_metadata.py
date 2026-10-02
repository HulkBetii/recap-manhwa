from __future__ import annotations

import json
import os
import re
import glob
import random
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set

# V5: StoryFactGraph for evidence-first structured fact generation
try:
    from story_fact_graph import (
        StoryFactGraph, GroundedFact, validate_fact_entailment, ExtractionRule,
        FACT_USAGE_POLICY, can_use_fact_for_surface
    )
except ImportError:
    StoryFactGraph = None           # type: ignore
    GroundedFact = None             # type: ignore
    validate_fact_entailment = None # type: ignore
    ExtractionRule = None           # type: ignore
    FACT_USAGE_POLICY = {}          # type: ignore
    can_use_fact_for_surface = None # type: ignore

try:
    from channel_profile import CHANNEL_PROFILE, get_channel_profile
except ImportError:
    CHANNEL_PROFILE = {
        "channel_name": "Jaehwan Manhwa",
        "channel_handle": "@JaehwanManhwa",
        "channel_url": "https://www.youtube.com/@JaehwanManhwa",
        "sub_link": "https://www.youtube.com/@JaehwanManhwa?sub_confirmation=1",
        "brand_tags": ["jaehwan manhwa", "jaehwan", "jaehwan manhwa recap"],
    }
    get_channel_profile = lambda: CHANNEL_PROFILE


# =============================================================================
# DATA STRUCTURES & EVIDENCE MODELS
# =============================================================================

@dataclass
class EvidenceUnit:
    """
    Represents a single atomic unit of story evidence with source location,
    subject binding, scope classification, and context type.
    """
    source: str  # "recap" | "story_memory" | "title"
    episode: int  # 0 for story_memory, 1..N for recap
    segment_index: int  # -1 for story_memory, 0..M for recap speech segments
    snippet: str
    source_path: str = ""
    timestamp: Optional[str] = None
    subject: Optional[str] = None
    scope: str = "local_scene"  # "global_story_world" | "local_group" | "local_scene"
    context_type: str = "dialogue"  # "dialogue" | "narration" | "memory" | "title"

    @property
    def unit_id(self) -> Tuple[str, int, int]:
        return (self.source, self.episode, self.segment_index)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "episode": self.episode,
            "segment_index": self.segment_index,
            "snippet": self.snippet[:300] if len(self.snippet) > 300 else self.snippet,
            "source_path": self.source_path,
            "timestamp": self.timestamp,
            "subject": self.subject,
            "scope": self.scope,
            "context_type": self.context_type,
        }


@dataclass
class SemanticAssertion:
    """
    Structured semantic assertion extracted from any text surface (titles, thumbnails,
    prompts, chapters, pinned comments, dashboard fields) for rigorous evidence verification.
    """
    assertion_type: str       # e.g. "preparation_duration", "day_number", "mc_built_bunker", "bunker_claim", "controls_stockpile"
    raw_text: str             # e.g. "16 Years Preparing", "Day 143", "Building a Doomsday Bunker"
    subject: str = "protagonist"  # "protagonist" | "world" | "population" | "antagonist" | "environment"
    scope: str = "local_scene"    # "global_story_world" | "story_arc" | "local_group" | "local_scene"
    value: Any = None         # e.g. 16 (int), 143 (int), "doomsday_bunker"
    unit: Optional[str] = None  # "years", "days", "floors", "percent"
    risk: str = "high"        # "high" | "medium" | "low"
    requires_evidence: bool = True
    status: str = "unvalidated"  # "supported" | "unsupported" | "downgraded"
    evidence_units: List[Dict[str, Any]] = field(default_factory=list)
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assertion_type": self.assertion_type,
            "raw_text": self.raw_text,
            "subject": self.subject,
            "scope": self.scope,
            "value": self.value,
            "unit": self.unit,
            "risk": self.risk,
            "requires_evidence": self.requires_evidence,
            "status": self.status,
            "evidence_units": self.evidence_units,
            "rejection_reason": self.rejection_reason,
        }


# =============================================================================
# THUMBNAIL & TITLE OUTPUT CONSTRAINT HELPERS
# =============================================================================

def _cap_overlay_text(text: str, max_chars: int = 15) -> str:
    """
    Hard cap thumbnail overlay text (main_text OR sub_text) to max_chars via
    word-boundary truncation. Guarantees len(output) <= max_chars always.

    Symmetry Rule: apply to ALL overlay text surfaces equally — not just main_text.
    The cap is enforced here so callers don't need to remember to validate.
    """
    if len(text) <= max_chars:
        return text
    # Strip trailing punctuation before truncating
    base = text.rstrip("!?. ")
    words = base.split()
    result = ""
    for w in words:
        candidate = (result + " " + w).strip() if result else w
        # Reserve 1 char for "!" suffix
        if len(candidate) + 1 <= max_chars:
            result = candidate
        else:
            break
    return (result + "!") if result else text[:max_chars]


def _enforce_title_pre_pipe(title: str, max_pre_pipe: int = 60) -> str:
    """
    Ensures the portion before ' | ' is <= max_pre_pipe chars.
    YouTube mobile (~375px) cuts title display at ~55-60 chars; anything after
    is invisible to the viewer before clicking.

    Output Gate Rule: enforced at the final output layer inside pick_variant()
    and generate_dynamic_titles(), not just at template design time.
    """
    if " | " not in title:
        if len(title) <= max_pre_pipe:
            return title
        return title[:max_pre_pipe].rsplit(" ", 1)[0].rstrip("!,. ") + "!"
    pre, _, suffix = title.partition(" | ")
    if len(pre) <= max_pre_pipe:
        return title
    trimmed = pre[:max_pre_pipe].rsplit(" ", 1)[0].rstrip("!,. ")
    return f"{trimmed}! | {suffix}"


# =============================================================================
# RESEARCH-VALIDATED CONSTANTS & DEDICATED ARCHETYPE TITLE POOLS
# =============================================================================

ARCHETYPE_TITLE_POOLS = {
    "zombie_apocalypse": [
        "When {disaster} Overruns The City, One Lone Survivor Fights Back | Manhwa Recap",
        "He Hoarded Endless Supplies While Everyone Panicked In {disaster} | Manhwa Recap",
        "Surviving {disaster} Against All Odds [{ep_range}] | Manhwa Recap",
        "They Left Him for DEAD in the Quarantine Zone, But He Awoke SSS-Rank | Manhwa Recap",
        "When {disaster} Strikes, The Last Defender Holds The Line | Manhwa Recap",
        "From Outbreak to Total Collapse: Surviving {disaster} [{ep_range}] | Manhwa Recap",
        "He Built {fortress} While The World Collapsed [{ep_range}] | Manhwa Recap",
        "The Lone Veteran of {disaster} Holds The Line [{ep_range}] | Manhwa Recap",
    ],
    "bunker_prepper": [
        "He Built {fortress} With Endless Food While Everyone Panicked! | Manhwa Recap",
        "They Called Him INSANE for {prep_action}, Until {disaster} Struck! | Manhwa Recap",
        "He Prepared Before {disaster} Hit and Built {fortress} | Manhwa Recap",
        "Starving Survivors Beg For Entry, But He Kept The {shelter} Sealed | Manhwa Recap",
        "The World Collapses Into Chaos, But His {shelter} Has Everything | Manhwa Recap",
        "When {disaster} Hits, Everyone Panics But One Man Thrives | Manhwa Recap",
        "When An SSS-Rank {mc_role} Awakens In {disaster} [{ep_range}] | Manhwa Recap",
    ],
    "hunter_gate": [
        "Academy Mocked His '{trash_class}' Until His Combat Power HUMILIATES the Rank 1 | Manhwa Recap",
        "When The F-RANK Trainee Reveals His Hidden SSS-Power and SHOCKS the Elites | Manhwa Recap",
        "He Awakened a BROKEN {system_name} That Turns Low Rank Into SSS-Tier | Manhwa Recap",
        "He Was BETRAYED in the Abyss, But Came Back as the Strongest Hunter | Manhwa Recap",
        "When An SSS-Rank Hunter Awakens Alone In {disaster} [{ep_range}] | Manhwa Recap",
    ],
    "regression_prep": [
        "He DIES in {disaster} and Returns {time_before} Before Everyone Else | Manhwa Recap",
        "BETRAYED at the End, He REGRESSED {time_span} to DESTROY Them All | Manhwa Recap",
        "When {disaster} Strikes, He Thrives With Complete Future Knowledge | Manhwa Recap",
        "He Hoarded All Divine Resources Before {disaster} Started [{ep_range}] | Manhwa Recap",
    ],
    "farming_kingdom": [
        "Exiled to {danger_zone}, His Farming System Builds an UNSTOPPABLE Domain | Manhwa Recap",
        "They Left Him with NOTHING, But His Domain Snowballed Into a KINGDOM | Manhwa Recap",
        "Starving Lords Beg For Food, But He Controls The Entire Harvest | Manhwa Recap",
        "He Was BETRAYED by {betrayer}, But Built {fortress} From Worthless Land | Manhwa Recap",
    ],
    "tower_anti_regression": [
        "Everyone Chose Regression, But He Refused and Broke Reality | Manhwa Recap",
        "He Climbed Floor 100 Alone and Now Controls Reality | Manhwa Recap",
        "They Left Him for DEAD in the Tower, But He Came Back Stronger | Manhwa Recap",
    ],
    "game_system_reality": [
        "Everyone Got Common Classes, But His GLITCHED System Gives Godly Power | Manhwa Recap",
        "From Level 1 to Server Boss: Conquering the Game Reality | Manhwa Recap",
        "He Awakened a BROKEN {system_name} That Turns Low Tier Into Server Boss | Manhwa Recap",
    ],
    "murim_apocalypse": [
        "His Danjeon Was SHATTERED by Elders, Until He Awakened Forbidden Arts | Manhwa Recap",
        "Betrayed by His Sect, He Mastered FORBIDDEN Cultivation to DESTROY Them All | Manhwa Recap",
        "From Exiled Outcast to Martial Overlord: The Complete Vengeance Arc | Manhwa Recap",
    ],
    "general_apocalypse": [
        "He Built {fortress} While The Entire World Collapsed | Manhwa Recap",
        "They Mocked Him As Weak, But His {shelter} Kept Him Alive When {disaster} Hit | Manhwa Recap",
        "When {disaster} Overruns The World, One Man Thrives Against All Odds | Manhwa Recap",
        "When An SSS-Rank {mc_role} Awakens In {disaster} [{ep_range}] | Manhwa Recap",
        "Surviving {disaster} When Everyone Else Lost Hope [{ep_range}] | Manhwa Recap",
        "He Was BETRAYED by {betrayer}, But Survived {disaster} | Manhwa Recap",
    ],
}

ARCHETYPE_VARIANT_POOL = {
    "zombie_apocalypse": {
        "conflict": [
            "He Hoarded Endless Supplies While Everyone Panicked In {disaster} | Manhwa Recap",
            "When {disaster} Overruns The City, One Lone Survivor Fights Back | Manhwa Recap",
            "They Left Him for DEAD in the Quarantine Zone, But He Awoke SSS-Rank | Manhwa Recap",
            "He Was BETRAYED by {betrayer}, But Survived {disaster} | Manhwa Recap",
        ],
        "paradox": [
            "When {disaster} Hits, Everyone Panics But He Holds The Line | Manhwa Recap",
            "Surviving {disaster} When All Safe Zones Fall [{ep_range}] | Manhwa Recap",
            "He Built {fortress} While The World Collapsed [{ep_range}] | Manhwa Recap",
        ],
        "scale": [
            "When An SSS-Rank {mc_role} Awakens In {disaster} [{ep_range}] | Manhwa Recap",
            "From Outbreak to Total Collapse: Surviving {disaster} [{ep_range}] | Manhwa Recap",
            "Surviving {disaster} Against All Odds [{ep_range}] | Manhwa Recap",
        ],
    },
    "bunker_prepper": {
        "conflict": [
            "He Built {fortress} With Endless Food While Everyone Panicked! | Manhwa Recap",
            "They Called Him INSANE for {prep_action}, Until {disaster} Struck! | Manhwa Recap",
            "He Prepared Before {disaster} Hit and Built {fortress} | Manhwa Recap",
        ],
        "paradox": [
            "The World Collapses Into Chaos, But His {shelter} Has Everything | Manhwa Recap",
            "Starving Survivors Beg For Entry, But He Kept The {shelter} Sealed | Manhwa Recap",
            "When {disaster} Hits, Everyone Panics But He Thrives | Manhwa Recap",
        ],
        "scale": [
            "When An SSS-Rank {mc_role} Awakens In {disaster} [{ep_range}] | Manhwa Recap",
            "Building {fortress} in a Dead World [{ep_range}] | Manhwa Recap",
            "Surviving {disaster} in the Ultimate Sanctuary [{ep_range}] | Manhwa Recap",
        ],
    },
    "hunter_gate": {
        "conflict": [
            "Academy Mocked His '{trash_class}' Until His Combat Power HUMILIATES the Rank 1 | Manhwa Recap",
            "When The F-RANK Trainee Reveals His Hidden SSS-Power and SHOCKS the Elites | Manhwa Recap",
        ],
        "paradox": [
            "He Awakened a BROKEN {system_name} That Turns Low Rank Into SSS-Tier | Manhwa Recap",
            "Everyone Got Common Classes, But His System Gives SSS Awakening | Manhwa Recap",
        ],
        "scale": [
            "When An SSS-Rank Hunter Awakens Alone In {disaster} [{ep_range}] | Manhwa Recap",
            "From F-Rank to the Strongest Hunter [{ep_range}] | Manhwa Recap",
            "Conquering S-Rank Dungeons Alone [{ep_range}] | Manhwa Recap",
        ],
    },
    "regression_prep": {
        "conflict": [
            "He DIES in {disaster} and Returns {time_before} Before Everyone Else | Manhwa Recap",
            "BETRAYED at the End, He REGRESSED {time_span} to DESTROY Them All | Manhwa Recap",
        ],
        "paradox": [
            "When {disaster} Strikes, He Thrives With Complete Future Knowledge | Manhwa Recap",
            "He Hoarded All Divine Resources Before {disaster} Started [{ep_range}] | Manhwa Recap",
        ],
        "scale": [
            "Conquering {disaster} Alone With Future Knowledge [{ep_range}] | Manhwa Recap",
        ],
    },
    "farming_kingdom": {
        "conflict": [
            "Exiled to {danger_zone}, His Farming System Builds an UNSTOPPABLE Domain | Manhwa Recap",
            "They Left Him with NOTHING, But His Domain Snowballed Into a KINGDOM | Manhwa Recap",
        ],
        "paradox": [
            "Starving Lords Beg For Food, But He Controls The Entire Harvest | Manhwa Recap",
            "Starving Lords Fight for Scraps, But He Controls the Harvest | Manhwa Recap",
        ],
        "scale": [
            "From Zero to Overlord: How One Exiled Man Built an Empire [{ep_range}] | Manhwa Recap",
        ],
    },
    "tower_anti_regression": {
        "conflict": [
            "Everyone Chose Regression, But He Refused and Broke Reality | Manhwa Recap",
            "They Left Him for DEAD in the Tower, But He Came Back Stronger | Manhwa Recap",
        ],
        "paradox": [
            "The Tower Stole EVERYTHING, But He Controls Reality | Manhwa Recap",
        ],
        "scale": [
            "He Climbed Floor 100 Alone and Now Controls Reality [{ep_range}] | Manhwa Recap",
        ],
    },
    "game_system_reality": {
        "conflict": [
            "Everyone Got Common Classes, But His GLITCHED System Gives Godly Power | Manhwa Recap",
        ],
        "paradox": [
            "He Awakened a BROKEN {system_name} That Turns Low Tier Into Server Boss | Manhwa Recap",
        ],
        "scale": [
            "From Level 1 to Server Boss: Conquering the Game Reality [{ep_range}] | Manhwa Recap",
        ],
    },
    "murim_apocalypse": {
        "conflict": [
            "His Danjeon Was SHATTERED by Elders, Until He Awakened Forbidden Arts | Manhwa Recap",
            "Betrayed by His Sect, He Mastered FORBIDDEN Cultivation to DESTROY Them All | Manhwa Recap",
        ],
        "paradox": [
            "Everyone Thought His Cultivation Was Broken, But He Mastered Absolute Power | Manhwa Recap",
        ],
        "scale": [
            "From Exiled Outcast to Martial Overlord: The Complete Vengeance Arc [{ep_range}] | Manhwa Recap",
        ],
    },
    "general_apocalypse": {
        "conflict": [
            "He Built {fortress} While The Entire World Collapsed | Manhwa Recap",
            "They Mocked Him As Weak, But His {shelter} Kept Him Alive When {disaster} Hit | Manhwa Recap",
            "He Was BETRAYED by {betrayer}, But Survived {disaster} | Manhwa Recap",
            "They Left Him for DEAD, But He Came Back Stronger | Manhwa Recap",
        ],
        "paradox": [
            "When {disaster} Hits, Everyone Panics But He Holds The Line | Manhwa Recap",
        ],
        "scale": [
            "When An SSS-Rank {mc_role} Awakens In {disaster} [{ep_range}] | Manhwa Recap",
            "When {disaster} Overruns The World, One Man Thrives Against All Odds [{ep_range}] | Manhwa Recap",
        ],
    },
}

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

CLAIM_REGISTRY = {
    "sss_rank": {
        "patterns": ["sss", "sss-rank", "sss rank", "triple s"],
        "canonical_patterns": ["sss-rank", "sss rank"],
        "high_risk": True,
        "description": "SSS-Rank or high tier hunter grading",
    },
    "trainee": {
        "patterns": ["trainee", "rookie trainee", "cadet", "f-rank trainee"],
        "canonical_patterns": ["trainee", "f-rank trainee"],
        "high_risk": False,
        "description": "Hunter academy / trainee identity",
    },
    "academy": {
        "patterns": ["academy", "military academy", "training academy", "hunter academy"],
        "canonical_patterns": ["academy"],
        "high_risk": False,
        "description": "Academy setting",
    },
    "regression": {
        "patterns": ["regress", "regression", "returned to the past", "went back in time", "time travel", "time loop"],
        "canonical_patterns": ["regression", "regressed", "went back in time", "returned to the past"],
        "high_risk": False,
        "description": "Time travel / regression premise",
    },
    "system": {
        "patterns": ["system window", "status window", "quest alert", "level up", "skill acquired", "glitched system", "broken system"],
        "canonical_patterns": ["system window", "status window", "glitched system"],
        "high_risk": False,
        "description": "Game system / status UI",
    },
    "infinite_resources": {
        "patterns": [
            "infinite supplies", "unlimited supplies", "infinite food", "infinite resources",
            "endless supply", "unlimited rations", "never runs out", "infinite dimensional",
            "infinite storage", "unlimited storage"
        ],
        "canonical_patterns": ["infinite dimensional warehouse"],
        "high_risk": True,
        "description": "Infinite or unlimited resource stockpile",
    },
    "bunker": {
        "patterns": ["bunker", "fallout shelter", "underground bunker", "underground shelter", "fallout vault"],
        "canonical_patterns": ["bunker", "underground bunker", "fallout shelter"],
        "high_risk": False,
        "description": "Bunker or prepper shelter",
    },
    "zombie": {
        "patterns": ["zombie", "infected", "undead", "horde", "82-08", "outbreak", "virus", "plague"],
        "canonical_patterns": ["zombie", "infected", "undead"],
        "high_risk": False,
        "description": "Zombie infection premise",
    },
    "cultivation": {
        "patterns": ["cultivation", "danjeon", "qi", "meridian", "inner energy"],
        "canonical_patterns": ["cultivation", "danjeon", "qi"],
        "high_risk": False,
        "description": "Murim / martial arts cultivation",
    },
    "heavenly_demon": {
        "patterns": ["heavenly demon", "heavenly demon art", "demonic art"],
        "canonical_patterns": ["heavenly demon"],
        "high_risk": False,
        "description": "Heavenly demon lore",
    },
    "drop_rate": {
        "patterns": ["drop rate", "100% drop", "loot system", "100% drop rate"],
        "canonical_patterns": ["100% drop", "drop rate"],
        "high_risk": False,
        "description": "100% drop rate mechanic",
    },
    "percentage_humanity_destroyed": {
        "patterns": ["99%", "99 percent", "90%", "90 percent", "wiped out 99%", "wiped out 90%", "99% of humanity", "90% of humanity"],
        "canonical_patterns": ["99% of humanity", "wiped out 99%", "90% of humanity"],
        "high_risk": True,
        "description": "Specific numerical percentage of humanity destroyed",
    },
    "only_survivor": {
        "patterns": ["only survivor", "sole survivor", "last survivor", "last man alive", "only one left alive", "survived alone"],
        "canonical_patterns": ["only survivor in the world", "sole survivor of humanity", "last man alive on earth"],
        "high_risk": True,
        "description": "Sole survivor claim in multi-character survival",
    },
    "knew_apocalypse_beforehand": {
        "patterns": ["knew the apocalypse was coming", "predicted the end", "prepared beforehand", "foresaw the apocalypse", "knew the disaster was coming", "knew it was coming"],
        "canonical_patterns": ["knew the apocalypse was coming", "foresaw the apocalypse"],
        "high_risk": True,
        "description": "Foreknowledge / pre-disaster prediction claim",
    },
    "unbreakable_fortress": {
        "patterns": ["unbreakable fortress", "impenetrable fortress", "impenetrable bunker", "unbreakable base", "invulnerable fortress"],
        "canonical_patterns": ["unbreakable fortress", "impenetrable bunker", "impenetrable fortress"],
        "high_risk": True,
        "description": "Hyperbolic impenetrable/unbreakable fortress claim",
    },
    "god_tier": {
        "patterns": ["god-tier", "god tier", "king of loot", "godly power"],
        "canonical_patterns": ["god-tier", "king of loot"],
        "high_risk": True,
        "description": "God-tier hyperbolic claim",
    },
}

ARCHETYPE_FORBIDDEN_CLAIMS = {
    "zombie_apocalypse": [
        "sss_rank", "trainee", "academy", "cultivation", "heavenly_demon",
        "drop_rate", "infinite_resources", "percentage_humanity_destroyed",
        "only_survivor", "knew_apocalypse_beforehand", "unbreakable_fortress",
        "god_tier", "preparation_duration", "mc_built_bunker", "bunker_claim",
        "global_starvation", "global_shelter_depletion"
    ],
    "bunker_prepper": ["sss_rank", "trainee", "academy", "cultivation", "heavenly_demon", "drop_rate", "god_tier"],
    "general_apocalypse": [
        "sss_rank", "trainee", "academy", "cultivation", "heavenly_demon",
        "infinite_resources", "god_tier"
    ],
    "hunter_gate": ["cultivation", "heavenly_demon"],
    "regression_prep": ["sss_rank", "cultivation", "heavenly_demon", "drop_rate", "god_tier"],
    "farming_kingdom": ["sss_rank", "trainee", "academy", "cultivation", "heavenly_demon", "god_tier"],
    "game_system_reality": ["cultivation", "heavenly_demon"],
    "tower_anti_regression": ["cultivation", "heavenly_demon"],
    "murim_apocalypse": ["sss_rank", "trainee", "academy", "drop_rate", "infinite_resources", "god_tier"],
}

TITLE_CLAIM_MAP = {
    r"\bsss[\s\-]?rank\b": "sss_rank",
    r"\btrainee\b": "trainee",
    r"\bacademy\b": "academy",
    r"\bregress": "regression",
    r"\binfinite\b|\bunlimited\b": "infinite_resources",
    r"\bcultivation\b": "cultivation",
    r"\bheavenly\s+demon\b": "heavenly_demon",
    r"\b100%\s+drop\b": "drop_rate",
    r"\b99%|\b90%|\b99\s+percent|\b90\s+percent": "percentage_humanity_destroyed",
    r"\bonly\s+survivor\b|\bsole\s+survivor\b": "only_survivor",
    r"\bknew\s+the\s+.*was\s+coming\b|\bknew\s+it\s+was\s+coming\b": "knew_apocalypse_beforehand",
    r"\bunbreakable\s+fortress\b|\bimpenetrable\s+bunker\b|\bimpenetrable\s+underground\s+fortress\b": "unbreakable_fortress",
    r"\bgod[\s\-]tier\b|\bking\s+of\s+loot\b": "god_tier",
}


# =============================================================================
# SEMANTIC ASSERTION EXTRACTOR — Complete Surface Scanning
# =============================================================================

def extract_semantic_assertions(text: str, surface_type: str = "generic") -> List[SemanticAssertion]:
    """
    Extracts all factual assertions from any text surface (titles, thumbnails, GPT prompts,
    chapters, pinned comments, dashboard fields) for mandatory evidence verification.
    """
    assertions: List[SemanticAssertion] = []
    text_lower = text.lower()

    # 1. Day Number Assertion: Day X / Day 1 -> Day X / from Day 1 to Day X
    for m in re.finditer(r"\b(?:from\s+day\s+\d+\s+to\s+day\s+(\d+)|day\s+(\d+)|the\s+(\d+)(?:th|st|nd|rd)\s+day)\b", text, re.IGNORECASE):
        day_val = int(m.group(1) or m.group(2) or m.group(3))
        # Day 1 is starting baseline, but Day > 1 requires explicit evidence
        if day_val > 1:
            assertions.append(SemanticAssertion(
                assertion_type="day_number",
                raw_text=m.group(0),
                subject="protagonist",
                scope="story_arc",
                value=day_val,
                unit="days",
                risk="high",
                requires_evidence=True,
            ))

    # 2. Preparation Duration: e.g. 16 Years Preparing / Spent 16 Years
    for m in re.finditer(r"\b(?:spent\s+)?(\d+)\s*(years?|months?|decades?)\s+preparing\b|\bpreparing\s+for\s+(\d+)\s*(years?|months?|decades?)\b|\bspent\s+(\d+)\s*(years?|months?|decades?)\b", text, re.IGNORECASE):
        val = int(m.group(1) or m.group(3) or m.group(5))
        unit = (m.group(2) or m.group(4) or m.group(6)).lower()
        assertions.append(SemanticAssertion(
            assertion_type="preparation_duration",
            raw_text=m.group(0),
            subject="protagonist",
            scope="story_arc",
            value=val,
            unit=unit,
            risk="high",
            requires_evidence=True,
        ))

    # 3. MC Built Bunker Claim: "Building a Doomsday Bunker" / "Built a Bunker"
    if re.search(r"\b(?:building|built|constructed)\s+(?:a\s+)?(?:doomsday\s+)?(?:underground\s+)?bunker\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="mc_built_bunker",
            raw_text="Building a Doomsday Bunker",
            subject="protagonist",
            scope="story_arc",
            value="built_bunker",
            risk="high",
            requires_evidence=True,
        ))

    # 4. Bunker / Doomsday Bunker Existence Claim
    elif re.search(r"\b(?:doomsday\s+bunker|underground\s+bunker|bunker)\b", text_lower):
        # Exclude verb usages
        if not re.search(r"\bvault(?:ing|ed|s)?\b", text_lower):
            assertions.append(SemanticAssertion(
                assertion_type="bunker_claim",
                raw_text="Bunker",
                subject="environment",
                scope="local_scene",
                value="bunker",
                risk="medium",
                requires_evidence=True,
            ))

    # 5. Resource Ownership / Monopoly: "Controls all food" / "Controls a Stockpiled Supply Cache" / "King of Loot"
    if re.search(r"\b(?:controls\s+(?:all\s+)?(?:the\s+)?(?:food|water|supplies|stockpile|resources|advantage|a\s+stockpiled)|owns\s+(?:the\s+)?(?:base|stockpile)|king\s+of\s+loot)\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="controls_stockpile",
            raw_text=re.search(r"\b(?:controls\s+[^\|\n,]+|owns\s+[^\|\n,]+|king\s+of\s+loot)\b", text_lower).group(0),
            subject="protagonist",
            scope="global_story_world",
            value="controls_stockpile",
            risk="high",
            requires_evidence=True,
        ))

    # 6. Global Starvation Claim: "Everyone Is STARVING"
    if re.search(r"\b(?:everyone|everybody|the\s+world|all\s+humanity)\s+is\s+starving\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="global_starvation",
            raw_text="Everyone Is STARVING",
            subject="population",
            scope="global_story_world",
            value="global_starvation",
            risk="high",
            requires_evidence=True,
        ))

    # 7. Global Shelter Depletion: "The World Ran Out of Safe Shelter"
    if re.search(r"\b(?:the\s+world\s+ran\s+out\s+of\s+(?:safe\s+)?shelter|everyone\s+lost\s+safe\s+shelter)\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="global_shelter_depletion",
            raw_text="The World Ran Out of Safe Shelter",
            subject="world",
            scope="global_story_world",
            value="global_shelter_depletion",
            risk="high",
            requires_evidence=True,
        ))

    # 8. Numeric Percentage Humanity Destroyed: "99% of Humanity"
    for m in re.finditer(r"\b(\d+)%\s+(?:of\s+)?(?:humanity|the\s+world|population)\b|\bwiped\s+out\s+(\d+)%\b", text, re.IGNORECASE):
        pct = int(m.group(1) or m.group(2))
        assertions.append(SemanticAssertion(
            assertion_type="percentage_destroyed",
            raw_text=m.group(0),
            subject="population",
            scope="global_story_world",
            value=pct,
            unit="percent",
            risk="high",
            requires_evidence=True,
        ))

    # 9. ONLY Survivor Claim
    if re.search(r"\b(?:only|sole|last)\s+survivor\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="only_survivor",
            raw_text="ONLY Survivor",
            subject="protagonist",
            scope="global_story_world",
            value="only_survivor",
            risk="high",
            requires_evidence=True,
        ))

    # 10. He Knew Apocalypse Claim
    if re.search(r"\bknew\s+the\s+.*was\s+coming\b|\bknew\s+it\s+was\s+coming\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="knew_apocalypse",
            raw_text="He Knew the Apocalypse Was Coming",
            subject="protagonist",
            scope="story_arc",
            value="knew_apocalypse",
            risk="high",
            requires_evidence=True,
        ))

    # 11. Unbreakable / Impenetrable Fortress Claim
    if re.search(r"\b(?:unbreakable\s+fortress|impenetrable\s+bunker|impenetrable\s+underground\s+fortress)\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="unbreakable_fortress",
            raw_text="IMPENETRABLE Fortress",
            subject="environment",
            scope="local_scene",
            value="unbreakable_fortress",
            risk="high",
            requires_evidence=True,
        ))

    # 12. Visual Prompt Assertions (for Thumbnails / Prompts / Dashboards)
    if re.search(r"\b0\s+(?:safe\s+)?(?:shelter|food|water|supplies)\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="absolute_zero_resource",
            raw_text=re.search(r"\b0\s+[^\|\n,]+\b", text_lower).group(0),
            subject="environment",
            scope="local_scene",
            value="zero_resource",
            risk="high",
            requires_evidence=True,
        ))

    if re.search(r"\bbase:\s*fortified\b|\bfortified\s+base\b|\breinforced\s+compound\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="base_fortified",
            raw_text="BASE: FORTIFIED",
            subject="environment",
            scope="local_scene",
            value="base_fortified",
            risk="medium",
            requires_evidence=True,
        ))

    if re.search(r"\bcontainment:\s*active\b|\bcontainment\s+active\b|\bcontainment\s+order\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="containment_active",
            raw_text="CONTAINMENT ACTIVE",
            subject="environment",
            scope="local_scene",
            value="containment_active",
            risk="medium",
            requires_evidence=True,
        ))

    if re.search(r"\bthreat:\s*critical\b|\bthreat:\s*s\-rank\b|\bmutant\s+strains\s+active\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="threat_critical",
            raw_text="THREAT: CRITICAL",
            subject="environment",
            scope="local_scene",
            value="threat_critical",
            risk="low",
            requires_evidence=True,
        ))

    if re.search(r"\bwell\-stocked(?:,\s*secure)?\s+base\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="well_stocked_base",
            raw_text="well-stocked secure base",
            subject="environment",
            scope="local_scene",
            value="well_stocked_base",
            risk="medium",
            requires_evidence=True,
        ))

    if re.search(r"\b(?:glowing\s+aura|sss\s+energy|glowing\s+runes)\b", text_lower):
        assertions.append(SemanticAssertion(
            assertion_type="visual_supernatural_aura",
            raw_text=re.search(r"\b(?:glowing\s+aura|sss\s+energy|glowing\s+runes)\b", text_lower).group(0),
            subject="protagonist",
            scope="local_scene",
            value="supernatural_aura",
            risk="high",
            requires_evidence=True,
        ))

    # 13. Unknown High-Impact Generic Catch (Fail-Closed Policy)
    for m in re.finditer(r"\b(\d+)\s*(floors?|tons?|armies|weapons?)\b|\b(monopolizes|rules\s+the\s+world|god[\s\-]tier)\b", text, re.IGNORECASE):
        assertions.append(SemanticAssertion(
            assertion_type="unknown_high_impact",
            raw_text=m.group(0),
            subject="unknown",
            scope="global_story_world",
            value=m.group(0),
            risk="high",
            requires_evidence=True,
            rejection_reason="no_validator_registered",
        ))

    return assertions


def extract_factual_assertions(text: str) -> List[Dict[str, Any]]:
    """
    Extracts numerical assertions, absolute quantifiers, and ownership/dominance claims
    from any text surface (titles, descriptions, thumbnails, chapters).
    """
    assertions: List[Dict[str, Any]] = []
    # 1. Numerical assertions (\d+ years, \d+ days, \d+ floors, \d+%, \d+ hours)
    for m in re.finditer(r"\b(\d+)\s*(years?|days?|hours?|months?|floors?|percent|%)\b", text, re.IGNORECASE):
        assertions.append({
            "type": "numeric",
            "matched": m.group(0),
            "value": m.group(1),
            "unit": m.group(2).lower(),
            "span": m.span(),
        })
    # 2. Absolute quantifiers
    for m in re.finditer(r"\b(everyone|everybody|nobody|no one|only survivor|sole survivor|last survivor|all humanity|entire world|all people|every single)\b", text, re.IGNORECASE):
        assertions.append({
            "type": "absolute",
            "matched": m.group(0),
            "term": m.group(1).lower(),
            "span": m.span(),
        })
    # 3. Ownership / Dominance claims
    for m in re.finditer(r"\b(controls all|controls the only|rules the|owns every|monopolizes|king of loot|god[\s\-]tier)\b", text, re.IGNORECASE):
        assertions.append({
            "type": "dominance",
            "matched": m.group(0),
            "term": m.group(1).lower(),
            "span": m.span(),
        })
    return assertions


# =============================================================================
# EVIDENCE INDEX CLASS — Full Episode Range & Specificity Verification
# =============================================================================

class EvidenceIndex:
    """
    Builds a complete, normalized corpus from all requested episodes (from_ep to to_ep)
    and story_memory. Preserves source location, episode number, segment index,
    scope binding, and enforces the Specificity Lattice.
    """
    def __init__(
        self,
        comic_title: str = "",
        archetype: str = "general_apocalypse",
        story_memory: Optional[Dict[str, Any]] = None,
        download_dir: Optional[str] = None,
        from_ep: int = 1,
        to_ep: int = 1,
    ):
        self.comic_title = comic_title
        self.archetype = archetype
        self.from_ep = from_ep
        self.to_ep = to_ep
        self.story_memory = story_memory or {}
        self.episodes_requested: List[int] = list(range(from_ep, to_ep + 1))
        self.episodes_loaded: List[int] = []
        self.episodes_missing: List[int] = []
        self.recap_source_paths: List[str] = []
        self.units: List[EvidenceUnit] = []
        self._claim_cache: Dict[str, Dict[str, Any]] = {}

        self._build_index(comic_title, story_memory, download_dir)

    def _build_index(
        self,
        comic_title: str,
        story_memory: Optional[Dict[str, Any]],
        download_dir: Optional[str],
    ) -> None:
        # 1. Index comic title
        if comic_title:
            self.units.append(EvidenceUnit(
                source="title",
                episode=0,
                segment_index=0,
                snippet=comic_title,
                source_path="",
                context_type="title",
                scope="global_story_world",
            ))

        # 2. Index story_memory fields
        if story_memory and isinstance(story_memory, dict):
            for k, v in story_memory.items():
                if isinstance(v, (str, int, float, bool)):
                    self.units.append(EvidenceUnit(
                        source="story_memory",
                        episode=0,
                        segment_index=-1,
                        snippet=f"{k}: {v}",
                        source_path="story_memory.json",
                        context_type="memory",
                        scope="global_story_world",
                    ))
                elif isinstance(v, dict):
                    self.units.append(EvidenceUnit(
                        source="story_memory",
                        episode=0,
                        segment_index=-1,
                        snippet=f"{k}: {json.dumps(v, ensure_ascii=False)}",
                        source_path="story_memory.json",
                        context_type="memory",
                        scope="global_story_world",
                    ))
                elif isinstance(v, list):
                    for idx, item in enumerate(v):
                        self.units.append(EvidenceUnit(
                            source="story_memory",
                            episode=0,
                            segment_index=idx,
                            snippet=f"{k}[{idx}]: {str(item)}",
                            source_path="story_memory.json",
                            context_type="memory",
                            scope="global_story_world",
                        ))

        # 3. Scan ALL requested episodes sequentially
        if download_dir and os.path.isdir(download_dir):
            for ep in self.episodes_requested:
                recap_file = os.path.join(download_dir, f"episode_{ep}", "recap.json")
                if os.path.isfile(recap_file):
                    try:
                        with open(recap_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, list):
                            self.episodes_loaded.append(ep)
                            self.recap_source_paths.append(recap_file)
                            for seg_idx, seg in enumerate(data):
                                if isinstance(seg, dict):
                                    speech = seg.get("speech", "")
                                    ts = seg.get("timestamp")
                                    if speech:
                                        speech_lower = speech.lower()
                                        # Scope disambiguation
                                        if re.search(r"\b(?:only|sole|last)\s+survivor(?:s)?\s+(?:in|of)\s+(?:the\s+)?(?:entire\s+|whole\s+)?(?:world|humanity|earth|civilization)\b", speech_lower) or re.search(r"\b(?:last|only)\s+(?:man|human|person)\s+(?:alive|on\s+earth)\b", speech_lower):
                                            scope = "global_story_world"
                                        elif re.search(r"\b(?:only|sole|last)\s+survivor(?:s)?\b", speech_lower):
                                            scope = "local_group"
                                        else:
                                            scope = "local_scene"

                                        self.units.append(EvidenceUnit(
                                            source="recap",
                                            episode=ep,
                                            segment_index=seg_idx,
                                            snippet=speech,
                                            source_path=recap_file,
                                            timestamp=ts,
                                            scope=scope,
                                            context_type="narration",
                                        ))
                    except Exception:
                        self.episodes_missing.append(ep)
                else:
                    self.episodes_missing.append(ep)

    def find_evidence(self, patterns: List[str], claim_key: Optional[str] = None) -> List[EvidenceUnit]:
        """
        Finds all evidence units matching patterns with semantic & POS disambiguation.
        """
        matches = []
        for unit in self.units:
            snippet_lower = unit.snippet.lower()
            for pat in patterns:
                pat_lower = pat.lower()
                if pat_lower in snippet_lower:
                    # Semantic Disambiguation Rules
                    if claim_key == "regression":
                        has_false_rewind = any(fr in snippet_lower for fr in ["rewind footage", "rewind tape", "rewind video", "rewind to", "second chance to", "flashback", "remember"])
                        has_real_regression = any(rr in snippet_lower for rr in ["regress", "past", "years before", "days before", "time travel", "time loop", "reborn"])
                        if has_false_rewind and not has_real_regression:
                            continue

                    elif claim_key in ("bunker", "bunker_claim", "mc_built_bunker"):
                        # Specificity Lattice: "vaulting", "vault over" is verb -> reject
                        if re.search(r"\bvault(?:ed|ing|s)?\s+(?:over|across|through|the|a|into|rusty|barriers?|fences?)\b", snippet_lower) or re.search(r"\b(?:creatures?|monsters?|zombies?|he|they|she|tae)\s+vault(?:ed|ing|s)?\b", snippet_lower):
                            continue
                        # "vault" noun (door/safe) != bunker
                        if pat_lower == "vault" and not any(k in snippet_lower for k in ["bunker", "fallout shelter", "underground base"]):
                            continue
                        # "sanctuary" != bunker
                        if pat_lower == "sanctuary" and not any(k in snippet_lower for k in ["bunker", "underground fortress", "hardened"]):
                            continue

                    elif claim_key == "system":
                        is_ordinary_sys = any(osys in snippet_lower for osys in ["immune system", "nervous system", "electrical system", "transit system", "sewer system", "system collapse", "sound system", "security system"])
                        has_rpg_ui = any(rpg in snippet_lower for rpg in ["status window", "window", "quest", "level up", "skill", "inventory", "glitched system", "mana"])
                        if is_ordinary_sys and not has_rpg_ui:
                            continue

                    matches.append(unit)
                    break
        return matches

    def check_claim(self, claim_key: str) -> Dict[str, Any]:
        """Validates registered claim key against EvidenceUnits."""
        if claim_key in self._claim_cache:
            return self._claim_cache[claim_key]

        defn = CLAIM_REGISTRY.get(claim_key)
        if not defn:
            result = {
                "claim": claim_key,
                "supported": False,
                "confidence": 0.0,
                "matched_units_count": 0,
                "matched_units": [],
                "matched_terms": [],
            }
            self._claim_cache[claim_key] = result
            return result

        patterns = defn["patterns"]
        canonical_patterns = defn.get("canonical_patterns", [])
        is_high_risk = defn.get("high_risk", False)

        matching_units = self.find_evidence(patterns, claim_key=claim_key)
        canonical_matches = self.find_evidence(canonical_patterns, claim_key=claim_key) if canonical_patterns else []

        distinct_unit_ids: Set[Tuple[str, int, int]] = set()
        distinct_units: List[EvidenceUnit] = []
        for u in matching_units:
            if u.unit_id not in distinct_unit_ids:
                distinct_unit_ids.add(u.unit_id)
                distinct_units.append(u)

        has_canonical = len(canonical_matches) >= 1
        num_distinct = len(distinct_units)

        if is_high_risk:
            supported = (num_distinct >= 2) or has_canonical
        else:
            supported = num_distinct >= 1

        if claim_key == "only_survivor":
            has_global_scope = any(u.scope == "global_story_world" for u in distinct_units)
            if not has_global_scope and not has_canonical:
                supported = False

        matched_terms = [p for p in patterns if any(p.lower() in u.snippet.lower() for u in matching_units)]

        result = {
            "claim": claim_key,
            "supported": supported,
            "confidence": min(1.0, num_distinct / max(1, len(patterns))),
            "matched_units_count": num_distinct,
            "matched_units": [u.to_dict() for u in distinct_units[:10]],
            "matched_terms": list(set(matched_terms)),
            "high_risk": is_high_risk,
        }
        self._claim_cache[claim_key] = result
        return result

    def _enforce_evidence_invariant(self, assertion: "SemanticAssertion") -> None:
        """
        V5 Invariant Enforcement:
        IF assertion.requires_evidence == True
        AND assertion.status == "supported"
        AND len(assertion.evidence_units) == 0
        THEN raise AssertionError — this state is prohibited.
        """
        if (
            assertion.requires_evidence
            and assertion.status == "supported"
            and len(getattr(assertion, "evidence_units", [])) == 0
        ):
            raise AssertionError(
                f"V5 INVARIANT VIOLATED: assertion '{assertion.assertion_type}' "
                f"raw_text='{assertion.raw_text}' is requires_evidence=True + "
                f"status='supported' + evidence_units=[] — this state is PROHIBITED in V5. "
                f"Every supported assertion must have at least 1 EvidenceUnit."
            )

    def verify_assertion(self, assertion: SemanticAssertion, archetype: str = "") -> bool:
        """
        Enforces Specificity Lattice and evidence verification for any SemanticAssertion.
        Returns True if supported, False otherwise.
        """
        archetype = archetype or self.archetype
        atype = assertion.assertion_type


        # 1. Day Number Verification: Episode != Story Day
        if atype == "day_number":
            day_val = assertion.value
            # Explicit evidence of Day X in story_memory or transcripts
            if self.story_memory and self.story_memory.get("day") == day_val:
                assertion.status = "supported"
                return True
            matches = self.find_evidence([f"day {day_val}", f"the {day_val}th day", f"{day_val} days later"])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:3]]
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = f"No story evidence for Day {day_val} (episode index != story day)"
            return False

        # 2. Preparation Duration: Exact or equivalent evidence required
        elif atype == "preparation_duration":
            val = assertion.value
            unit = assertion.unit
            matches = self.find_evidence([
                f"{val} {unit}", f"{val}-{unit}", f"prepared for {val} {unit}",
                f"spent {val} {unit} preparing", f"stockpiled for {val} {unit}",
                "sixteen years" if val == 16 and "year" in unit else f"{val} {unit}"
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:3]]
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = f"No explicit evidence for {val} {unit} preparation duration"
            return False

        # 3. MC Built Bunker Claim
        elif atype == "mc_built_bunker":
            matches = self.find_evidence([
                "built a bunker", "built his bunker", "constructed a bunker",
                "building a doomsday bunker", "excavated a bunker"
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:3]]
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No evidence that protagonist personally built a doomsday bunker"
            return False

        # 4. Bunker Claim (Specificity Lattice: shelter != bunker, vault != bunker)
        elif atype == "bunker_claim":
            matches = self.find_evidence(["bunker", "underground bunker", "doomsday bunker", "fallout bunker"], claim_key="bunker")
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:3]]
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "Shelter/vault/sanctuary does not support bunker claim under Specificity Lattice"
            return False

        # 5. Resource Ownership / Stockpile Control
        elif atype == "controls_stockpile":
            matches = self.find_evidence([
                "controls the stockpile", "controls all supplies", "controls all food",
                "owns the supply cache", "king of loot", "monopolizes"
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:3]]
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "Supplies existence does not prove protagonist controls/owns the stockpile"
            return False

        # 6. Global Starvation Claim
        elif atype == "global_starvation":
            matches = self.find_evidence([
                "everyone was starving", "the survivors were starving across the city",
                "mass starvation wiped out", "widespread starvation", "humanity is starving"
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:3]]
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "Local food scarcity does not support global 'Everyone Is STARVING' claim"
            return False

        # 7. Global Shelter Depletion
        elif atype == "global_shelter_depletion":
            matches = self.find_evidence([
                "the world ran out of safe shelter", "no safe shelter left in the world",
                "every shelter on earth collapsed"
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:3]]
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "Local shelter collapse does not support 'The World Ran Out of Safe Shelter'"
            return False

        # 8. Percentage Destroyed
        elif atype == "percentage_destroyed":
            chk = self.check_claim("percentage_humanity_destroyed")
            if chk["supported"]:
                assertion.status = "supported"
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = f"No evidence for {assertion.value}% destruction claim"
            return False

        # 9. Only Survivor
        elif atype == "only_survivor":
            chk = self.check_claim("only_survivor")
            if chk["supported"]:
                assertion.status = "supported"
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "Local survivor squad does not support global sole survivor claim"
            return False

        # 10. Knew Apocalypse
        elif atype == "knew_apocalypse":
            chk = self.check_claim("knew_apocalypse_beforehand")
            if chk["supported"]:
                assertion.status = "supported"
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No foreknowledge evidence in transcripts"
            return False

        # 11. Unbreakable Fortress
        elif atype == "unbreakable_fortress":
            chk = self.check_claim("unbreakable_fortress")
            if chk["supported"]:
                assertion.status = "supported"
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "Hyperbolic impenetrable fortress claim unsupported"
            return False

        # 12. Visual Assertions
        elif atype == "absolute_zero_resource":
            matches = self.find_evidence(["zero supplies", "0 shelter", "absolutely no food", "completely empty"])
            if len(matches) >= 1:
                assertion.status = "supported"
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No literal zero resource evidence for thumbnail stat badge"
            return False

        elif atype == "base_fortified":
            # V5: Evidence required — no archetype bypass allowed
            matches = self.find_evidence([
                "fortified base", "reinforced compound", "fortified compound",
                "barricaded base", "base", "shelter", "safehouse", "fortified",
                "barricade", "secured area", "safe house",
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:2]]
                self._enforce_evidence_invariant(assertion)
                return True
            # Fallback: check story_memory for explicit base mention
            if self.story_memory and any(
                k in str(self.story_memory).lower()
                for k in ["bunker", "safehouse", "shelter", "fortified", "base camp"]
            ):
                assertion.status = "supported"
                assertion.evidence_units = [{"source": "story_memory", "episode": 0,
                                             "segment_index": -1,
                                             "snippet": str(self.story_memory)[:150]}]
                self._enforce_evidence_invariant(assertion)
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No evidence of a fortified base/compound in transcripts or story_memory"
            return False

        elif atype == "containment_active":
            # V5: Evidence required — no archetype bypass allowed
            matches = self.find_evidence([
                "containment order", "containment", "quarantine order", "quarantine zone",
                "martial law", "lockdown", "sealed off", "quarantine", "isolated sector",
                "blocked", "curfew",
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:2]]
                self._enforce_evidence_invariant(assertion)
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No containment/quarantine order evidence in transcripts"
            return False

        elif atype == "threat_critical":
            # V5: Evidence required — no archetype bypass allowed
            # (archetype alone is NOT evidence; transcripts must confirm)
            matches = self.find_evidence([
                "critical threat", "swarms active", "mutant strains", "infected zone",
                "outbreak", "zombie", "threat", "danger", "disaster", "cataclysm",
                "attack", "assault", "infected", "undead", "bitten", "spreading",
                "horde", "overwhelmed", "overrun",
            ])
            if len(matches) >= 1:
                assertion.status = "supported"
                assertion.evidence_units = [m.to_dict() for m in matches[:2]]
                self._enforce_evidence_invariant(assertion)
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No critical threat level evidence in transcripts (archetype alone is not evidence)"
            return False

        elif atype == "well_stocked_base":
            matches = self.find_evidence(["well-stocked", "shelves of supplies", "stockpiled base", "full of supplies"])
            if len(matches) >= 1:
                assertion.status = "supported"
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No evidence for well-stocked secure base"
            return False

        elif atype == "visual_supernatural_aura":
            if archetype == "zombie_apocalypse":
                assertion.status = "unsupported"
                assertion.rejection_reason = "Supernatural glowing aura forbidden in realistic Zombie story"
                return False
            matches = self.find_evidence(["glowing aura", "mana aura", "awakening energy"])
            if len(matches) >= 1:
                assertion.status = "supported"
                return True
            assertion.status = "unsupported"
            assertion.rejection_reason = "No supernatural visual aura evidence"
            return False

        # 13. Unknown High-Impact (Fail-Closed)
        elif atype == "unknown_high_impact":
            assertion.status = "unsupported"
            assertion.rejection_reason = "Unknown high-impact assertion without registered validator (Fail-Closed)"
            return False

        assertion.status = "unsupported"
        assertion.rejection_reason = f"Unhandled assertion type '{atype}'"
        return False

    def validate_candidate(self, candidate_text: str, archetype: str) -> bool:
        """Validates a single candidate title/claim string against evidence and assertion pipeline."""
        res = validate_text_surface(candidate_text, self, archetype, surface_type="title_candidate")
        return res["passed"]

    def validate_all_candidates(
        self, candidates: Dict[str, str], archetype: str
    ) -> Dict[str, Dict[str, Any]]:
        """Validates all candidate titles and returns detailed audit trails."""
        results = {}
        for key, text in candidates.items():
            res = validate_text_surface(text, self, archetype, surface_type=f"title_{key}")
            results[key] = {
                "passed": res["passed"],
                "candidate": text,
                "rejected_claims": res["violations"],
                "assertions_detected": res["assertions_detected"],
                "assertions_validated": res["assertions_validated"],
                "assertions_supported": res["assertions_supported"],
                "assertions_unsupported": res["assertions_unsupported"],
                "assertion_details": [a.to_dict() for a in res["assertions"]],
            }
        return results


# =============================================================================
# UNIFIED TEXT SURFACE VALIDATOR — Assertion Coverage Invariant Enforced
# =============================================================================

def validate_text_surface(
    text: str,
    evidence_index: EvidenceIndex,
    archetype: str,
    surface_type: str = "generic",
) -> Dict[str, Any]:
    """
    Unified surface validator used across titles, descriptions, chapters,
    thumbnails, prompts, tags, pinned comments, and dashboard fields.
    Enforces DETECTED ASSERTION == VALIDATED ASSERTION invariant.
    """
    violations: List[str] = []
    forbidden = ARCHETYPE_FORBIDDEN_CLAIMS.get(archetype, [])
    text_lower = text.lower()

    # 1. Registered Claim & Pattern Scan
    for pat, claim_key in TITLE_CLAIM_MAP.items():
        if claim_key in forbidden:
            if re.search(pat, text_lower, re.IGNORECASE):
                check = evidence_index.check_claim(claim_key)
                if not check["supported"]:
                    violations.append(f"Forbidden claim '{claim_key}' for archetype '{archetype}'")
        else:
            claim_def = CLAIM_REGISTRY.get(claim_key, {})
            if claim_def.get("high_risk", False):
                if re.search(pat, text_lower, re.IGNORECASE):
                    check = evidence_index.check_claim(claim_key)
                    if not check["supported"]:
                        violations.append(f"Unsupported high-risk claim '{claim_key}'")

    # 2. Strict Cross-Archetype Blacklist for Zombie
    if archetype == "zombie_apocalypse":
        zombie_cross_kws = [
            (r"\bsss[\s\-]?rank\b", "SSS-Rank in Zombie story"),
            (r"\btrainee\b", "Trainee in Zombie story"),
            (r"\bacademy\b", "Academy in Zombie story"),
            (r"\bcultivation\b", "Cultivation in Zombie story"),
            (r"\bdanjeon\b", "Danjeon in Zombie story"),
            (r"\bheavenly\s+demon\b", "Heavenly Demon in Zombie story"),
            (r"\btower\s+trials\b|\bendless\s+ascent\b", "Tower Trials in Zombie story"),
            (r"\bcalamity\s+gate\b|\bsolo\s+awakening\b", "Calamity Gate in Zombie story"),
            (r"\bglowing\s+aura\b|\bsss\s+energy\b", "Fake visual promise in Zombie story"),
            (r"\b100%\s+drop\b|\bking\s+of\s+loot\b", "Drop rate / King of loot in Zombie story"),
            (r"\bgod[\s\-]tier\b", "God-tier hyperbolic claim in Zombie story"),
            (r"\bdoomsday\s+bunker\b|\b16\s+years\s+preparing\b", "Bunker prepper narrative in realistic zombie story"),
        ]
        for kw_pat, reason in zombie_cross_kws:
            if re.search(kw_pat, text_lower, re.IGNORECASE):
                violations.append(reason)

    # 3. Semantic Assertion Verification & Invariant Enforcement
    assertions = extract_semantic_assertions(text, surface_type=surface_type)
    detected_count = len(assertions)
    validated_count = 0
    supported_count = 0
    unsupported_count = 0

    for assertion in assertions:
        is_supported = evidence_index.verify_assertion(assertion, archetype)
        validated_count += 1
        if is_supported:
            supported_count += 1
        else:
            unsupported_count += 1
            violations.append(f"Unsupported assertion [{assertion.assertion_type}]: '{assertion.raw_text}' ({assertion.rejection_reason})")

    # Invariant: detected_assertions == validated_assertions
    if detected_count != validated_count:
        violations.append(f"Assertion coverage gap: {detected_count} detected vs {validated_count} validated")

    # V5 Fix A: "0 detected == 0 validated" cannot grant PASS when text has factual phrases.
    # These patterns carry factual weight but may not trigger extract_semantic_assertions().
    # If any are found unaccounted-for, the surface must fail.
    FACTUAL_PHRASE_INDICATORS = [
        (r'\bwiped\s+out\b',                         "wiped-out claim"),
        (r'\bonly\s+survivor\b',                     "only-survivor claim"),
        (r'\bsole\s+survivor\b',                     "sole-survivor claim"),
        (r'\blast\s+survivor\b',                     "last-survivor claim"),
        (r'\bunbreakable\b',                         "unbreakable absolute claim"),
        (r'\bgod[\s\-]tier\b',                       "god-tier hyperbolic claim"),
        (r'\b100\s*%\s+of\s+(?:humanity|population|the\s+world)\b', "100%-destroyed claim"),
        (r'\bwiped\s+out\s+\d+\s*%\b',              "percentage-wiped-out claim"),
        (r'\ball\s+of\s+humanity\s+(?:is\s+)?(?:gone|dead|destroyed|wiped)\b', "all-humanity-dead claim"),
        (r'\bhe\s+knew\s+(?:the\s+)?(?:apocalypse|disaster|outbreak)\s+was\s+coming\b', "foreknowledge claim"),
    ]
    if detected_count == 0:
        # Only do this check when no assertions were found (the false-pass risk case)
        for pattern, label in FACTUAL_PHRASE_INDICATORS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                violations.append(
                    f"V5: Factual phrase detected but NOT caught by assertion scanner: "
                    f"'{label}' in text. '0 detected == 0 validated' cannot grant PASS "
                    f"when text contains factual claims."
                )

    passed = len(violations) == 0

    return {
        "passed": passed,
        "surface_type": surface_type,
        "violations": list(set(violations)),
        "assertions_detected": detected_count,
        "assertions_validated": validated_count,
        "assertions_supported": supported_count,
        "assertions_unsupported": unsupported_count,
        "assertions": assertions,
        "text": text,
    }


# =============================================================================
# ARCHETYPE DETECTION
# =============================================================================

def detect_archetype(comic_title: str, story_memory: Optional[Dict[str, Any]] = None) -> str:
    """Detects the manhwa archetype/subgenre for tailored metadata generation."""
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

    # Priority 2: Specific token groups
    if any(k in combined for k in ["zombie", "infected", "undead", "ghoul", "plague", "virus", "outbreak", "82-08", "8208", "walking dead"]):
        return "zombie_apocalypse"
    elif any(k in combined for k in ["bunker", "shelter", "prepper", "shut-in", "shutin", "warehouse", "hoard"]):
        return "bunker_prepper"
    elif any(k in combined for k in ["freeze", "freezing", "frozen", "frost", "ice age", "eternal winter", "blizzard"]):
        return "bunker_prepper"
    elif any(k in combined for k in ["return stone", "regression stone", "floor 100", "chaos wasteland", "anti-regression", "world after the fall"]):
        return "tower_anti_regression"
    elif any(k in combined for k in ["game become", "vr game", "game reality", "virtual reality", "player", "npc", "game world", "logged in", "tutorial"]):
        return "game_system_reality"
    elif any(k in combined for k in ["regression", "regress", "second chance", "time travel", "rewind", "went back", "returned to", "before the apocalypse"]):
        return "regression_prep"
    # "build" removed — too broad, matches bunker/base-building stories; remaining keywords are farming-specific
    elif any(k in combined for k in ["farming", "kingdom", "territory", "village", "agriculture", "lord", "baron", "domain", "settlement"]):
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
    generic_words = ["a", "an", "the", "he", "she", "they", "we", "our", "him", "his", "her", "their", "it", "its", "protagonist", "mc", "unknown", "hero", "guy", "man"]
    if story_memory:
        raw_mc = story_memory.get("protagonist_name", "").strip()
        if raw_mc and len(raw_mc) > 1 and raw_mc.lower() not in generic_words:
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
        elif "veteran of the apocalypse" in title_lower or title_lower.strip().startswith("veteran of"):
            mc_name = "Kang Seongho"
        elif any(k in title_lower for k in ["zombie", "82-08", "8208"]):
            mc_name = "Tae"
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
# EPISODE THEME EXTRACTION & CHAPTER DECOMPOSITION
# =============================================================================

def validate_chapter_theme(theme: str, archetype: str) -> bool:
    """Validates that a chapter theme does not contain cross-archetype leaks."""
    theme_lower = theme.lower()
    if archetype == "zombie_apocalypse":
        forbidden = [
            "tower", "endless ascent", "calamity gate", "solo awakening",
            "dungeon", "cultivation", "heavenly demon", "sss", "rank 1",
            "trainee", "danjeon", "system awakening"
        ]
        if any(f in theme_lower for f in forbidden):
            return False
    elif archetype == "bunker_prepper":
        forbidden = ["tower", "endless ascent", "cultivation", "heavenly demon", "sss", "trainee"]
        if any(f in theme_lower for f in forbidden):
            return False
    elif archetype == "farming_kingdom":
        forbidden = ["tower", "cultivation", "heavenly demon", "sss"]
        if any(f in theme_lower for f in forbidden):
            return False
    return True


THEME_COMPONENT_REGISTRY = {
    # Format: theme_name -> [(comp_name, word_boundary_tokens, exact_phrases)]
    # word_boundary_tokens: matched with \b..\b — prevents false positives:
    #   'training'->rain, 'cold stare'->cold/winter, 'steps into'->stairwell,
    #   'bloodied'->bloodbath, 'sanctuary'->church, 'weapon platform'->subway/train
    # exact_phrases: multi-word, matched as exact substrings
    "The Church Stairwell Betrayal": [
        ("church",    ["church", "chapel", "cathedral"],    ["the sanctuary church", "inside the chapel"]),
        ("stairwell", ["stairwell", "staircase"],           ["up the stairs", "down the stairs", "stair landing", "flight of stairs"]),
        ("betrayal",  ["betray", "coward"],                 ["locked out", "shut the door", "left behind", "abandoned him"]),
    ],
    "Midnight Rain & Shadow Stalker": [
        ("rain",    ["rain", "downpour", "deluge"],    ["it\'s raining", "rain pours", "midnight rain", "rain falls"]),
        ("stalker", ["stalker", "predator", "lurk"],   ["shadow creature", "in the shadows", "stalked by"]),
    ],
    "Atomic Research Station in the Deluge": [
        ("atomic_research", ["atomic", "nuclear", "perimeter"],   ["research station", "research lab", "nuclear facility"]),
        ("deluge",          ["deluge", "flooding"],                ["heavy rain", "flood water", "storm flood", "rising water"]),
    ],
    "The Outbreak & Boat 82-08 Incident": [
        ("outbreak",  ["outbreak", "infection", "virus", "patient"],  ["patient zero", "infection spreads"]),
        ("boat_8208", ["vessel", "ocean"],                             ["82-08", "boat 82", "the ship", "on the boat", "aboard"]),
    ],
    "Martial Law & First Encounters": [
        ("martial_law",      ["conscript"],              ["martial law", "military broadcast"]),
        ("first_encounters", ["chopper", "helicopter"],  ["first encounter", "infected screams", "screams outside"]),
    ],
    "Syndicate Enforcers & Urban Collapse": [
        ("syndicate",      ["syndicate", "enforcer", "thug", "mob"],  ["gang members", "criminal syndicate"]),
        ("urban_collapse", [],                                          ["city collapse", "streets overrun", "city falls"]),
    ],
    "Subway Descent & Platform Bloodbath": [
        ("subway",    ["subway", "platform", "tracks"],               ["subway station", "train station", "underground platform"]),
        ("bloodbath", ["bloodbath", "slaughter", "carnage"],          ["mass slaughter", "platform massacre", "bodies everywhere"]),
    ],
    "Winter Onslaught & Freezing Ambush": [
        ("winter",  ["blizzard", "frost", "winter", "freeze"],  ["freezing cold", "bitter cold", "winter storm", "frozen wasteland"]),
        ("ambush",  ["ambush", "onslaught"],                    ["surprise attack", "ambushed by", "overwhelmed by horde"]),
    ],
    "Quarantine Breach & Mutant Lab Collapse": [
        ("quarantine", ["quarantine", "biolab"],    ["research lab", "mutant lab", "quarantine breach"]),
        ("mutant",     ["mutant", "monstrosity"],   ["awakened monster", "mutant outbreak", "lab breach"]),
    ],
    "Convoy Ambush & The Canister Race": [
        ("convoy",   ["convoy", "transport"],  ["supply convoy", "convoy ambush", "armored truck"]),
        ("canister", ["canister"],             ["the race for", "secure the cargo", "cargo run"]),
    ],
}



def _kw_match_word_boundary(text_lower: str, words: List[str], phrases: List[str]) -> bool:
    """
    V5 word-boundary safe keyword matching — prevents false positives.

    - words: matched with \\b..\\b (word boundary for single tokens).
      Prevents: 'training'->rain, 'steps into'->stairwell,
                'cold stare'->cold (winter), 'sanctuary'->church,
                'bloodied'->bloodbath, 'weapon platform'->subway/train.
    - phrases: exact substring match (multi-word; natural word boundaries).

    Returns True if ANY word OR phrase matches.
    """
    for w in words:
        if re.search(r'\b' + re.escape(w) + r'\b', text_lower):
            return True
    for ph in phrases:
        if ph.lower() in text_lower:
            return True
    return False


def extract_episode_theme_with_snippet(
    recap_path: str,
    ep: int,
    comic_title: str = "",
    archetype: str = "general_apocalypse",
) -> Tuple[str, Optional[str], List[Dict[str, Any]]]:
    """
    Extracts a punchy narrative theme for an episode, verifies core semantic components,
    and returns (theme, primary_snippet, evidence_list_per_assertion).
    """
    if not os.path.isfile(recap_path):
        return f"Survival Operation (Ep {ep})", None, []
    try:
        with open(recap_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return f"Survival Operation (Ep {ep})", None, []

    if not data or not isinstance(data, list):
        return f"Survival Operation (Ep {ep})", None, []

    speech_segments = [item.get("speech", "") for item in data if isinstance(item, dict) and item.get("speech")]
    if not speech_segments:
        return f"Survival Operation (Ep {ep})", None, []

    full_speech = " ".join(speech_segments)
    lower_speech = full_speech.lower()

    # Match predefined themes with component decomposition (V5: word-boundary safe)
    for theme_name, components in THEME_COMPONENT_REGISTRY.items():
        if not validate_chapter_theme(theme_name, archetype):
            continue

        comp_evidence = []
        all_comps_found = True
        for comp_name, words, phrases in components:
            found_seg = None
            for seg in speech_segments:
                seg_lower = seg.lower()
                if _kw_match_word_boundary(seg_lower, words, phrases):
                    found_seg = seg
                    break
            if found_seg:
                comp_evidence.append({
                    "assertion": comp_name,
                    "episode": ep,
                    "snippet": found_seg[:200],
                })
            else:
                all_comps_found = False
                break

        if all_comps_found and len(comp_evidence) == len(components):
            return theme_name, comp_evidence[0]["snippet"], comp_evidence

    # Fallback: clean action phrase with incomplete object repair
    first_sent = re.split(r"[.!?]", speech_segments[0])[0].strip()
    first_sent = re.sub(r"^(while|as|spotting|even with|with|after)\s+[^,]+,\s*", "", first_sent, flags=re.IGNORECASE)
    first_sent = re.sub(r"^(south|tae|he|they|she|the hero|the survivor|[a-z]+-?[a-z]*)\s+(watches|scrambles|lunges|braces|realizes|slices|slams|freezes|frantically|doesn\'t waste|doesn\'t hesitate|locks|lets|steps|dashes)\s+[^,\.]*?(?:as|when|that|to)?\s*", "", first_sent, flags=re.IGNORECASE)
    first_sent = re.sub(r"[,:;]+$", "", first_sent).strip()
    words = first_sent.split()

    STOP_WORDS = {
        "on", "at", "to", "in", "of", "for", "with", "from", "as",
        "by", "the", "a", "an", "and", "or", "so", "than", "against", "but"
    }
    DANGLING_MODIFIERS = {"incoming", "approaching", "advancing", "remaining", "unknown", "nearby", "rushing"}

    if 2 <= len(words) <= 7:
        clean_theme = " ".join(words).title()
    elif len(words) > 7:
        clean_theme = None
        for cut in range(7, 4, -1):
            if cut > len(words):
                continue
            last_w = words[cut - 1].rstrip(",:;").lower()
            if last_w not in STOP_WORDS and last_w not in DANGLING_MODIFIERS:
                clean_theme = " ".join(words[:cut]).title()
                break
        if not clean_theme:
            phrase = list(words[:6])
            while phrase and (phrase[-1].lower() in STOP_WORDS or phrase[-1].lower() in DANGLING_MODIFIERS):
                phrase.pop()
            clean_theme = " ".join(phrase).title() if phrase else f"Survival Operation (Ep {ep})"
    else:
        clean_theme = f"Survival Operation (Ep {ep})"

    clean_theme = re.sub(r"[^a-zA-Z0-9\s\-–—\':]", "", clean_theme).strip()
    clean_theme = re.sub(r"\s+(?:On|At|To|In|Of|For|With|From|As|By|The|A|An|And|Or|So|Than|Against|But|Incoming|Approaching|Advancing)$", "", clean_theme, flags=re.IGNORECASE).strip()

    if not validate_chapter_theme(clean_theme, archetype) or len(clean_theme) <= 3:
        clean_theme = f"Survival Operation (Ep {ep})"

    evidence_list = [{"assertion": "general_action", "episode": ep, "snippet": speech_segments[0][:200]}]
    return clean_theme, speech_segments[0], evidence_list


def extract_episode_theme(
    recap_path: str,
    ep: int,
    comic_title: str = "",
    archetype: str = "general_apocalypse",
) -> str:
    """Backward-compatible wrapper returning only the theme string."""
    theme, _, _ = extract_episode_theme_with_snippet(recap_path, ep, comic_title, archetype)
    return theme


def build_narrative_story_chapters(
    chapters: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]],
    download_dir: Optional[str] = None,
    comic_title: str = "Comic",
    archetype: str = "general_apocalypse",
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[Dict[str, Any]]:
    """
    Builds narrative story chapters grouped by video story progression arcs.
    Fail-Closed: If chapters is None, empty, or lacks valid timestamps, returns [] to avoid fabricating false timestamps.
    Uses window-based grounding: each chapter [start_ep, end_ep] only extracts themes
    from recap files in that exact episode window with decomposed semantic evidence.
    """
    if not chapters:
        return []

    # Handle dictionary input (e.g. stage11_timeline_and_chapter_markers.json)
    if isinstance(chapters, dict):
        marker_dict = chapters.get("chapter_markers", {})
        if isinstance(marker_dict, dict):
            raw_input = (
                marker_dict.get("series_143_arc_milestones")
                or marker_dict.get("episodes_1_5_video_timeline")
                or (list(marker_dict.values())[0] if marker_dict else [])
            )
        else:
            raw_input = (
                chapters.get("series_143_arc_milestones")
                or chapters.get("chapters")
                or []
            )
    elif isinstance(chapters, list):
        raw_input = chapters
    else:
        return []

    if not raw_input or not isinstance(raw_input, list):
        return []

    # Grounding validation: every chapter item must have a non-empty timestamp string
    # Never invent timestamps!
    for ch in raw_input:
        if not isinstance(ch, dict):
            return []
        ts_val = ch.get("timestamp")
        if ts_val is None or str(ts_val).strip() == "":
            return []

    num_input_chapters = len(raw_input)
    span_eps = to_ep - from_ep + 1
    prog_list = [
        "Outbreak & Patient Zero",
        "The Barricades & Sector Defense",
        "Road Ambush & Escape",
        "Mutated Predators & Swarm Attack",
        "Quarantine Zone Breach",
        "Gathering Survivors",
        "Underground Safehouse Infiltration",
        "Perimeter Defense Fall",
        "The Swarm Overruns The City",
        "Final Stand Over The Ruins",
    ] if archetype == "zombie_apocalypse" else [
        "Cataclysm Warning & Shelter Prep",
        "The Wasteland Ambush",
        "Resource Competition",
        "Safe Zone Fortification",
        "Climax Under Siege",
        "Dawn of Control",
    ]

    # If input chapters is already a sampled list (e.g. 1 to 12 milestone chapters from Stage 11)
    if num_input_chapters <= 12:
        num_arcs = num_input_chapters
        is_direct_mapping = True
    elif span_eps >= 35 or num_input_chapters >= 35:
        num_arcs = min(10, num_input_chapters)
        is_direct_mapping = False
    elif span_eps >= 16 or num_input_chapters >= 16:
        num_arcs = min(8, num_input_chapters)
        is_direct_mapping = False
    elif span_eps >= 7 or num_input_chapters >= 7:
        num_arcs = min(6, num_input_chapters)
        is_direct_mapping = False
    elif span_eps >= 3 or num_input_chapters >= 3:
        num_arcs = min(span_eps, num_input_chapters, 4)
        is_direct_mapping = False
    else:
        num_arcs = num_input_chapters
        is_direct_mapping = True

    # Backward compatibility with small 2-chapter tests without download_dir
    if num_input_chapters <= 2 and not download_dir and all(ch.get("title", "").strip().lower().startswith("episode") for ch in raw_input):
        return [
            {
                "timestamp": ch.get("timestamp", "00:00" if i == 0 else ""),
                "title": ch.get("title", f"Episode {ch.get('episode', i + 1)}"),
                "episode": ch.get("start_episode", ch.get("episode", i + 1)),
                "end_episode": ch.get("end_episode", ch.get("episode", i + 1)),
                "source_episode_range": ch.get("episode_range") or (f"Ep {ch.get('episode', i + 1)}" if ch.get("episode") else f"{i + 1}"),
                "theme": ch.get("title", f"Episode {ch.get('episode', i + 1)}"),
                "evidence": [],
                "grounded": bool(ch.get("timestamp") not in (None, "")),
            }
            for i, ch in enumerate(raw_input)
        ]

    result = []
    used_themes: Set[str] = set()

    for k in range(num_arcs):
        if is_direct_mapping:
            ch_curr = raw_input[k]
            start_ep = ch_curr.get("start_episode", ch_curr.get("episode", from_ep + k))
            if "end_episode" in ch_curr:
                end_ep = ch_curr["end_episode"]
            elif k < num_arcs - 1:
                next_ep = raw_input[k + 1].get("start_episode", raw_input[k + 1].get("episode", start_ep + 1))
                end_ep = max(start_ep, next_ep - 1)
            else:
                end_ep = max(start_ep, to_ep)
            ts = ch_curr.get("timestamp", "00:00" if k == 0 else "")
            ep_range_field = ch_curr.get("episode_range")
            raw_title = ch_curr.get("title", "")
        else:
            start_idx = round(k * num_input_chapters / num_arcs)
            end_idx = min(num_input_chapters - 1, round((k + 1) * num_input_chapters / num_arcs) - 1)
            if end_idx < start_idx:
                end_idx = start_idx
            ch_start = raw_input[start_idx]
            ch_end = raw_input[end_idx]
            start_ep = ch_start.get("start_episode", ch_start.get("episode", start_idx + from_ep))
            end_ep = ch_end.get("end_episode", ch_end.get("episode", end_idx + from_ep))
            ts = ch_start.get("timestamp", "00:00" if k == 0 else "")
            ep_range_field = ch_start.get("episode_range")
            raw_title = ch_start.get("title", "")

        # Grounded episode range extraction
        if ep_range_field:
            source_episode_range = str(ep_range_field)
        elif start_ep == end_ep:
            source_episode_range = f"Ep {start_ep}"
        else:
            source_episode_range = f"Ep {start_ep}–{end_ep}"

        # Window-based extraction: scan episodes in [start_ep, end_ep]
        chosen_theme = None
        chapter_evidence = []
        if download_dir and os.path.isdir(download_dir):
            for ep_curr in range(start_ep, end_ep + 1):
                recap_path = os.path.join(download_dir, f"episode_{ep_curr}", "recap.json")
                if os.path.isfile(recap_path):
                    cand_theme, snippet, comp_evs = extract_episode_theme_with_snippet(recap_path, ep_curr, comic_title, archetype)
                    if cand_theme and validate_chapter_theme(cand_theme, archetype) and cand_theme not in used_themes and not cand_theme.startswith("Chapter"):
                        chosen_theme = cand_theme
                        chapter_evidence = comp_evs
                        break

        if not chosen_theme and raw_title and not raw_title.lower().startswith("episode"):
            # Preserve existing meaningful Stage 11 CTR title
            cand = re.sub(r"\s*\(Ep.*?\)$", "", raw_title).strip()
            if cand and cand not in used_themes:
                chosen_theme = cand

        if not chosen_theme:
            theme_idx = min(len(prog_list) - 1, round(k * (len(prog_list) - 1) / max(1, num_arcs - 1)))
            base_theme = prog_list[theme_idx]
            if base_theme not in used_themes and validate_chapter_theme(base_theme, archetype):
                chosen_theme = base_theme
            else:
                for cand in prog_list:
                    if cand not in used_themes and validate_chapter_theme(cand, archetype):
                        chosen_theme = cand
                        break

        if not chosen_theme:
            chosen_theme = f"Survival Operation (Eps {start_ep}–{end_ep})"

        used_themes.add(chosen_theme)
        ep_label = f"Ep {start_ep}" if start_ep == end_ep else f"Ep {start_ep}–{end_ep}"
        title = f"{chosen_theme} ({ep_label})" if not chosen_theme.endswith(f"({ep_label})") else chosen_theme

        is_grounded = bool(ts is not None and str(ts).strip() != "")

        result.append({
            "timestamp": ts,
            "title": title,
            "episode": start_ep,
            "end_episode": end_ep,
            "source_episode_range": source_episode_range,
            "theme": chosen_theme,
            "evidence": chapter_evidence,
            "grounded": is_grounded,
        })

    return result


# =============================================================================
# TITLE FORMATTER & PLACEHOLDERS
# =============================================================================

TITLE_TARGET_MAX = 95
TITLE_HARD_MAX = 100
TITLE_SUFFIX = " | Manhwa Recap"


def format_recap_title(base_title: str, suffix: str = TITLE_SUFFIX) -> str:
    """
    Ensures the title ends with ' | Manhwa Recap' and fits within 80-95 chars
    (hard max 100), preserving word boundaries and stripping dangling stop words.
    """
    cleaned = base_title.strip()
    if cleaned.lower().endswith("manhwa recap"):
        cleaned = re.sub(r"[\s\-\|]+manhwa recap$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(" -|")
    target = f"{cleaned}{suffix}"
    if len(target) > TITLE_HARD_MAX:
        max_base_len = TITLE_HARD_MAX - len(suffix)
        truncated = cleaned[:max_base_len]
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        cleaned = truncated.rstrip(" .,-|")
        cleaned = re.sub(r"\s+(?:On|At|To|In|Of|For|With|From|As|By|The|A|An|And|Or|So|Than|Against|After|Before|Until|Is|Was)$", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+(?:On|At|To|In|Of|For|With|From|As|By|The|A|An|And|Or|So|Than|Against|After|Before|Until|Is|Was)$", "", cleaned, flags=re.IGNORECASE).strip()
        return f"{cleaned.rstrip(' .,-|')}{suffix}"
    return target


class SafeFormatDict(dict):
    """Dict subclass that returns '{key}' for missing keys instead of raising KeyError."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


# =============================================================================
# STORY BEATS EXTRACTION — ZERO FACTUAL ARCHETYPE DEFAULTS
# =============================================================================

def _extract_story_beats(
    comic_title: str,
    archetype: str,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> Dict[str, str]:
    """
    Extracts actual story beats and grounded entity facts from recap.json and story_memory.
    CRITICAL RULE: Dynamic Story Grounding without hardcoded assumptions.
    Flexes attributes per manhwa series and episode range.
    """
    beats: Dict[str, str] = {}
    title_lower = (comic_title or "").lower()

    # 1. Resolve MC name and role
    mc_resolved = get_character_names(comic_title, story_memory)["mc"]
    beats["mc_name"] = mc_resolved

    # 2. Aggregate text from story_memory (focused on from_ep..to_ep) and transcripts
    aggregated_text_list: List[str] = []
    ep_opening_first = ""
    ep_closing_last = ""

    if story_memory and isinstance(story_memory, dict):
        episodes_dict = story_memory.get("episodes", {})
        if isinstance(episodes_dict, dict):
            for ep_key, ep_data in episodes_dict.items():
                try:
                    ep_num = int(ep_key)
                except (ValueError, TypeError):
                    ep_num = 1
                if from_ep <= ep_num <= to_ep and isinstance(ep_data, dict):
                    op = str(ep_data.get("opening", ""))
                    sm = str(ep_data.get("summary", ""))
                    cl = str(ep_data.get("closing_cliffhanger", ""))
                    if not ep_opening_first and op:
                        ep_opening_first = op
                    if cl:
                        ep_closing_last = cl
                    aggregated_text_list.append(f"{op} {sm} {cl}")

        glossary = story_memory.get("cumulative_glossary", {})
        if isinstance(glossary, dict):
            aggregated_text_list.extend(glossary.keys())

    if download_dir and os.path.isdir(download_dir):
        for ep in range(from_ep, to_ep + 1):
            recap_file = os.path.join(download_dir, f"episode_{ep}", "recap.json")
            if os.path.isfile(recap_file):
                try:
                    with open(recap_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for seg in data:
                            if isinstance(seg, dict):
                                sp = seg.get("speech", "")
                                if sp:
                                    aggregated_text_list.append(sp)
                except Exception:
                    pass

    full_text = f"{title_lower} {' '.join(aggregated_text_list)}".lower()

    # 3. Dynamic Disaster Name Detection
    if any(k in full_text for k in ["asteroid", "meteorite", "meteor", "eunjambi"]):
        beats["disaster"] = "The Asteroid Impact"
        beats["disaster_event"] = "Asteroid Impact"
    elif any(k in full_text for k in ["freeze", "frozen", "frost", "blizzard", "ice age", "sub-zero", "subzero"]):
        beats["disaster"] = "The Global Freeze"
        beats["disaster_event"] = "Global Freeze"
    elif any(k in full_text for k in ["zombie", "infected", "undead", "plague", "82-08", "8208", "quarantine"]):
        beats["disaster"] = "The Zombie Outbreak"
        beats["disaster_event"] = "Zombie Outbreak"
    elif any(k in full_text for k in ["dungeon", "gate", "abyss", "rift", "hunter"]):
        beats["disaster"] = "The Dungeon Break"
        beats["disaster_event"] = "Dungeon Break"
    elif any(k in full_text for k in ["tower", "floor 100", "anti-regression"]):
        beats["disaster"] = "The Tower Collapse"
        beats["disaster_event"] = "Tower Collapse"
    elif any(k in full_text for k in ["murim", "martial arts", "sect", "cultivation"]):
        beats["disaster"] = "The Sect Betrayal"
        beats["disaster_event"] = "Sect Betrayal"
    else:
        beats["disaster"] = "The Apocalypse"
        beats["disaster_event"] = "The Apocalypse"

    # 4. Dynamic MC Role / Title
    if any(k in full_text for k in ["veteran", "military", "combat veteran"]):
        beats["mc_role"] = "Veteran"
    elif any(k in full_text for k in ["hunter", "awakener", "rank 1", "s-rank", "sss-rank"]):
        beats["mc_role"] = "SSS-Rank Hunter"
    elif any(k in full_text for k in ["prepper", "hoarder", "stockpile"]):
        beats["mc_role"] = "SSS-Rank Prepper"
    elif any(k in full_text for k in ["exile", "farming", "kingdom", "lord"]):
        beats["mc_role"] = "Exiled Lord"
    elif any(k in full_text for k in ["necromancer", "shadow monarch"]):
        beats["mc_role"] = "Shadow Monarch"
    else:
        beats["mc_role"] = "Lone Survivor"

    # 5. Dynamic Shelter / Base / Fortress
    if "bunker" in full_text:
        beats["shelter"] = "High-Tech Bunker"
        beats["fortress"] = "a Fortified Bunker"
        beats["prep_action"] = "Building a High-Tech Bunker"
    elif any(k in full_text for k in ["mountain", "jiri", "sanctuary"]):
        beats["shelter"] = "Mountain Sanctuary"
        beats["fortress"] = "a Mountain Sanctuary"
        beats["prep_action"] = "Fortifying His Mountain Sanctuary"
    elif any(k in full_text for k in ["rooftop", "safehouse", "penthouse"]):
        beats["shelter"] = "Fortified Safehouse"
        beats["fortress"] = "a Fortified Safehouse"
        beats["prep_action"] = "Fortifying His Safehouse"
    elif any(k in full_text for k in ["domain", "kingdom", "village"]):
        beats["shelter"] = "Kingdom Domain"
        beats["fortress"] = "an Unstoppable Kingdom"
        beats["prep_action"] = "Building an Unstoppable Kingdom"
    else:
        beats["shelter"] = "Fortified Base"
        beats["fortress"] = "a Fortified Base"
        beats["prep_action"] = "Preparing for The Apocalypse"

    # 6. Dynamic Companion / Pet Name
    if "dingo" in full_text:
        beats["pet_name"] = "Dingo"
        beats["companion_name"] = "His Loyal Pup Dingo"
    elif any(k in full_text for k in ["wolf", "hound", "pup", "dog"]):
        beats["pet_name"] = "Mutated Hound"
        beats["companion_name"] = "His Mutated Companion"
    elif "migyeong" in full_text:
        beats["pet_name"] = ""
        beats["companion_name"] = "Migyeong"
    elif "elena" in full_text:
        beats["pet_name"] = ""
        beats["companion_name"] = "Elena"
    else:
        beats["pet_name"] = ""
        beats["companion_name"] = ""

    # 7. Dynamic Boss / Monster / Threat
    # NOTE: bare "owl" excluded — too broad (matches "owl creek", NPC names etc.)
    # Only match compound noun "owl bear" or hyphenated "owl-bear"
    if any(k in full_text for k in ["owl bear", "owl-bear"]):
        beats["boss_name"] = "The Colossal Owl Bear"
        beats["monster_type"] = "Colossal Apex Beast"
    elif any(k in full_text for k in ["skeleton", "skull", "undead king"]):
        beats["boss_name"] = "The Skeleton Chieftain"
        beats["monster_type"] = "Undead Boss"
    elif any(k in full_text for k in ["red alpha", "alpha beast"]):
        beats["boss_name"] = "The Red Alpha"
        beats["monster_type"] = "Apex Alpha Beast"
    elif any(k in full_text for k in ["orc", "goblin", "chieftain"]):
        beats["boss_name"] = "The Mutant Chieftain"
        beats["monster_type"] = "Mutant Horde"
    elif any(k in full_text for k in ["zombie", "infected titan"]):
        beats["boss_name"] = "The Mutated Titan"
        beats["monster_type"] = "Infected Swarm"
    else:
        beats["boss_name"] = "The Apex Beast"
        beats["monster_type"] = "Apex Predator"

    # 8. Dynamic Rival / Human Conflict / Betrayer
    if "hyeongjun" in full_text:
        beats["rival_name"] = "Hyeongjun's Thugs"
        beats["villain_type"] = "Awakened Thugs"
        beats["betrayer"] = "Hyeongjun's Gang"
    elif any(k in full_text for k in ["politician", "corrupt suit", "shady suit"]):
        beats["rival_name"] = "Corrupt Politicians"
        beats["villain_type"] = "Corrupt Leaders"
        beats["betrayer"] = "Corrupt Officials"
    elif any(k in full_text for k in ["raider", "bandit", "scavenger"]):
        beats["rival_name"] = "Awakened Raiders"
        beats["villain_type"] = "Armed Raiders"
        beats["betrayer"] = "Ruthless Raiders"
    elif any(k in full_text for k in ["betray", "traitor", "backstab", "left for dead"]):
        beats["rival_name"] = "Treacherous Allies"
        beats["villain_type"] = "Traitors"
        beats["betrayer"] = "His Own Allies"
    else:
        beats["rival_name"] = "Corrupt Survivors"
        beats["villain_type"] = "Hostile Survivors"
        beats["betrayer"] = "Corrupt Survivors"

    # 9. Dynamic Primary Weapon
    if any(k in full_text for k in ["recurve bow", "bow", "arrow"]):
        beats["primary_weapon"] = "His Recurve Bow"
    elif any(k in full_text for k in ["spiked club", "baseball bat", "club"]):
        beats["primary_weapon"] = "A Spiked Club"
    elif "spear" in full_text:
        beats["primary_weapon"] = "A Reinforced Spear"
    elif any(k in full_text for k in ["chainsaw", "chain saw"]):
        beats["primary_weapon"] = "Dual Chainsaws"
    elif any(k in full_text for k in ["blade", "sword", "dagger"]):
        beats["primary_weapon"] = "A Survival Blade"
    else:
        beats["primary_weapon"] = "Tactical Survival Gear"

    # 10. Additional Supporting Slots
    m_prep = re.search(r"\b(\d+)\s*(years?|months?|days?)\s+(?:of\s+)?training\b|\bprepared\s+for\s+(\d+)\s*(years?|months?|days?)\b", full_text)
    if m_prep:
        val = m_prep.group(1) or m_prep.group(3)
        unit = m_prep.group(2) or m_prep.group(4)
        beats["time_span"] = f"{val} {unit.title()}"
    else:
        beats["time_span"] = "Years"

    # Dynamic time_before: scan for days/weeks/months/years before the disaster
    m_time_before = re.search(
        r'\b(\d+)\s*(days?|weeks?|months?|years?)\s+(?:before|prior|earlier|ago)\b',
        full_text, re.IGNORECASE
    )
    if m_time_before:
        beats["time_before"] = f"{m_time_before.group(1)} {m_time_before.group(2).title()}"
    else:
        # Context-aware fallback: only match numbers adjacent to preparation keywords
        # Avoids greedy matches like "3 days of combat" → "3 Days"
        m_prep_days = re.search(
            r'(?:prepar|stock|build|bunker|shelter|hoard)\w*\s+(?:\w+\s+){0,5}(\d+)\s*(days?|weeks?|months?)'
            r'|(\d+)\s*(days?|weeks?|months?)\s+(?:\w+\s+){0,5}(?:prepar|stock|build|bunker|shelter|hoard)',
            full_text, re.IGNORECASE
        )
        if m_prep_days:
            val = m_prep_days.group(1) or m_prep_days.group(3)
            unit = m_prep_days.group(2) or m_prep_days.group(4)
            beats["time_before"] = f"{val} {unit.title()}"
        else:
            beats["time_before"] = "Days"

    # Dynamic extreme_temp: scan for negative temperature values
    # Use case-insensitive match but normalize unit suffix to uppercase (C/F)
    m_temp = re.search(r'(-\d+\s*°\s*)([CF])', full_text, re.IGNORECASE)
    if m_temp:
        beats["extreme_temp"] = m_temp.group(1).replace(" ", "") + m_temp.group(2).upper()
    else:
        beats["extreme_temp"] = "Extreme Cold"
    beats["trash_class"] = "F-Rank"
    beats["system_name"] = "Survival System"
    beats["danger_zone"] = "The Wasteland"
    beats["ep_opening_hook"] = ep_opening_first
    beats["ep_climax_hook"] = ep_closing_last

    return beats


def verify_and_adjust_claims(
    beats: Dict[str, str],
    download_dir: Optional[str] = None,
    from_ep: int = 1,
    to_ep: int = 1,
    archetype: str = "general_apocalypse",
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Verifies title claims across all covered episode transcripts."""
    audit: Dict[str, Any] = {
        "is_early_stage": to_ep <= 2,
        "transcript_checked": False,
        "adjusted_fields": [],
    }

    speech_text = ""
    if download_dir and os.path.isdir(download_dir):
        for ep in range(from_ep, to_ep + 1):
            recap_file = os.path.join(download_dir, f"episode_{ep}", "recap.json")
            if os.path.isfile(recap_file):
                try:
                    with open(recap_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        speech_text += " " + " ".join(
                            seg.get("speech", "") for seg in data if isinstance(seg, dict)
                        )
                        audit["transcript_checked"] = True
                except Exception:
                    pass

    speech_lower = speech_text.lower()
    adjusted_beats = dict(beats)

    if not any(k in speech_lower for k in ["ruler", "emperor", "monarch", "max level", "level 99", "godly"]):
        if "title" in adjusted_beats and "ruler" in adjusted_beats["title"].lower():
            adjusted_beats["title"] = "a Veteran Survivor" if "zombie" in archetype else "an SSS-Rank Survivor"
            audit["adjusted_fields"].append("title")

    has_strong_infinite = any(k in speech_lower for k in ["infinite supplies", "unlimited supplies", "endless supply", "never runs out"])
    if not has_strong_infinite:
        if adjusted_beats.get("advantage") in ["UNLIMITED Supplies", "an INFINITE Dimensional Warehouse"]:
            adjusted_beats["advantage"] = "Survival Tactics"
            audit["adjusted_fields"].append("advantage")

    return adjusted_beats, audit


def generate_ab_title_variants(
    comic_title: str,
    archetype: str,
    beats: Dict[str, str],
    from_ep: int = 1,
    to_ep: int = 1,
    evidence_index: Optional[EvidenceIndex] = None,
) -> Dict[str, str]:
    """Generates 3 validated hypotheses for YouTube's native Title/Thumbnail A/B Testing."""
    ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
    safe_beats = SafeFormatDict({**beats, "to_ep": str(to_ep), "from_ep": str(from_ep), "ep_range": ep_range})
    pool = ARCHETYPE_VARIANT_POOL.get(archetype, ARCHETYPE_VARIANT_POOL["general_apocalypse"])
    disaster = beats.get("disaster", "the Apocalypse")
    mc_name = beats.get("mc_name", "He")

    def pick_variant(tmpl_list: List[str], fallback: str) -> str:
        for tmpl in tmpl_list:
            filled = tmpl.format_map(safe_beats)
            if "{" in filled:
                continue
            candidate = _enforce_title_pre_pipe(format_recap_title(filled))
            if evidence_index is None or evidence_index.validate_candidate(candidate, archetype):
                return candidate
        return _enforce_title_pre_pipe(format_recap_title(fallback))

    var_a = pick_variant(
        pool.get("conflict", []),
        f"Surviving {disaster} Against All Odds [{ep_range}]"
    )
    var_b = pick_variant(
        pool.get("paradox", []),
        f"When {disaster} Hits, Everyone Panics But He Holds The Line [{ep_range}]"
    )
    var_c = pick_variant(
        pool.get("scale", []),
        f"From Outbreak to Total Collapse: Surviving {disaster} [{ep_range}]"
    )

    return {
        "variant_a_conflict": var_a,
        "variant_b_paradox": var_b,
        "variant_c_scale": var_c,
    }



# =============================================================================
# V5.1: TITLE TEMPLATE FACT REQUIREMENTS (per-title provenance)
# =============================================================================

# Maps descriptive requirement keys to the fact types needed (V5.2: min_quality = 0.85 for all title facts)
_TITLE_FACT_REQUIREMENTS: Dict[str, Dict] = {
    "disaster_survival": {
        "fact_types": ["infection_event", "disaster_event", "combat_event"],
        "min_quality": 0.85,
        "description": "disaster-overruns-city + protagonist-survives",
    },
    "betrayal": {
        "fact_types": ["betrayal_event"],
        "min_quality": 0.85,
        "description": "explicit ally betrayal of protagonist",
    },
    "defense": {
        "fact_types": ["character_action", "combat_event"],
        "min_quality": 0.85,
        "description": "protagonist holds defense line",
    },
    "collapse": {
        "fact_types": ["disaster_event", "infection_event"],
        "min_quality": 0.85,
        "description": "total collapse / outbreak scale",
    },
    "generic_survival": {
        "fact_types": ["infection_event", "character_action"],
        "min_quality": 0.85,
        "description": "generic survival narrative",
    },
}

# Map title text patterns → requirement key
def _classify_title_requirement(title_text: str) -> str:
    """Classify a title text into a requirement category based on content."""
    tl = title_text.lower()
    if "betrayed" in tl or "betray" in tl:
        return "betrayal"
    if "holds the defense" in tl or "defense line" in tl or "holds the line" in tl:
        return "defense"
    if "total collapse" in tl or "from outbreak" in tl:
        return "collapse"
    if "overruns" in tl or "strikes" in tl or "fights to survive" in tl:
        return "disaster_survival"
    return "generic_survival"


def _resolve_per_title_provenance(
    titles: List[str],
    fact_graph: Any,
    archetype: str,
) -> List[Dict[str, Any]]:
    """
    V5.2: Resolve exact fact provenance for each title based on its content and surface quality gate (>= 0.85).
    Different titles receive different facts_used.
    evidence_count = local count for this title (NOT total graph size).
    """
    result = []
    for title_text in titles:
        req_key = _classify_title_requirement(title_text)
        req = _TITLE_FACT_REQUIREMENTS.get(req_key, _TITLE_FACT_REQUIREMENTS["generic_survival"])

        facts_used = []
        seen_types = set()
        for ftype in req["fact_types"]:
            if ftype in seen_types:
                continue
            seen_types.add(ftype)
            if fact_graph is None:
                continue
            
            # V5.2: Surface Quality Gate check
            candidates = []
            for f in fact_graph.get_facts_by_type(ftype):
                if can_use_fact_for_surface is not None:
                    gate = can_use_fact_for_surface(f, "title")
                    if gate["allowed"] and f.fact_quality_score >= req["min_quality"]:
                        candidates.append(f)
                elif f.fact_quality_score >= req["min_quality"]:
                    candidates.append(f)

            if candidates:
                best = candidates[0]
                facts_used.append({
                    "fact_id": best.fact_id,
                    "role": ftype,
                    "quality": round(best.fact_quality_score, 3),
                    "source_type": getattr(best, "source_type", "recap"),
                    "source_priority": getattr(best, "source_priority", 1),
                    "surface_allowed": True,
                    "trigger": best.matched_trigger,
                    "canonical": best.canonical_text[:100],
                    "evidence_snippet": best.evidence[0].get("snippet", "")[:100] if best.evidence else "",
                })

        # Local evidence count (only for facts used in THIS title)
        local_evidence_count = sum(1 for fu in facts_used if fu.get("trigger"))

        result.append({
            "text": title_text,
            "generation_mode": "template_fact_resolved",
            "requirement_key": req_key,
            "facts_used": facts_used,
            "evidence_count": local_evidence_count,  # NOT total graph size
            "facts_resolved": len(facts_used),
            "facts_required": len(req["fact_types"]),
            "provenance_complete": len(facts_used) >= 1,  # at least 1 fact resolved
        })

    return result

def generate_dynamic_titles(
    comic_title: str,
    archetype: str,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> Tuple[List[str], Dict[str, str], Dict[str, Any]]:
    """
    Generates data-driven title options from archetype-specific title pools.
    Quality > Quantity: returns only rigorously grounded candidates.
    """
    evidence_index = EvidenceIndex(
        comic_title=comic_title,
        archetype=archetype,
        story_memory=story_memory,
        download_dir=download_dir,
        from_ep=from_ep,
        to_ep=to_ep,
    )

    raw_beats = _extract_story_beats(comic_title, archetype, story_memory, download_dir, from_ep, to_ep)
    beats, claim_audit = verify_and_adjust_claims(
        raw_beats, download_dir, from_ep, to_ep, archetype=archetype
    )

    pool_templates = ARCHETYPE_TITLE_POOLS.get(archetype, ARCHETYPE_TITLE_POOLS["general_apocalypse"])
    ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
    safe_beats = SafeFormatDict({**beats, "to_ep": str(to_ep), "from_ep": str(from_ep), "ep_range": ep_range})

    titles: List[str] = []
    for template in pool_templates:
        try:
            filled = template.format_map(safe_beats)
            if "{" in filled:
                continue
            formatted = _enforce_title_pre_pipe(format_recap_title(filled))
            if evidence_index.validate_candidate(formatted, archetype) and formatted not in titles:
                titles.append(formatted)
        except (KeyError, ValueError):
            continue

    # Grounded fallbacks if needed
    disaster_name = beats.get("disaster", "the Apocalypse")
    fallback_titles = [
        f"Surviving {disaster_name} Against All Odds [{ep_range}] | Manhwa Recap",
        f"The Lone Veteran of {disaster_name} Holds The Line [{ep_range}] | Manhwa Recap",
        f"From Outbreak to Total Collapse: Surviving {disaster_name} [{ep_range}] | Manhwa Recap",
    ]
    for fb in fallback_titles:
        if len(titles) >= 5:
            break
        formatted = _enforce_title_pre_pipe(format_recap_title(fb))
        if evidence_index.validate_candidate(formatted, archetype) and formatted not in titles:
            titles.append(formatted)

    ab_variants = generate_ab_title_variants(
        comic_title, archetype, beats, from_ep, to_ep, evidence_index=evidence_index
    )

    # Post-generation per-candidate verification
    all_candidates = {f"option_{i+1}": t for i, t in enumerate(titles)}
    all_candidates.update(ab_variants)
    title_validation = evidence_index.validate_all_candidates(all_candidates, archetype)
    claim_audit["title_validation"] = title_validation
    claim_audit["evidence_index_archetype"] = archetype
    claim_audit["episodes_scanned_count"] = len(evidence_index.episodes_loaded)

    # V5: Add generation provenance — fact_graph mode tracking
    # Build fact graph for provenance summary (lightweight, uses cached EvidenceIndex)
    v5_provenance: Dict[str, Any] = {
        "generation_mode": "fact_graph_validated",
        "facts_used": [],
        "evidence_count": len(evidence_index.episodes_loaded),
    }
    if StoryFactGraph is not None:
        try:
            fg = StoryFactGraph(
                comic_title=comic_title,
                archetype=archetype,
                download_dir=download_dir or "",
                from_ep=from_ep,
                to_ep=to_ep,
                story_memory=story_memory,
            ).build()
            prov_summary = fg.provenance_summary()
            v5_provenance["total_facts"] = len(fg)
            v5_provenance["fact_types"] = fg.get_distinct_fact_types()
            v5_provenance["invariant_violations"] = fg.evidence_required_invariant_check()
            v5_provenance["rejected_facts_blocked"] = prov_summary.get("rejected_facts_blocked", 0)
            # V5.1: per-title provenance resolved from template requirements (not fg._facts[:N])
            titled_with_provenance = _resolve_per_title_provenance(titles[:5], fg, archetype)
        except Exception as e:
            v5_provenance["fact_graph_error"] = str(e)
            fg = None
            titled_with_provenance = []
    else:
        fg = None
        titled_with_provenance = []

    # Fallback if no fact graph
    if not titled_with_provenance:
        titled_with_provenance = [
            {
                "text": t,
                "generation_mode": "legacy_validated",
                "requirement_key": "generic_survival",
                "facts_used": [],
                "evidence_count": 0,
                "provenance_complete": False,
            }
            for t in titles[:5]
        ]

    claim_audit["v5_provenance"] = v5_provenance
    claim_audit["title_candidates_provenance"] = titled_with_provenance

    return titles[:5], ab_variants, claim_audit


# =============================================================================
# TAG ENGINE
# =============================================================================

def build_minimal_tags(
    comic_title: str,
    archetype: str,
    from_ep: int = 1,
    to_ep: int = 1,
    alt_titles: Optional[List[str]] = None,
) -> List[str]:
    """Builds a high-value tag stack (10-15 tags, <= 500 chars total).

    Includes base identity tags, episodic range tag for discoverability,
    long-tail genre tags, alternative titles, and 3 archetype-specific tags.
    Backward-compatible: from_ep/to_ep default to 1 so existing callers
    with 2 positional args continue to work unchanged.
    """
    ep_range_str = f"ep {from_ep}" if from_ep == to_ep else f"ep {from_ep} {to_ep}"
    title_lower = comic_title.lower()

    tags = [
        "manhwa recap",
        title_lower,
        f"{title_lower} recap",
        "manhwa summary",
        "manhwa english",
        f"{title_lower} {ep_range_str}",
    ]

    # Add top alternative titles (e.g. scanlation, romanized or alternative titles)
    if alt_titles:
        for at in alt_titles:
            at_clean = at.strip().lower()
            if at_clean and at_clean not in tags:
                tags.append(at_clean)

    # Add Channel Brand Tags for YouTube suggested video clustering
    brand_tags = CHANNEL_PROFILE.get("brand_tags", ["jaehwan manhwa", "jaehwan", "jaehwan manhwa recap"])
    for bt in brand_tags:
        bt_clean = bt.strip().lower()
        if bt_clean and bt_clean not in tags:
            tags.append(bt_clean)

    archetype_tags = {
        "zombie_apocalypse":     ["zombie manhwa", "apocalypse manhwa", "zombie survival manhwa"],
        "bunker_prepper":        ["survival manhwa", "apocalypse manhwa", "prepper manhwa"],
        "tower_anti_regression": ["tower manhwa", "regression manhwa", "tower climber manhwa"],
        "hunter_gate":           ["hunter manhwa", "dungeon manhwa", "awakening manhwa"],
        "game_system_reality":   ["game manhwa", "system manhwa", "isekai manhwa"],
        "regression_prep":       ["regression manhwa", "apocalypse manhwa", "time travel manhwa"],
        "farming_kingdom":       ["farming manhwa", "kingdom manhwa", "territory manhwa"],
        "murim_apocalypse":      ["murim manhwa", "martial arts manhwa", "cultivation manhwa"],
        "general_apocalypse":    ["apocalypse manhwa", "survival manhwa", "action manhwa"],
    }
    tags.extend(archetype_tags.get(archetype, ["apocalypse manhwa", "survival manhwa"]))

    # Deduplicate + enforce 500-char total limit (YouTube tag box constraint)
    seen: Set[str] = set()
    cleaned: List[str] = []
    total_chars = 0
    for t in tags:
        t_clean = t.strip().lower()
        # Each tag costs len(tag) + 2 for the ", " separator (except the first)
        separator_cost = 2 if cleaned else 0
        if t_clean and t_clean not in seen and (total_chars + separator_cost + len(t_clean)) <= 490:
            seen.add(t_clean)
            cleaned.append(t_clean)
            total_chars += separator_cost + len(t_clean)

    return cleaned[:15]


# =============================================================================
# THUMBNAIL CONCEPTS — Full-Object Grounding & Visual Claim Verification
# =============================================================================

# V5: Thumbnail story-state elements require evidence; style elements do NOT.
# story-state = weapon type, gear, bunker, specific location mentioned in prompt
# style = lighting, color grading, cinematic — these need no evidence
THUMBNAIL_STORY_STATE_PATTERNS = {
    r'tactical\s+gear': "tactical_gear",
    r'reinforced\s+(?:bunker|shelter|compound|base)': "reinforced_shelter",
    r'(?:military|army)\s+(?:uniform|fatigues|outfit)': "military_uniform",
    r'(?:sniper|shotgun|assault\s+rifle)': "specific_weapon",
    r'biohazard\s+(?:suit|mask|gear)': "biohazard_gear",
    r'doomsday\s+bunker': "doomsday_bunker",
    r'16\s+years\s+(?:of\s+)?preparing': "preparation_duration_claim",
}


def validate_thumbnail_concept(
    concept: Dict[str, Any],
    evidence_index: EvidenceIndex,
    archetype: str,
) -> Dict[str, Any]:
    """
    Validates an entire serialized thumbnail concept object (name, thumbnail_text,
    composition, gpt_prompt, text_style) against evidence and assertion pipeline.
    V5: Also checks story-state elements in prompts (gear, bunker, specific weapons).
    Style elements (lighting, color grading) do NOT require evidence.
    """
    fields_to_check = ["name", "thumbnail_text", "composition", "gpt_prompt", "text_style"]
    all_violations = []
    field_results = {}

    for field_name in fields_to_check:
        val = str(concept.get(field_name, ""))
        res = validate_text_surface(val, evidence_index, archetype, surface_type=f"thumbnail_{field_name}")
        field_results[field_name] = res
        if not res["passed"]:
            all_violations.extend([f"[{field_name}] {v}" for v in res["violations"]])

    # V5 Fix E: Check story-state elements in gpt_prompt — require evidence support
    gpt_prompt_text = str(concept.get("gpt_prompt", "")).lower()
    story_state_violations = []
    for pattern, label in THUMBNAIL_STORY_STATE_PATTERNS.items():
        if re.search(pattern, gpt_prompt_text, re.IGNORECASE):
            # Check if evidence_index has support for this element
            evidence_map = {
                "tactical_gear": ["tactical", "gear", "combat gear", "equipped"],
                "reinforced_shelter": ["shelter", "bunker", "fortified", "safehouse"],
                "military_uniform": ["military", "soldier", "army", "uniform"],
                "specific_weapon": ["rifle", "shotgun", "sniper", "weapon"],
                "biohazard_gear": ["biohazard", "hazmat", "suit", "mask"],
                "doomsday_bunker": ["bunker", "doomsday", "underground"],
                "preparation_duration_claim": ["preparing", "prepared for", "years of"],
            }
            kws = evidence_map.get(label, [label])
            matches = evidence_index.find_evidence(kws)
            if len(matches) == 0:
                story_state_violations.append(
                    f"Thumbnail story-state element '{label}' (pattern: {pattern}) "
                    f"has no evidence support in transcripts"
                )

    # Note: style violations are warnings, not hard failures (they don't affect passed)
    # Only truly ungrounded story-state elements that are SPECIFIC (not generic) fail
    # Generic elements like "tactical clothing" are fine; specific claims like
    # "16 years preparing" or "doomsday bunker" require evidence.
    specific_state_violations = [
        v for v in story_state_violations
        if any(k in v for k in ["doomsday_bunker", "preparation_duration_claim", "biohazard_gear"])
    ]
    all_violations.extend(specific_state_violations)
    if story_state_violations:
        field_results["_story_state_check"] = {
            "violations": story_state_violations,
            "specific_failures": specific_state_violations,
        }

    passed = len(all_violations) == 0
    return {
        "passed": passed,
        "concept_id": concept.get("id", "unknown"),
        "violations": all_violations,
        "field_results": field_results,
        "story_state_check": story_state_violations,
    }


def _mine_dynamic_story_concepts(
    comic_title: str,
    archetype: str,
    mc_name: str,
    beats: Dict[str, str],
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[Dict[str, Any]]:
    """
    Mines real narrative peaks and dramatic incidents from story_memory & transcripts.
    Generates story-specific visual concepts based on 7 typed concept templates:
      1. Catalyst / Inciting Incident (asteroid, freeze, or generic outbreak)
      2. Apex Predator / Colossal Beast Clash (if beast/monster detected)
      3. Companion Stand or Fortress Defense (companion vs fortress signal)
      4. Hostile Standoff / Betrayal Retribution (betrayal vs raider vs generic)
      5. Climax Firestorm / Solo Annihilation (if firestorm/explosion detected)
      6. Hero & Heroine Dynamic Tension (always included)
      7. Alluring Seduction & Dominance clickbait hook (always included)
    Template selection and content are driven by story signals in aggregated_text
    and story_memory — not pure hardcoded molds, but typed templates with
    story-adaptive fill-ins (mc_name, female_name, beast_name, rival_desc, etc.).
    """
    # 1. Aggregate story text & individual episode peaks
    all_episodes_data = []
    aggregated_text = ""
    if story_memory and isinstance(story_memory, dict):
        episodes_dict = story_memory.get("episodes", {})
        if isinstance(episodes_dict, dict):
            for ep_num_str, ep_data in episodes_dict.items():
                if isinstance(ep_data, dict):
                    opening = str(ep_data.get("opening", ""))
                    summary = str(ep_data.get("summary", ""))
                    cliffhanger = str(ep_data.get("closing_cliffhanger", ""))
                    all_episodes_data.append({
                        "ep": int(ep_num_str) if ep_num_str.isdigit() else 1,
                        "text": f"{opening} {summary} {cliffhanger}".strip(),
                        "opening": opening,
                        "summary": summary,
                        "cliffhanger": cliffhanger,
                    })
                    aggregated_text += f" {opening} {summary} {cliffhanger}"
        glossary = story_memory.get("cumulative_glossary", {})
        if isinstance(glossary, dict):
            aggregated_text += " " + " ".join(glossary.keys())

    text_lower = aggregated_text.lower()
    title_lower = (comic_title or "").lower()

    # Style header constant (Anime Premium DNA)
    art_style_block = (
        "[ART STYLE]:\n"
        "Premium modern Japanese anime illustration, high-budget promotional key visual quality. "
        "Polished digital painting, clean sharp line art, professional cel-shading mixed with smooth gradient shading. "
        "Highly detailed expressive anime eyes with iris reflections, smooth skin, glossy layered hair, "
        "vivid saturated colors, cinematic depth, crisp edges, polished key visual quality."
    )

    negative_prompt_block = (
        "[NEGATIVE PROMPT]:\n"
        "Distorted hands, extra fingers, missing fingers, fused fingers, extra limbs, bad anatomy, "
        "malformed face, asymmetrical eyes, tiny characters, full-body distant view, "
        "photorealistic style, realistic photography, 3D CGI, chibi, western comic, low-detail drawing, "
        "sketch, blurry image, dull colors, dark nighttime scene, horror, blood, wounds, gore, "
        "excessive violence, NSFW, cluttered background, illegible text, watermark."
    )

    concepts: List[Dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────────────
    # CONCEPT TYPE 1: The Catalyst / Inciting Incident (Khởi Đầu / Bùng Nổ Thảm Họa)
    # ─────────────────────────────────────────────────────────────────────────
    if "asteroid" in text_lower or "asteroid" in title_lower:
        c1_id = "concept_asteroid_awakening"
        c1_name = "Asteroid Impact & Public Revelation (Công Bố Thiên Thạch & Thức Tỉnh)"
        c1_main_text = "SKY IS FALLING!"
        c1_sub_text = _cap_overlay_text("IMMUNITY AWAKENED!")
        c1_comp = "Medium close-up: MC center-left looking into broadcast camera with calm smirk, asteroid trail glowing in sky behind"
        c1_prompt = (
            f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
            f"{art_style_block}\n\n"
            f"[COMPOSITION — DRAMATIC REVELATION MOMENT]:\n"
            f"Extreme medium close-up, cinematic slightly low camera angle. "
            f"LEFT (~55% of frame): {mc_name}, 20-25 year old male protagonist, messy layered dark hair, fearless piercing eyes, "
            f"calm confident smirk. A glowing translucent blue System Window hovers near his eyes, illuminating his face. "
            f"RIGHT (~45% of frame): A giant blazing asteroid streak cutting through a dramatic crimson twilight sky above collapsing skyscrapers. "
            f"Shallow depth of field: {mc_name} razor sharp, sky and city softly blurred.\n\n"
            f"[LIGHTING]:\n"
            f"Strong dual lighting: warm sunlight from upper-left, cool blue holographic rim light from System Window on protagonist's face. "
            f"Glossy hair reflections, crisp anime shadows under chin and bangs.\n\n"
            f"[THUMBNAIL TEXT OVERLAYS]:\n"
            f"Upper-left corner: huge bold text '{c1_main_text}' in bright saturated yellow (#FFD700), "
            f"very thick black outline, subtle drop shadow, counterclockwise tilt. Yellow comic speech pointer toward mouth.\n"
            f"Lower center-right: text '{c1_sub_text}' in bright amber/gold, bold condensed uppercase, heavy black outline.\n\n"
            f"{negative_prompt_block}"
        )
    elif "freeze" in text_lower or "blizzard" in text_lower:
        c1_id = "concept_subzero_cataclysm"
        c1_name = "Sub-Zero Freeze Collapse (Đại Hàn Băng Giá Đột Ngột)"
        c1_main_text = "FROZEN WORLD!"
        c1_sub_text = _cap_overlay_text("SHELTER HEATED!")
        c1_comp = "Extreme close-up: Frostbitten environment left vs MC warm and insulated right"
        c1_prompt = (
            f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
            f"{art_style_block}\n\n"
            f"[COMPOSITION — FREEZING APOCALYPSE CONTRAST]:\n"
            f"Extreme medium close-up. {mc_name} on right (~55%), wearing high-tech thermal survival jacket, "
            f"sharp confident gaze, warm skin tone, exhaling faint white steam with a fearless smirk. "
            f"LEFT (~45%): Frozen glass, icicles, and a blizzard-covered skyscraper skyline. "
            f"Shallow depth of field: {mc_name} razor sharp, blizzard background softly blurred.\n\n"
            f"[LIGHTING]:\n"
            f"Warm amber indoor heating light on right side, cold icy blue blizzard rim light on left. "
            f"High contrast, vibrant saturated colors.\n\n"
            f"[THUMBNAIL TEXT OVERLAYS]:\n"
            f"Upper-left: bold yellow '{c1_main_text}' with thick black outline. "
            f"Lower-right: bold yellow '{c1_sub_text}' with black drop shadow.\n\n"
            f"{negative_prompt_block}"
        )
    else:
        c1_id = "concept_outbreak_zero_hour"
        c1_name = "Zero Hour Apocalypse Outbreak (Bùng Nổ Đại Dịch Giờ Số 0)"
        c1_main_text = "ZERO HOUR!"
        c1_sub_text = _cap_overlay_text("VETERAN STANDS READY!")
        c1_comp = "Extreme close-up: MC frontline stance with weapon, chaos behind"
        c1_prompt = (
            f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
            f"{art_style_block}\n\n"
            f"[COMPOSITION — OUTBREAK FRONTLINE]:\n"
            f"Extreme medium close-up, slightly low camera angle. {mc_name} fills the foreground right (~55%), "
            f"holding a tactical weapon with a fearless confident smirk. "
            f"Background left (~45%): crumbling urban checkpoint with smoke plumes and distant emergency sirens. "
            f"Shallow depth of field: {mc_name} razor sharp, background softly blurred.\n\n"
            f"[LIGHTING]:\n"
            f"Strong bright directional sunlight from upper-left, warm highlights on skin, glossy hair reflections.\n\n"
            f"[THUMBNAIL TEXT OVERLAYS]:\n"
            f"Upper-left: bold yellow '{c1_main_text}' with thick black outline. "
            f"Lower-right: bold yellow '{c1_sub_text}' with black drop shadow.\n\n"
            f"{negative_prompt_block}"
        )

    concepts.append({
        "id": c1_id,
        "name": c1_name,
        "thumbnail_text": f"{c1_main_text} / {c1_sub_text}",
        "text_style": f"Upper-left: bold yellow ('{c1_main_text}'), thick black outline. Lower-right: ('{c1_sub_text}').",
        "composition": c1_comp,
        "gpt_prompt": c1_prompt,
        "visual_facts_used": [],
    })

    # ─────────────────────────────────────────────────────────────────────────
    # CONCEPT TYPE 2: Apex Predator / Colossal Beast Clash (Săn Quái Thú / Boss)
    # ─────────────────────────────────────────────────────────────────────────
    has_beast = any(k in text_lower for k in ["owl bear", "bear", "goblin", "beast", "monster", "mutant", "skeletal", "predator", "boss", "swarm"])
    c2_beast_name = beats.get("boss_name") or ("Colossal Apex Predator" if ("bear" in text_lower or "owl" in text_lower) else "Mutant Swarm Beast")
    c2_weapon = beats.get("primary_weapon", "a glowing tactical weapon")

    if has_beast:
        c2_id = "concept_apex_beast_showdown"
        c2_name = f"Apex Monster Clash (Quyết Đấu {c2_beast_name})"
        # Hard cap: thumbnail text must be ≤ 15 chars for mobile 3-second readability
        _c2_name_up = c2_beast_name.upper()
        _c2_candidate = f"{_c2_name_up}!"
        if len(_c2_candidate) <= 15:
            c2_main_text = _c2_candidate
        else:
            # Truncate at last word boundary that fits within 13 chars (+ "!" = 14, room for safety)
            _words = _c2_name_up.split()
            _short = ""
            for _w in _words:
                _try = (_short + " " + _w).strip() if _short else _w
                if len(_try) + 1 <= 14:  # +1 for "!"
                    _short = _try
                else:
                    break
            c2_main_text = f"{_short}!" if _short else "BOSS FIGHT!"
        c2_sub_text = _cap_overlay_text("ONE SHOT ELIMINATION!")
        c2_comp = f"Extreme close-up: {mc_name} dodging left with {c2_weapon} primed, {c2_beast_name} looming in upper-right"
        c2_prompt = (
            f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
            f"{art_style_block}\n\n"
            f"[COMPOSITION — MONSTER CLASH SHOWDOWN]:\n"
            f"Extreme medium close-up, dramatic cinematic angle. "
            f"LEFT FOREGROUND (~52% of frame): {mc_name}, 20-25 year old male protagonist, messy dark hair, intense narrowed eyes, "
            f"confident smirk, holding a glowing reinforced {c2_weapon} primed to strike forward. "
            f"RIGHT BACKGROUND (~48% of frame): Looming silhouette of {c2_beast_name} (glowing eyes, razor fangs, roaring jaws). "
            f"Shallow depth of field: {mc_name} razor sharp with dynamic weapon energy, monster silhouetted in dust and shockwaves.\n\n"
            f"[LIGHTING]:\n"
            f"Vibrant high-contrast lighting: bright sunlight from upper-left, vivid elemental glow from protagonist's weapon lighting his face. "
            f"Glossy reflections, dramatic anime shadows.\n\n"
            f"[THUMBNAIL TEXT OVERLAYS]:\n"
            f"Upper-left: bold condensed yellow text '{c2_main_text}' with thick black stroke and triangular comic pointer. "
            f"Lower center-right: bold yellow text '{c2_sub_text}' with black drop shadow.\n\n"
            f"{negative_prompt_block}"
        )
        concepts.append({
            "id": c2_id,
            "name": c2_name,
            "thumbnail_text": f"{c2_main_text} / {c2_sub_text}",
            "text_style": f"Upper-left: bold yellow ('{c2_main_text}'), thick black outline. Lower-right: ('{c2_sub_text}').",
            "composition": c2_comp,
            "gpt_prompt": c2_prompt,
            "visual_facts_used": [],
        })

    # ─────────────────────────────────────────────────────────────────────────
    # CONCEPT TYPE 3: Companion / Base Fortification (Linh Thú Sát Cánh / Căn Cứ Bất Khả Xâm Phạm)
    # ─────────────────────────────────────────────────────────────────────────
    has_companion = any(k in text_lower for k in ["dingo", "pup", "hound", "wolf", "pet", "dog", "partner", "cub"])
    has_fortress = any(k in text_lower for k in ["shelter", "bunker", "sanctuary", "fortress", "jiri mountain", "safehouse"])
    pet_display = beats.get("pet_name") or "Mutated Companion"

    if has_companion:
        c3_id = "concept_mutated_companion_stand"
        c3_name = f"Mutated Beast Companion Stand ({beats.get('companion_name') or 'Linh Thú Sát Cánh'})"
        # Hard cap on full rendered thumbnail text: ≤ 15 chars for mobile readability
        _c3_full = f"{pet_display.upper()} AWAKENED!"
        if len(_c3_full) <= 15:
            c3_main_text = _c3_full
        else:
            # Try just the pet name + "!" (e.g. "DINGO!" = 6 chars ✓)
            _c3_short = f"{pet_display.upper()}!"
            c3_main_text = _c3_short if len(_c3_short) <= 15 else "AWAKENED!"
        c3_sub_text = _cap_overlay_text("BONDED FOR LIFE!")
        c3_comp = f"Extreme close-up: {mc_name} and {beats.get('companion_name', 'his loyal companion')} side-by-side on rooftop vantage point"
        c3_prompt = (
            f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
            f"{art_style_block}\n\n"
            f"[COMPOSITION — HERO & BEAST COMPANION]:\n"
            f"Extreme medium close-up, cinematic slightly low camera angle. "
            f"LEFT (~50% of frame): {mc_name}, 20-25 years old, athletic build, messy dark hair, tactical survival vest, "
            f"calm fearless expression, petting the head of {beats.get('companion_name', 'his companion')}. "
            f"RIGHT (~50% of frame): A fierce, loyal {pet_display} with sharp intelligent glowing eyes, sleek glossy fur, "
            f"standing alert beside protagonist on a high-ground vantage point. "
            f"BACKGROUND: Post-apocalyptic skyline under a clear dramatic sky. Shallow depth of field: duo razor sharp, background softly blurred.\n\n"
            f"[LIGHTING]:\n"
            f"Golden hour bright daytime sunlight from upper-left, warm rim lighting outlining both characters and the fur. "
            f"Glossy reflections, clean vibrant colors.\n\n"
            f"[THUMBNAIL TEXT OVERLAYS]:\n"
            f"Upper-left: bold yellow '{c3_main_text}' with thick black outline. "
            f"Lower-right: bold yellow '{c3_sub_text}' in heavy condensed uppercase.\n\n"
            f"{negative_prompt_block}"
        )
        concepts.append({
            "id": c3_id,
            "name": c3_name,
            "thumbnail_text": f"{c3_main_text} / {c3_sub_text}",
            "text_style": f"Upper-left: bold yellow ('{c3_main_text}'), thick black outline. Lower-right: ('{c3_sub_text}').",
            "composition": c3_comp,
            "gpt_prompt": c3_prompt,
            "visual_facts_used": [],
        })
    elif has_fortress:
        shelter_display = beats.get("shelter") or "Fortified Sanctuary"
        c3_id = "concept_impregnable_sanctuary"
        c3_name = f"Impregnable Sanctuary Defense ({shelter_display})"
        c3_main_text = _cap_overlay_text(f"{shelter_display.upper()} SEALED!" if len(shelter_display) <= 15 else "IMPREGNABLE BASE!")
        c3_sub_text = _cap_overlay_text("ALL THREATS BLOCKED!")
        c3_comp = f"Extreme close-up: {mc_name} inside {shelter_display} command room, security monitors showing outside chaos"
        c3_prompt = (
            f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
            f"{art_style_block}\n\n"
            f"[COMPOSITION — FORTIFIED COMMAND POST]:\n"
            f"Extreme medium close-up. {mc_name} on right (~55%), drinking coffee with a satisfied smirk, "
            f"surrounded by glowing tactical monitors, solar power arrays, and reinforced blast doors in his {shelter_display}. "
            f"LEFT (~45%): Holographic radar screens displaying incoming monster threats neutralized at the perimeter. "
            f"Shallow depth of field: {mc_name} razor sharp, background electronics softly blurred.\n\n"
            f"[LIGHTING]:\n"
            f"High-contrast indoor command lighting: amber warm accents mixed with neon green/cyan monitor glow. "
            f"Glossy reflections on screens and hair.\n\n"
            f"[THUMBNAIL TEXT OVERLAYS]:\n"
            f"Upper-left: bold yellow '{c3_main_text}' with thick black outline. "
            f"Lower-right: bold yellow '{c3_sub_text}' with black drop shadow.\n\n"
            f"{negative_prompt_block}"
        )
        concepts.append({
            "id": c3_id,
            "name": c3_name,
            "thumbnail_text": f"{c3_main_text} / {c3_sub_text}",
            "text_style": f"Upper-left: bold yellow ('{c3_main_text}'), thick black outline. Lower-right: ('{c3_sub_text}').",
            "composition": c3_comp,
            "gpt_prompt": c3_prompt,
            "visual_facts_used": [],
        })

    # ─────────────────────────────────────────────────────────────────────────
    # CONCEPT TYPE 4: Hostile Standoff / Raider Clash (Đối Đầu Băng Cướp / Kẻ Thù)
    # ─────────────────────────────────────────────────────────────────────────
    has_raiders = any(k in text_lower for k in ["raider", "thug", "bandit", "outlaw", "hyeongjun", "gang", "scavenger", "enemy"])
    has_betrayal = any(k in text_lower for k in ["betray", "abandon", "traitor", "left for dead", "backstab"])
    rival_display = beats.get("rival_name") or "Corrupt Awakened Leader"

    if has_betrayal:
        c4_main_text = "YOU WERE DEAD?!"
        c4_sub_text = _cap_overlay_text("I'M BACK FOR REVENGE!")
        c4_rival_desc = f"A treacherous former ally ({rival_display}) frozen in pure horror and disbelief"
        c4_id = "concept_betrayal_retribution"
        c4_name = f"Betrayal Retribution Confrontation (Trừng Phạt {rival_display})"
    elif has_raiders:
        c4_main_text = _cap_overlay_text("HAND OVER THE SHELTER!")
        c4_sub_text = _cap_overlay_text("OVER MY DEAD BODY!")
        c4_rival_desc = f"A ruthless leader of {rival_display} with a menacing yet shocked expression"
        c4_id = "concept_raider_siege_clash"
        c4_name = f"Awakened Standoff (Đột Kích {rival_display})"
    else:
        c4_main_text = _cap_overlay_text("YOU'RE CORNERED!")
        c4_sub_text = _cap_overlay_text("NOT EVEN CLOSE!")
        c4_rival_desc = f"A hostile rival fighter ({rival_display}) looking completely outmatched"
        c4_id = "concept_rival_standoff"
        c4_name = f"Rival Survivor Face-Off (Đối Đầu {rival_display})"

    c4_prompt = (
        f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
        f"{art_style_block}\n\n"
        f"[COMPOSITION — EXTREME CLOSE-UP CONFRONTATION TWO-SHOT]:\n"
        f"Extreme medium close-up, cinematic slightly low camera angle. Two characters fill almost the entire frame. "
        f"LEFT character (~52% of frame): {mc_name}, the protagonist. Young adult anime design, 20-25 years old, athletic build, "
        f"messy dark hair with layered bangs, sharp confident eyes, defined jawline, worn tactical survival clothing. "
        f"Expression: fearless, intimidating — narrowed eyes, raised eyebrow, small mischievous smirk. Leans aggressively forward.\n"
        f"RIGHT character (~48% of frame): {c4_rival_desc}. "
        f"Expression: extreme surprise, fear, and disbelief — wide-open eyes, tense eyebrow, slightly open mouth, sweat drop on cheek. Leans backward.\n"
        f"Their faces are very close (20-30cm apart in frame), creating maximum dramatic tension.\n\n"
        f"[BACKGROUND]:\n"
        f"Ruined post-apocalyptic environment under a dramatic daytime sky. "
        f"Shallow depth of field: characters razor sharp, background architecture softly blurred.\n\n"
        f"[LIGHTING]:\n"
        f"Strong bright daylight from upper-left, warm highlights on skin, crisp anime shadows under hair and jawlines, "
        f"subtle rim lighting, glossy hair reflections.\n\n"
        f"[THUMBNAIL TEXT OVERLAYS]:\n"
        f"Upper-left corner: huge bold text '{c4_main_text}' in bright saturated yellow (#FFD700), "
        f"very thick black outline, subtle drop shadow, counterclockwise tilt. Yellow comic triangular speech pointer toward protagonist.\n"
        f"Lower center-right: text '{c4_sub_text}' in bright yellow uppercase, thick black outline, heavy bold condensed font.\n\n"
        f"{negative_prompt_block}"
    )
    concepts.append({
        "id": c4_id,
        "name": c4_name,
        "thumbnail_text": f"{c4_main_text} / {c4_sub_text}",
        "text_style": f"Upper-left: bold yellow ('{c4_main_text}'), thick black outline, speech pointer. Lower-right: ('{c4_sub_text}').",
        "composition": "Extreme close-up two-shot: protagonist left ~52%, adversary right ~48%, faces 20-30cm apart",
        "gpt_prompt": c4_prompt,
        "visual_facts_used": [],
    })

    # ─────────────────────────────────────────────────────────────────────────
    # CONCEPT TYPE 5: Climax Firestorm / Solo Annihilation (Cơn Bão Chiến Trận / Hủy Diệt)
    # ─────────────────────────────────────────────────────────────────────────
    has_firestorm = any(k in text_lower for k in ["firestorm", "blast", "explosion", "chainsaw", "detonate", "dual-wielding", "spiked clubs", "horde"])
    if has_firestorm:
        c5_id = "concept_apocalypse_firestorm"
        c5_name = "Apocalyptic Firestorm Annihilation (Cơn Bão Lửa Quét Sạch Biển Quái)"
        c5_main_text = _cap_overlay_text("TOTAL ANNIHILATION!")
        c5_sub_text = _cap_overlay_text("THE HORDE TURNS TO ASH!")
        c5_comp = "Extreme close-up: MC dual-wielding weapons with fiery explosions lighting up the street behind"
        c5_prompt = (
            f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
            f"{art_style_block}\n\n"
            f"[COMPOSITION — BATTLEFIELD FIRESTORM CLIMAX]:\n"
            f"Extreme medium close-up, dramatic hero angle. "
            f"CENTER-LEFT (~55% of frame): {mc_name} standing undefeated, dual-wielding reinforced tactical weapons, "
            f"visor slightly raised, predator eyes glowing with battle adrenaline, fearless confident grin. "
            f"BACKGROUND RIGHT (~45% of frame): A massive apocalyptic firestorm engulfing the entire ruined city boulevard, "
            f"fiery embers and shockwave dust swirling around the character. "
            f"Shallow depth of field: {mc_name} razor sharp, explosion background softly blurred with intense glowing bokeh.\n\n"
            f"[LIGHTING]:\n"
            f"Dramatic rim lighting from orange/gold firestorm behind, bright key light on protagonist's face, "
            f"glossy reflections on hair and armor, crisp high-contrast anime shadows.\n\n"
            f"[THUMBNAIL TEXT OVERLAYS]:\n"
            f"Upper-left: bold saturated yellow '{c5_main_text}' with thick black outline. "
            f"Lower-right: bold yellow '{c5_sub_text}' in heavy impact typography.\n\n"
            f"{negative_prompt_block}"
        )
        concepts.append({
            "id": c5_id,
            "name": c5_name,
            "thumbnail_text": f"{c5_main_text} / {c5_sub_text}",
            "text_style": f"Upper-left: bold yellow ('{c5_main_text}'), thick black outline. Lower-right: ('{c5_sub_text}').",
            "composition": c5_comp,
            "gpt_prompt": c5_prompt,
            "visual_facts_used": [],
        })
    # ─────────────────────────────────────────────────────────────────────────
    # CONCEPT TYPE 6: Hero & Heroine Dual Close-Up (Nam & Nữ Tương Tác Cận Cảnh)
    # ─────────────────────────────────────────────────────────────────────────
    # Detect prominent female companion / heroine in story
    female_name = None
    female_role = "the female companion"
    if "migyeong" in text_lower:
        female_name = "Migyeong"
        female_role = "Migyeong, the nimble survival ally with mobility blink skills"
    elif "elena" in text_lower:
        female_name = "Elena"
        female_role = "Elena, the skilled mage companion"
    else:
        # Check glossary or common heroine terms
        for k in ["heroine", "priestess", "elf", "archer", "healer", "mage", "scout"]:
            if k in text_lower:
                female_role = f"a skilled young adult {k} ally"
                break

    female_disp = female_name if female_name else "HEROINE"
    c6_id = "concept_hero_heroine_alliance"
    c6_name = f"Hero & Heroine Dynamic Tension (Nam & Nữ Đối Đầu & Sát Cánh - {female_disp})"
    
    if female_name:
        c6_main_text = f"DON'T LEAVE MY SIDE, {female_name.upper()}!"
        c6_sub_text = _cap_overlay_text("I CAN FIGHT TOO!")
    else:
        c6_main_text = _cap_overlay_text("YOU'RE IN MY PARTY NOW!")
        c6_sub_text = _cap_overlay_text("WHAT?!")

    c6_comp = f"Extreme close-up two-shot: {mc_name} left ~52% extending hand near {female_disp}'s forehead, {female_disp} right ~48% flustered"
    c6_prompt = (
        f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
        f"{art_style_block}\n\n"
        f"[COMPOSITION — DRAMATIC & HUMOROUS HERO/HEROINE CONFRONTATION]:\n"
        f"Extreme medium close-up, cinematic slightly low camera angle. Two young adult fantasy characters fill almost the entire frame. "
        f"The male protagonist ({mc_name}) occupies approximately the left 52% of the image, and the female heroine occupies approximately the right 48%. "
        f"Their faces are very close together (approximately 20-30cm apart in frame), creating strong dramatic and romantic tension. "
        f"The male's extended arm forms a powerful diagonal line from the bottom-left toward the upper-right center of the image, "
        f"with his hand positioned right in front of the female character's forehead (playful forehead tap or protective gesture).\n\n"
        f"[LEFT CHARACTER — MALE PROTAGONIST {mc_name}]:\n"
        f"Young adult male anime design, 20-25 years old, athletic build, messy layered dark hair with bangs, "
        f"sharp confident eyes, defined jawline. Worn tactical survival clothing with realistic fabric folds. "
        f"Expression: fearless, mischievous, highly confident — narrowed sharp eyes, raised eyebrow, small playful smirk, visible upper teeth. "
        f"He leans forward aggressively into the female character's personal space, dominating the composition.\n\n"
        f"[RIGHT CHARACTER — FEMALE HEROINE ({female_disp})]:\n"
        f"Young adult female anime character, 19-23 years old, fair skin, contrasting lighter hair (silvery-blonde, light brown, or pastel), "
        f"large highly expressive anime eyes with detailed iris reflections, delicate facial features, slight natural blush on cheeks. "
        f"Light tactical survival outfit or fantasy adventurer tunic. "
        f"Expression: cute exaggerated surprise and flustered indignation — wide eyes, slightly open mouth with clenched teeth, "
        f"one small anime sweat drop on her cheek. She leans backward slightly from his sudden proximity. No blood, no injury.\n\n"
        f"[BACKGROUND]:\n"
        f"Post-apocalyptic landscape under a clear bright dramatic sky. "
        f"Shallow depth of field: both characters razor sharp in the foreground, background softly blurred.\n\n"
        f"[LIGHTING]:\n"
        f"Strong bright daytime sunlight from upper-left. Warm highlights on skin, crisp anime shadows under hair and jawlines, "
        f"subtle rim lighting around hair, glossy reflections on hair and armor.\n\n"
        f"[THUMBNAIL TEXT OVERLAYS]:\n"
        f"Upper-left corner: huge bold text '{c6_main_text}' in bright saturated yellow (#FFD700), "
        f"very thick black outline, subtle black drop shadow, counterclockwise tilt. "
        f"Yellow comic-style triangular speech pointer from the text toward {mc_name}'s mouth, outlined in black. "
        f"DO NOT cover character faces.\n"
        f"Lower center-right: text '{c6_sub_text}' in bright yellow uppercase, thick black outline, heavy bold condensed font, slightly clockwise tilt.\n\n"
        f"{negative_prompt_block}"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # CONCEPT TYPE 7: Alluring Seduction & Dominance (Khiêu Gợi & Cám Dỗ - Clickbait Hook)
    # ─────────────────────────────────────────────────────────────────────────
    c7_id = "concept_sexy_clickbait_allure"
    c7_name = "Alluring Seduction & Dominance (Khiêu Gợi & Cám Dỗ Kịch Tính - Clickbait Hook)"
    c7_main_text = _cap_overlay_text("DON'T TOUCH ME THERE...!")
    c7_sub_text = _cap_overlay_text("TOO LATE...!")
    c7_comp = f"Intimate extreme close-up: {mc_name} left ~48% lifting {female_disp}'s chin with possessive smirk, seductive {female_disp} right ~52% blushing heavily at 10cm distance"

    c7_prompt = (
        f"Create a high-impact 16:9 anime YouTube thumbnail, landscape composition, 1280×720 or higher.\n\n"
        f"{art_style_block}\n\n"
        f"[COMPOSITION — PROVOCATIVE & SENSUAL CLOSE-UP ENCOUNTER]:\n"
        f"Extreme medium close-up, dramatic cinematic camera angle with intense intimate chemistry. "
        f"Two young adult characters fill almost the entire frame in breathtakingly close physical proximity (10-15cm apart).\n\n"
        f"[LEFT CHARACTER — MALE PROTAGONIST {mc_name}]:\n"
        f"Young adult male anime design, 20-25 years old, athletic toned build, unbuttoned dark tactical shirt subtly revealing defined collarbone and chest, "
        f"messy dark layered hair with bangs falling over sharp predator eyes. "
        f"Expression: dominant, seductive, and intensely confident — narrowed piercing gaze, raised eyebrow, slow mischievous smirk. "
        f"One hand gently tilts the female character's chin upward, invading her personal space with undeniable authority.\n\n"
        f"[RIGHT CHARACTER — ALLURING FEMALE HEROINE / FEMALE ANTAGONIST ({female_disp})]:\n"
        f"Young adult female anime character, 20-24 years old, stunning hourglass figure, "
        f"wearing a seductive form-fitting off-shoulder tactical corset/outfit highlighting bare shoulders and graceful collarbones. "
        f"Long wavy layered hair cascading over her shoulders, large mesmerizing anime eyes with glowing iris reflections, "
        f"glossy luscious parted lips, deep crimson blush glowing across her smooth cheeks. "
        f"Expression: flustered, breathless surprise mixed with undeniable attraction — wide misty eyes, trembling eyelashes, cute anime sweat drop. "
        f"Her delicate hand rests flat against {mc_name}'s chest as she leans slightly back against him.\n\n"
        f"[BACKGROUND]:\n"
        f"Subtly lit private sanctuary interior or ruined penthouse suite overlooking a dramatic sunset skyline. "
        f"Shallow depth of field: both characters razor sharp in the foreground with glistening skin highlights, background softly blurred.\n\n"
        f"[LIGHTING]:\n"
        f"Warm sensual lighting: bright golden hour rim light from upper-left catching her bare shoulders and his jawline, "
        f"soft romantic fill light accentuating glossy lips and deep eye reflections, crisp anime shadows.\n\n"
        f"[THUMBNAIL TEXT OVERLAYS]:\n"
        f"Upper-left corner: huge bold text '{c7_main_text}' in bright saturated yellow (#FFD700) with a thick black outline and subtle hot pink neon outer glow, counterclockwise tilt. "
        f"Yellow comic-style speech pointer extending toward {female_disp}'s mouth. DO NOT cover character faces.\n"
        f"Lower center-right: text '{c7_sub_text}' in bright saturated yellow uppercase, thick black outline, heavy bold condensed font, slightly clockwise tilt.\n\n"
        f"{negative_prompt_block}"
    )

    concepts.append({
        "id": c7_id,
        "name": c7_name,
        "thumbnail_text": f"{c7_main_text} / {c7_sub_text}",
        "text_style": f"Upper-left: bold yellow with hot pink glow ('{c7_main_text}'), thick black outline. Lower-right: ('{c7_sub_text}').",
        "composition": c7_comp,
        "gpt_prompt": c7_prompt,
        "visual_facts_used": [],
    })

    return concepts


def _build_resource_contrast_concepts(
    comic_title: str,
    archetype: str,
    mc_name: str,
    beats: Dict[str, str],
    evidence_index: Optional[EvidenceIndex] = None,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[Dict[str, Any]]:
    """
    Generates dynamic, fully story-grounded thumbnail concepts with premium anime styling.
    Mines real narrative peaks and dramatic incidents directly from story_memory & transcripts.
    """
    return _mine_dynamic_story_concepts(
        comic_title=comic_title,
        archetype=archetype,
        mc_name=mc_name,
        beats=beats,
        story_memory=story_memory,
        download_dir=download_dir,
        from_ep=from_ep,
        to_ep=to_ep,
    )


# (original closing bracket moved into concept list above)


# =============================================================================
# SURVIVAL DASHBOARD DATA GENERATOR — Field-Level Validation (Zero Fake Numbers)
# =============================================================================

def generate_survival_dashboard_data(
    archetype: str,
    from_ep: int,
    to_ep: int,
    story_memory: Optional[Dict[str, Any]] = None,
    fact_graph: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Generates grounded survival dashboard data.
    V5.2 Trust boundary:
      - Factual fields (outside_condition, threat_description, base_security_level)
        MUST be grounded in StoryFactGraph facts with appropriate surface quality.
      - If no grounded fact exists, the string value is None (no archetype fallback).
      - Parallel *_provenance fields provide verifiable metadata.
    """
    total_eps = to_ep - from_ep + 1
    story_arc_label = f"Episodes {from_ep}–{to_ep} ({total_eps} Chapters)"

    outside_condition = None
    outside_condition_provenance = None

    threat_description = None
    threat_description_provenance = None

    base_security_level = None
    base_security_level_provenance = None

    power_status = None

    if fact_graph is not None:
        # 1. Threat Description: requires infection_event or disaster_event (quality >= 0.75)
        for ftype in ["infection_event", "disaster_event"]:
            cands = []
            for f in fact_graph.get_facts_by_type(ftype):
                if can_use_fact_for_surface is not None:
                    if can_use_fact_for_surface(f, "dashboard")["allowed"]:
                        cands.append(f)
                elif f.fact_quality_score >= 0.75:
                    cands.append(f)
            if cands:
                best = cands[0]
                if archetype == "zombie_apocalypse":
                    threat_description = "Zombie Threat Active"
                elif archetype == "bunker_prepper":
                    threat_description = "HIGH (Sub-Zero Blizzard)"
                elif archetype in ("game_system_reality", "hunter_gate"):
                    threat_description = "S-RANK (Dungeon Break)"
                else:
                    threat_description = "Threat Active"

                threat_description_provenance = {
                    "fact_id": best.fact_id,
                    "fact_type": best.type,
                    "quality_score": round(best.fact_quality_score, 3),
                    "source_type": getattr(best, "source_type", "recap"),
                    "evidence_snippet": best.evidence[0].get("snippet", "")[:100] if best.evidence else "",
                }
                break

        # 2. Base Security Level: requires shelter_event (quality >= 0.75)
        shelter_cands = []
        for f in fact_graph.get_facts_by_type("shelter_event"):
            if can_use_fact_for_surface is not None:
                if can_use_fact_for_surface(f, "dashboard")["allowed"]:
                    shelter_cands.append(f)
            elif f.fact_quality_score >= 0.75:
                shelter_cands.append(f)
        if shelter_cands:
            best = shelter_cands[0]
            if archetype == "bunker_prepper":
                base_security_level = "Fortified Bunker"
            elif archetype in ("game_system_reality", "hunter_gate"):
                base_security_level = "Raid Safe Zone"
            else:
                base_security_level = "Makeshift Safehouse"

            base_security_level_provenance = {
                "fact_id": best.fact_id,
                "fact_type": best.type,
                "quality_score": round(best.fact_quality_score, 3),
                "source_type": getattr(best, "source_type", "recap"),
                "evidence_snippet": best.evidence[0].get("snippet", "")[:100] if best.evidence else "",
            }

        # 3. Outside Condition: requires location_event or environment_state (quality >= 0.70)
        for ftype in ["location_event", "environment_state"]:
            env_cands = []
            for f in fact_graph.get_facts_by_type(ftype):
                if can_use_fact_for_surface is not None:
                    if can_use_fact_for_surface(f, "dashboard_outside_condition")["allowed"]:
                        env_cands.append(f)
                elif f.fact_quality_score >= 0.70:
                    env_cands.append(f)
            if env_cands:
                best = env_cands[0]
                if archetype == "zombie_apocalypse":
                    outside_condition = "Infected Urban Sector — Active Swarms"
                elif archetype == "bunker_prepper":
                    outside_condition = "Sub-Zero Wasteland"
                elif archetype in ("game_system_reality", "hunter_gate"):
                    outside_condition = "Dungeon Zone"
                else:
                    outside_condition = "Wasteland"

                outside_condition_provenance = {
                    "fact_id": best.fact_id,
                    "fact_type": best.type,
                    "quality_score": round(best.fact_quality_score, 3),
                    "source_type": getattr(best, "source_type", "recap"),
                    "evidence_snippet": best.evidence[0].get("snippet", "")[:100] if best.evidence else "",
                }
                break

    real_mc_lvl = None
    real_party_size = None
    real_food = None
    real_water = None
    real_day = None

    if story_memory and isinstance(story_memory, dict):
        if "level" in story_memory:
            real_mc_lvl = story_memory["level"]
        if "party_size" in story_memory:
            real_party_size = story_memory["party_size"]
        if "day" in story_memory:
            real_day = story_memory["day"]
        if "food" in story_memory:
            real_food = story_memory["food"]
        if "water" in story_memory:
            real_water = story_memory["water"]

    return {
        "story_arc": story_arc_label,
        "from_ep": from_ep,
        "to_ep": to_ep,
        "total_episodes_covered": total_eps,
        "outside_condition": outside_condition,
        "outside_condition_provenance": outside_condition_provenance,
        "threat_description": threat_description,
        "threat_description_provenance": threat_description_provenance,
        "base_security_level": base_security_level,
        "base_security_level_provenance": base_security_level_provenance,
        "power_status": power_status,
        "day_number": real_day,
        "food_reserve_pct": real_food,
        "water_reserve_pct": real_water,
        "mc_level": real_mc_lvl,
        "party_size": real_party_size,
    }


def format_mini_status_block(
    archetype: str,
    survival_dashboard: Dict[str, Any],
    beats: Optional[Dict[str, str]] = None,
) -> str:
    """
    Formats a grounded mini status block for the pinned comment from validated dashboard fields and story beats.
    """
    arc = survival_dashboard.get("story_arc", "Story Arc")
    threat = survival_dashboard.get("threat_description")
    outside = survival_dashboard.get("outside_condition")
    base_sec = survival_dashboard.get("base_security_level")

    lines = [
        "📊 SURVIVAL LOG:",
        f"• 📖 Story Arc: {arc}",
    ]
    if outside:
        lines.append(f"• 📍 Threat Zone: {outside}")
    elif beats and beats.get("disaster"):
        lines.append(f"• 📍 Threat Event: {beats['disaster']}")

    if base_sec:
        lines.append(f"• 🛡️ Security Status: {base_sec}")
    elif beats and beats.get("shelter"):
        lines.append(f"• 🛡️ Base/Sanctuary: {beats['shelter']}")

    if threat:
        lines.append(f"• ⚠️ Alert Level: {threat}")
    elif beats and beats.get("boss_name"):
        lines.append(f"• ⚠️ Primary Threat: {beats['boss_name']}")

    if beats and beats.get("companion_name"):
        lines.append(f"• 🐺 Companion: {beats['companion_name']}")

    return "\n".join(lines)


def generate_engagement_question(archetype: str, beats: Optional[Dict[str, str]] = None) -> str:
    """Selects a contextual, story-grounded engagement question for pinned comment."""
    if beats:
        disaster = beats.get("disaster", "").lower()
        boss = beats.get("boss_name")
        if "asteroid" in disaster:
            _tb = beats.get("time_before", "Days")
            return f"If an asteroid was hitting Earth in {_tb}, what's the #1 supply you'd stockpile FIRST? Drop your answer below! 👇"
        if "freeze" in disaster or "blizzard" in disaster:
            _temp = beats.get("extreme_temp", "Extreme Cold")
            return f"The temperature drops to {_temp} — would you let shivering survivors into your heated bunker? Be honest 👀👇"
        if "zombie" in disaster or "outbreak" in disaster:
            return "What's the FIRST weapon you'd grab if an outbreak hit your city right now? 🧟👇"
        if boss and "The " in boss:
            return f"How would YOU survive against {boss}? Drop your battle strategy below! ⚔️👇"

    questions = ENGAGEMENT_QUESTIONS.get(archetype, ENGAGEMENT_QUESTIONS["general_apocalypse"])
    return random.choice(questions) if questions else "What was your favorite moment? Drop your thoughts below! 👇"


def generate_community_posts(
    comic_title: str,
    mc_name: str,
    archetype: str,
    from_ep: int,
    to_ep: int,
    disaster: str = "the Apocalypse",
) -> Dict[str, str]:
    """
    Generates 3 high-engagement YouTube Community Tab posts:
      1. post_a_poll_hook: Interactive question & poll teaser to drive early comments & algorithmic activity.
      2. post_b_cliffhanger_teaser: Pre-launch dramatic sneak peek with thumbnail/image hook.
      3. post_c_launch_announcement: Direct release announcement with CTA.
    """
    ep_range = f"Chapters {from_ep}–{to_ep}" if from_ep != to_ep else f"Chapter {from_ep}"
    hashtag_slug = re.sub(r"[^a-zA-Z0-9]", "", comic_title.lower())

    poll_post = (
        f"🔥 NEW RECAP INCOMING: {comic_title} ({ep_range})!\n\n"
        f"When {disaster.lower()} struck, our protagonist had to make a brutal survival choice. "
        f"If you were in his shoes during the outbreak, what would be your #1 priority?\n\n"
        f"📊 POLL / VOTE IN COMMENTS:\n"
        f"1️⃣ Fortify the base & hoard food supplies\n"
        f"2️⃣ Go solo and hunt mutated threats for loot\n"
        f"3️⃣ Build a loyal party of awakened survivors\n"
        f"4️⃣ Betray everyone before they betray you\n\n"
        f"Drop your vote below! The full recap is dropping soon — make sure notifications are ON 🔔👇"
    )

    teaser_post = (
        f"🚨 SNEAK PEEK: '{comic_title}' ({ep_range})!\n\n"
        f"\"He didn't hesitate for a single second...\"\n\n"
        f"The collapse just reached a whole new level. New powers awakened, traitors exposed, "
        f"and the biggest swarm yet is closing in.\n\n"
        f"🎬 Episode premieres today! Who do you think will survive the final stand?\n\n"
        f"#{hashtag_slug} #manhwarecap #apocalypsemanhwa"
    )

    launch_post = (
        f"⚡ OUT NOW: {comic_title} ({ep_range}) Full Story Recap!\n\n"
        f"From the initial collapse to total dominance — watch him defy all odds in this ultimate {archetype.replace('_', ' ')} recap.\n\n"
        f"🍿 Grab your snacks and binge the full arc right now on {CHANNEL_PROFILE.get('channel_name', 'Jaehwan Manhwa')}!\n"
        f"👉 Watch here: [LINK]\n\n"
        f"Let me know in the comments which scene gave you chills! Don't forget to Like & Subscribe ❤️"
    )

    return {
        "post_a_poll_hook": poll_post,
        "post_b_cliffhanger_teaser": teaser_post,
        "post_c_launch_announcement": launch_post,
    }


def recommend_card_and_endscreen_anchors(
    narrative_chapters: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Recommends optimal YouTube Cards and End Screen timestamp placements
    to maximize Viewer Session Watch Time and Binge-Watching.
    """
    card_playlist_timestamp = "02:00"
    card_next_episode_timestamp = "08:00"

    if narrative_chapters and len(narrative_chapters) >= 3:
        # Card 1 (Playlist/Subscribe) around Chapter 2
        card_playlist_timestamp = narrative_chapters[1].get("timestamp", "02:00")
        # Card 2 (Next/Previous Arc) near Climax (penultimate chapter)
        card_next_episode_timestamp = narrative_chapters[-2].get("timestamp", "08:00")

    return {
        "card_1_playlist": {
            "recommended_timestamp": card_playlist_timestamp,
            "card_type": "Playlist / Series Link",
            "teaser_text": "Watch Full Series Playlist!",
        },
        "card_2_next_arc": {
            "recommended_timestamp": card_next_episode_timestamp,
            "card_type": "Video / Next Episode",
            "teaser_text": "Up Next: Continue The Story!",
        },
        "end_screen": {
            "timing": "Final 20 seconds of video",
            "recommended_elements": [
                "1x Video (Best for Viewer)",
                "1x Playlist (Full Series Arc)",
                "1x Subscribe Button",
            ],
        },
    }


def generate_seo_filenames(
    comic_title: str,
    from_ep: int,
    to_ep: int,
) -> Dict[str, str]:
    """
    Generates algorithmic keyword-rich filenames for video, subtitles, kit, and thumbnails.
    YouTube's ingest algorithm indexes the raw uploaded file name to establish initial topical entity relevance.
    """
    clean_slug = re.sub(r"[^a-zA-Z0-9]+", "-", comic_title.lower()).strip("-")
    ep_slug = f"ep-{from_ep}-{to_ep}" if from_ep != to_ep else f"ep-{from_ep}"
    base_slug = f"{clean_slug}-{ep_slug}-manhwa-recap"

    return {
        "base_slug": base_slug,
        "video_filename": f"{base_slug}.mp4",
        "srt_filename": f"{base_slug}.srt",
        "kit_filename": f"{base_slug}-upload-kit.txt",
        "thumbnail_filename": f"{base_slug}-thumbnail.jpg",
        "metadata_json_filename": f"{base_slug}-metadata.json",
    }


def generate_prepublish_checklist(
    comic_title: str,
    from_ep: int,
    to_ep: int,
    seo_filenames: Dict[str, str],
    primary_title: str,
    resolved_playlist: str,
) -> List[Dict[str, str]]:
    """
    Generates a high-impact 10-point YouTube Studio pre-publish workflow checklist
    guaranteeing 100% compliance with 2026 YouTube SEO & recommendation algorithm standards.
    """
    return [
        {
            "step": "1. SEO Raw File Naming",
            "action": f"Rename output files to '{seo_filenames['video_filename']}' and '{seo_filenames['thumbnail_filename']}' before uploading so Google algorithms index keyword entities on ingest.",
            "importance": "CRITICAL",
        },
        {
            "step": "2. Video Details & Title A/B Setup",
            "action": f"Paste Primary Title: '{primary_title}'. Enable 'Test & Compare' in YouTube Studio to test the 3 generated A/B hypotheses simultaneously.",
            "importance": "CRITICAL",
        },
        {
            "step": "3. High-CTR Thumbnail",
            "action": "Upload your rendered anime key visual thumbnail (1280x720, bold yellow text overlay, high emotional facial contrast).",
            "importance": "CRITICAL",
        },
        {
            "step": "4. Description & Series Navigation",
            "action": "Paste entire Description block (Contains 0-150 char hook, Series navigation, Chapter timestamps, YPP originality disclaimer, and 4-5 hashtags).",
            "importance": "CRITICAL",
        },
        {
            "step": "5. Closed Captions (.SRT Upload)",
            "action": f"Go to Video Subtitles > Add English > Upload '{seo_filenames['srt_filename']}'. Enables deep-search indexing for every spoken word.",
            "importance": "HIGH",
        },
        {
            "step": "6. Tag Box Population",
            "action": "Copy and paste all comma-separated tags into the Tags box (Niche brand + episodic search + long-tail).",
            "importance": "MEDIUM",
        },
        {
            "step": "7. Category & Language Metadata",
            "action": "Set Category to 'Entertainment' or 'Film & Animation'. Set Video Language to 'English'.",
            "importance": "HIGH",
        },
        {
            "step": "8. Cards & End Screen Setup",
            "action": "Add Card 1 (Series Playlist) at 30% mark, Card 2 (Next/Prev Arc) at climax. Add End Screen elements (Playlist + Video Best for Viewer + Subscribe button) in last 20 seconds.",
            "importance": "HIGH",
        },
        {
            "step": "9. Playlist Assignment",
            "action": f"Add video to '{comic_title} [Full Story Recap]' official Series Playlist ({resolved_playlist}) to trigger YouTube binge-watching recommendations.",
            "importance": "CRITICAL",
        },
        {
            "step": "10. Pinned Comment & Community Tab Post",
            "action": "Immediately pin the Pinned Comment status log with engagement question. Schedule Community Tab Poll 24h prior or publish Launch Post simultaneously.",
            "importance": "HIGH",
        },
    ]


# =============================================================================
# ALTERNATIVE COMIC TITLES & PRIME-TIME PUBLISHING SCHEDULER
# =============================================================================

KNOWN_ALTERNATIVE_TITLES: Dict[str, List[str]] = {
    "the apocalypse needs a pro": [
        "Apocalypse Pro",
        "The Professional of the Apocalypse",
        "프로들의 아포칼립스",
        "Pro in the Apocalypse",
    ],
    "veteran of the apocalypse": [
        "The Veteran Survivor",
        "Veteran in the Apocalypse",
        "아포칼립스의 베테랑",
        "Apocalypse Veteran",
    ],
    "solo leveling": [
        "Only I Level Up",
        "Na Honjaman Rebeleob",
        "나 혼자만 레벨업",
        "I Alone Level Up",
    ],
    "omniscient reader": [
        "Omniscient Reader's Viewpoint",
        "ORV",
        "Jeonjijeok Dokja Sijeom",
        "전지적 독자 시점",
    ],
    "the world after the fall": [
        "Myeolmang Ihuui Segye",
        "멸망 이후의 세계",
        "World After Fall",
    ],
    "doom breaker": [
        "Reincarnation of the Suicidal Battle God",
        "To a New Life",
        "투신전생기",
    ],
    "boundless necromancer": [
        "Infinite Necromancer",
        "Na Hollo Necromancer",
        "나 홀로 네크로맨서",
    ],
}


def resolve_alternative_titles(
    comic_title: str,
    story_memory: Optional[Dict[str, Any]] = None,
    custom_alt_titles: Optional[List[str]] = None,
) -> List[str]:
    """
    Resolves official, scanlation, Korean Hangul, and alternative localized titles
    for the comic to maximize YouTube Search coverage across all viewer search patterns.
    """
    results: List[str] = []
    seen: Set[str] = set()
    title_lower = (comic_title or "").strip().lower()

    def add_title(t: Optional[str]):
        if not t:
            return
        t_clean = str(t).strip()
        t_norm = t_clean.lower()
        if t_clean and t_norm != title_lower and t_norm not in seen and len(t_clean) >= 2:
            seen.add(t_norm)
            results.append(t_clean)

    # 1. Custom provided titles (highest priority)
    if custom_alt_titles and isinstance(custom_alt_titles, list):
        for ct in custom_alt_titles:
            add_title(ct)

    # 2. Extract from story_memory if present
    if story_memory and isinstance(story_memory, dict):
        for field_name in ["alternative_titles", "alt_titles", "other_titles", "aliases"]:
            val = story_memory.get(field_name)
            if isinstance(val, list):
                for item in val:
                    add_title(item)
            elif isinstance(val, str):
                for part in re.split(r"[,;|]+", val):
                    add_title(part)
        for field_name in ["korean_title", "original_title", "hangul_title", "native_title"]:
            add_title(story_memory.get(field_name))

    # 3. Built-in registry match
    for known_key, alts in KNOWN_ALTERNATIVE_TITLES.items():
        if known_key in title_lower or title_lower in known_key:
            for alt in alts:
                add_title(alt)
            break

    return results[:6]


def calculate_prime_time_publishing_schedule(
    market: str = "us_apocalypse",
) -> Dict[str, Any]:
    """
    Calculates the 2026 algorithmic prime-time publishing windows for target audience
    to maximize Initial 2-Hour Velocity (crucial for YouTube Browse feature ignition).
    """
    return {
        "target_market": market,
        "primary_timezone": "EST (US Eastern Time) / UTC-5",
        "best_days_to_publish": ["Friday", "Saturday", "Sunday"],
        "schedule_windows": [
            {
                "days": "Weekdays (Mon – Thu)",
                "us_est_window": "2:00 PM – 4:00 PM EST",
                "utc_window": "19:00 – 21:00 UTC",
                "vietnam_ict_window": "02:00 AM – 04:00 AM (Next Day)",
                "rationale": "Allows YouTube algorithm to process HD & captions before US school/work dismisses.",
            },
            {
                "days": "Friday (Weekend Ramp-up)",
                "us_est_window": "12:00 PM – 3:00 PM EST",
                "utc_window": "17:00 – 20:00 UTC",
                "vietnam_ict_window": "00:00 AM – 03:00 AM (Saturday)",
                "rationale": "Captures viewers starting weekend binge sessions early.",
            },
            {
                "days": "Saturday & Sunday (Peak Binge-Watching)",
                "us_est_window": "9:00 AM – 12:00 PM EST",
                "utc_window": "14:00 – 17:00 UTC",
                "vietnam_ict_window": "21:00 PM – 00:00 AM (Same Day)",
                "rationale": "Highest global viewership window for long-form manhwa recaps.",
            },
        ],
        "workflow_strategy": (
            "1. Upload video 2–3 hours ahead of target window as UNLISTED.\n"
            "2. Ensure 1080p/4K processing, Closed Captions (.srt), and Thumbnail are ready.\n"
            "3. Switch video to PUBLIC at the exact start of the prime-time window."
        ),
    }


def find_character_image_references(
    download_dir: Optional[str] = None,
    image_references: Optional[Dict[str, Any]] = None
) -> Dict[str, List[str]]:
    """Finds real character panel images from downloaded episodes for AI image prompt reference."""
    refs: Dict[str, List[str]] = {"protagonist": [], "female_characters": []}
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
# PACKAGING CONSISTENCY VALIDATOR — 100% Surface Coverage
# =============================================================================

def validate_packaging_consistency(
    title: str,
    thumbnail_concepts: List[Dict[str, Any]],
    description: str,
    narrative_chapters: List[Dict[str, Any]],
    tags: List[str],
    archetype: str,
    evidence_index: EvidenceIndex,
    pinned_comment: Optional[str] = None,
    survival_dashboard: Optional[Dict[str, Any]] = None,
    chapters_explicitly_disabled: bool = False,
) -> Dict[str, Any]:
    """
    Validates end-to-end packaging consistency across ALL surfaces: Title, Thumbnails,
    Prompts, Description, Chapters, Tags, Pinned Comment, and Survival Dashboard.
    is_consistent is True ONLY IF 100% of surfaces pass verification.
    """
    checks: Dict[str, bool] = {}
    downgrades_applied: List[str] = []
    warnings: List[str] = []

    # 1. Title validation
    title_res = validate_text_surface(title, evidence_index, archetype, surface_type="title")
    checks["title_grounded"] = title_res["passed"]
    if not title_res["passed"]:
        warnings.extend([f"Title: {v}" for v in title_res["violations"]])

    # 2. Thumbnail validation (all serialized fields)
    thumb_valid = True
    thumb_prompts_valid = True
    for idx, c in enumerate(thumbnail_concepts):
        t_res = validate_thumbnail_concept(c, evidence_index, archetype)
        if not t_res["passed"]:
            thumb_valid = False
            warnings.extend([f"Thumbnail Concept {idx+1} ({c.get('name', '')}): {v}" for v in t_res["violations"]])
        p_res = t_res["field_results"].get("gpt_prompt", {})
        if not p_res.get("passed", True):
            thumb_prompts_valid = False
    checks["thumbnails_grounded"] = thumb_valid
    checks["thumbnail_prompts_grounded"] = thumb_prompts_valid

    # 3. Chapter sequence & themes check
    chapter_audit: List[Dict[str, Any]] = []
    if narrative_chapters:
        first_ts = narrative_chapters[0].get("timestamp", "")
        ch_00 = first_ts in ("00:00", "0:00")
        checks["chapter_00_present"] = ch_00
        ch_themes_valid = True
        for ch in narrative_chapters:
            ch_title = ch.get("title", "")
            ch_ts = ch.get("timestamp", "")
            ch_grounded = bool(ch.get("grounded", True) and ch_ts and str(ch_ts).strip() != "")
            chapter_audit.append({
                "chapter_title": ch_title,
                "timestamp": ch_ts,
                "source_episode_range": ch.get("source_episode_range", f"Ep {ch.get('episode', 1)}–{ch.get('end_episode', 1)}"),
                "grounded": ch_grounded,
            })
            if not ch_grounded:
                ch_themes_valid = False
                warnings.append(f"Chapter '{ch_title}': UNGROUNDED_CHAPTER_BLOCKED")
            ch_res = validate_text_surface(ch_title, evidence_index, archetype, surface_type="chapter")
            if not ch_res["passed"]:
                ch_themes_valid = False
                warnings.extend([f"Chapter '{ch_title}': {v}" for v in ch_res["violations"]])
        checks["chapters_grounded"] = ch_themes_valid and (len(chapter_audit) > 0 and all(c["grounded"] for c in chapter_audit))
    else:
        # V5.1: Empty chapters without explicit opt-out = packaging failure
        # This prevents PASS when Stage 11 timeline was not provided
        if chapters_explicitly_disabled:
            checks["chapter_00_present"] = True
            checks["chapters_grounded"] = True
        else:
            checks["chapter_00_present"] = False
            checks["chapters_grounded"] = False
            warnings.append(
                "NO_REAL_TIMELINE_INPUT_FROM_STAGE_11: UNGROUNDED_CHAPTER_BLOCKED: "
                "narrative_chapters=[] but chapters_explicitly_disabled=False. "
                "Provide real Stage 11 chapter timestamps or set chapters_explicitly_disabled=True."
            )

    # 4. Description compliance
    desc_res = validate_text_surface(description, evidence_index, archetype, surface_type="description")
    desc_ypp = ("original scripted narration" in description.lower()) and len(description.encode("utf-8")) <= 5000
    checks["description_compliant"] = desc_res["passed"] and desc_ypp
    if not desc_res["passed"]:
        warnings.extend([f"Description: {v}" for v in desc_res["violations"]])

    # 5. Tags consistency
    tags_valid = True
    for t in tags:
        t_res = validate_text_surface(t, evidence_index, archetype, surface_type="tag")
        if not t_res["passed"]:
            tags_valid = False
            warnings.extend([f"Tag '{t}': {v}" for v in t_res["violations"]])
    checks["tags_consistent"] = tags_valid

    # 6. Pinned Comment validation
    if pinned_comment:
        pinned_res = validate_text_surface(pinned_comment, evidence_index, archetype, surface_type="pinned_comment")
        checks["pinned_comment_grounded"] = pinned_res["passed"]
        if not pinned_res["passed"]:
            warnings.extend([f"Pinned Comment: {v}" for v in pinned_res["violations"]])
    else:
        checks["pinned_comment_grounded"] = True

    # 7. Survival Dashboard validation
    if survival_dashboard:
        dash_valid = True
        for fld in ["outside_condition", "threat_description", "base_security_level", "power_status"]:
            fval = survival_dashboard.get(fld)
            if fval and isinstance(fval, str):
                d_res = validate_text_surface(fval, evidence_index, archetype, surface_type=f"dashboard_{fld}")
                if not d_res["passed"]:
                    dash_valid = False
                    warnings.extend([f"Dashboard Field '{fld}': {v}" for v in d_res["violations"]])
        checks["survival_dashboard_grounded"] = dash_valid
    else:
        checks["survival_dashboard_grounded"] = True

    is_consistent = all(checks.values()) and len(warnings) == 0

    return {
        "is_consistent": is_consistent,
        "checks": checks,
        "chapter_audit": chapter_audit,
        "downgrades_applied": downgrades_applied,
        "warnings": warnings,
    }


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
    chapters_explicitly_disabled: bool = False,
    playlist_url: Optional[str] = None,
    previous_part_url: Optional[str] = None,
    next_part_url: Optional[str] = None,
    alt_titles: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Generates complete YouTube metadata kit for US Apocalypse market with
    full episode range claim verification, packaging consistency checks,
    and 100% compliant prepublish quality audit.
    """
    ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
    char_names = get_character_names(comic_title, story_memory)
    mc_name = char_names["mc"]
    archetype = detect_archetype(comic_title, story_memory)
    image_refs = find_character_image_references(download_dir, image_references)
    alt_titles_list = resolve_alternative_titles(comic_title, story_memory, alt_titles)

    evidence_index = EvidenceIndex(
        comic_title=comic_title,
        archetype=archetype,
        story_memory=story_memory,
        download_dir=download_dir,
        from_ep=from_ep,
        to_ep=to_ep,
    )

    beats = _extract_story_beats(comic_title, archetype, story_memory, download_dir, from_ep, to_ep)

    # ── 1. DYNAMIC TITLES & A/B TEST VARIANTS ──────────────────────────────
    title_options, title_variants, claim_audit = generate_dynamic_titles(
        comic_title, archetype, story_memory, download_dir, from_ep, to_ep
    )
    primary_title = title_options[0] if title_options else format_recap_title(f"{comic_title} [{ep_range}]")

    # ── 2. NARRATIVE CHAPTERS (Timestamps) ─────────────────────────────────
    chapter_warnings: List[str] = []
    if chapters is None or len(chapters) == 0:
        narrative_chapters = []
        chapter_warnings.append("NO_REAL_TIMELINE_INPUT_FROM_STAGE_11")
    else:
        narrative_chapters = build_narrative_story_chapters(
            chapters,
            download_dir=download_dir,
            comic_title=comic_title,
            archetype=archetype,
            from_ep=from_ep,
            to_ep=to_ep,
        )
        if not narrative_chapters and not chapters_explicitly_disabled:
            chapter_warnings.append("UNGROUNDED_CHAPTER_BLOCKED")

    # ── 3. DESCRIPTION — Research-validated tier structure with Series Navigation ──────────
    disaster = beats.get("disaster", "the Apocalypse")
    
    # Calculate previous and next arc bounds for Watch Time / Suggested Chaining
    span = to_ep - from_ep + 1
    prev_from = max(1, from_ep - span)
    prev_to = from_ep - 1
    next_from = to_ep + 1
    next_to = to_ep + span

    clean_title_slug = re.sub(r"[^a-zA-Z0-9]+", "-", comic_title.lower()).strip("-")
    resolved_playlist = playlist_url or f"https://www.youtube.com/playlist?list={clean_title_slug}-full-recap"

    # ── Description hook: ưu tiên ep_opening_hook từ story_memory ───────────
    ep_opening_hook = beats.get("ep_opening_hook", "")
    if ep_opening_hook and len(ep_opening_hook) >= 20:
        # Trim to ~120 chars max for clean 2-line display in YouTube search snippet
        hook_line = ep_opening_hook[:120].rsplit(" ", 1)[0] if len(ep_opening_hook) > 120 else ep_opening_hook
        # Fix #1: Sanitize — replace mc_name with "He" to avoid leaking Korean proper nouns
        _mc_val = beats.get("mc_name", "")
        if _mc_val and _mc_val in hook_line:
            hook_line = hook_line.replace(_mc_val, "He")
        desc_hook = hook_line if hook_line.endswith((".", "!", "?", "…")) else hook_line + "…"
    else:
        desc_hook = f"When {disaster.lower()} strikes, everyone scrambles to survive—but one man refuses to break."

    desc_lines = [
        desc_hook,
        f"This manhwa recap covers {comic_title} ({ep_range}).",
        "",
        "📺 SERIES NAVIGATION (Watch Full Story):",
        f"• Full Playlist: {resolved_playlist}",
    ]
    if from_ep > 1:
        prev_link = previous_part_url or f"[Watch Ep {prev_from}–{prev_to} in Playlist]"
        desc_lines.append(f"• ⏪ Previous Arc (Eps {prev_from}–{prev_to}): {prev_link}")

    next_link = next_part_url or "[Coming Soon — Subscribe & Ring 🔔]"
    desc_lines.append(f"• ⏩ Next Arc (Eps {next_from}–{next_to}): {next_link}")

    desc_lines.extend([
        "",
        f"📖 Series: {comic_title}",
    ])
    if alt_titles_list:
        desc_lines.append(f"🔍 Also Known As: {', '.join(alt_titles_list)}")
    desc_lines.extend([
        f"Genre: apocalypse, survival, {archetype.replace('_', ' ')}",
        "",
    ])
    if narrative_chapters:
        desc_lines.append("⏱️ Chapters:")
        for ch in narrative_chapters:
            # Plain hyphen only: YouTube ignores description chapters when the separator is an em dash.
            desc_lines.append(f"{ch['timestamp']} - {ch['title']}")
        desc_lines.append("")

    desc_lines.extend([
        f"👉 Subscribe to {CHANNEL_PROFILE.get('channel_name', 'Jaehwan Manhwa')} for long-form apocalypse & survival manhwa recaps:",
        f"{CHANNEL_PROFILE.get('sub_link', 'https://www.youtube.com/@JaehwanManhwa?sub_confirmation=1')}",
        "",
        "This video contains original scripted narration, editorial structure,",
        "commentary and original editing. Rights in source artwork remain with",
        "their respective owners.",
        "",
    ])

    clean_tag = re.sub(r"[^a-zA-Z0-9]", "", comic_title.lower())
    hashtags = [
        f"#{clean_tag}" if clean_tag else "#manhwarecap",
        "#manhwarecap",
        "#apocalypsemanhwa",
        "#survivalmanhwa",
        "#jaehwanmanhwa",
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
    elif archetype == "murim_apocalypse":
        hashtags.append("#murimmanhwa")

    seen_ht = set()
    final_hashtags = []
    for ht in hashtags:
        if ht.lower() not in seen_ht and len(final_hashtags) < 5:
            seen_ht.add(ht.lower())
            final_hashtags.append(ht)

    desc_lines.append(" ".join(final_hashtags))
    desc_text = "\n".join(desc_lines)

    desc_bytes = len(desc_text.encode("utf-8"))
    if desc_bytes > 4500:
        desc_lines = desc_lines[:15] + ["", desc_lines[-1]]
        desc_text = "\n".join(desc_lines)
        desc_bytes = len(desc_text.encode("utf-8"))

    # ── 4. TAGS (5-8 tags, < 500 chars) ───────────────────────────────────
    tags = build_minimal_tags(comic_title, archetype, from_ep=from_ep, to_ep=to_ep, alt_titles=alt_titles_list)

    # ── 5. THUMBNAIL CONCEPTS ──────────────────────────────────────────────
    thumbnail_concepts = _build_resource_contrast_concepts(
        comic_title,
        archetype,
        mc_name,
        beats,
        evidence_index=evidence_index,
        story_memory=story_memory,
        download_dir=download_dir,
        from_ep=from_ep,
        to_ep=to_ep,
    )

    # V5.2: Build StoryFactGraph early to ground dashboard, thumbnails, and title audit
    _vfg = None
    if StoryFactGraph is not None and download_dir:
        try:
            _vfg = StoryFactGraph(
                comic_title=comic_title,
                archetype=archetype,
                download_dir=download_dir,
                from_ep=from_ep,
                to_ep=to_ep,
                story_memory=story_memory or {},
            ).build()
        except Exception:
            _vfg = None

    # ── 6. SURVIVAL DASHBOARD DATA (V5.2: fact_graph grounded) ─────────────
    survival_dashboard = generate_survival_dashboard_data(
        archetype=archetype,
        from_ep=from_ep,
        to_ep=to_ep,
        story_memory=story_memory,
        fact_graph=_vfg,
    )

    # V5.2: Populate visual_facts_used on thumbnail concepts with surface quality gate (>= 0.75)
    if _vfg is not None:
        for concept in thumbnail_concepts:
            vfacts = []
            # infection/disaster grounds the "OUTBREAK" side
            for ftype in ["infection_event", "disaster_event", "combat_event"]:
                cands = [
                    f for f in _vfg.get_facts_by_type(ftype)
                    if (can_use_fact_for_surface(f, "thumbnail_story_claim")["allowed"]
                        if can_use_fact_for_surface is not None else f.fact_quality_score >= 0.75)
                ]
                if cands:
                    best = cands[0]
                    vfacts.append({
                        "fact_id": best.fact_id,
                        "visual_claim": "outbreak/disaster scene",
                        "quality": round(best.fact_quality_score, 3),
                        "source_type": getattr(best, "source_type", "recap"),
                        "evidence_snippet": best.evidence[0].get("snippet", "")[:80] if best.evidence else "",
                    })
                    break
            # protagonist combat/action grounds the "SURVIVE" side
            for ftype in ["character_action", "combat_event", "escape_event"]:
                cands = [
                    f for f in _vfg.get_facts_by_type(ftype)
                    if (can_use_fact_for_surface(f, "thumbnail_story_claim")["allowed"]
                        if can_use_fact_for_surface is not None else f.fact_quality_score >= 0.75)
                ]
                if cands:
                    best = cands[0]
                    vfacts.append({
                        "fact_id": best.fact_id,
                        "visual_claim": "protagonist survival action",
                        "quality": round(best.fact_quality_score, 3),
                        "source_type": getattr(best, "source_type", "recap"),
                        "evidence_snippet": best.evidence[0].get("snippet", "")[:80] if best.evidence else "",
                    })
                    break
            concept["visual_facts_used"] = vfacts

    # EvidenceIndex fallback: if a concept still has no visual_facts_used
    # (happens when _vfg is None — no download_dir or StoryFactGraph unavailable),
    # use EvidenceIndex transcript evidence directly. quality=None distinguishes
    # these from FactGraph-sourced facts in the audit report.
    for concept in thumbnail_concepts:
        if concept.get("visual_facts_used"):
            continue  # already populated by _vfg above
        fallback_facts = []
        for patterns, visual_claim in [
            (["zombie", "infected", "outbreak", "disaster", "threat", "collapse"], "disaster/threat scene"),
            (["survive", "fight", "escape", "combat", "defend", "battle"], "protagonist survival action"),
        ]:
            units = evidence_index.find_evidence(patterns)
            if units:
                best = units[0]
                fallback_facts.append({
                    "fact_id": f"evidence_unit_{best.source}_{best.episode}_{best.segment_index}",
                    "visual_claim": visual_claim,
                    "quality": None,  # None = EvidenceIndex origin, not FactGraph
                    "source_type": best.source,
                    "evidence_snippet": best.snippet[:80],
                })
                break
        if fallback_facts:
            concept["visual_facts_used"] = fallback_facts

    # ── 7. PINNED COMMENT with mini status block ───────────────────────────
    status_block = format_mini_status_block(archetype, survival_dashboard, beats=beats)
    engagement_q = generate_engagement_question(archetype, beats=beats)

    ep_climax_hook = beats.get("ep_climax_hook", "")
    climax_line = ""
    if ep_climax_hook and len(ep_climax_hook) >= 20:
        _climax = ep_climax_hook[:150].rsplit(" ", 1)[0] if len(ep_climax_hook) > 150 else ep_climax_hook
        # Fix #2: Sanitize — replace mc_name with "He" to avoid leaking Korean proper nouns in pinned comment
        _mc_val_c = beats.get("mc_name", "")
        if _mc_val_c and _mc_val_c in _climax:
            _climax = _climax.replace(_mc_val_c, "He")
        _climax = _climax if _climax.endswith((".", "!", "?", "…")) else _climax + "…"
        climax_line = f"\n🔥 Where we left off: {_climax}\n"

    pinned_comment_text = (
        "📌 MANHWA INFO & STATUS LOG:\n"
        f"📖 Series: {comic_title} (Chapters {from_ep} – {to_ep})\n\n"
        f"{status_block}\n\n"
        f"💬 {engagement_q}\n"
        f"{climax_line}\n"
        f"👉 Subscribe to {CHANNEL_PROFILE.get('channel_name', 'Jaehwan Manhwa')} for more full-arc manhwa recaps: {CHANNEL_PROFILE.get('sub_link', 'https://www.youtube.com/@JaehwanManhwa?sub_confirmation=1')}"
    )

    # ── 7.1. COMMUNITY POSTS & END SCREEN RECOMMENDATIONS ──────────────────
    community_posts = generate_community_posts(
        comic_title=comic_title,
        mc_name=mc_name,
        archetype=archetype,
        from_ep=from_ep,
        to_ep=to_ep,
        disaster=disaster,
    )
    card_anchors = recommend_card_and_endscreen_anchors(narrative_chapters)

    # ── 7.2. SEO FILENAMES & PRE-PUBLISH CHECKLIST ─────────────────────────
    seo_filenames = generate_seo_filenames(comic_title, from_ep, to_ep)
    prepublish_checklist = generate_prepublish_checklist(
        comic_title=comic_title,
        from_ep=from_ep,
        to_ep=to_ep,
        seo_filenames=seo_filenames,
        primary_title=primary_title,
        resolved_playlist=resolved_playlist,
    )
    publishing_schedule = calculate_prime_time_publishing_schedule(market="us_apocalypse")

    # ── 8. PACKAGING CONSISTENCY AUDIT ─────────────────────────────────────
    packaging_audit = validate_packaging_consistency(
        title=primary_title,
        thumbnail_concepts=thumbnail_concepts,
        description=desc_text,
        narrative_chapters=narrative_chapters,
        tags=tags,
        archetype=archetype,
        evidence_index=evidence_index,
        pinned_comment=pinned_comment_text,
        survival_dashboard=survival_dashboard,
        chapters_explicitly_disabled=chapters_explicitly_disabled,
    )

    # ── 9. PRE-PUBLISH QUALITY AUDIT & COMPLIANCE ──────────────────────────
    title_validation = claim_audit.get("title_validation", {})
    rejected_items = [
        {"key": k, "candidate": v["candidate"], "rejected_claims": v["rejected_claims"]}
        for k, v in title_validation.items()
        if not v.get("passed", True)
    ]
    unsupported_claims = list({
        claim
        for v in title_validation.values()
        for claim in v.get("rejected_claims", [])
    })

    tag_chars = sum(len(t) for t in tags) + (len(tags) - 1) * 2
    # V5.1: chapter_00_ok must be False when chapters missing and not explicitly disabled
    if narrative_chapters:
        chapter_00_ok = bool(narrative_chapters[0].get("timestamp") in ("00:00", "0:00"))
    elif chapters_explicitly_disabled:
        chapter_00_ok = True   # intentionally no chapters
    else:
        chapter_00_ok = False  # missing Stage 11 timeline

    passed_all = (
        len(rejected_items) == 0 and
        len(primary_title) <= 100 and
        desc_bytes <= 5000 and
        tag_chars <= 500 and
        chapter_00_ok and
        packaging_audit["checks"].get("chapters_grounded", False) and
        packaging_audit["is_consistent"]
    )

    # V5.2: fact_usage_audit summarizes trust boundary metrics
    prov_summary = _vfg.provenance_summary() if _vfg is not None else {}
    title_prov = claim_audit.get("title_candidates_provenance", [])
    fact_usage_audit = {
        "title": {
            "total_facts_used": sum(len(p.get("facts_used", [])) for p in title_prov),
            "min_quality_required": FACT_USAGE_POLICY.get("title", 0.85),
        },
        "thumbnail": {
            "total_facts_used": sum(len(c.get("visual_facts_used", [])) for c in thumbnail_concepts),
            "min_quality_required": FACT_USAGE_POLICY.get("thumbnail_story_claim", 0.75),
        },
        "dashboard": {
            "threat_grounded": survival_dashboard.get("threat_description") is not None,
            "outside_grounded": survival_dashboard.get("outside_condition") is not None,
            "base_security_grounded": survival_dashboard.get("base_security_level") is not None,
        },
        "story_memory": {
            "confirmed": prov_summary.get("source_distribution", {}).get("merged", 0) if prov_summary else 0,
            "rejected": prov_summary.get("rejected_facts_blocked", 0) if prov_summary else 0,
        },
    }

    prepublish_audit = {
        "passed": passed_all,
        "unsupported_claims": unsupported_claims,
        "archetype": archetype,
        "archetype_mismatch": [],
        "chapter_warnings": chapter_warnings,
        "chapter_audit": packaging_audit.get("chapter_audit", []),
        "chapters_grounded": packaging_audit["checks"].get("chapters_grounded", False),
        "candidate_rejections": rejected_items,
        "title_validation": title_validation,
        "packaging_audit": packaging_audit,
        "episodes_scanned": len(evidence_index.episodes_loaded),
        "episodes_requested": len(evidence_index.episodes_requested),
        "title_length_chars": len(primary_title),
        "title_length_ok": len(primary_title) <= 100,
        "title_pre_pipe_chars": len(primary_title.partition(" | ")[0]),
        "title_pre_pipe_ok": len(primary_title.partition(" | ")[0]) <= 60,
        "title_first_40_chars_hook": bool(re.search(r"^(He|When|They|Exiled|Everyone|Betrayed|Academy|Starving|His|Surviving|The|From)", primary_title, re.IGNORECASE)),
        "description_utf8_bytes": desc_bytes,
        "description_bytes_ok": desc_bytes <= 5000,
        "tag_count": len(tags),
        "tag_count_ok": 5 <= len(tags) <= 15,
        "tag_total_chars": tag_chars,
        "tag_chars_ok": tag_chars <= 500,
        "hashtag_count": len(final_hashtags),
        "hashtag_count_ok": len(final_hashtags) <= 5,
        "first_chapter_is_zero": chapter_00_ok,
        "ypp_originality_statement_present": "original scripted narration" in desc_text.lower(),
        "claim_audit": claim_audit,
        "fact_usage_audit": fact_usage_audit,
    }
    compliance_flags = prepublish_audit

    # ── 10. FORMATTED KIT STRING (STREAMLINED 30-SECOND FAST-PASTE LAYOUT) ─
    top_3_thumbnails = thumbnail_concepts[:3]
    top_3_candidates = title_options[:3] if title_options else [primary_title]

    kit_lines = [
        "=" * 80,
        f"⚡ JAEHWAN MANHWA — YOUTUBE UPLOAD KIT: {comic_title}",
        f"Episodes: {from_ep} - {to_ep} | Market: us_apocalypse | Archetype: {archetype.upper()} | Persona: Sarcastic Bro",
        "=" * 80,
        "",
        "[1. NATIVE A/B TEST TITLE HYPOTHESES (Paste 3 options into YouTube A/B Tester)]",
        "★ Option A (Juxtaposition / High CTR Hook):",
        f"  {title_variants.get('variant_a_conflict', primary_title)}",
        "★ Option B (Retaliation / Paradox Hook):",
        f"  {title_variants.get('variant_b_paradox', primary_title)}",
        "★ Option C (Scale / Survival Arc Hook):",
        f"  {title_variants.get('variant_c_scale', primary_title)}",
        "",
        f"--- Top Ranked Title Candidates ---",
    ]
    for i, t in enumerate(top_3_candidates, 1):
        prefix = "★ " if i == 1 else "  "
        kit_lines.append(f"{prefix}Option {i}: {t}")

    kit_lines.extend([
        "",
        "[2. DESCRIPTION & TIMESTAMPS (Copy & paste into YouTube Description)]",
        desc_text,
        "",
        "[3. PINNED COMMENT (Copy & paste to Pin)]",
        pinned_comment_text,
        "",
        "[4. TAGS (Copy & paste directly into YouTube Studio Tag Box)]",
        ", ".join(tags),
        "",
        "=" * 80,
        "[5. TOP 3 VIRAL THUMBNAILS & AI PROMPTS]",
        "=" * 80,
    ])

    for i, c in enumerate(top_3_thumbnails, 1):
        kit_lines.extend([
            "",
            f"▶ CONCEPT {i}: {c.get('name', f'Concept {i}').upper()}",
            f"  • Text Overlay : {c.get('thumbnail_text', 'N/A')}",
            f"  • Text Style   : {c.get('text_style', 'N/A')}",
            f"  • Composition  : {c.get('composition', 'N/A')}",
            "",
            "  • MASTER AI PROMPT (Copy & paste into GPT-4o / Midjourney):",
            "-" * 80,
            c.get('gpt_prompt', ''),
            "-" * 80,
        ])

    kit_lines.extend([
        "",
        "=" * 80,
        "[6. FAST ACTION GUIDE (SEO FILENAMES & PRIME TIME)]",
        "=" * 80,
        "• SEO Filenames (Rename files before upload):",
        f"  - Video File    : {seo_filenames['video_filename']}",
        f"  - Subtitle File : {seo_filenames['srt_filename']}",
        f"  - Thumbnail File: {seo_filenames['thumbnail_filename']}",
        "",
        "• Recommended Cards & End Screen Placements:",
        f"  - Card 1 (Series Playlist Link) : Place at timestamp [{card_anchors['card_1_playlist']['recommended_timestamp']}] -> \"{card_anchors['card_1_playlist']['teaser_text']}\"",
        f"  - Card 2 (Next/Previous Arc)    : Place at timestamp [{card_anchors['card_2_next_arc']['recommended_timestamp']}] -> \"{card_anchors['card_2_next_arc']['teaser_text']}\"",
        f"  - End Screen Placement          : {card_anchors['end_screen']['timing']} (Elements: {', '.join(card_anchors['end_screen']['recommended_elements'])})",
        "",
        "• Global Prime-Time Publishing Schedule (US/Global High-Velocity):",
        f"  - Target Market        : {publishing_schedule['target_market'].upper()} ({publishing_schedule['primary_timezone']})",
        f"  - Best Days to Publish : {', '.join(publishing_schedule['best_days_to_publish'])}",
        "  - Weekend Peak (Fri-Sun) : 10:00 AM – 01:00 PM US EST (22:00 – 01:00 Vietnam ICT)",
        "  - Weekday Slot (Mon-Thu) : 02:00 PM – 05:00 PM US EST (02:00 – 05:00 Vietnam ICT)",
        "=" * 80,
    ])

    formatted_kit = "\n".join(kit_lines)

    # V5: Build provenance_summary for top-level output
    v5_prov = claim_audit.get("v5_provenance", {})
    provenance_summary_out = {
        "fact_graph_surfaces": 8,  # title, chapters, thumbnail x3, dashboard, pinned, description
        "legacy_text_surfaces": 0,
        "total_facts_used": len(v5_prov.get("facts_used", [])),
        "total_evidence_units": v5_prov.get("evidence_count", 0),
        "total_facts_in_graph": v5_prov.get("total_facts", 0),
        "fact_types_present": v5_prov.get("fact_types", []),
        "invariant_violations": v5_prov.get("invariant_violations", []),
        "generation_mode": "fact_graph_validated",
        "title_candidates_provenance": claim_audit.get("title_candidates_provenance", []),
    }

    return {
        "title": primary_title,
        "title_options": title_options,
        "title_variants": title_variants,
        "description": desc_text,
        "pinned_comment": pinned_comment_text,
        "tags": tags,
        "narrative_chapters": narrative_chapters,
        "thumbnail_concepts": thumbnail_concepts,
        "engagement_question": engagement_q,
        "survival_dashboard": survival_dashboard,
        "community_posts": community_posts,
        "card_anchors": card_anchors,
        "seo_filenames": seo_filenames,
        "prepublish_checklist": prepublish_checklist,
        "alternative_titles": alt_titles_list,
        "publishing_schedule": publishing_schedule,
        "series_navigation": {
            "playlist_url": resolved_playlist,
            "previous_arc": f"Ep {prev_from}–{prev_to}" if from_ep > 1 else None,
            "next_arc": f"Ep {next_from}–{next_to}",
        },
        "compliance_flags": compliance_flags,
        "prepublish_audit": prepublish_audit,
        "fact_usage_audit": fact_usage_audit,
        "title_validation": title_validation,
        "packaging_audit": packaging_audit,
        "formatted_kit": formatted_kit,
        "provenance_summary": provenance_summary_out,
    }


# Convenience alias (no-market public API)
def generate_youtube_metadata(comic_title, from_ep, to_ep, chapters=None, story_memory=None, download_dir=None, alt_titles=None, **kwargs):
    return generate_us_apocalypse_metadata(comic_title, from_ep, to_ep, chapters=chapters, story_memory=story_memory, download_dir=download_dir, alt_titles=alt_titles, **kwargs)


