from __future__ import annotations

from typing import Dict, Any, List


def generate_us_apocalypse_metadata(
    comic_title: str,
    from_ep: int,
    to_ep: int,
    chapters: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
    
    # Curiosity-gap title templates
    title_options = [
        f"The World Ended, But He Had An Infinite Space Warehouse... [{comic_title} {ep_range} Recap]",
        f"He Prepared An Impenetrable Bunker Before The Apocalypse, Then... [{comic_title}]",
        f"Everyone Laughed When He Hoarded 50,000 Tons Of Supplies, Until... [{comic_title}]",
        f"He Regressed Before The Doomsday Struck And Prepared Everything [{comic_title} {ep_range} Full Recap]",
    ]

    primary_title = title_options[0]

    # Description template with timestamps and fair use
    desc_lines = [
        f"Title: {comic_title} ({ep_range})",
        "",
        "📖 Synopsis & Premise:",
        f"When the global apocalypse strikes, society collapses overnight. While the rest of the world descends into utter chaos and starvation, our protagonist is armed with extraordinary foresight, a fortified survival sanctuary, and an infinite dimensional warehouse.",
        "",
        "⏱️ Chapters & Timestamps:",
    ]

    if chapters:
        for ch in chapters:
            time_str = ch.get("timestamp", "00:00")
            title = ch.get("title", f"Episode {ch.get('episode', 1)}")
            desc_lines.append(f"{time_str} - {title}")
    else:
        desc_lines.append("00:00 - Introduction & The Doomsday Awakening")
        desc_lines.append("05:00 - Fortifying The Bunker")
        desc_lines.append("15:00 - The Catastrophe Strikes")

    desc_lines.extend([
        "",
        "🔔 Don't forget to LIKE and SUBSCRIBE for more epic Apocalypse & Survival Manhwa recaps!",
        "",
        "⚠️ Copyright Disclaimer:",
        "Under Section 107 of the Copyright Act 1976, allowance is made for 'fair use' for purposes such as criticism, comment, news reporting, teaching, scholarship, and research. Fair use is a use permitted by copyright statute that might otherwise be infringing.",
        "",
        "#manhwarecap #apocalypsemanhwa #mangarecap #survivalmanhwa #webtoonrecap"
    ])

    tags = [
        "manhwa recap",
        "apocalypse manhwa",
        "survival manhwa",
        "bunker manhwa",
        "prepper manhwa",
        "regression manhwa",
        "infinite storage manhwa",
        "op mc manhwa",
        "manga recap",
        "comic recap",
        "full story recap",
        comic_title.lower(),
        f"{comic_title.lower()} recap",
    ]

    return {
        "title": primary_title,
        "title_options": title_options,
        "description": "\n".join(desc_lines),
        "tags": tags,
    }
