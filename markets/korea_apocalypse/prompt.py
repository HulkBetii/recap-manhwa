from __future__ import annotations

import json
import os
from typing import Optional


def get_korea_apocalypse_prompt(
    comic_title: str,
    ep: int,
    total_pages: int,
    glossary: Optional[str] = None,
    point_score_threshold: int = 60,
) -> str:
    if not glossary:
        try:
            glossary_path = os.path.join(os.getcwd(), "glossary.json")
            if os.path.exists(glossary_path):
                with open(glossary_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    glossary = ", ".join(f'"{k}" -> "{v}"' for k, v in data.items())
                else:
                    glossary = str(data)
            else:
                glossary = "No glossary provided."
        except Exception:
            glossary = "No glossary provided."

    if ep == 1:
        intro_rule = """
EPISODE 1 HIGH-RETENTION HOOK (0-5s GOLDEN RULE):
The first sentence must be an overwhelming tension-filled opening hook.
- Shocking crisis + hidden awakening ability hint.
- No greetings. Example: "On the day 99% of humanity turned into monsters, the lowest-rank hunter awakened the one absolute power."
"""
    else:
        intro_rule = """
EPISODE CONTINUATION:
Start immediately with the ongoing high-stakes action from the previous chapter.
- No greetings, no recap. Jump straight into the scene.
- End with a cliffhanger that seamlessly connects to the next chapter.
"""

    pt = point_score_threshold

    return f"""
ROLE:
You are a top-tier Korean YouTube webtoon binge-watching specialist and scriptwriter.
Analyze the provided webtoon images and create a 100% immersive Korean narration script with the breathtaking tension and satisfaction unique to the Apocalypse/Survival genre.

SOURCE:
Title: "{comic_title}"
Episode: {ep}
Total provided pages: {total_pages}

{intro_rule}

STORY BEAT FIRST WORKFLOW:
For EVERY segment, follow this workflow:
  Step 1 - STORY BEAT:   Identify the next important story event.
  Step 2 - FIND PAGE:    Scan PDF for candidate pages showing it.
  Step 3 - SELECT PAGE:  Pick page or multi-page range [<start>, <end>] with clear visual evidence.
  Step 4 - WRITE:        Write 1-2 concise narration sentences based on the page.

STRICT ASCENDING PAGE ORDER:
All page numbers must appear in strictly ascending order.
Never go backward, never repeat, never rearrange.

CORE TONE & NARRATION RULES:
1. Sentence endings:
   - Use tension-filled Korean endings: ~하는데요, ~하게 됩니다, ~하고 맙니다, ~그 순간!, ~상황입니다.
2. Pacing:
   - Keep sentences around 35 characters, short and punchy for TTS.
   - Use active verbs (처단하다, 각성하다, 돌파하다, 압도하다) over passive forms.
3. YouTube Safety:
   - Avoid demonetization words. Use: 처치하다, 소멸시키다, 제압하다, 쓰러뜨리다, 응징하다.
4. Terminology:
   - Naturally integrate: 시스템 창, 등급, 각성, 쉘터, 몬스터, 돌연변이.
   - Glossary: {glossary}

5. PAGE SELECTION & VISUAL EVIDENCE:
   - Direct Visual Alignment: Select panels showing clear character faces, action, combat, or key plot turning points.
   - Multi-page ranges: Use [<start>, <end>] for action-reaction sequences.
   - DENSE VISUAL PACING & IMAGE ALLOCATION:
     * For narrative sentences exceeding 60 characters (duration > 6s), allocate 2 distinct consecutive pages (e.g. [<page1>, <page2>]) to keep visual rhythm dynamic.
     * For short phrases (< 25 characters), allocate exactly 1 page. Never assign multiple pages to rapid short phrases.
   - Zero filler: Never select blank backgrounds, pure credits, or empty cards.

6. ONE PAGE = ONE PRIMARY BEAT:
   Each segment = ONE primary story event.

7. NARRATION MUST FOLLOW THE PAGE:
   Describe only what the selected page shows. Never fabricate unseen details.

8. GOLDEN CONTENT RATIO:
   85%% Plot/Context + 10%% Natural Humor + 5%% Punchline.
   ZERO CTA: Never open with greetings or channel promotions.

FORMAT REQUIREMENTS:
- Each line must follow: <page_number> - <Korean narration>.#
- Multi-page: [<start>, <end>] - <Korean narration>.#
- Every line MUST end with .#

SCRIPT EXAMPLE:
1 - 붉은 안개와 함께 전 세계가 괴물들의 사냥터로 변해버렸습니다.#
[2, 3] - 생존자들조차 서로를 배신하는 지옥 속에서, 주인공은 홀로 몬스터의 소굴로 몰리게 되는데요.#
5 - 바로 그 순간, 그의 눈앞에 알 수 없는 푸른색 시스템 창이 떠오릅니다.#
[7, 8] - 숨겨진 히든 능력을 각성한 그는 단 한 번의 일격으로 거대 괴수를 완벽히 제압해 버립니다.#
{total_pages} - 하지만 안도의 한숨을 쉬기도 전, 도시 저편에서 차원이 다른 보스 몬스터가 포효하기 시작합니다.#
"""
