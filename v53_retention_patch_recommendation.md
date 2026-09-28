# V5.3 Retention Hook Patch — Architectural Recommendations

**Status:** Proposed Engineering Specification (No Code Modifications Applied)  
**Target:** Solve 0–15s Protagonist Drop-off & Name Hallucination in Stage 5 Narration without Breaking V5.2 Grounding

---

## 1. Problem Statement Summary

The forensic audit of Episode 1 in *Zombie Revelation 82-08* revealed:
1. **66-Second Protagonist Delay:** First 10 narration sentences describe generic world disaster; protagonist only acts in Segment 11 (at `00:01:06`).
2. **Name Hallucination ("Paran"):** Episode 1 prompt lacked explicit protagonist anchoring, causing Gemini to copy the dummy name `"Paran"` from few-shot example lines in `markets/us_apocalypse/prompt.py`.
3. **Cold Start Gap:** `StoryMemory.get_previous_context(1)` returns `None` by design, leaving Episode 1 completely unanchored.

---

## 2. Proposed Surgical Recommendations for V5.3

### Recommendation 1: Dynamic Few-Shot Prompt Template (Neutralize Dummy Names)
- **Problem:** `markets/us_apocalypse/prompt.py:52-54` hardcodes `"Paran"` in all 3 few-shot hook examples.
- **Recommendation:** Replace static `"Paran"` with dynamically formatted `{protagonist_name or 'the protagonist'}` or neutral placeholders.
- **Expected Impact:** Eliminates the root vector of name hallucination across all series.

### Recommendation 2: Episode 1 Cold-Start Protagonist Resolver
- **Problem:** When starting Episode 1, `StoryMemory` is blank and has no prior episodes to infer from.
- **Recommendation:**
  1. If `task.payload` has `ip_context["protagonist_name"]`, pass it directly into `StoryMemory.protagonist_name` before Stage 5 runs.
  2. If not in payload, check `markets/us_apocalypse/metadata.py` character dictionary or perform a fast title/glossary extraction.
  3. Ensure `get_us_apocalypse_prompt(ep=1)` always receives `confirmed_protagonist_name` whenever identifiable.
- **Expected Impact:** Guarantees `ip_guidance_text` is populated with the true character name (`"Tae"`) in Segment 1 of Episode 1.

### Recommendation 3: Character-First Perspective Hook Directive
- **Problem:** Manhwa artists often spend pages 1–5 on wide establishing shots (skylines, burning buildings, running crowds). When the prompt asks Gemini to "follow the page", Gemini spends the first 60 seconds describing those background crowds before the protagonist appears.
- **Recommendation:** Add a specific hook directive for Segment 1:
  > *"Even if Page 1 depicts an establishing shot or panicked crowd, your very first narration sentence (Segment 1, 0-15s) MUST frame the disaster through [Protagonist Name]'s vantage point (e.g. 'When the zombie outbreak tears through Seoul, Tae doesn't panic—he grabs his sledgehammer and prepares for war.')."*
- **Expected Impact:** Instant audience attachment within the first 5 seconds while remaining 100% true to the visual comic art.

### Recommendation 4: Preserve V5.2 Trust Boundary & Grounding Invariants
- Keep `StoryFactGraph` as the post-generation extraction and validation layer.
- Retain all 143 automated tests and surface quality gates (`title: 0.85`, `thumbnail: 0.75`, `dashboard: 0.75`).
- Ensure narration enhancements improve retention without introducing unevidenced factual claims.

---

## 3. Readiness Evaluation for V5.3 Patch

| Criteria | Status | Evidence |
|---|---|---|
| **Root Cause Identified** | ✅ CONFIRMED | `markets/us_apocalypse/prompt.py:52-54` & `story_memory.py:426` |
| **Data Flow Traced** | ✅ CONFIRMED | `stage5_pipeline_audit_v53.md` & `storymemory_stage5_connection_report.md` |
| **V5.2 Test Baseline** | ✅ CONFIRMED | 143/143 tests passing |
| **Code Freeze Maintained** | ✅ CONFIRMED | Zero source code modifications made during audit |
