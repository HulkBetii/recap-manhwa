# -*- coding: utf-8 -*-
"""
Unit tests for GeminiWebEngine (Direct In-Browser RPC + Playwright Interceptor)
"""

import json
import unittest
from gemini_web_engine import (
    parse_stream_generate_response,
    classify_gemini_exception,
    GeminiRateLimitException,
    GeminiSafetyBlockException,
    GeminiAuthExpiredException,
    GeminiServerErrorException,
    GeminiStreamHangException
)

class TestGeminiWebEngine(unittest.TestCase):

    def test_parse_stream_generate_response(self):
        # Mock Google StreamGenerate response envelope
        inner_cand = [
            "rc_123",
            ["[{\"speech\": \"Nhân vật chính bước vào hang động...\", \"images\": [1]}], [{\"speech\": \"Anh ấy nhìn thấy quái vật...\", \"images\": [2]}]"],
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            [["Deep thinking notes here"]]
        ]
        body_json = [None, None, None, None, [inner_cand]]
        envelope = [["wrb.fr", None, json.dumps(body_json)]]
        raw_mock = ")]}'\n123\n" + json.dumps(envelope)

        text, thoughts, err = parse_stream_generate_response(raw_mock)
        self.assertIsNotNone(text)
        self.assertIn("Nhân vật chính", text)
        self.assertIn("quái vật", text)
        self.assertEqual(thoughts, "Deep thinking notes here")
        self.assertIsNone(err)

    def test_classify_rate_limit_exception(self):
        exc = classify_gemini_exception("You've reached your limit for Gemini 3.0 Flash. Please try again tomorrow.")
        self.assertIsInstance(exc, GeminiRateLimitException)

        exc_vi = classify_gemini_exception("Tài khoản của bạn đã đạt giới hạn sử dụng mô hình. Vui lòng chờ.")
        self.assertIsInstance(exc_vi, GeminiRateLimitException)

    def test_classify_safety_block_exception(self):
        exc = classify_gemini_exception("I cannot help with this image as it violates our safety guidelines.")
        self.assertIsInstance(exc, GeminiSafetyBlockException)

        exc_vi = classify_gemini_exception("Tôi không thể hỗ trợ tạo kịch bản do nội dung nhạy cảm.")
        self.assertIsInstance(exc_vi, GeminiSafetyBlockException)

    def test_classify_server_error(self):
        exc = classify_gemini_exception("Something went wrong on our end. Please try again.")
        self.assertIsInstance(exc, GeminiServerErrorException)

    def test_classify_auth_expired(self):
        exc = classify_gemini_exception("Sign in to continue using Gemini")
        self.assertIsInstance(exc, GeminiAuthExpiredException)

    def test_js_prompt_injection_constants(self):
        from gemini_web_engine import JS_INJECT_PROMPT_TEXT, JS_GET_TEXTBOX_TEXT, JS_TRIGGER_SUBMIT
        self.assertIn("rich-textarea", JS_INJECT_PROMPT_TEXT)
        self.assertIn("execCommand", JS_INJECT_PROMPT_TEXT)
        self.assertIn("DataTransfer", JS_INJECT_PROMPT_TEXT)
        self.assertIn("rich-textarea", JS_GET_TEXTBOX_TEXT)
        self.assertIn("clicked", JS_TRIGGER_SUBMIT)

if __name__ == "__main__":
    unittest.main()

