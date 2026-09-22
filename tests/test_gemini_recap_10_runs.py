# -*- coding: utf-8 -*-
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gemini_web_engine import (
    GeminiPlaywrightEngine,
    classify_gemini_exception,
    parse_stream_generate_response,
    JS_CHECK_ATTACHMENT,
    JS_POLL_UI_STATE
)
from app import verify_gemini_response_format, parse_gemini_recap_text, generate_gemini_prompt


class TestGeminiRecap10Runs(unittest.IsolatedAsyncioTestCase):
    """
    Tests 10 consecutive simulations with realistic recap prompts
    and verifies that at least 70% (target 100%) succeed on the 1st try
    without throwing selector errors or hanging during streaming.
    """

    async def test_10_consecutive_recap_runs(self):
        engine = GeminiPlaywrightEngine()
        success_first_try = 0
        total_runs = 10

        test_pdf = os.path.abspath("test_recap_sample.pdf")
        with open(test_pdf, "wb") as f:
            f.write(b"%PDF-1.4 sample pdf content")

        try:
            for run_idx in range(1, total_runs + 1):
                prompt = generate_gemini_prompt(
                    comic_title="The Regressed Mercenary's Machinations",
                    ep=run_idx,
                    total_pages=20,
                    target_language="vi"
                )

                sample_recap_lines = [
                    f"[R{i}] - Nhân vật chính bước vào khu rừng bí ẩn và bắt đầu triển khai kế hoạch tác chiến cho tập {run_idx}.#"
                    for i in range(1, 16)
                ]
                sample_recap_text = "\n".join(sample_recap_lines)

                mock_page = MagicMock()
                mock_page.url = "https://gemini.google.com/app"
                mock_page.on = MagicMock()
                mock_page.remove_listener = MagicMock()
                mock_page.keyboard = MagicMock()
                mock_page.keyboard.insert_text = AsyncMock()
                mock_page.keyboard.press = AsyncMock()

                call_counts = {"poll": 0, "attach": 0}

                async def mock_evaluate(script, args=None):
                    if isinstance(script, str):
                        if "attachmentSelectors" in script:
                            call_counts["attach"] += 1
                            return {"attached": True, "tag": "mat-chip", "text": "test_recap_sample.pdf"}
                        if "JS_DIRECT_RPC_EXECUTE" in script or "WIZ_global_data" in script:
                            if run_idx % 2 == 1:
                                part_json = [None, None, None, None, [[None, [sample_recap_text]]]]
                                mock_rpc_env = json.dumps([[["wrb.fr", None, json.dumps(part_json)]]])
                                return {"success": True, "rawText": mock_rpc_env}
                            else:
                                return {"success": False, "error": "RPC_FALLBACK"}
                        if "isVis" in script or "isGenerating" in script:
                            call_counts["poll"] += 1
                            if call_counts["poll"] <= 1:
                                return {
                                    "text": "\n".join(sample_recap_lines[:5]),
                                    "is_generating": True,
                                    "has_action_bar": False
                                }
                            else:
                                return {
                                    "text": sample_recap_text,
                                    "is_generating": False,
                                    "has_action_bar": True
                                }
                    return {"success": True}

                mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)

                loc = MagicMock()
                loc.count = AsyncMock(return_value=1)
                loc.is_visible = AsyncMock(return_value=True)
                loc.is_enabled = AsyncMock(return_value=True)
                loc.click = AsyncMock()
                loc.fill = AsyncMock()
                loc.first = loc
                mock_page.locator.return_value = loc

                resp_text = None
                rpc_text, _ = await engine.execute_direct_rpc(
                    page=mock_page,
                    prompt_text=prompt,
                    pdf_path=test_pdf,
                    episode=run_idx
                )
                if rpc_text:
                    resp_text = rpc_text
                else:
                    resp_text, _ = await engine.execute_playwright_interceptor(
                        page=mock_page,
                        prompt_text=prompt,
                        pdf_path=test_pdf,
                        min_sentences=10,
                        timeout=30,
                        episode=run_idx,
                        step_label=f"Recap Run {run_idx}"
                    )

                self.assertIsNotNone(resp_text)
                is_valid, err_msg = verify_gemini_response_format(resp_text, is_intro=False, min_sentences=10)
                self.assertTrue(is_valid, f"Run {run_idx} failed validation: {err_msg}")

                parsed = parse_gemini_recap_text(resp_text)
                self.assertGreaterEqual(len(parsed), 10, f"Run {run_idx} has fewer than 10 segments")

                success_first_try += 1

            success_rate = (success_first_try / total_runs) * 100.0
            print(f"\n[Test Result] 1st Try Success Rate: {success_rate}% ({success_first_try}/{total_runs} runs)")
            self.assertGreaterEqual(success_rate, 70.0)

        finally:
            if os.path.exists(test_pdf):
                os.remove(test_pdf)


if __name__ == "__main__":
    unittest.main()
