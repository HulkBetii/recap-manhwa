# StoryMemory Wiring & Cache Invalidation Audit (Round 2)

## 1. Overview & Verification Summary
- **Target Subsystem**: Stage 5 Narration Generation & Cumulative Context Management.
- **Audited Files**:
  - `story_memory.py`
  - `workflow_stages_1.py` (Stage 5 execution methods: lines ~1389, ~1476, ~2054, ~2270)
- **Status**: **VERIFIED & INTEGRATED**

---

## 2. Key Architecture & API Changes

### 2.1. `StoryMemory.load_validated(...)`
```python
@classmethod
def load_validated(
    cls,
    download_dir: str,
    comic_title: str = "",
    language: str = "vi",
    source_url: str = "",
    from_ep: int = 1,
    to_ep: int = 1,
    prompt_version: str = "us_apocalypse_v2",
) -> StoryMemory:
```
- **Cross-Comic Identity Validation**: If `stored_title != comic_title`, hard resets `episodes = {}`, `cumulative_glossary = {}`, `protagonist_name = ""`, preventing glossary and context leakage between different comic series.
- **Fingerprint Mismatch Invalidation**: If the comic title is the same but the fingerprint differs (due to prompt version or episode range changes), invalidates stale `episodes = {}` while preserving cumulative translation glossary.

### 2.2. `StoryMemory.save_with_fingerprint(...)`
```python
def save_with_fingerprint(
    self,
    download_dir: str,
    source_url: str = "",
    from_ep: int = 1,
    to_ep: int = 1,
    prompt_version: str = "us_apocalypse_v2",
) -> bool:
```
- Generates SHA-256 16-character fingerprint: `source_url|comic_title|from_ep|to_ep|language|prompt_version`.
- Atomically writes memory file with `_fingerprint` field using atomic tmp file replace.

---

## 3. Wiring Points in `workflow_stages_1.py`

| Location (Stage 5) | Method / Context | Action Taken | Prompt Version Configured |
| :--- | :--- | :--- | :--- |
| **Line ~1389** | `_run_narration_generation()` | Replaced raw `StoryMemory.load()` with `StoryMemory.load_validated(download_dir, comic_title, language, source_url, from_ep, to_ep, prompt_version="us_apocalypse_v2")` | `us_apocalypse_v2` |
| **Line ~1476** | `_run_narration_generation()` | Replaced `story_memory.save()` with `story_memory.save_with_fingerprint(download_dir, source_url, from_ep, to_ep, prompt_version="us_apocalypse_v2")` | `us_apocalypse_v2` |
| **Line ~2054** | Batch / Streaming narration setup | Configured `StoryMemory.load_validated()` with full validation params | `us_apocalypse_v2` |
| **Line ~2270** | Batch save hook | Configured `StoryMemory.save_with_fingerprint()` with atomic swap | `us_apocalypse_v2` |

---

## 4. Verification Test Cases
- `tests/test_stage12_metadata.py::test_story_memory_fingerprint`: Passed (Fingerprint uniqueness and determinism).
- `tests/test_stage12_metadata.py::test_story_memory_validated_load_and_reset`: Passed (Hard reset of glossary on comic title change).
- `tests/test_story_memory.py` (8/8 tests): Passed.
