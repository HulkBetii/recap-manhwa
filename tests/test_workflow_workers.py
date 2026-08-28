import asyncio
import inspect
import json
import os
import sys
import time
from pathlib import Path

import psutil
import pytest

from workflow import EventBus, WorkflowManager
from workflow_base import JSONWorkflowRepository, WorkflowState, WorkflowTask
from worker_protocol import atomic_write_json
from video_worker import public_final_video_url
from workflow_stages_2 import Stage11_FinalVideoAssembly, can_recover_ffmpeg_pipe_output, is_ffmpeg_pipe_closed_error


HELPER = Path(__file__).parent / "helpers" / "workflow_stub_worker.py"


def test_workflow_never_deletes_gemini_activity():
    source = inspect.getsource(WorkflowManager._execute_workflow)
    assert "clear_gemini_activity" not in source
    assert "My Activity" not in source
    assert "time.monotonic() - start_time_seconds" in source
    assert "checkpoint kế tiếp" in source
    assert 'stage.name != "Stage 0 - Project Init"' in source


def test_video_worker_returns_real_output_url():
    assert public_final_video_url("comic_1_1_en_deadbeef") == (
        "/downloads/comic_1_1_en_deadbeef/output/comic_1_1_en_deadbeef.mp4"
    )


def test_ffmpeg_closed_pipe_errors_include_windows_invalid_argument():
    assert is_ffmpeg_pipe_closed_error(BrokenPipeError())
    assert is_ffmpeg_pipe_closed_error(OSError(22, "Invalid argument"))
    assert not is_ffmpeg_pipe_closed_error(OSError(5, "Access denied"))


def test_ffmpeg_closed_pipe_recovery_requires_valid_mp4(monkeypatch, tmp_path):
    output = tmp_path / "video.mp4.tmp.mp4"
    output.write_bytes(b"valid-enough-for-test")
    monkeypatch.setattr("workflow_stages_2.validate_mp4_file", lambda path: Path(path) == output)

    assert can_recover_ffmpeg_pipe_output(OSError(22, "Invalid argument"), str(output))
    assert not can_recover_ffmpeg_pipe_output(OSError(5, "Access denied"), str(output))
    assert not can_recover_ffmpeg_pipe_output(OSError(22, "Invalid argument"), str(tmp_path / "missing.mp4"))


