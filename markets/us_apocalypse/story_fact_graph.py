"""
StoryFactGraph — V5.2 Final Trust Boundary Patch
=================================================

V5.2 changes:
  - FACT_USAGE_POLICY & can_use_fact_for_surface() for strict surface quality gates
    (title: 0.85, thumbnail: 0.75, chapter: 0.70, dashboard: 0.75, dashboard_outside_condition: 0.70, pinned_comment: 0.75)
  - GroundedFact fields: source_type ("recap" | "story_memory" | "merged"), source_priority (1, 2, 3), fact_class ("identity" | "event" | "state")
  - StoryMemory confidence cap: narrative/event/state facts capped at 0.70 (identity facts keep full confidence)
  - merge_with_recap_evidence(): confirms & promotes story_memory facts when recap evidence agrees
  - _reject_unconfirmed_mem_claims(): rejects unconfirmed story_memory strong claims (e.g. betrayal)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# FACT TYPES — 21 supported categories
# =============================================================================

VALID_FACT_TYPES = {
    "disaster_event",
    "location_event",
    "combat_event",
    "survival_event",
    "betrayal_event",
    "resource_event",
    "shelter_event",
    "military_event",
    "character_action",
    "character_state",
    "group_state",
    "environment_state",
    "time_fact",
    "numeric_fact",
    "relationship_event",
    "death_event",
    "escape_event",
    "arrival_event",
    "departure_event",
    "containment_event",
    "infection_event",
}


# =============================================================================
# FACT USAGE POLICY — V5.2 Quality Gates Per Surface
# =============================================================================

FACT_USAGE_POLICY: Dict[str, float] = {
    "title":                       0.85,
    "thumbnail_story_claim":       0.75,
    "chapter":                     0.70,
    "dashboard":                   0.75,
    "dashboard_outside_condition": 0.70,
    "pinned_comment":              0.75,
}


def can_use_fact_for_surface(
    fact: "GroundedFact",
    surface_type: str,
) -> Dict[str, Any]:
    """
    V5.2: Check if a fact meets the quality threshold for a given output surface.

    Returns:
        {
          "allowed": bool,
          "reason": str,
          "required_quality": float,
          "actual_quality": float,
          "surface_type": str,
          "fact_id": str,
          "source_type": str,
          "source_priority": int,
        }
    """
    required = FACT_USAGE_POLICY.get(surface_type)
    if required is None:
        raise ValueError(f"Unknown surface_type: '{surface_type}'. Must be one of {sorted(FACT_USAGE_POLICY)}")

    actual = fact.fact_quality_score
    allowed = actual >= required

    return {
        "allowed": allowed,
        "reason": "ok" if allowed else f"quality_{actual:.2f}_below_{required:.2f}_for_{surface_type}",
        "required_quality": required,
        "actual_quality": actual,
        "surface_type": surface_type,
        "fact_id": fact.fact_id,
        "source_type": getattr(fact, "source_type", "recap"),
        "source_priority": getattr(fact, "source_priority", 1),
    }


# =============================================================================
# GROUNDED FACT DATACLASS — V5.2 extended
# =============================================================================

@dataclass
class GroundedFact:
    """
    A single structured fact extracted from evidence (recap.json transcripts,
    story_memory). Every field is derived from actual source data.

    V5.2 Invariant:
      - if confidence > 0, len(evidence) >= 1
      - matched_trigger must appear in evidence[0]["snippet"] (for recap-sourced facts)
      - entailment_passed must be True (fact was validated before adding to graph)
      - source_type in ("recap", "story_memory", "merged")
      - source_priority in (1, 2, 3)
      - fact_class in ("identity", "event", "state")
    """
    fact_id: str                        # e.g. "combat_event_ep042_001"
    type: str                           # one of VALID_FACT_TYPES
    subject: str                        # "Tae", "zombie horde", "military"
    predicate: str                      # "fights", "overruns", "defenses_collapse"
    object: str                         # "infected squad", "city block"
    scope: str                          # "episode" | "arc" | "series"
    episode_start: int
    episode_end: int
    confidence: float                   # 0.0–1.0
    canonical_text: str                 # human-readable summary
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    # V5.1 additions:
    matched_trigger: str = ""           # keyword that triggered this fact, e.g. "betrayed"
    matched_span: str = ""              # snippet context containing the trigger
    extraction_rule_id: str = ""        # e.g. "betrayal_explicit_v51"
    fact_quality_score: float = 0.0     # 1.0=explicit SPO, 0.85=clear event+subject, 0.7=event, 0.6=broad
    entailment_passed: bool = False     # True only after validate_fact_entailment() passes
    # V5.2 additions:
    source_type: str = "recap"          # "recap" | "story_memory" | "merged"
    source_priority: int = 1            # 1=recap, 2=metadata, 3=story_memory
    fact_class: str = "event"           # "identity" | "event" | "state"

    def __post_init__(self) -> None:
        if self.type not in VALID_FACT_TYPES:
            raise ValueError(f"Invalid fact type: '{self.type}'. Must be one of {sorted(VALID_FACT_TYPES)}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "type": self.type,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "scope": self.scope,
            "episode_start": self.episode_start,
            "episode_end": self.episode_end,
            "confidence": self.confidence,
            "canonical_text": self.canonical_text,
            "matched_trigger": self.matched_trigger,
            "matched_span": self.matched_span,
            "extraction_rule_id": self.extraction_rule_id,
            "fact_quality_score": self.fact_quality_score,
            "entailment_passed": self.entailment_passed,
            "source_type": self.source_type,
            "source_priority": self.source_priority,
            "fact_class": self.fact_class,
            "evidence_count": len(self.evidence),
            "evidence": self.evidence[:3],  # export first 3 snippets
        }


# =============================================================================
# EXTRACTION RULE — V5.1/V5.2 structured format
# =============================================================================

@dataclass
class ExtractionRule:
    """
    Defines how a fact type is extracted and validated.

    trigger_keywords:   Any of these in the text starts the match attempt.
    subject_triggers:   At least one of these must appear for subject to be supported.
                        If empty, subject is always considered supported.
    predicate_triggers: At least one of these must appear for the specific predicate to be supported.
                        If empty, predicate defaults to base quality.
    exclusion_contexts: If any of these exact phrases appear, the fact is REJECTED.
    quality_base:       Quality score when only trigger matches (no S+P confirmation).
    quality_explicit:   Quality score when trigger + subject + predicate all confirmed.
    """
    rule_id: str
    fact_type: str
    subject: str
    predicate: str
    object: str
    trigger_keywords: List[str]
    subject_triggers: List[str]
    predicate_triggers: List[str]
    exclusion_contexts: List[str]
    quality_base: float
    quality_explicit: float


# =============================================================================
# EXTRACTION RULES — V5.1/V5.2 (semantic entailment enforced)
# =============================================================================

_EXTRACTION_RULES_V51: List[ExtractionRule] = [

    # ── INFECTION / OUTBREAK ─────────────────────────────────────────────────
    ExtractionRule(
        rule_id="infection_spreads_v51",
        fact_type="infection_event",
        subject="infected",
        predicate="spreads",
        object="population",
        trigger_keywords=["infect", "infection", "infected", "infections", "outbreak", "virus", "patient zero", "bitten",
                          "spreading", "contagion", "contaminate", "infected spread"],
        subject_triggers=["infect", "infection", "infected", "virus", "outbreak", "contagion", "bitten", "patient zero"],
        predicate_triggers=["spread", "spreading", "spreads", "infect", "infection", "infected", "contaminate", "outbreak"],
        exclusion_contexts=[],
        quality_base=0.80,
        quality_explicit=0.90,
    ),

    # ── COMBAT EVENT — protagonist must be actor ─────────────────────────────
    ExtractionRule(
        rule_id="protagonist_combat_v51",
        fact_type="combat_event",
        subject="protagonist",
        predicate="fights",
        object="infected",
        trigger_keywords=["fights", "attacks", "slices", "shoots", "slams", "charges",
                          "swings", "fires", "battles", "engages", "confronts", "takes on",
                          "fight the", "fought", "tae fights", "tae attacks", "tae shoots",
                          "tae slices", "tae charges"],
        subject_triggers=["tae", "protagonist", "our hero", "main character",
                          "he fights", "he attacks", "he charges", "he shoots",
                          "she fights", "she attacks"],
        predicate_triggers=["fights", "attacks", "charges", "slices", "shoots", "swings",
                            "fires", "battles", "engages", "confronts"],
        exclusion_contexts=["citizens scramble", "terrified citizens", "civilians flee",
                            "crowd panics", "people run", "bystanders flee",
                            "civilians scrambling", "frantic survivors", "crowds"],
        quality_base=0.70,
        quality_explicit=0.95,
    ),

    # ── COMBAT EVENT — zombie horde attacks (environment-level) ──────────────
    ExtractionRule(
        rule_id="horde_attacks_v51",
        fact_type="combat_event",
        subject="zombie_horde",
        predicate="attacks",
        object="survivors",
        trigger_keywords=["horde", "swarm", "surge", "overrun", "mob of infected",
                          "undead swarm", "zombie horde", "horde surges", "horde attacks"],
        subject_triggers=["horde", "swarm", "mob", "surge"],
        predicate_triggers=["surges", "attacks", "overruns", "overwhelms", "swarms"],
        exclusion_contexts=[],
        quality_base=0.75,
        quality_explicit=0.85,
    ),

    # ── MILITARY — deployment (explicit action) ───────────────────────────────
    ExtractionRule(
        rule_id="military_deploys_v51",
        fact_type="military_event",
        subject="military",
        predicate="deploys",
        object="response force",
        trigger_keywords=["deployed", "mobilized", "troops arrived", "soldiers arrived",
                          "military deployed", "sent troops", "reinforcements arrived",
                          "called in troops", "military moves in", "army deploys"],
        subject_triggers=["military", "soldiers", "troops", "army", "forces", "squad", "unit"],
        predicate_triggers=["deployed", "mobilized", "arrived", "sent", "moves in",
                            "called in", "reinforcements"],
        exclusion_contexts=[],
        quality_base=0.80,
        quality_explicit=0.92,
    ),

    # ── MILITARY — defenses collapsing (explicit collapse state) ─────────────
    ExtractionRule(
        rule_id="military_collapse_v51",
        fact_type="military_event",
        subject="military",
        predicate="defenses_collapse",
        object="under attack",
        trigger_keywords=["crumbling defenses", "military line collapses",
                          "overwhelmed the military", "military fails", "military overrun",
                          "military defenses fall", "military retreat", "military crumbles",
                          "military overwhelmed"],
        subject_triggers=["military", "defense", "defenses", "military line"],
        predicate_triggers=["crumbling", "collapsing", "overwhelmed", "fails",
                            "collapses", "retreats", "crumbles", "fall"],
        exclusion_contexts=[],
        quality_base=0.78,
        quality_explicit=0.88,
    ),

    # ── MILITARY — general presence (broad) ──────────────────────────────────
    ExtractionRule(
        rule_id="military_presence_v51",
        fact_type="military_event",
        subject="military",
        predicate="responds",
        object="to outbreak",
        trigger_keywords=["military", "soldiers", "troops", "martial law",
                          "national guard", "army unit", "conscript"],
        subject_triggers=["military", "soldiers", "troops", "army", "forces"],
        predicate_triggers=[],
        exclusion_contexts=[],
        quality_base=0.60,
        quality_explicit=0.70,
    ),

    # ── BETRAYAL — explicit betrayal language ONLY ───────────────────────────
    ExtractionRule(
        rule_id="betrayal_explicit_v51",
        fact_type="betrayal_event",
        subject="ally",
        predicate="betrays",
        object="protagonist",
        trigger_keywords=["betray", "betrayed", "betrays", "backstab", "backstabbed",
                          "sold him out", "sold them out", "turned against him",
                          "turned against them", "locked him out intentionally",
                          "abandoned him", "left him to die", "left him for dead",
                          "left her to die", "left her for dead",
                          "shut the door on him", "ally betrays"],
        subject_triggers=["ally", "friend", "partner", "teammate", "companion",
                          "comrade", "trusted", "survivor who", "one of them"],
        predicate_triggers=["betray", "betrayed", "backstab", "sold out",
                            "turned against", "locked out", "left him", "left her",
                            "left them"],
        exclusion_contexts=["abandoned vehicle", "abandoned car", "abandoned building",
                            "abandoned street", "abandoned post", "abandoned city",
                            "abandoned zone", "abandoned equipment", "abandoned bus",
                            "abandoned truck", "abandoned ambulance"],
        quality_base=0.75,
        quality_explicit=0.95,
    ),

    # ── CONTAINMENT ───────────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="containment_enforced_v51",
        fact_type="containment_event",
        subject="authority",
        predicate="enforces",
        object="quarantine zone",
        trigger_keywords=["quarantine", "containment", "lockdown", "sealed",
                          "barricade", "blockade", "isolation zone"],
        subject_triggers=["authority", "government", "military", "police",
                          "quarantine", "officials"],
        predicate_triggers=["quarantine", "sealed", "blockade", "lockdown",
                            "containment", "barricade"],
        exclusion_contexts=[],
        quality_base=0.78,
        quality_explicit=0.88,
    ),

    # ── SHELTER ──────────────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="shelter_secured_v51",
        fact_type="shelter_event",
        subject="protagonist",
        predicate="secures",
        object="shelter",
        trigger_keywords=["shelter", "safehouse", "hideout", "safe zone",
                          "fortified", "barricaded", "bunker", "refuge",
                          "found shelter", "took refuge", "barricades the door",
                          "secure the building"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "they ", "our hero",
                          "survivor", "group"],
        predicate_triggers=["shelter", "safehouse", "hideout", "refuge",
                            "barricades", "fortified", "secured"],
        exclusion_contexts=[],
        quality_base=0.70,
        quality_explicit=0.85,
    ),

    # ── RESOURCE ACQUISITION ─────────────────────────────────────────────────
    ExtractionRule(
        rule_id="resource_acquired_v51",
        fact_type="resource_event",
        subject="protagonist",
        predicate="acquires",
        object="supplies",
        trigger_keywords=["food", "water", "medicine", "ammo", "supply",
                          "stockpile", "provision", "ration", "fuel",
                          "found food", "found water", "scavenged", "looted supplies"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "they ", "group",
                          "survivor", "our hero"],
        predicate_triggers=["found", "gathered", "scavenged", "looted", "stockpile",
                            "supply", "provision", "acquired"],
        exclusion_contexts=[],
        quality_base=0.65,
        quality_explicit=0.80,
    ),

    # ── DEATH EVENT ──────────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="death_occurred_v51",
        fact_type="death_event",
        subject="character",
        predicate="dies",
        object="in conflict",
        trigger_keywords=["died", "killed", "dead", "murder", "sacrifice",
                          "perish", "fatal", "loss of life", "casualty", "fell",
                          "massacre", "execution", "slain"],
        subject_triggers=["killed", "died", "dead", "casualty", "sacrifice",
                          "slain", "perish", "fell"],
        predicate_triggers=["died", "killed", "dead", "perish", "slain", "fell"],
        exclusion_contexts=[],
        quality_base=0.70,
        quality_explicit=0.85,
    ),

    # ── ESCAPE EVENT ─────────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="protagonist_escapes_v51",
        fact_type="escape_event",
        subject="protagonist",
        predicate="escapes",
        object="danger zone",
        trigger_keywords=["escape", "fled", "run away", "evacuate", "retreat",
                          "break out", "get out", "broke free", "escaped from",
                          "fled from", "evacuated"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "they ",
                          "survivor", "escape"],
        predicate_triggers=["escape", "fled", "evacuate", "retreat", "break out",
                            "get out", "broke free"],
        exclusion_contexts=[],
        quality_base=0.65,
        quality_explicit=0.80,
    ),

    # ── ARRIVAL EVENT ────────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="protagonist_arrives_v51",
        fact_type="arrival_event",
        subject="protagonist",
        predicate="arrives",
        object="new location",
        trigger_keywords=["arrive", "reach", "get to", "found", "discovered location",
                          "enter the", "reached the", "arrived at"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "they ", "group"],
        predicate_triggers=["arrive", "reach", "reached", "found", "enter", "arrived"],
        exclusion_contexts=[],
        quality_base=0.60,
        quality_explicit=0.75,
    ),

    # ── DEPARTURE EVENT ──────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="protagonist_departs_v51",
        fact_type="departure_event",
        subject="protagonist",
        predicate="departs",
        object="previous location",
        trigger_keywords=["leave", "depart", "move out", "evacuated from",
                          "flee from", "left the building", "abandoned the"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "they ", "group"],
        predicate_triggers=["leave", "depart", "evacuated", "flee", "left"],
        exclusion_contexts=["abandoned vehicle", "abandoned car", "abandoned building"],
        quality_base=0.60,
        quality_explicit=0.75,
    ),

    # ── ENVIRONMENT STATE ────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="environment_hazardous_v51",
        fact_type="environment_state",
        subject="environment",
        predicate="is",
        object="hazardous",
        trigger_keywords=["ruin", "collapse", "debris", "fire", "flood",
                          "destroyed city", "devastat", "rubble", "carnage",
                          "smoke-choked", "burning", "crumbling"],
        subject_triggers=["city", "building", "street", "environment",
                          "ruin", "collapse", "debris", "rubble"],
        predicate_triggers=[],
        exclusion_contexts=[],
        quality_base=0.65,
        quality_explicit=0.75,
    ),

    # ── GROUP STATE ──────────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="group_survival_v51",
        fact_type="group_state",
        subject="group",
        predicate="are",
        object="survivors",
        trigger_keywords=["group", "team", "squad", "crew", "allies", "party",
                          "band of survivors", "group of survivors"],
        subject_triggers=["group", "team", "squad", "crew", "allies",
                          "band", "survivors"],
        predicate_triggers=[],
        exclusion_contexts=[],
        quality_base=0.55,
        quality_explicit=0.65,
    ),

    # ── DISASTER EVENT ───────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="disaster_scale_v51",
        fact_type="disaster_event",
        subject="disaster",
        predicate="destroys",
        object="city/region",
        trigger_keywords=["apocalypse", "outbreak overrun", "city fell",
                          "total collapse", "end of the world", "civilization fell",
                          "society collapses", "everything falls apart"],
        subject_triggers=["apocalypse", "outbreak", "collapse", "disaster"],
        predicate_triggers=["fell", "collapse", "destroys", "overrun", "falls"],
        exclusion_contexts=[],
        quality_base=0.80,
        quality_explicit=0.90,
    ),

    # ── LOCATION EVENT ───────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="protagonist_at_location_v51",
        fact_type="location_event",
        subject="protagonist",
        predicate="at",
        object="named location",
        trigger_keywords=["hospital", "school", "subway station", "rooftop",
                          "apartment", "warehouse", "mall", "bridge", "highway",
                          "stadium", "supermarket", "pharmacy"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "they ", "group"],
        predicate_triggers=[],
        exclusion_contexts=[],
        quality_base=0.60,
        quality_explicit=0.72,
    ),

    # ── CHARACTER ACTION ─────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="protagonist_action_v51",
        fact_type="character_action",
        subject="protagonist",
        predicate="acts",
        object="under pressure",
        trigger_keywords=["risked", "sacrificed", "saved", "rescued", "protected",
                          "defended", "fought off", "held the line", "stood his ground",
                          "tae risked", "tae saved", "tae rescued", "tae protected"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "our hero"],
        predicate_triggers=["risked", "sacrificed", "saved", "rescued",
                            "protected", "defended", "held"],
        exclusion_contexts=[],
        quality_base=0.70,
        quality_explicit=0.88,
    ),

    # ── CHARACTER STATE ──────────────────────────────────────────────────────
    ExtractionRule(
        rule_id="protagonist_state_v51",
        fact_type="character_state",
        subject="protagonist",
        predicate="is",
        object="in danger",
        trigger_keywords=["injured", "trapped", "surrounded", "exhausted",
                          "starving", "dehydrated", "outnumbered", "cornered",
                          "tae is trapped", "tae is injured", "tae is surrounded"],
        subject_triggers=["tae", "protagonist", "he ", "she ", "our hero"],
        predicate_triggers=["injured", "trapped", "surrounded", "exhausted",
                            "starving", "cornered", "outnumbered"],
        exclusion_contexts=[],
        quality_base=0.65,
        quality_explicit=0.82,
    ),

    # ── RELATIONSHIP EVENT ───────────────────────────────────────────────────
    ExtractionRule(
        rule_id="relationship_formed_v51",
        fact_type="relationship_event",
        subject="characters",
        predicate="form",
        object="relationship",
        trigger_keywords=["trust", "allied", "team up", "friendship", "bond",
                          "partner", "joined forces", "formed alliance"],
        subject_triggers=["tae", "protagonist", "they", "alliance", "trust"],
        predicate_triggers=["trust", "allied", "team up", "bond", "joined"],
        exclusion_contexts=[],
        quality_base=0.60,
        quality_explicit=0.75,
    ),
]


# =============================================================================
# FACT ENTAILMENT VALIDATOR — V5.1/V5.2 Core
# =============================================================================

def validate_fact_entailment(
    fact: "GroundedFact",
    rule: ExtractionRule,
) -> Dict[str, Any]:
    """
    Semantic entailment check.
    Checks:
    A. Evidence exists
    B. Trigger keyword appears in evidence text (word-boundary safe)
    C. Exclusion context NOT present in evidence
    D. Subject is supported by subject_triggers (if rule has them)
    E. Predicate is supported by predicate_triggers (if rule has them)
    """
    if not fact.evidence:
        return {
            "passed": False,
            "reason": "no_evidence",
            "subject_supported": False,
            "predicate_supported": False,
            "trigger_supported": False,
            "exclusion_matched": None,
            "matched_trigger": "",
            "fact_quality_score": 0.0,
        }

    evidence_text = " ".join(
        ev.get("snippet", "") for ev in fact.evidence
    ).lower()

    # ── A. Trigger must appear in evidence ────────────────────────────────────
    trigger_found = False
    matched_trigger = ""
    for kw in rule.trigger_keywords:
        if " " in kw:
            if kw.lower() in evidence_text:
                trigger_found = True
                matched_trigger = kw
                break
        else:
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", evidence_text):
                trigger_found = True
                matched_trigger = kw
                break

    if not trigger_found:
        return {
            "passed": False,
            "reason": "trigger_not_in_evidence",
            "subject_supported": False,
            "predicate_supported": False,
            "trigger_supported": False,
            "exclusion_matched": None,
            "matched_trigger": "",
            "fact_quality_score": 0.0,
        }

    # ── B. Exclusion context check ────────────────────────────────────────────
    for exc in rule.exclusion_contexts:
        if exc.lower() in evidence_text:
            return {
                "passed": False,
                "reason": f"exclusion_context: '{exc}'",
                "subject_supported": False,
                "predicate_supported": False,
                "trigger_supported": True,
                "exclusion_matched": exc,
                "matched_trigger": matched_trigger,
                "fact_quality_score": 0.0,
            }

    # ── C. Subject support ────────────────────────────────────────────────────
    subject_supported = True
    if rule.subject_triggers:
        subject_supported = any(
            (" " in st and st.lower() in evidence_text)
            or re.search(r"\b" + re.escape(st.lower()) + r"\b", evidence_text)
            for st in rule.subject_triggers
        )

    # ── D. Predicate support ──────────────────────────────────────────────────
    predicate_supported = True
    if rule.predicate_triggers:
        predicate_supported = any(
            (" " in pt and pt.lower() in evidence_text)
            or re.search(r"\b" + re.escape(pt.lower()) + r"\b", evidence_text)
            for pt in rule.predicate_triggers
        )

    # ── E. Compute quality score ──────────────────────────────────────────────
    if subject_supported and predicate_supported:
        quality = rule.quality_explicit
    elif subject_supported or predicate_supported:
        quality = (rule.quality_base + rule.quality_explicit) / 2
    else:
        quality = rule.quality_base

    # ── F. Overall pass/fail ──────────────────────────────────────────────────
    passed = trigger_found and (subject_supported or not rule.subject_triggers)

    return {
        "passed": passed,
        "subject_supported": subject_supported,
        "predicate_supported": predicate_supported,
        "trigger_supported": True,
        "exclusion_matched": None,
        "matched_trigger": matched_trigger,
        "fact_quality_score": quality,
        "reason": "ok" if passed else "subject_not_supported",
    }


# =============================================================================
# WORD BOUNDARY HELPER
# =============================================================================

def _word_boundary_match(text_lower: str, keywords: List[str]) -> Optional[Tuple[str, str]]:
    """Match keywords with word boundaries."""
    for kw in keywords:
        kw_lower = kw.lower()
        if " " in kw_lower:
            if kw_lower in text_lower:
                start = text_lower.find(kw_lower)
                span = text_lower[max(0, start - 15): start + len(kw_lower) + 50]
                return (kw, span)
        else:
            m = re.search(r"\b" + re.escape(kw_lower) + r"\b", text_lower)
            if m:
                start = m.start()
                span = text_lower[max(0, start - 15): start + len(kw_lower) + 50]
                return (kw, span)
    return None


# =============================================================================
# STORY FACT GRAPH — V5.2
# =============================================================================

class StoryFactGraph:
    """
    Evidence-first structured fact graph built ONLY from real source data.
    V5.2: Enforces surface quality gates, StoryMemory confidence caps & merges,
    and provenance tagging on every fact.
    """

    def __init__(
        self,
        comic_title: str,
        archetype: str,
        download_dir: str,
        from_ep: int,
        to_ep: int,
        story_memory: Optional[Dict[str, Any]] = None,
        stage11_timeline: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.comic_title = comic_title
        self.archetype = archetype
        self.download_dir = download_dir
        self.from_ep = from_ep
        self.to_ep = to_ep
        self.story_memory = story_memory or {}
        self.stage11_timeline = stage11_timeline or []

        self._facts: List[GroundedFact] = []
        self._built = False
        self._episodes_scanned: int = 0
        self._episodes_found: int = 0
        self._rejected_facts: int = 0

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def build(self) -> "StoryFactGraph":
        """Extract all facts from source data, merge sources, and enforce trust boundaries."""
        if self._built:
            return self
        self._facts = []
        self._rejected_facts = 0
        self._extract_from_episodes()
        self._extract_from_story_memory()
        self.merge_with_recap_evidence()
        self._reject_unconfirmed_mem_claims()
        self._built = True
        return self

    def get_facts_by_type(self, fact_type: str) -> List[GroundedFact]:
        """Return all facts of a given type, sorted by quality desc then confidence desc."""
        return sorted(
            [f for f in self._facts if f.type == fact_type],
            key=lambda f: (f.fact_quality_score, f.confidence),
            reverse=True,
        )

    def get_facts_for_episode_range(
        self, ep_start: int, ep_end: int
    ) -> List[GroundedFact]:
        """Return facts whose episode range overlaps with [ep_start, ep_end]."""
        return [
            f for f in self._facts
            if f.episode_end >= ep_start and f.episode_start <= ep_end
        ]

    def get_facts_by_quality(self, min_quality: float = 0.8) -> List[GroundedFact]:
        """Return all facts with quality >= threshold, sorted by quality desc."""
        return sorted(
            [f for f in self._facts if f.fact_quality_score >= min_quality],
            key=lambda f: f.fact_quality_score,
            reverse=True,
        )

    def get_facts_for_surface(
        self, surface_type: str, min_quality: Optional[float] = None
    ) -> List[GroundedFact]:
        """V5.2: Return facts that satisfy the policy threshold for a given output surface."""
        thresh = min_quality if min_quality is not None else FACT_USAGE_POLICY.get(surface_type, 0.70)
        return [
            f for f in self._facts
            if can_use_fact_for_surface(f, surface_type)["allowed"] and f.fact_quality_score >= thresh
        ]

    def get_distinct_fact_types(self) -> List[str]:
        """Return the list of distinct fact types present in the graph."""
        return sorted({f.type for f in self._facts})

    def select_facts_for_template(
        self, required_types: List[str], min_quality: float = 0.85
    ) -> Optional[Dict[str, "GroundedFact"]]:
        """
        Select one best fact per required type for template filling.
        Returns None if any required type has no qualifying facts.
        """
        result: Dict[str, GroundedFact] = {}
        for req_type in required_types:
            candidates = [
                f for f in self.get_facts_by_type(req_type)
                if f.fact_quality_score >= min_quality
            ]
            if not candidates:
                return None
            result[req_type] = candidates[0]
        return result

    def evidence_required_invariant_check(self) -> List[str]:
        """
        Verify invariant — every fact must have:
        1. confidence > 0 → len(evidence) >= 1
        2. entailment_passed == True
        3. matched_trigger appears in evidence[0]["snippet"] (for recap sources)
        """
        violations: List[str] = []
        for f in self._facts:
            if f.confidence > 0 and len(f.evidence) == 0:
                violations.append(
                    f"INVARIANT: fact '{f.fact_id}' has confidence={f.confidence} "
                    f"but evidence=[] — invariant broken."
                )
                continue

            if not f.entailment_passed:
                violations.append(
                    f"INVARIANT: fact '{f.fact_id}' has entailment_passed=False "
                    f"but is in the graph — should have been filtered."
                )

            if f.source_type == "recap" and f.matched_trigger and f.evidence:
                snippet = f.evidence[0].get("snippet", "").lower()
                trigger_lower = f.matched_trigger.lower()
                trigger_in_evidence = (
                    (" " in trigger_lower and trigger_lower in snippet)
                    or bool(re.search(r"\b" + re.escape(trigger_lower) + r"\b", snippet))
                )
                if not trigger_in_evidence:
                    violations.append(
                        f"INVARIANT: fact '{f.fact_id}' matched_trigger='{f.matched_trigger}' "
                        f"does NOT appear in evidence snippet — semantic gap."
                    )

        return violations

    def to_json(self) -> Dict[str, Any]:
        """Serialize the full fact graph to a JSON-serializable dict."""
        return {
            "comic_title": self.comic_title,
            "archetype": self.archetype,
            "from_ep": self.from_ep,
            "to_ep": self.to_ep,
            "episodes_scanned": self._episodes_scanned,
            "episodes_found": self._episodes_found,
            "total_facts": len(self._facts),
            "rejected_facts_blocked": self._rejected_facts,
            "distinct_fact_types": self.get_distinct_fact_types(),
            "invariant_violations": self.evidence_required_invariant_check(),
            "facts": [f.to_dict() for f in self._facts],
        }

    def __len__(self) -> int:
        return len(self._facts)

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: EXTRACTION FROM EPISODES
    # ─────────────────────────────────────────────────────────────────────────

    def _make_fact_id(self, fact_type: str, ep: int, counter: int) -> str:
        return f"{fact_type}_ep{ep:03d}_{counter:03d}"

    def _extract_from_episodes(self) -> None:
        """Scan all recap.json files and extract GroundedFacts with entailment validation."""
        if not self.download_dir or not os.path.isdir(self.download_dir):
            return

        fact_counter: Dict[str, int] = {}

        for ep in range(self.from_ep, self.to_ep + 1):
            self._episodes_scanned += 1
            recap_path = os.path.join(
                self.download_dir, f"episode_{ep}", "recap.json"
            )
            if not os.path.isfile(recap_path):
                continue
            self._episodes_found += 1

            try:
                with open(recap_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            if not isinstance(data, list):
                continue

            segments = [
                item.get("speech", "")
                for item in data
                if isinstance(item, dict) and item.get("speech")
            ]
            if not segments:
                continue

            fired_rules: set = set()

            for rule in _EXTRACTION_RULES_V51:
                if rule.rule_id in fired_rules:
                    continue

                for seg_idx, seg in enumerate(segments):
                    seg_lower = seg.lower()

                    match_result = _word_boundary_match(seg_lower, rule.trigger_keywords)
                    if not match_result:
                        continue

                    kw_matched, span = match_result

                    ftype_counter = fact_counter.get(rule.fact_type, 0) + 1

                    canonical = (
                        f"[Ep {ep}] {rule.subject.title()} {rule.predicate} {rule.object} "
                        f"(trigger: '{kw_matched}'; from: \"{seg[:80].strip()}...\")"
                    )

                    fact_cls = "event"
                    if "state" in rule.fact_type:
                        fact_cls = "state"
                    elif "action" in rule.fact_type or "event" in rule.fact_type:
                        fact_cls = "event"

                    candidate_fact = GroundedFact(
                        fact_id=self._make_fact_id(rule.fact_type, ep, ftype_counter),
                        type=rule.fact_type,
                        subject=rule.subject,
                        predicate=rule.predicate,
                        object=rule.object,
                        scope="episode",
                        episode_start=ep,
                        episode_end=ep,
                        confidence=rule.quality_base,
                        canonical_text=canonical,
                        evidence=[{
                            "episode": ep,
                            "segment_index": seg_idx,
                            "snippet": seg[:200],
                            "source": "recap",
                            "source_path": recap_path,
                        }],
                        matched_trigger=kw_matched,
                        matched_span=span,
                        extraction_rule_id=rule.rule_id,
                        fact_quality_score=0.0,
                        entailment_passed=False,
                        source_type="recap",
                        source_priority=1,
                        fact_class=fact_cls,
                    )

                    entailment = validate_fact_entailment(candidate_fact, rule)
                    if not entailment["passed"]:
                        self._rejected_facts += 1
                        break

                    candidate_fact.fact_quality_score = entailment["fact_quality_score"]
                    candidate_fact.entailment_passed = True
                    candidate_fact.confidence = entailment["fact_quality_score"]
                    candidate_fact.matched_trigger = entailment["matched_trigger"]

                    fact_counter[rule.fact_type] = ftype_counter
                    self._facts.append(candidate_fact)
                    fired_rules.add(rule.rule_id)
                    break

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: EXTRACTION FROM STORY MEMORY
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_from_story_memory(self) -> None:
        """
        Extract structured facts from story_memory fields.
        V5.2: Capping policy:
          - fact_class='identity': exempt from cap, keeps full confidence (e.g. 0.95)
          - fact_class in ('event', 'state'): capped at 0.70 unless merged with recap evidence
        """
        if not self.story_memory:
            return

        mem = self.story_memory
        mem_str = str(mem).lower()
        fact_counter: Dict[str, int] = {}

        def _mem_fact(
            fact_type: str, subject: str, predicate: str, obj: str,
            conf: float, snippet: str, trigger: str = "", quality: float = 0.80,
            fact_class: str = "event",
        ) -> GroundedFact:
            c = fact_counter.get(fact_type, 0) + 1
            fact_counter[fact_type] = c
            fact_id = f"{fact_type}_mem_{c:03d}"

            # V5.2 Capping Rule: identity is preserved; narrative events/states are capped at 0.70
            if fact_class == "identity":
                final_quality = quality
                final_conf = conf
            else:
                final_quality = min(quality, 0.70)
                final_conf = min(conf, 0.70)

            return GroundedFact(
                fact_id=fact_id,
                type=fact_type,
                subject=subject,
                predicate=predicate,
                object=obj,
                scope="series",
                episode_start=self.from_ep,
                episode_end=self.to_ep,
                confidence=final_conf,
                canonical_text=f"[story_memory] {subject} {predicate} {obj}",
                evidence=[{
                    "episode": 0,
                    "segment_index": -1,
                    "snippet": snippet[:200],
                    "source": "story_memory",
                    "source_path": "",
                }],
                matched_trigger=trigger,
                matched_span=snippet[:80],
                extraction_rule_id="story_memory_v52",
                fact_quality_score=final_quality,
                entailment_passed=True,
                source_type="story_memory",
                source_priority=3,
                fact_class=fact_class,
            )

        # Protagonist name — IDENTITY (EXEMPT from cap)
        protagonist = mem.get("protagonist_name", "")
        if protagonist and len(protagonist) > 1:
            self._facts.append(_mem_fact(
                "character_state", protagonist, "is", "the protagonist",
                0.95, f"protagonist_name: {protagonist}",
                trigger="protagonist_name", quality=0.95,
                fact_class="identity",
            ))

        # Betrayal — EVENT (capped at 0.70 unless confirmed by recap)
        if any(k in mem_str for k in ["betray", "backstab", "left for dead"]):
            self._facts.append(_mem_fact(
                "betrayal_event", "ally", "betrays", "protagonist",
                0.90, f"story_memory betrayal: {mem_str[:100]}",
                trigger="betray", quality=0.90,
                fact_class="event",
            ))

        # Shelter/bunker — EVENT (capped at 0.70)
        if "bunker" in mem_str or "shelter" in mem_str or "safehouse" in mem_str:
            self._facts.append(_mem_fact(
                "shelter_event", "protagonist", "uses", "shelter/bunker",
                0.85, f"story_memory shelter: {mem_str[:100]}",
                trigger="shelter", quality=0.85,
                fact_class="event",
            ))

        # Day number — STATE (capped at 0.70)
        if "day" in mem:
            day_val = mem["day"]
            if isinstance(day_val, (int, float)) and day_val > 0:
                self._facts.append(_mem_fact(
                    "time_fact", "story", "spans", f"Day {int(day_val)}",
                    0.90, f"story_memory day: {day_val}",
                    trigger="day", quality=0.90,
                    fact_class="state",
                ))

        # Infection/zombie from story_memory — EVENT (capped at 0.70)
        if any(k in mem_str for k in ["zombie", "infected", "outbreak", "virus", "undead"]):
            self._facts.append(_mem_fact(
                "infection_event", "virus", "spreads", "population",
                0.90, f"story_memory infection: {mem_str[:100]}",
                trigger="infected", quality=0.90,
                fact_class="event",
            ))

        # Military — EVENT (capped at 0.70)
        if any(k in mem_str for k in ["military", "soldier", "army", "martial law"]):
            self._facts.append(_mem_fact(
                "military_event", "military", "responds", "to outbreak",
                0.75, f"story_memory military: {mem_str[:100]}",
                trigger="military", quality=0.75,
                fact_class="event",
            ))

        # Group/party — STATE (capped at 0.70)
        if "party_size" in mem and isinstance(mem["party_size"], (int, float)):
            ps = int(mem["party_size"])
            if ps > 1:
                self._facts.append(_mem_fact(
                    "group_state", "group", "has", f"{ps} survivors",
                    0.85, f"story_memory party_size: {ps}",
                    trigger="party_size", quality=0.85,
                    fact_class="state",
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # V5.2: MERGE & REJECT UNCONFIRMED MEMORY CLAIMS
    # ─────────────────────────────────────────────────────────────────────────

    def merge_with_recap_evidence(self) -> None:
        """
        V5.2: If a story_memory fact has matching recap evidence (same type),
        merge: upgrade source_type='merged', source_priority=1, use highest quality.
        """
        recap_by_type: Dict[str, List[GroundedFact]] = {}
        for f in self._facts:
            if f.source_type == "recap":
                recap_by_type.setdefault(f.type, []).append(f)

        for f in self._facts:
            if f.source_type != "story_memory":
                continue
            recap_matches = recap_by_type.get(f.type, [])
            if recap_matches:
                best_recap = max(recap_matches, key=lambda r: r.fact_quality_score)
                f.source_type = "merged"
                f.source_priority = 1
                f.fact_quality_score = max(f.fact_quality_score, best_recap.fact_quality_score)
                f.confidence = f.fact_quality_score
                if best_recap.evidence:
                    f.evidence.append(best_recap.evidence[0])

    def _reject_unconfirmed_mem_claims(self) -> None:
        """
        V5.2: Remove story_memory-only strong claims (like betrayal_event)
        that are not confirmed by recap evidence.
        """
        strong_claim_types = {"betrayal_event"}
        retained = []
        for f in self._facts:
            if f.source_type == "story_memory" and f.type in strong_claim_types:
                self._rejected_facts += 1
                continue
            retained.append(f)
        self._facts = retained

    # ─────────────────────────────────────────────────────────────────────────
    # CONVENIENCE: Summary statistics
    # ─────────────────────────────────────────────────────────────────────────

    def provenance_summary(self) -> Dict[str, Any]:
        """Returns a provenance summary for inclusion in output metadata."""
        type_counts: Dict[str, int] = {}
        quality_counts = {"high": 0, "medium": 0, "low": 0}
        source_counts = {"recap": 0, "story_memory": 0, "merged": 0}
        total_evidence = 0
        for f in self._facts:
            type_counts[f.type] = type_counts.get(f.type, 0) + 1
            src = getattr(f, "source_type", "recap")
            source_counts[src] = source_counts.get(src, 0) + 1
            total_evidence += len(f.evidence)
            if f.fact_quality_score >= 0.85:
                quality_counts["high"] += 1
            elif f.fact_quality_score >= 0.70:
                quality_counts["medium"] += 1
            else:
                quality_counts["low"] += 1
        return {
            "total_facts": len(self._facts),
            "rejected_facts_blocked": self._rejected_facts,
            "distinct_types": len(self.get_distinct_fact_types()),
            "fact_types_present": self.get_distinct_fact_types(),
            "total_evidence_units": total_evidence,
            "episodes_scanned": self._episodes_scanned,
            "episodes_found": self._episodes_found,
            "invariant_violations": len(self.evidence_required_invariant_check()),
            "type_counts": type_counts,
            "quality_distribution": quality_counts,
            "source_distribution": source_counts,
        }
