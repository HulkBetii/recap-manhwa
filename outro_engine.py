"""
Outro — a 20-25s spoken closing that tells viewers where the story stands.

Why: videos used to stop on the last narrated line of the last rendered episode. Most recapped comics
are still running, so viewers could not tell whether the story continues, and there was no natural slot
for the end screen. The outro type follows the comic's real release status (series_status.py):

- CONTINUES: the comic is still being released.
- HIATUS: the comic is on a break and the video reaches its latest episode.
- FINALE: the comic is completed and the video reaches its last episode.
- NEUTRAL: status unknown, or the video stops before the last released episode of a completed or
  paused comic. It closes the video without claiming the story continues or ends.

The LLM drafts, code validates (length, invented names/numbers, predictions, cliffhanger copy, CTA count,
type-consistent wording); one retry with feedback, then a fixed template with no story facts. Never raises.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from premise_pitch import GREETING_RE, invented_names
from series_bible import normalize_text
from series_status import ReleaseStatus
from title_engine import NUMBER_RE, WORD_RE, load_narration_by_episode

logger = logging.getLogger(__name__)


class OutroType(str, Enum):
    CONTINUES = "continues"
    HIATUS = "hiatus"
    FINALE = "finale"
    NEUTRAL = "neutral"


MAX_ATTEMPTS = 2
# ~150 spoken words/min (TTS runs at +6%) -> about 20-26s in English; Vietnamese counts syllables.
WORD_BOUNDS = {"en": (50, 70), "vi": (60, 90)}
LAST_LINES_COUNT = 3              # narration lines treated as the cliffhanger
CLIFFHANGER_NGRAM = 8             # this many consecutive words shared with the cliffhanger = a copy
MAX_CTAS = 1
LANGUAGE_NAMES = {"en": "English", "vi": "Vietnamese"}

CTA_RE = re.compile(
    r"\b(subscrib\w*|playlist|comment below|leave a comment|like button|hit the like|leave a like|"
    r"next part|đăng ký|danh sách phát|phần tiếp theo)\b",
    re.IGNORECASE,
)
PLAYLIST_RE = re.compile(r"\b(playlist|danh sách phát)\b", re.IGNORECASE)
NEXT_PART_RE = re.compile(r"\b(next part|part two|part 2|phần tiếp theo|phần 2)\b", re.IGNORECASE)
# Claims that the story is over; only a FINALE may make them.
ENDING_CLAIM_RE = re.compile(
    r"\b(the end|finale|final chapter|last chapter|completed?|full story|complete story|ending|"
    r"hết truyện|kết thúc truyện|chương cuối|hoàn thành|trọn bộ|đại kết cục)\b",
    re.IGNORECASE,
)
REQUIRED_SIGNAL = {
    OutroType.FINALE: re.compile(r"\b(end|ending|final|finale|last|kết|cuối)\b", re.IGNORECASE),
    OutroType.CONTINUES: re.compile(
        r"\b(continu\w*|still being released|not over|far from over|ongoing|new chapters?|còn tiếp|"
        r"chưa kết thúc|vẫn đang ra|chương mới)\b",
        re.IGNORECASE,
    ),
    OutroType.HIATUS: re.compile(r"\b(break|hiatus|paused?|tạm nghỉ|tạm dừng)\b", re.IGNORECASE),
}
# Closings address the viewer ("Thank you...", "You can find..."); these openers are never names.
OUTRO_COMMON_OPENERS = frozenset({
    "thank", "thanks", "you", "we", "our", "your", "see", "stay", "until",
    # Call-to-action verbs open the last sentence ("Subscribe for more..."); a Veteran dry run lost a draft to it.
    "subscribe", "make", "check", "watch", "join", "hit", "catch", "follow", "don't",
})
PREDICTION_SUBJECTS = r"(he|she|they|anh ấy|cậu ấy|hắn|cô ấy|họ)"
PREDICTION_VERBS = r"(will|'ll|is going to|are going to|is about to|are about to|sẽ|sắp)"

TEMPLATE_OUTROS: Dict[str, Dict[str, Dict[str, str]]] = {
    "en": {
        OutroType.CONTINUES.value: {
            "body": (
                "And that is where the story stands for now. The comic is still being released, so his "
                "journey is far from over, and the hardest battles may still be ahead of him. Thanks for "
                "staying with this recap through every chapter."
            ),
        },
        OutroType.HIATUS.value: {
            "body": (
                "And that is where the story stands for now. The comic is currently on a break, so this is "
                "as far as his journey goes until the author returns. Thanks for staying with this recap "
                "through every chapter, and we hope to see the story return soon."
            ),
        },
        OutroType.FINALE.value: {
            "body": (
                "And that is the end of the story. From the very first chapter to the very last page, every "
                "choice he made led him to this ending. Thank you for staying with this recap all the way to "
                "the final chapter of his journey."
            ),
        },
        OutroType.NEUTRAL.value: {
            "body": (
                "And that is where we stop for this recap. He has come a long way since the first chapter, "
                "and the world around him is still full of danger. Thanks for staying with this recap and "
                "following his journey this far."
            ),
        },
    },
    "vi": {
        OutroType.CONTINUES.value: {
            "body": (
                "Và câu chuyện tạm dừng tại đây. Bộ truyện vẫn đang ra chương mới, nên hành trình của anh ấy "
                "còn tiếp và những thử thách khó khăn nhất có lẽ vẫn còn ở phía trước. Cảm ơn các bạn đã theo "
                "dõi bản tóm tắt này qua từng chương."
            ),
        },
        OutroType.HIATUS.value: {
            "body": (
                "Và câu chuyện tạm dừng tại đây. Bộ truyện hiện đang tạm nghỉ, nên hành trình của anh ấy chỉ "
                "đi đến đây cho đến khi tác giả quay lại. Cảm ơn các bạn đã theo dõi bản tóm tắt này qua từng "
                "chương, mong bộ truyện sớm trở lại."
            ),
        },
        OutroType.FINALE.value: {
            "body": (
                "Và đó là cái kết của câu chuyện. Từ chương đầu tiên đến trang cuối cùng, mọi lựa chọn của anh "
                "ấy đều dẫn đến kết cục này. Cảm ơn các bạn đã đồng hành cùng bản tóm tắt này đến tận chương "
                "kết của hành trình."
            ),
        },
        OutroType.NEUTRAL.value: {
            "body": (
                "Và bản tóm tắt dừng lại tại đây. Anh ấy đã đi một chặng đường dài kể từ chương đầu tiên, và "
                "thế giới xung quanh vẫn đầy rẫy hiểm nguy. Cảm ơn các bạn đã theo dõi hành trình của anh ấy "
                "đến lúc này."
            ),
        },
    },
}
# One call to action at most, chosen from the real navigation links.
TEMPLATE_CTAS = {
    "en": {
        "next_part": "The next part of the story is linked right below this video.",
        "playlist": "You can find the whole story so far in the playlist linked below.",
        "default": "If you enjoyed it, subscribe so you do not miss the next survival recap.",
    },
    "vi": {
        "next_part": "Phần tiếp theo của câu chuyện có ở đường dẫn ngay bên dưới video.",
        "playlist": "Toàn bộ câu chuyện đến lúc này có trong danh sách phát bên dưới.",
        "default": "Nếu thấy hay, hãy đăng ký kênh để không bỏ lỡ bản tóm tắt sinh tồn tiếp theo.",
    },
}


class OutroFacts(BaseModel):
    """Grounded inputs for drafting and validating the outro."""
    protagonist: str = ""
    known_names: List[str] = Field(default_factory=list)  # name_key form (Bible names + aliases)
    episodes_covered: int = 0
    last_summary: str = ""
    last_lines: List[str] = Field(default_factory=list)
    corpus_text: str = ""
    has_playlist: bool = False
    has_next_part: bool = False


class OutroCheck(BaseModel):
    text: str
    passed: bool
    reasons: List[str] = Field(default_factory=list)
    word_count: int = 0


class OutroResult(BaseModel):
    type: OutroType
    text: Optional[str] = None
    source: str = ""  # "llm" | "template" | "reused" | "" (no outro)
    attempts: List[OutroCheck] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text)


def _lang(language: str) -> str:
    return (language or "en").lower()[:2]


def classify_outro(status: Optional[ReleaseStatus], to_ep: int) -> OutroType:
    """Deterministic: only claims an ending or a break when the video reaches the latest episode."""
    if status is None:
        return OutroType.NEUTRAL
    reaches_latest = status.latest_episode is not None and to_ep >= status.latest_episode
    if status.state == "ongoing":
        return OutroType.CONTINUES
    if status.state == "completed" and reaches_latest:
        return OutroType.FINALE
    if status.state == "hiatus" and (reaches_latest or status.latest_episode is None):
        return OutroType.HIATUS
    return OutroType.NEUTRAL


def build_outro_facts(
    download_dir: Optional[str],
    from_ep: int,
    to_ep: int,
    story_memory: Optional[Dict[str, Any]] = None,
    bible: Any = None,
    payload: Optional[Dict[str, Any]] = None,
) -> OutroFacts:
    """`bible` is a series_bible.SeriesBible or None."""
    by_episode = load_narration_by_episode(download_dir, from_ep, to_ep)
    last_ep = max(by_episode) if by_episode else None
    last_summary = ""
    episodes = (story_memory or {}).get("episodes") if isinstance(story_memory, dict) else None
    if isinstance(episodes, dict) and last_ep is not None:
        info = episodes.get(str(last_ep)) or episodes.get(last_ep) or {}
        last_summary = str(info.get("summary", "") or "") if isinstance(info, dict) else ""
    corpus = [seg for ep in sorted(by_episode) for seg in by_episode[ep]]
    payload = payload or {}
    return OutroFacts(
        protagonist=getattr(bible, "protagonist_name", "") or "",
        known_names=sorted(bible.known_names()) if bible is not None else [],
        episodes_covered=len(by_episode),
        last_summary=last_summary,
        last_lines=by_episode[last_ep][-LAST_LINES_COUNT:] if last_ep is not None else [],
        corpus_text=" ".join(corpus + [last_summary]),
        has_playlist=bool(payload.get("playlist_url")),
        has_next_part=bool(payload.get("next_part_url")),
    )


def _type_instruction(outro_type: OutroType, lang: str) -> str:
    return {
        OutroType.CONTINUES: (
            "The comic is STILL BEING RELEASED. Say clearly that the story continues (\"the story continues\", "
            "\"his journey is far from over\"). Do not guess what happens next. Never call it the end."
        ),
        OutroType.HIATUS: (
            "The comic is ON A BREAK (hiatus). Say the comic is currently on a break and this is as far as the "
            "story goes for now. Never call it the end."
        ),
        OutroType.FINALE: (
            "The comic is COMPLETED and this video covered its final chapter. Close the story: say this is the "
            "end of his journey and reflect in one sentence on how far he came."
        ),
        OutroType.NEUTRAL: (
            "Close this video only. Do NOT say whether the comic continues or has ended, and never call it the "
            "end, the finale or the full story."
        ),
    }[outro_type]


def _cta_instruction(facts: OutroFacts) -> str:
    if facts.has_next_part:
        return "End with ONE call to action: the next part of the story is linked below."
    if facts.has_playlist:
        return "End with ONE call to action: the whole story so far is in the playlist linked below."
    return "End with ONE call to action: subscribe for more survival recaps. Never mention a playlist or a next part."


def build_outro_prompt(
    outro_type: OutroType,
    facts: OutroFacts,
    language: str = "en",
    feedback: Optional[List[str]] = None,
) -> str:
    lang = _lang(language)
    lo, hi = WORD_BOUNDS.get(lang, WORD_BOUNDS["en"])
    retry = ""
    if feedback:
        retry = "\nYOUR PREVIOUS DRAFT WAS REJECTED FOR: " + "; ".join(feedback) + ". Fix every point.\n"
    last_lines = "\n".join(f"- {line}" for line in facts.last_lines) or "- (none)"
    return f"""You write the spoken closing lines of a long manhwa recap video, read right after its last scene.