@pytest.mark.asyncio
async def test_final_assembly_always_exports_subtitles(monkeypatch, tmp_path):
    import app as app_module

    episode_dir = tmp_path / "episode_1"
    episode_dir.mkdir()
    (episode_dir / "video.mp4").write_bytes(b"video")
    (episode_dir / "transcript.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nTest\n",
        encoding="utf-8",
    )

    task = WorkflowTask("Comic", "https://example.com/comic", 1, 1, {})
    task.artifacts = {
        "download_dir": str(tmp_path),
        "download_folder_name": "comic_1_1_en_test",
    }

    class Context:
        def __init__(self, workflow_task):
            self.task = workflow_task

        async def log(self, *_args, **_kwargs):
            return None

        async def update_stage_progress(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(app_module, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("workflow_stages_2.get_video_duration", lambda *_args: 1.0)
    assert await Stage11_FinalVideoAssembly().execute(Context(task))

    output_dir = tmp_path / "output"
    assert (output_dir / "comic_1_1_en_test.mp4").is_file()
    assert (output_dir / "comic_1_1_en_test.srt").is_file()
    assert task.artifacts["final_subtitle_url"].endswith("comic_1_1_en_test.srt")


def test_atomic_status_write_retries_windows_file_sharing(monkeypatch, tmp_path):
    destination = tmp_path / "status.json"
    real_replace = os.replace
    attempts = 0

    def flaky_replace(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("destination is temporarily open")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", flaky_replace)
    atomic_write_json(destination, {"status": "running"})
    assert json.loads(destination.read_text(encoding="utf-8")) == {"status": "running"}
    assert attempts == 3


def configure_stub(manager: WorkflowManager) -> None:
    manager._worker_command = lambda task_id: [
        sys.executable,
        str(HELPER),
        "--job-dir",
        str(manager._job_dir(task_id)),
    ]


async def wait_for_status(repository, task_id, statuses, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = repository.load(task_id)
        if task is not None and task.status in statuses:
            return task
        await asyncio.sleep(0.05)
    task = repository.load(task_id)
    raise AssertionError(f"Task did not reach {statuses}; current={getattr(task, 'status', None)}")


async def make_manager(tmp_path, *, grace=0.25):
    repository = JSONWorkflowRepository(str(tmp_path / "tasks.json"))
    manager = WorkflowManager(
        repository,
        EventBus(),
        max_workers=1,
        runtime_root=tmp_path / "runtime",
        cancel_grace_seconds=grace,
    )
    configure_stub(manager)
    manager.start()
    return repository, manager


async def stop_manager(manager):
    await asyncio.wait_for(manager.stop(), timeout=5)


@pytest.mark.asyncio
async def test_subprocess_success_and_progress_propagation(tmp_path):
    repository, manager = await make_manager(tmp_path)
    try:
        task_id = await manager.queue_task("Comic", "https://example.com", 1, 1, {"worker_test_mode": "success"})
        task = await wait_for_status(repository, task_id, {WorkflowState.SUCCESS})
        assert task.overall_progress == 100.0
        assert task.runtime.get("exit_code") == 0
    finally:
        await stop_manager(manager)


@pytest.mark.asyncio
async def test_worker_crash_does_not_stop_queue(tmp_path):
    repository, manager = await make_manager(tmp_path)
    try:
        failed_id = await manager.queue_task("Crash", "https://example.com/a", 1, 1, {"worker_test_mode": "crash"})
        success_id = await manager.queue_task("Success", "https://example.com/b", 1, 1, {"worker_test_mode": "success"})
        failed = await wait_for_status(repository, failed_id, {WorkflowState.FAILED})
        succeeded = await wait_for_status(repository, success_id, {WorkflowState.SUCCESS})
        assert "exited with code 7" in (failed.error_message or "")
        assert succeeded.status == WorkflowState.SUCCESS
    finally:
        await stop_manager(manager)


@pytest.mark.asyncio
async def test_graceful_cancel_uses_cancel_flag(tmp_path):
    repository, manager = await make_manager(tmp_path, grace=1.0)
    try:
        task_id = await manager.queue_task("Cancel", "https://example.com", 1, 1, {"worker_test_mode": "slow_success"})
        await wait_for_status(repository, task_id, {WorkflowState.RUNNING})
        assert await manager.cancel_task(task_id)
        task = await wait_for_status(repository, task_id, {WorkflowState.CANCELLED})
        assert (manager._job_dir(task_id) / "cancel.flag").exists()
        assert task.runtime.get("exit_code") == 2
    finally:
        await stop_manager(manager)


@pytest.mark.asyncio
async def test_forced_cancel_kills_process_tree(tmp_path):
    repository, manager = await make_manager(tmp_path, grace=0.2)
    try:
        task_id = await manager.queue_task("Stubborn", "https://example.com", 1, 1, {"worker_test_mode": "stubborn"})
        await wait_for_status(repository, task_id, {WorkflowState.RUNNING})
        child_path = manager._job_dir(task_id) / "child.pid"
        deadline = time.monotonic() + 5
        while not child_path.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        child_pid = int(child_path.read_text(encoding="utf-8"))
        parent_pid = repository.load(task_id).runtime["pid"]

        assert await manager.cancel_task(task_id)
        await wait_for_status(repository, task_id, {WorkflowState.CANCELLED})
        await asyncio.sleep(0.2)
        assert not psutil.pid_exists(parent_pid)
        assert not psutil.pid_exists(child_pid)
    finally:
        await stop_manager(manager)


@pytest.mark.asyncio
async def test_server_restart_reattaches_to_matching_worker(tmp_path):
    repository, first_manager = await make_manager(tmp_path, grace=0.25)
    task_id = await first_manager.queue_task("Restart", "https://example.com", 1, 1, {"worker_test_mode": "slow_success"})
    await wait_for_status(repository, task_id, {WorkflowState.RUNNING})
    await stop_manager(first_manager)

    second_repository = JSONWorkflowRepository(str(tmp_path / "tasks.json"))
    second_manager = WorkflowManager(
        second_repository,
        EventBus(),
        max_workers=1,
        runtime_root=tmp_path / "runtime",
        cancel_grace_seconds=0.25,
    )
    configure_stub(second_manager)
    second_manager.start()
    try:
        task = await wait_for_status(second_repository, task_id, {WorkflowState.SUCCESS})
        assert task.overall_progress == 100.0
    finally:
        await stop_manager(second_manager)
