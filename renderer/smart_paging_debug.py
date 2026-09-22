# -*- coding: utf-8 -*-
"""
Smart Paging Debugger: 5-Color Visual Overlay and Decision Logger.

Color Specification:
- GREEN: Final selected page boundaries
- YELLOW: Candidate boundaries (unselected valid candidates)
- RED: Rejected / unsafe candidates (e.g. character/face overlap, internal bubble)
- BLUE: Character / object safety zones
- PURPLE: Speech bubble zones (labeled EDGE_TOP, EDGE_BOTTOM, INTERNAL)

Also generates detailed decision logs for each candidate boundary.
"""

import os
import json
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
import cv2

from renderer.visual_boundary_scanner import BoundaryCandidate


class SmartPagingDebugger:
    """
    Renders diagnostic 5-color overlays and structured decision logs.
    """

    @staticmethod
    def generate_decision_log(
        candidates: List[BoundaryCandidate],
        selected_cuts: List[int]
    ) -> Dict[str, Any]:
        """
        Generates structured decision log and human-readable text for all candidates.
        """
        selected_set = set(selected_cuts)
        entries = []
        text_lines = []

        for c in sorted(candidates, key=lambda x: x.y):
            is_selected = c.y in selected_set
            char_overlap = not c.is_safe and "character" in c.rejection_reason
            speech_edge = (c.candidate_type == "speech_bubble_edge")

            if is_selected:
                decision = "SELECTED"
                reason = "optimal_global_page_boundary"
            elif not c.is_safe:
                decision = "REJECTED"
                reason = c.rejection_reason or "unsafe_boundary"
            elif c.score < 0.20:
                decision = "REJECTED"
                reason = "low_boundary_score"
            else:
                decision = "NOT_SELECTED"
                reason = "suboptimal_in_global_optimization"

            entry = {
                "y": int(c.y),
                "type": c.candidate_type,
                "score": round(float(c.score), 4),
                "character_overlap": bool(char_overlap),
                "speech_edge": bool(speech_edge),
                "continuity": round(float(c.visual_continuity), 4),
                "decision": decision,
                "reason": reason,
                "hard": bool(c.hard)
            }
            entries.append(entry)

            text_lines.append(
                f"Y={c.y}\n"
                f"type={c.candidate_type}\n"
                f"score={round(float(c.score), 2)}\n"
                f"character_overlap={str(char_overlap).lower()}\n"
                f"speech_edge={str(speech_edge).lower()}\n"
                f"continuity={round(float(c.visual_continuity), 2)}\n"
                f"decision={decision}\n"
                f"reason={reason}\n"
            )

        return {
            "total_candidates": len(candidates),
            "selected_count": len(selected_cuts),
            "rejected_count": sum(1 for e in entries if e["decision"] == "REJECTED"),
            "entries": entries,
            "log_text": "\n".join(text_lines)
        }

    @staticmethod
    def generate_debug_overlay(
        canvas_bgr: np.ndarray,
        candidates: List[BoundaryCandidate],
        selected_cuts: List[int],
        character_boxes: Optional[List[Tuple[int, int, int, int]]] = None,
        speech_bubbles: Optional[List[Dict[str, Any]]] = None,
        max_preview_width: int = 800
    ) -> np.ndarray:
        """
        Creates a color-coded visual overlay on the comic canvas:
        - GREEN: Final selected cuts
        - YELLOW: Unselected valid candidates
        - RED: Rejected / unsafe candidates
        - BLUE: Character / object safety zones
        - PURPLE: Speech bubble zones
        """
        total_h, total_w = canvas_bgr.shape[:2]
        if total_h <= 0 or total_w <= 0:
            return np.zeros((100, 100, 3), dtype=np.uint8)

        scale = min(1.0, float(max_preview_width) / float(total_w))
        disp_w = int(round(total_w * scale))
        disp_h = int(round(total_h * scale))

        preview = cv2.resize(canvas_bgr, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
        overlay = preview.copy()

        # 1. BLUE: Character / object safety zones
        if character_boxes:
            for cx1, cy1, cx2, cy2 in character_boxes:
                sx1 = int(round(cx1 * scale))
                sy1 = int(round(cy1 * scale))
                sx2 = int(round(cx2 * scale))
                sy2 = int(round(cy2 * scale))
                # Semi-transparent blue fill
                cv2.rectangle(overlay, (sx1, sy1), (sx2, sy2), (255, 120, 0), -1)
                cv2.rectangle(preview, (sx1, sy1), (sx2, sy2), (255, 80, 0), 2)
                cv2.putText(preview, "CHAR_SAFETY", (sx1 + 4, sy1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 80, 0), 1)

        # 2. PURPLE: Speech bubble zones
        if speech_bubbles:
            for sb in speech_bubbles:
                bbox = sb.get("bbox", (0, 0, 0, 0))
                role = sb.get("role", "INTERNAL")
                bx1, by1, bx2, by2 = bbox
                sx1 = int(round(bx1 * scale))
                sy1 = int(round(by1 * scale))
                sx2 = int(round(bx2 * scale))
                sy2 = int(round(by2 * scale))
                # Purple color: BGR (200, 0, 200)
                cv2.rectangle(overlay, (sx1, sy1), (sx2, sy2), (200, 0, 200), -1)
                cv2.rectangle(preview, (sx1, sy1), (sx2, sy2), (220, 20, 220), 2)
                cv2.putText(preview, f"BUBBLE:{role}", (sx1 + 4, sy1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 20, 220), 1)

        # Blend semi-transparent annotations
        cv2.addWeighted(overlay, 0.25, preview, 0.75, 0, preview)

        # 3. Candidate Cut Lines
        selected_set = set(selected_cuts)
        for c in candidates:
            sy = int(round(c.y * scale))
            if not (0 <= sy < disp_h):
                continue

            if c.y in selected_set:
                # Handled in GREEN step below
                continue

            if not c.is_safe:
                # RED: Rejected / unsafe candidate
                cv2.line(preview, (0, sy), (disp_w, sy), (0, 0, 255), 2)
                lbl = f"REJECTED Y={c.y} ({c.rejection_reason})"
                cv2.putText(preview, lbl, (10, max(15, sy - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1)
            else:
                # YELLOW: Candidate boundary (valid but not selected in global DP)
                cv2.line(preview, (0, sy), (disp_w, sy), (0, 255, 255), 1)
                lbl = f"CAND Y={c.y} s={c.score:.2f} ({c.candidate_type})"
                cv2.putText(preview, lbl, (10, max(15, sy - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 220, 220), 1)

        # 4. GREEN: Final selected boundaries
        for idx, cut_y in enumerate(sorted(selected_cuts), start=1):
            sy = int(round(cut_y * scale))
            if not (0 <= sy < disp_h):
                continue
            cv2.line(preview, (0, sy), (disp_w, sy), (0, 255, 0), 3)
            lbl = f"SELECTED CUT #{idx} Y={cut_y}"
            cv2.putText(preview, lbl, (disp_w - 240, max(20, sy - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 0), 2)

        return preview

    @classmethod
    def save_debug_output(
        cls,
        output_dir: str,
        prefix: str,
        canvas_bgr: np.ndarray,
        candidates: List[BoundaryCandidate],
        selected_cuts: List[int],
        character_boxes: Optional[List[Tuple[int, int, int, int]]] = None,
        speech_bubbles: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, str]:
        """
        Saves debug overlay image and decision logs to output_dir.
        Returns dictionary of saved file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        img_path = os.path.join(output_dir, f"{prefix}_smart_paging_debug.jpg")
        json_path = os.path.join(output_dir, f"{prefix}_decision_log.json")
        txt_path = os.path.join(output_dir, f"{prefix}_decision_log.txt")

        # 1. Overlay image
        overlay = cls.generate_debug_overlay(
            canvas_bgr=canvas_bgr,
            candidates=candidates,
            selected_cuts=selected_cuts,
            character_boxes=character_boxes,
            speech_bubbles=speech_bubbles
        )
        cv2.imwrite(img_path, overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])

        # 2. Decision log
        log_data = cls.generate_decision_log(candidates, selected_cuts)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(log_data["log_text"])

        return {
            "debug_overlay_image": img_path,
            "decision_log_json": json_path,
            "decision_log_txt": txt_path
        }
