"""Field encryption at rest (AES-256-GCM).

Stored form: "v<key version>:<base64url(nonce + ciphertext + tag)>". The version picks the key, so keys can
rotate: the current key encrypts, older keys listed in APP_ENCRYPTION_KEYS_OLD still decrypt.
"""
from __future__ import annotations

import base64
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings

TOKEN = re.compile(r"^v(\d+):([A-Za-z0-9_\-=]+)$")


class CryptoError(ValueError):
    pass


def _key(raw: str) -> bytes:
    key = base64.urlsafe_b64decode(raw.strip())
    if len(key) != 32:
        raise CryptoError("Encryption keys must be 32 bytes, base64 encoded.")
    return key


def _keys() -> dict[int, bytes]:
    keys = {}
    for entry in settings.encryption_keys_old:
        version, _, raw = entry.partition("=")
        keys[int(version.lstrip("v"))] = _key(raw)
    keys[settings.encryption_key_version] = _key(settings.encryption_key)
    return keys


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and TOKEN.match(value) is not None


def encrypt(plain: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_key(settings.encryption_key)).encrypt(nonce, plain.encode(), None)
    return f"v{settings.encryption_key_version}:" + base64.urlsafe_b64encode(nonce + sealed).decode()


def decrypt(token: str) -> str:
    match = TOKEN.match(token)
    if not match:
        raise CryptoError("Value is not encrypted.")
    key = _keys().get(int(match.group(1)))
    if key is None:
        raise CryptoError(f"No key for version {match.group(1)}.")
    blob = base64.urlsafe_b64decode(match.group(2))
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], None).decode()
    except Exception as exc:  # cryptography raises InvalidTag; never leak details
        raise CryptoError("Encrypted value could not be read.") from exc
