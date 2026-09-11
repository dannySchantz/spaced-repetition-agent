import os
import base64
import hashlib
import secrets
import threading
import time

from fastapi import HTTPException, Request
import jwt

_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}

def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.urlsafe_b64encode(salt + digest).decode()

def login(request: Request, email: str, password: str, website: str = "") -> str:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _lock:
        recent = [x for x in _attempts.get(ip, []) if now - x < 300]
        recent.append(now); _attempts[ip] = recent
    if website or len(recent) > 10:
        raise HTTPException(403 if website else 429, "Login rejected")
    expected_email = os.getenv("RECALL_LOGIN_EMAIL", "").strip().lower()
    stored_hash = os.getenv("RECALL_LOGIN_PASSWORD_HASH", "")
    secret = os.getenv("RECALL_TOKEN", "")
    if not expected_email or not stored_hash or len(secret) < 32:
        raise HTTPException(503, "Login is not configured")
    try:
        raw = base64.urlsafe_b64decode(stored_hash.removeprefix("scrypt$").encode())
        actual = hashlib.scrypt(password.encode(), salt=raw[:16], n=2**14, r=8, p=1)
        valid = secrets.compare_digest(email.strip().lower(), expected_email) and secrets.compare_digest(actual, raw[16:])
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(401, "Invalid credentials")
    return jwt.encode({"sub": expected_email, "exp": int(time.time()) + 86400}, secret, algorithm="HS256")

def valid_session(token: str) -> bool:
    try:
        jwt.decode(token, os.getenv("RECALL_TOKEN", ""), algorithms=["HS256"])
        return True
    except Exception:
        return False
