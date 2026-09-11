import os
from pathlib import Path


def database_path() -> Path:
    return Path(os.getenv("RECALL_DB", "~/.local/share/recall/recall.db")).expanduser()


def server_url() -> str:
    return os.getenv("RECALL_URL", "http://127.0.0.1:8765")
