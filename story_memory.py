from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional


class StoryMemory:
    """
    Manages cumulative story memory and rolling context across multi-episode
    comic recaps to ensure seamless binge-watching transitions and prevent context drift.
    """

    def __init__(
        self,
        comic_title: str = "",
        language: str = "vi",
        episodes: Optional[Dict[str, Any]] = None,
        cumulative_glossary: Optional[Dict[str, str]] = None,
        protagonist_name: str = "",
        protagonist_gender: str = "auto",
    ):
        self.comic_title = comic_title
        self.language = language
        self.episodes: Dict[str, Any] = episodes or {}
        self.cumulative_glossary: Dict[str, str] = cumulative_glossary or {}
        self.protagonist_name = protagonist_name
        self.protagonist_gender = protagonist_gender

    @classmethod
    def load(
        cls,
        download_dir: str,
        comic_title: str = "",
        language: str = "vi",
    ) -> StoryMemory:
        if not download_dir or not os.path.exists(download_dir):
            return cls(comic_title=comic_title, language=language)

        memory_file = os.path.join(download_dir, "story_memory.json")
        if os.path.exists(memory_file):
            try:
                with open(memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(
                    comic_title=data.get("comic_title", comic_title),
                    language=data.get("language", language),
                    episodes=data.get("episodes", {}),
                    cumulative_glossary=data.get("cumulative_glossary", {}),
                    protagonist_name=data.get("protagonist_name", ""),
                    protagonist_gender=data.get("protagonist_gender", "auto"),
                )
            except Exception:
                pass
        return cls(comic_title=comic_title, language=language)


    def save(self, download_dir: str) -> bool:
        if not download_dir:
            return False
        os.makedirs(download_dir, exist_ok=True)
        memory_file = os.path.join(download_dir, "story_memory.json")
        tmp_file = memory_file + ".tmp_" + str(int(time.time() * 1000))

        payload = {
            "comic_title": self.comic_title,
            "language": self.language,
            "protagonist_name": self.protagonist_name,
            "protagonist_gender": self.protagonist_gender,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_episodes_recorded": len(self.episodes),
            "episodes": self.episodes,
            "cumulative_glossary": self.cumulative_glossary,
        }

        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, memory_file)
            return True
        except Exception:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            return False

    @staticmethod
    def extract_cliffhanger(recap_data: list) -> str:
        """Extracts the final punchline/cliffhanger sentence from a recap list."""
        if not recap_data:
            return ""
        last_seg = recap_data[-1]
        speech = last_seg.get("speech", "") if isinstance(last_seg, dict) else getattr(last_seg, "speech", "")
        return speech.strip()

    @staticmethod
    def extract_chapter_summary(recap_data: list, max_sentences: int = 3) -> str:
        """
        Synthesizes a compact 2-3 sentence summary of the chapter's key progression
        based on opening, midpoint, and climax segments.
        """
        if not recap_data:
            return ""

        speeches = [
            (s.get("speech", "") if isinstance(s, dict) else getattr(s, "speech", "")).strip()
            for s in recap_data
        ]
        speeches = [s for s in speeches if s]
        if not speeches:
            return ""

        if len(speeches) <= max_sentences:
            return " ".join(speeches)

        first = speeches[0]
        mid = speeches[len(speeches) // 2]
        pre_last = speeches[-2] if len(speeches) > 2 else speeches[-1]

        summary_parts = [first, mid, pre_last]
        seen = set()
        unique_parts = []
        for p in summary_parts:
            if p not in seen:
                seen.add(p)
                unique_parts.append(p)

        return " ".join(unique_parts)


    @staticmethod
    def infer_protagonist_name(
        recap_data: list, glossary: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Attempts to infer the protagonist's proper name from glossary or early recap sentences.
        Uses title filtering, multi-word name detection, and frequency ranking across segments.
        """
        if glossary:
            for k, v in glossary.items():
                if any(role in k.lower() for role in ["protagonist", "mc", "nam chính", "main"]):
                    return v.strip()

        if not recap_data:
            return ""

        stopwords = {
            "When", "Everyone", "After", "With", "While", "Panic", "Then",
            "Here", "What", "This", "There", "Turns", "Once", "Even", "Just",
            "Only", "Because", "From", "Into", "Over", "Under", "Before",
            "Across", "Inside", "Outside", "Along", "Around", "During",
            "Without", "Despite", "Although", "Instead", "Between",
            "Dilapidated", "Shocked", "Suddenly", "Looking", "Walking", "Holding",
            "Seeing", "Staring", "Clutching", "Stepping", "Running", "Standing",
            "Turning", "Leaning", "Whispering", "Screaming", "Falling", "Rising",
            "Dropping", "Pulling", "Pushing", "Grinding", "Unfazed", "Collapsed",
            "Bare", "Cold", "Dark", "Heavy", "Deep", "Pure", "Every", "Still",
            "Spinning", "Sliding", "Day", "Night", "Morning", "Evening",
            "Khi", "Sau", "Trong", "Giữa", "Trước", "Nếu", "Nhưng", "Thế",
            "Tuy", "Dù", "Ngay", "Đúng", "Cùng", "Toàn", "Khắp", "Mọi",
            "Quân", "Đích", "Tiểu", "Vị", "Bản", "Cơn", "Trận", "Cuộc",
            "Hết", "Cả", "Mỗi", "Tất", "Chính", "Người", "Bộ", "Nơi",
            # Titles & Pronouns
            "Tổng", "Tổng thống", "Chủ tịch", "Thủ tướng", "Đại tá", "Trung tá", "Thiếu tá",
            "Đại úy", "Thượng úy", "Trung úy", "Thiếu úy", "Tướng", "Bộ trưởng", "Thứ trưởng",
            "Bác sĩ", "Giáo sư", "Tiến sĩ", "Thầy", "Cô", "Anh", "Chị", "Em", "Ông", "Bà",
            "Cụ", "Bác", "Chú", "Dì", "Cô nàng", "Anh chàng", "Thanh niên", "Cựu binh",
            "Nhân vật", "Người", "Quân đội", "Chính phủ", "Tiểu hành tinh",
            "President", "General", "Commander", "Captain", "Doctor", "Professor", "Minister",
            "King", "Queen", "Lord", "Lady", "Prince", "Princess",
        }
        geo_words = {"Earth", "Seoul", "Korea", "America", "Tokyo", "Japan", "Nhật", "Hàn", "Mỹ", "Trái Đất", "Survival", "Life", "Truth", "Silence"}

        title_pattern = r'\b(Tổng thống|Tổng|Chủ tịch|Thủ tướng|Đại tá|Bác sĩ|President|General|Commander|Doctor|Professor)\s+([A-ZÀ-Ỹa-zà-ỹ]+(\s+[A-ZÀ-Ỹa-zà-ỹ]+)?)'

        name_counts: Dict[str, int] = {}
        mid_sentence_counts: Dict[str, int] = {}

        for seg in recap_data[:35]:
            speech = (
                seg.get("speech", "")
                if isinstance(seg, dict)
                else getattr(seg, "speech", "")
            )
            cleaned_speech = re.sub(title_pattern, '', speech)
            words = re.findall(r'\b\w+\b', cleaned_speech)

            for i in range(len(words)):
                w = words[i]
                if w[0].isupper() and w not in stopwords and w not in geo_words and not w.endswith("day") and len(w) >= 3:
                    is_mid_sentence = (i > 0)
                    # Check for two-word name (e.g. Seongho Kang, Penelope Eckart)
                    if i + 1 < len(words):
                        w2 = words[i + 1]
                        if w2[0].isupper() and w2 not in stopwords and w2 not in geo_words and len(w2) >= 3:
                            full_name = f"{w} {w2}"
                            name_counts[full_name] = name_counts.get(full_name, 0) + (8 if is_mid_sentence else 4)
                            if is_mid_sentence:
                                mid_sentence_counts[full_name] = mid_sentence_counts.get(full_name, 0) + 1
                    
                    name_weight = 5 if is_mid_sentence else 1
                    name_counts[w] = name_counts.get(w, 0) + name_weight
                    if is_mid_sentence:
                        mid_sentence_counts[w] = mid_sentence_counts.get(w, 0) + 1

        if not name_counts:
            return ""

        # Prioritize names that appeared mid-sentence over candidates that only ever appeared at sentence start
        candidates_with_mid = {k: v for k, v in name_counts.items() if mid_sentence_counts.get(k, 0) > 0}
        if candidates_with_mid:
            sorted_candidates = sorted(candidates_with_mid.items(), key=lambda x: x[1], reverse=True)
            return sorted_candidates[0][0]

        sorted_candidates = sorted(name_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_candidates[0][0]

    @staticmethod
    def infer_protagonist_gender(
        glossary: Optional[Dict[str, str]] = None,
        recap_data: Optional[list] = None,
    ) -> str:
        """
        Attempts to infer protagonist gender ('male', 'female', or 'auto') from glossary or early recap sentences.
        """
        if glossary:
            for k, v in glossary.items():
                k_lower = k.lower().strip()
                v_lower = str(v).lower().strip()
                if "gender" in k_lower or "giới tính" in k_lower or "sex" in k_lower:
                    if any(w in v_lower for w in ["female", "nữ", "woman", "girl", "f"]):
                        return "female"
                    if any(w in v_lower for w in ["male", "nam", "man", "boy", "m"]):
                        return "male"
                if any(r in k_lower for r in ["heroine", "nữ chính", "villainess", "queen", "lady"]):
                    return "female"
                if any(r in k_lower for r in ["hero", "nam chính", "king", "lord"]):
                    return "male"

        if recap_data:
            female_score = 0
            male_score = 0
            for seg in recap_data[:5]:
                speech = (
                    seg.get("speech", "")
                    if isinstance(seg, dict)
                    else getattr(seg, "speech", "")
                ).lower()
                female_score += sum(speech.count(w) for w in ["cô nàng", "nữ chính", "cô ấy", "nàng", "chị đại", "our girl", "her ", "she ", "heroine", "villainess"])
                male_score += sum(speech.count(w) for w in ["anh chàng", "thanh niên", "cậu ấy", "our boy", "his ", "he ", "him "])
            if female_score > male_score and female_score >= 2:
                return "female"
            elif male_score > female_score and male_score >= 2:
                return "male"

        return "auto"

    def set_protagonist_name(self, name: str) -> None:
        """Sets or updates the detected protagonist name."""
        if name and name.strip():
            self.protagonist_name = name.strip()

    def set_protagonist_gender(self, gender: str) -> None:
        """Sets or updates the detected protagonist gender ('male', 'female', or 'auto')."""
        if gender and gender.strip().lower() in {"male", "female", "auto"}:
            self.protagonist_gender = gender.strip().lower()

    def add_episode_recap(
        self,
        ep: int,
        recap_data: list,
        language: str = "vi",
        protagonist_name: Optional[str] = None,
        protagonist_gender: Optional[str] = None,
    ) -> None:
        """Stores structured context for an episode."""
        if not recap_data:
            return

        if protagonist_name:
            self.set_protagonist_name(protagonist_name)
        elif not self.protagonist_name:
            inferred = self.infer_protagonist_name(
                recap_data, self.cumulative_glossary
            )
            if inferred:
                self.set_protagonist_name(inferred)

        if protagonist_gender:
            self.set_protagonist_gender(protagonist_gender)
        elif self.protagonist_gender == "auto":
            inferred_gender = self.infer_protagonist_gender(
                self.cumulative_glossary, recap_data
            )
            if inferred_gender != "auto":
                self.set_protagonist_gender(inferred_gender)

        cliffhanger = self.extract_cliffhanger(recap_data)
        summary = self.extract_chapter_summary(recap_data)
        opening = (
            recap_data[0].get("speech", "")
            if isinstance(recap_data[0], dict)
            else getattr(recap_data[0], "speech", "")
        )

        self.episodes[str(ep)] = {
            "episode": ep,
            "opening": opening.strip(),
            "closing_cliffhanger": cliffhanger,
            "summary": summary,
            "segment_count": len(recap_data),
            "timestamp": time.time(),
        }


    def get_previous_context(
        self, current_ep: int, download_dir: Optional[str] = None
    ) -> Optional[dict]:
        """
        Retrieves previous chapter context for current_ep.
        Looks up memory dict first, or attempts to read from episode_{ep-1}/recap.json on disk.
        """
        if current_ep <= 1:
            return None

        prev_ep = current_ep - 1
        prev_data = self.episodes.get(str(prev_ep))

        if not prev_data and download_dir:
            prev_recap_path = os.path.join(
                download_dir, f"episode_{prev_ep}", "recap.json"
            )
            if os.path.exists(prev_recap_path):
                try:
                    with open(prev_recap_path, "r", encoding="utf-8") as f:
                        disk_recap = json.load(f)
                    if disk_recap and isinstance(disk_recap, list):
                        self.add_episode_recap(
                            prev_ep, disk_recap, language=self.language
                        )
                        prev_data = self.episodes.get(str(prev_ep))
                except Exception:
                    pass

        if not prev_data:
            return None

        recent_summaries = []
        start_ep = max(1, current_ep - 3)
        for e in range(start_ep, prev_ep):
            e_info = self.episodes.get(str(e))
            if e_info and e_info.get("summary"):
                recent_summaries.append(f"Tập {e}: {e_info['summary']}")

        macro_ctx = " | ".join(recent_summaries) if recent_summaries else ""

        return {
            "previous_episode": prev_ep,
            "closing_cliffhanger": prev_data.get("closing_cliffhanger", ""),
            "summary": prev_data.get("summary", ""),
            "macro_context": macro_ctx,
            "active_plot_threads": prev_data.get("closing_cliffhanger", ""),
            "protagonist_name": self.protagonist_name,
            "protagonist_gender": self.protagonist_gender,
        }
