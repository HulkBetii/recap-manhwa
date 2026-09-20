from __future__ import annotations

import os
import re
import math
import json
import time
import wave
import shutil
import asyncio
import subprocess
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    httpx = None


import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from visual_scorer import VisualSemanticScorer
from app import find_ffmpeg, get_working_encoder, parse_time_to_seconds
from workflow_stages_2 import detect_clean_panel_and_focal_point, get_video_duration


# High-impact vocabulary for scoring climax intensity
ACTION_KEYWORDS = {
    # English
    "monster", "beast", "mutant", "boss", "swarm", "demon", "undead", "zombie",
    "slay", "slash", "sever", "strike", "obliterate", "destroy", "shatter", "crush",
    "sword", "blade", "shockwave", "lightning", "explosion", "fire", "energy",
    "awakening", "power", "unfazed", "unstoppable", "god", "titan", "lethal",
    "furious", "barrage", "parry", "clash", "overwhelm", "breach", "perish",
    # Vietnamese
    "quái vật", "quái thú", "dị biến", "trùm", "huyết sát", "ác mộng",
    "chém", "đồ sát", "hủy diệt", "bùng nổ", "thức tỉnh", "sấm sét", "nghịch thiên",
    "áp đảo", "tuyệt vọng", "sinh tử", "thần cấp", "bá đạo", "khiếp sợ", "kinh hoàng"
}


def ensure_whoosh_sfx(sfx_path: str) -> str:
    """Generates a high-energy cinematic time-shift whoosh SFX if missing."""
    if os.path.exists(sfx_path) and os.path.getsize(sfx_path) > 1000:
        return sfx_path

    os.makedirs(os.path.dirname(os.path.abspath(sfx_path)), exist_ok=True)
    sample_rate = 44100
    duration = 0.85
    num_samples = int(sample_rate * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False)

    # Low rumble (110Hz) sweeping up to 2400Hz and diving into sub-drop (75Hz)
    freq = 110 + 2290 * np.sin(np.pi * (t / duration)) ** 1.6
    phase = 2 * np.pi * np.cumsum(freq) / sample_rate
    sine_wave = np.sin(phase)

    # Pink-ish filtered noise burst for air velocity
    noise = np.random.normal(0, 0.45, num_samples)
    env = np.exp(-((t - 0.55) ** 2) / (2 * 0.15 ** 2))

    whoosh = (sine_wave * 0.42 + noise * 0.58) * env
    whoosh = np.clip(whoosh, -1.0, 1.0)
    int_samples = (whoosh * 32767).astype(np.int16)

    with wave.open(sfx_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int_samples.tobytes())

    return sfx_path


