from __future__ import annotations

import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent
DOWNLOADS_ROOT = (PROJECT_ROOT / "downloads").resolve()
UPLOADS_ROOT = (PROJECT_ROOT / "static" / "uploads").resolve()
SESSION_COOKIE_NAME = "recap_session"
SESSION_TOKEN = secrets.token_urlsafe(32)
ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
SENSITIVE_PAYLOAD_KEYS = {
    "ai33pro_api_key",
    "api_key",
    "vlm_email",
    "vlm_password",
    "password",
    "token",
}
PUBLIC_ARTIFACT_KEYS = {"final_videos", "final_video_url", "final_subtitle_url"}

_SECRET_PATTERNS = (
    re.compile(r"\bsk_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(xi-api-key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)\b((?:vlm_)?(?:email|password)|token|api[_-]?key)\s*[:=]\s*[^\s,;]+"),
)
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&](?:token|sig|signature|expires|key|credential|policy|x-amz-[^=&#\s]+)=)[^&#\s]+"
)
_URL_QUERY_VALUE = re.compile(r"([?&][^=&#\s]+)=([^&#\s]+)")
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?i)\b[a-z]:[\\/](?:[^\\/:*?\"<>|\r\n]+[\\/])*[^\\/:*?\"<>|\r\n]*"
)


class PathAccessError(ValueError):
    pass


def request_host_allowed(host_header: str) -> bool:
    parsed = urlsplit(f"//{host_header}")
    return (parsed.hostname or "").casefold() in ALLOWED_HOSTNAMES


def same_origin_allowed(origin: str | None, host_header: str) -> bool:
    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.scheme in {"http", "https"} and parsed.netloc.casefold() == host_header.casefold()


def session_token_matches(value: str | None) -> bool:
    return bool(value) and hmac.compare_digest(value, SESSION_TOKEN)


def resolve_download_path(comic_folder: str, *parts: str | int, must_exist: bool = False) -> Path:
    folder = comic_folder.strip()
    if (
        not folder
        or folder in {".", ".."}
        or Path(folder).is_absolute()
        or "/" in folder
        or "\\" in folder
    ):
        raise PathAccessError("comic_folder must be a single relative folder name")

    DOWNLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = (DOWNLOADS_ROOT / folder).joinpath(*(str(part) for part in parts)).resolve()
    try:
        candidate.relative_to(DOWNLOADS_ROOT)
    except ValueError as exc:
        raise PathAccessError("resolved path escapes downloads root") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError(candidate)
    return candidate


def resolve_upload_path(value: str | None, *, must_exist: bool = True) -> Path | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("/uploads/"):
        filename = normalized.removeprefix("/uploads/")
    elif normalized.startswith("static/uploads/"):
        filename = normalized.removeprefix("static/uploads/")
    else:
        raise PathAccessError("asset path must reference static/uploads")
    if not filename or "/" in filename or filename in {".", ".."}:
        raise PathAccessError("asset path must reference one uploaded file")
    candidate = (UPLOADS_ROOT / filename).resolve()
    try:
        candidate.relative_to(UPLOADS_ROOT)
    except ValueError as exc:
        raise PathAccessError("asset path escapes uploads root") from exc
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def upload_reference(path: Path | None) -> str | None:
    if path is None:
        return None
    return f"static/uploads/{path.name}"


def redact_sensitive_text(value: str | None, sensitive_values: Iterable[str] = ()) -> str | None:
    if value is None:
        return None
    redacted = value
    environment_secret = os.getenv("XI_API_KEY", "").strip()
    environment_voice_id = os.getenv("AI33PRO_VOICE_ID", "").strip()
    values = [item for item in (*sensitive_values, environment_secret, environment_voice_id) if item]
    for item in sorted(set(values), key=len, reverse=True):
        redacted = redacted.replace(item, "<redacted>")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "<redacted>", redacted)
    redacted = _SENSITIVE_QUERY_VALUE.sub(lambda match: match.group(1) + "<redacted>", redacted)
    redacted = _WINDOWS_ABSOLUTE_PATH.sub("<path>", redacted)
    return redacted


def redact_url_query_values(value: str | None) -> str | None:
    if value is None:
        return None
    return _URL_QUERY_VALUE.sub(lambda match: match.group(1) + "=<redacted>", value)


class RedactingTextStream:
    def __init__(self, stream: Any):
        self.stream = stream

    def write(self, value: str) -> int:
        safe_value = redact_url_query_values(redact_sensitive_text(value)) or ""
        return self.stream.write(safe_value)

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str | None:
        return getattr(self.stream, "encoding", None)


def strip_sensitive_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_sensitive_fields(child)
            for key, child in value.items()
            if key.casefold() not in SENSITIVE_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [strip_sensitive_fields(child) for child in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def public_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
    return {
        key: strip_sensitive_fields(value)
        for key, value in artifacts.items()
        if key in PUBLIC_ARTIFACT_KEYS
    }
