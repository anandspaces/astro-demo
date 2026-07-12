"""Encryption for stored provider API keys, so third-party keys are never held in
plaintext at rest. Fernet = AES-128-CBC + HMAC.

The key comes from STARSAGE_SECRET_KEY; if unset it is generated once and persisted
to <project-root>/.starsage_secret (git/docker-ignored) so encrypted values stay
readable across restarts in local/dev use. In production, set STARSAGE_SECRET_KEY
explicitly (see .env.example).
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("starsage.keystore")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
_SECRET_FILE = os.path.join(_ROOT, ".starsage_secret")
_fernet: Fernet | None = None


def _load_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("STARSAGE_SECRET_KEY", "").strip()
    if key:
        # Accept either a real Fernet key or any passphrase (hashed to 32 bytes).
        try:
            _fernet = Fernet(key.encode())
        except (ValueError, TypeError):
            digest = hashlib.sha256(key.encode()).digest()
            _fernet = Fernet(base64.urlsafe_b64encode(digest))
        return _fernet
    # No env key: derive + persist one for local/dev continuity. In a container
    # this file lives only in the writable layer, so it is LOST on every rebuild
    # — taking every stored (encrypted) API key with it. Set STARSAGE_SECRET_KEY.
    log.warning("STARSAGE_SECRET_KEY is not set — falling back to a generated "
                ".starsage_secret. Stored API keys will NOT survive a container "
                "rebuild. Set STARSAGE_SECRET_KEY in any deployed environment.")
    if os.path.exists(_SECRET_FILE):
        with open(_SECRET_FILE, "rb") as f:
            _fernet = Fernet(f.read().strip())
    else:
        gen = Fernet.generate_key()
        with open(_SECRET_FILE, "wb") as f:
            f.write(gen)
        os.chmod(_SECRET_FILE, 0o600)
        _fernet = Fernet(gen)
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    return _load_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str | None:
    if not ciphertext:
        return None
    try:
        return _load_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def mask_secret(plaintext: str) -> str:
    """Safe-to-display hint, e.g. 'sk-a…f9c2'. Never reveals the key."""
    if not plaintext:
        return ""
    if len(plaintext) <= 8:
        return "•" * len(plaintext)
    return f"{plaintext[:4]}…{plaintext[-4:]}"
