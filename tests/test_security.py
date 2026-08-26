import importlib
import json

import pytest
from fastapi.testclient import TestClient

from security_utils import PathAccessError, RedactingTextStream, redact_sensitive_text, resolve_download_path, resolve_upload_path
from tts_settings import normalize_tts_voice_mode
from workflow_base import JSONWorkflowRepository, WorkflowTask


def test_public_response_does_not_expose_secrets_paths_or_runtime(monkeypatch):
    monkeypatch.setenv("XI_API_KEY", "sk_test_secret_value_123456")
    task = WorkflowTask("Comic", "https://example.com/comic", 1, 1, {
        "status": "running",
        "ai33pro_api_key": "sk_old_secret_value_123456",
        "vlm_password": "password123",
        "logs": [{"message": r"Failed at D:\private\episode with sk_test_secret_value_123456"}],
        "artifacts": {
            "download_dir": r"D:\private\episode",
            "final_video_url": "/downloads/comic/output/final.mp4",
        },
        "runtime": {"pid": 1234, "create_time": 1.0, "command_hash": "hash"},
    })

    public_json = json.dumps(task.to_public_dict())
    assert "sk_test" not in public_json
    assert "password123" not in public_json
    assert "D:\\\\private" not in public_json
    assert '"pid"' not in public_json
    assert "download_dir" not in public_json
    assert "/downloads/comic/output/final.mp4" in public_json


def test_repository_migration_scrubs_legacy_credentials(tmp_path):
    db_path = tmp_path / "tasks_db.json"
    db_path.write_text(json.dumps({
        "task-1": {
            "comic_title": "Comic",
            "comic_url": "https://example.com/comic?title_no=7181",
            "from_episode": 1,
            "to_episode": 1,
            "vlm_email": "old@example.com",
            "vlm_password": "old-password",
            "ai33pro_api_key": "sk_old_secret_value_123456",
            "voice_id": "elevenlabs_legacy_voice",
            "logs": [{"message": "token=secret-token-value"}],
        }
    }), encoding="utf-8")

    repository = JSONWorkflowRepository(str(db_path))
    assert repository.load("task-1") is not None
    persisted = db_path.read_text(encoding="utf-8")
    assert "vlm_email" not in persisted
    assert "vlm_password" not in persisted
    assert "ai33pro_api_key" not in persisted
    assert "old-password" not in persisted
    assert "elevenlabs_legacy_voice" not in persisted
    assert '"voice_id": "ai33pro"' in persisted
    assert "title_no=7181" in persisted


@pytest.mark.parametrize("folder", [r"D:\absolute", "../escape", "a/b", r"a\b", ".", "..", ""])
def test_download_resolver_rejects_unsafe_folder(folder):
    with pytest.raises(PathAccessError):
        resolve_download_path(folder)


@pytest.mark.parametrize("path", [r"D:\asset.png", "../asset.png", "images/logo.png", "/etc/passwd"])
def test_upload_resolver_rejects_non_upload_paths(path):
    with pytest.raises(PathAccessError):
        resolve_upload_path(path, must_exist=False)


def test_api_cookie_host_origin_and_public_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAP_TASK_DB", str(tmp_path / "api_tasks.json"))
    app_module = importlib.import_module("app")
    task = WorkflowTask("Comic", "https://example.com/comic", 1, 1, {
        "status": "success",
        "logs": [{"message": r"Error at D:\secret\file"}],
        "artifacts": {"download_dir": r"D:\secret", "final_video_url": "/downloads/a/final.mp4"},
        "runtime": {"pid": 999},
    })
    app_module.repository.save(task)

    with TestClient(app_module.app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/workflows").status_code == 403
        assert client.get("/", headers={"host": "evil.example"}).status_code == 403
        home = client.get("/")
        assert home.status_code == 200
        assert home.cookies.get("recap_session")
        response = client.get("/api/workflows")
        assert response.status_code == 200
        body = response.text
        assert '"pid"' not in body
        assert "download_dir" not in body
        assert r"D:\secret" not in body
        assert client.post(
            "/api/workflows/retry-all",
            headers={"origin": "http://evil.example"},
        ).status_code == 403
        assert client.post(
            "/api/workflows/retry-all",
            headers={"origin": "http://127.0.0.1"},
        ).status_code == 200


def test_crawl_request_rejects_removed_fields():
    app_module = importlib.import_module("app")
    with pytest.raises(Exception):
        app_module.CrawlRequest.model_validate({
            "url": "https://example.com/comic",
            "from_episode": 1,
            "to_episode": 1,
            "vlm_provider": "chatgpt",
            "vlm_email": "old@example.com",
        })


def test_ai33_voice_is_normalized_to_environment_mode():
    assert normalize_tts_voice_mode("elevenlabs_example") == "ai33pro"
    assert normalize_tts_voice_mode("ai33pro") == "ai33pro"
    assert normalize_tts_voice_mode("female, low pitch") == "female, low pitch"


def test_log_redaction_covers_credentials_signed_urls_and_paths(monkeypatch):
    import io

    monkeypatch.setenv("XI_API_KEY", "sk_test_secret_value_123456")
    monkeypatch.setenv("AI33PRO_VOICE_ID", "elevenlabs_private_voice")
    raw = (
        "password=hunter2 token=secret-value "
        "https://cdn.example/audio?name=private-title&X-Amz-Signature=signed-value&expires=123 "
        r"D:\private\episode sk_test_secret_value_123456 elevenlabs_private_voice"
    )
    redacted = redact_sensitive_text(raw)
    assert "hunter2" not in redacted
    assert "secret-value" not in redacted
    assert "signed-value" not in redacted
    assert "private-title" in redacted
    assert r"D:\private" not in redacted
    assert "sk_test_secret" not in redacted
    assert "elevenlabs_private_voice" not in redacted

    output = io.StringIO()
    stream = RedactingTextStream(output)
    stream.write(raw)
    assert "private-title" not in output.getvalue()
    assert "signed-value" not in output.getvalue()
