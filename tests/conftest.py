"""Test-session isolation from the real app state.

Must run before any test imports `app`: app.py builds its task repository from RECAP_TASK_DB at
import time, and TestClient(app) runs the lifespan that starts pipeline workers. Without this, test
runs wrote tasks into the real tasks_db.json and spawned real crawl/LLM/TTS workers for them.
"""
import os
import tempfile

_SESSION_DIR = tempfile.mkdtemp(prefix="recap_tests_")
os.environ["RECAP_TASK_DB"] = os.path.join(_SESSION_DIR, "tasks_db.json")
os.environ["RECAP_DISABLE_WORKERS"] = "1"
