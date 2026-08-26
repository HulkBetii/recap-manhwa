from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import psutil


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    create_time: float
    command_hash: str

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ProcessIdentity":
        return cls(
            pid=int(value["pid"]),
            create_time=float(value["create_time"]),
            command_hash=str(value["command_hash"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {"pid": self.pid, "create_time": self.create_time, "command_hash": self.command_hash}


def command_hash(argv: Sequence[str]) -> str:
    normalized = json.dumps([str(item) for item in argv], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def popen_command(argv: Sequence[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    flags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(
        [str(item) for item in argv],
        cwd=str(cwd),
        env=env,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=start_new_session,
    )


def identity_for_process(process: subprocess.Popen[bytes], argv: Sequence[str]) -> ProcessIdentity:
    return ProcessIdentity(
        pid=process.pid,
        create_time=psutil.Process(process.pid).create_time(),
        command_hash=command_hash(argv),
    )


def process_matches(identity: ProcessIdentity) -> bool:
    try:
        process = psutil.Process(identity.pid)
        if abs(process.create_time() - identity.create_time) > 0.01:
            return False
        return command_hash(process.cmdline()) == identity.command_hash
    except (psutil.Error, OSError, ValueError):
        return False


def terminate_process_tree(identity: ProcessIdentity, *, grace_seconds: float = 15.0) -> bool:
    if not process_matches(identity):
        return False
    process = psutil.Process(identity.pid)
    targets = process.children(recursive=True) + [process]
    if os.name == "nt":
        try:
            os.kill(identity.pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        except OSError:
            pass
    else:
        try:
            os.killpg(identity.pid, signal.SIGINT)
        except OSError:
            pass
    _, alive = psutil.wait_procs(targets, timeout=max(0.0, grace_seconds))
    for target in reversed(alive):
        try:
            target.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(alive, timeout=3.0)
    for target in alive:
        try:
            target.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=3.0)
    return not psutil.pid_exists(identity.pid)
