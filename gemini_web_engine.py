# -*- coding: utf-8 -*-
"""
GEMINI WEB ENGINE (DUAL-ENGINE: DIRECT IN-BROWSER RPC + PLAYWRIGHT STREAM INTERCEPTOR)
Provides rock-solid, ultra-fast, and exception-safe Gemini VLM script generation.
Designed to minimize errors, detect & handle all web exceptions, and eliminate UI flakiness.
"""

import asyncio
import base64
import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("GeminiWebEngine")


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM EXCEPTIONS FOR GRANULAR ERROR HANDLING & AUTO-RECOVERY
# ─────────────────────────────────────────────────────────────────────────────

class GeminiWebException(Exception):
    """Base exception for Gemini Web Automation."""
    def __init__(self, message: str, error_type: str = "unknown", can_retry_web: bool = True, can_retry_tool: bool = True):
        super().__init__(message)
        self.error_type = error_type
        self.can_retry_web = can_retry_web
        self.can_retry_tool = can_retry_tool


class GeminiRateLimitException(GeminiWebException):
    """Raised when Gemini quota/rate limit is hit (Error 1037 / Limit modal / Disabled model)."""
    def __init__(self, message: str):
        super().__init__(message, error_type="rate_limit", can_retry_web=False, can_retry_tool=True)


class GeminiSafetyBlockException(GeminiWebException):
    """Raised when Gemini safety guardrails reject content (NSFW / Safety Policy)."""
    def __init__(self, message: str):
        super().__init__(message, error_type="safety_block", can_retry_web=False, can_retry_tool=True)


class GeminiAuthExpiredException(GeminiWebException):
    """Raised when Google login is expired or not authenticated."""
    def __init__(self, message: str):
        super().__init__(message, error_type="auth_expired", can_retry_web=False, can_retry_tool=True)


class GeminiStreamHangException(GeminiWebException):
    """Raised when generation stream hangs without new tokens."""
    def __init__(self, message: str):
        super().__init__(message, error_type="stream_hang", can_retry_web=True, can_retry_tool=True)


class GeminiServerErrorException(GeminiWebException):
    """Raised when Gemini backend fails (Temporary error 1013 / 500 / Something went wrong)."""
    def __init__(self, message: str):
        super().__init__(message, error_type="server_error", can_retry_web=True, can_retry_tool=True)


# ─────────────────────────────────────────────────────────────────────────────
# STREAMGENERATE RPC PARSER & EXCEPTION CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

def extract_nested_value(data: Any, path: List[int], default: Any = None) -> Any:
    """Safely traverses nested lists/arrays."""
    cur = data
    for idx in path:
        if not isinstance(cur, (list, tuple)) or idx < 0 or idx >= len(cur):
            return default
        cur = cur[idx]
    return cur if cur is not None else default


