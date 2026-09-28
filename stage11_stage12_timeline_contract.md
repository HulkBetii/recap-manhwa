# Stage 11 ↔ Stage 12 Timeline & Chapters Data Contract Spec

## 1. Overview & Architectural Contract

Stage 11 (`workflow_stages_2.py:2657-2935`) performs final video assembly, concatenating episode videos into the master long-form video, calculating exact cumulative timestamps, and recording milestone chapter data into `task.artifacts["chapters"]`.

Stage 12 (`workflow_stages_2.py:2937-3050` & `markets/us_apocalypse/metadata.py`) consumes `chapters = task.artifacts.get("chapters")` to generate YouTube-compliant chapter markers, description timestamps, and story progression metadata.

---

## 2. Formal Schema

### 2.1 Stage 11 Output Schema (`task.artifacts["chapters"]`)

```json
[
  {
    "episode": 1,
    "timestamp": "00:00",
    "duration_seconds": 5576.0
  },
  {
    "episode": 15,
    "timestamp": "01:32:56",
    "duration_seconds": 6188.0
  },
  {
    "episode": 30,
    "timestamp": "03:16:04",
    "duration_seconds": 5034.0
  },
  "..."
]
```

### 2.2 Stage 12 Output Schema (`youtube_metadata["narrative_chapters"]`)

```json
[
  {
    "timestamp": "00:00",
    "title": "The Outbreak & Boat 82-08 Incident (Ep 1–14)",
    "episode": 1,
    "end_episode": 14,
    "theme": "The Outbreak & Boat 82-08 Incident",
    "evidence": [
      {
        "episode": 1,
        "snippet": "The virus broke out in section 82-08..."
      }
    ]
  },
  {
    "timestamp": "01:32:56",
    "title": "Martial Law & First Encounters (Ep 15–29)",
    "episode": 15,
    "end_episode": 29,
    "theme": "Martial Law & First Encounters",
    "evidence": [
      {
        "episode": 15,
        "snippet": "Helicopters broadcasted mandatory martial law..."
      }
    ]
  }
]
```

---

## 3. Core Contract Principles

### 3.1 Principle 1: Fail-Closed on Missing Timeline (No Synthetic Fallbacks)
- **Previous Anti-Pattern (Eliminated)**: When `chapters` was `None` or `[]`, code fabricated `minutes = k * 15` timestamps (`00:00`, `15:00`, `30:00`, `45:00`, ...).
- **V3 Contract**: If Stage 11 has not provided valid chapter timestamps, Stage 12 MUST return `narrative_chapters = []` and record `prepublish_audit["chapter_warnings"] = ["NO_REAL_TIMELINE_INPUT_FROM_STAGE_11"]`. Synthetic timestamps are completely prohibited.

### 3.2 Principle 2: Direct Milestone Preservation & Granular Mapping
- When Stage 11 passes pre-aggregated milestone chapters (e.g. 10 key timestamps for 143 episodes), Stage 12 maps them 1-to-1 (`is_direct_mapping = True`), preserving exact timestamps (`00:00`, `01:32:56`, `03:16:04`, etc.).
- When Stage 11 passes full per-episode timestamps (e.g. 143 items), Stage 12 samples the `num_arcs` (10 arcs for >= 35 eps) and retains the exact start timestamps of those sampled episodes.

### 3.3 Principle 3: Window-Based Narrative Grounding
- For any chapter representing episode range `[start_ep, end_ep]`, theme extraction is strictly restricted to recap transcript files in `range(start_ep, end_ep + 1)`.
- Recap data outside this window cannot contaminate the chapter theme.
- Supporting transcript snippets from that window are bound directly to the chapter object in `evidence`.

### 3.4 Principle 4: Archetype-Gated Theme Validation
- Every candidate theme is audited through `validate_chapter_theme(theme, archetype)`.
- Cross-archetype keywords (e.g. `"Tower Trials"`, `"Endless Ascent"`, `"Calamity Gate"`, `"Solo Awakening"`, `"Cultivation"`, `"Heavenly Demon"`) are strictly rejected in `zombie_apocalypse` and `bunker_prepper` stories.

---

## 4. Contract Verification Matrix

| Input Condition | Stage 12 Behavior | Audit Status | Output `narrative_chapters` |
|:---|:---|:---|:---|
| `chapters = None` | Fail-Closed: No timestamps generated | Warning: `NO_REAL_TIMELINE_INPUT_FROM_STAGE_11` | `[]` |
| `chapters = []` | Fail-Closed: No timestamps generated | Warning: `NO_REAL_TIMELINE_INPUT_FROM_STAGE_11` | `[]` |
| `chapters = 10 milestones` | Direct 1-to-1 mapping + window theme extraction | `chapter_00_present = True` | 10 grounded chapters with exact Stage 11 timestamps |
| `chapters = 143 per-ep` | Subsampled 10 arcs + window theme extraction | `chapter_00_present = True` | 10 grounded chapters with exact Stage 11 timestamps |
