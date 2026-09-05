from __future__ import annotations

from typing import Dict, List


def generate_japan_isekai_metadata(comic_title: str, from_ep: int, to_ep: int) -> Dict[str, any]:
    ep_range = f"{from_ep}話~{to_ep}話" if from_ep != to_ep else f"{from_ep}話"

    suggested_titles = [
        f"【異世界漫画】無能と追放された元貴族、現代知識と規格外スキルで最果ての荒野を最強帝国へ開拓してしまう ({ep_range} 一気見)",
        f"【異世界漫画】役立たずと蔑まれ辺境へ左遷された領主、前世チートで世界一の楽園を建国し元家族を完全論破する ({comic_title} {ep_range})",
        f"【漫画総集編】追放された没落貴族が規格外の生産魔法で大逆転！隣国が平伏する巨大都市へ成り上がる【作業用/睡眠用】",
    ]

    description = f"""🔥【異世界漫画・総集編】{comic_title} ({ep_range}) 一気見まとめ

「無能」と見下され、最果ての荒野へと追放された元貴族の主人公。
しかし彼は、誰もが想像し得ない現代知識と規格外のチート能力を隠し持っていた――！
不毛の大地を最強の巨大帝国へと開拓し、見下していた者たちを完全に圧倒する痛快成り上がり劇！

📌 チャンネル登録＆高評価をいただけると、次回の動画制作の大きな励みになります！
🔔 通知ベルをONにして最新の漫画総集編をお見逃しなく！

#異世界漫画 #漫画総集編 #一気見 #領地経営 #成り上がり #追放 #チート #ざまぁ #マンガ動画
"""

    tags: List[str] = [
        "異世界漫画",
        "漫画総集編",
        "一気見",
        "マンガ動画",
        "領地経営",
        "成り上がり",
        "追放",
        "チート",
        "ざまぁ",
        "現代知識",
        "漫画解説",
        comic_title,
        f"{comic_title} 一気見",
    ]

    return {
        "title": suggested_titles[0],
        "suggested_titles": suggested_titles,
        "description": description.strip(),
        "tags": tags,
    }
