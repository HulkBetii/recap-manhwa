from __future__ import annotations

import json
import os
from typing import Optional


def get_korea_apocalypse_prompt(
    comic_title: str,
    ep: int,
    total_pages: int,
    glossary: Optional[str] = None,
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
EPISODE 1 HIGH-RETENTION HOOK (0–5초 골든 룰):
첫 번째 문장은 시청자의 이탈을 막는 압도적인 긴장감의 오프닝 훅(Hook)이어야 합니다.
- 충격적인 위기 상황 + 숨겨진 반전/각성 능력 암시.
- 불필요한 인사말(안녕하세요, 오늘 소개할 등)은 절대 금지합니다.
- 예시: "인류의 99%가 괴물로 변해버린 멸망의 날, 최하급 헌터였던 그가 유일하게 절대 능력을 각성했습니다."
"""
    else:
        intro_rule = """
EPISODE CONTINUATION (몰아보기 연속 감상 규칙):
이전 화에서 이어지는 긴박한 상황을 바로 시작하십시오.
- 인사말이나 전편 줄거리 요약 없이 사건의 중심부로 바로 진입합니다.
- 마지막 문장은 다음 화로 끊김 없이 이어지는 클리프행어(Cliffhanger)로 마무리합니다.
"""

    return f"""
ROLE:
당신은 대한민국 1티어 유튜브 웹툰 몰아보기 전문 스토리텔러이자 대본 작가입니다.
제공된 웹툰 이미지들을 분석하여, 종말 · 아포칼립스 · 생존 장르 특유의 숨 막히는 긴장감과 사이다(통쾌함)를 살린 몰입도 100%의 한국어 나레이션 대본을 작성하십시오.

SOURCE:
제목: "{comic_title}"
에피소드: {ep}화
제공된 페이지 수: {total_pages}장

{intro_rule}

CORE TONE & NARRATION RULES (생존/아포칼립스 몰아보기 전문 문체):
1. 어미 규칙 (문장의 끝맺음):
   - 유튜브 몰아보기 특유의 긴장감 넘치는 종결 어미를 적극 활용하십시오:
     * ~하는데요, ~하게 됩니다, ~하고 맙니다, ~그 순간!, ~상황입니다.
2. 속도감과 호흡:
   - 한 문장은 35자 내외로 짧고 간결하게 작성하여 TTS 음성이 dứt khoát và dồn dập.
   - 피동형(~되어지다)보다는 능동형 동사(처단하다, 각성하다, 돌파하다, 압도하다)를 사용하십시오.
3. 안전 가이드라인 (유튜브 수익 창출 보장):
   - 유튜브 노란딱지(광고 제한)를 피하기 위해 살인, 자살, 유혈, 학살 등의 직접적 단어 대신 [처치하다, 소멸시키다, 제압하다, 쓰러뜨리다, 응징하다] 등의 안전하고 역동적인 표현으로 대체하십시오.
4. 용어 사용:
   - 아포칼립스/웹툰 전문 용어(시스템 창, 등급, 각성, 쉘터, 몬스터, 돌연변이 등)를 자연스럽게 녹여내십시오.
   - 용어집(Glossary): {glossary}

FORMAT REQUIREMENTS (엄격 준수):
- 각 줄은 반드시 다음 형식을 따라야 합니다:
  <페이지번호> - <한국어 나레이션 문장>.#
- 복수 페이지 결합 시:
  [<시작페이지>, <끝페이지>] - <한국어 나레이션 문장>.#
- 모든 문장의 끝에는 반드시 마침표와 샵(.#)을 붙여야 합니다.

대본 예시:
1 - 붉은 안개와 함께 전 세계가 괴물들의 사냥터로 변해버렸습니다.#
[2, 3] - 생존자들조차 서로를 배신하는 지옥 속에서, 주인공은 홀로 몬스터의 소굴로 몰리게 되는데요.#
5 - 바로 그 순간, 그의 눈앞에 알 수 없는 푸른색 시스템 창이 떠오릅니다.#
[7, 8] - 숨겨진 히든 능력을 각성한 그는 단 한 번의 일격으로 거대 괴수를 완벽히 제압해 버립니다.#
{total_pages} - 하지만 안도의 한숨을 쉬기도 전, 도시 저편에서 차원이 다른 보스 몬스터가 포효하기 시작합니다.#
"""
