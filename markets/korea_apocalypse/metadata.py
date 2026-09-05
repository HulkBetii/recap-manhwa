from __future__ import annotations

from typing import Dict, List


def generate_korea_apocalypse_metadata(comic_title: str, from_ep: int, to_ep: int) -> Dict[str, any]:
    # Hook titles matching top YouTube Korea Manhwa Binge-watch format
    ep_range = f"{from_ep}화~{to_ep}화" if from_ep != to_ep else f"{from_ep}화"
    
    suggested_titles = [
        f"[웹툰 몰아보기] 괴물들이 세상을 지배했다... 인류 멸망 직전 각성한 생존자 ({ep_range} 몰아보기)",
        f"[아포칼립스 웹툰] 바닥부터 시작해 세계 최강이 된 생존자의 처절한 사투 ({ep_range} 완결 몰아보기)",
        f"[웹툰 추천] 멸망한 세계에서 나 혼자만 치트 시스템을 각성했다 ({comic_title} {ep_range})",
    ]

    description = f"""🔥 [웹툰 몰아보기] {comic_title} ({ep_range}) 전편 몰아보기

세상이 멸망하고 괴물들이 쏟아져 나오는 아포칼립스 속에서,
살아남기 위해 모든 것을 걸고 싸우는 생존자의 처절하고 통쾌한 이야기!

📌 재생목록에서 더 많은 아포칼립스 웹툰 몰아보기를 감상하세요!
👍 구독과 좋아요, 알림 설정은 다음 영상 제작에 큰 힘이 됩니다!

#웹툰몰아보기 #아포칼립스웹툰 #생존웹툰 #웹툰추천 #만화몰아보기 #사이다웹툰
"""

    tags: List[str] = [
        "웹툰몰아보기",
        "아포칼립스웹툰",
        "생존웹툰",
        "웹툰추천",
        "만화몰아보기",
        "사이다웹툰",
        "웹툰리뷰",
        "인기웹툰",
        comic_title,
        f"{comic_title} 몰아보기",
    ]

    return {
        "title": suggested_titles[0],
        "suggested_titles": suggested_titles,
        "description": description.strip(),
        "tags": tags,
    }