def parse_stream_generate_response(raw_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parses Google StreamGenerate / batchexecute response text.
    Returns: (response_text, thoughts, error_message)
    """
    if not raw_text:
        return None, None, "Empty response text"

    lines = raw_text.splitlines()
    last_valid_text = None
    last_thoughts = None
    error_message = None

    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith(")]}'"):
            continue
        try:
            parsed = json.loads(line_s)
            if not isinstance(parsed, list):
                continue
            
            # Check for error code in envelope
            err_code = extract_nested_value(parsed, [0, 5, 2, 0, 1, 0])
            if err_code == 1037:
                error_message = "RATE_LIMIT_1037: Usage limit of model exceeded"
            elif err_code == 1013:
                error_message = "TEMPORARY_ERROR_1013: Temporary backend error"
            elif err_code == 1060:
                error_message = "IP_BLOCKED_1060: IP temporarily blocked"

            # Flatten/Unwrap outer envelope lists if deeply nested
            envelope = parsed
            while isinstance(envelope, list) and len(envelope) > 0 and isinstance(envelope[0], list) and len(envelope[0]) > 0 and isinstance(envelope[0][0], list):
                envelope = envelope[0]

            for part in envelope:
                if not isinstance(part, list) or len(part) < 3:
                    continue
                part_body_str = part[2]
                if not isinstance(part_body_str, str):
                    continue
                try:
                    part_json = json.loads(part_body_str)
                    if not isinstance(part_json, list):
                        continue
                    candidates = extract_nested_value(part_json, [4], [])
                    if isinstance(candidates, list) and len(candidates) > 0:
                        cand = candidates[0]
                        if isinstance(cand, list):
                            cand_text = extract_nested_value(cand, [1, 0])
                            if isinstance(cand_text, str) and cand_text.startswith("http://googleusercontent.com/card_content/"):
                                cand_text = extract_nested_value(cand, [22, 0], cand_text)
                            if cand_text and isinstance(cand_text, str):
                                last_valid_text = cand_text
                            
                            thoughts = extract_nested_value(cand, [37, 0, 0])
                            if thoughts and isinstance(thoughts, str):
                                last_thoughts = thoughts
                except Exception:
                    pass
        except Exception:
            pass

    return last_valid_text, last_thoughts, error_message


def classify_gemini_exception(text: str, page_content: str = "") -> Optional[GeminiWebException]:
    """
    Analyzes response text or page content to classify known Gemini errors accurately.
    """
    combined = (text + " " + page_content).lower()

    # 1. Rate limit / Quota reached
    if any(k in combined for k in [
        "rate limit", "usage limit", "you've reached your limit", "đã đạt giới hạn",
        "hạn mức của bạn", "tạm thời hết lượt", "try again later", "resets tomorrow",
        "1037", "rate_limit_1037", "model is currently overloaded"
    ]):
        return GeminiRateLimitException("Gemini Rate Limit / Quota Exceeded (1037). Cần xoay vòng profile.")

    # 2. Safety / NSFW block
    if any(k in combined for k in [
        "i cannot help with this", "i can't help with that", "i'm unable to help",
        "tôi không thể hỗ trợ", "không thể tạo kịch bản cho nội dung", "chính sách an toàn",
        "safety guidelines", "sensitive content", "violates our terms", "inappropriate content"
    ]):
        return GeminiSafetyBlockException("Gemini Safety Guardrail Block (NSFW / Policy). Cần bật Safe Mode DINO+SAM.")

    # 3. Auth expired
    if any(k in combined for k in [
        "sign in to continue", "đăng nhập để tiếp tục", "phiên đăng nhập đã hết hạn",
        "session expired", "auth_token_not_found"
    ]):
        return GeminiAuthExpiredException("Google Auth / Session Expired. Cần đăng nhập lại.")

    # 4. Server error
    if any(k in combined for k in [
        "something went wrong", "đã xảy ra lỗi", "temporary_error_1013",
        "internal server error", "500 internal", "try again in a moment"
    ]):
        return GeminiServerErrorException("Gemini Backend Temporary Error (1013 / 500). Có thể thử lại (Redo).")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# JAVASCRIPT SNIPPETS FOR DIRECT IN-BROWSER RPC & DOM AUTOMATION
# ─────────────────────────────────────────────────────────────────────────────

JS_DIRECT_RPC_EXECUTE = """
async (args) => {
    const { promptText, base64Pdf, fileName, modelName } = args;
    
    // 1. Get SNlM0e token
    let snlm0e = window.WIZ_global_data?.SNlM0e;
    if (!snlm0e) {
        const html = document.documentElement.innerHTML;
        const m = html.match(/\"SNlM0e\":\"(.*?)\"/);
        if (m) snlm0e = m[1];
    }
    if (!snlm0e) {
        return { success: false, error: "AUTH_TOKEN_NOT_FOUND: Could not locate SNlM0e token on Gemini page." };
    }
    
    // 2. Upload file to Content Push API
    let uploadedFileRef = null;
    if (base64Pdf && fileName) {
        try {
            const byteCharacters = atob(base64Pdf);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], { type: "application/pdf" });
            
            const form = new FormData();
            form.append("file", blob, fileName);
            
            const uploadRes = await fetch("https://content-push.googleapis.com/upload", {
                method: "POST",
                headers: {
                    "Push-ID": "feeds/mcudyrk2a4khkz"
                },
                body: form
            });
            
            if (!uploadRes.ok) {
                return { success: false, error: `UPLOAD_FAILED: Upload returned status ${uploadRes.status}` };
            }
            const pushResponse = await uploadRes.text();
            uploadedFileRef = [[pushResponse], fileName];
        } catch (uErr) {
            return { success: false, error: `UPLOAD_EXCEPTION: ${uErr.message || uErr}` };
        }
    }
    
    // 3. Build StreamGenerate Payload
    const firstPart = uploadedFileRef ? [promptText, 0, null, [uploadedFileRef]] : [promptText];
    const inner = [firstPart, null, null];
    const fReq = JSON.stringify([null, JSON.stringify(inner)]);
    
    const bodyParams = new URLSearchParams();
    bodyParams.append("at", snlm0e);
    bodyParams.append("f.req", fReq);
    
    const headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "X-Same-Domain": "1"
    };
    
    const mLow = (modelName || "flash").toLowerCase();
    if (mLow.includes("pro")) {
        headers["x-goog-ext-525001261-jspb"] = '[1,null,null,null,"9d8ca3786ebdfbea",null,null,0,[4],null,null,1]';
    } else if (mLow.includes("thinking")) {
        headers["x-goog-ext-525001261-jspb"] = '[1,null,null,null,"5bf011840784117a",null,null,0,[4],null,null,1]';
    } else {
        headers["x-goog-ext-525001261-jspb"] = '[1,null,null,null,"fbb127bbb056c959",null,null,0,[4],null,null,1]';
    }
    
    try {
        const genRes = await fetch("https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate", {
            method: "POST",
            headers: headers,
            body: bodyParams.toString()
        });
        
        if (!genRes.ok) {
            return { success: false, error: `GENERATE_RPC_FAILED: HTTP ${genRes.status} ${genRes.statusText}` };
        }
        
        const rawText = await genRes.text();
        return {
            success: true,
            status: genRes.status,
            rawText: rawText
        };
    } catch (gErr) {
        return { success: false, error: `RPC_NETWORK_ERROR: ${gErr.message || gErr}` };
    }
}
"""

JS_PASTE_PDF = """
async (args) => {
    const { base64Data, fileName, mimeType } = args;
    let element = document.querySelector("rich-textarea div[contenteditable='true'], rich-textarea p, div.ql-editor, div[contenteditable='true'], [role='textbox']");
    if (!element) return { success: false, error: "Không tìm thấy ô nhập prompt để đính kèm tệp." };
    
    element.focus();
    const res = await fetch("data:" + mimeType + ";base64," + base64Data);
    const blob = await res.blob();
    const file = new File([blob], fileName, { type: mimeType });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    const pasteEvent = new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dataTransfer });
    element.dispatchEvent(pasteEvent);
    
    const rich = element.closest('rich-textarea');
    if (rich && rich !== element) {
        rich.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dataTransfer }));
    }
    return { success: true };
}
"""

JS_CHECK_ATTACHMENT = """
() => {
    try {
        const attachmentSelectors = [
            "mat-chip",
            "mat-chip-row",
            ".attachment-preview",
            "[data-test-id='file-preview']",
            "file-preview",
            "file-attachment",
            "uploader-file-item",
            ".file-chip",
            ".attachment-chip",
            "rich-textarea-file-preview",
            "input-area-v2 [role='row']",
            "button[aria-label*='Remove' i]",
            "button[aria-label*='Xóa tệp' i]",
            "button[aria-label*='Dismiss' i]"
        ];
        for (const sel of attachmentSelectors) {
            try {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    if (el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0)) {
                        return { attached: true, tag: sel, text: (el.innerText || el.textContent || "").trim() };
                    }
                }
            } catch (e) {}
        }

        const inputArea = document.querySelector("input-area-v2, rich-textarea, form");
        if (inputArea) {
            const els = inputArea.querySelectorAll("div, span, p");
            for (const el of els) {
                const t = (el.innerText || el.textContent || "").toLowerCase();
                if (t.includes(".pdf") || t.includes("pdf")) {
                    if (el.offsetWidth > 0 || el.offsetHeight > 0) {
                        return { attached: true, tag: "text-match", text: t };
                    }
                }
            }
        }
    } catch (e) {}
    return { attached: false };
}
"""

JS_POLL_UI_STATE = """
() => {
    const isVis = (el) => {
        if (!el) return false;
        try {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 || rect.height > 0 || el.offsetWidth > 0 || el.offsetHeight > 0;
        } catch (e) {
            return el.offsetParent !== null;
        }
    };

    // 1. Check stop / cancel button
    const stopSelectors = [
        "button[aria-label*='Stop' i]",
        "button[aria-label*='Dừng' i]",
        "button[aria-label*='Cancel' i]",
        "button[aria-label*='Hủy' i]",
        "gem-icon-button[aria-label*='Stop' i]",
        "gem-icon-button[aria-label*='Dừng' i]",
        "button.stop-generating-button",
        ".stop-button",
        ".stop-icon"
    ];
    let isGenerating = false;
    for (const sel of stopSelectors) {
        try {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                if (isVis(el)) {
                    isGenerating = true;
                    break;
                }
            }
        } catch (e) {}
        if (isGenerating) break;
    }

    // 2. Check streaming indicator
    if (!isGenerating) {
        const streamSelectors = [
            "[class*='streaming']",
            "[class*='generating']",
            "[class*='typing']",
            ".blinking-cursor",
            ".cursor",
            "gem-streaming-indicator",
            "sparkle-icon.animate-spin",
            "[data-is-generating='true']",
            "[data-is-streaming='true']",
            "input-area-v2 [role='progressbar']",
            "form [role='progressbar']"
        ];
        for (const sel of streamSelectors) {
            try {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    if (isVis(el)) {
                        isGenerating = true;
                        break;
                    }
                }
            } catch (e) {}
            if (isGenerating) break;
        }
    }

    // Check thinking spinner
    if (!isGenerating) {
        try {
            const thinkEls = document.querySelectorAll(".thinking-container, [data-testid='thinking-indicator'], thinking-bubble");
            for (const te of thinkEls) {
                if (isVis(te)) {
                    const sp = te.querySelector("mat-spinner, [role='progressbar'], svg.animate-spin");
                    if (sp && isVis(sp)) {
                        isGenerating = true;
                        break;
                    }
                }
            }
        } catch (e) {}
    }

    // 3. Clean Text Extractor
    const getCleanText = (el) => {
        if (!el) return "";
        try {
            const clone = el.cloneNode(true);
            clone.querySelectorAll(
                "sources-carousel, citation-tag, source-chip, grounding-citation, " +
                "grounding-tag, grounding-popover, .grounding-container, a.citation-chip, " +
                "span.citation, [class*='citation'], [class*='grounding'], [class*='source-chip'], " +
                "[data-test-id*='citation'], [data-test-id*='grounding'], message-actions, " +
                ".message-actions, [data-testid='message-actions'], .response-bottom-actions, " +
                "button, [role='button'], thinking-bubble, .thinking-container, " +
                "[data-testid='thinking-indicator'], mat-expansion-panel-header"
            ).forEach(c => c.remove());

            clone.querySelectorAll("br").forEach(br => br.replaceWith("\\n"));
            
            const blocks = clone.querySelectorAll("p, li, tr, h1, h2, h3, h4, h5, h6");
            if (blocks.length > 0) {
                const lines = [];
                blocks.forEach(b => {
                    const t = (b.innerText || b.textContent || "").trim();
                    if (t) lines.push(t);
                });
                if (lines.length > 0) return lines.join("\\n");
            }
            return (clone.innerText || clone.textContent || "").trim();
        } catch (e) {
            return (el.innerText || el.textContent || "").trim();
        }
    };

    // 4. Find latest model response
    const modelResponses = document.querySelectorAll("model-response, [data-test-id='model-response'], .model-response, response-container");
    let targetEl = null;
    if (modelResponses.length > 0) {
        targetEl = modelResponses[modelResponses.length - 1];
    }
    if (!targetEl) {
        const respSelectors = [
            ".response-content-markdown",
            "message-content",
            "structured-content-container",
            "div.markdown",
            "div.prose"
        ];
        for (const sel of respSelectors) {
            try {
                const els = document.querySelectorAll(sel);
                for (let i = els.length - 1; i >= 0; i--) {
                    const el = els[i];
                    if (!el.closest("user-query, user-message, [data-test-id='user-query'], .user-query-container, .query-text")) {
                        targetEl = el;
                        break;
                    }
                }
            } catch (e) {}
            if (targetEl) break;
        }
    }

    let text = "";
    let hasActionBar = false;
    if (targetEl) {
        text = getCleanText(targetEl);
        try {
            const actEl = targetEl.querySelector("message-actions, .message-actions, [data-testid='message-actions'], .response-bottom-actions, button[aria-label*='Copy' i], button[aria-label*='Sao chép' i], button[aria-label*='Good response' i]");
            if (actEl && isVis(actEl)) {
                hasActionBar = true;
            }
        } catch (e) {}
    }

    // Auto scroll down to keep rendering active
    try {
        window.scrollTo(0, document.body.scrollHeight);
    } catch (e) {}

    return {
        text: text,
        is_generating: isGenerating,
        has_action_bar: hasActionBar
    };
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI PLAYWRIGHT & DIRECT ENGINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class GeminiPlaywrightEngine:
    """
    High-level orchestrator providing dual-engine Gemini execution:
    Engine 1: Direct in-browser RPC (Zero UI delay, ~3-8s).
    Engine 2: Network-intercepted Playwright DOM automation with smart retries.
    """

    def __init__(self, context_logger: Optional[Any] = None):
        self.context = context_logger

    async def _log(self, message: str, level: str = "info", stage_name: str = "Stage 5 - Gemini Automation", episode: Optional[int] = None):
        if self.context and hasattr(self.context, "log"):
            await self.context.log(message, level, stage_name=stage_name, episode=episode)
        else:
            logger.info(f"[{level.upper()}] {message}")

    async def execute_direct_rpc(
        self,
        page: Any,
        prompt_text: str,
        pdf_path: Optional[str] = None,
        model_name: str = "flash",
        episode: Optional[int] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Attempts direct in-browser RPC invocation.
        Returns: (response_text, thoughts) if successful, or (None, None) if fallback needed.
        """
        b64_pdf = None
        file_name = None
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pf:
                b64_pdf = base64.b64encode(pf.read()).decode("utf-8")
            file_name = os.path.basename(pdf_path)

        await self._log(f"Tập {episode}: [Engine 1 - Direct RPC] Đang gửi yêu cầu trực tiếp qua API nội bộ Gemini...", "info", episode=episode)
        try:
            res = await asyncio.wait_for(
                page.evaluate(JS_DIRECT_RPC_EXECUTE, {
                    "promptText": prompt_text,
                    "base64Pdf": b64_pdf,
                    "fileName": file_name,
                    "modelName": model_name
                }),
                timeout=120.0
            )

            if isinstance(res, dict) and res.get("success"):
                raw_text = res.get("rawText", "")
                text, thoughts, err = parse_stream_generate_response(raw_text)
                if err:
                    exc = classify_gemini_exception(err)
                    if exc:
                        raise exc
                if text:
                    await self._log(f"Tập {episode}: [Engine 1 - Direct RPC] Nhận phản hồi thành công ({len(text)} ký tự)!", "success", episode=episode)
                    return text, thoughts

            err_msg = res.get("error", "Unknown RPC failure") if isinstance(res, dict) else str(res)
            await self._log(f"Tập {episode}: [Engine 1 - Direct RPC] Không khả dụng ({err_msg}). Chuyển sang Engine 2 (Playwright Interceptor)...", "info", episode=episode)
            return None, None

        except GeminiWebException:
            raise
        except Exception as e:
            await self._log(f"Tập {episode}: [Engine 1 - Direct RPC] Lỗi: {e}. Chuyển sang Engine 2...", "warning", episode=episode)
            return None, None

    async def execute_playwright_interceptor(
        self,
        page: Any,
        prompt_text: str,
        pdf_path: Optional[str] = None,
        model_name: str = "flash",
        is_intro: bool = False,
        min_sentences: int = 1,
        timeout: int = 120,
        episode: Optional[int] = None,
        step_label: str = "Recap"
    ) -> Tuple[str, str]:
        """
        Executes prompt via Playwright with Network Response Stream Interception and DOM fallback.
        """
        # 1. Setup Network Response Stream Interceptor
        intercepted_text = {"content": None, "thoughts": None, "error": None}
        response_completed_event = asyncio.Event()

        async def on_response(response):
            url = response.url or ""
            if "assistant.lamda.BardFrontendService/StreamGenerate" in url or "BardChatUi/data/batchexecute" in url:
                try:
                    if response.status == 200:
                        body_text = await response.text()
                        txt, th, err = parse_stream_generate_response(body_text)
                        if txt:
                            intercepted_text["content"] = txt
                            intercepted_text["thoughts"] = th
                        if err:
                            intercepted_text["error"] = err
                        response_completed_event.set()
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            # 2. Attach PDF if present
            if pdf_path and os.path.exists(pdf_path):
                file_name = os.path.basename(pdf_path)
                await self._log(f"Tập {episode}: [Engine 2] Đính kèm file PDF [{file_name}]...", "info", episode=episode)
                with open(pdf_path, "rb") as pf:
                    pdf_bytes = pf.read()
                b64_data = base64.b64encode(pdf_bytes).decode("utf-8")

                await page.evaluate(JS_PASTE_PDF, {
                    "base64Data": b64_data,
                    "fileName": file_name,
                    "mimeType": "application/pdf"
                })

                # Verify attachment chip appeared
                attached = False
                for _ in range(30):
                    chk = await page.evaluate(JS_CHECK_ATTACHMENT)
                    if isinstance(chk, dict) and chk.get("attached"):
                        attached = True
                        break
                    await asyncio.sleep(0.2)

                if attached:
                    await self._log(f"Tập {episode}: Đã xác nhận file PDF [{file_name}] được đính kèm vào khung chat.", "success", episode=episode)
                else:
                    await self._log(f"Tập {episode}: Cảnh báo: Badge đính kèm chưa xuất hiện, tiếp tục điền prompt...", "warning", episode=episode)

            # 3. Fill prompt text
            await self._log(f"Tập {episode}: [Engine 2] Đang điền prompt [{step_label}]...", "info", episode=episode)
            textbox = None
            for sel in [
                "rich-textarea p",
                "rich-textarea div[contenteditable='true']",
                "div.ql-editor[contenteditable='true']",
                "div[contenteditable='true']",
                "[role='textbox']"
            ]:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    textbox = loc
                    break

            if textbox:
                try:
                    await textbox.click(force=True)
                    await asyncio.sleep(0.2)
                    await textbox.fill(prompt_text)
                except Exception:
                    await page.keyboard.insert_text(prompt_text)
            else:
                await page.keyboard.insert_text(prompt_text)

            await asyncio.sleep(0.5)

            # 4. Click Send button
            send_btn = None
            for sel in [
                "button[aria-label*='Send' i]",
                "button[aria-label*='Gửi' i]",
                "button.send-button",
                "gem-icon-button[aria-label*='Send' i]",
                "[data-test-id='send-button']"
            ]:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                    send_btn = loc
                    break

            if send_btn:
                await send_btn.click(force=True, timeout=3000)
            else:
                await page.keyboard.press("Enter")

            # 5. Listen for Response (Network Stream + DOM Stability Polling)
            await self._log(f"Tập {episode}: [Engine 2] Đang lắng nghe phản hồi từ Gemini...", "info", episode=episode)
            gen_start = time.time()
            resp_text = ""
            last_len = 0
            last_progress = time.time()
            stable_count = 0
            min_len = 25 if is_intro else 150

            while time.time() - gen_start < timeout:
                # Check if Network Interceptor already caught full response
                if response_completed_event.is_set() and intercepted_text["content"]:
                    resp_text = intercepted_text["content"]
                    await self._log(f"Tập {episode}: [Network Interceptor] Bắt thành công dữ liệu phản hồi nguyên bản ({len(resp_text)} chars)!", "success", episode=episode)
                    break

                if intercepted_text["error"]:
                    exc = classify_gemini_exception(intercepted_text["error"])
                    if exc:
                        raise exc

                # Poll UI DOM state
                ui_state = await page.evaluate(JS_POLL_UI_STATE)
                if not isinstance(ui_state, dict):
                    ui_state = {}
                cur_text = ui_state.get("text", "")
                is_generating = ui_state.get("is_generating", False)
                has_action_bar = ui_state.get("has_action_bar", False)

                # Check safety/rate limit in DOM text
                if cur_text:
                    exc = classify_gemini_exception(cur_text)
                    if exc:
                        raise exc

                # Check timeouts
                if not cur_text and (time.time() - gen_start > 75.0):
                    raise GeminiStreamHangException("Quá 75s không có ký tự phản hồi nào từ Gemini.")

                if is_generating:
                    stable_count = 0
                    if len(cur_text) > last_len:
                        last_progress = time.time()
                        last_len = len(cur_text)
                        resp_text = cur_text
                    elif cur_text and (time.time() - last_progress > 60.0):
                        raise GeminiStreamHangException(f"Stream bị treo quá 60s không có ký tự mới ({len(cur_text)} chars).")
                    await asyncio.sleep(0.8)
                    continue

                # When NOT generating:
                if cur_text:
                    resp_text = cur_text

                if len(resp_text) == last_len and len(resp_text) >= min_len:
                    stable_count += 1
                else:
                    stable_count = 0
                    last_len = len(resp_text)
                    last_progress = time.time()

                # Completion conditions:
                # 1. Action bar is visible and text meets minimum length
                if has_action_bar and len(resp_text) >= min_len and stable_count >= 1:
                    break
                # 2. Text has stabilized for >= 4 cycles (approx 3.2s) without generating indicator
                if stable_count >= 4 and len(resp_text) >= min_len:
                    break

                await asyncio.sleep(0.8)

            return resp_text, intercepted_text.get("thoughts") or ""

        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass
