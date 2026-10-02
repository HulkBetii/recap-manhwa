# -*- coding: utf-8 -*-
"""
GEMINI API ENGINE (9ROUTER COMPATIBLE)
High-performance, async client for Google Gemini VLM API through 9router and direct OpenAI/Gemini gateways.
Supports:
1. Base64 PDF and Image payload attachments
2. Multi-key rotation with automatic failover on 429 (Rate Limit) / Quota limits
3. Auto-detection for both Google Gemini format (/v1beta/models/...:generateContent) and OpenAI format (/v1/chat/completions)
4. Robust retry policies with exponential backoff
"""

import os
import re
import json
import base64
import asyncio
import logging
from typing import Optional, List, Any, Tuple, Union
import httpx

logger = logging.getLogger("GeminiApiEngine")


def _read_file_base64(file_path: str) -> Optional[Tuple[str, str]]:
    """Đọc file và trả về (mime_type, base64_data)."""
    if not file_path or not os.path.exists(file_path):
        return None
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    mime_type = mime_map.get(ext, "application/octet-stream")
    try:
        with open(file_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
        return mime_type, b64_data
    except Exception as e:
        logger.error(f"Lỗi đọc file {file_path} sang base64: {e}")
        return None


class GeminiApiEngine:
    """
    Async Engine tương tác với Gemini API qua 9router (hoặc OpenAI/Gemini compatible proxy).
    """

    _key_index: int = 0
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(
        self,
        base_url: Optional[str] = None,
        ninerouter_url: Optional[str] = None,
        api_keys: Optional[Union[List[str], str]] = None,
        default_model: str = "ag/gemini-3.8-flash-high",
        timeout: int = 180,
    ):
        self.base_url = (base_url or ninerouter_url or os.getenv("NINEROUTER_URL") or os.getenv("GEMINI_API_BASE_URL") or "https://api.9router.com/v1").strip().rstrip("/")
        self.api_keys = self._parse_keys(api_keys)
        self.default_model = default_model or os.getenv("GEMINI_MODEL") or "ag/gemini-3.8-flash-high"
        self.timeout = timeout

    @classmethod
    def _parse_keys(cls, keys: Optional[Union[List[str], str]]) -> List[str]:
        """Chuẩn hóa danh sách API Keys từ string, list hoặc biến môi trường."""
        if keys is None:
            raw = (
                os.getenv("NINEROUTER_API_KEYS")
                or os.getenv("NINEROUTER_API_KEY")
                or os.getenv("GEMINI_API_KEYS")
                or os.getenv("GEMINI_API_KEY")
                or ""
            )
        elif isinstance(keys, list):
            raw = ",".join(str(k) for k in keys)
        else:
            raw = str(keys)

        # Split by comma, newline, semicolon, whitespace
        cleaned = []
        for part in re.split(r"[\r\n,;\s]+", raw):
            k = part.strip()
            if k and k not in cleaned:
                cleaned.append(k)
        return cleaned

    def get_current_key(self) -> str:
        """Lấy API Key hiện tại trong vòng xoay."""
        if not self.api_keys:
            return ""
        return self.api_keys[GeminiApiEngine._key_index % len(self.api_keys)]

    def get_active_api_key(self) -> str:
        """Alias cho get_current_key."""
        return self.get_current_key()

    def rotate_key_sync(self) -> str:
        """Chuyển sang API Key tiếp theo (đồng bộ)."""
        if not self.api_keys:
            return ""
        GeminiApiEngine._key_index = (GeminiApiEngine._key_index + 1) % len(self.api_keys)
        return self.api_keys[GeminiApiEngine._key_index]

    async def rotate_key(self, context_logger: Optional[Any] = None) -> str:
        """Chuyển sang API Key tiếp theo khi gặp rate limit hoặc lỗi quota."""
        async with GeminiApiEngine._lock:
            if not self.api_keys:
                return ""
            GeminiApiEngine._key_index = (GeminiApiEngine._key_index + 1) % len(self.api_keys)
            next_k = self.api_keys[GeminiApiEngine._key_index]
            masked = next_k[:6] + "..." + next_k[-4:] if len(next_k) > 10 else "***"
            msg = f"[9router] Đã xoay vòng sang API Key {GeminiApiEngine._key_index + 1}/{len(self.api_keys)} ({masked})"
            logger.info(msg)
            if context_logger and hasattr(context_logger, "log"):
                try:
                    await context_logger.log(msg, "warning")
                except Exception:
                    pass
            return next_k

    async def generate_content(
        self,
        prompt: str,
        pdf_path: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 8192,
        timeout: Optional[int] = None,
        context_logger: Optional[Any] = None,
    ) -> Tuple[str, str]:
        """
        Gửi prompt (kèm PDF hoặc danh sách ảnh) tới 9router Gemini API.
        Tự động thử Google Gemini native protocol hoặc OpenAI protocol.
        Hỗ trợ xoay vòng API Keys nếu gặp Rate Limit (429) hoặc lỗi quota.
        """
        model_name = (model or self.default_model).strip()
        req_timeout = timeout or self.timeout
        keys_count = max(1, len(self.api_keys))
        max_attempts = max(3, keys_count * 2)

        last_error = "Không xác định"

        # Đọc dữ liệu PDF nếu có
        pdf_attachment = None
        if pdf_path and os.path.exists(pdf_path):
            pdf_attachment = _read_file_base64(pdf_path)

        # Đọc danh sách ảnh đính kèm nếu có
        image_attachments = []
        if image_paths:
            for ip in image_paths:
                if os.path.exists(ip):
                    att = _read_file_base64(ip)
                    if att:
                        image_attachments.append(att)

        for attempt in range(1, max_attempts + 1):
            current_key = self.get_current_key()
            if not current_key:
                raise ValueError("Chưa cấu hình API Key cho 9router / Gemini API. Vui lòng nhập API Key trong phần Cấu hình.")

            masked_key = current_key[:6] + "..." + current_key[-4:] if len(current_key) > 10 else "***"
            if context_logger and hasattr(context_logger, "log"):
                try:
                    await context_logger.log(
                        f"[9router API] Đang gửi yêu cầu tới model '{model_name}' (Key: {masked_key}, lần thử {attempt}/{max_attempts})...",
                        "info",
                    )
                except Exception:
                    pass

            prefer_openai = model_name.startswith("ag/") or self.base_url.endswith("/v1")
            try:
                if prefer_openai:
                    try:
                        response_text = await self._call_openai_format(
                            prompt=prompt,
                            pdf_attachment=pdf_attachment,
                            image_attachments=image_attachments,
                            model=model_name,
                            api_key=current_key,
                            temperature=temperature,
                            max_output_tokens=max_output_tokens,
                            timeout=req_timeout,
                        )
                        if response_text and response_text.strip():
                            return response_text.strip(), model_name
                    except httpx.HTTPStatusError as oai_http_err:
                        if oai_http_err.response.status_code in (404, 405):
                            logger.info("[9router] OpenAI endpoint trả về 404/405, thử chuyển sang Gemini Native format...")
                            response_text = await self._call_gemini_native(
                                prompt=prompt,
                                pdf_attachment=pdf_attachment,
                                image_attachments=image_attachments,
                                model=model_name,
                                api_key=current_key,
                                temperature=temperature,
                                max_output_tokens=max_output_tokens,
                                timeout=req_timeout,
                            )
                            if response_text and response_text.strip():
                                return response_text.strip(), model_name
                        else:
                            raise oai_http_err
                else:
                    try:
                        response_text = await self._call_gemini_native(
                            prompt=prompt,
                            pdf_attachment=pdf_attachment,
                            image_attachments=image_attachments,
                            model=model_name,
                            api_key=current_key,
                            temperature=temperature,
                            max_output_tokens=max_output_tokens,
                            timeout=req_timeout,
                        )
                        if response_text and response_text.strip():
                            return response_text.strip(), model_name
                    except httpx.HTTPStatusError as gem_http_err:
                        if gem_http_err.response.status_code in (404, 405):
                            logger.info("[9router] Native endpoint trả về 404/405, thử chuyển sang OpenAI format...")
                            response_text = await self._call_openai_format(
                                prompt=prompt,
                                pdf_attachment=pdf_attachment,
                                image_attachments=image_attachments,
                                model=model_name,
                                api_key=current_key,
                                temperature=temperature,
                                max_output_tokens=max_output_tokens,
                                timeout=req_timeout,
                            )
                            if response_text and response_text.strip():
                                return response_text.strip(), model_name
                        else:
                            raise gem_http_err

            except httpx.HTTPStatusError as http_err:
                status_code = http_err.response.status_code
                error_body = http_err.response.text
                logger.warning(f"[9router HTTP {status_code}] {error_body}")

                # Xử lý Rate Limit (429) hoặc Quota limit (403/429/503)
                if status_code in (429, 403, 503) or "quota" in error_body.lower() or "rate" in error_body.lower():
                    last_error = f"HTTP {status_code}: {error_body}"
                    await self.rotate_key(context_logger=context_logger)
                    await asyncio.sleep(min(2.0 * attempt, 6.0))
                    continue
                else:
                    last_error = f"HTTP {status_code}: {error_body}"
                    await asyncio.sleep(1.5)

            except httpx.RequestError as req_err:
                last_error = f"Lỗi kết nối mạng: {req_err}"
                logger.warning(f"[9router Connection Error] {req_err}")
                await asyncio.sleep(2.0)

            except Exception as e:
                last_error = str(e)
                logger.warning(f"[9router General Error] {e}")
                err_lower = str(e).lower()
                if "rate limit" in err_lower or "429" in err_lower or "quota" in err_lower:
                    await self.rotate_key(context_logger=context_logger)
                await asyncio.sleep(1.5)

        raise RuntimeError(f"Không thể nhận phản hồi từ 9router sau {max_attempts} lần thử. Lỗi cuối: {last_error}")

    async def generate_recap_1turn(
        self,
        prompt: str,
        pdf_path: Optional[str] = None,
        model: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: Optional[int] = None,
        context_logger: Optional[Any] = None,
    ) -> str:
        """Sinh kịch bản recap 1 lượt duy nhất qua Gemini API."""
        m = model_name or model or self.default_model
        text, _ = await self.generate_content(
            prompt=prompt,
            pdf_path=pdf_path,
            model=m,
            timeout=timeout,
            context_logger=context_logger,
        )
        return text

    async def _call_gemini_native(
        self,
        prompt: str,
        pdf_attachment: Optional[Tuple[str, str]],
        image_attachments: List[Tuple[str, str]],
        model: str,
        api_key: str,
        temperature: float,
        max_output_tokens: int,
        timeout: int,
    ) -> str:
        """Gọi theo chuẩn Google Gemini API /v1beta/models/{model}:generateContent."""
        # Chuẩn hóa base URL
        clean_base = self.base_url
        if clean_base.endswith("/v1"):
            clean_base = clean_base[:-3]
        if not clean_base.endswith("/v1beta") and "/v1" not in clean_base:
            endpoint_url = f"{clean_base}/v1beta/models/{model}:generateContent"
        elif clean_base.endswith("/v1beta"):
            endpoint_url = f"{clean_base}/models/{model}:generateContent"
        else:
            endpoint_url = f"{clean_base}/models/{model}:generateContent"

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "Authorization": f"Bearer {api_key}",
        }

        # Xây dựng parts: đính kèm PDF hoặc ảnh trước, sau đó là text prompt
        parts = []
        if pdf_attachment:
            mime_type, b64_data = pdf_attachment
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": b64_data
                }
            })

        for img_mime, img_b64 in image_attachments:
            parts.append({
                "inline_data": {
                    "mime_type": img_mime,
                    "data": img_b64
                }
            })

        parts.append({"text": prompt})

        payload = {
            "contents": [
                {
                    "parts": parts
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            }
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint_url, json=payload, headers=headers)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                raise ValueError(f"Không thể giải mã JSON từ Gemini Native API (HTTP {resp.status_code}): {resp.text[:300]}")

            # Parse Gemini native response format
            candidates = data.get("candidates", [])
            if not candidates:
                # Check for promptFeedback block
                feedback = data.get("promptFeedback", {})
                block_reason = feedback.get("blockReason")
                if block_reason:
                    raise ValueError(f"Gemini API chặn nội dung: {block_reason}")
                raise ValueError("Gemini API trả về candidates rỗng.")

            first_cand = candidates[0]
            content = first_cand.get("content", {})
            cand_parts = content.get("parts", [])
            text_chunks = [p.get("text", "") for p in cand_parts if "text" in p]
            return "".join(text_chunks).strip()

    async def _call_openai_format(
        self,
        prompt: str,
        pdf_attachment: Optional[Tuple[str, str]],
        image_attachments: List[Tuple[str, str]],
        model: str,
        api_key: str,
        temperature: float,
        max_output_tokens: int,
        timeout: int,
    ) -> str:
        """Gọi theo chuẩn OpenAI Chat Completions /v1/chat/completions."""
        clean_base = self.base_url
        if not clean_base.endswith("/chat/completions"):
            if clean_base.endswith("/v1"):
                endpoint_url = f"{clean_base}/chat/completions"
            else:
                endpoint_url = f"{clean_base}/v1/chat/completions"
        else:
            endpoint_url = clean_base

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        content_parts = [{"type": "text", "text": prompt}]

        if pdf_attachment:
            mime_type, b64_data = pdf_attachment
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{b64_data}"
                }
            })

        for img_mime, img_b64 in image_attachments:
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img_mime};base64,{img_b64}"
                }
            })

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": content_parts
                }
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint_url, json=payload, headers=headers)
            resp.raise_for_status()

            # Hỗ trợ tự động parse nếu proxy trả về Server-Sent Events stream (data: {...})
            resp_text = resp.text.strip()
            if resp_text.startswith("data:") or "data: {" in resp_text:
                full_content = []
                for line in resp_text.splitlines():
                    line = line.strip()
                    if line.startswith("data:"):
                        data_part = line[5:].strip()
                        if data_part == "[DONE]":
                            break
                        if data_part:
                            try:
                                chunk_json = json.loads(data_part)
                                choices = chunk_json.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    delta_content = delta.get("content", "")
                                    if delta_content:
                                        full_content.append(delta_content)
                                    msg = choices[0].get("message", {})
                                    if msg.get("content"):
                                        full_content.append(msg.get("content"))
                            except Exception:
                                pass
                if full_content:
                    return "".join(full_content).strip()

            try:
                data = resp.json()
            except Exception:
                raise ValueError(f"Không thể giải mã phản hồi JSON từ 9router (HTTP {resp.status_code}): {resp.text[:300]}")

            choices = data.get("choices", [])
            if not choices:
                raise ValueError(f"OpenAI endpoint trả về choices rỗng: {data}")

            msg = choices[0].get("message", {})
            return msg.get("content", "").strip()

    async def test_connection(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Kiểm tra kết nối và tính khả dụng của API Key và Model."""
        test_url = (base_url or self.base_url).strip().rstrip("/")
        test_key = (api_key or self.get_current_key()).strip()
        test_model = (model or self.default_model).strip()

        if not test_key:
            return False, "Chưa cung cấp API Key để kiểm tra."

        temp_engine = GeminiApiEngine(base_url=test_url, api_keys=[test_key], default_model=test_model, timeout=30)
        try:
            res, _ = await temp_engine.generate_content(
                prompt="Say 'OK 9router Connected' in 3 words.",
                model=test_model,
                timeout=30,
            )
            return True, f"Kết nối 9router thành công! Phản hồi từ {test_model}: {res[:100]}"
        except Exception as e:
            return False, f"Kiểm tra kết nối thất bại: {e}"


# Singleton helper instance
_gemini_api_engine_instance: Optional[GeminiApiEngine] = None


def get_gemini_api_engine(
    base_url: Optional[str] = None,
    ninerouter_url: Optional[str] = None,
    api_keys: Optional[Union[List[str], str]] = None,
    api_key: Optional[str] = None,
    default_model: Optional[str] = None,
    timeout: int = 180,
    reload: bool = False,
    **kwargs
) -> GeminiApiEngine:
    """Lấy singleton hoặc tạo mới GeminiApiEngine với tham số tùy chọn."""
    global _gemini_api_engine_instance

    effective_url = base_url or ninerouter_url
    effective_keys = api_key if api_key is not None else api_keys

    # Khi có truyền tham số tùy chỉnh cụ thể, tạo instance mới tương ứng
    if effective_url is not None or effective_keys is not None or default_model is not None:
        try:
            from app import load_config
            cfg = load_config()
        except Exception:
            cfg = {}
        final_url = effective_url or cfg.get("ninerouter_url") or os.getenv("NINEROUTER_URL") or "https://api.9router.com/v1"
        final_keys = effective_keys if effective_keys is not None else (
            cfg.get("ninerouter_api_key")
            or cfg.get("ninerouter_api_keys")
            or os.getenv("NINEROUTER_API_KEY")
            or os.getenv("NINEROUTER_API_KEYS")
            or ""
        )
        final_model = default_model or cfg.get("ninerouter_model") or cfg.get("gemini_model") or os.getenv("GEMINI_MODEL") or "ag/gemini-3.8-flash-high"
        return GeminiApiEngine(
            base_url=final_url,
            api_keys=final_keys,
            default_model=final_model,
            timeout=timeout,
        )

    if _gemini_api_engine_instance is None or reload:
        try:
            from app import load_config
            cfg = load_config()
        except Exception:
            cfg = {}
        base_url = cfg.get("ninerouter_url") or os.getenv("NINEROUTER_URL") or "https://api.9router.com/v1"
        api_keys = (
            cfg.get("ninerouter_api_key")
            or cfg.get("ninerouter_api_keys")
            or os.getenv("NINEROUTER_API_KEY")
            or os.getenv("NINEROUTER_API_KEYS")
            or ""
        )
        model = cfg.get("ninerouter_model") or cfg.get("gemini_model") or os.getenv("GEMINI_MODEL") or "ag/gemini-3.8-flash-high"
        _gemini_api_engine_instance = GeminiApiEngine(
            base_url=base_url,
            api_keys=api_keys,
            default_model=model,
            timeout=timeout,
        )
    return _gemini_api_engine_instance