class ArcClimaxMiner:
    """
    Scans episodes across a full story arc to discover the most dramatic,
    visually stunning future climax moment for In Medias Res hook creation.
    """

    @staticmethod
    def scan_climax_episode(
        download_dir: str,
        from_ep: int = 1,
        to_ep: int = 100,
        min_future_offset: int = 2
    ) -> Dict[str, Any]:
        available_eps = []
        for d in os.listdir(download_dir):
            if d.startswith("episode_") and os.path.isdir(os.path.join(download_dir, d)):
                try:
                    num = int(d.split("_")[1])
                    if from_ep <= num <= to_ep:
                        available_eps.append(num)
                except ValueError:
                    continue
        available_eps.sort()

        if not available_eps:
            raise ValueError(f"No episode folders found in {download_dir}")

        candidate_eps = [ep for ep in available_eps if ep >= from_ep + min_future_offset]
        if not candidate_eps:
            candidate_eps = available_eps[-1:] if len(available_eps) > 1 else available_eps

        best_ep = candidate_eps[-1]
        best_score = -1.0
        best_narration = ""
        best_snippet = ""

        for ep in candidate_eps:
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            narr_path = os.path.join(ep_dir, "narration.txt")
            if not os.path.exists(narr_path):
                continue

            with open(narr_path, "r", encoding="utf-8") as f:
                text = f.read()

            text_lower = text.lower()
            keyword_count = sum(text_lower.count(kw) for kw in ACTION_KEYWORDS)
            
            # Bonus weight for late-arc episodes
            progress_ratio = (ep - from_ep) / max(1, (to_ep - from_ep))
            combined_score = keyword_count * (1.0 + 0.5 * progress_ratio)

            if combined_score > best_score:
                best_score = combined_score
                best_ep = ep
                best_narration = text
                best_snippet = text[:300]

        origin_text = ""
        ep1_dir = os.path.join(download_dir, f"episode_{from_ep}")
        ep1_narr = os.path.join(ep1_dir, "narration.txt")
        if os.path.exists(ep1_narr):
            with open(ep1_narr, "r", encoding="utf-8") as f:
                origin_text = f.read()[:300]

        return {
            "climax_episode": best_ep,
            "climax_score": round(best_score, 2),
            "climax_narration_sample": best_snippet,
            "origin_narration_sample": origin_text,
            "total_episodes_available": len(available_eps),
        }

    @staticmethod
    def select_top_climax_images(
        download_dir: str,
        climax_episode: int,
        num_images: int = 3,
        min_point_threshold: int = 75
    ) -> List[Dict[str, Any]]:
        img_dir = os.path.join(download_dir, f"episode_{climax_episode}", "images")
        if not os.path.exists(img_dir):
            raise FileNotFoundError(f"Images directory not found: {img_dir}")

        image_files = [
            f for f in os.listdir(img_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ]
        if not image_files:
            raise FileNotFoundError(f"No image files found in: {img_dir}")

        scored_images = []
        for f in image_files:
            img_path = os.path.join(img_dir, f)
            try:
                with Image.open(img_path) as img:
                    score, bd = VisualSemanticScorer.calculate_score_from_pil(img)
                    is_meaningless = bd.get("is_meaningless", False)
                    if not is_meaningless and score >= min_point_threshold:
                        action_score = bd.get("action_context", 0.0)
                        char_score = bd.get("character_presence", 0.0)
                        np_gray = np.array(img.convert("L"))
                        white_ratio = float(np.mean(np_gray > 240))
                        # Heavily penalize panels with large white text boxes or empty gutters
                        composite = (score * 0.5 + action_score * 0.3 + char_score * 0.2) * (1.0 - min(0.9, white_ratio * 1.5))
                        scored_images.append({
                            "filename": f,
                            "path": img_path,
                            "score": score,
                            "action_score": action_score,
                            "char_score": char_score,
                            "white_ratio": white_ratio,
                            "composite": composite
                        })
            except Exception:
                continue

        scored_images.sort(key=lambda x: x["composite"], reverse=True)

        if len(scored_images) < num_images:
            scored_images.clear()
            for f in image_files:
                img_path = os.path.join(img_dir, f)
                try:
                    with Image.open(img_path) as img:
                        score, bd = VisualSemanticScorer.calculate_score_from_pil(img)
                        if not bd.get("is_meaningless", False):
                            np_gray = np.array(img.convert("L"))
                            white_ratio = float(np.mean(np_gray > 240))
                            composite = (score * 0.5) * (1.0 - min(0.9, white_ratio * 1.5))
                            scored_images.append({
                                "filename": f,
                                "path": img_path,
                                "score": score,
                                "white_ratio": white_ratio,
                                "composite": composite
                            })
                except Exception:
                    continue
            scored_images.sort(key=lambda x: x["composite"], reverse=True)

        return scored_images[:num_images]


class HookArchetype(str, Enum):
    OUTRAGEOUS_FLEX = "outrageous_flex"           # Ao trình & Khinh địch (God-mode combat, unbothered slaughter)
    ABSURD_HIGH_CONCEPT = "absurd_high_concept"   # Độc chiêu / Trục lợi dị biệt (Bizarre exploit / cheat power)
    VENGEANCE_RETRIBUTION = "vengeance_retribution" # Phản bội & Phục thù (Betrayal, rebirth, wrath)
    TICKING_BOMB_CRISIS = "ticking_bomb_crisis"     # Đếm ngược sinh tử (Imminent doom, 0 seconds left)
    OPEN_LOOP_PARADOX = "open_loop_paradox"         # Nghịch lý mở / Bí ẩn vô giải (Impossible survival, mind-bending contrast)


class DynamicHookDirector:
    """
    Directs dynamic In Medias Res retention hooks across 5 distinct archetypes,
    enforcing a strict 14-16.5s length and irresistible Open Loop endings.
    """

    @staticmethod
    def detect_archetype(
        climax_text: str = "",
        origin_text: str = "",
        comic_title: str = ""
    ) -> HookArchetype:
        combined = f"{comic_title} {origin_text} {climax_text}".lower()

        # 1. Vengeance / Retribution
        vengeance_kw = [
            "phản bội", "trả thù", "phục thù", "đâm sau lưng", "oán hận", "thù hận",
            "betray", "revenge", "traitor", "backstab", "retribution", "vengeance",
            "배신", "복수", "裏切り", "復讐"
        ]
        if any(k in combined for k in vengeance_kw):
            return HookArchetype.VENGEANCE_RETRIBUTION

        # 2. Ticking Bomb / Crisis
        crisis_kw = [
            "đếm ngược", "sắp chết", "ngày tàn", "diệt vong", "tuyệt chủng", "phút chót", "giây cuối",
            "countdown", "seconds left", "annihilation", "extinction", "imminent doom", "ticking",
            "멸망", "카운트다운", "滅亡", "カウントダウン"
        ]
        if any(k in combined for k in crisis_kw):
            return HookArchetype.TICKING_BOMB_CRISIS

        # 3. Absurd High Concept / Exploit
        exploit_kw = [
            "hệ thống", "trục lợi", "thâu tóm", "độc quyền", "gian lận", "hack", "buôn bán", "thương nhân",
            "system", "exploit", "monopolize", "cheat", "glitch", "merchant",
            "독점", "사기", "시스템", "独占"
        ]
        if any(k in combined for k in exploit_kw):
            return HookArchetype.ABSURD_HIGH_CONCEPT

        # 4. Paradox / Mystery
        paradox_kw = [
            "nghịch lý", "bí ẩn", "không thể tin", "dị thường", "vô lý", "kỳ dị",
            "paradox", "mystery", "impossible", "unexplainable", "anomaly",
            "미스터리", "패러독스", "謎", "パラドックス"
        ]
        if any(k in combined for k in paradox_kw):
            return HookArchetype.OPEN_LOOP_PARADOX

        # 5. Default: Outrageous Flex (Dominant combat / flex)
        return HookArchetype.OUTRAGEOUS_FLEX

    @classmethod
    def get_archetype_template(
        cls,
        archetype: HookArchetype,
        protagonist_name: str,
        language: str = "en"
    ) -> str:
        lang = language.lower()
        p_name = protagonist_name.strip() if protagonist_name and protagonist_name.strip() else ""

        if lang in ("vi", "vietnamese"):
            p_vi = p_name if p_name else "chàng trai"
            if archetype == HookArchetype.ABSURD_HIGH_CONCEPT:
                return (
                    f"Khi nhân loại tuyệt vọng giành giật từng mẩu bánh, {p_vi} đã âm thầm thao túng hệ thống "
                    f"để thâu tóm mọi tài nguyên sinh tồn. Anh không cứu thế giới, anh trục lợi từ nó. "
                    f"Vậy mánh khóe điên rồ này đã bắt đầu như thế nào?"
                )
            elif archetype == HookArchetype.VENGEANCE_RETRIBUTION:
                return (
                    f"Những kẻ từng phản bội và xô ngã {p_vi} xuống vực sâu giờ chỉ biết run rẩy van xin trong tuyệt vọng. "
                    f"Lưỡi kiếm báo thù đã giáng xuống, không một ai được dung thứ. "
                    f"Nhưng nỗi đau tột cùng nào đã biến một kẻ vô danh thành ác quỷ săn mồi?"
                )
            elif archetype == HookArchetype.TICKING_BOMB_CRISIS:
                return (
                    f"Chỉ mười giây trước khi làn sóng quái vật san phẳng cứ điểm cuối cùng, {p_vi} một mình lao thẳng vào tâm bão hủy diệt "
                    f"để lật ngược ván cờ sinh tử. Không một ai tin anh có thể sống sót. "
                    f"Vậy phép màu nào đã xảy ra ngay trước bờ vực tuyệt chủng?"
                )
            elif archetype == HookArchetype.OPEN_LOOP_PARADOX:
                return (
                    f"Tại nơi cả một quân đoàn tinh nhuệ bị xóa sổ trong chớp mắt, {p_vi} lại bước ra nguyên vẹn "
                    f"cùng sức mạnh vượt khỏi mọi quy luật tự nhiên. Đó là một nghịch lý không ai lý giải nổi. "
                    f"Thứ gì đã biến đổi anh trong khoảnh khắc sinh tử đầu tiên này?"
                )
            else:  # OUTRAGEOUS_FLEX
                return (
                    f"Một nhát chém xé toạc bầu trời, trảm sát quái thú thảm họa trong chớp mắt. "
                    f"Hiện tại, {p_vi} là nỗi khiếp sợ của ngày tận thế. "
                    f"Nhưng trước khi thống trị tất cả... bí mật đen tối nào đã xảy ra vào ngày đầu tiên này?"
                )

        elif lang in ("ko", "korean"):
            p_ko = p_name if p_name else "그"
            if archetype == HookArchetype.ABSURD_HIGH_CONCEPT:
                return (
                    f"모든 인류가 생존을 위해 발버둥 칠 때, {p_ko}은(는) 홀로 시스템을 완벽히 장악하여 모든 자원을 독점했습니다. "
                    f"세상을 구원하는 것이 아니라 농락하는 남자. 과연 이 기상천외한 사기극의 시작은 무엇이었을까요?"
                )
            elif archetype == HookArchetype.VENGEANCE_RETRIBUTION:
                return (
                    f"{p_ko}을(를) 배신하고 절망의 구렁텅이로 밀어 넣었던 자들이 이제는 목숨을 구걸하고 있습니다. "
                    f"그의 심판에는 자비란 없습니다. 하지만 대체 어떤 잔혹한 배신이 그를 복수의 괴물로 만들었을까요?"
                )
            elif archetype == HookArchetype.TICKING_BOMB_CRISIS:
                return (
                    f"괴물 군단이 인류의 마지막 거점을 집어삼키기 직전, {p_ko}은(는) 홀로 파멸의 소용돌이 속으로 뛰어듭니다. "
                    f"그 누구도 생환을 믿지 않았던 절체절명의 위기. 그는 과연 이 지옥 같은 카운트다운을 어떻게 뒤집었을까요?"
                )
            elif archetype == HookArchetype.OPEN_LOOP_PARADOX:
                return (
                    f"정예 군단마저 순식간에 전멸한 사지에서, {p_ko}은(는) 자연의 법칙을 비웃듯 상처 하나 없이 걸어 나왔습니다. "
                    f"그 누구도 해명할 수 없는 거대한 미스터리. 그 첫날, 대체 무엇이 그를 각성시켰을까요?"
                )
            else:  # OUTRAGEOUS_FLEX
                return (
                    f"단 한 번의 가벼운 검격으로 재앙급 돌연변이 괴물을 단숨에 베어 넘깁니다. "
                    f"현재 {p_ko}은(는) 아포칼립스 세계의 절대 패자로 군림하고 있습니다. "
                    f"하지만 전 세계가 그의 발아래 무릎 꿇기 전... 과연 첫날 폐허 속에서는 무슨 일이 벌어졌을까요?"
                )

        elif lang in ("ja", "japanese"):
            p_ja = p_name if p_name else "彼"
            if archetype == HookArchetype.ABSURD_HIGH_CONCEPT:
                return (
                    f"全人類が生き残りを賭けて絶望する中、{p_ja}はただ一人、世界システムをハックして終末の富を独占していた。 "
                    f"救済ではなく完全な支配。この前代未聞の悪巧みは、一体どこから始まったのか？"
                )
            elif archetype == HookArchetype.VENGEANCE_RETRIBUTION:
                return (
                    f"{p_ja}を裏切り、地獄へと突き落とした者たちが、いまや命乞いをして震えている。 "
                    f"彼の復讐に慈悲はない。だが、かつて無力だった彼を、これほどの怪物に変えた真実とは何だったのか？"
                )
            elif archetype == HookArchetype.TICKING_BOMB_CRISIS:
                return (
                    f"怪物の群れが人類最後の砦を蹂躙する直前、{p_ja}はたった一人で破滅の渦中へと飛び込んだ。 "
                    f"生還の可能性はゼロ。絶滅のカウントダウンの中、彼は一体いかにしてこの結末を覆したのか？"
                )
            elif archetype == HookArchetype.OPEN_LOOP_PARADOX:
                return (
                    f"精鋭部隊が一瞬で全滅した死地から、{p_ja}は傷一つなく、世界の理を超越した力を持って生還した。 "
                    f"誰も解き明かせない不条理なパラドックス。あの日、彼を覚醒させた真実とは何だったのか？"
                )
            else:  # OUTRAGEOUS_FLEX
                return (
                    f"たった一振りの剣撃が、災害級の巨大怪物を一瞬で両断する。 "
                    f"現在、{p_ja}は終末世界の絶対的覇者として君臨している。 "
                    f"だが、世界が彼にひれ伏す前…この最初の一日に、一体何が起きたというのか？"
                )

        else:  # English (Default)
            p_en = p_name if p_name else "our protagonist"
            if archetype == HookArchetype.ABSURD_HIGH_CONCEPT:
                return (
                    f"While billions despair over scraps, {p_en} silently hijacked the global system to monopolize every vital resource in the wasteland. "
                    f"He didn't come to save humanity—he came to exploit it. "
                    f"How did such an insane scheme actually begin right here?"
                )
            elif archetype == HookArchetype.VENGEANCE_RETRIBUTION:
                return (
                    f"The traitors who cast {p_en} into the abyss now grovel on their knees, begging for mercy that will never come. "
                    f"His retribution is absolute. "
                    f"But what unspeakable betrayal transformed this harmless man into an unstoppable predator right here?"
                )
            elif archetype == HookArchetype.TICKING_BOMB_CRISIS:
                return (
                    f"Ten seconds before the swarm obliterates humanity's last stronghold, {p_en} dives headfirst into the cataclysm to turn the impossible tide. "
                    f"No one believed he would make it out alive. "
                    f"How did he survive the countdown to total extinction right here?"
                )
            elif archetype == HookArchetype.OPEN_LOOP_PARADOX:
                return (
                    f"Where an elite army was erased in seconds, {p_en} walked out completely untouched, wielding power that defies the laws of nature. "
                    f"It is an impossible paradox no one can explain. "
                    f"What truly changed inside that underground shelter right here?"
                )
            else:  # OUTRAGEOUS_FLEX
                return (
                    f"Surrounded by a terrifying mutant swarm, one man obliterates towering abominations without breaking a sweat. "
                    f"Today, {p_en} reigns as the wasteland's ultimate legend. "
                    f"Yet before commanding this godlike power... what deadly trial was he forced to survive right here?"
                )

    @classmethod
    async def generate_hook_script_llm(
        cls,
        comic_title: str,
        protagonist_name: str,
        archetype: HookArchetype,
        climax_text: str = "",
        origin_text: str = "",
        language: str = "en"
    ) -> Optional[str]:
        """Calls Google Gemini REST API via httpx to generate a dynamic custom hook."""
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key or not httpx:
            return None

        prompt = (
            f"You are an elite YouTube retention specialist for manhwa recap videos.\n"
            f"Task: Write a punchy 14-16s In Medias Res cold open hook script.\n"
            f"Comic Title: {comic_title}\n"
            f"Protagonist: {protagonist_name or 'the protagonist'}\n"
            f"Hook Archetype: {archetype.value}\n"
            f"Target Language: {language}\n"
            f"Climax Context: {climax_text[:350]}\n"
            f"Origin Context: {origin_text[:350]}\n\n"
            f"STRICT RULES:\n"
            f"1. Length: Exactly 35 to 45 words.\n"
            f"2. Mandatory OPEN LOOP ending: The final sentence MUST be an unresolved question or irresistible mystery leading directly into Episode 1.\n"
            f"3. 0% generic boilerplate (DO NOT use 'Giữa bầy quái thú...' or 'In a world where...').\n"
            f"4. Output ONLY the clean script text in {language}."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 200
            }
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text", "").strip()
                            clean_text = raw_text.replace("\n", " ").strip("\"'")
                            words = clean_text.split()
                            if 25 <= len(words) <= 60 and ("?" in clean_text or "？" in clean_text):
                                return clean_text
        except Exception:
            pass
        return None

    @classmethod
    async def generate_dynamic_retention_hook(
        cls,
        comic_title: str,
        protagonist_name: str,
        climax_episode: int,
        climax_text: str = "",
        origin_text: str = "",
        language: str = "en",
        custom_hook: Optional[str] = None,
        archetype: Optional[HookArchetype] = None
    ) -> Dict[str, Any]:
        """
        Master method to generate a retention hook:
        1. Uses custom_hook if provided.
        2. Detects archetype if not specified.
        3. Tries Gemini LLM synthesis.
        4. Falls back to deterministic high-impact archetype template.
        """
        if custom_hook and custom_hook.strip():
            return {
                "hook_script": custom_hook.strip(),
                "archetype": "custom",
                "word_count": len(custom_hook.strip().split()),
                "source": "custom"
            }

        selected_archetype = archetype or cls.detect_archetype(
            climax_text=climax_text,
            origin_text=origin_text,
            comic_title=comic_title
        )

        # Attempt LLM generation if available
        llm_script = await cls.generate_hook_script_llm(
            comic_title=comic_title,
            protagonist_name=protagonist_name,
            archetype=selected_archetype,
            climax_text=climax_text,
            origin_text=origin_text,
            language=language
        )
        if llm_script:
            return {
                "hook_script": llm_script,
                "archetype": selected_archetype.value,
                "word_count": len(llm_script.split()),
                "source": "gemini_llm"
            }

        # Dynamic Archetype Heuristic Template
        template_script = cls.get_archetype_template(
            archetype=selected_archetype,
            protagonist_name=protagonist_name,
            language=language
        )
        return {
            "hook_script": template_script,
            "archetype": selected_archetype.value,
            "word_count": len(template_script.split()),
            "source": "archetype_director"
        }

    @classmethod
    def generate_hook_script(
        cls,
        comic_title: str,
        protagonist_name: str,
        climax_episode: int,
        climax_text: str = "",
        origin_text: str = "",
        language: str = "en",
        custom_hook: Optional[str] = None,
        archetype: Optional[HookArchetype] = None
    ) -> str:
        """Synchronous generation helper for pipeline/tests."""
        if custom_hook and custom_hook.strip():
            return custom_hook.strip()

        selected_archetype = archetype or cls.detect_archetype(
            climax_text=climax_text,
            origin_text=origin_text,
            comic_title=comic_title
        )
        return cls.get_archetype_template(
            archetype=selected_archetype,
            protagonist_name=protagonist_name,
            language=language
        )


class InMediasResHookGenerator:
    """
    Backwards-compatible wrapper delegating to DynamicHookDirector.
    """

    @staticmethod
    def generate_hook_script(
        comic_title: str,
        protagonist_name: str,
        climax_episode: int,
        language: str = "en",
        custom_hook: Optional[str] = None
    ) -> str:
        return DynamicHookDirector.generate_hook_script(
            comic_title=comic_title,
            protagonist_name=protagonist_name,
            climax_episode=climax_episode,
            language=language,
            custom_hook=custom_hook
        )



class MicroIntroRenderer:
    """
    Renders a standalone, cinema-grade 14-16s video clip with smart panel cropping,
    ambient background, Ken Burns zoom, and Time-Shift Whoosh SFX.
    """

    @staticmethod
    async def render_intro_clip(
        intro_dir: str,
        hook_script: str,
        image_paths: List[str],
        language: str = "en",
        voice_id: str = "clone_andrew",
        ref_audio_path: Optional[str] = None,
        enable_sfx: bool = True,
        target_resolution: Tuple[int, int] = (1920, 1080),
        fps: int = 30
    ) -> Dict[str, Any]:
        os.makedirs(intro_dir, exist_ok=True)
        raw_audio_path = os.path.join(intro_dir, "raw_narration.mp3")
        final_audio_path = os.path.join(intro_dir, "audio.mp3")
        srt_path = os.path.join(intro_dir, "transcript.srt")
        video_path = os.path.join(intro_dir, "video.mp4")
        ffmpeg_exe = find_ffmpeg()

        # Step 1: Generate TTS audio & SRT
        from tts_provider import generate_tts
        audio_temp = raw_audio_path + ".tmp.mp3"
        srt_temp = srt_path + ".tmp.srt"

        # Auto-resolve voice by language if default
        actual_voice = voice_id
        actual_ref_audio = ref_audio_path
        if language.lower() in ("vi", "vietnamese"):
            import config
            if not actual_voice or actual_voice in ("ai33pro", "default", "auto", "clone"):
                actual_voice = getattr(config, "DEFAULT_VI_VOICE_ID", "clone")
            if not actual_ref_audio and actual_voice in ("clone", "auto", "omnivoice", "default"):
                actual_ref_audio = getattr(config, "DEFAULT_VI_REF_AUDIO", getattr(config, "DEFAULT_REF_AUDIO_PATH", None))
        elif (not actual_voice or actual_voice in ("ai33pro", "default", "auto", "clone")) and not actual_ref_audio:
            if language.lower() in ("ko", "korean"):
                actual_voice = "edge-tts_ko-KR-InJoonNeural"
            elif language.lower() in ("ja", "japanese"):
                actual_voice = "edge-tts_ja-JP-KeitaNeural"
            else:
                import config
                actual_voice = getattr(config, "DEFAULT_EN_VOICE_ID", "clone_andrew")
                actual_ref_audio = getattr(config, "DEFAULT_EN_REF_AUDIO", None)

        tts_ok = await generate_tts(
            hook_script,
            audio_temp,
            srt_temp,
            voice_id=actual_voice,
            ref_audio_path=actual_ref_audio,
            rate="+6%",  # Fast, punchy delivery for teaser hook
            pitch="+0Hz"
        )
        if not tts_ok:
            raise RuntimeError("Failed to synthesize TTS audio for Intro Hook")

        if os.path.exists(audio_temp):
            os.replace(audio_temp, raw_audio_path)
        if os.path.exists(srt_temp):
            os.replace(srt_temp, srt_path)

        # Measure TTS narration duration
        duration = get_video_duration(raw_audio_path, ffmpeg_exe)
        if not duration or duration <= 0:
            duration = 15.0

        # Step 2: Audio Post-Production (Pure Voiceover Narration + Optional SFX)
        project_root = os.path.dirname(os.path.abspath(__file__))
        default_sfx = os.path.join(project_root, "static", "sfx_time_shift_whoosh.wav")
        ensure_whoosh_sfx(default_sfx)

        if enable_sfx and os.path.exists(default_sfx):
            whoosh_delay_ms = max(500, int((duration - 1.0) * 1000))
            mix_cmd = [
                ffmpeg_exe, "-y",
                "-i", raw_audio_path,
                "-i", default_sfx,
                "-filter_complex",
                f"[1:a]highpass=f=350,adelay={whoosh_delay_ms}|{whoosh_delay_ms},volume=0.35[sfx];"
                "[0:a][sfx]amix=inputs=2:duration=first:dropout_transition=0[aout]",
                "-map", "[aout]",
                "-c:a", "libmp3lame", "-b:a", "192k",
                final_audio_path
            ]
            mix_res = subprocess.run(mix_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if mix_res.returncode != 0 or not os.path.exists(final_audio_path) or os.path.getsize(final_audio_path) == 0:
                shutil.copy2(raw_audio_path, final_audio_path)
        else:
            shutil.copy2(raw_audio_path, final_audio_path)

        # Step 3: Set up frame timeline for images
        W, H = target_resolution
        num_images = len(image_paths)
        dur_per_img = duration / max(1, num_images)

        displays = []
        curr_t = 0.0
        for p in image_paths:
            displays.append({
                "path": p,
                "start": curr_t,
                "end": curr_t + dur_per_img,
                "dur": dur_per_img
            })
            curr_t += dur_per_img

        # Step 4: Detect clean panel bounds & character focal points
        image_meta = {}
        loaded_pil = {}
        cached_bgs = {}

        for d in displays:
            p = d["path"]
            if p not in loaded_pil:
                im = Image.open(p)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                loaded_pil[p] = im

                # Smart panel isolation (cuts off speech bubbles & solid gutters)
                bounds, focal, skin_ratio, _ = detect_clean_panel_and_focal_point(im)
                image_meta[p] = (bounds, focal, skin_ratio)

                # Precompute blurred ambient background from CLEAN panel only
                cb_x, cb_y, W_c, H_c = bounds
                clean_crop = im.crop((cb_x, cb_y, cb_x + W_c, cb_y + H_c))
                bg_scale = max(W / float(W_c), H / float(H_c))
                bg_w = int(W_c * bg_scale)
                bg_h = int(H_c * bg_scale)
                bg_resized = clean_crop.resize((bg_w, bg_h), Image.Resampling.BOX)
                clean_crop.close()

                x_bg = (bg_w - W) // 2
                y_bg = (bg_h - H) // 2
                bg_crop = bg_resized.crop((x_bg, y_bg, x_bg + W, y_bg + H))
                bg_small = bg_crop.resize((160, 90), Image.Resampling.BOX)
                bg_blurred = bg_small.filter(ImageFilter.GaussianBlur(radius=8)).resize((W, H), Image.Resampling.BILINEAR)
                cached_bgs[p] = ImageEnhance.Brightness(bg_blurred).enhance(0.38)
                bg_resized.close()
                bg_crop.close()
                bg_small.close()
                bg_blurred.close()

        def make_frame(img_path: str, t_progress: float) -> Image.Image:
            img_obj = loaded_pil[img_path]
            bounds, focal, skin_ratio = image_meta[img_path]
            cb_x, cb_y, W_c, H_c = bounds
            x_focal, y_focal = focal

            # Cinematic framing: tighter framing for character portraits
            base_zoom = 1.06 if skin_ratio > 0.05 else 1.01
            zoom = base_zoom + 0.12 * t_progress

            aspect_panel = W_c / max(1.0, float(H_c))
            aspect_card = max(0.25, min(16.0 / 9.0, aspect_panel))
            card_h = H
            card_w = max(10, min(W, int(round(card_h * aspect_card))))
            card_x = (W - card_w) // 2
            card_y = 0

            if aspect_card <= aspect_panel:
                h_base = float(H_c)
                w_base = min(float(W_c), h_base * aspect_card)
            else:
                w_base = float(W_c)
                h_base = min(float(H_c), w_base / aspect_card)

            w_cam = w_base / zoom
            h_cam = h_base / zoom

            cx_ideal = cb_x + float(x_focal)
            cy_ideal = cb_y + float(y_focal)

            cx_min = cb_x + w_cam / 2.0
            cx_max = cb_x + W_c - w_cam / 2.0
            cx = cx_min if cx_min >= cx_max else float(np.clip(cx_ideal, cx_min, cx_max))

            cy_min = cb_y + h_cam / 2.0
            cy_max = cb_y + H_c - h_cam / 2.0
            cy = cy_min if cy_min >= cy_max else float(np.clip(cy_ideal, cy_min, cy_max))

            box = (cx - w_cam / 2.0, cy - h_cam / 2.0, cx + w_cam / 2.0, cy + h_cam / 2.0)
            fg_resized = img_obj.resize((card_w, card_h), Image.Resampling.BILINEAR, box=box)
            fg_enh = ImageEnhance.Color(fg_resized).enhance(1.08)
            fg_sharp = ImageEnhance.Sharpness(fg_enh).enhance(1.06)

            final_img = cached_bgs[img_path].copy()
            final_img.paste(fg_sharp, (card_x, card_y))

            fg_resized.close()
            fg_enh.close()
            fg_sharp.close()
            return final_img

        # Step 5: Frame-by-frame rendering into ffmpeg pipe
        total_frames = int(math.ceil(duration * fps))
        encoder = get_working_encoder(ffmpeg_exe, image_paths[0])

        ffmpeg_cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{W}x{H}",
            "-pix_fmt", "rgb24",
            "-r", str(fps),
            "-i", "-",
            "-i", final_audio_path,
            "-c:v", encoder,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            video_path
        ]

        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

        try:
            for frame_idx in range(total_frames):
                t = frame_idx / float(fps)
                active = displays[-1]
                for d in displays:
                    if d["start"] <= t < d["end"]:
                        active = d
                        break

                t_rel = (t - active["start"]) / max(0.01, active["dur"])
                frame_img = make_frame(active["path"], min(1.0, max(0.0, t_rel)))

                fade_start = duration - 0.40
                if t >= fade_start:
                    fade_ratio = (t - fade_start) / 0.40
                    fade_alpha = max(0.0, min(1.0, fade_ratio))
                    frame_arr = np.array(frame_img)
                    frame_arr = (frame_arr * (1.0 - fade_alpha)).astype(np.uint8)
                    proc.stdin.write(frame_arr.tobytes())
                else:
                    proc.stdin.write(frame_img.tobytes())

                frame_img.close()

            proc.stdin.close()
            proc.wait()
        except Exception as e:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            proc.kill()
            raise RuntimeError(f"Error during intro video rendering: {e}")
        finally:
            for im in loaded_pil.values():
                im.close()
            for im in cached_bgs.values():
                im.close()

        if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
            raise RuntimeError("Intro video output is missing or empty")

        return {
            "video_path": video_path,
            "audio_path": final_audio_path,
            "srt_path": srt_path,
            "duration": duration,
            "hook_script": hook_script
        }


class FastIntroPrepender:
    """
    Merges the rendered micro-intro clip in front of the main video or episode
    without re-encoding (stream copy, takes ~0.2 seconds).
    """

    @staticmethod
    def prepend_intro(
        intro_video_path: str,
        intro_srt_path: str,
        intro_duration: float,
        target_video_path: str,
        target_srt_path: str,
        output_video_path: str,
        output_srt_path: str
    ) -> bool:
        ffmpeg_exe = find_ffmpeg()
        work_dir = os.path.dirname(output_video_path)
        os.makedirs(work_dir, exist_ok=True)

        concat_txt = os.path.join(work_dir, "intro_concat_list.tmp.txt")
        p_intro = os.path.abspath(intro_video_path).replace("\\", "/")
        p_target = os.path.abspath(target_video_path).replace("\\", "/")
        with open(concat_txt, "w", encoding="utf-8") as f:
            f.write(f"file '{p_intro}'\n")
            f.write(f"file '{p_target}'\n")

        temp_out_vid = output_video_path + ".tmp.mp4"
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_txt,
            "-c", "copy",
            "-movflags", "+faststart",
            temp_out_vid
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(concat_txt):
            try:
                os.remove(concat_txt)
            except Exception:
                pass

        if res.returncode != 0 or not os.path.exists(temp_out_vid) or os.path.getsize(temp_out_vid) == 0:
            return False

        def parse_srt(path: str) -> List[Dict[str, Any]]:
            if not os.path.exists(path):
                return []
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            blocks = re.split(r"\n\s*\n", content)
            items = []
            for b in blocks:
                lines = b.strip().split("\n")
                if len(lines) >= 3:
                    m = re.match(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", lines[1])
                    if m:
                        items.append({
                            "start": parse_time_to_seconds(m.group(1).replace(",", ".")),
                            "end": parse_time_to_seconds(m.group(2).replace(",", ".")),
                            "text": "\n".join(lines[2:])
                        })
            return items

        def format_ts(sec: float) -> str:
            hrs = int(sec // 3600)
            mins = int((sec % 3600) // 60)
            secs = int(sec % 60)
            ms = int(round((sec - int(sec)) * 1000))
            return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

        intro_subs = parse_srt(intro_srt_path)
        main_subs = parse_srt(target_srt_path)

        shifted_subs = []
        idx = 1
        for s in intro_subs:
            shifted_subs.append(f"{idx}\n{format_ts(s['start'])} --> {format_ts(s['end'])}\n{s['text']}\n")
            idx += 1

        for s in main_subs:
            shifted_subs.append(f"{idx}\n{format_ts(s['start'] + intro_duration)} --> {format_ts(s['end'] + intro_duration)}\n{s['text']}\n")
            idx += 1

        temp_out_srt = output_srt_path + ".tmp.srt"
        with open(temp_out_srt, "w", encoding="utf-8") as f:
            f.write("\n".join(shifted_subs).strip() + "\n")

        os.replace(temp_out_vid, output_video_path)
        os.replace(temp_out_srt, output_srt_path)
        return True