STORY FACTS (the ONLY facts you may use):
- Protagonist: {facts.protagonist or "(unnamed; call him 'he')"}
- Episodes covered in this video: {facts.episodes_covered}
- What happened in the last episode: {facts.last_summary or "(not available)"}
- The video's last narrated lines (do NOT repeat them):
{last_lines}
{retry}
Write ONE closing in {LANGUAGE_NAMES.get(lang, language)}, {lo}-{hi} words, to be read aloud.

STATUS: {_type_instruction(outro_type, lang)}

STRUCTURE:
1. One sentence that lands the moment where the video stops, in fresh words.
2. One or two sentences on where the story stands (follow STATUS exactly).
3. {_cta_instruction(facts)}

RULES:
- Use no names except "{facts.protagonist or "he"}"; describe everyone else by role. No comic title.
- Use no numbers.
- Never predict events ("he will...", "he is about to...").
- No greetings, no questions to the viewer, no lists, no Markdown, no quotation marks.

Return ONLY the closing text.
"""


def _words(text: str, lang: str) -> List[str]:
    return WORD_RE.findall(text) if lang == "en" else text.split()


def _copies_cliffhanger(text: str, last_lines: List[str], lang: str) -> bool:
    def ngrams(s: str) -> set:
        w = [x.lower() for x in _words(s, lang)]
        return {tuple(w[i:i + CLIFFHANGER_NGRAM]) for i in range(len(w) - CLIFFHANGER_NGRAM + 1)}
    source = set().union(*(ngrams(line) for line in last_lines)) if last_lines else set()
    return bool(ngrams(text) & source)


def validate_outro(text: str, outro_type: OutroType, facts: OutroFacts, language: str = "en") -> OutroCheck:
    lang = _lang(language)
    text = re.sub(r"\s+", " ", (text or "").strip().strip("\"'"))
    words = _words(text, lang)
    lo, hi = WORD_BOUNDS.get(lang, WORD_BOUNDS["en"])
    reasons: List[str] = []

    if not lo <= len(words) <= hi:
        reasons.append(f"word_count {len(words)} outside {lo}-{hi}")
    if GREETING_RE.search(text):
        reasons.append("greeting or channel talk")
    if re.search(r"^\s*[-*#\d]+[.)]?\s", text, re.MULTILINE):
        reasons.append("list or Markdown formatting")

    corpus_numbers = {n.replace(",", "") for n in NUMBER_RE.findall(facts.corpus_text)}
    invented_numbers = sorted({n.replace(",", "") for n in NUMBER_RE.findall(text)} - corpus_numbers)
    if invented_numbers:
        reasons.append(f"numbers not in the story: {', '.join(invented_numbers)}")

    names = invented_names(text, facts.corpus_text, set(facts.known_names), OUTRO_COMMON_OPENERS)
    if names:
        reasons.append(f"names not in the story: {', '.join(names)}")

    subjects = PREDICTION_SUBJECTS
    if facts.protagonist:
        subjects = rf"({PREDICTION_SUBJECTS[1:-1]}|{re.escape(facts.protagonist)})"
    if re.search(rf"\b{subjects}\s*{PREDICTION_VERBS}\b", text, re.IGNORECASE):
        reasons.append("predicts future events (he will / is about to)")

    if _copies_cliffhanger(text, facts.last_lines, lang):
        reasons.append(f"repeats the last narrated lines ({CLIFFHANGER_NGRAM}+ words)")

    cta_count = len(CTA_RE.findall(text))
    if cta_count > MAX_CTAS:
        reasons.append(f"{cta_count} calls to action (max {MAX_CTAS})")
    if PLAYLIST_RE.search(text) and not facts.has_playlist:
        reasons.append("mentions a playlist but there is none")
    if NEXT_PART_RE.search(text) and not facts.has_next_part:
        reasons.append("mentions a next part but there is none")

    if outro_type != OutroType.FINALE and ENDING_CLAIM_RE.search(text):
        reasons.append(f"claims the story ended, but the outro type is {outro_type.value}")
    required = REQUIRED_SIGNAL.get(outro_type)
    if required is not None and not required.search(text):
        reasons.append(f"does not say the story status ({outro_type.value})")

    return OutroCheck(text=text, passed=not reasons, reasons=reasons, word_count=len(words))


def template_outro(outro_type: OutroType, facts: OutroFacts, language: str = "en") -> Optional[str]:
    """Fixed closing with no story facts; None for languages without a template."""
    lang = _lang(language)
    bodies = TEMPLATE_OUTROS.get(lang)
    if not bodies:
        return None
    ctas = TEMPLATE_CTAS[lang]
    cta = ctas["next_part"] if facts.has_next_part else ctas["playlist"] if facts.has_playlist else ctas["default"]
    return f"{bodies[outro_type.value]['body']} {cta}"


async def generate_outro(
    outro_type: OutroType,
    facts: OutroFacts,
    llm_text_call: Optional[Callable[[str], Awaitable[Optional[str]]]],
    bible: Any = None,
    language: str = "en",
    previous_text: Optional[str] = None,
) -> OutroResult:
    """Drafts and validates; retries once with the rejection reasons, then falls back to the template.

    `previous_text` (an earlier run's outro of the same type) is re-validated first and kept when it
    still passes, so re-running Stage 11 does not change an approved video.
    """
    result = OutroResult(type=outro_type)
    if previous_text:
        check = validate_outro(previous_text, outro_type, facts, language)
        result.attempts.append(check)
        if check.passed:
            result.text, result.source = check.text, "reused"
            return result
    feedback: Optional[List[str]] = None
    for _ in range(MAX_ATTEMPTS if llm_text_call else 0):
        try:
            raw = await llm_text_call(build_outro_prompt(outro_type, facts, language, feedback))
        except Exception as err:
            logger.warning("Outro LLM call failed: %s", err)
            result.attempts.append(OutroCheck(text="", passed=False, reasons=[f"llm_error: {err}"]))
            break
        draft, _ = normalize_text(raw or "", bible)
        check = validate_outro(draft, outro_type, facts, language)
        result.attempts.append(check)
        if check.passed:
            result.text, result.source = check.text, "llm"
            return result
        feedback = check.reasons
    fallback = template_outro(outro_type, facts, language)
    if fallback:
        result.text, result.source = fallback, "template"
    return result
