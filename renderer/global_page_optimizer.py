# -*- coding: utf-8 -*-
"""
Global Page Optimizer: Dynamic Programming / Shortest-Path Optimization for Comic Canvases.

Optimizes page cuts globally across the entire canvas:
- Finds the optimal combination of cut boundaries.
- Balances visual boundary quality, semantic safety, speech bubble rules, and page height.
- Enforces MIN_PAGE_HEIGHT, IDEAL_PAGE_HEIGHT, and MAX_PAGE_HEIGHT without overriding strong visual composition.
- Preserves continuous multi-panel scenes and action sequences.
"""

from typing import List, Tuple, Dict, Any, Optional
import numpy as np

from renderer.visual_boundary_scanner import BoundaryCandidate


class GlobalPageOptimizer:
    """
    Global Dynamic Programming optimizer for comic canvas page segmentation.
    """

    def __init__(
        self,
        min_page_height: int = 400,
        ideal_page_height: int = 1200,
        max_page_height: int = 3500,
        height_weight: float = 1.2,
        boundary_weight: float = 3.0,
        hard_cut_bonus: float = 5.0
    ):
        self.min_page_height = min_page_height
        self.ideal_page_height = ideal_page_height
        self.max_page_height = max_page_height
        self.height_weight = height_weight
        self.boundary_weight = boundary_weight
        self.hard_cut_bonus = hard_cut_bonus

    def compute_page_cost(
        self,
        y_start: int,
        y_end: int,
        candidate_end: Optional[BoundaryCandidate],
        total_canvas_h: int
    ) -> float:
        """
        Computes the cost of creating a page spanning [y_start, y_end].
        Lower cost is better (minimization problem).
        """
        h = y_end - y_start
        if h <= 0:
            return float("inf")

        # 1. Safety Gate: candidates marked as unsafe (cutting through character/face/action/internal bubble)
        # or candidates belonging to the SAME visual composition are strictly forbidden
        if candidate_end is not None and y_end < total_canvas_h:
            if not candidate_end.is_safe:
                return float("inf")
            if candidate_end.details.get("same_visual_composition", False) or candidate_end.score <= 0.05:
                return float("inf")

        # 2. Height Penalty (Soft constraint for visual composition integrity)
        if h < self.min_page_height:
            # Heavily penalize any micro-page below min_page_height to eliminate over-segmentation,
            # but allow explicit hard cut boundaries (e.g. speech bubble edge with hard=True)
            deficit = (self.min_page_height - h) / float(self.min_page_height)
            if candidate_end is not None and candidate_end.hard:
                height_penalty = 1.0 + (deficit ** 2) * 4.0
            else:
                height_penalty = 25.0 + (deficit ** 2) * 50.0
        elif h > self.max_page_height:
            # Quadratic runaway penalty for overly tall pages exceeding max limit
            excess = (h - self.max_page_height) / 1000.0
            height_penalty = 15.0 + (excess ** 2) * 25.0
        else:
            # Deviation penalty from ideal_page_height
            dev = abs(h - self.ideal_page_height) / float(self.ideal_page_height)
            height_penalty = (dev ** 2) * (self.height_weight * 1.5)

        # 3. Boundary Quality Reward (Negative Cost)
        # Bounded so rewards don't encourage micro-splitting
        boundary_reward = 0.0
        if candidate_end is not None and y_end < total_canvas_h:
            boundary_reward = min(4.0, candidate_end.score * min(3.5, self.boundary_weight))
            if candidate_end.hard:
                boundary_reward += self.hard_cut_bonus

        base_page_cost = 0.6
        total_cost = base_page_cost + height_penalty - boundary_reward
        return total_cost

    def optimize_pages(
        self,
        total_height: int,
        candidates: List[BoundaryCandidate]
    ) -> Tuple[List[int], List[Tuple[int, int]]]:
        """
        Executes Dynamic Programming global optimization to select the best combination of cuts.
        Returns:
            (selected_cut_y_coords, page_intervals_list)
        """
        if total_height <= 0:
            return [], []

        # If canvas is smaller than min_page_height, treat as a single page
        if total_height <= self.min_page_height:
            return [], [(0, total_height)]

        # Prepare candidate points: 0, c_1, c_2, ..., total_height
        safe_cands = [c for c in candidates if 0 < c.y < total_height]
        cand_dict: Dict[int, BoundaryCandidate] = {c.y: c for c in safe_cands}

        cut_points = [0] + sorted(list(set([c.y for c in safe_cands])))
        if cut_points[-1] != total_height:
            cut_points.append(total_height)

        n = len(cut_points)
        if n == 2:
            # Only start and end
            return [], [(0, total_height)]

        # DP State:
        # dp[i] = minimum cost to partition [0, cut_points[i]]
        # parent[i] = index j < i of the previous cut
        dp = np.full(n, float("inf"), dtype=np.float64)
        parent = np.full(n, -1, dtype=np.int32)
        dp[0] = 0.0

        for i in range(1, n):
            yi = cut_points[i]
            cand_i = cand_dict.get(yi)

            # Pruning: only evaluate reasonable previous cuts j
            for j in range(i - 1, -1, -1):
                yj = cut_points[j]
                h = yi - yj

                # If distance exceeds max_page_height + buffer, stop looking further back
                if h > (self.max_page_height + 2000):
                    break

                if dp[j] == float("inf"):
                    continue

                cost = self.compute_page_cost(yj, yi, cand_i, total_height)
                if cost == float("inf"):
                    continue

                total_cost = dp[j] + cost
                if total_cost < dp[i]:
                    dp[i] = total_cost
                    parent[i] = j

        # If DP reached end successfully, backtrack optimal cuts
        if parent[n - 1] != -1:
            chosen_indices = []
            curr = n - 1
            while curr > 0:
                chosen_indices.append(curr)
                curr = parent[curr]
            chosen_indices.reverse()

            selected_cuts = [cut_points[idx] for idx in chosen_indices[:-1]]
            bounds = [0] + selected_cuts + [total_height]
            pages = [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)]
            return selected_cuts, pages

        # Fallback if no valid path was found:
        # Never cut blindly at arbitrary coordinates; always pick safe candidates
        fallback_cuts: List[int] = []
        curr_y = 0
        while curr_y + self.ideal_page_height < total_height:
            target_y = curr_y + self.ideal_page_height
            # 1. Search for any safe candidate within [curr_y + min_page_height, curr_y + max_page_height]
            window_cands = [
                c for c in safe_cands
                if curr_y + self.min_page_height <= c.y <= min(total_height - 100, curr_y + self.max_page_height)
                and c.is_safe and not c.details.get("same_visual_composition", False)
            ]
            if window_cands:
                def _cand_rank(c):
                    return abs(c.y - target_y) / float(self.ideal_page_height) - c.score * 2.0
                best_cand = min(window_cands, key=_cand_rank)
                cut_y = best_cand.y
            else:
                # 2. Search any safe candidate within +/- 450px
                nearby = [c for c in safe_cands if abs(c.y - target_y) <= 450 and c.is_safe]
                if nearby:
                    best_cand = max(nearby, key=lambda c: c.score)
                    cut_y = best_cand.y
                else:
                    further = [c for c in safe_cands if c.y > curr_y + self.min_page_height and c.is_safe]
                    if further:
                        best_cand = min(further, key=lambda c: abs(c.y - target_y))
                        cut_y = best_cand.y
                    else:
                        break
            fallback_cuts.append(cut_y)
            curr_y = cut_y

        bounds = [0] + sorted(list(set(fallback_cuts))) + [total_height]
        pages = [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)]
        return sorted(list(set(fallback_cuts))), pages
