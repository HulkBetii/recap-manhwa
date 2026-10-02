"""
Episode-to-episode narration continuity for Stage 5.

Episodes are narrated in contiguous chunks (one per worker), each in order, so every episode except a
chunk's first one is written knowing how the previous episode ended (StoryMemory).
"""

from __future__ import annotations

from typing import List, Sequence


def partition_contiguous(episodes: Sequence[int], workers: int) -> List[List[int]]:
    """Splits `episodes` into at most `workers` contiguous, non-empty chunks of near-equal size."""
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    episodes = list(episodes)
    n = min(workers, len(episodes))
    if n == 0:
        return []
    size, extra = divmod(len(episodes), n)
    chunks, start = [], 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        chunks.append(episodes[start:end])
        start = end
    return chunks
