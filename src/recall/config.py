import os
from pathlib import Path

def _saved(key: str) -> str:
    if os.getenv(key):
        return os.getenv(key, "")
    try:
        for line in Path("~/.config/recall/config").expanduser().read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
    except FileNotFoundError:
        pass
    return ""


def database_path() -> Path:
    return Path(os.getenv("RECALL_DB", "~/.local/share/recall/recall.db")).expanduser()


def server_url() -> str:
    return _saved("RECALL_URL") or "http://127.0.0.1:8765"

def auth_token() -> str:
    return _saved("RECALL_TOKEN")
